"""Shared types and constants for Marketing Intelligence Platform."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# Scoring / recommendation engine versions (deterministic, bump on rule changes).
SCORING_ENGINE_VERSION = "1.2.0"
RECOMMENDATION_ENGINE_VERSION = "1.2.0"
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
