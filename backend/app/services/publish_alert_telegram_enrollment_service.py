"""Secure Telegram operator-alert recipient self-enrollment.

Mint opaque deep-link tokens (hash-only storage), redeem via private /start,
and require explicit tenant-admin confirmation before writing allowlist settings.
Enrollment never enables delivery and never creates outbox rows.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import math
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.publish_alert_telegram import (
    ENROLLMENT_ACTIVE_STATUSES,
    ENROLLMENT_PURPOSE,
    PublishAlertTelegramEnrollment,
    TenantPublishAlertTelegramSettings,
)
from app.services.publish_alert_telegram_outbox_service import PublishAlertTelegramOutboxService
from app.utils.operator_telegram_chat import mask_chat_id, safe_plain

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

_START_TOKEN_RE = re.compile(
    r"^/start(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$",
    re.IGNORECASE,
)
_TOKEN_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
# Telegram public usernames: 5–32 chars, start with a letter, then alnum/underscore.
_BOT_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

_GENERIC_INVALID_REPLY = (
    "This connection link is invalid or expired. Return to China SMM OS and try again."
)
_SUCCESS_REPLY = (
    "Telegram account detected. Return to China SMM OS and confirm the connection."
)
_BOT_USERNAME_CACHE: dict[str, Any] = {"username": None, "fetched_at": None}
_BOT_USERNAME_CACHE_TTL = timedelta(hours=1)

TTL_MIN_SECONDS = 60
TTL_MAX_SECONDS = 30 * 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_enrollment_token() -> str:
    """Cryptographically random opaque token suitable for Telegram start payload."""
    return secrets.token_urlsafe(32)


def hash_enrollment_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_bot_username(raw: str | None) -> str | None:
    """Return a validated public bot username, or None if invalid."""
    user = (raw or "").strip().lstrip("@")
    if not user or not _BOT_USERNAME_RE.match(user):
        return None
    return user[:64]


def is_valid_bot_username(raw: str | None) -> bool:
    return normalize_bot_username(raw) is not None


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def clamp_enrollment_ttl_seconds(raw: int | None = None) -> int:
    value = int(raw if raw is not None else settings.PUBLISH_ALERT_TELEGRAM_ENROLLMENT_TOKEN_TTL_SECONDS)
    return max(TTL_MIN_SECONDS, min(TTL_MAX_SECONDS, value))


def parse_enrollment_start_payload(text: str | None) -> str | None:
    """Return opaque token from exact `/start <token>` payload, else None.

    Bare `/start` (no token) is not an enrollment command.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    match = _START_TOKEN_RE.match(raw)
    if not match:
        return None
    payload = (match.group(1) or "").strip()
    if not payload:
        return None
    # Telegram may pass only the payload after deep-link; reject multi-word / extras
    if any(ch.isspace() for ch in payload):
        return None
    if not _TOKEN_PAYLOAD_RE.match(payload):
        return None
    return payload


def is_private_user_chat(chat: dict | None, user: dict | None) -> tuple[bool, str | None]:
    """Validate private personal chat suitable for operator recipient enrollment."""
    chat = chat or {}
    user = user or {}
    chat_type = str(chat.get("type") or "")
    if chat_type in ("group", "supergroup", "channel"):
        return False, "not_private_chat"
    if chat_type != "private":
        return False, "unsupported_chat_type"
    if user.get("is_bot") is True:
        return False, "is_bot"
    # Anonymous admin / channel posts impersonating users are not private personal DMs
    if user.get("is_anonymous") is True:
        return False, "anonymous_admin"
    if chat.get("id") is None or user.get("id") is None:
        return False, "unsupported_chat_type"
    # Private chats use positive user IDs; reject negative (group/channel) IDs
    try:
        chat_id = int(chat["id"])
        user_id = int(user["id"])
    except (TypeError, ValueError):
        return False, "unsupported_chat_type"
    if chat_id <= 0 or user_id <= 0:
        return False, "not_private_chat"
    if chat_id != user_id:
        # Personal private chat: chat.id == from.id
        return False, "unsupported_chat_type"
    return True, None


def safe_telegram_display_name(user: dict | None, chat: dict | None = None) -> str | None:
    user = user or {}
    chat = chat or {}
    parts = [
        safe_plain(user.get("first_name"), limit=60),
        safe_plain(user.get("last_name"), limit=60),
    ]
    name = " ".join(p for p in parts if p).strip()
    if name:
        return name[:120]
    title = safe_plain(chat.get("title") or chat.get("first_name"), limit=120)
    return title or None


