"""Customer success integration — journey timeline and onboarding activity."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent, SubscriberResult
from app.models.customer_success_journey import TenantCustomerSuccessJourney
from app.models.tenant_onboarding import TenantOnboardingProgress
from app.services.event_handlers.base import IntegrationHandler


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CustomerSuccessEventHandler(IntegrationHandler):
    name = "customer_success"
    integration_key = "customer_success"

    async def handle(self, db: AsyncSession, event: PlatformEvent) -> SubscriberResult:
        if not self._is_enabled(event):
            return self._skip("integration disabled for event type")

        tenant_id = event.require_tenant_id()
        definition = self._definition(event)
        entry = {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "title": event.title or (definition.description if definition else event.event_type),
            "occurred_at": event.occurred_at.isoformat(),
            "payload": event.payload,
        }

        progress = (await db.execute(
            select(TenantOnboardingProgress).where(TenantOnboardingProgress.tenant_id == tenant_id),
        )).scalar_one_or_none()
        if progress is not None:
            progress.last_activity_at = _utcnow()

        journey = (await db.execute(
            select(TenantCustomerSuccessJourney).where(
                TenantCustomerSuccessJourney.tenant_id == tenant_id,
            ),
        )).scalar_one_or_none()
        if journey is not None:
            timeline = list(journey.timeline_entries or [])
            timeline.append(entry)
            journey.timeline_entries = timeline[-200:]
            journey.last_refreshed_at = _utcnow()

        await db.flush()
        return self._handled(detail="timeline updated" if journey else "activity stamped")
