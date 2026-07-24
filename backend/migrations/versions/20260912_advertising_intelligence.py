"""Advertising Intelligence Phase 1 — read-only advertising foundation.

Creates the tenant-scoped advertising mirror (accounts, campaigns, ad groups,
ads, creatives), immutable entity-history + metric-snapshot tables, derived
aggregates, conversion/budget observations, delivery anomalies, and the
creative/campaign linking tables. Also extends ``tenant_measurement_jobs`` with
a ``job_domain`` discriminator and an optional advertising-account pointer so a
single durable job runner can serve both measurement and advertising domains.

READ-ONLY: this migration establishes only read/observation storage. No table
here stores provider tokens or credentials — those live exclusively on
``publishing_accounts`` (referenced optionally via ``integration_id``). Money is
stored as integer minor units plus an explicit currency string.

down_revision = "20260911_measurement_foundation"
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    add_column_if_missing,
    create_foreign_key_if_missing,
    create_index_if_missing,
    drop_column_if_exists,
    drop_index_if_exists,
    drop_table_if_exists,
    foreign_key_exists,
    table_exists,
)

revision = "20260912_advertising_intelligence"
down_revision = "20260911_measurement_foundation"
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

    # ------------------------------------------------------ advertising accounts
    if not table_exists("tenant_advertising_accounts"):
        op.create_table(
            "tenant_advertising_accounts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("integration_id", UUID(as_uuid=True), sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("platform", sa.String(40), nullable=True),
            sa.Column("provider_account_id", sa.String(255), nullable=False),
            sa.Column("provider_business_id", sa.String(255), nullable=True),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("timezone", sa.String(64), nullable=True),
            sa.Column("account_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("connection_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("capabilities", JSONB(), nullable=True),
            sa.Column("permission_summary", JSONB(), nullable=True),
            sa.Column("last_import_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_metrics_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_mock", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "tenant_id", "provider", "provider_account_id",
                name="uq_tenant_advertising_accounts_provider_identity",
            ),
        )
    create_index_if_missing("ix_tenant_advertising_accounts_tenant_id", "tenant_advertising_accounts", ["tenant_id"])
    create_index_if_missing("ix_tenant_advertising_accounts_tenant_provider", "tenant_advertising_accounts", ["tenant_id", "provider"])
    create_index_if_missing("ix_tenant_advertising_accounts_tenant_conn", "tenant_advertising_accounts", ["tenant_id", "connection_status"])
    create_index_if_missing("ix_tenant_advertising_accounts_integration", "tenant_advertising_accounts", ["integration_id"])

    # --------------------------------------------------------------- ad creatives
    if not table_exists("tenant_ad_creatives"):
        op.create_table(
            "tenant_ad_creatives",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("provider_creative_id", sa.String(255), nullable=False),
            sa.Column("name", sa.String(500), nullable=True),
            sa.Column("title", sa.String(500), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("call_to_action_type", sa.String(80), nullable=True),
            sa.Column("object_type", sa.String(80), nullable=True),
            sa.Column("thumbnail_url", sa.String(2000), nullable=True),
            sa.Column("permalink_url", sa.String(2000), nullable=True),
            sa.Column("object_story_id", sa.String(255), nullable=True),
            sa.Column("asset_summary", JSONB(), nullable=True),
            sa.Column("source_fingerprint", sa.String(128), nullable=True),
            sa.Column("is_mock", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "tenant_id", "advertising_account_id", "provider_creative_id",
                name="uq_tenant_ad_creatives_provider_identity",
            ),
        )
    create_index_if_missing("ix_tenant_ad_creatives_tenant_id", "tenant_ad_creatives", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_creatives_account", "tenant_ad_creatives", ["tenant_id", "advertising_account_id"])

    # --------------------------------------------------------------- ad campaigns
    if not table_exists("tenant_ad_campaigns"):
        op.create_table(
            "tenant_ad_campaigns",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("provider_campaign_id", sa.String(255), nullable=False),
            sa.Column("name", sa.String(500), nullable=True),
            sa.Column("objective", sa.String(80), nullable=True),
            sa.Column("buying_type", sa.String(40), nullable=True),
            sa.Column("config_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("effective_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("bid_strategy", sa.String(80), nullable=True),
            sa.Column("daily_budget_minor", sa.Integer(), nullable=True),
            sa.Column("lifetime_budget_minor", sa.Integer(), nullable=True),
            sa.Column("budget_currency", sa.String(3), nullable=True),
            sa.Column("spend_cap_minor", sa.Integer(), nullable=True),
            sa.Column("special_ad_categories", JSONB(), nullable=True),
            sa.Column("attribution_spec", JSONB(), nullable=True),
            sa.Column("provider_start_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_stop_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_created_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_updated_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_fingerprint", sa.String(128), nullable=True),
            sa.Column("is_mock", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "tenant_id", "advertising_account_id", "provider_campaign_id",
                name="uq_tenant_ad_campaigns_provider_identity",
            ),
        )
    create_index_if_missing("ix_tenant_ad_campaigns_tenant_id", "tenant_ad_campaigns", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_campaigns_account", "tenant_ad_campaigns", ["tenant_id", "advertising_account_id"])
    create_index_if_missing("ix_tenant_ad_campaigns_tenant_status", "tenant_ad_campaigns", ["tenant_id", "effective_status"])

    # ----------------------------------------------------------------- ad groups
    if not table_exists("tenant_ad_groups"):
        op.create_table(
            "tenant_ad_groups",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"), nullable=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("provider_ad_group_id", sa.String(255), nullable=False),
            sa.Column("provider_campaign_id", sa.String(255), nullable=True),
            sa.Column("name", sa.String(500), nullable=True),
            sa.Column("config_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("effective_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("optimization_goal", sa.String(80), nullable=True),
            sa.Column("billing_event", sa.String(80), nullable=True),
            sa.Column("bid_amount_minor", sa.Integer(), nullable=True),
            sa.Column("bid_currency", sa.String(3), nullable=True),
            sa.Column("daily_budget_minor", sa.Integer(), nullable=True),
            sa.Column("lifetime_budget_minor", sa.Integer(), nullable=True),
            sa.Column("budget_currency", sa.String(3), nullable=True),
            sa.Column("targeting_summary", JSONB(), nullable=True),
            sa.Column("provider_start_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_stop_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_created_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_updated_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_fingerprint", sa.String(128), nullable=True),
            sa.Column("is_mock", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "tenant_id", "advertising_account_id", "provider_ad_group_id",
                name="uq_tenant_ad_groups_provider_identity",
            ),
        )
    create_index_if_missing("ix_tenant_ad_groups_tenant_id", "tenant_ad_groups", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_groups_account", "tenant_ad_groups", ["tenant_id", "advertising_account_id"])
    create_index_if_missing("ix_tenant_ad_groups_campaign", "tenant_ad_groups", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_ad_groups_tenant_status", "tenant_ad_groups", ["tenant_id", "effective_status"])

    # ----------------------------------------------------------------------- ads
    if not table_exists("tenant_ads"):
        op.create_table(
            "tenant_ads",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"), nullable=True),
            sa.Column("ad_group_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_groups.id", ondelete="CASCADE"), nullable=True),
            sa.Column("creative_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_creatives.id", ondelete="SET NULL"), nullable=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("provider_ad_id", sa.String(255), nullable=False),
            sa.Column("provider_ad_group_id", sa.String(255), nullable=True),
            sa.Column("provider_creative_id", sa.String(255), nullable=True),
            sa.Column("name", sa.String(500), nullable=True),
            sa.Column("config_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("effective_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("tracking_specs", JSONB(), nullable=True),
            sa.Column("provider_created_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_updated_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_fingerprint", sa.String(128), nullable=True),
            sa.Column("is_mock", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "tenant_id", "advertising_account_id", "provider_ad_id",
                name="uq_tenant_ads_provider_identity",
            ),
        )
    create_index_if_missing("ix_tenant_ads_tenant_id", "tenant_ads", ["tenant_id"])
    create_index_if_missing("ix_tenant_ads_account", "tenant_ads", ["tenant_id", "advertising_account_id"])
    create_index_if_missing("ix_tenant_ads_ad_group", "tenant_ads", ["tenant_id", "ad_group_id"])
    create_index_if_missing("ix_tenant_ads_campaign", "tenant_ads", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_ads_tenant_status", "tenant_ads", ["tenant_id", "effective_status"])

    # ---------------------------------------------------------------- import runs
    if not table_exists("tenant_ad_import_runs"):
        op.create_table(
            "tenant_ad_import_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("scope", sa.String(40), nullable=False, server_default="full"),
            sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
            _ts("requested_at"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cursor_before", sa.String(255), nullable=True),
            sa.Column("cursor_after", sa.String(255), nullable=True),
            sa.Column("entities_requested", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entities_created", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entities_updated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entities_unchanged", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entities_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("provider_request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_code", sa.String(80), nullable=True),
            sa.Column("failure_metadata", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_ad_import_runs_tenant_id", "tenant_ad_import_runs", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_import_runs_tenant_created", "tenant_ad_import_runs", ["tenant_id", "created_at"])
    create_index_if_missing("ix_tenant_ad_import_runs_tenant_status", "tenant_ad_import_runs", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_ad_import_runs_account", "tenant_ad_import_runs", ["advertising_account_id"])

    # -------------------------------------------------------------- entity history
    if not table_exists("tenant_ad_entity_history"):
        op.create_table(
            "tenant_ad_entity_history",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
            sa.Column("provider_entity_id", sa.String(255), nullable=False),
            sa.Column("change_type", sa.String(40), nullable=False, server_default="observed"),
            sa.Column("field_changes", JSONB(), nullable=True),
            sa.Column("previous_fingerprint", sa.String(128), nullable=True),
            sa.Column("fingerprint", sa.String(128), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("import_run_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_import_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String(40), nullable=False, server_default="provider"),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_ad_entity_history_tenant_id", "tenant_ad_entity_history", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_entity_history_entity", "tenant_ad_entity_history", ["tenant_id", "entity_type", "entity_id"])
    create_index_if_missing("ix_tenant_ad_entity_history_account", "tenant_ad_entity_history", ["tenant_id", "advertising_account_id"])
    create_index_if_missing("ix_tenant_ad_entity_history_observed", "tenant_ad_entity_history", ["tenant_id", "observed_at"])

    # ------------------------------------------------------- metric ingestion runs
    if not table_exists("tenant_ad_metric_ingestion_runs"):
        op.create_table(
            "tenant_ad_metric_ingestion_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("level", sa.String(40), nullable=False, server_default="account"),
            sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
            sa.Column("date_start", sa.String(10), nullable=True),
            sa.Column("date_stop", sa.String(10), nullable=True),
            _ts("requested_at"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cursor_before", sa.String(255), nullable=True),
            sa.Column("cursor_after", sa.String(255), nullable=True),
            sa.Column("entities_requested", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entities_succeeded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entities_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("snapshots_created", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("provider_request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_code", sa.String(80), nullable=True),
            sa.Column("failure_metadata", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_ad_metric_ingestion_runs_tenant_id", "tenant_ad_metric_ingestion_runs", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_metric_ingestion_runs_tenant_created", "tenant_ad_metric_ingestion_runs", ["tenant_id", "created_at"])
    create_index_if_missing("ix_tenant_ad_metric_ingestion_runs_tenant_status", "tenant_ad_metric_ingestion_runs", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_ad_metric_ingestion_runs_account", "tenant_ad_metric_ingestion_runs", ["advertising_account_id"])

    # ------------------------------------------------------------ metric snapshots
    if not table_exists("tenant_ad_metric_snapshots"):
        op.create_table(
            "tenant_ad_metric_snapshots",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column("provider_entity_id", sa.String(255), nullable=False),
            sa.Column("level", sa.String(40), nullable=False, server_default="account"),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("provider_data_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("date_start", sa.String(10), nullable=True),
            sa.Column("date_stop", sa.String(10), nullable=True),
            sa.Column("snapshot_fingerprint", sa.String(128), nullable=False),
            sa.Column("ingestion_run_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_metric_ingestion_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="complete"),
            sa.Column("source", sa.String(40), nullable=False, server_default="provider"),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("raw_metric_summary", JSONB(), nullable=True),
            _ts("created_at"),
            sa.UniqueConstraint(
                "tenant_id", "entity_type", "entity_id", "snapshot_fingerprint",
                name="uq_tenant_ad_metric_snapshots_fingerprint",
            ),
        )
    create_index_if_missing("ix_tenant_ad_metric_snapshots_tenant_id", "tenant_ad_metric_snapshots", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_metric_snapshots_entity_observed", "tenant_ad_metric_snapshots", ["entity_type", "entity_id", "observed_at"])
    create_index_if_missing("ix_tenant_ad_metric_snapshots_tenant_observed", "tenant_ad_metric_snapshots", ["tenant_id", "observed_at"])
    create_index_if_missing("ix_tenant_ad_metric_snapshots_account", "tenant_ad_metric_snapshots", ["tenant_id", "advertising_account_id"])

    # -------------------------------------------------------------- metric values
    if not table_exists("tenant_ad_metric_values"):
        op.create_table(
            "tenant_ad_metric_values",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("metric_snapshot_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_metric_snapshots.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column("metric_key", sa.String(120), nullable=False),
            sa.Column("provider_metric_key", sa.String(120), nullable=True),
            sa.Column("metric_value", sa.Numeric(24, 6), nullable=False),
            sa.Column("value_type", sa.String(40), nullable=False, server_default="count"),
            sa.Column("aggregation_type", sa.String(40), nullable=False, server_default="interval"),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("metric_semantics_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("normalization_status", sa.String(40), nullable=False, server_default="normalized"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_ad_metric_values_tenant_id", "tenant_ad_metric_values", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_metric_values_snapshot", "tenant_ad_metric_values", ["metric_snapshot_id"])
    create_index_if_missing("ix_tenant_ad_metric_values_entity_key", "tenant_ad_metric_values", ["entity_type", "entity_id", "metric_key"])
    create_index_if_missing("ix_tenant_ad_metric_values_tenant_key", "tenant_ad_metric_values", ["tenant_id", "metric_key"])

    # ---------------------------------------------------------- metric aggregates
    if not table_exists("tenant_ad_metric_aggregates"):
        op.create_table(
            "tenant_ad_metric_aggregates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column("window_key", sa.String(20), nullable=False),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metric_key", sa.String(120), nullable=False),
            sa.Column("metric_value", sa.Numeric(24, 6), nullable=False),
            sa.Column("value_type", sa.String(40), nullable=False, server_default="count"),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("calculation_method", sa.String(80), nullable=False, server_default="sum_interval"),
            sa.Column("calculation_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("freshness_status", sa.String(40), nullable=False, server_default="unavailable"),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
            sa.Column("source_snapshot_ids", JSONB(), nullable=True),
            _ts("calculated_at"),
            sa.UniqueConstraint(
                "tenant_id", "entity_type", "entity_id", "window_key", "metric_key", "calculation_version",
                name="uq_tenant_ad_metric_aggregates_window",
            ),
        )
    create_index_if_missing("ix_tenant_ad_metric_aggregates_tenant_id", "tenant_ad_metric_aggregates", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_metric_aggregates_entity", "tenant_ad_metric_aggregates", ["entity_type", "entity_id", "window_key"])
    create_index_if_missing("ix_tenant_ad_metric_aggregates_account", "tenant_ad_metric_aggregates", ["tenant_id", "advertising_account_id"])

    # ------------------------------------------------------- conversion breakdowns
    if not table_exists("tenant_ad_conversion_breakdowns"):
        op.create_table(
            "tenant_ad_conversion_breakdowns",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("metric_snapshot_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_metric_snapshots.id", ondelete="CASCADE"), nullable=True),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column("action_type", sa.String(120), nullable=False),
            sa.Column("action_destination", sa.String(120), nullable=True),
            sa.Column("attribution_setting", sa.String(80), nullable=True),
            sa.Column("conversion_window", sa.String(40), nullable=True),
            sa.Column("value", sa.Numeric(24, 6), nullable=False),
            sa.Column("value_type", sa.String(40), nullable=False, server_default="count"),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("date_start", sa.String(10), nullable=True),
            sa.Column("date_stop", sa.String(10), nullable=True),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_ad_conversion_breakdowns_tenant_id", "tenant_ad_conversion_breakdowns", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_conversion_breakdowns_entity", "tenant_ad_conversion_breakdowns", ["tenant_id", "entity_type", "entity_id"])
    create_index_if_missing("ix_tenant_ad_conversion_breakdowns_snapshot", "tenant_ad_conversion_breakdowns", ["metric_snapshot_id"])
    create_index_if_missing("ix_tenant_ad_conversion_breakdowns_action", "tenant_ad_conversion_breakdowns", ["tenant_id", "action_type"])

    # ------------------------------------------------------------ budget snapshots
    if not table_exists("tenant_ad_budget_snapshots"):
        op.create_table(
            "tenant_ad_budget_snapshots",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_type", sa.String(40), nullable=False),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column("budget_type", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("budget_minor", sa.Integer(), nullable=True),
            sa.Column("spend_minor", sa.Integer(), nullable=True),
            sa.Column("remaining_minor", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("utilization_ratio", sa.Numeric(9, 6), nullable=True),
            sa.Column("pacing_status", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(40), nullable=False, server_default="provider"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_ad_budget_snapshots_tenant_id", "tenant_ad_budget_snapshots", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_budget_snapshots_entity", "tenant_ad_budget_snapshots", ["tenant_id", "entity_type", "entity_id"])
    create_index_if_missing("ix_tenant_ad_budget_snapshots_observed", "tenant_ad_budget_snapshots", ["tenant_id", "observed_at"])
    create_index_if_missing("ix_tenant_ad_budget_snapshots_account", "tenant_ad_budget_snapshots", ["tenant_id", "advertising_account_id"])

    # ----------------------------------------------------------- delivery anomalies
    if not table_exists("tenant_ad_delivery_anomalies"):
        op.create_table(
            "tenant_ad_delivery_anomalies",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=True),
            sa.Column("metric_snapshot_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_metric_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("entity_type", sa.String(40), nullable=True),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
            sa.Column("anomaly_key", sa.String(80), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
            sa.Column("metric_key", sa.String(120), nullable=True),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="open"),
            _ts("created_at"),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
    create_index_if_missing("ix_tenant_ad_delivery_anomalies_tenant_id", "tenant_ad_delivery_anomalies", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_delivery_anomalies_tenant_status", "tenant_ad_delivery_anomalies", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_ad_delivery_anomalies_entity", "tenant_ad_delivery_anomalies", ["tenant_id", "entity_type", "entity_id"])
    create_index_if_missing("ix_tenant_ad_delivery_anomalies_account", "tenant_ad_delivery_anomalies", ["advertising_account_id"])

    # ------------------------------------------------------------- creative links
    if not table_exists("tenant_ad_creative_links"):
        op.create_table(
            "tenant_ad_creative_links",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=True),
            sa.Column("creative_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_creatives.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_type", sa.String(40), nullable=False, server_default="content_item"),
            sa.Column("target_id", sa.String(80), nullable=False),
            sa.Column("content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_variant_id", UUID(as_uuid=True), nullable=True),
            sa.Column("external_publication_id", UUID(as_uuid=True), sa.ForeignKey("tenant_external_publications.id", ondelete="SET NULL"), nullable=True),
            sa.Column("link_method", sa.String(40), nullable=False, server_default="manual_link"),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            sa.UniqueConstraint(
                "tenant_id", "creative_id", "target_type", "target_id",
                name="uq_tenant_ad_creative_links_target",
            ),
        )
    create_index_if_missing("ix_tenant_ad_creative_links_tenant_id", "tenant_ad_creative_links", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_creative_links_creative", "tenant_ad_creative_links", ["tenant_id", "creative_id"])
    create_index_if_missing("ix_tenant_ad_creative_links_target", "tenant_ad_creative_links", ["tenant_id", "target_type", "target_id"])

    # ------------------------------------------------------------- campaign links
    if not table_exists("tenant_ad_campaign_links"):
        op.create_table(
            "tenant_ad_campaign_links",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("advertising_account_id", UUID(as_uuid=True), sa.ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"), nullable=True),
            sa.Column("ad_campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("marketing_campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_plan_version_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_plan_versions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("link_method", sa.String(40), nullable=False, server_default="manual_link"),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            sa.UniqueConstraint(
                "tenant_id", "ad_campaign_id", "marketing_campaign_id",
                name="uq_tenant_ad_campaign_links_pair",
            ),
        )
    create_index_if_missing("ix_tenant_ad_campaign_links_tenant_id", "tenant_ad_campaign_links", ["tenant_id"])
    create_index_if_missing("ix_tenant_ad_campaign_links_ad_campaign", "tenant_ad_campaign_links", ["tenant_id", "ad_campaign_id"])
    create_index_if_missing("ix_tenant_ad_campaign_links_marketing", "tenant_ad_campaign_links", ["tenant_id", "marketing_campaign_id"])

    # ---------------------------------- extend tenant_measurement_jobs (shared runner)
    if table_exists("tenant_measurement_jobs"):
        add_column_if_missing(
            "tenant_measurement_jobs",
            sa.Column("job_domain", sa.String(40), nullable=False, server_default="measurement"),
        )
        add_column_if_missing(
            "tenant_measurement_jobs",
            sa.Column("advertising_account_id", UUID(as_uuid=True), nullable=True),
        )
        create_foreign_key_if_missing(
            "fk_tenant_measurement_jobs_advertising_account",
            "tenant_measurement_jobs",
            "tenant_advertising_accounts",
            ["advertising_account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        create_index_if_missing(
            "ix_tenant_measurement_jobs_domain",
            "tenant_measurement_jobs",
            ["tenant_id", "job_domain", "status"],
        )
        create_index_if_missing(
            "ix_tenant_measurement_jobs_advertising_account",
            "tenant_measurement_jobs",
            ["advertising_account_id"],
        )


def downgrade() -> None:
    # Roll back the shared-runner extension first (drop FK/indexes/columns).
    # Always attempt FK drop — ensure_advertising_schema may have created it
    # under the same name even when Alembic did not track the ALTER.
    if table_exists("tenant_measurement_jobs"):
        drop_index_if_exists("ix_tenant_measurement_jobs_advertising_account", "tenant_measurement_jobs")
        drop_index_if_exists("ix_tenant_measurement_jobs_domain", "tenant_measurement_jobs")
        op.execute(
            sa.text(
                "ALTER TABLE tenant_measurement_jobs "
                "DROP CONSTRAINT IF EXISTS fk_tenant_measurement_jobs_advertising_account"
            )
        )
        drop_column_if_exists("tenant_measurement_jobs", "advertising_account_id")
        drop_column_if_exists("tenant_measurement_jobs", "job_domain")

    for idx, tbl in (
        ("ix_tenant_ad_campaign_links_marketing", "tenant_ad_campaign_links"),
        ("ix_tenant_ad_campaign_links_ad_campaign", "tenant_ad_campaign_links"),
        ("ix_tenant_ad_campaign_links_tenant_id", "tenant_ad_campaign_links"),
        ("ix_tenant_ad_creative_links_target", "tenant_ad_creative_links"),
        ("ix_tenant_ad_creative_links_creative", "tenant_ad_creative_links"),
        ("ix_tenant_ad_creative_links_tenant_id", "tenant_ad_creative_links"),
        ("ix_tenant_ad_delivery_anomalies_account", "tenant_ad_delivery_anomalies"),
        ("ix_tenant_ad_delivery_anomalies_entity", "tenant_ad_delivery_anomalies"),
        ("ix_tenant_ad_delivery_anomalies_tenant_status", "tenant_ad_delivery_anomalies"),
        ("ix_tenant_ad_delivery_anomalies_tenant_id", "tenant_ad_delivery_anomalies"),
        ("ix_tenant_ad_budget_snapshots_account", "tenant_ad_budget_snapshots"),
        ("ix_tenant_ad_budget_snapshots_observed", "tenant_ad_budget_snapshots"),
        ("ix_tenant_ad_budget_snapshots_entity", "tenant_ad_budget_snapshots"),
        ("ix_tenant_ad_budget_snapshots_tenant_id", "tenant_ad_budget_snapshots"),
        ("ix_tenant_ad_conversion_breakdowns_action", "tenant_ad_conversion_breakdowns"),
        ("ix_tenant_ad_conversion_breakdowns_snapshot", "tenant_ad_conversion_breakdowns"),
        ("ix_tenant_ad_conversion_breakdowns_entity", "tenant_ad_conversion_breakdowns"),
        ("ix_tenant_ad_conversion_breakdowns_tenant_id", "tenant_ad_conversion_breakdowns"),
        ("ix_tenant_ad_metric_aggregates_account", "tenant_ad_metric_aggregates"),
        ("ix_tenant_ad_metric_aggregates_entity", "tenant_ad_metric_aggregates"),
        ("ix_tenant_ad_metric_aggregates_tenant_id", "tenant_ad_metric_aggregates"),
        ("ix_tenant_ad_metric_values_tenant_key", "tenant_ad_metric_values"),
        ("ix_tenant_ad_metric_values_entity_key", "tenant_ad_metric_values"),
        ("ix_tenant_ad_metric_values_snapshot", "tenant_ad_metric_values"),
        ("ix_tenant_ad_metric_values_tenant_id", "tenant_ad_metric_values"),
        ("ix_tenant_ad_metric_snapshots_account", "tenant_ad_metric_snapshots"),
        ("ix_tenant_ad_metric_snapshots_tenant_observed", "tenant_ad_metric_snapshots"),
        ("ix_tenant_ad_metric_snapshots_entity_observed", "tenant_ad_metric_snapshots"),
        ("ix_tenant_ad_metric_snapshots_tenant_id", "tenant_ad_metric_snapshots"),
        ("ix_tenant_ad_metric_ingestion_runs_account", "tenant_ad_metric_ingestion_runs"),
        ("ix_tenant_ad_metric_ingestion_runs_tenant_status", "tenant_ad_metric_ingestion_runs"),
        ("ix_tenant_ad_metric_ingestion_runs_tenant_created", "tenant_ad_metric_ingestion_runs"),
        ("ix_tenant_ad_metric_ingestion_runs_tenant_id", "tenant_ad_metric_ingestion_runs"),
        ("ix_tenant_ad_entity_history_observed", "tenant_ad_entity_history"),
        ("ix_tenant_ad_entity_history_account", "tenant_ad_entity_history"),
        ("ix_tenant_ad_entity_history_entity", "tenant_ad_entity_history"),
        ("ix_tenant_ad_entity_history_tenant_id", "tenant_ad_entity_history"),
        ("ix_tenant_ad_import_runs_account", "tenant_ad_import_runs"),
        ("ix_tenant_ad_import_runs_tenant_status", "tenant_ad_import_runs"),
        ("ix_tenant_ad_import_runs_tenant_created", "tenant_ad_import_runs"),
        ("ix_tenant_ad_import_runs_tenant_id", "tenant_ad_import_runs"),
        ("ix_tenant_ads_tenant_status", "tenant_ads"),
        ("ix_tenant_ads_campaign", "tenant_ads"),
        ("ix_tenant_ads_ad_group", "tenant_ads"),
        ("ix_tenant_ads_account", "tenant_ads"),
        ("ix_tenant_ads_tenant_id", "tenant_ads"),
        ("ix_tenant_ad_groups_tenant_status", "tenant_ad_groups"),
        ("ix_tenant_ad_groups_campaign", "tenant_ad_groups"),
        ("ix_tenant_ad_groups_account", "tenant_ad_groups"),
        ("ix_tenant_ad_groups_tenant_id", "tenant_ad_groups"),
        ("ix_tenant_ad_campaigns_tenant_status", "tenant_ad_campaigns"),
        ("ix_tenant_ad_campaigns_account", "tenant_ad_campaigns"),
        ("ix_tenant_ad_campaigns_tenant_id", "tenant_ad_campaigns"),
        ("ix_tenant_ad_creatives_account", "tenant_ad_creatives"),
        ("ix_tenant_ad_creatives_tenant_id", "tenant_ad_creatives"),
        ("ix_tenant_advertising_accounts_integration", "tenant_advertising_accounts"),
        ("ix_tenant_advertising_accounts_tenant_conn", "tenant_advertising_accounts"),
        ("ix_tenant_advertising_accounts_tenant_provider", "tenant_advertising_accounts"),
        ("ix_tenant_advertising_accounts_tenant_id", "tenant_advertising_accounts"),
    ):
        drop_index_if_exists(idx, tbl)

    # Drop advertising tables only (respect FK order). Measurement tables are
    # deliberately left intact. CASCADE on the account root is a safety net for
    # any leftover child FKs (e.g. from ensure_* DDL drift).
    for tbl in (
        "tenant_ad_campaign_links",
        "tenant_ad_creative_links",
        "tenant_ad_delivery_anomalies",
        "tenant_ad_budget_snapshots",
        "tenant_ad_conversion_breakdowns",
        "tenant_ad_metric_aggregates",
        "tenant_ad_metric_values",
        "tenant_ad_metric_snapshots",
        "tenant_ad_metric_ingestion_runs",
        "tenant_ad_entity_history",
        "tenant_ad_import_runs",
        "tenant_ads",
        "tenant_ad_groups",
        "tenant_ad_campaigns",
        "tenant_ad_creatives",
    ):
        drop_table_if_exists(tbl)
    if table_exists("tenant_advertising_accounts"):
        op.execute(sa.text('DROP TABLE IF EXISTS tenant_advertising_accounts CASCADE'))
