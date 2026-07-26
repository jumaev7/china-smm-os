"""Advertising Intelligence Phase 2 — Decision Support domain models.

Governed advisory / simulation / experiment-planning storage. This domain NEVER
mutates provider campaigns, budgets, bids, targeting, creatives, or schedules.
Simulations, experiments, and change plans are internal planning artifacts only.

Design notes:
- READ-ONLY toward providers. No executable provider payloads.
- Money is integer minor units + explicit currency; never silently mixed.
- Engine versions are persisted on every run for auditability.
- Experiment ``running_observation`` means we observe externally executed
  entities — China SMM OS does not launch provider experiments.
- Change-plan lifecycle stops at draft/reviewed/dismissed/archived — no
  approved_for_execution / executed / provider_synced states.
- NO secrets. Provider tokens are never stored here.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DECISION_SUPPORT_VERSION = "1.0.0"
COMPARISON_ENGINE_VERSION = "1.0.0"
BUDGET_SIMULATION_ENGINE_VERSION = "1.0.0"
PACING_PROJECTION_ENGINE_VERSION = "1.0.0"
CONCENTRATION_ENGINE_VERSION = "1.0.0"
DIMINISHING_RETURNS_ENGINE_VERSION = "1.0.0"
CREATIVE_ROTATION_ENGINE_VERSION = "1.0.0"
EXPERIMENT_PLANNER_ENGINE_VERSION = "1.0.0"
RECOMMENDATION_ENGINE_VERSION = "1.0.0"
EXPLANATION_ENGINE_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Experiment vocabulary
# ---------------------------------------------------------------------------
EXPERIMENT_TYPES = frozenset({
    "creative_comparison",
    "audience_comparison",
    "placement_comparison",
    "campaign_structure_comparison",
    "landing_page_comparison",
})

EXPERIMENT_STATUSES = frozenset({
    "draft",
    "ready",
    "running_observation",
    "completed",
    "cancelled",
    "archived",
})

EXPERIMENT_RESULT_STATUSES = frozenset({
    "insufficient_data",
    "collecting",
    "directional",
    "inconclusive",
    "completed",
})

# ---------------------------------------------------------------------------
# Change plan vocabulary
# ---------------------------------------------------------------------------
CHANGE_PLAN_STATUSES = frozenset({
    "draft",
    "reviewed",
    "dismissed",
    "archived",
})

CHANGE_PLAN_ITEM_TYPES = frozenset({
    "review_budget_allocation",
    "review_creative_rotation",
    "review_campaign_structure",
    "review_audience_split",
    "review_tracking",
    "review_pacing",
    "review_underperforming_entity",
    "review_experiment_result",
})

# ---------------------------------------------------------------------------
# Diagnostic classification vocabularies
# ---------------------------------------------------------------------------
CONCENTRATION_STATUSES = frozenset({
    "diversified",
    "moderately_concentrated",
    "highly_concentrated",
    "insufficient_data",
})

DIMINISHING_RETURN_STATUSES = frozenset({
    "no_evidence",
    "possible_diminishing_efficiency",
    "stable",
    "insufficient_data",
})

CREATIVE_ROTATION_STATUSES = frozenset({
    "healthy_rotation",
    "concentrated",
    "possible_fatigue",
    "insufficient_data",
})

COMPARABLE_ENTITY_TYPES = frozenset({"campaign", "ad_group", "ad", "creative"})


class TenantAdBudgetSimulation(Base):
    """Immutable hypothetical budget allocation simulation run.

    Does NOT modify real campaign budgets. Stores user-entered assumptions and
    mechanical projections alongside observed reference metrics.
    """

    __tablename__ = "tenant_ad_budget_simulations"
    __table_args__ = (
        Index("ix_tenant_ad_budget_simulations_tenant_created", "tenant_id", "created_at"),
        Index("ix_tenant_ad_budget_simulations_tenant_currency", "tenant_id", "currency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_budget_minor: Mapped[int] = mapped_column(Integer(), nullable=False)
    measurement_window_key: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="lifetime",
    )
    window_start: Mapped[date | None] = mapped_column(Date(), nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date(), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    assumptions_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    warnings_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    disclaimer: Mapped[str] = mapped_column(
        Text(),
        nullable=False,
        server_default=(
            "Simulation does not predict future advertising performance "
            "and does not modify provider budgets."
        ),
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdBudgetSimulationItem(Base):
    """Per-campaign row inside an immutable budget simulation."""

    __tablename__ = "tenant_ad_budget_simulation_items"
    __table_args__ = (
        UniqueConstraint(
            "simulation_id", "campaign_id",
            name="uq_tenant_ad_budget_simulation_items_campaign",
        ),
        Index("ix_tenant_ad_budget_simulation_items_sim", "tenant_id", "simulation_id"),
        Index("ix_tenant_ad_budget_simulation_items_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    simulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_budget_simulations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    observed_spend_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    observed_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    allocation_pct: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    simulated_budget_minor: Mapped[int] = mapped_column(Integer(), nullable=False)
    simulated_share: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    historical_reference_metrics: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    freshness_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    warnings_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdExperiment(Base):
    """Internal advertising experiment plan (observation only — not provider-launched)."""

    __tablename__ = "tenant_ad_experiments"
    __table_args__ = (
        Index("ix_tenant_ad_experiments_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_ad_experiments_tenant_created", "tenant_id", "created_at"),
        Index("ix_tenant_ad_experiments_tenant_type", "tenant_id", "experiment_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    experiment_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="draft")
    hypothesis: Mapped[str] = mapped_column(Text(), nullable=False)
    primary_metric_key: Mapped[str] = mapped_column(String(80), nullable=False)
    secondary_metric_keys: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    observation_start: Mapped[date | None] = mapped_column(Date(), nullable=True)
    observation_end: Mapped[date | None] = mapped_column(Date(), nullable=True)
    minimum_observations: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="100")
    minimum_spend_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    minimum_conversions: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    attribution_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    result_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    observation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantAdExperimentVariant(Base):
    """A named variant linked to one or more advertising entities."""

    __tablename__ = "tenant_ad_experiment_variants"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "variant_key",
            name="uq_tenant_ad_experiment_variants_key",
        ),
        Index("ix_tenant_ad_experiment_variants_exp", "tenant_id", "experiment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_experiments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    variant_key: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdExperimentMeasurement(Base):
    """Immutable measurement snapshot for an experiment variant (observed metrics)."""

    __tablename__ = "tenant_ad_experiment_measurements"
    __table_args__ = (
        Index("ix_tenant_ad_experiment_measurements_exp", "tenant_id", "experiment_id"),
        Index("ix_tenant_ad_experiment_measurements_variant", "tenant_id", "variant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_experiments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_experiment_variants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    spend_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    impressions: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    clicks: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    conversions: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    freshness_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attribution_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    warnings_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdExperimentReview(Base):
    """Human review record for an experiment (advisory conclusion only)."""

    __tablename__ = "tenant_ad_experiment_reviews"
    __table_args__ = (
        Index("ix_tenant_ad_experiment_reviews_exp", "tenant_id", "experiment_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_experiments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    result_status: Mapped[str] = mapped_column(String(40), nullable=False)
    conclusion: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    limitations_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdChangePlan(Base):
    """Reviewable proposed change plan — recommendations ONLY, never executable."""

    __tablename__ = "tenant_ad_change_plans"
    __table_args__ = (
        Index("ix_tenant_ad_change_plans_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_ad_change_plans_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="draft")
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantAdChangePlanItem(Base):
    """Single advisory item inside a change plan. No provider command payload."""

    __tablename__ = "tenant_ad_change_plan_items"
    __table_args__ = (
        Index("ix_tenant_ad_change_plan_items_plan", "tenant_id", "change_plan_id"),
        Index("ix_tenant_ad_change_plan_items_entity", "tenant_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    change_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_change_plans.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    observation: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    reasoning: Mapped[str] = mapped_column(Text(), nullable=False)
    suggested_human_action: Mapped[str] = mapped_column(Text(), nullable=False)
    risk: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 3), nullable=True)
    supporting_metrics: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    # Explicitly absent by design: provider_payload / executable_command.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
