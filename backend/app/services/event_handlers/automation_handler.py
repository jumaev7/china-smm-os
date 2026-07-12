"""Automation integration — records triggers for workflow engines."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent, SubscriberResult
from app.models.platform_event import TenantAutomationTrigger
from app.services.event_handlers.base import IntegrationHandler

_WORKFLOW_HINTS: dict[str, str] = {
    "tenant.crm.lead_created": "follow_up_workflow",
    "tenant.crm.deal_stage_changed": "proposal_workflow",
    "tenant.automation.triggered": "follow_up_workflow",
}


class AutomationEventHandler(IntegrationHandler):
    name = "automation"
    integration_key = "automation"

    async def handle(self, db: AsyncSession, event: PlatformEvent) -> SubscriberResult:
        if not self._is_enabled(event):
            return self._skip("integration disabled for event type")

        tenant_id = event.require_tenant_id()
        trigger_key = event.metadata.get("trigger_key") or event.event_type
        workflow_hint = event.metadata.get("workflow_hint") or _WORKFLOW_HINTS.get(event.event_type)
        row = TenantAutomationTrigger(
            tenant_id=tenant_id,
            event_id=event.event_id,
            event_type=event.event_type,
            trigger_key=str(trigger_key),
            workflow_hint=workflow_hint,
            payload=event.payload or None,
        )
        db.add(row)
        await db.flush()
        return self._handled(detail=str(row.id))
