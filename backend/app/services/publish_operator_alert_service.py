"""Deduplicated publish operator alert lifecycle.

Alert generation is isolated from core publishing transactions: callers wrap
`on_attempt_transition` / helpers so failures never roll back publish writes
or create social posts.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import (
    ALERT_SEVERITIES,
    ALERT_STATES,
    ALERT_TYPES,
    FAILURE_ALERT_TYPES,
    PublishOperatorAlert,
)
from app.models.publishing_account import PublishingAccount
from app.schemas.publish_alerts import (
    PublishAlertAcknowledgeResponse,
    PublishAlertCountsResponse,
    PublishAlertItem,
    PublishAlertListResponse,
    PublishAlertResolveResponse,
)
from app.services.automation_domain_events import emit_domain_event, scrub_payload
from app.services.publish_alert_delivery import deliver_publish_alert
from app.services.publish_resilience import (
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

_SEVERITY_BY_TYPE = {
    "operator_review": "critical",
    "exhausted": "critical",
    "terminal_failure": "critical",
    "stale_in_progress": "warning",
    "recovery": "info",
    "repeated_failure": "critical",
}

_TITLE_BY_TYPE = {
    "operator_review": "Publish attempt needs operator review",
    "exhausted": "Publish retries exhausted",
    "terminal_failure": "Terminal publish failure",
    "stale_in_progress": "Stale in-progress publish attempt",
    "recovery": "Publish recovered successfully",
    "repeated_failure": "Repeated publish failures on destination",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_dedupe_key(
    *,
    alert_type: str,
    content_id: UUID | None,
    platform: str | None,
    account_id: UUID | None,
    attempt_id: UUID | None = None,
) -> str:
    """Stable incident key: type + content + destination (+ attempt for attempt-scoped types)."""
    acct = str(account_id) if account_id else "-"
    content = str(content_id) if content_id else "-"
    plat = (platform or "-").lower()
    # Attempt-scoped for stale/operator_review so worker polls collapse on same attempt.
    # Destination-scoped for exhausted/terminal/repeated so retries of same destination merge.
    if alert_type in ("stale_in_progress", "operator_review", "recovery"):
        attempt = str(attempt_id) if attempt_id else "-"
        return f"{alert_type}|{content}|{plat}|{acct}|{attempt}"
    if alert_type == "repeated_failure":
        return f"repeated_failure|{plat}|{acct}"
    return f"{alert_type}|{content}|{plat}|{acct}"


def _action_urls(content_id: UUID | None, attempt_id: UUID | None) -> dict[str, str]:
    urls = {
        "queue_url": "/publishing/queue",
        "action_url": "/publishing/alerts",
    }
    if content_id:
        urls["content_url"] = f"/content/{content_id}"
        urls["action_url"] = f"/content/{content_id}"
        urls["attempts_url"] = f"/publishing/queue?content_id={content_id}"
    if attempt_id and content_id:
        urls["action_url"] = f"/content/{content_id}"
    return urls


class PublishOperatorAlertService:
    # ── Generation (never raise into publishing) ───────────────────────────

    @classmethod
    async def on_attempt_transition(
        cls,
        db: AsyncSession,
        attempt: PublishAttempt,
        *,
        previous_status: str | None = None,
    ) -> PublishOperatorAlert | None:
        """Map attempt status transitions to operator alerts. Never raises."""
        try:
            status = attempt.status
            if status == STATUS_SUCCESS:
                return await cls._handle_success(db, attempt)
            if status == STATUS_OPERATOR_REVIEW:
                return await cls.upsert_failure_alert(db, attempt, alert_type="operator_review")
            if status == STATUS_EXHAUSTED:
                return await cls.upsert_failure_alert(db, attempt, alert_type="exhausted")
            if status == STATUS_FAILED:
                # Terminal only when not superseded/cancelled duplicates.
                code = (attempt.failure_code or "").lower()
                if code in {"stale_after_success", "max_attempts_exhausted"}:
                    return None
                if attempt.retryable is True:
                    return None
                return await cls.upsert_failure_alert(db, attempt, alert_type="terminal_failure")
            if status == STATUS_RETRYING and previous_status == "in_progress":
                # Stale recovery for non-Meta platforms.
                return await cls.upsert_failure_alert(db, attempt, alert_type="stale_in_progress")
            return None
        except Exception:
            logger.exception(
                "[PublishAlert] on_attempt_transition failed attempt_id=%s status=%s",
                getattr(attempt, "id", None),
                getattr(attempt, "status", None),
            )
            return None

    @classmethod
    async def upsert_failure_alert(
        cls,
        db: AsyncSession,
        attempt: PublishAttempt,
        *,
        alert_type: str,
    ) -> PublishOperatorAlert | None:
        if alert_type not in ALERT_TYPES:
            return None
        ctx = await cls._resolve_context(db, attempt)
        if ctx.get("tenant_id") is None:
            logger.warning(
                "[PublishAlert] skip alert — missing tenant attempt_id=%s",
                attempt.id,
            )
            return None

        severity = _SEVERITY_BY_TYPE.get(alert_type, "warning")
        urls = _action_urls(attempt.content_id, attempt.id)
        dedupe_key = build_dedupe_key(
            alert_type=alert_type,
            content_id=attempt.content_id,
            platform=attempt.platform,
            account_id=attempt.account_id,
            attempt_id=attempt.id,
        )
        title = _TITLE_BY_TYPE.get(alert_type, "Publish alert")
        if ctx.get("company_name") and attempt.platform:
            title = f"{title}: {ctx['company_name']} / {attempt.platform}"

        body = sanitize_error_message(attempt.error) or title
        safe_context = scrub_payload({
            "failure_category": attempt.failure_category,
            "idempotency_key": attempt.idempotency_key,
            "publish_version": attempt.publish_version,
            "alert_type": alert_type,
        })

        alert, created = await cls._upsert(
            db,
            tenant_id=ctx["tenant_id"],
            dedupe_key=dedupe_key,
            alert_type=alert_type,
            severity=severity,
            title=title[:255],
            body=body,
            client_id=ctx.get("client_id"),
            content_id=attempt.content_id,
            account_id=attempt.account_id,
            attempt_id=attempt.id,
            platform=attempt.platform,
            account_name=ctx.get("account_name"),
            company_name=ctx.get("company_name"),
            attempt_status=attempt.status,
            attempt_number=attempt.attempt_number,
            failure_code=attempt.failure_code,
            failure_message=body,
            next_retry_at=attempt.next_retry_at,
            action_url=urls.get("action_url"),
            context=safe_context,
        )
        if created:
            logger.info(
                "[PublishAlert] created type=%s severity=%s tenant=%s attempt=%s dedupe=%s",
                alert_type,
                severity,
                ctx["tenant_id"],
                attempt.id,
                dedupe_key,
            )
            await cls._emit_and_deliver(db, alert, created=True)
        else:
            logger.info(
                "[PublishAlert] deduped type=%s tenant=%s attempt=%s occurrences=%s",
                alert_type,
                ctx["tenant_id"],
                attempt.id,
                alert.occurrence_count,
            )

        if alert_type in FAILURE_ALERT_TYPES and alert_type != "repeated_failure":
            await cls._maybe_repeated_failure(db, attempt, ctx)

        return alert

    @classmethod
    async def _handle_success(
        cls,
        db: AsyncSession,
        attempt: PublishAttempt,
    ) -> PublishOperatorAlert | None:
        ctx = await cls._resolve_context(db, attempt)
        tenant_id = ctx.get("tenant_id")
        if tenant_id is None:
            return None

        resolved = await cls.resolve_open_for_destination(
            db,
            tenant_id=tenant_id,
            content_id=attempt.content_id,
            platform=attempt.platform,
            account_id=attempt.account_id,
            note="Auto-resolved after successful publish",
            system=True,
            exclude_alert_types=frozenset({"recovery", "repeated_failure"}),
        )
        if not resolved:
            return None

        urls = _action_urls(attempt.content_id, attempt.id)
        dedupe_key = build_dedupe_key(
            alert_type="recovery",
            content_id=attempt.content_id,
            platform=attempt.platform,
            account_id=attempt.account_id,
            attempt_id=attempt.id,
        )
        title = _TITLE_BY_TYPE["recovery"]
        if ctx.get("company_name") and attempt.platform:
            title = f"{title}: {ctx['company_name']} / {attempt.platform}"
        body = (
            f"Previously alerted destination published successfully "
            f"(resolved {len(resolved)} open alert(s))."
        )
        alert, created = await cls._upsert(
            db,
            tenant_id=tenant_id,
            dedupe_key=dedupe_key,
            alert_type="recovery",
            severity="info",
            title=title[:255],
            body=body,
            client_id=ctx.get("client_id"),
            content_id=attempt.content_id,
            account_id=attempt.account_id,
            attempt_id=attempt.id,
            platform=attempt.platform,
            account_name=ctx.get("account_name"),
            company_name=ctx.get("company_name"),
            attempt_status=STATUS_SUCCESS,
            attempt_number=attempt.attempt_number,
            failure_code=None,
            failure_message=None,
            next_retry_at=None,
            action_url=urls.get("content_url") or urls.get("action_url"),
            context=scrub_payload({
                "resolved_alert_ids": [str(a.id) for a in resolved],
                "external_post_id": attempt.external_post_id,
            }),
            initial_state="resolved",
        )
        # Recovery alerts are informational and start resolved.
        if alert.state != "resolved":
            alert.state = "resolved"
            alert.resolved_at = utc_now()
            alert.resolved_by_system = True
            alert.resolve_note = "Recovery notification"
            await db.flush()
        if created:
            logger.info(
                "[PublishAlert] recovery created tenant=%s attempt=%s resolved=%s",
                tenant_id,
                attempt.id,
                len(resolved),
            )
            await cls._emit_and_deliver(db, alert, created=True)
        return alert

    @classmethod
    async def resolve_open_for_destination(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        content_id: UUID,
        platform: str | None,
        account_id: UUID | None,
        note: str | None = None,
        system: bool = False,
        exclude_alert_types: frozenset[str] | None = None,
    ) -> list[PublishOperatorAlert]:
        """Resolve open/acked failure alerts for this destination only."""
        filters = [
            PublishOperatorAlert.tenant_id == tenant_id,
            PublishOperatorAlert.state.in_(("open", "acknowledged")),
            PublishOperatorAlert.content_id == content_id,
            PublishOperatorAlert.alert_type.in_(tuple(FAILURE_ALERT_TYPES)),
        ]
        if platform:
            filters.append(PublishOperatorAlert.platform == platform)
        if account_id is None:
            filters.append(PublishOperatorAlert.account_id.is_(None))
        else:
            filters.append(PublishOperatorAlert.account_id == account_id)
        if exclude_alert_types:
            filters.append(~PublishOperatorAlert.alert_type.in_(tuple(exclude_alert_types)))

        rows = list(
            (await db.execute(select(PublishOperatorAlert).where(*filters))).scalars().all()
        )
        now = utc_now()
        for row in rows:
            row.state = "resolved"
            row.resolved_at = now
            row.resolved_by_system = system
            row.resolve_note = sanitize_error_message(note)
            logger.info(
                "[PublishAlert] resolved alert_id=%s type=%s system=%s",
                row.id,
                row.alert_type,
                system,
            )
        if rows:
            await db.flush()
        return rows

    @classmethod
    async def _maybe_repeated_failure(
        cls,
        db: AsyncSession,
        attempt: PublishAttempt,
        ctx: dict[str, Any],
    ) -> PublishOperatorAlert | None:
        threshold = max(2, int(settings.PUBLISH_ALERT_REPEATED_FAILURE_THRESHOLD or 3))
        window_min = max(1, int(settings.PUBLISH_ALERT_REPEATED_FAILURE_WINDOW_MINUTES or 60))
        since = utc_now() - timedelta(minutes=window_min)

        filters = [
            PublishAttempt.content_id == attempt.content_id,
            PublishAttempt.platform == attempt.platform,
            PublishAttempt.status.in_(
                (STATUS_FAILED, STATUS_EXHAUSTED, STATUS_OPERATOR_REVIEW, STATUS_RETRYING),
            ),
            PublishAttempt.created_at >= since,
        ]
        if attempt.account_id is None:
            filters.append(PublishAttempt.account_id.is_(None))
        else:
            filters.append(PublishAttempt.account_id == attempt.account_id)

        # Broader: count failures for this account/platform across content in window.
        account_filters = [
            PublishAttempt.platform == attempt.platform,
            PublishAttempt.status.in_(
                (STATUS_FAILED, STATUS_EXHAUSTED, STATUS_OPERATOR_REVIEW),
            ),
            PublishAttempt.created_at >= since,
        ]
        if attempt.account_id is None:
            account_filters.append(PublishAttempt.account_id.is_(None))
        else:
            account_filters.append(PublishAttempt.account_id == attempt.account_id)

        # Join content → client for tenant isolation.
        count_q = (
            select(func.count())
            .select_from(PublishAttempt)
            .join(ContentItem, ContentItem.id == PublishAttempt.content_id)
            .join(Client, Client.id == ContentItem.client_id)
            .where(Client.tenant_id == ctx["tenant_id"], *account_filters)
        )
        count = int((await db.execute(count_q)).scalar_one() or 0)
        if count < threshold:
            return None

        urls = _action_urls(attempt.content_id, attempt.id)
        dedupe_key = build_dedupe_key(
            alert_type="repeated_failure",
            content_id=None,
            platform=attempt.platform,
            account_id=attempt.account_id,
        )
        title = (
            f"Repeated publish failures: {attempt.platform}"
            + (f" / {ctx.get('account_name')}" if ctx.get("account_name") else "")
        )
        body = (
            f"{count} failed publish attempts on this destination "
            f"within {window_min} minutes (threshold {threshold})."
        )
        alert, created = await cls._upsert(
            db,
            tenant_id=ctx["tenant_id"],
            dedupe_key=dedupe_key,
            alert_type="repeated_failure",
            severity="critical",
            title=title[:255],
            body=body,
            client_id=ctx.get("client_id"),
            content_id=attempt.content_id,
            account_id=attempt.account_id,
            attempt_id=attempt.id,
            platform=attempt.platform,
            account_name=ctx.get("account_name"),
            company_name=ctx.get("company_name"),
            attempt_status=attempt.status,
            attempt_number=attempt.attempt_number,
            failure_code=attempt.failure_code or "repeated_failure",
            failure_message=body,
            next_retry_at=None,
            action_url=urls.get("queue_url"),
            context=scrub_payload({
                "failure_count": count,
                "window_minutes": window_min,
                "threshold": threshold,
            }),
        )
        if created:
            logger.info(
                "[PublishAlert] repeated_failure created tenant=%s platform=%s count=%s",
                ctx["tenant_id"],
                attempt.platform,
                count,
            )
            await cls._emit_and_deliver(db, alert, created=True)
        return alert

    # ── Upsert / persistence ───────────────────────────────────────────────

    @classmethod
    async def _upsert(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        dedupe_key: str,
        alert_type: str,
        severity: str,
        title: str,
        body: str | None,
        client_id: UUID | None,
        content_id: UUID | None,
        account_id: UUID | None,
        attempt_id: UUID | None,
        platform: str | None,
        account_name: str | None,
        company_name: str | None,
        attempt_status: str | None,
        attempt_number: int | None,
        failure_code: str | None,
        failure_message: str | None,
        next_retry_at: datetime | None,
        action_url: str | None,
        context: dict[str, Any] | None,
        initial_state: str = "open",
    ) -> tuple[PublishOperatorAlert, bool]:
        """Insert or bump an open/acked alert. Uses a savepoint for races."""

        async def _do() -> tuple[PublishOperatorAlert, bool]:
            existing = await cls._find_open(db, tenant_id, dedupe_key)
            now = utc_now()
            if existing is not None:
                existing.occurrence_count = int(existing.occurrence_count or 1) + 1
                existing.latest_occurred_at = now
                existing.attempt_id = attempt_id or existing.attempt_id
                existing.attempt_status = attempt_status or existing.attempt_status
                existing.attempt_number = (
                    attempt_number if attempt_number is not None else existing.attempt_number
                )
                existing.failure_code = failure_code or existing.failure_code
                existing.failure_message = failure_message or existing.failure_message
                existing.next_retry_at = next_retry_at
                existing.body = body or existing.body
                existing.title = title or existing.title
                if context:
                    existing.context = scrub_payload({**(existing.context or {}), **context})
                await db.flush()
                return existing, False

            row = PublishOperatorAlert(
                id=uuid4(),
                tenant_id=tenant_id,
                dedupe_key=dedupe_key,
                alert_type=alert_type,
                state=initial_state if initial_state in ALERT_STATES else "open",
                severity=severity if severity in ALERT_SEVERITIES else "warning",
                title=title,
                body=body,
                client_id=client_id,
                content_id=content_id,
                account_id=account_id,
                attempt_id=attempt_id,
                platform=platform,
                account_name=account_name,
                company_name=company_name,
                attempt_status=attempt_status,
                attempt_number=attempt_number,
                failure_code=failure_code,
                failure_message=sanitize_error_message(failure_message),
                next_retry_at=next_retry_at,
                occurrence_count=1,
                first_occurred_at=now,
                latest_occurred_at=now,
                action_url=action_url,
                context=scrub_payload(context),
                resolved_by_system=initial_state == "resolved",
                resolved_at=now if initial_state == "resolved" else None,
                resolve_note="Recovery notification" if initial_state == "resolved" else None,
            )
            db.add(row)
            await db.flush()
            return row, True

        try:
            begin_nested = getattr(db, "begin_nested", None)
            if begin_nested is not None:
                async with db.begin_nested():
                    return await _do()
            return await _do()
        except IntegrityError:
            existing = await cls._find_open(db, tenant_id, dedupe_key)
            if existing is None:
                return await _do()
            existing.occurrence_count = int(existing.occurrence_count or 1) + 1
            existing.latest_occurred_at = utc_now()
            await db.flush()
            logger.info(
                "[PublishAlert] concurrent dedupe resolved alert_id=%s occurrences=%s",
                existing.id,
                existing.occurrence_count,
            )
            return existing, False

    @classmethod
    async def _find_open(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        dedupe_key: str,
    ) -> PublishOperatorAlert | None:
        return (
            await db.execute(
                select(PublishOperatorAlert).where(
                    PublishOperatorAlert.tenant_id == tenant_id,
                    PublishOperatorAlert.dedupe_key == dedupe_key,
                    PublishOperatorAlert.state.in_(("open", "acknowledged")),
                ),
            )
        ).scalar_one_or_none()

    @classmethod
    async def _resolve_context(
        cls,
        db: AsyncSession,
        attempt: PublishAttempt,
    ) -> dict[str, Any]:
        result = await db.execute(
            select(ContentItem, Client, PublishingAccount)
            .join(Client, Client.id == ContentItem.client_id)
            .outerjoin(PublishingAccount, PublishingAccount.id == attempt.account_id)
            .where(ContentItem.id == attempt.content_id),
        )
        row = result.one_or_none()
        if row is None:
            return {}
        content, client, account = row
        return {
            "tenant_id": client.tenant_id,
            "client_id": client.id,
            "company_name": client.company_name,
            "account_name": account.account_name if account else None,
            "content_status": content.status,
        }

    @classmethod
    async def _emit_and_deliver(
        cls,
        db: AsyncSession,
        alert: PublishOperatorAlert,
        *,
        created: bool,
    ) -> None:
        if not created:
            return
        try:
            urls = _action_urls(alert.content_id, alert.attempt_id)
            await emit_domain_event(
                db,
                f"tenant.publish_alert.{alert.alert_type}",
                alert.tenant_id,
                payload={
                    "severity": "info" if alert.severity == "info" else (
                        "critical" if alert.severity == "critical" else "warning"
                    ),
                    "alert_id": str(alert.id),
                    "alert_type": alert.alert_type,
                    "attempt_id": str(alert.attempt_id) if alert.attempt_id else None,
                    "content_id": str(alert.content_id) if alert.content_id else None,
                    "platform": alert.platform,
                    "failure_code": alert.failure_code,
                    "action_url": alert.action_url or urls.get("action_url"),
                },
                resource_type="publish_alert",
                resource_id=str(alert.id),
                title=alert.title,
                description=alert.body,
            )
        except Exception:
            logger.exception("[PublishAlert] event emit failed alert_id=%s", alert.id)
        try:
            await deliver_publish_alert(db, alert)
        except Exception:
            logger.exception("[PublishAlert] delivery failed alert_id=%s", alert.id)

    # ── Admin API ──────────────────────────────────────────────────────────

    @classmethod
    def serialize(cls, row: PublishOperatorAlert) -> PublishAlertItem:
        urls = _action_urls(row.content_id, row.attempt_id)
        return PublishAlertItem(
            id=row.id,
            tenant_id=row.tenant_id,
            dedupe_key=row.dedupe_key,
            alert_type=row.alert_type,  # type: ignore[arg-type]
            state=row.state,  # type: ignore[arg-type]
            severity=row.severity,  # type: ignore[arg-type]
            title=row.title,
            body=row.body,
            client_id=row.client_id,
            content_id=row.content_id,
            account_id=row.account_id,
            attempt_id=row.attempt_id,
            platform=row.platform,
            account_name=row.account_name,
            company_name=row.company_name,
            attempt_status=row.attempt_status,
            attempt_number=row.attempt_number,
            failure_code=row.failure_code,
            failure_message=row.failure_message,
            next_retry_at=row.next_retry_at,
            occurrence_count=row.occurrence_count,
            first_occurred_at=row.first_occurred_at,
            latest_occurred_at=row.latest_occurred_at,
            acknowledged_at=row.acknowledged_at,
            acknowledged_by=row.acknowledged_by,
            resolved_at=row.resolved_at,
            resolved_by=row.resolved_by,
            resolve_note=row.resolve_note,
            resolved_by_system=bool(row.resolved_by_system),
            action_url=row.action_url or urls.get("action_url"),
            content_url=urls.get("content_url"),
            queue_url=urls.get("queue_url"),
            attempts_url=urls.get("attempts_url"),
            context=row.context,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @classmethod
    async def list_alerts(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        state: str | None = None,
        severity: str | None = None,
        platform: str | None = None,
        client_id: UUID | None = None,
        alert_type: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> PublishAlertListResponse:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        offset = (page - 1) * page_size

        filters: list[Any] = [PublishOperatorAlert.tenant_id == tenant_id]
        if state:
            if state not in ALERT_STATES:
                raise HTTPException(status_code=400, detail=f"Invalid state: {state}")
            filters.append(PublishOperatorAlert.state == state)
        if severity:
            if severity not in ALERT_SEVERITIES:
                raise HTTPException(status_code=400, detail=f"Invalid severity: {severity}")
            filters.append(PublishOperatorAlert.severity == severity)
        if platform:
            filters.append(PublishOperatorAlert.platform == platform)
        if client_id:
            filters.append(PublishOperatorAlert.client_id == client_id)
        if alert_type:
            if alert_type not in ALERT_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid alert_type: {alert_type}")
            filters.append(PublishOperatorAlert.alert_type == alert_type)
        if created_from is not None:
            filters.append(PublishOperatorAlert.created_at >= created_from)
        if created_to is not None:
            filters.append(PublishOperatorAlert.created_at <= created_to)

        total = int(
            (await db.execute(
                select(func.count()).select_from(PublishOperatorAlert).where(*filters),
            )).scalar_one()
            or 0
        )
        rows = list(
            (
                await db.execute(
                    select(PublishOperatorAlert)
                    .where(*filters)
                    .order_by(
                        PublishOperatorAlert.latest_occurred_at.desc(),
                        PublishOperatorAlert.id.desc(),
                    )
                    .offset(offset)
                    .limit(page_size),
                )
            ).scalars().all()
        )
        pages = max(1, math.ceil(total / page_size)) if total else 0
        return PublishAlertListResponse(
            items=[cls.serialize(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    @classmethod
    async def counts(cls, db: AsyncSession, tenant_id: UUID) -> PublishAlertCountsResponse:
        rows = (
            await db.execute(
                select(
                    PublishOperatorAlert.state,
                    PublishOperatorAlert.severity,
                    func.count(),
                )
                .where(PublishOperatorAlert.tenant_id == tenant_id)
                .group_by(PublishOperatorAlert.state, PublishOperatorAlert.severity),
            )
        ).all()
        open_count = ack_count = resolved_count = 0
        critical_open = warning_open = info_open = 0
        for state, severity, count in rows:
            c = int(count)
            if state == "open":
                open_count += c
                if severity == "critical":
                    critical_open += c
                elif severity == "warning":
                    warning_open += c
                elif severity == "info":
                    info_open += c
            elif state == "acknowledged":
                ack_count += c
            elif state == "resolved":
                resolved_count += c
        return PublishAlertCountsResponse(
            open_count=open_count,
            acknowledged_count=ack_count,
            resolved_count=resolved_count,
            critical_open_count=critical_open,
            warning_open_count=warning_open,
            info_open_count=info_open,
            unread_open_count=open_count,
        )

    @classmethod
    async def acknowledge(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        alert_id: UUID,
        *,
        actor_id: UUID | None = None,
    ) -> PublishAlertAcknowledgeResponse:
        row = await cls._get_for_tenant(db, tenant_id, alert_id)
        if row.state == "resolved":
            raise HTTPException(status_code=400, detail="Alert is already resolved")
        if row.state != "acknowledged":
            row.state = "acknowledged"
            row.acknowledged_at = utc_now()
            row.acknowledged_by = actor_id
            await db.flush()
            logger.info("[PublishAlert] acknowledged alert_id=%s tenant=%s", alert_id, tenant_id)
        return PublishAlertAcknowledgeResponse(
            id=row.id,
            state=row.state,  # type: ignore[arg-type]
            acknowledged_at=row.acknowledged_at,
        )

    @classmethod
    async def resolve_manual(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        alert_id: UUID,
        *,
        actor_id: UUID | None = None,
        note: str | None = None,
    ) -> PublishAlertResolveResponse:
        row = await cls._get_for_tenant(db, tenant_id, alert_id)
        if row.state != "resolved":
            row.state = "resolved"
            row.resolved_at = utc_now()
            row.resolved_by = actor_id
            row.resolved_by_system = False
            row.resolve_note = sanitize_error_message(note)
            await db.flush()
            logger.info("[PublishAlert] manually resolved alert_id=%s tenant=%s", alert_id, tenant_id)
        return PublishAlertResolveResponse(
            id=row.id,
            state=row.state,  # type: ignore[arg-type]
            resolved_at=row.resolved_at,
            resolve_note=row.resolve_note,
        )

    @classmethod
    async def _get_for_tenant(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        alert_id: UUID,
    ) -> PublishOperatorAlert:
        row = (
            await db.execute(
                select(PublishOperatorAlert).where(
                    PublishOperatorAlert.id == alert_id,
                    PublishOperatorAlert.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        return row
