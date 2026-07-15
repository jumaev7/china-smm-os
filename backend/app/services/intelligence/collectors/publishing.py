"""Publishing signal collector."""
from __future__ import annotations

from decimal import Decimal

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal

_EVENT_MAP = {
    "tenant.content.published": ("publishing.completed", "success", Decimal("1.000")),
    "tenant.content.publish_failed": ("publishing.failed", "error", Decimal("1.000")),
    "tenant.content.publish_partial_failed": ("publishing.partial_failed", "warning", Decimal("0.950")),
}


class PublishingCollector(SignalCollector):
    name = "publishing"
    source = "publishing"
    event_types = frozenset(_EVENT_MAP.keys())

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        mapped = _EVENT_MAP.get(event.event_type)
        if not mapped:
            return []
        signal_type, severity, confidence = mapped
        payload = event.payload or {}
        return [
            normalize_signal(
                tenant_id=event.require_tenant_id(),
                signal_type=signal_type,
                source=self.source,
                severity=severity,
                confidence=confidence,
                entity_type=event.resource_type or "content",
                entity_id=event.resource_id,
                occurred_at=event.occurred_at,
                metadata={
                    "title": event.title,
                    "description": event.description,
                    "payload": payload,
                },
                signal_id=event.event_id,
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        ]
