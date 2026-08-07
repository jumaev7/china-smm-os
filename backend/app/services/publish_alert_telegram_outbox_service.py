"""Enqueue and process durable Telegram deliveries for publish operator alerts."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy import and_, func as sa_func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.publish_alert_telegram import (
    DELIVERY_STATES,
    MESSAGE_KINDS,
    SEVERITY_RANK,
    PublishAlertTelegramDelivery,
    TenantPublishAlertTelegramSettings,
)
from app.models.publish_operator_alert import ALERT_TYPES, PublishOperatorAlert
from app.services.publish_resilience import sanitize_error_message
from app.utils.operator_telegram_chat import (
    escape_html,
    mask_chat_id,
    normalize_allowed_chat_ids,
    safe_plain,
    validate_operator_telegram_chat_id,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

# Telegram API error classes
_TERMINAL_ERROR_RE = re.compile(
    r"chat not found|bot was blocked|bot is not a member|forbidden|"
    r"user is deactivated|chat_id is empty|unauthorized|invalid token|"
    r"wrong bot token|PEER_ID_INVALID",
    re.IGNORECASE,
)
_RETRY_AFTER_RE = re.compile(r"retry after (\d+)", re.IGNORECASE)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_delivery_dedupe_key(
    *,
    alert_id: UUID,
    recipient_chat_id: int,
    channel: str,
    alert_version: int,
    message_kind: str,
) -> str:
    return f"{alert_id}|{recipient_chat_id}|{channel}|{alert_version}|{message_kind}"


def app_base_url() -> str:
    base = (settings.PUBLISH_ALERT_APP_BASE_URL or "https://app.chinasmmos.com").rstrip("/")
    return base


def absolute_action_url(relative: str | None) -> str:
    path = (relative or "/publishing/alerts").strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{app_base_url()}{path}"


def format_alert_telegram_html(
    alert: PublishOperatorAlert,
    *,
    message_kind: str = "alert",
    attempt_number: int | None = None,
    next_retry_at: datetime | None = None,
) -> str:
    """Concise operational HTML message. Escapes all dynamic fields."""
    severity = escape_html((alert.severity or "warning").upper())
    alert_type = escape_html(alert.alert_type or "unknown")
    client = escape_html(safe_plain(alert.company_name, limit=120) or "—")
    platform = escape_html(safe_plain(alert.platform, limit=40) or "—")
    code = escape_html(safe_plain(alert.failure_code, limit=80) or "—")
    detail = escape_html(
        safe_plain(sanitize_error_message(alert.failure_message) or "", limit=240) or "—",
    )
    link = escape_html(absolute_action_url(alert.action_url))

    if message_kind == "recovery":
        header = f"<b>China SMM OS</b> · RECOVERY · {alert_type}"
    elif message_kind == "test":
        header = f"<b>China SMM OS</b> · TEST · {severity}"
    else:
        header = f"<b>China SMM OS</b> · {severity} · {alert_type}"

    lines = [
        header,
        f"Client: {client}",
        f"Platform: {platform}",
        f"Reason: {code}",
        f"Detail: {detail}",
    ]
    if attempt_number is not None:
        lines.append(f"Publish attempt #: {int(attempt_number)}")
    if next_retry_at is not None:
        lines.append(f"Next publish retry: {escape_html(next_retry_at.isoformat())}")
    lines.append(f'<a href="{link}">Open in app</a>')
    return "\n".join(lines)[:3500]


def recipient_authorized(settings_row: TenantPublishAlertTelegramSettings) -> bool:
    if settings_row.recipient_chat_id is None:
        return False
    try:
        allowlist = normalize_allowed_chat_ids(settings_row.allowed_chat_ids or [])
        recipient = int(settings_row.recipient_chat_id)
    except (ValueError, TypeError):
        return False
    if not allowlist:
        return False
    return recipient in allowlist


def passes_filters(settings_row: TenantPublishAlertTelegramSettings, alert: PublishOperatorAlert) -> bool:
    threshold = (settings_row.severity_threshold or "warning").lower()
    alert_rank = SEVERITY_RANK.get((alert.severity or "warning").lower(), 1)
    min_rank = SEVERITY_RANK.get(threshold, 1)
    if alert_rank < min_rank:
        return False
    selected = settings_row.alert_types or []
    if selected and alert.alert_type not in selected:
        return False
    if alert.alert_type == "recovery":
        # Both global and tenant recovery gates required (fail closed).
        if (
            not settings.PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED
            or not settings_row.recovery_messages_enabled
        ):
            return False
    return True


def quiet_hours_delay(settings_row: TenantPublishAlertTelegramSettings, now: datetime | None = None) -> timedelta | None:
    """Return delay until quiet hours end, or None if sending is allowed now."""
    if not settings_row.quiet_hours_enabled:
        return None
    start = settings_row.quiet_hours_start
    end = settings_row.quiet_hours_end
    if start is None or end is None:
        return None
    now = now or _utc_now()
    tz_name = (settings_row.quiet_hours_timezone or "UTC").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    local = now.astimezone(tz)
    local_t = local.timetz().replace(tzinfo=None)

    def _in_quiet(t) -> bool:
        if start <= end:
            return start <= t < end
        return t >= start or t < end

    if not _in_quiet(local_t):
        return None

    end_dt = datetime.combine(local.date(), end, tzinfo=tz)
    if start <= end:
        if local_t >= end:
            end_dt = end_dt + timedelta(days=1)
    else:
        # Quiet wraps midnight: if currently in the evening segment, end is tomorrow.
        if local_t >= start:
            end_dt = end_dt + timedelta(days=1)
    delay = end_dt.astimezone(timezone.utc) - now
    if delay.total_seconds() <= 0:
        return timedelta(minutes=1)
    return delay


def classify_telegram_error(err: str | None) -> tuple[str, bool, int | None]:
    """Return (failure_code, is_terminal, retry_after_seconds)."""
    text = err or "unknown"
    lower = text.lower()
    m = _RETRY_AFTER_RE.search(text)
    retry_after = int(m.group(1)) if m else None
    if "too many requests" in lower or retry_after is not None:
        return "rate_limited", False, retry_after
    if _TERMINAL_ERROR_RE.search(text):
        if "unauthorized" in lower or "invalid token" in lower or "wrong bot token" in lower:
            return "invalid_token", True, None
        if "blocked" in lower:
            return "bot_blocked", True, None
        if "forbidden" in lower or "not a member" in lower:
            return "forbidden", True, None
        if "chat not found" in lower or "peer_id_invalid" in lower:
            return "invalid_chat", True, None
        return "terminal_telegram_error", True, None
    if "timed out" in lower or "timeout" in lower or "temporarily" in lower:
        return "transient_network", False, None
    return "telegram_error", False, None


def compute_backoff_seconds(attempt_number: int, *, retry_after: int | None = None) -> int:
    if retry_after is not None and retry_after > 0:
        return min(
            int(settings.PUBLISH_ALERT_TELEGRAM_RETRY_MAX_SECONDS),
            max(1, retry_after),
        )
    base = max(1, int(settings.PUBLISH_ALERT_TELEGRAM_RETRY_BASE_SECONDS))
    cap = max(base, int(settings.PUBLISH_ALERT_TELEGRAM_RETRY_MAX_SECONDS))
    exp = min(cap, int(base * (2 ** max(0, attempt_number - 1))))
    return exp


class PublishAlertTelegramOutboxService:
    """Enqueue + claim + send Telegram deliveries. Never raises into publishing."""

    # ── Settings ───────────────────────────────────────────────────────────

    @staticmethod
    async def get_settings(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> TenantPublishAlertTelegramSettings | None:
        return await db.scalar(
            select(TenantPublishAlertTelegramSettings).where(
                TenantPublishAlertTelegramSettings.tenant_id == tenant_id,
            ),
        )

    @classmethod
    async def get_or_create_settings(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> TenantPublishAlertTelegramSettings:
        row = await cls.get_settings(db, tenant_id)
        if row:
            return row
        row = TenantPublishAlertTelegramSettings(
            id=uuid4(),
            tenant_id=tenant_id,
            enabled=False,
            severity_threshold="warning",
            allowed_chat_ids=[],
            created_by=actor_id,
            updated_by=actor_id,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            existing = await cls.get_settings(db, tenant_id)
            if existing:
                return existing
            raise
        return row

    @classmethod
    def serialize_settings(
        cls,
        row: TenantPublishAlertTelegramSettings | None,
        *,
        reveal_chat_id: bool,
        global_enabled: bool | None = None,
    ) -> dict[str, Any]:
        global_on = (
            settings.PUBLISH_ALERT_TELEGRAM_ENABLED
            if global_enabled is None
            else global_enabled
        )
        if row is None:
            return {
                "configured": False,
                "enabled": False,
                "global_telegram_enabled": global_on,
                "delivery_effective": False,
                "recipient_chat_id": None,
                "recipient_chat_id_masked": None,
                "recipient_label": None,
                "allowed_chat_ids": [],
                "allowed_chat_ids_masked": [],
                "severity_threshold": "warning",
                "alert_types": None,
                "quiet_hours_enabled": False,
                "quiet_hours_start": None,
                "quiet_hours_end": None,
                "quiet_hours_timezone": None,
                "recovery_messages_enabled": False,
                "updated_at": None,
            }
        allowlist = list(row.allowed_chat_ids or [])
        chat_id = row.recipient_chat_id
        return {
            "configured": True,
            "enabled": bool(row.enabled),
            "global_telegram_enabled": global_on,
            "delivery_effective": bool(
                global_on and row.enabled and recipient_authorized(row),
            ),
            "recipient_chat_id": int(chat_id) if reveal_chat_id and chat_id is not None else None,
            "recipient_chat_id_masked": mask_chat_id(int(chat_id) if chat_id is not None else None),
            "recipient_label": row.recipient_label,
            "allowed_chat_ids": [int(x) for x in allowlist] if reveal_chat_id else [],
            "allowed_chat_ids_masked": [
                mask_chat_id(int(x)) for x in allowlist
            ],
            "severity_threshold": row.severity_threshold,
            "alert_types": list(row.alert_types) if row.alert_types else None,
            "quiet_hours_enabled": bool(row.quiet_hours_enabled),
            "quiet_hours_start": row.quiet_hours_start.isoformat() if row.quiet_hours_start else None,
            "quiet_hours_end": row.quiet_hours_end.isoformat() if row.quiet_hours_end else None,
            "quiet_hours_timezone": row.quiet_hours_timezone,
            "recovery_messages_enabled": bool(row.recovery_messages_enabled),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @classmethod
    async def update_settings(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        actor_id: UUID | None,
        payload: dict[str, Any],
    ) -> TenantPublishAlertTelegramSettings:
        row = await cls.get_or_create_settings(db, tenant_id, actor_id=actor_id)

        if "recipient_chat_id" in payload and payload["recipient_chat_id"] is not None:
            row.recipient_chat_id = validate_operator_telegram_chat_id(payload["recipient_chat_id"])
        elif "recipient_chat_id" in payload and payload["recipient_chat_id"] is None:
            row.recipient_chat_id = None

        if "recipient_label" in payload:
            label = payload["recipient_label"]
            row.recipient_label = safe_plain(label, limit=120) or None if label is not None else None

        if "allowed_chat_ids" in payload:
            row.allowed_chat_ids = normalize_allowed_chat_ids(payload["allowed_chat_ids"])

        # If recipient set but allowlist empty, auto-seed allowlist with recipient (explicit).
        if row.recipient_chat_id is not None:
            allow = normalize_allowed_chat_ids(row.allowed_chat_ids or [])
            if row.recipient_chat_id not in allow:
                # Require allowlist membership: if updating chat id, include it only when
                # caller also provided allowlist containing it, or allowlist was empty→seed.
                if "allowed_chat_ids" not in payload and not allow:
                    row.allowed_chat_ids = [int(row.recipient_chat_id)]
                elif row.recipient_chat_id not in normalize_allowed_chat_ids(row.allowed_chat_ids or []):
                    raise HTTPException(
                        status_code=400,
                        detail="recipient_chat_id must be present on the explicit allowlist",
                    )

        if "enabled" in payload and payload["enabled"] is not None:
            enabled = bool(payload["enabled"])
            if enabled and not recipient_authorized(row):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Cannot enable Telegram delivery without a numeric recipient "
                        "chat ID on the allowlist"
                    ),
                )
            row.enabled = enabled

        if "severity_threshold" in payload and payload["severity_threshold"] is not None:
            thr = str(payload["severity_threshold"]).lower().strip()
            if thr not in SEVERITY_RANK:
                raise HTTPException(status_code=400, detail="Invalid severity_threshold")
            row.severity_threshold = thr

        if "alert_types" in payload:
            types = payload["alert_types"]
            if types is None:
                row.alert_types = None
            else:
                cleaned = []
                for t in types:
                    t = str(t).strip()
                    if t not in ALERT_TYPES:
                        raise HTTPException(status_code=400, detail=f"Invalid alert_type: {t}")
                    cleaned.append(t)
                row.alert_types = cleaned or None

        if "quiet_hours_enabled" in payload and payload["quiet_hours_enabled"] is not None:
            row.quiet_hours_enabled = bool(payload["quiet_hours_enabled"])
        if "quiet_hours_start" in payload:
            row.quiet_hours_start = _parse_time(payload["quiet_hours_start"])
        if "quiet_hours_end" in payload:
            row.quiet_hours_end = _parse_time(payload["quiet_hours_end"])
        if "quiet_hours_timezone" in payload:
            tz = payload["quiet_hours_timezone"]
            if tz:
                try:
                    ZoneInfo(str(tz))
                except Exception as exc:
                    raise HTTPException(status_code=400, detail="Invalid quiet_hours_timezone") from exc
                row.quiet_hours_timezone = str(tz)[:64]
            else:
                row.quiet_hours_timezone = None

        if "recovery_messages_enabled" in payload and payload["recovery_messages_enabled"] is not None:
            row.recovery_messages_enabled = bool(payload["recovery_messages_enabled"])

        row.updated_by = actor_id
        row.updated_at = _utc_now()
        await db.flush()
        # server onupdate/defaults can expire attrs; refresh before sync serialize
        await db.refresh(row)
        return row

    # ── Enqueue ────────────────────────────────────────────────────────────

    @classmethod
    async def enqueue_for_alert(
        cls,
        db: AsyncSession,
        alert: PublishOperatorAlert,
        *,
        message_kind: str | None = None,
    ) -> PublishAlertTelegramDelivery | None:
        """Create a pending outbox row when global + tenant gates pass. Fail closed."""
        try:
            if not settings.PUBLISH_ALERT_TELEGRAM_ENABLED:
                return None
            if alert.tenant_id is None:
                return None
            kind = message_kind or ("recovery" if alert.alert_type == "recovery" else "alert")
            if kind not in MESSAGE_KINDS:
                return None

            cfg = await cls.get_settings(db, alert.tenant_id)
            if cfg is None or not cfg.enabled:
                return None
            if not recipient_authorized(cfg):
                logger.info(
                    "[AlertTgOutbox] skip enqueue — recipient not authorized tenant=%s alert=%s",
                    alert.tenant_id,
                    alert.id,
                )
                return None
            if not passes_filters(cfg, alert):
                return None

            recipient = int(cfg.recipient_chat_id)  # type: ignore[arg-type]
            alert_version = 1
            dedupe = build_delivery_dedupe_key(
                alert_id=alert.id,
                recipient_chat_id=recipient,
                channel="telegram",
                alert_version=alert_version,
                message_kind=kind,
            )
            next_at = _utc_now()
            delay = quiet_hours_delay(cfg)
            if delay is not None:
                next_at = next_at + delay

            snapshot = {
                "severity": alert.severity,
                "alert_type": alert.alert_type,
                "company_name": safe_plain(alert.company_name, limit=120),
                "platform": safe_plain(alert.platform, limit=40),
                "failure_code": safe_plain(alert.failure_code, limit=80),
                "failure_message": safe_plain(
                    sanitize_error_message(alert.failure_message), limit=240,
                ),
                "attempt_number": alert.attempt_number,
                "next_retry_at": alert.next_retry_at.isoformat() if alert.next_retry_at else None,
                "action_url": alert.action_url,
                "message_kind": kind,
            }

            stmt = (
                insert(PublishAlertTelegramDelivery)
                .values(
                    id=uuid4(),
                    tenant_id=alert.tenant_id,
                    alert_id=alert.id,
                    dedupe_key=dedupe,
                    channel="telegram",
                    message_kind=kind,
                    alert_version=alert_version,
                    recipient_chat_id=recipient,
                    recipient_label=cfg.recipient_label,
                    status="pending",
                    attempt_number=0,
                    max_attempts=max(1, int(settings.PUBLISH_ALERT_TELEGRAM_MAX_ATTEMPTS)),
                    next_attempt_at=next_at,
                    payload_snapshot=snapshot,
                )
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(PublishAlertTelegramDelivery.id)
            )
            new_id = (await db.execute(stmt)).scalar_one_or_none()
            await db.flush()
            if new_id is None:
                logger.info(
                    "[AlertTgOutbox] dedupe hit alert=%s recipient=%s kind=%s",
                    alert.id,
                    mask_chat_id(recipient),
                    kind,
                )
                return None
            row = await db.get(PublishAlertTelegramDelivery, new_id)
            logger.info(
                "[AlertTgOutbox] enqueued delivery_id=%s alert=%s kind=%s",
                new_id,
                alert.id,
                kind,
            )
            return row
        except Exception:
            logger.exception(
                "[AlertTgOutbox] enqueue failed alert_id=%s",
                getattr(alert, "id", None),
            )
            return None

    # ── Worker claim / process ─────────────────────────────────────────────

    @staticmethod
    async def claim_batch(
        db: AsyncSession,
        *,
        worker_id: str,
        batch_size: int | None = None,
        lease_seconds: int | None = None,
    ) -> list[PublishAlertTelegramDelivery]:
        if not settings.PUBLISH_ALERT_TELEGRAM_ENABLED:
            return []
        now = _utc_now()
        batch = max(1, int(batch_size or settings.PUBLISH_ALERT_TELEGRAM_WORKER_BATCH_SIZE))
        lease = max(30, int(lease_seconds or settings.PUBLISH_ALERT_TELEGRAM_LEASE_SECONDS))
        eligible = or_(
            and_(
                PublishAlertTelegramDelivery.status.in_(("pending", "retrying")),
                PublishAlertTelegramDelivery.next_attempt_at <= now,
            ),
            and_(
                PublishAlertTelegramDelivery.status == "sending",
                PublishAlertTelegramDelivery.lease_expires_at.is_not(None),
                PublishAlertTelegramDelivery.lease_expires_at < now,
            ),
        )
        rows = list(
            (
                await db.scalars(
                    select(PublishAlertTelegramDelivery)
                    .where(eligible)
                    .order_by(PublishAlertTelegramDelivery.created_at.asc())
                    .limit(batch)
                    .with_for_update(skip_locked=True),
                )
            ).all(),
        )
        lease_until = now + timedelta(seconds=lease)
        claimed: list[PublishAlertTelegramDelivery] = []
        for row in rows:
            row.status = "sending"
            row.lease_owner = worker_id
            row.lease_expires_at = lease_until
            row.attempt_number = int(row.attempt_number or 0) + 1
            row.last_attempt_at = now
            claimed.append(row)
        await db.flush()
        return claimed

    @classmethod
    async def process_delivery(
        cls,
        db: AsyncSession,
        delivery: PublishAlertTelegramDelivery,
        *,
        worker_id: str,
        send_fn=None,
    ) -> str:
        """Send one claimed delivery. Returns final status label."""
        if delivery.lease_owner != worker_id:
            return "lease_mismatch"
        if not settings.PUBLISH_ALERT_TELEGRAM_ENABLED:
            delivery.status = "cancelled"
            delivery.cancelled_at = _utc_now()
            delivery.failure_code = "global_disabled"
            delivery.failure_message = "Global Telegram delivery disabled"
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            await db.flush()
            return "cancelled"

        alert = await db.get(PublishOperatorAlert, delivery.alert_id)
        if alert is None:
            delivery.status = "failed"
            delivery.failure_code = "alert_missing"
            delivery.failure_message = "Alert row missing"
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            await db.flush()
            return "failed"

        cfg = await cls.get_settings(db, delivery.tenant_id)
        if cfg is None or not cfg.enabled or not recipient_authorized(cfg):
            delivery.status = "cancelled"
            delivery.cancelled_at = _utc_now()
            delivery.failure_code = "tenant_disabled"
            delivery.failure_message = "Tenant Telegram recipient disabled or unauthorized"
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            await db.flush()
            return "cancelled"

        # Quiet hours: requeue without burning a terminal failure
        delay = quiet_hours_delay(cfg)
        if delay is not None:
            delivery.status = "pending"
            delivery.next_attempt_at = _utc_now() + delay
            delivery.attempt_number = max(0, int(delivery.attempt_number) - 1)
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            await db.flush()
            return "deferred_quiet_hours"

        text = format_alert_telegram_html(
            alert,
            message_kind=delivery.message_kind,
            attempt_number=alert.attempt_number,
            next_retry_at=alert.next_retry_at,
        )
        sender = send_fn or send_telegram_html_message
        try:
            ok, message_id, err = await sender(int(delivery.recipient_chat_id), text)
        except Exception as exc:
            ok, message_id, err = False, None, str(exc)

        now = _utc_now()
        if ok:
            delivery.status = "delivered"
            delivery.telegram_message_id = message_id
            delivery.delivered_at = now
            delivery.failure_code = None
            delivery.failure_message = None
            delivery.lease_owner = None
            delivery.lease_expires_at = None
            alert.last_delivery_at = now
            alert.last_delivery_channel = "telegram"
            alert.last_delivery_error = None
            await db.flush()
            logger.info(
                "[AlertTgOutbox] delivered id=%s alert=%s msg_id=%s",
                delivery.id,
                delivery.alert_id,
                message_id,
            )
            return "delivered"

        code, terminal, retry_after = classify_telegram_error(err)
        safe_err = sanitize_error_message(err) or code
        delivery.failure_code = code
        delivery.failure_message = safe_err
        delivery.lease_owner = None
        delivery.lease_expires_at = None

        if terminal:
            delivery.status = "failed"
            alert.last_delivery_error = safe_err
            await db.flush()
            logger.warning(
                "[AlertTgOutbox] terminal failure id=%s code=%s",
                delivery.id,
                code,
            )
            return "failed"

        if int(delivery.attempt_number) >= int(delivery.max_attempts):
            delivery.status = "exhausted"
            alert.last_delivery_error = safe_err
            await db.flush()
            return "exhausted"

        backoff = compute_backoff_seconds(delivery.attempt_number, retry_after=retry_after)
        delivery.status = "retrying"
        delivery.next_attempt_at = now + timedelta(seconds=backoff)
        alert.last_delivery_error = safe_err
        await db.flush()
        return "retrying"

    # ── Admin ops ──────────────────────────────────────────────────────────

    @classmethod
    async def list_deliveries(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        reveal_chat_id: bool = False,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        filters = [PublishAlertTelegramDelivery.tenant_id == tenant_id]
        if status:
            if status not in DELIVERY_STATES:
                raise HTTPException(status_code=400, detail="Invalid delivery status")
            filters.append(PublishAlertTelegramDelivery.status == status)
        total_n = int(
            await db.scalar(
                select(sa_func.count()).select_from(PublishAlertTelegramDelivery).where(*filters),
            )
            or 0,
        )
        rows = list(
            (
                await db.scalars(
                    select(PublishAlertTelegramDelivery)
                    .where(*filters)
                    .order_by(PublishAlertTelegramDelivery.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size),
                )
            ).all(),
        )
        return {
            "items": [cls.serialize_delivery(r, reveal_chat_id=reveal_chat_id) for r in rows],
            "total": total_n,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def serialize_delivery(
        row: PublishAlertTelegramDelivery,
        *,
        reveal_chat_id: bool,
    ) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "alert_id": str(row.alert_id),
            "status": row.status,
            "message_kind": row.message_kind,
            "channel": row.channel,
            "alert_version": row.alert_version,
            "recipient_chat_id": int(row.recipient_chat_id) if reveal_chat_id else None,
            "recipient_chat_id_masked": mask_chat_id(int(row.recipient_chat_id)),
            "recipient_label": row.recipient_label,
            "attempt_number": row.attempt_number,
            "max_attempts": row.max_attempts,
            "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            "telegram_message_id": row.telegram_message_id if reveal_chat_id else None,
            "failure_code": row.failure_code,
            "failure_message": sanitize_error_message(row.failure_message),
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @classmethod
    async def cancel_delivery(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        delivery_id: UUID,
        *,
        actor_id: UUID | None,
    ) -> dict[str, Any]:
        row = await db.get(PublishAlertTelegramDelivery, delivery_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Delivery not found")
        if row.status not in ("pending", "retrying", "sending"):
            raise HTTPException(status_code=400, detail=f"Cannot cancel status={row.status}")
        row.status = "cancelled"
        row.cancelled_at = _utc_now()
        row.cancelled_by = actor_id
        row.lease_owner = None
        row.lease_expires_at = None
        await db.flush()
        await db.refresh(row)
        return cls.serialize_delivery(row, reveal_chat_id=True)

    @classmethod
    async def manual_retry(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        delivery_id: UUID,
    ) -> dict[str, Any]:
        row = await db.get(PublishAlertTelegramDelivery, delivery_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Delivery not found")
        if row.status not in ("failed", "exhausted", "cancelled"):
            raise HTTPException(status_code=400, detail=f"Cannot retry status={row.status}")
        if not settings.PUBLISH_ALERT_TELEGRAM_ENABLED:
            raise HTTPException(status_code=400, detail="Global Telegram delivery is disabled")
        if int(row.attempt_number) >= int(row.max_attempts):
            row.max_attempts = int(row.attempt_number) + 1
        row.status = "pending"
        row.next_attempt_at = _utc_now()
        row.failure_code = None
        row.failure_message = None
        row.cancelled_at = None
        row.cancelled_by = None
        row.lease_owner = None
        row.lease_expires_at = None
        await db.flush()
        await db.refresh(row)
        return cls.serialize_delivery(row, reveal_chat_id=True)

    @classmethod
    async def enqueue_test(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        actor_id: UUID | None,
        confirm: bool,
    ) -> dict[str, Any]:
        if not confirm:
            raise HTTPException(status_code=400, detail="confirm=true is required")
        if not settings.PUBLISH_ALERT_TELEGRAM_ENABLED:
            raise HTTPException(
                status_code=400,
                detail="Global PUBLISH_ALERT_TELEGRAM_ENABLED is false — test send refused",
            )
        cfg = await cls.get_settings(db, tenant_id)
        if cfg is None or not cfg.enabled or not recipient_authorized(cfg):
            raise HTTPException(
                status_code=400,
                detail="Tenant Telegram recipient is not enabled/authorized",
            )
        # Create a synthetic alert snapshot without persisting a real ops alert —
        # use a lightweight outbox-only path with a throwaway alert is unwanted.
        # Instead require an existing open alert OR create ephemeral delivery tied
        # to a synthetic UUID is bad for FK. Create a temporary in-app alert marked test.
        now = _utc_now()
        # Use critical severity so tenant severity thresholds do not block the test.
        alert = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=tenant_id,
            dedupe_key=f"test|{uuid4()}",
            alert_type="operator_review",
            state="resolved",
            severity="critical",
            title="Telegram delivery test",
            body="Operator-requested test notification",
            occurrence_count=1,
            first_occurred_at=now,
            latest_occurred_at=now,
            resolved_at=now,
            resolved_by=actor_id,
            resolve_note="telegram_delivery_test",
            resolved_by_system=True,
            action_url="/publishing/alerts",
            company_name="(test)",
            platform="system",
            failure_code="test_notification",
            failure_message="This is a test operator-alert Telegram notification.",
        )
        db.add(alert)
        await db.flush()
        # Bypass alert-type filter for explicit tests: temporarily clear types.
        original_types = cfg.alert_types
        try:
            cfg.alert_types = None
            delivery = await cls.enqueue_for_alert(db, alert, message_kind="test")
        finally:
            cfg.alert_types = original_types
        if delivery is None:
            raise HTTPException(status_code=400, detail="Failed to enqueue test delivery")
        return {
            "enqueued": True,
            "delivery": cls.serialize_delivery(delivery, reveal_chat_id=True),
            "alert_id": str(alert.id),
            "note": "Test delivery enqueued; worker must be enabled to send.",
        }


def _parse_time(value: Any):
    from datetime import time as dt_time

    if value is None or value == "":
        return None
    if isinstance(value, dt_time):
        return value
    s = str(value).strip()
    parts = s.split(":")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid time; use HH:MM")
    try:
        return dt_time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid time; use HH:MM") from exc


async def send_telegram_html_message(
    chat_id: int,
    text: str,
) -> tuple[bool, int | None, str | None]:
    """Send HTML message via shared bot token. Never logs the token."""
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return False, None, "TELEGRAM_BOT_TOKEN is not configured"
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            body = resp.json() if resp.content else {}
            if resp.status_code == 429:
                retry = None
                try:
                    retry = int((body.get("parameters") or {}).get("retry_after") or 0) or None
                except Exception:
                    retry = None
                desc = body.get("description") or "Too Many Requests"
                if retry:
                    return False, None, f"{desc} retry after {retry}"
                return False, None, desc
            if not body.get("ok"):
                desc = body.get("description") or f"HTTP {resp.status_code}"
                # Never return raw body with potential secrets
                return False, None, sanitize_error_message(desc) or "telegram_error"
            result = body.get("result") or {}
            message_id = result.get("message_id")
            return True, int(message_id) if message_id is not None else None, None
    except Exception as exc:
        return False, None, sanitize_error_message(str(exc)) or "telegram_request_failed"
