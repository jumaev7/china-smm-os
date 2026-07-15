"""Notification signal collector."""
from __future__ import annotations

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal


class NotificationCollector(SignalCollector):
    name = "notification"
    source = "notification"
    event_types = frozenset({"tenant.notification.sent"})

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        payload = event.payload or {}
        return [
            normalize_signal(
                tenant_id=event.require_tenant_id(),
                signal_type="notification.created",
                source=self.source,
                severity=str(payload.get("severity") or "info"),
                entity_type=event.resource_type or "notification",
                entity_id=event.resource_id,
                occurred_at=event.occurred_at,
                metadata={"title": event.title, "payload": payload},
                signal_id=event.event_id,
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        ]
