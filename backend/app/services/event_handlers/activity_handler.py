"""Activity log integration — tenant-scoped activity feed."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent, SubscriberResult
from app.models.platform_event import TenantActivityEvent
from app.services.event_handlers.base import IntegrationHandler


class ActivityEventHandler(IntegrationHandler):
    name = "activity"
    integration_key = "activity"

    async def handle(self, db: AsyncSession, event: PlatformEvent) -> SubscriberResult:
        if not self._is_enabled(event):
            return self._skip("integration disabled for event type")

        definition = self._definition(event)
        tenant_id = event.require_tenant_id()
        title = event.title or definition.description if definition else event.event_type
        row = TenantActivityEvent(
            tenant_id=tenant_id,
            event_id=event.event_id,
            event_type=event.event_type,
            category=definition.category if definition else "general",
            title=title,
            description=event.description,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            payload=event.payload or None,
            occurred_at=event.occurred_at,
        )
        db.add(row)
        await db.flush()
        return self._handled(detail=str(row.id))
