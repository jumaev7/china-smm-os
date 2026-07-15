"""Automation signal collector."""
from __future__ import annotations

from decimal import Decimal

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal


class AutomationCollector(SignalCollector):
    name = "automation"
    source = "automation"
    event_types = frozenset({"tenant.automation.triggered"})

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        payload = event.payload or {}
        is_retry = bool(
            payload.get("is_retry")
            or payload.get("retry")
            or (isinstance(payload.get("attempt"), int) and payload["attempt"] > 1)
            or payload.get("job_status") == "retrying"
        )
        signal_type = "automation.retried" if is_retry else "automation.triggered"
        severity = "warning" if is_retry else "info"
        return [
            normalize_signal(
                tenant_id=event.require_tenant_id(),
                signal_type=signal_type,
                source=self.source,
                severity=severity,
                confidence=Decimal("1.000"),
                entity_type=event.resource_type or "automation",
                entity_id=event.resource_id,
                occurred_at=event.occurred_at,
                metadata={"title": event.title, "payload": payload, "is_retry": is_retry},
                signal_id=event.event_id,
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        ]
