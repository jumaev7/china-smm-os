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
    "tenant.publishing.variant_generated": ("publishing.variant_generated", "info", Decimal("1.000")),
    "tenant.publishing.variant_applied": ("publishing.variant_applied", "success", Decimal("1.000")),
    "tenant.publishing.optimization_failed": ("publishing.optimizer_failed", "error", Decimal("1.000")),
    "ai.content_adaptation_completed": ("ai.content_adaptation_completed", "success", Decimal("1.000")),
    "ai.content_adaptation_failed": ("ai.content_adaptation_failed", "error", Decimal("1.000")),
    "ai.content_validation_failed": ("ai.factual_validation_failed", "warning", Decimal("1.000")),
    "ai.quota_exceeded": ("ai.quota_exceeded", "warning", Decimal("1.000")),
    "ai.variant_applied": ("ai.variant_applied", "success", Decimal("1.000")),
    "brand.profile_published": ("brand.profile_published", "info", Decimal("1.000")),
}

# Safe metadata keys for review/optimizer signals — never include caption or template text.
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
    "optimization_run_id",
    "variant_id",
    "platform",
    "locale",
    "length_profile",
    "source_fingerprint",
    "variant_fingerprint",
    "source_score",
    "variant_score",
    "score_delta",
    "status",
    "optimizer_version",
    "policy_version",
    "failure_code",
    "request_id",
    "generation_id",
    "model_alias",
    "prompt_version",
    "brand_profile_version",
    "token_usage",
    "estimated_cost_minor",
    "validation_status",
    "task_type",
})


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    return {k: v for k, v in payload.items() if k in _SAFE_REVIEW_KEYS}


class PublishingCollector(SignalCollector):
    name = "publishing"
    source = "publishing"
    event_types = frozenset(_EVENT_MAP.keys()) | frozenset({
        # Accepted/rejected/stale/requested are registered events; collector may ignore extras.
        "tenant.publishing.variant_accepted",
        "tenant.publishing.variant_rejected",
        "tenant.publishing.variant_stale",
        "tenant.publishing.optimization_requested",
        "ai.content_adaptation_requested",
        "ai.variant_generated",
        "ai.variant_accepted",
        "ai.variant_rejected",
    })

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        mapped = _EVENT_MAP.get(event.event_type)
        signals: list[NormalizedSignal] = []
        payload = event.payload or {}

        if mapped:
            signal_type, severity, confidence = mapped
            if event.event_type.startswith("tenant.publishing.") or event.event_type.startswith("ai.") or event.event_type.startswith("brand."):
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
            signals.append(
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
            )

        # Derive score improved/declined from variant_generated without extra events.
        if event.event_type in ("tenant.publishing.variant_generated", "ai.variant_generated"):
            delta = payload.get("score_delta")
            improved_type = (
                "ai.variant_score_improved"
                if event.event_type.startswith("ai.")
                else "publishing.variant_score_improved"
            )
            declined_type = (
                "ai.variant_score_declined"
                if event.event_type.startswith("ai.")
                else "publishing.variant_score_declined"
            )
            if isinstance(delta, int) and delta > 0:
                signals.append(
                    normalize_signal(
                        tenant_id=event.require_tenant_id(),
                        signal_type=improved_type,
                        source=self.source,
                        severity="info",
                        confidence=Decimal("1.000"),
                        entity_type=event.resource_type or "content_variant",
                        entity_id=event.resource_id,
                        occurred_at=event.occurred_at,
                        metadata={"title": event.title, "payload": _safe_payload(payload)},
                        signal_id=None,
                        platform_event_id=event.event_id,
                        platform_event_type=event.event_type,
                    )
                )
            elif isinstance(delta, int) and delta < 0:
                signals.append(
                    normalize_signal(
                        tenant_id=event.require_tenant_id(),
                        signal_type=declined_type,
                        source=self.source,
                        severity="warning",
                        confidence=Decimal("1.000"),
                        entity_type=event.resource_type or "content_variant",
                        entity_id=event.resource_id,
                        occurred_at=event.occurred_at,
                        metadata={"title": event.title, "payload": _safe_payload(payload)},
                        signal_id=None,
                        platform_event_id=event.event_id,
                        platform_event_type=event.event_type,
                    )
                )

        return signals
