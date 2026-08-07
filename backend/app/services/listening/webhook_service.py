"""Signed Meta webhook inbox for GET-only Social Listening reconciliation."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.listening import TenantListeningSource, TenantListeningWebhookEvent
from app.services.listening.live_sync_service import sync_live_source
from app.services.listening.normalize import utcnow

MAX_WEBHOOK_BYTES = 1_000_000
SAFE_VALUE_KEYS = frozenset({"item", "verb", "post_id", "comment_id", "created_time"})


def verify_signature(body: bytes, signature: str | None) -> bool:
    secret = settings.META_APP_SECRET
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


def verify_challenge(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    configured = settings.LISTENING_META_WEBHOOK_VERIFY_TOKEN
    if configured and mode == "subscribe" and token and hmac.compare_digest(token, configured):
        return challenge or ""
    return None


def _event_key(object_ref: str, field: str, change: dict[str, Any]) -> str:
    canonical = json.dumps(change, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(f"{object_ref}|{field}|{canonical}".encode()).hexdigest()


def _safe_summary(change: dict[str, Any]) -> dict[str, Any]:
    value = change.get("value") if isinstance(change.get("value"), dict) else {}
    return {
        "field": str(change.get("field") or "")[:80],
        "value": {key: value[key] for key in SAFE_VALUE_KEYS if key in value},
    }


async def enqueue_payload(db: AsyncSession, payload: dict[str, Any]) -> dict[str, int]:
    """Route Page events only to enabled sources with the same Page id."""
    accepted = duplicates = unrouted = 0
    if payload.get("object") != "page":
        return {"accepted": 0, "duplicates": 0, "unrouted": 0}
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        page_id = str(entry["id"])
        sources = list((await db.execute(select(TenantListeningSource).where(
            TenantListeningSource.provider_resource_ref == page_id,
            TenantListeningSource.is_enabled.is_(True),
            TenantListeningSource.source_type.in_(("facebook_page_comments", "facebook_page_mentions")),
        ))).scalars().all())
        changes = [c for c in (entry.get("changes") or []) if isinstance(c, dict)]
        if not sources:
            unrouted += len(changes) or 1
            continue
        for change in changes:
            field = str(change.get("field") or "")[:80]
            key = _event_key(page_id, field, change)
            for source in sources:
                stmt = insert(TenantListeningWebhookEvent).values(
                    id=uuid4(), tenant_id=source.tenant_id, project_id=source.project_id,
                    source_id=source.id, event_key=key, provider_object_ref=page_id,
                    provider_field=field or None, payload_summary_json=_safe_summary(change),
                ).on_conflict_do_nothing(constraint="uq_listening_webhook_source_event").returning(TenantListeningWebhookEvent.id)
                if (await db.execute(stmt)).scalar_one_or_none() is None:
                    duplicates += 1
                else:
                    accepted += 1
    return {"accepted": accepted, "duplicates": duplicates, "unrouted": unrouted}


async def list_events(db: AsyncSession, *, tenant_id: UUID, limit: int = 100) -> list[TenantListeningWebhookEvent]:
    return list((await db.execute(select(TenantListeningWebhookEvent).where(
        TenantListeningWebhookEvent.tenant_id == tenant_id,
    ).order_by(TenantListeningWebhookEvent.created_at.desc()).limit(min(max(limit, 1), 200)))).scalars().all())


async def replay_event(db: AsyncSession, *, tenant_id: UUID, event_id: UUID) -> TenantListeningWebhookEvent | None:
    event = (await db.execute(select(TenantListeningWebhookEvent).where(
        TenantListeningWebhookEvent.id == event_id,
        TenantListeningWebhookEvent.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if event:
        event.status = "pending"
        event.next_attempt_at = None
        event.last_error_code = None
        event.processed_at = None
        await db.flush()
    return event


async def process_due_events(
    db: AsyncSession, *, limit: int = 20, tenant_id: UUID | None = None,
) -> list[dict[str, Any]]:
    now = utcnow()
    stale_before = now - timedelta(minutes=5)
    claimable = or_(
        and_(
            TenantListeningWebhookEvent.status.in_(("pending", "retry")),
            or_(TenantListeningWebhookEvent.next_attempt_at.is_(None), TenantListeningWebhookEvent.next_attempt_at <= now),
        ),
        and_(
            TenantListeningWebhookEvent.status == "processing",
            TenantListeningWebhookEvent.updated_at < stale_before,
        ),
    )
    filters = [claimable]
    if tenant_id is not None:
        filters.append(TenantListeningWebhookEvent.tenant_id == tenant_id)
    event_ids = list((await db.execute(select(TenantListeningWebhookEvent.id).where(
        *filters,
    ).order_by(TenantListeningWebhookEvent.created_at).limit(limit))).scalars().all())
    results: list[dict[str, Any]] = []
    for event_id in event_ids:
        claimed = (await db.execute(update(TenantListeningWebhookEvent).where(
            TenantListeningWebhookEvent.id == event_id,
            claimable,
        ).values(
            status="processing",
            attempt_count=TenantListeningWebhookEvent.attempt_count + 1,
            updated_at=utcnow(),
        ).returning(TenantListeningWebhookEvent.id))).scalar_one_or_none()
        if claimed is None:
            await db.rollback()
            continue
        await db.commit()
        event = await db.get(TenantListeningWebhookEvent, event_id)
        if event is None:
            continue
        try:
            run = await sync_live_source(db, tenant_id=event.tenant_id, source_id=event.source_id, trigger_type="webhook", lock_owner=f"webhook:{event.id}")
            event = await db.get(TenantListeningWebhookEvent, event_id)
            if event:
                event.status = "succeeded"
                event.processed_at = utcnow()
                event.next_attempt_at = None
                event.last_error_code = None
            results.append({"event_id": str(event.id), "status": "succeeded", "run_id": str(run.id)})
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            event = await db.get(TenantListeningWebhookEvent, event_id)
            if event:
                max_attempts = max(1, settings.LISTENING_WEBHOOK_MAX_ATTEMPTS)
                event.last_error_code = type(exc).__name__[:80]
                if event.attempt_count >= max_attempts:
                    event.status = "dead_letter"
                else:
                    event.status = "retry"
                    delay = max(1, settings.LISTENING_WEBHOOK_RETRY_BASE_SECONDS) * (2 ** (event.attempt_count - 1))
                    event.next_attempt_at = utcnow() + timedelta(seconds=min(delay, 3600))
            results.append({"event_id": str(event_id), "status": event.status if event else "failed"})
        await db.commit()
    return results


__all__ = ["MAX_WEBHOOK_BYTES", "verify_signature", "verify_challenge", "enqueue_payload", "list_events", "replay_event", "process_due_events"]
