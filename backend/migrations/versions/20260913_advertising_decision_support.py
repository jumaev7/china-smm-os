"""Advertising Intelligence Phase 2 — Decision Support tables.

Creates immutable budget simulation runs, experiment planning/observation
artifacts, and advisory change plans. READ-ONLY toward providers: no table
here stores executable provider payloads, credentials, or mutation commands.

down_revision = "20260912_advertising_intelligence"
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

revision = "20260913_advertising_decision_support"
down_revision = "20260912_advertising_intelligence"
branch_labels = None
depends_on = None


def _ts(name: str, *, default: bool = True, nullable: bool = False) -> sa.Column:
    kwargs = {"nullable": nullable}
    if default:
        kwargs["server_default"] = sa.text("now()")
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    if not table_exists("tenants") or not table_exists("tenant_ad_campaigns"):
        return

    # ------------------------------------------------------ budget simulations
    if not table_exists("tenant_ad_budget_simulations"):
        op.create_table(
            "tenant_ad_budget_simulations",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("total_budget_minor", sa.Integer(), nullable=False),
            sa.Column("measurement_window_key", sa.String(40), nullable=False, server_default="lifetime"),
            sa.Column("window_start", sa.Date(), nullable=True),
            sa.Column("window_end", sa.Date(), nullable=True),
            sa.Column("engine_version", sa.String(40), nullable=False),
            sa.Column("input_fingerprint", sa.String(128), nullable=False),
            sa.Column("assumptions_json", JSONB(), nullable=True),
            sa.Column("summary_json", JSONB(), nullable=True),
            sa.Column("warnings_json", JSONB(), nullable=True),
            sa.Column(
                "disclaimer",
                sa.Text(),
                nullable=False,
                server_default=(
                    "Simulation does not predict future advertising performance "
                    "and does not modify provider budgets."
                ),
            ),
            sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing(
        "ix_tenant_ad_budget_simulations_tenant_created",
        "tenant_ad_budget_simulations",
        ["tenant_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_ad_budget_simulations_tenant_currency",
        "tenant_ad_budget_simulations",
        ["tenant_id", "currency"],
    )
    create_index_if_missing(
        "ix_tenant_ad_budget_simulations_tenant_id",
        "tenant_ad_budget_simulations",
        ["tenant_id"],
    )

    if not table_exists("tenant_ad_budget_simulation_items"):
        op.create_table(
            "tenant_ad_budget_simulation_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "simulation_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ad_budget_simulations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "campaign_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("campaign_name", sa.String(500), nullable=True),
            sa.Column("observed_spend_minor", sa.Integer(), nullable=True),
            sa.Column("observed_share", sa.Numeric(12, 8), nullable=True),
            sa.Column("allocation_pct", sa.Numeric(12, 8), nullable=False),
            sa.Column("simulated_budget_minor", sa.Integer(), nullable=False),
            sa.Column("simulated_share", sa.Numeric(12, 8), nullable=False),
            sa.Column("historical_reference_metrics", JSONB(), nullable=True),
            sa.Column("freshness_status", sa.String(40), nullable=True),
            sa.Column("warnings_json", JSONB(), nullable=True),
            _ts("created_at"),
            sa.UniqueConstraint(
                "simulation_id", "campaign_id",
                name="uq_tenant_ad_budget_simulation_items_campaign",
            ),
        )
    create_index_if_missing(
        "ix_tenant_ad_budget_simulation_items_sim",
        "tenant_ad_budget_simulation_items",
        ["tenant_id", "simulation_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_budget_simulation_items_campaign",
        "tenant_ad_budget_simulation_items",
        ["tenant_id", "campaign_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_budget_simulation_items_tenant_id",
        "tenant_ad_budget_simulation_items",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_budget_simulation_items_simulation_id",
        "tenant_ad_budget_simulation_items",
        ["simulation_id"],
    )

    # ------------------------------------------------------ experiments
    if not table_exists("tenant_ad_experiments"):
        op.create_table(
            "tenant_ad_experiments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("experiment_type", sa.String(80), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("hypothesis", sa.Text(), nullable=False),
            sa.Column("primary_metric_key", sa.String(80), nullable=False),
            sa.Column("secondary_metric_keys", JSONB(), nullable=True),
            sa.Column("observation_start", sa.Date(), nullable=True),
            sa.Column("observation_end", sa.Date(), nullable=True),
            sa.Column("minimum_observations", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("minimum_spend_minor", sa.Integer(), nullable=True),
            sa.Column("minimum_conversions", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("attribution_method", sa.String(80), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("result_status", sa.String(40), nullable=True),
            sa.Column("engine_version", sa.String(40), nullable=False),
            sa.Column("metadata_json", JSONB(), nullable=True),
            sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.Column("observation_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        )
    create_index_if_missing(
        "ix_tenant_ad_experiments_tenant_status",
        "tenant_ad_experiments",
        ["tenant_id", "status"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiments_tenant_created",
        "tenant_ad_experiments",
        ["tenant_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiments_tenant_type",
        "tenant_ad_experiments",
        ["tenant_id", "experiment_type"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiments_tenant_id",
        "tenant_ad_experiments",
        ["tenant_id"],
    )

    if not table_exists("tenant_ad_experiment_variants"):
        op.create_table(
            "tenant_ad_experiment_variants",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "experiment_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ad_experiments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("variant_key", sa.String(40), nullable=False),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            sa.UniqueConstraint(
                "experiment_id", "variant_key",
                name="uq_tenant_ad_experiment_variants_key",
            ),
        )
    create_index_if_missing(
        "ix_tenant_ad_experiment_variants_exp",
        "tenant_ad_experiment_variants",
        ["tenant_id", "experiment_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_variants_tenant_id",
        "tenant_ad_experiment_variants",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_variants_experiment_id",
        "tenant_ad_experiment_variants",
        ["experiment_id"],
    )

    if not table_exists("tenant_ad_experiment_measurements"):
        op.create_table(
            "tenant_ad_experiment_measurements",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "experiment_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ad_experiments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "variant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ad_experiment_variants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("metrics_json", JSONB(), nullable=True),
            sa.Column("spend_minor", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("impressions", sa.Numeric(24, 6), nullable=True),
            sa.Column("clicks", sa.Numeric(24, 6), nullable=True),
            sa.Column("conversions", sa.Numeric(24, 6), nullable=True),
            sa.Column("freshness_status", sa.String(40), nullable=True),
            sa.Column("attribution_method", sa.String(80), nullable=True),
            sa.Column("warnings_json", JSONB(), nullable=True),
            sa.Column("engine_version", sa.String(40), nullable=False),
            _ts("created_at"),
        )
    create_index_if_missing(
        "ix_tenant_ad_experiment_measurements_exp",
        "tenant_ad_experiment_measurements",
        ["tenant_id", "experiment_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_measurements_variant",
        "tenant_ad_experiment_measurements",
        ["tenant_id", "variant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_measurements_tenant_id",
        "tenant_ad_experiment_measurements",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_measurements_experiment_id",
        "tenant_ad_experiment_measurements",
        ["experiment_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_measurements_variant_id",
        "tenant_ad_experiment_measurements",
        ["variant_id"],
    )

    if not table_exists("tenant_ad_experiment_reviews"):
        op.create_table(
            "tenant_ad_experiment_reviews",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "experiment_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ad_experiments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("result_status", sa.String(40), nullable=False),
            sa.Column("conclusion", sa.Text(), nullable=False),
            sa.Column("evidence_json", JSONB(), nullable=True),
            sa.Column("limitations_json", JSONB(), nullable=True),
            sa.Column("reviewed_by_user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("engine_version", sa.String(40), nullable=False),
            _ts("created_at"),
        )
    create_index_if_missing(
        "ix_tenant_ad_experiment_reviews_exp",
        "tenant_ad_experiment_reviews",
        ["tenant_id", "experiment_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_reviews_tenant_id",
        "tenant_ad_experiment_reviews",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_experiment_reviews_experiment_id",
        "tenant_ad_experiment_reviews",
        ["experiment_id"],
    )

    # ------------------------------------------------------ change plans
    if not table_exists("tenant_ad_change_plans"):
        op.create_table(
            "tenant_ad_change_plans",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("source", sa.String(80), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("engine_version", sa.String(40), nullable=False),
            sa.Column("evidence_json", JSONB(), nullable=True),
            sa.Column("metadata_json", JSONB(), nullable=True),
            sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        )
    create_index_if_missing(
        "ix_tenant_ad_change_plans_tenant_status",
        "tenant_ad_change_plans",
        ["tenant_id", "status"],
    )
    create_index_if_missing(
        "ix_tenant_ad_change_plans_tenant_created",
        "tenant_ad_change_plans",
        ["tenant_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_ad_change_plans_tenant_id",
        "tenant_ad_change_plans",
        ["tenant_id"],
    )

    if not table_exists("tenant_ad_change_plan_items"):
        op.create_table(
            "tenant_ad_change_plan_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "change_plan_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ad_change_plans.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("item_type", sa.String(80), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=True),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
            sa.Column("observation", sa.Text(), nullable=False),
            sa.Column("evidence_json", JSONB(), nullable=True),
            sa.Column("reasoning", sa.Text(), nullable=False),
            sa.Column("suggested_human_action", sa.Text(), nullable=False),
            sa.Column("risk", sa.String(40), nullable=True),
            sa.Column("confidence", sa.Numeric(5, 3), nullable=True),
            sa.Column("supporting_metrics", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing(
        "ix_tenant_ad_change_plan_items_plan",
        "tenant_ad_change_plan_items",
        ["tenant_id", "change_plan_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_change_plan_items_entity",
        "tenant_ad_change_plan_items",
        ["tenant_id", "entity_type", "entity_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_change_plan_items_tenant_id",
        "tenant_ad_change_plan_items",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ad_change_plan_items_change_plan_id",
        "tenant_ad_change_plan_items",
        ["change_plan_id"],
    )


def downgrade() -> None:
    for idx, tbl in (
        ("ix_tenant_ad_change_plan_items_change_plan_id", "tenant_ad_change_plan_items"),
        ("ix_tenant_ad_change_plan_items_tenant_id", "tenant_ad_change_plan_items"),
        ("ix_tenant_ad_change_plan_items_entity", "tenant_ad_change_plan_items"),
        ("ix_tenant_ad_change_plan_items_plan", "tenant_ad_change_plan_items"),
        ("ix_tenant_ad_change_plans_tenant_id", "tenant_ad_change_plans"),
        ("ix_tenant_ad_change_plans_tenant_created", "tenant_ad_change_plans"),
        ("ix_tenant_ad_change_plans_tenant_status", "tenant_ad_change_plans"),
        ("ix_tenant_ad_experiment_reviews_experiment_id", "tenant_ad_experiment_reviews"),
        ("ix_tenant_ad_experiment_reviews_tenant_id", "tenant_ad_experiment_reviews"),
        ("ix_tenant_ad_experiment_reviews_exp", "tenant_ad_experiment_reviews"),
        ("ix_tenant_ad_experiment_measurements_variant_id", "tenant_ad_experiment_measurements"),
        ("ix_tenant_ad_experiment_measurements_experiment_id", "tenant_ad_experiment_measurements"),
        ("ix_tenant_ad_experiment_measurements_tenant_id", "tenant_ad_experiment_measurements"),
        ("ix_tenant_ad_experiment_measurements_variant", "tenant_ad_experiment_measurements"),
        ("ix_tenant_ad_experiment_measurements_exp", "tenant_ad_experiment_measurements"),
        ("ix_tenant_ad_experiment_variants_experiment_id", "tenant_ad_experiment_variants"),
        ("ix_tenant_ad_experiment_variants_tenant_id", "tenant_ad_experiment_variants"),
        ("ix_tenant_ad_experiment_variants_exp", "tenant_ad_experiment_variants"),
        ("ix_tenant_ad_experiments_tenant_id", "tenant_ad_experiments"),
        ("ix_tenant_ad_experiments_tenant_type", "tenant_ad_experiments"),
        ("ix_tenant_ad_experiments_tenant_created", "tenant_ad_experiments"),
        ("ix_tenant_ad_experiments_tenant_status", "tenant_ad_experiments"),
        ("ix_tenant_ad_budget_simulation_items_simulation_id", "tenant_ad_budget_simulation_items"),
        ("ix_tenant_ad_budget_simulation_items_tenant_id", "tenant_ad_budget_simulation_items"),
        ("ix_tenant_ad_budget_simulation_items_campaign", "tenant_ad_budget_simulation_items"),
        ("ix_tenant_ad_budget_simulation_items_sim", "tenant_ad_budget_simulation_items"),
        ("ix_tenant_ad_budget_simulations_tenant_id", "tenant_ad_budget_simulations"),
        ("ix_tenant_ad_budget_simulations_tenant_currency", "tenant_ad_budget_simulations"),
        ("ix_tenant_ad_budget_simulations_tenant_created", "tenant_ad_budget_simulations"),
    ):
        drop_index_if_exists(idx, tbl)

    for tbl in (
        "tenant_ad_change_plan_items",
        "tenant_ad_change_plans",
        "tenant_ad_experiment_reviews",
        "tenant_ad_experiment_measurements",
        "tenant_ad_experiment_variants",
        "tenant_ad_experiments",
        "tenant_ad_budget_simulation_items",
        "tenant_ad_budget_simulations",
    ):
        drop_table_if_exists(tbl)
