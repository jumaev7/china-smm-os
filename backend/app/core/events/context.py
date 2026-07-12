"""Helpers for building platform events from request/auth context."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.events.types import PlatformEvent


def build_tenant_event(
    event_type: str,
    tenant_id: UUID,
    *,
    payload: dict[str, Any] | None = None,
    actor_type: str | None = None,
    actor_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlatformEvent:
    return PlatformEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        payload=payload or {},
        actor_type=actor_type,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        title=title,
        description=description,
        metadata=metadata or {},
    )


def build_event_from_auth(
    event_type: str,
    *,
    tenant_id: UUID | None,
    actor_type: str = "tenant_user",
    actor_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
) -> PlatformEvent:
    return PlatformEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        payload=payload or {},
        actor_type=actor_type,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        title=title,
        description=description,
    )
