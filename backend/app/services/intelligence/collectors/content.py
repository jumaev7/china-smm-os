"""Content signal collector."""
from __future__ import annotations

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal


class ContentCollector(SignalCollector):
    name = "content"
    source = "content"
    event_types = frozenset({"tenant.content.created"})

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        return [
            normalize_signal(
                tenant_id=event.require_tenant_id(),
                signal_type="content.created",
                source=self.source,
                severity="info",
                entity_type=event.resource_type or "content",
                entity_id=event.resource_id,
                occurred_at=event.occurred_at,
                metadata={"title": event.title, "payload": event.payload or {}},
                signal_id=event.event_id,
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        ]
