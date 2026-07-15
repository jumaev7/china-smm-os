"""Workflow signal collector.

Maps automation/workflow-related platform events into workflow.executed signals.
Dedicated workflow execution bus events can be added later without changing the store.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal


class WorkflowCollector(SignalCollector):
    name = "workflow"
    source = "workflow"
    event_types = frozenset({"tenant.automation.triggered"})

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        payload = event.payload or {}
        # Only emit workflow.executed when the payload indicates a workflow (not simple automation).
        kind = str(payload.get("execution_kind") or payload.get("kind") or "").lower()
        has_workflow = bool(
            payload.get("workflow_id")
            or payload.get("workflow_key")
            or kind in {"workflow", "event", "test"}
        )
        if not has_workflow:
            return []
        return [
            normalize_signal(
                tenant_id=event.require_tenant_id(),
                signal_type="workflow.executed",
                source=self.source,
                severity="info",
                confidence=Decimal("0.850"),
                entity_type=event.resource_type or "workflow",
                entity_id=event.resource_id or str(payload.get("workflow_id") or ""),
                occurred_at=event.occurred_at,
                metadata={"title": event.title, "payload": payload},
                signal_id=uuid5(NAMESPACE_URL, f"mip:workflow:{event.event_id}"),
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        ]
