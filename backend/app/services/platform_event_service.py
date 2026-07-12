"""High-level API for emitting tenant-scoped platform events."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import (
    PlatformEvent,
    PublishResult,
    build_tenant_event,
    event_bus,
    event_registry,
)
from app.core.events.types import EventDefinition
from app.models.platform_event import (
    TenantActivityEvent,
    TenantAutomationTrigger,
    TenantEventNotification,
)


class PlatformEventService:
    """Facade for publishing events and querying integration stores."""

    @staticmethod
    def list_event_types() -> list[EventDefinition]:
        return event_registry.list_all()

    @staticmethod
    async def emit(
        db: AsyncSession,
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
        commit: bool = True,
    ) -> PublishResult:
        event = build_tenant_event(
            event_type,
            tenant_id,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            title=title,
            description=description,
            metadata=metadata,
        )
        result = await event_bus.publish(db, event)
        if commit:
            await db.commit()
        return result

    @staticmethod
    async def emit_event(
        db: AsyncSession,
        event: PlatformEvent,
        *,
        commit: bool = True,
    ) -> PublishResult:
        result = await event_bus.publish(db, event)
        if commit:
            await db.commit()
        return result

    @staticmethod
    async def list_activity(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        limit: int = 50,
    ) -> list[TenantActivityEvent]:
        rows = (
            await db.execute(
                select(TenantActivityEvent)
                .where(TenantActivityEvent.tenant_id == tenant_id)
                .order_by(TenantActivityEvent.occurred_at.desc())
                .limit(limit),
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_notifications(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = "unread",
        limit: int = 50,
    ) -> list[TenantEventNotification]:
        query = select(TenantEventNotification).where(
            TenantEventNotification.tenant_id == tenant_id,
            TenantEventNotification.deleted_at.is_(None),
        )
        if status == "unread":
            query = query.where(TenantEventNotification.is_read.is_(False))
        elif status == "read":
            query = query.where(TenantEventNotification.is_read.is_(True))
        elif status:
            query = query.where(TenantEventNotification.status == status)
        rows = (
            await db.execute(
                query.order_by(TenantEventNotification.created_at.desc()).limit(limit),
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_automation_triggers(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = "pending",
        limit: int = 50,
    ) -> list[TenantAutomationTrigger]:
        query = select(TenantAutomationTrigger).where(
            TenantAutomationTrigger.tenant_id == tenant_id,
        )
        if status:
            query = query.where(TenantAutomationTrigger.status == status)
        rows = (
            await db.execute(
                query.order_by(TenantAutomationTrigger.created_at.desc()).limit(limit),
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def count_tenant_records(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict[str, int]:
        activity = (
            await db.execute(
                select(func.count())
                .select_from(TenantActivityEvent)
                .where(TenantActivityEvent.tenant_id == tenant_id),
            )
        ).scalar_one()
        notifications = (
            await db.execute(
                select(func.count())
                .select_from(TenantEventNotification)
                .where(
                    TenantEventNotification.tenant_id == tenant_id,
                    TenantEventNotification.deleted_at.is_(None),
                ),
            )
        ).scalar_one()
        triggers = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationTrigger)
                .where(TenantAutomationTrigger.tenant_id == tenant_id),
            )
        ).scalar_one()
        return {
            "activity": int(activity),
            "notifications": int(notifications),
            "automation_triggers": int(triggers),
        }
