"""Advertising signal collector — maps advertising.* events to MIP signals.

Deterministic, evidence-only. Never emits recommendations directly; it produces
normalized signals that the recommendation engine consumes.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal

# event_type -> (signal_type, severity, confidence)
_EVENT_MAP: dict[str, tuple[str, str, Decimal]] = {
    "advertising.account_connected": ("advertising.account_connected", "info", Decimal("1.000")),
    "advertising.account_disconnected": ("advertising.account_disconnected", "warning", Decimal("1.000")),
    "advertising.entities_imported": ("advertising.entities_imported", "info", Decimal("1.000")),
    "advertising.import_failed": ("advertising.import_failed", "error", Decimal("1.000")),
    "advertising.insights_ingested": ("advertising.insights_ingested", "info", Decimal("1.000")),
    "advertising.insights_failed": ("advertising.insights_failed", "error", Decimal("1.000")),
    "advertising.metrics_stale": ("advertising.metrics_stale", "warning", Decimal("1.000")),
    "advertising.delivery_issue_detected": ("advertising.delivery_issue", "warning", Decimal("1.000")),
    "advertising.creative_fatigue_detected": ("advertising.creative_fatigue", "warning", Decimal("1.000")),
    "advertising.attribution_recorded": ("advertising.attribution_recorded", "info", Decimal("1.000")),
}

# Budget pacing alerts carry a ``pacing_status`` in the payload that determines
# the emitted signal type (deterministic, evidence-backed).
_PACING_SIGNAL_BY_STATUS = {
    # Canonical model pacing vocab (see app.models.advertising.PACING_STATUSES).
    "underspending": "advertising.budget_underspending",
    "overspending": "advertising.budget_overspending",
    "budget_exhausted": "advertising.budget_exhausted",
}

_RECONCILIATION_SIGNAL_BY_STATUS = {
    "discrepant": "advertising.conversion_discrepant",
}

_SAFE_KEYS = frozenset({
    "ad_account_id",
    "ad_entity_id",
    "entity_type",
    "provider",
    "provider_entity_id",
    "import_run_id",
    "snapshot_id",
    "entities_upserted",
    "entities_failed",
    "entity_count",
    "metric_count",
    "conversion_count",
    "snapshot_count",
    "currency",
    "status",
    "is_mock",
    "failure_code",
    "capability_status",
    "pacing_status",
    "pace_ratio",
    "diagnostic_key",
    "diagnostic_keys",
    "fatigue_status",
    "attribution_method",
    "reconciliation_status",
    "confidence",
    "campaign_id",
})


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in _SAFE_KEYS}


class AdvertisingCollector(SignalCollector):
    name = "advertising"
    source = "advertising"
    event_types = frozenset({
        "advertising.account_connected",
        "advertising.account_disconnected",
        "advertising.entities_imported",
        "advertising.import_failed",
        "advertising.insights_ingested",
        "advertising.insights_failed",
        "advertising.metrics_stale",
        "advertising.budget_pacing_alert",
        "advertising.delivery_issue_detected",
        "advertising.creative_fatigue_detected",
        "advertising.attribution_recorded",
        "advertising.conversion_reconciled",
    })

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        signals: list[NormalizedSignal] = []
        payload = event.payload or {}
        meta = {"title": event.title, "payload": _safe_payload(payload)}

        signal_type: str | None = None
        severity = "info"
        confidence = Decimal("1.000")

        mapped = _EVENT_MAP.get(event.event_type)
        if mapped:
            signal_type, severity, confidence = mapped
        elif event.event_type == "advertising.budget_pacing_alert":
            status = str(payload.get("pacing_status") or "")
            signal_type = _PACING_SIGNAL_BY_STATUS.get(status)
            severity = "warning"
        elif event.event_type == "advertising.conversion_reconciled":
            status = str(payload.get("reconciliation_status") or "")
            signal_type = _RECONCILIATION_SIGNAL_BY_STATUS.get(status)
            severity = "warning"

        if signal_type is None:
            return signals

        signals.append(
            normalize_signal(
                tenant_id=event.require_tenant_id(),
                signal_type=signal_type,
                source=self.source,
                severity=severity,
                confidence=confidence,
                entity_type=event.resource_type or "ad_entity",
                entity_id=event.resource_id,
                occurred_at=event.occurred_at,
                metadata=meta,
                signal_id=event.event_id,
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        )
        return signals


__all__ = ["AdvertisingCollector"]
