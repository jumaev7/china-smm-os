"""Smart Publishing Phase 3 — Campaign Planner (tenant-scoped).

New tenant-scoped campaign planning domain. This is intentionally separate from
the legacy client-scoped ``Campaign`` model (``campaigns`` table / ``/api/v1/campaigns``)
which MUST remain untouched. All tables here are prefixed ``tenant_`` and keyed by
``tenant_id``.

Design notes:
- Plans are versioned; a *published* plan version is immutable.
- Calendar slots carry deterministic, rule-based suggested times (never "optimal").
- Slot assignment is advisory only — it never schedules or publishes content.
- Publishing Score is advisory; PublishSafetyService remains authoritative.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# ---------------------------------------------------------------------------
# Enums / constants (frozensets — server controlled)
# ---------------------------------------------------------------------------

PLANNER_VERSION = "1.0.0"
POLICY_VERSION = "1.0.0"

CAMPAIGN_STATUSES = frozenset({
    "draft",
    "planning",
    "approved",
    "active",
    "paused",
    "completed",
    "archived",
})

# Terminal / non-editable campaign states for mutation guards.
CAMPAIGN_TERMINAL_STATUSES = frozenset({"completed", "archived"})

PLAN_VERSION_STATUSES = frozenset({
    "draft",
    "reviewed",
    "published",
    "superseded",
    "archived",
})

# A published plan version is immutable and authoritative for its campaign.
PLAN_IMMUTABLE_STATUSES = frozenset({"published", "superseded", "archived"})

GENERATION_METHODS = frozenset({"deterministic", "ai_assisted"})

SLOT_STATUSES = frozenset({
    "unassigned",
    "assigned",
    "ready",
    "ready_with_warnings",
    "blocked",
    "skipped",
})

ASSIGNMENT_STATUSES = frozenset({
    "assigned",
    "ready",
    "ready_with_warnings",
    "blocked",
    "skipped",
})

ASSIGNMENT_TYPES = frozenset({
    "content",
    "deterministic_variant",
    "ai_variant",
})

# Advisory readiness classifications (PublishSafety remains authoritative).
READINESS_STATUSES = frozenset({
    "ready",
    "ready_with_warnings",
    "blocked",
    "unknown",
})

GOAL_TYPES = frozenset({
    "awareness",
    "engagement",
    "traffic",
    "leads",
    "conversion",
    "retention",
    "launch",
    "recruitment",
    "other",
})

PHASE_TYPES = frozenset({
    "teaser",
    "launch",
    "sustain",
    "conversion",
    "wind_down",
    "custom",
})

REVIEW_TYPES = frozenset({
    "coverage",
    "readiness",
    "gap",
    "plan",
})

GAP_TYPES = frozenset({
    "unfilled_slot",
    "pillar_underrepresented",
    "locale_missing",
    "platform_missing",
    "phase_empty",
    "stale_content",
    "blocked_account",
    "same_day_conflict",
})

GAP_SEVERITIES = frozenset({"info", "low", "medium", "high", "critical"})

GAP_STATUSES = frozenset({"open", "resolved", "ignored"})

RECOMMENDATION_PRIORITIES = frozenset({"low", "medium", "high", "critical"})

RECOMMENDATION_STATUSES = frozenset({"open", "acknowledged", "dismissed", "resolved"})

SUPPORTED_PLATFORMS = frozenset({"telegram", "facebook", "instagram", "tiktok", "linkedin"})
SUPPORTED_LOCALES = frozenset({"en", "ru", "uz", "zh"})


# ---------------------------------------------------------------------------
# Core campaign
# ---------------------------------------------------------------------------


class TenantMarketingCampaign(Base):
    __tablename__ = "tenant_marketing_campaigns"
    __table_args__ = (
        Index("ix_tenant_marketing_campaigns_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_marketing_campaigns_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    objective: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    primary_locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    locales: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    platforms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    blackout_dates: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    cadence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    brand_profile_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    current_plan_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    published_plan_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    planner_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=PLANNER_VERSION)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=POLICY_VERSION)
    metadata_json: Mapped[dict | None] = mapped_column("metadata_json", JSONB(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantCampaignGoal(Base):
    __tablename__ = "tenant_campaign_goals"
    __table_args__ = (
        Index("ix_tenant_campaign_goals_tenant_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    goal_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="other")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, server_default="medium")
    target_metric: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantCampaignKpi(Base):
    __tablename__ = "tenant_campaign_kpis"
    __table_args__ = (
        Index("ix_tenant_campaign_kpis_tenant_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    target_value: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    comparator: Mapped[str] = mapped_column(String(10), nullable=False, server_default=">=")
    timeframe: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantCampaignAudience(Base):
    __tablename__ = "tenant_campaign_audiences"
    __table_args__ = (
        Index("ix_tenant_campaign_audiences_tenant_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    platforms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    segment: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


# ---------------------------------------------------------------------------
# Content pillars (tenant-reusable) and campaign pillar weights
# ---------------------------------------------------------------------------


class TenantContentPillar(Base):
    __tablename__ = "tenant_content_pillars"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_tenant_content_pillars_tenant_slug"),
        Index("ix_tenant_content_pillars_tenant_active", "tenant_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    default_weight: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantCampaignPillar(Base):
    __tablename__ = "tenant_campaign_pillars"
    __table_args__ = (
        UniqueConstraint("campaign_id", "pillar_id", name="uq_tenant_campaign_pillars_campaign_pillar"),
        Index("ix_tenant_campaign_pillars_tenant_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    pillar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_content_pillars.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    weight: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantCampaignPhase(Base):
    __tablename__ = "tenant_campaign_phases"
    __table_args__ = (
        Index("ix_tenant_campaign_phases_tenant_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phase_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="custom")
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    weight: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


# ---------------------------------------------------------------------------
# Plan versions, calendar slots, assignments
# ---------------------------------------------------------------------------


class TenantCampaignPlanVersion(Base):
    """A generated plan version. Published versions are immutable."""

    __tablename__ = "tenant_campaign_plan_versions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version", name="uq_tenant_campaign_plan_versions_campaign_version"),
        Index("ix_tenant_campaign_plan_versions_tenant_campaign", "tenant_id", "campaign_id"),
        Index("ix_tenant_campaign_plan_versions_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    generation_method: Mapped[str] = mapped_column(String(40), nullable=False, server_default="deterministic")
    plan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    planner_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=PLANNER_VERSION)
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=POLICY_VERSION)
    parameters: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    source_ai_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    slot_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantCampaignCalendarSlot(Base):
    __tablename__ = "tenant_campaign_calendar_slots"
    __table_args__ = (
        Index("ix_tenant_campaign_calendar_slots_tenant_plan", "tenant_id", "plan_version_id"),
        Index("ix_tenant_campaign_calendar_slots_plan_date", "plan_version_id", "scheduled_date"),
        Index(
            "ix_tenant_campaign_calendar_slots_plan_platform_dt",
            "plan_version_id", "platform", "scheduled_date", "scheduled_time",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    plan_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    slot_index: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    pillar_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    phase_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scheduled_date: Mapped[date] = mapped_column(Date(), nullable=False)
    scheduled_time: Mapped[time] = mapped_column(Time(), nullable=False)
    suggested_time_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unassigned")
    slot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantCampaignSlotAssignment(Base):
    __tablename__ = "tenant_campaign_slot_assignments"
    __table_args__ = (
        UniqueConstraint("slot_id", name="uq_tenant_campaign_slot_assignments_slot"),
        Index("ix_tenant_campaign_slot_assignments_tenant_campaign", "tenant_id", "campaign_id"),
        Index("ix_tenant_campaign_slot_assignments_tenant_content", "tenant_id", "content_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    plan_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_calendar_slots.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assignment_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="content")
    assigned_platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assigned_locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    assignment_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="assigned")
    readiness_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    readiness_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    publishing_review_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


# ---------------------------------------------------------------------------
# Reviews, gaps, recommendations
# ---------------------------------------------------------------------------


class TenantCampaignReview(Base):
    __tablename__ = "tenant_campaign_reviews"
    __table_args__ = (
        Index("ix_tenant_campaign_reviews_tenant_campaign", "tenant_id", "campaign_id"),
        Index("ix_tenant_campaign_reviews_plan_created", "plan_version_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    review_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="plan")
    coverage_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    readiness_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    total_slots: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    assigned_slots: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    blocked_slots: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    unassigned_slots: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    conflict_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    gap_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=PLANNER_VERSION)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantCampaignGap(Base):
    __tablename__ = "tenant_campaign_gaps"
    __table_args__ = (
        Index("ix_tenant_campaign_gaps_tenant_campaign", "tenant_id", "campaign_id"),
        Index("ix_tenant_campaign_gaps_review", "review_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_reviews.id", ondelete="CASCADE"),
        nullable=True,
    )
    gap_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="medium")
    dimension: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dimension_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantCampaignRecommendation(Base):
    __tablename__ = "tenant_campaign_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "campaign_id", "recommendation_key",
            name="uq_tenant_campaign_recommendations_key",
        ),
        Index("ix_tenant_campaign_recommendations_tenant_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recommendation_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, server_default="campaign")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, server_default="medium")
    rule_id: Mapped[str] = mapped_column(String(120), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default=PLANNER_VERSION)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open")
    action_url: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