def safe_telegram_username(user: dict | None) -> str | None:
    raw = safe_plain((user or {}).get("username"), limit=64)
    if not raw:
        return None
    return raw.lstrip("@")[:64] or None


def redact_start_token_for_logs(text: str | None) -> str:
    raw = text or ""
    return re.sub(
        r"(^|\s)(/start(?:@[A-Za-z0-9_]+)?)\s+\S+",
        r"\1\2 <redacted>",
        raw,
        flags=re.IGNORECASE,
    )


class PublishAlertTelegramEnrollmentService:
    """Tenant-admin enrollment minting + webhook redemption + confirmation."""

    @classmethod
    def enrollment_enabled(cls) -> bool:
        return bool(settings.PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED)

    @classmethod
    def max_confirmed_recipients(cls) -> int:
        return max(1, int(settings.PUBLISH_ALERT_TELEGRAM_MAX_CONFIRMED_RECIPIENTS))

    @classmethod
    def ui_poll_interval_seconds(cls) -> float:
        return float(settings.PUBLISH_ALERT_TELEGRAM_ENROLLMENT_POLL_SECONDS)

    @classmethod
    async def resolve_bot_username(cls) -> str | None:
        configured = normalize_bot_username(settings.TELEGRAM_BOT_USERNAME)
        if configured:
            return configured
        if (settings.TELEGRAM_BOT_USERNAME or "").strip():
            logger.warning("Telegram enrollment: configured TELEGRAM_BOT_USERNAME failed format validation")
        cached = normalize_bot_username(_BOT_USERNAME_CACHE.get("username"))
        fetched_at = _BOT_USERNAME_CACHE.get("fetched_at")
        if cached and fetched_at and (_now() - fetched_at) < _BOT_USERNAME_CACHE_TTL:
            return cached
        token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
        if not token:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{TELEGRAM_API}/bot{token}/getMe")
                resp.raise_for_status()
                body = resp.json()
                username = normalize_bot_username(
                    ((body.get("result") or {}).get("username") or "")
                )
                if username:
                    _BOT_USERNAME_CACHE["username"] = username
                    _BOT_USERNAME_CACHE["fetched_at"] = _now()
                    return username
                logger.warning("Telegram enrollment: getMe returned invalid bot username format")
        except Exception as exc:
            logger.warning("Telegram enrollment: getMe failed to resolve bot username — %s", type(exc).__name__)
        return None

    @classmethod
    def build_deep_link(cls, bot_username: str, token: str) -> str:
        user = normalize_bot_username(bot_username)
        if not user:
            raise ValueError("Invalid bot username for deep link")
        if not _TOKEN_PAYLOAD_RE.match(token or ""):
            raise ValueError("Invalid enrollment token for deep link")
        return f"https://t.me/{user}?start={token}"

    @classmethod
    def serialize_enrollment(
        cls,
        row: PublishAlertTelegramEnrollment | None,
        *,
        deep_link: str | None = None,
        raw_token: str | None = None,
    ) -> dict[str, Any]:
        if row is None:
            return {
                "enrollment": None,
                "enrollment_enabled": cls.enrollment_enabled(),
                "max_confirmed_recipients": cls.max_confirmed_recipients(),
                "poll_interval_seconds": cls.ui_poll_interval_seconds(),
                "delivery_still_disabled_note": (
                    "Connecting Telegram does not enable notifications. "
                    "Enable delivery separately after confirmation."
                ),
            }
        payload: dict[str, Any] = {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "status": row.status,
            "purpose": row.purpose,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "consumed_at": row.consumed_at.isoformat() if row.consumed_at else None,
            "telegram_chat_id_masked": row.telegram_chat_id_masked,
            "telegram_display_name": row.telegram_display_name,
            "telegram_username": row.telegram_username,
            "telegram_chat_type": row.telegram_chat_type,
            "bot_username": row.bot_username,
            "rejection_reason_code": row.rejection_reason_code,
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "deep_link": deep_link,
            # raw_token only returned once at creation time
            "start_token": raw_token,
            "enrollment_enabled": cls.enrollment_enabled(),
            "max_confirmed_recipients": cls.max_confirmed_recipients(),
            "poll_interval_seconds": cls.ui_poll_interval_seconds(),
            "delivery_still_disabled_note": (
                "Connecting Telegram does not enable notifications. "
                "Enable delivery separately after confirmation."
            ),
        }
        return payload

    @classmethod
    def serialize_recipient(
        cls,
        row: PublishAlertTelegramEnrollment,
        *,
        reveal_chat_id: bool = False,
    ) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "status": row.status,
            "telegram_chat_id": int(row.telegram_chat_id) if reveal_chat_id and row.telegram_chat_id is not None else None,
            "telegram_chat_id_masked": row.telegram_chat_id_masked or mask_chat_id(row.telegram_chat_id),
            "telegram_display_name": row.telegram_display_name,
            "telegram_username": row.telegram_username,
            "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
            "confirmed_by": str(row.confirmed_by) if row.confirmed_by else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @classmethod
    async def _expire_stale(cls, db: AsyncSession, tenant_id: UUID | None = None) -> None:
        now = _now()
        stmt = (
            update(PublishAlertTelegramEnrollment)
            .where(
                PublishAlertTelegramEnrollment.status.in_(tuple(ENROLLMENT_ACTIVE_STATUSES)),
                PublishAlertTelegramEnrollment.expires_at <= now,
            )
            .values(
                status="expired",
                rejection_reason_code="token_expired",
                updated_at=now,
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(PublishAlertTelegramEnrollment.tenant_id == tenant_id)
        await db.execute(stmt)

    @classmethod
    async def get_active_enrollment(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        creator_id: UUID | None = None,
    ) -> PublishAlertTelegramEnrollment | None:
        await cls._expire_stale(db, tenant_id)
        stmt = select(PublishAlertTelegramEnrollment).where(
            PublishAlertTelegramEnrollment.tenant_id == tenant_id,
            PublishAlertTelegramEnrollment.status.in_(tuple(ENROLLMENT_ACTIVE_STATUSES)),
        )
        if creator_id is not None:
            stmt = stmt.where(PublishAlertTelegramEnrollment.created_by_admin_id == creator_id)
        stmt = stmt.order_by(PublishAlertTelegramEnrollment.created_at.desc()).limit(1)
        return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def revoke_active_for_creator(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        creator_id: UUID,
        actor_id: UUID | None,
        reason: str = "replaced",
    ) -> int:
        now = _now()
        result = await db.execute(
            update(PublishAlertTelegramEnrollment)
            .where(
                PublishAlertTelegramEnrollment.tenant_id == tenant_id,
                PublishAlertTelegramEnrollment.created_by_admin_id == creator_id,
                PublishAlertTelegramEnrollment.status.in_(tuple(ENROLLMENT_ACTIVE_STATUSES)),
            )
            .values(
                status="revoked",
                revoked_at=now,
                revoked_by=actor_id,
                rejection_reason_code=reason,
                updated_at=now,
            )
        )
        return int(result.rowcount or 0)

    @classmethod
    async def create_enrollment(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        actor_id: UUID,
    ) -> dict[str, Any]:
        if not cls.enrollment_enabled():
            raise HTTPException(
                status_code=403,
                detail="Telegram operator enrollment is disabled",
            )
        if actor_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")

        bot_username = await cls.resolve_bot_username()
        if not bot_username:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Bot username is unavailable. Set TELEGRAM_BOT_USERNAME or ensure "
                    "TELEGRAM_BOT_TOKEN can call getMe."
                ),
            )

        await cls.revoke_active_for_creator(
            db,
            tenant_id,
            creator_id=actor_id,
            actor_id=actor_id,
            reason="replaced",
        )

        raw_token = generate_enrollment_token()
        token_hash = hash_enrollment_token(raw_token)
        ttl = clamp_enrollment_ttl_seconds()
        now = _now()
        row = PublishAlertTelegramEnrollment(
            id=uuid4(),
            tenant_id=tenant_id,
            created_by_admin_id=actor_id,
            token_hash=token_hash,
            purpose=ENROLLMENT_PURPOSE,
            status="pending_start",
            expires_at=now + timedelta(seconds=ttl),
            bot_username=bot_username,
        )
        db.add(row)
        await db.flush()
        # server defaults can expire created_at/updated_at; refresh before sync serialize
        await db.refresh(row)

        deep_link = cls.build_deep_link(bot_username, raw_token)
        logger.info(
            "Telegram enrollment created tenant=%s enrollment=%s expires_in=%ss",
            tenant_id,
            row.id,
            ttl,
        )
        return cls.serialize_enrollment(row, deep_link=deep_link, raw_token=raw_token)

    @classmethod
    async def get_status(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> dict[str, Any]:
        await cls._expire_stale(db, tenant_id)
        row = await cls.get_active_enrollment(db, tenant_id, creator_id=actor_id)
        if row is None:
            # Fall back to latest enrollment for this tenant/creator for terminal states
            stmt = select(PublishAlertTelegramEnrollment).where(
                PublishAlertTelegramEnrollment.tenant_id == tenant_id,
            )
            if actor_id is not None:
                stmt = stmt.where(PublishAlertTelegramEnrollment.created_by_admin_id == actor_id)
            stmt = stmt.order_by(PublishAlertTelegramEnrollment.created_at.desc()).limit(1)
            row = (await db.execute(stmt)).scalar_one_or_none()
        deep_link = None
        if row and row.status == "pending_start" and row.bot_username:
            # Token plaintext is not recoverable; UI must use deep_link from create response.
            deep_link = None
        return cls.serialize_enrollment(row, deep_link=deep_link)

    @classmethod
    async def revoke_enrollment(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        enrollment_id: UUID,
        *,
        actor_id: UUID,
    ) -> dict[str, Any]:
        row = await db.get(PublishAlertTelegramEnrollment, enrollment_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Enrollment not found")
        if row.status not in ENROLLMENT_ACTIVE_STATUSES:
            return cls.serialize_enrollment(row)
        now = _now()
        row.status = "revoked"
        row.revoked_at = now
        row.revoked_by = actor_id
        row.rejection_reason_code = "token_revoked"
        row.updated_at = now
        await db.flush()
        await db.refresh(row)
        return cls.serialize_enrollment(row)

    @classmethod
    async def reject_candidate(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        enrollment_id: UUID,
        *,
        actor_id: UUID,
    ) -> dict[str, Any]:
        row = await db.get(PublishAlertTelegramEnrollment, enrollment_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Enrollment not found")
        if row.status == "rejected":
            return cls.serialize_enrollment(row)
        if row.status != "candidate_received":
            raise HTTPException(
                status_code=400,
                detail="Only a received candidate can be rejected",
            )
        now = _now()
        row.status = "rejected"
        row.rejected_at = now
        row.rejected_by = actor_id
        row.rejection_reason_code = "user_rejected"
        # Clear internal IDs so a rejected candidate cannot be reused
        row.telegram_user_id = None
        row.telegram_chat_id = None
        row.updated_at = now
        await db.flush()
        await db.refresh(row)
        return cls.serialize_enrollment(row)

    @classmethod
    async def confirm_candidate(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        enrollment_id: UUID,
        *,
        actor_id: UUID,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        row = await db.get(PublishAlertTelegramEnrollment, enrollment_id)
        if row is None or row.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Enrollment not found")

        # Idempotent: already confirmed
        if row.status == "confirmed":
            return {
                "enrollment": cls.serialize_enrollment(row),
                "settings": PublishAlertTelegramOutboxService.serialize_settings(
                    await PublishAlertTelegramOutboxService.get_settings(db, tenant_id),
                    reveal_chat_id=False,
                ),
                "idempotent": True,
            }

        if row.status != "candidate_received":
            raise HTTPException(
                status_code=400,
                detail="Enrollment has no candidate to confirm",
            )
        if row.telegram_chat_id is None:
            raise HTTPException(status_code=400, detail="Candidate chat ID missing")

        settings_row = await PublishAlertTelegramOutboxService.get_or_create_settings(
            db, tenant_id, actor_id=actor_id,
        )
        existing = settings_row.recipient_chat_id
        max_recipients = cls.max_confirmed_recipients()
        if (
            existing is not None
            and int(existing) != int(row.telegram_chat_id)
            and max_recipients <= 1
            and not replace_existing
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "A recipient is already configured. Pass replace_existing=true to replace it. "
                    f"Max confirmed recipients for this tenant: {max_recipients}."
                ),
            )

        # Write recipient + allowlist; never flip enabled
        was_enabled = bool(settings_row.enabled)
        label = row.telegram_display_name or (
            f"@{row.telegram_username}" if row.telegram_username else "Telegram operator"
        )
        settings_row.recipient_chat_id = int(row.telegram_chat_id)
        settings_row.recipient_label = safe_plain(label, limit=120)
        settings_row.allowed_chat_ids = [int(row.telegram_chat_id)]
        settings_row.enabled = was_enabled  # explicit: do not enable via enrollment
        settings_row.updated_by = actor_id

        # Revoke prior confirmed enrollments for this tenant (history retained as revoked)
        now = _now()
        settings_row.updated_at = now
        if existing is not None and int(existing) != int(row.telegram_chat_id):
            await db.execute(
                update(PublishAlertTelegramEnrollment)
                .where(
                    PublishAlertTelegramEnrollment.tenant_id == tenant_id,
                    PublishAlertTelegramEnrollment.status == "confirmed",
                    PublishAlertTelegramEnrollment.id != row.id,
                )
                .values(
                    status="revoked",
                    revoked_at=now,
                    revoked_by=actor_id,
                    rejection_reason_code="replaced",
                    updated_at=now,
                )
            )

        row.status = "confirmed"
        row.confirmed_at = now
        row.confirmed_by = actor_id
        row.updated_at = now
        await db.flush()
        # server onupdate/defaults can expire attrs; refresh before sync serialize
        await db.refresh(settings_row)
        await db.refresh(row)

        logger.info(
            "Telegram enrollment confirmed tenant=%s enrollment=%s recipient=%s enabled=%s",
            tenant_id,
            row.id,
            row.telegram_chat_id_masked,
            was_enabled,
        )
        return {
            "enrollment": cls.serialize_enrollment(row),
            "settings": PublishAlertTelegramOutboxService.serialize_settings(
                settings_row,
                reveal_chat_id=False,
            ),
            "idempotent": False,
            "delivery_enabled": False,
            "tenant_delivery_flag": was_enabled,
        }

    @classmethod
    async def list_recipients(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        include_history: bool = True,
        reveal_chat_id: bool = False,
    ) -> dict[str, Any]:
        statuses = ("confirmed",) if not include_history else ("confirmed", "revoked")
        base = select(PublishAlertTelegramEnrollment).where(
            PublishAlertTelegramEnrollment.tenant_id == tenant_id,
            PublishAlertTelegramEnrollment.status.in_(statuses),
            PublishAlertTelegramEnrollment.telegram_chat_id_masked.is_not(None),
        )
        from sqlalchemy import func as sa_func

        total = (
            await db.execute(
                select(sa_func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        pages = max(1, int(math.ceil(total / page_size))) if total else 1
        page = max(1, min(page, pages))
        rows = (
            await db.execute(
                base.order_by(
                    PublishAlertTelegramEnrollment.confirmed_at.desc().nullslast(),
                    PublishAlertTelegramEnrollment.created_at.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "items": [cls.serialize_recipient(r, reveal_chat_id=reveal_chat_id) for r in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "max_confirmed_recipients": cls.max_confirmed_recipients(),
        }

    @classmethod
    async def remove_recipient(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        actor_id: UUID,
        enrollment_id: UUID | None = None,
    ) -> dict[str, Any]:
        settings_row = await PublishAlertTelegramOutboxService.get_or_create_settings(
            db, tenant_id, actor_id=actor_id,
        )
        now = _now()

        target: PublishAlertTelegramEnrollment | None = None
        if enrollment_id is not None:
            target = await db.get(PublishAlertTelegramEnrollment, enrollment_id)
            if target is None or target.tenant_id != tenant_id:
                raise HTTPException(status_code=404, detail="Recipient enrollment not found")
            if target.status != "confirmed":
                raise HTTPException(status_code=400, detail="Recipient is not confirmed")
        else:
            stmt = (
                select(PublishAlertTelegramEnrollment)
                .where(
                    PublishAlertTelegramEnrollment.tenant_id == tenant_id,
                    PublishAlertTelegramEnrollment.status == "confirmed",
                )
                .order_by(PublishAlertTelegramEnrollment.confirmed_at.desc())
                .limit(1)
            )
            target = (await db.execute(stmt)).scalar_one_or_none()

        # Clear settings recipient; disable delivery when clearing destination
        settings_row.recipient_chat_id = None
        settings_row.recipient_label = None
        settings_row.allowed_chat_ids = []
        settings_row.enabled = False
        settings_row.updated_by = actor_id
        settings_row.updated_at = now

        if target is not None:
            target.status = "revoked"
            target.revoked_at = now
            target.revoked_by = actor_id
            target.rejection_reason_code = "replaced"
            target.updated_at = now

        await db.flush()
        await db.refresh(settings_row)
        if target is not None:
            await db.refresh(target)
        return {
            "removed": True,
            "enrollment": cls.serialize_enrollment(target) if target else None,
            "settings": PublishAlertTelegramOutboxService.serialize_settings(
                settings_row,
                reveal_chat_id=False,
            ),
        }

    @classmethod
    async def try_handle_start_message(
        cls,
        db: AsyncSession,
        *,
        update_id: int | None,
        message: dict,
    ) -> dict[str, Any] | None:
        """If message is enrollment `/start <token>`, process and return result dict.

        Returns None when the message is not an enrollment start command so the
        caller can continue normal webhook handling.
        """
        text = (message.get("text") or "").strip()
        token = parse_enrollment_start_payload(text)
        if token is None:
            return None

        chat = message.get("chat") or {}
        user = message.get("from") or {}
        chat_id = chat.get("id")

        async def _reply(body: str) -> None:
            if chat_id is None:
                return
            from app.services.telegram_service import _send_telegram_message

            await _send_telegram_message(chat_id, body)

        if not cls.enrollment_enabled():
            await _reply(_GENERIC_INVALID_REPLY)
            return {"enrollment": True, "ok": False, "reason": "enrollment_disabled"}

        ok_chat, reject_code = is_private_user_chat(chat, user)
        if not ok_chat:
            await _reply(_GENERIC_INVALID_REPLY)
            logger.info(
                "Telegram enrollment rejected chat_type=%s reason=%s",
                chat.get("type"),
                reject_code,
            )
            return {"enrollment": True, "ok": False, "reason": reject_code}

        token_hash = hash_enrollment_token(token)
        now = _now()

        # Idempotent replay: same update already bound
        if update_id is not None:
            existing_by_update = (
                await db.execute(
                    select(PublishAlertTelegramEnrollment).where(
                        PublishAlertTelegramEnrollment.source_update_id == int(update_id),
                    )
                )
            ).scalar_one_or_none()
            if existing_by_update is not None:
                await _reply(_SUCCESS_REPLY if existing_by_update.status == "candidate_received" else _GENERIC_INVALID_REPLY)
                return {"enrollment": True, "ok": True, "duplicate_update": True, "id": str(existing_by_update.id)}

        # Atomic single-use consume
        result = await db.execute(
            update(PublishAlertTelegramEnrollment)
            .where(
                PublishAlertTelegramEnrollment.token_hash == token_hash,
                PublishAlertTelegramEnrollment.purpose == ENROLLMENT_PURPOSE,
                PublishAlertTelegramEnrollment.status == "pending_start",
                PublishAlertTelegramEnrollment.expires_at > now,
            )
            .values(
                status="candidate_received",
                consumed_at=now,
                telegram_user_id=int(user["id"]),
                telegram_chat_id=int(chat["id"]),
                telegram_chat_id_masked=mask_chat_id(int(chat["id"])),
                telegram_display_name=safe_telegram_display_name(user, chat),
                telegram_username=safe_telegram_username(user),
                telegram_chat_type=str(chat.get("type") or "private"),
                source_update_id=int(update_id) if update_id is not None else None,
                updated_at=now,
            )
            .returning(PublishAlertTelegramEnrollment.id)
        )
        consumed_id = result.scalar_one_or_none()
        if consumed_id is None:
            # Diagnose without leaking existence details to the user
            row = (
                await db.execute(
                    select(PublishAlertTelegramEnrollment).where(
                        PublishAlertTelegramEnrollment.token_hash == token_hash,
                    )
                )
            ).scalar_one_or_none()
            reason = "token_invalid"
            if row is not None:
                if row.status == "revoked":
                    reason = "token_revoked"
                elif row.status in ("candidate_received", "confirmed"):
                    reason = "token_consumed"
                elif row.expires_at <= now or row.status == "expired":
                    reason = "token_expired"
            await _reply(_GENERIC_INVALID_REPLY)
            logger.info("Telegram enrollment token rejected reason=%s", reason)
            return {"enrollment": True, "ok": False, "reason": reason}

        await db.flush()
        await _reply(_SUCCESS_REPLY)
        logger.info(
            "Telegram enrollment candidate received enrollment=%s masked=%s",
            consumed_id,
            mask_chat_id(int(chat["id"])),
        )
        return {
            "enrollment": True,
            "ok": True,
            "id": str(consumed_id),
            "status": "candidate_received",
        }
