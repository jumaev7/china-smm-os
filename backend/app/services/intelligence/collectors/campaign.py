"""Campaign Planner signal collector — maps campaign.* events to MIP signals."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal

_EVENT_MAP = {
    "campaign.created": ("campaign.created", "info", Decimal("1.000")),
    "campaign.plan_generated": ("campaign.plan_generated", "info", Decimal("1.000")),
    "campaign.plan_published": ("campaign.plan_published", "success", Decimal("1.000")),
    "campaign.ai_plan_completed": ("campaign.ai_plan_completed", "success", Decimal("1.000")),
    "campaign.ai_plan_failed": ("campaign.ai_plan_failed", "error", Decimal("1.000")),
}

_SAFE_KEYS = frozenset({
    "campaign_id",
    "plan_version_id",
    "review_id",
    "request_id",
    "generation_id",
    "version",
    "status",
    "slot_count",
    "coverage_score",
    "readiness_score",
    "conflict_count",
    "gap_count",
    "unassigned_slots",
    "assigned_slots",
    "blocked_slots",
    "total_slots",
    "unassigned_ratio",
    "pillar_imbalance",
    "coverage_low",
    "readiness_low",
    "unassigned_slots_high",
    "generation_method",
    "plan_fingerprint",
    "planner_version",
    "model_alias",
    "prompt_version",
    "token_usage",
    "estimated_cost_minor",
    "failure_code",
    "slot_hint_count",
    "platform_count",
    "locale_count",
    "has_date_range",
    "gap_types",
    "high_severity_count",
    "engine_version",
})


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in _SAFE_KEYS}


class CampaignCollector(SignalCollector):
    name = "campaign"
    source = "content"
    event_types = frozenset({
        "campaign.created",
        "campaign.updated",
        "campaign.archived",
        "campaign.plan_generated",
        "campaign.plan_reviewed",
        "campaign.plan_published",
        "campaign.slot_assigned",
        "campaign.slot_blocked",
        "campaign.gap_detected",
        "campaign.ai_plan_requested",
        "campaign.ai_plan_completed",
        "campaign.ai_plan_failed",
        "campaign.ai_plan_applied",
    })

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        signals: list[NormalizedSignal] = []
        payload = event.payload or {}
        meta = {"title": event.title, "payload": _safe_payload(payload)}

        mapped = _EVENT_MAP.get(event.event_type)
        if mapped:
            signal_type, severity, confidence = mapped
            signals.append(
                normalize_signal(
                    tenant_id=event.require_tenant_id(),
                    signal_type=signal_type,
                    source=self.source,
                    severity=severity,
                    confidence=confidence,
                    entity_type=event.resource_type or "campaign",
                    entity_id=event.resource_id,
                    occurred_at=event.occurred_at,
                    metadata=meta,
                    signal_id=event.event_id,
                    platform_event_id=event.event_id,
                    platform_event_type=event.event_type,
                )
            )

        # Derive advisory signals from plan_reviewed payload.
        if event.event_type == "campaign.plan_reviewed":
            derived = [
                ("coverage_low", "campaign.coverage_low", "warning"),
                ("readiness_low", "campaign.readiness_low", "warning"),
                ("unassigned_slots_high", "campaign.unassigned_slots_high", "warning"),
                ("pillar_imbalance", "campaign.pillar_imbalance", "info"),
            ]
            for flag, signal_type, severity in derived:
                if payload.get(flag):
                    signals.append(
                        normalize_signal(
                            tenant_id=event.require_tenant_id(),
                            signal_type=signal_type,
                            source=self.source,
                            severity=severity,
                            confidence=Decimal("1.000"),
                            entity_type=event.resource_type or "campaign",
                            entity_id=event.resource_id,
                            occurred_at=event.occurred_at,
                            metadata=meta,
                            signal_id=None,
                            platform_event_id=event.event_id,
                            platform_event_type=event.event_type,
                        )
                    )
            if int(payload.get("conflict_count") or 0) >= 1:
                signals.append(
                    normalize_signal(
                        tenant_id=event.require_tenant_id(),
                        signal_type="campaign.conflicts_detected",
                        source=self.source,
                        severity="warning",
                        confidence=Decimal("1.000"),
                        entity_type=event.resource_type or "campaign",
                        entity_id=event.resource_id,
                        occurred_at=event.occurred_at,
                        metadata=meta,
                        signal_id=None,
                        platform_event_id=event.event_id,
                        platform_event_type=event.event_type,
                    )
                )

        return signals
