"""Shared types and constants for Marketing Intelligence Platform."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# Scoring / recommendation engine versions (deterministic, bump on rule changes).
SCORING_ENGINE_VERSION = "1.4.0"
RECOMMENDATION_ENGINE_VERSION = "1.4.0"
EXPLANATION_ENGINE_VERSION = "1.0.0"

# Lookback windows (days) for score computation.
SCORE_LOOKBACK_DAYS = 30
SIGNAL_COUNT_LOOKBACK_DAYS = 7

# Default confidence when mapping platform events → signals.
DEFAULT_SIGNAL_CONFIDENCE = Decimal("1.000")

# Category weights for overall marketing score (must sum ≈ 1.0).
SCORE_WEIGHTS: dict[str, Decimal] = {
    "publishing": Decimal("0.1800"),
    "advertising": Decimal("0.0800"),
    "crm": Decimal("0.1800"),
    "automation": Decimal("0.1000"),
    "workflow": Decimal("0.1000"),
    "customer_success": Decimal("0.1200"),
    "brand": Decimal("0.0800"),
    "content": Decimal("0.1600"),
}

# Canonical signal types produced by collectors.
SIGNAL_TYPES = frozenset({
    "publishing.completed",
    "publishing.failed",
    "publishing.partial_failed",
    "publishing.review_completed",
    "publishing.score_low",
    "publishing.critical_issue_detected",
    "publishing.platform_fit_low",
    "publishing.review_became_stale",
    "publishing.variant_generated",
    "publishing.variant_score_improved",
    "publishing.variant_score_declined",
    "publishing.variant_applied",
    "publishing.optimizer_failed",
    "ai.content_adaptation_completed",
    "ai.content_adaptation_failed",
    "ai.factual_validation_failed",
    "ai.quota_exceeded",
    "ai.variant_score_improved",
    "ai.variant_score_declined",
    "ai.variant_applied",
    "brand.profile_published",
    "crm.lead_created",
    "crm.deal_stage_changed",
    "crm.deal_won",
    "crm.deal_lost",
    "crm.buyer_created",
    "campaign.started",
    "campaign.stopped",
    "integration.disconnected",
    "workflow.executed",
    "automation.triggered",
    "automation.retried",
    "notification.created",
    "customer_success.milestone",
    "content.created",
    "onboarding.step_completed",
    "onboarding.platform_ready",
    "campaign.created",
    "campaign.plan_generated",
    "campaign.plan_published",
    "campaign.coverage_low",
    "campaign.readiness_low",
    "campaign.conflicts_detected",
    "campaign.unassigned_slots_high",
    "campaign.pillar_imbalance",
    "campaign.ai_plan_completed",
    "campaign.ai_plan_failed",
    "measurement.snapshot_ingested",
    "measurement.snapshot_failed",
    "measurement.metrics_stale",
    "measurement.anomaly_detected",
    "publication.performance_above_baseline",
    "publication.performance_below_baseline",
    "campaign.kpi_progress_updated",
    "campaign.measurement_incomplete",
    "campaign.attribution_low",
    "integration.metrics_collection_blocked",
    "publication.registered",
    "attribution.recorded",
})

# Map platform event types → collector domain.
PLATFORM_EVENT_TO_SOURCE: dict[str, str] = {
    "tenant.content.published": "publishing",
    "tenant.content.publish_failed": "publishing",
    "tenant.content.publish_partial_failed": "publishing",
    "tenant.publishing.review_completed": "publishing",
    "tenant.publishing.score_low": "publishing",
    "tenant.publishing.critical_issue_detected": "publishing",
    "tenant.publishing.platform_fit_low": "publishing",
    "tenant.publishing.review_became_stale": "publishing",
    "tenant.publishing.optimization_requested": "publishing",
    "tenant.publishing.variant_generated": "publishing",
    "tenant.publishing.variant_accepted": "publishing",
    "tenant.publishing.variant_rejected": "publishing",
    "tenant.publishing.variant_applied": "publishing",
    "tenant.publishing.variant_stale": "publishing",
    "tenant.publishing.optimization_failed": "publishing",
    "ai.content_adaptation_requested": "publishing",
    "ai.content_adaptation_completed": "publishing",
    "ai.content_adaptation_failed": "publishing",
    "ai.content_validation_failed": "publishing",
    "ai.quota_exceeded": "publishing",
    "ai.variant_generated": "publishing",
    "ai.variant_accepted": "publishing",
    "ai.variant_rejected": "publishing",
    "ai.variant_applied": "publishing",
    "brand.profile_published": "brand",
    "tenant.content.created": "content",
    "tenant.crm.lead_created": "crm",
    "tenant.crm.deal_stage_changed": "crm",
    "tenant.buyer.created": "crm",
    "tenant.automation.triggered": "automation",
    "tenant.notification.sent": "notification",
    "tenant.customer_success.milestone": "customer_success",
    "tenant.integration.disconnected": "integration",
    "tenant.onboarding.step_completed": "onboarding",
    "tenant.onboarding.platform_ready": "onboarding",
    "campaign.created": "content",
    "campaign.updated": "content",
    "campaign.archived": "content",
    "campaign.plan_generated": "content",
    "campaign.plan_reviewed": "content",
    "campaign.plan_published": "content",
    "campaign.slot_assigned": "content",
    "campaign.slot_blocked": "content",
    "campaign.gap_detected": "content",
    "campaign.ai_plan_requested": "content",
    "campaign.ai_plan_completed": "content",
    "campaign.ai_plan_failed": "content",
    "campaign.ai_plan_applied": "content",
    "publication.registered": "content",
    "publication.metrics_ingested": "content",
    "publication.metrics_failed": "content",
    "publication.metrics_stale": "content",
    "publication.measurement_anomaly_detected": "content",
    "campaign.metrics_updated": "content",
    "campaign.kpi_progress_updated": "content",
    "attribution.recorded": "content",
    "attribution.updated": "content",
    "tracked_link.created": "content",
}


@dataclass(frozen=True)
class NormalizedSignal:
    """Immutable in-memory representation of a marketing signal before persistence."""

    signal_id: UUID
    tenant_id: UUID
    signal_type: str
    entity_type: str | None
    entity_id: str | None
    occurred_at: datetime
    metadata: dict[str, Any]
    source: str
    severity: str
    confidence: Decimal
    platform_event_id: UUID | None = None
    platform_event_type: str | None = None


@dataclass
class ScoreResult:
    category: str
    score: int
    weight: Decimal
    scoring_version: str
    explanation: dict[str, Any]
    evidence: dict[str, Any]


@dataclass
class RecommendationResult:
    recommendation_key: str
    category: str
    title: str
    reason: str
    evidence: dict[str, Any]
    explanation: dict[str, Any]
    confidence: Decimal
    priority: str
    rule_id: str
    rule_version: str
    action_url: str | None = None


@dataclass
class Explanation:
    """Structured explanation: observation → evidence → reasoning → recommendation."""

    observation: str
    evidence: list[str] = field(default_factory=list)
    reasoning: str = ""
    recommendation: str | None = None
    engine_version: str = EXPLANATION_ENGINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation,
            "evidence": list(self.evidence),
            "reasoning": self.reasoning,
            "recommendation": self.recommendation,
            "engine_version": self.engine_version,
        }
