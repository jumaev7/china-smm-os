"""Smart Publishing Phase 3 — Campaign Planner (tenant-scoped).

Creates the tenant-scoped campaign planning domain. Deliberately isolated from the
legacy client-scoped ``campaigns`` table, which is left untouched.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    create_index_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    table_exists,
)

revision = "20260910_campaign_planner"
down_revision = "20260909_governed_ai_content"
branch_labels = None
depends_on = None


def _ts(name: str, *, default: bool = True, nullable: bool = False) -> sa.Column:
    kwargs = {"nullable": nullable}
    if default:
        kwargs["server_default"] = sa.text("now()")
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    if not table_exists("tenants"):
        return

    # ---------------------------------------------------------------- campaigns
    if not table_exists("tenant_marketing_campaigns"):
        op.create_table(
            "tenant_marketing_campaigns",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("objective", sa.String(120), nullable=True),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
            sa.Column("primary_locale", sa.String(10), nullable=False, server_default="en"),
            sa.Column("locales", JSONB(), nullable=True),
            sa.Column("platforms", JSONB(), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("blackout_dates", JSONB(), nullable=True),
            sa.Column("cadence", JSONB(), nullable=True),
            sa.Column("brand_profile_id", UUID(as_uuid=True), nullable=True),
            sa.Column("brand_profile_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("current_plan_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("published_plan_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("planner_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("policy_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            _ts("archived_at", default=False, nullable=True),
        )
    # Optional FK to brand profiles when the table exists.
    if table_exists("tenant_brand_profiles"):
        from migrations.helpers import create_foreign_key_if_missing

        create_foreign_key_if_missing(
            "fk_tenant_marketing_campaigns_brand_profile",
            "tenant_marketing_campaigns",
            "tenant_brand_profiles",
            ["brand_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
    create_index_if_missing("ix_tenant_marketing_campaigns_tenant_id", "tenant_marketing_campaigns", ["tenant_id"])
    create_index_if_missing("ix_tenant_marketing_campaigns_tenant_status", "tenant_marketing_campaigns", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_marketing_campaigns_tenant_created", "tenant_marketing_campaigns", ["tenant_id", "created_at"])

    # ------------------------------------------------------------------- goals
    if not table_exists("tenant_campaign_goals"):
        op.create_table(
            "tenant_campaign_goals",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("goal_type", sa.String(40), nullable=False, server_default="other"),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("target_metric", sa.String(120), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at"),
            _ts("updated_at"),
        )
    create_index_if_missing("ix_tenant_campaign_goals_tenant_id", "tenant_campaign_goals", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_goals_tenant_campaign", "tenant_campaign_goals", ["tenant_id", "campaign_id"])

    # -------------------------------------------------------------------- kpis
    if not table_exists("tenant_campaign_kpis"):
        op.create_table(
            "tenant_campaign_kpis",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("metric_key", sa.String(120), nullable=False),
            sa.Column("target_value", sa.Numeric(18, 4), nullable=True),
            sa.Column("unit", sa.String(40), nullable=True),
            sa.Column("comparator", sa.String(10), nullable=False, server_default=">="),
            sa.Column("timeframe", sa.String(40), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at"),
            _ts("updated_at"),
        )
    create_index_if_missing("ix_tenant_campaign_kpis_tenant_id", "tenant_campaign_kpis", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_kpis_tenant_campaign", "tenant_campaign_kpis", ["tenant_id", "campaign_id"])

    # --------------------------------------------------------------- audiences
    if not table_exists("tenant_campaign_audiences"):
        op.create_table(
            "tenant_campaign_audiences",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("locale", sa.String(10), nullable=True),
            sa.Column("platforms", JSONB(), nullable=True),
            sa.Column("segment", JSONB(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at"),
            _ts("updated_at"),
        )
    create_index_if_missing("ix_tenant_campaign_audiences_tenant_id", "tenant_campaign_audiences", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_audiences_tenant_campaign", "tenant_campaign_audiences", ["tenant_id", "campaign_id"])

    # --------------------------------------------------------- content pillars
    if not table_exists("tenant_content_pillars"):
        op.create_table(
            "tenant_content_pillars",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("slug", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("color", sa.String(20), nullable=True),
            sa.Column("default_weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint("tenant_id", "slug", name="uq_tenant_content_pillars_tenant_slug"),
        )
    create_index_if_missing("ix_tenant_content_pillars_tenant_id", "tenant_content_pillars", ["tenant_id"])
    create_index_if_missing("ix_tenant_content_pillars_tenant_active", "tenant_content_pillars", ["tenant_id", "is_active"])

    # -------------------------------------------------------- campaign pillars
    if not table_exists("tenant_campaign_pillars"):
        op.create_table(
            "tenant_campaign_pillars",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("pillar_id", UUID(as_uuid=True), sa.ForeignKey("tenant_content_pillars.id", ondelete="CASCADE"), nullable=False),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint("campaign_id", "pillar_id", name="uq_tenant_campaign_pillars_campaign_pillar"),
        )
    create_index_if_missing("ix_tenant_campaign_pillars_tenant_id", "tenant_campaign_pillars", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_pillars_tenant_campaign", "tenant_campaign_pillars", ["tenant_id", "campaign_id"])

    # ----------------------------------------------------------------- phases
    if not table_exists("tenant_campaign_phases"):
        op.create_table(
            "tenant_campaign_phases",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("phase_type", sa.String(40), nullable=False, server_default="custom"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at"),
            _ts("updated_at"),
        )
    create_index_if_missing("ix_tenant_campaign_phases_tenant_id", "tenant_campaign_phases", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_phases_tenant_campaign", "tenant_campaign_phases", ["tenant_id", "campaign_id"])

    # --------------------------------------------------------- plan versions
    if not table_exists("tenant_campaign_plan_versions"):
        op.create_table(
            "tenant_campaign_plan_versions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("generation_method", sa.String(40), nullable=False, server_default="deterministic"),
            sa.Column("plan_fingerprint", sa.String(64), nullable=False),
            sa.Column("planner_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("policy_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("parameters", JSONB(), nullable=True),
            sa.Column("summary", JSONB(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("source_ai_request_id", UUID(as_uuid=True), nullable=True),
            sa.Column("parent_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("slot_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            _ts("reviewed_at", default=False, nullable=True),
            _ts("published_at", default=False, nullable=True),
            _ts("superseded_at", default=False, nullable=True),
            sa.UniqueConstraint("campaign_id", "version", name="uq_tenant_campaign_plan_versions_campaign_version"),
        )
    create_index_if_missing("ix_tenant_campaign_plan_versions_tenant_id", "tenant_campaign_plan_versions", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_plan_versions_tenant_campaign", "tenant_campaign_plan_versions", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_campaign_plan_versions_tenant_status", "tenant_campaign_plan_versions", ["tenant_id", "status"])

    # -------------------------------------------------------- calendar slots
    if not table_exists("tenant_campaign_calendar_slots"):
        op.create_table(
            "tenant_campaign_calendar_slots",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_version_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("slot_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("platform", sa.String(40), nullable=False),
            sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
            sa.Column("pillar_id", UUID(as_uuid=True), nullable=True),
            sa.Column("phase_id", UUID(as_uuid=True), nullable=True),
            sa.Column("scheduled_date", sa.Date(), nullable=False),
            sa.Column("scheduled_time", sa.Time(), nullable=False),
            sa.Column("suggested_time_label", sa.String(80), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="unassigned"),
            sa.Column("slot_fingerprint", sa.String(64), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
        )
    create_index_if_missing("ix_tenant_campaign_calendar_slots_tenant_id", "tenant_campaign_calendar_slots", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_calendar_slots_tenant_plan", "tenant_campaign_calendar_slots", ["tenant_id", "plan_version_id"])
    create_index_if_missing("ix_tenant_campaign_calendar_slots_plan_date", "tenant_campaign_calendar_slots", ["plan_version_id", "scheduled_date"])
    create_index_if_missing(
        "ix_tenant_campaign_calendar_slots_plan_platform_dt",
        "tenant_campaign_calendar_slots",
        ["plan_version_id", "platform", "scheduled_date", "scheduled_time"],
    )

    # ------------------------------------------------------- slot assignments
    if not table_exists("tenant_campaign_slot_assignments"):
        op.create_table(
            "tenant_campaign_slot_assignments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_version_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("slot_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_calendar_slots.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_variant_id", UUID(as_uuid=True), nullable=True),
            sa.Column("assignment_type", sa.String(40), nullable=False, server_default="content"),
            sa.Column("assigned_platform", sa.String(40), nullable=True),
            sa.Column("assigned_locale", sa.String(10), nullable=True),
            sa.Column("assignment_status", sa.String(40), nullable=False, server_default="assigned"),
            sa.Column("readiness_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("readiness_score", sa.Integer(), nullable=True),
            sa.Column("publishing_review_id", UUID(as_uuid=True), nullable=True),
            sa.Column("warnings", JSONB(), nullable=True),
            sa.Column("assigned_by", UUID(as_uuid=True), nullable=True),
            _ts("assigned_at", default=False, nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint("slot_id", name="uq_tenant_campaign_slot_assignments_slot"),
        )
    create_index_if_missing("ix_tenant_campaign_slot_assignments_tenant_id", "tenant_campaign_slot_assignments", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_slot_assignments_tenant_campaign", "tenant_campaign_slot_assignments", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_campaign_slot_assignments_tenant_content", "tenant_campaign_slot_assignments", ["tenant_id", "content_id"])

    # ---------------------------------------------------------------- reviews
    if not table_exists("tenant_campaign_reviews"):
        op.create_table(
            "tenant_campaign_reviews",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_version_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"), nullable=True),
            sa.Column("review_type", sa.String(20), nullable=False, server_default="plan"),
            sa.Column("coverage_score", sa.Integer(), nullable=True),
            sa.Column("readiness_score", sa.Integer(), nullable=True),
            sa.Column("total_slots", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("assigned_slots", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("blocked_slots", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unassigned_slots", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary", JSONB(), nullable=True),
            sa.Column("engine_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_campaign_reviews_tenant_id", "tenant_campaign_reviews", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_reviews_tenant_campaign", "tenant_campaign_reviews", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_campaign_reviews_plan_created", "tenant_campaign_reviews", ["plan_version_id", "created_at"])

    # ------------------------------------------------------------------- gaps
    if not table_exists("tenant_campaign_gaps"):
        op.create_table(
            "tenant_campaign_gaps",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_version_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_plan_versions.id", ondelete="CASCADE"), nullable=True),
            sa.Column("review_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_reviews.id", ondelete="CASCADE"), nullable=True),
            sa.Column("gap_type", sa.String(40), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("dimension", sa.String(40), nullable=True),
            sa.Column("dimension_value", sa.String(120), nullable=True),
            sa.Column("detail", JSONB(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_campaign_gaps_tenant_id", "tenant_campaign_gaps", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_gaps_tenant_campaign", "tenant_campaign_gaps", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_campaign_gaps_review", "tenant_campaign_gaps", ["review_id"])

    # ------------------------------------------------------- recommendations
    if not table_exists("tenant_campaign_recommendations"):
        op.create_table(
            "tenant_campaign_recommendations",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("plan_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("recommendation_key", sa.String(120), nullable=False),
            sa.Column("category", sa.String(40), nullable=False, server_default="campaign"),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("rule_id", sa.String(120), nullable=False),
            sa.Column("rule_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("action_url", sa.String(200), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint("tenant_id", "campaign_id", "recommendation_key", name="uq_tenant_campaign_recommendations_key"),
        )
    create_index_if_missing("ix_tenant_campaign_recommendations_tenant_id", "tenant_campaign_recommendations", ["tenant_id"])
    create_index_if_missing("ix_tenant_campaign_recommendations_tenant_campaign", "tenant_campaign_recommendations", ["tenant_id", "campaign_id"])


def downgrade() -> None:
    for idx, tbl in (
        ("ix_tenant_campaign_recommendations_tenant_campaign", "tenant_campaign_recommendations"),
        ("ix_tenant_campaign_recommendations_tenant_id", "tenant_campaign_recommendations"),
        ("ix_tenant_campaign_gaps_review", "tenant_campaign_gaps"),
        ("ix_tenant_campaign_gaps_tenant_campaign", "tenant_campaign_gaps"),
        ("ix_tenant_campaign_gaps_tenant_id", "tenant_campaign_gaps"),
        ("ix_tenant_campaign_reviews_plan_created", "tenant_campaign_reviews"),
        ("ix_tenant_campaign_reviews_tenant_campaign", "tenant_campaign_reviews"),
        ("ix_tenant_campaign_reviews_tenant_id", "tenant_campaign_reviews"),
        ("ix_tenant_campaign_slot_assignments_tenant_content", "tenant_campaign_slot_assignments"),
        ("ix_tenant_campaign_slot_assignments_tenant_campaign", "tenant_campaign_slot_assignments"),
        ("ix_tenant_campaign_slot_assignments_tenant_id", "tenant_campaign_slot_assignments"),
        ("ix_tenant_campaign_calendar_slots_plan_platform_dt", "tenant_campaign_calendar_slots"),
        ("ix_tenant_campaign_calendar_slots_plan_date", "tenant_campaign_calendar_slots"),
        ("ix_tenant_campaign_calendar_slots_tenant_plan", "tenant_campaign_calendar_slots"),
        ("ix_tenant_campaign_calendar_slots_tenant_id", "tenant_campaign_calendar_slots"),
        ("ix_tenant_campaign_plan_versions_tenant_status", "tenant_campaign_plan_versions"),
        ("ix_tenant_campaign_plan_versions_tenant_campaign", "tenant_campaign_plan_versions"),
        ("ix_tenant_campaign_plan_versions_tenant_id", "tenant_campaign_plan_versions"),
        ("ix_tenant_campaign_phases_tenant_campaign", "tenant_campaign_phases"),
        ("ix_tenant_campaign_phases_tenant_id", "tenant_campaign_phases"),
        ("ix_tenant_campaign_pillars_tenant_campaign", "tenant_campaign_pillars"),
        ("ix_tenant_campaign_pillars_tenant_id", "tenant_campaign_pillars"),
        ("ix_tenant_content_pillars_tenant_active", "tenant_content_pillars"),
        ("ix_tenant_content_pillars_tenant_id", "tenant_content_pillars"),
        ("ix_tenant_campaign_audiences_tenant_campaign", "tenant_campaign_audiences"),
        ("ix_tenant_campaign_audiences_tenant_id", "tenant_campaign_audiences"),
        ("ix_tenant_campaign_kpis_tenant_campaign", "tenant_campaign_kpis"),
        ("ix_tenant_campaign_kpis_tenant_id", "tenant_campaign_kpis"),
        ("ix_tenant_campaign_goals_tenant_campaign", "tenant_campaign_goals"),
        ("ix_tenant_campaign_goals_tenant_id", "tenant_campaign_goals"),
        ("ix_tenant_marketing_campaigns_tenant_created", "tenant_marketing_campaigns"),
        ("ix_tenant_marketing_campaigns_tenant_status", "tenant_marketing_campaigns"),
        ("ix_tenant_marketing_campaigns_tenant_id", "tenant_marketing_campaigns"),
    ):
        drop_index_if_exists(idx, tbl)

    for tbl in (
        "tenant_campaign_recommendations",
        "tenant_campaign_gaps",
        "tenant_campaign_reviews",
        "tenant_campaign_slot_assignments",
        "tenant_campaign_calendar_slots",
        "tenant_campaign_plan_versions",
        "tenant_campaign_phases",
        "tenant_campaign_pillars",
        "tenant_content_pillars",
        "tenant_campaign_audiences",
        "tenant_campaign_kpis",
        "tenant_campaign_goals",
        "tenant_marketing_campaigns",
    ):
        drop_table_if_exists(tbl)
