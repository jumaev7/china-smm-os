"""Audit log integration — writes to platform_audit_logs (audit-ready)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent, SubscriberResult
from app.services.event_handlers.base import IntegrationHandler
from app.services.platform_audit_service import PlatformAuditService


class AuditEventHandler(IntegrationHandler):
    name = "audit"
    integration_key = "audit"

    async def handle(self, db: AsyncSession, event: PlatformEvent) -> SubscriberResult:
        if not self._is_enabled(event):
            return self._skip("integration disabled for event type")

        row = await PlatformAuditService.record(
            db,
            actor_type=event.actor_type or "system",
            actor_id=event.actor_id,
            tenant_id=event.tenant_id,
            event_type=event.event_type,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details={
                "event_id": str(event.event_id),
                "payload": event.payload,
                "title": event.title,
                "description": event.description,
                **event.metadata,
            },
            commit=False,
        )
        return self._handled(detail=str(row.id))
