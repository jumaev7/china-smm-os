"""Publishing signal collector."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal

_EVENT_MAP = {
    "tenant.content.published": ("publishing.completed", "success", Decimal("1.000")),
    "tenant.content.publish_failed": ("publishing.failed", "error", Decimal("1.000")),
    "tenant.content.publish_partial_failed": ("publishing.partial_failed", "warning", Decimal("0.950")),
    "tenant.publishing.review_completed": ("publishing.review_completed", "info", Decimal("1.000")),
    "tenant.publishing.score_low": ("publishing.score_low", "warning", Decimal("1.000")),
    "tenant.publishing.critical_issue_detected": (
        "publishing.critical_issue_detected",
        "error",
        Decimal("1.000"),
    ),
    "tenant.publishing.platform_fit_low": ("publishing.platform_fit_low", "warning", Decimal("1.000")),
    "tenant.publishing.review_became_stale": ("publishing.review_became_stale", "info", Decimal("1.000")),
}

# Safe metadata keys for review signals — never include caption text.
_SAFE_REVIEW_KEYS = frozenset({
    "content_id",
    "review_id",
    "overall_score",
    "platform_scores",
    "warning_count",
    "failure_count",
    "critical_issue_count",
    "review_engine_version",
    "review_version",
    "low_fit_platforms",
})


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in _SAFE_REVIEW_KEYS}


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
        if event.event_type.startswith("tenant.publishing."):
            meta: dict[str, Any] = {
                "title": event.title,
                "payload": _safe_payload(payload),
            }
        else:
            meta = {
                "title": event.title,
                "description": event.description,
                "payload": payload,
            }
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
                metadata=meta,
                signal_id=event.event_id,
                platform_event_id=event.event_id,
                platform_event_type=event.event_type,
            )
        ]
