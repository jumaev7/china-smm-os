"""Measurement signal collector — maps publication/attribution events to MIP signals."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal

_EVENT_MAP = {
    "publication.metrics_ingested": ("measurement.snapshot_ingested", "info", Decimal("1.000")),
    "publication.metrics_failed": ("measurement.snapshot_failed", "error", Decimal("1.000")),
    "publication.metrics_stale": ("measurement.metrics_stale", "warning", Decimal("1.000")),
    "publication.measurement_anomaly_detected": ("measurement.anomaly_detected", "warning", Decimal("1.000")),
    "campaign.kpi_progress_updated": ("campaign.kpi_progress_updated", "info", Decimal("1.000")),
    "publication.registered": ("publication.registered", "info", Decimal("1.000")),
    "attribution.recorded": ("attribution.recorded", "info", Decimal("1.000")),
}

_SAFE_KEYS = frozenset({
    "external_publication_id",
    "publication_id",
    "snapshot_id",
    "ingestion_run_id",
    "content_id",
    "campaign_id",
    "tracked_link_id",
    "platform",
    "metric_key",
    "metric_keys",
    "metric_count",
    "publication_count",
    "anomaly_count",
    "anomaly_keys",
    "freshness_status",
    "confidence",
    "status",
    "is_mock",
    "has_assignment",
    "kpi_count",
    "statuses",
    "attribution_method",
    "entity_type",
    "entity_id",
    "target_type",
    "target_id",
    "failure_code",
    "capability_status",
})


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in _SAFE_KEYS}


class MeasurementCollector(SignalCollector):
    name = "measurement"
    source = "content"
    event_types = frozenset({
        "publication.registered",
        "publication.metrics_ingested",
        "publication.metrics_failed",
        "publication.metrics_stale",
        "publication.measurement_anomaly_detected",
        "campaign.kpi_progress_updated",
        "campaign.metrics_updated",
        "attribution.recorded",
        "attribution.updated",
        "tracked_link.created",
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
                    entity_type=event.resource_type or "external_publication",
                    entity_id=event.resource_id,
                    occurred_at=event.occurred_at,
                    metadata=meta,
                    signal_id=event.event_id,
                    platform_event_id=event.event_id,
                    platform_event_type=event.event_type,
                )
            )

        return signals
