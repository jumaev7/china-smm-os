"""Marketing Intelligence Phase 2 — Measurement foundation (tenant-scoped).

Creates the canonical external-publication identity plus immutable metric
observation tables. Deliberately separate from ContentItem (one item may
publish to many platforms) and from the legacy analytics tables.

No secrets columns are created by this migration — provider tokens/credentials
live exclusively on ``publishing_accounts`` and are never duplicated here.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    create_foreign_key_if_missing,
    create_index_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    table_exists,
)

revision = "20260911_measurement_foundation"
down_revision = "20260910_campaign_planner"
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

    # ------------------------------------------------------- external publications
    if not table_exists("tenant_external_publications"):
        op.create_table(
            "tenant_external_publications",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_variant_id", UUID(as_uuid=True), nullable=True),
            sa.Column("publishing_account_id", UUID(as_uuid=True), sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("platform", sa.String(40), nullable=False),
            sa.Column("provider_publication_id", sa.String(255), nullable=False),
            sa.Column("provider_parent_id", sa.String(255), nullable=True),
            sa.Column("provider_permalink", sa.String(2000), nullable=True),
            sa.Column("publication_status", sa.String(40), nullable=False, server_default="published"),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            _ts("first_seen_at"),
            _ts("last_seen_at"),
            sa.Column("last_metric_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("freshness_status", sa.String(40), nullable=False, server_default="unavailable"),
            sa.Column("source_fingerprint", sa.String(128), nullable=True),
            sa.Column("generation_method", sa.String(40), nullable=True),
            sa.Column("publishing_review_id", UUID(as_uuid=True), nullable=True),
            sa.Column("publishing_score_at_publish", sa.Integer(), nullable=True),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="SET NULL"), nullable=True),
            sa.Column("campaign_plan_version_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_plan_versions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("campaign_slot_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_calendar_slots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("assignment_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_slot_assignments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("publish_attempt_id", UUID(as_uuid=True), sa.ForeignKey("publish_attempts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_pillar_id", UUID(as_uuid=True), nullable=True),
            sa.Column("campaign_phase_id", UUID(as_uuid=True), nullable=True),
            sa.Column("locale", sa.String(10), nullable=True),
            sa.Column("is_mock", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "tenant_id", "publishing_account_id", "platform", "provider_publication_id",
                name="uq_tenant_external_publications_provider_identity",
            ),
        )
    create_index_if_missing("ix_tenant_ext_pubs_tenant_platform", "tenant_external_publications", ["tenant_id", "platform"])
    create_index_if_missing("ix_tenant_ext_pubs_tenant_content", "tenant_external_publications", ["tenant_id", "content_id"])
    create_index_if_missing("ix_tenant_ext_pubs_tenant_campaign", "tenant_external_publications", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_ext_pubs_tenant_published", "tenant_external_publications", ["tenant_id", "published_at"])
    create_index_if_missing("ix_tenant_ext_pubs_tenant_freshness", "tenant_external_publications", ["tenant_id", "freshness_status"])
    create_index_if_missing("ix_tenant_external_publications_tenant_id", "tenant_external_publications", ["tenant_id"])

    # Optional FK to content optimizer variants when that table exists.
    if table_exists("tenant_content_variants"):
        create_foreign_key_if_missing(
            "fk_tenant_external_publications_content_variant",
            "tenant_external_publications",
            "tenant_content_variants",
            ["content_variant_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # ------------------------------------------------------------- ingestion runs
    if not table_exists("tenant_metric_ingestion_runs"):
        op.create_table(
            "tenant_metric_ingestion_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("publishing_account_id", UUID(as_uuid=True), sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("platform", sa.String(40), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
            _ts("requested_at"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cursor_before", sa.String(255), nullable=True),
            sa.Column("cursor_after", sa.String(255), nullable=True),
            sa.Column("publications_requested", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("publications_succeeded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("publications_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("provider_request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_code", sa.String(80), nullable=True),
            sa.Column("failure_metadata", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_metric_ingestion_runs_tenant_created", "tenant_metric_ingestion_runs", ["tenant_id", "created_at"])
    create_index_if_missing("ix_tenant_metric_ingestion_runs_tenant_status", "tenant_metric_ingestion_runs", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_metric_ingestion_runs_tenant_id", "tenant_metric_ingestion_runs", ["tenant_id"])

    # ------------------------------------------------------------- metric snapshots
    if not table_exists("tenant_publication_metric_snapshots"):
        op.create_table(
            "tenant_publication_metric_snapshots",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("external_publication_id", UUID(as_uuid=True), sa.ForeignKey("tenant_external_publications.id", ondelete="CASCADE"), nullable=False),
            sa.Column("publishing_account_id", UUID(as_uuid=True), sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("platform", sa.String(40), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("provider_data_timestamp", sa.DateTime(timezone=True), nullable=True),
            sa.Column("snapshot_fingerprint", sa.String(128), nullable=False),
            sa.Column("ingestion_run_id", UUID(as_uuid=True), sa.ForeignKey("tenant_metric_ingestion_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="complete"),
            sa.Column("source", sa.String(40), nullable=False, server_default="provider"),
            sa.Column("raw_metric_summary", JSONB(), nullable=True),
            _ts("created_at"),
            sa.UniqueConstraint(
                "tenant_id", "external_publication_id", "snapshot_fingerprint",
                name="uq_tenant_pub_metric_snapshots_fingerprint",
            ),
        )
    create_index_if_missing("ix_tenant_pub_metric_snapshots_pub_observed", "tenant_publication_metric_snapshots", ["external_publication_id", "observed_at"])
    create_index_if_missing("ix_tenant_pub_metric_snapshots_tenant_observed", "tenant_publication_metric_snapshots", ["tenant_id", "observed_at"])
    create_index_if_missing("ix_tenant_publication_metric_snapshots_tenant_id", "tenant_publication_metric_snapshots", ["tenant_id"])

    # --------------------------------------------------------------- metric values
    if not table_exists("tenant_publication_metric_values"):
        op.create_table(
            "tenant_publication_metric_values",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("metric_snapshot_id", UUID(as_uuid=True), sa.ForeignKey("tenant_publication_metric_snapshots.id", ondelete="CASCADE"), nullable=False),
            sa.Column("external_publication_id", UUID(as_uuid=True), sa.ForeignKey("tenant_external_publications.id", ondelete="CASCADE"), nullable=False),
            sa.Column("metric_key", sa.String(120), nullable=False),
            sa.Column("provider_metric_key", sa.String(120), nullable=True),
            sa.Column("metric_value", sa.Numeric(24, 6), nullable=False),
            sa.Column("value_type", sa.String(40), nullable=False, server_default="count"),
            sa.Column("aggregation_type", sa.String(40), nullable=False, server_default="cumulative"),
            sa.Column("metric_semantics_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("normalization_status", sa.String(40), nullable=False, server_default="normalized"),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_pub_metric_values_snapshot", "tenant_publication_metric_values", ["metric_snapshot_id"])
    create_index_if_missing("ix_tenant_pub_metric_values_pub_key", "tenant_publication_metric_values", ["external_publication_id", "metric_key"])
    create_index_if_missing("ix_tenant_pub_metric_values_tenant_key", "tenant_publication_metric_values", ["tenant_id", "metric_key"])
    create_index_if_missing("ix_tenant_publication_metric_values_tenant_id", "tenant_publication_metric_values", ["tenant_id"])

    # ----------------------------------------------------------- metric aggregates
    if not table_exists("tenant_publication_metric_aggregates"):
        op.create_table(
            "tenant_publication_metric_aggregates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("external_publication_id", UUID(as_uuid=True), sa.ForeignKey("tenant_external_publications.id", ondelete="CASCADE"), nullable=False),
            sa.Column("window_key", sa.String(20), nullable=False),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metric_key", sa.String(120), nullable=False),
            sa.Column("metric_value", sa.Numeric(24, 6), nullable=False),
            sa.Column("calculation_method", sa.String(80), nullable=False, server_default="latest_cumulative"),
            sa.Column("calculation_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("freshness_status", sa.String(40), nullable=False, server_default="unavailable"),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
            sa.Column("source_snapshot_ids", JSONB(), nullable=True),
            _ts("calculated_at"),
            sa.UniqueConstraint(
                "tenant_id", "external_publication_id", "window_key", "metric_key", "calculation_version",
                name="uq_tenant_pub_metric_aggregates_window",
            ),
        )
    create_index_if_missing("ix_tenant_pub_metric_aggregates_pub", "tenant_publication_metric_aggregates", ["external_publication_id", "window_key"])
    create_index_if_missing("ix_tenant_publication_metric_aggregates_tenant_id", "tenant_publication_metric_aggregates", ["tenant_id"])

    # ------------------------------------------------------- campaign metric aggregates
    if not table_exists("tenant_campaign_metric_aggregates"):
        op.create_table(
            "tenant_campaign_metric_aggregates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("campaign_plan_version_id", UUID(as_uuid=True), sa.ForeignKey("tenant_campaign_plan_versions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("metric_key", sa.String(120), nullable=False),
            sa.Column("metric_value", sa.Numeric(24, 6), nullable=False),
            sa.Column("aggregation_method", sa.String(80), nullable=False, server_default="sum_attributed"),
            sa.Column("attribution_scope", sa.String(80), nullable=False, server_default="direct_slot_assignment"),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1.000"),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("calculation_version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("publication_count", sa.Integer(), nullable=False, server_default="0"),
            _ts("calculated_at"),
            sa.UniqueConstraint(
                "tenant_id", "campaign_id", "campaign_plan_version_id", "metric_key",
                "window_start", "window_end", "attribution_scope", "calculation_version",
                name="uq_tenant_campaign_metric_aggregates",
            ),
        )
    create_index_if_missing("ix_tenant_campaign_metric_aggregates_campaign", "tenant_campaign_metric_aggregates", ["tenant_id", "campaign_id"])
    create_index_if_missing("ix_tenant_campaign_metric_aggregates_tenant_id", "tenant_campaign_metric_aggregates", ["tenant_id"])

    # -------------------------------------------------------------- attribution
    if not table_exists("tenant_attribution_records"):
        op.create_table(
            "tenant_attribution_records",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("entity_type", sa.String(80), nullable=False),
            sa.Column("entity_id", sa.String(80), nullable=False),
            sa.Column("source_type", sa.String(80), nullable=False),
            sa.Column("source_id", sa.String(80), nullable=False),
            sa.Column("target_type", sa.String(80), nullable=False),
            sa.Column("target_id", sa.String(80), nullable=False),
            sa.Column("attribution_method", sa.String(80), nullable=False),
            sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0.000"),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="active"),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_attribution_records_entity", "tenant_attribution_records", ["tenant_id", "entity_type", "entity_id"])
    create_index_if_missing("ix_tenant_attribution_records_target", "tenant_attribution_records", ["tenant_id", "target_type", "target_id"])
    create_index_if_missing("ix_tenant_attribution_records_source", "tenant_attribution_records", ["tenant_id", "source_type", "source_id"])
    create_index_if_missing("ix_tenant_attribution_records_tenant_id", "tenant_attribution_records", ["tenant_id"])

    # ------------------------------------------------------------------- anomalies
    if not table_exists("tenant_measurement_anomalies"):
        op.create_table(
            "tenant_measurement_anomalies",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("external_publication_id", UUID(as_uuid=True), sa.ForeignKey("tenant_external_publications.id", ondelete="CASCADE"), nullable=True),
            sa.Column("metric_snapshot_id", UUID(as_uuid=True), sa.ForeignKey("tenant_publication_metric_snapshots.id", ondelete="SET NULL"), nullable=True),
            sa.Column("anomaly_key", sa.String(80), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
            sa.Column("metric_key", sa.String(120), nullable=True),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="open"),
            _ts("created_at"),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
    create_index_if_missing("ix_tenant_measurement_anomalies_tenant_status", "tenant_measurement_anomalies", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_measurement_anomalies_pub", "tenant_measurement_anomalies", ["external_publication_id"])
    create_index_if_missing("ix_tenant_measurement_anomalies_tenant_id", "tenant_measurement_anomalies", ["tenant_id"])

    # -------------------------------------------------------------- measurement jobs
    if not table_exists("tenant_measurement_jobs"):
        op.create_table(
            "tenant_measurement_jobs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("external_publication_id", UUID(as_uuid=True), sa.ForeignKey("tenant_external_publications.id", ondelete="CASCADE"), nullable=True),
            sa.Column("publishing_account_id", UUID(as_uuid=True), sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("platform", sa.String(40), nullable=False),
            sa.Column("job_kind", sa.String(40), nullable=False, server_default="metrics_collect"),
            sa.Column("status", sa.String(40), nullable=False, server_default="scheduled"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            _ts("available_at"),
            sa.Column("lease_owner", sa.String(120), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("deduplication_key", sa.String(255), nullable=False),
            sa.Column("cadence_key", sa.String(40), nullable=True),
            sa.Column("last_error_code", sa.String(80), nullable=True),
            sa.Column("last_error_metadata", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "deduplication_key", name="uq_tenant_measurement_jobs_dedupe"),
        )
    create_index_if_missing("ix_tenant_measurement_jobs_claim", "tenant_measurement_jobs", ["status", "available_at", "priority"])
    create_index_if_missing("ix_tenant_measurement_jobs_tenant_status", "tenant_measurement_jobs", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_measurement_jobs_lease", "tenant_measurement_jobs", ["lease_expires_at"])
    create_index_if_missing("ix_tenant_measurement_jobs_tenant_id", "tenant_measurement_jobs", ["tenant_id"])

    # ------------------------------------------------------------------- tracked links
    if not table_exists("tenant_tracked_links"):
        op.create_table(
            "tenant_tracked_links",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("destination_url", sa.String(2000), nullable=False),
            sa.Column("tracking_code", sa.String(64), nullable=False),
            sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("tenant_marketing_campaigns.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("content_variant_id", UUID(as_uuid=True), nullable=True),
            sa.Column("platform", sa.String(40), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "tracking_code", name="uq_tenant_tracked_links_code"),
        )
    create_index_if_missing("ix_tenant_tracked_links_tenant_status", "tenant_tracked_links", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_tracked_links_tenant_id", "tenant_tracked_links", ["tenant_id"])

    # Optional FK to content optimizer variants when that table exists.
    if table_exists("tenant_content_variants"):
        create_foreign_key_if_missing(
            "fk_tenant_tracked_links_content_variant",
            "tenant_tracked_links",
            "tenant_content_variants",
            ["content_variant_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # ----------------------------------------------------- tracked link clicks daily
    if not table_exists("tenant_tracked_link_clicks_daily"):
        op.create_table(
            "tenant_tracked_link_clicks_daily",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tracked_link_id", UUID(as_uuid=True), sa.ForeignKey("tenant_tracked_links.id", ondelete="CASCADE"), nullable=False),
            sa.Column("day_utc", sa.String(10), nullable=False),
            sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint("tenant_id", "tracked_link_id", "day_utc", name="uq_tenant_tracked_link_clicks_daily"),
        )
    create_index_if_missing("ix_tenant_tracked_link_clicks_daily_tenant_id", "tenant_tracked_link_clicks_daily", ["tenant_id"])
    create_index_if_missing("ix_tenant_tracked_link_clicks_daily_link", "tenant_tracked_link_clicks_daily", ["tracked_link_id"])


def downgrade() -> None:
    for idx, tbl in (
        ("ix_tenant_tracked_link_clicks_daily_link", "tenant_tracked_link_clicks_daily"),
        ("ix_tenant_tracked_link_clicks_daily_tenant_id", "tenant_tracked_link_clicks_daily"),
        ("ix_tenant_tracked_links_tenant_id", "tenant_tracked_links"),
        ("ix_tenant_tracked_links_tenant_status", "tenant_tracked_links"),
        ("ix_tenant_measurement_jobs_tenant_id", "tenant_measurement_jobs"),
        ("ix_tenant_measurement_jobs_lease", "tenant_measurement_jobs"),
        ("ix_tenant_measurement_jobs_tenant_status", "tenant_measurement_jobs"),
        ("ix_tenant_measurement_jobs_claim", "tenant_measurement_jobs"),
        ("ix_tenant_measurement_anomalies_tenant_id", "tenant_measurement_anomalies"),
        ("ix_tenant_measurement_anomalies_pub", "tenant_measurement_anomalies"),
        ("ix_tenant_measurement_anomalies_tenant_status", "tenant_measurement_anomalies"),
        ("ix_tenant_attribution_records_tenant_id", "tenant_attribution_records"),
        ("ix_tenant_attribution_records_source", "tenant_attribution_records"),
        ("ix_tenant_attribution_records_target", "tenant_attribution_records"),
        ("ix_tenant_attribution_records_entity", "tenant_attribution_records"),
        ("ix_tenant_campaign_metric_aggregates_tenant_id", "tenant_campaign_metric_aggregates"),
        ("ix_tenant_campaign_metric_aggregates_campaign", "tenant_campaign_metric_aggregates"),
        ("ix_tenant_publication_metric_aggregates_tenant_id", "tenant_publication_metric_aggregates"),
        ("ix_tenant_pub_metric_aggregates_pub", "tenant_publication_metric_aggregates"),
        ("ix_tenant_publication_metric_values_tenant_id", "tenant_publication_metric_values"),
        ("ix_tenant_pub_metric_values_tenant_key", "tenant_publication_metric_values"),
        ("ix_tenant_pub_metric_values_pub_key", "tenant_publication_metric_values"),
        ("ix_tenant_pub_metric_values_snapshot", "tenant_publication_metric_values"),
        ("ix_tenant_publication_metric_snapshots_tenant_id", "tenant_publication_metric_snapshots"),
        ("ix_tenant_pub_metric_snapshots_tenant_observed", "tenant_publication_metric_snapshots"),
        ("ix_tenant_pub_metric_snapshots_pub_observed", "tenant_publication_metric_snapshots"),
        ("ix_tenant_metric_ingestion_runs_tenant_id", "tenant_metric_ingestion_runs"),
        ("ix_tenant_metric_ingestion_runs_tenant_status", "tenant_metric_ingestion_runs"),
        ("ix_tenant_metric_ingestion_runs_tenant_created", "tenant_metric_ingestion_runs"),
        ("ix_tenant_external_publications_tenant_id", "tenant_external_publications"),
        ("ix_tenant_ext_pubs_tenant_freshness", "tenant_external_publications"),
        ("ix_tenant_ext_pubs_tenant_published", "tenant_external_publications"),
        ("ix_tenant_ext_pubs_tenant_campaign", "tenant_external_publications"),
        ("ix_tenant_ext_pubs_tenant_content", "tenant_external_publications"),
        ("ix_tenant_ext_pubs_tenant_platform", "tenant_external_publications"),
    ):
        drop_index_if_exists(idx, tbl)

    for tbl in (
        "tenant_tracked_link_clicks_daily",
        "tenant_tracked_links",
        "tenant_measurement_jobs",
        "tenant_measurement_anomalies",
        "tenant_attribution_records",
        "tenant_campaign_metric_aggregates",
        "tenant_publication_metric_aggregates",
        "tenant_publication_metric_values",
        "tenant_publication_metric_snapshots",
        "tenant_metric_ingestion_runs",
        "tenant_external_publications",
    ):
        drop_table_if_exists(tbl)
