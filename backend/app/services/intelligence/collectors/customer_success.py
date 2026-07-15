"""Customer Success signal collector."""
from __future__ import annotations

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal


class CustomerSuccessCollector(SignalCollector):
    name = "customer_success"
    source = "customer_success"
    event_types = frozenset({
        "tenant.customer_success.milestone",
        "tenant.onboarding.step_completed",
        "tenant.onboarding.platform_ready",
    })

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        mapping = {
            "tenant.customer_success.milestone": ("customer_success.milestone", "success", "customer_success"),
            "tenant.onboarding.step_completed": ("onboarding.step_completed", "info", "onboarding"),
            "tenant.onboarding.platform_ready": ("onboarding.platform_ready", "success", "onboarding"),
        }
        mapped = mapping.get(event.event_type)
        if not mapped:
            return []
        signal_type, severity, source = mapped
        return [
            normalize_signal(
                tenant_id=event.require_tenant_id(),
                signal_type=signal_type,
                source=source,
                severity=severity,
                entity_type=event.resource_type or source,
                entity_id=event.resource_id,
                occurred_at=event.occurred_at,
                metadata={"title": event.title, "payload": event.payload or {}},
                signal_id=event.event_id,
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        ]
