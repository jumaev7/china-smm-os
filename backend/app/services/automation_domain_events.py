"""Safe domain helpers for emitting automation-eligible platform events.

Transaction semantics (sync Event Bus):
- Emit with commit=False inside the caller's domain session, then let the
  domain service commit once. Event records + automation executions flush in
  the same transaction as the domain mutation.
- Subscriber / automation failures are swallowed by the Event Bus and must not
  roll back or alter the originating business mutation. Emit helpers catch
  unexpected errors and log them.
- Prefer transition-gated emission so health polls and re-saves stay silent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.platform_event_service import PlatformEventService

logger = logging.getLogger(__name__)

_FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "access_token",
    "refresh_token",
    "access_token_encrypted",
    "refresh_token_encrypted",
    "page_access_token",
    "user_access_token",
    "authorization",
    "password",
    "secret",
    "api_key",
    "token",
    "bearer",
    "client_secret",
})

INTEGRATION_ATTENTION_STATUSES = frozenset({
    "disconnected",
    "expired",
    "invalid",
    "missing_permissions",
    "blocked",
})


def scrub_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Drop secrets and nested blobs that must never enter event/automation payloads."""
    if not payload:
        return {}
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in _FORBIDDEN_PAYLOAD_KEYS or any(part in lowered for part in ("token", "secret", "password", "authorization")):
            continue
        if isinstance(value, dict):
            clean[key] = scrub_payload(value)
        elif isinstance(value, list):
            clean[key] = [
                scrub_payload(item) if isinstance(item, dict) else item
                for item in value
                if not isinstance(item, dict) or scrub_payload(item) is not None
            ]
        else:
            clean[key] = value
    return clean


async def emit_domain_event(
    db: AsyncSession,
    event_type: str,
    tenant_id: UUID,
    *,
    payload: dict[str, Any] | None = None,
    actor_type: str | None = "system",
    actor_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit a tenant event without committing; never raise into the domain path."""
    try:
        await PlatformEventService.emit(
            db,
            event_type,
            tenant_id,
            payload=scrub_payload(payload),
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            title=title,
            description=description,
            metadata=metadata,
            commit=False,
        )
    except Exception:
        logger.exception(
            "[DomainEvent] failed to emit %s for tenant=%s resource=%s:%s",
            event_type,
            tenant_id,
            resource_type,
            resource_id,
        )


def classify_publish_failure(error: str | None) -> tuple[str, str, bool]:
    """Map a free-text publish error into safe structured diagnostics."""
    text = (error or "").lower()
    if "timeout" in text or "interrupted" in text:
        return "publish_timeout", "timeout", True
    if "token" in text or "oauth" in text or "auth" in text or "permission" in text:
        return "auth_or_permission", "auth", True
    if "account" in text or "not found" in text or "no connected" in text:
        return "account_unavailable", "account", False
    if "rate" in text or "throttle" in text:
        return "rate_limited", "provider", True
    return "adapter_failure", "provider", True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
