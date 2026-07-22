"""Marketing Intelligence Phase 2 — Measurement foundation (tenant-scoped).

Canonical external publication identity + immutable metric observations.
Deliberately separate from ContentItem (one item may publish to many platforms).

Design notes:
- Metric snapshots are append-only; historical observations are never overwritten.
- Provider-native metrics remain distinct from normalized catalog metrics.
- Attribution methods and confidence are always explicit; no probabilistic MTA.
- Measurement never publishes, schedules, or mutates campaign plans.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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

MEASUREMENT_VERSION = "1.0.0"
CALCULATION_VERSION = "1.0.0"
METRIC_SEMANTICS_VERSION = "1.0.0"

PUBLICATION_STATUSES = frozenset({
    "published",
    "partially_available",
    "deleted",
    "unavailable",
    "unknown",
})

SNAPSHOT_STATUSES = frozenset({"complete", "partial", "unavailable", "invalid"})

INGESTION_RUN_STATUSES = frozenset({
    "pending",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
})

VALUE_TYPES = frozenset({"count", "ratio", "duration_seconds", "currency_minor"})
AGGREGATION_TYPES = frozenset({"cumulative", "interval", "point_in_time", "derived"})

FRESHNESS_STATUSES = frozenset({
    "fresh",
    "aging",
    "stale",
    "unavailable",
    "unsupported",
})

ATTRIBUTION_METHODS = frozenset({
    "direct_slot_assignment",
    "direct_campaign_publication",
    "manual_link",
    "unattributed",
})

ATTRIBUTION_STATUSES = frozenset({"active", "superseded", "revoked"})

ANOMALY_KEYS = frozenset({
    "cumulative_metric_decreased",
    "negative_metric",
    "ratio_out_of_range",
    "provider_timestamp_regressed",
    "duplicate_provider_identity",
    "snapshot_time_regressed",
    "unexpected_metric_type",
    "extreme_jump",
    "missing_required_metric",
})

ANOMALY_SEVERITIES = frozenset({"info", "warning", "error", "critical"})
ANOMALY_STATUSES = frozenset({"open", "acknowledged", "resolved", "dismissed"})

WINDOW_KEYS = frozenset({"24h", "72h", "7d", "14d", "30d", "lifetime"})

JOB_KINDS = frozenset({"metrics_collect", "metrics_backfill", "metrics_aggregate"})
JOB_STATUSES = frozenset({
    "scheduled",
    "leased",
    "running",
    "succeeded",
    "failed",
    "dead_letter",
    "cancelled",
    "paused",
})

TRACKED_LINK_STATUSES = frozenset({"active", "disabled"})


class TenantExternalPublication(Base):
    """Canonical record of an actual external publication (provider post)."""

    __tablename__ = "tenant_external_publications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "publishing_account_id",
            "platform",
            "provider_publication_id",
            name="uq_tenant_external_publications_provider_identity",
        ),
        Index("ix_tenant_ext_pubs_tenant_platform", "tenant_id", "platform"),
        Index("ix_tenant_ext_pubs_tenant_content", "tenant_id", "content_id"),
        Index("ix_tenant_ext_pubs_tenant_campaign", "tenant_id", "campaign_id"),
        Index("ix_tenant_ext_pubs_tenant_published", "tenant_id", "published_at"),
        Index("ix_tenant_ext_pubs_tenant_freshness", "tenant_id", "freshness_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    publishing_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_publication_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_parent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_permalink: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    publication_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="published",
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    last_metric_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unavailable",
    )
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generation_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    publishing_review_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    publishing_score_at_publish: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    campaign_plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    campaign_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_calendar_slots.id", ondelete="SET NULL"),
        nullable=True,
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_slot_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    publish_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publish_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_pillar_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    campaign_phase_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_mock: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantMetricIngestionRun(Base):
    __tablename__ = "tenant_metric_ingestion_runs"
    __table_args__ = (
        Index("ix_tenant_metric_ingestion_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_tenant_metric_ingestion_runs_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    publishing_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor_before: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(String(255), nullable=True)
    publications_requested: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    publications_succeeded: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    publications_failed: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    provider_request_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_metadata: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantPublicationMetricSnapshot(Base):
    """Immutable observation of provider metrics at a point in time."""

    __tablename__ = "tenant_publication_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "external_publication_id",
            "snapshot_fingerprint",
            name="uq_tenant_pub_metric_snapshots_fingerprint",
        ),
        Index("ix_tenant_pub_metric_snapshots_pub_observed", "external_publication_id", "observed_at"),
        Index("ix_tenant_pub_metric_snapshots_tenant_observed", "tenant_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    external_publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_external_publications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    publishing_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_data_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    snapshot_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_metric_ingestion_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="complete")
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="provider")
    raw_metric_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantPublicationMetricValue(Base):
    __tablename__ = "tenant_publication_metric_values"
    __table_args__ = (
        Index("ix_tenant_pub_metric_values_snapshot", "metric_snapshot_id"),
        Index("ix_tenant_pub_metric_values_pub_key", "external_publication_id", "metric_key"),
        Index("ix_tenant_pub_metric_values_tenant_key", "tenant_id", "metric_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    metric_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_publication_metric_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_external_publications.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_metric_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    value_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="count")
    aggregation_type: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="cumulative",
    )
    metric_semantics_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=METRIC_SEMANTICS_VERSION,
    )
    normalization_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="normalized",
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantPublicationMetricAggregate(Base):
    __tablename__ = "tenant_publication_metric_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "external_publication_id",
            "window_key",
            "metric_key",
            "calculation_version",
            name="uq_tenant_pub_metric_aggregates_window",
        ),
        Index("ix_tenant_pub_metric_aggregates_pub", "external_publication_id", "window_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    external_publication_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_external_publications.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_key: Mapped[str] = mapped_column(String(20), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    calculation_method: Mapped[str] = mapped_column(String(80), nullable=False, server_default="latest_cumulative")
    calculation_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=CALCULATION_VERSION,
    )
    freshness_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unavailable")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="1.000")
    source_snapshot_ids: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantCampaignMetricAggregate(Base):
    __tablename__ = "tenant_campaign_metric_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "campaign_id",
            "campaign_plan_version_id",
            "metric_key",
            "window_start",
            "window_end",
            "attribution_scope",
            "calculation_version",
            name="uq_tenant_campaign_metric_aggregates",
        ),
        Index("ix_tenant_campaign_metric_aggregates_campaign", "tenant_id", "campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    aggregation_method: Mapped[str] = mapped_column(String(80), nullable=False, server_default="sum_attributed")
    attribution_scope: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="direct_slot_assignment",
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="1.000")
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calculation_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=CALCULATION_VERSION,
    )
    publication_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAttributionRecord(Base):
    __tablename__ = "tenant_attribution_records"
    __table_args__ = (
        Index("ix_tenant_attribution_records_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_tenant_attribution_records_target", "tenant_id", "target_type", "target_id"),
        Index("ix_tenant_attribution_records_source", "tenant_id", "source_type", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    attribution_method: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="0.000")
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantMeasurementAnomaly(Base):
    __tablename__ = "tenant_measurement_anomalies"
    __table_args__ = (
        Index("ix_tenant_measurement_anomalies_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_measurement_anomalies_pub", "external_publication_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    external_publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_external_publications.id", ondelete="CASCADE"),
        nullable=True,
    )
    metric_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_publication_metric_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    anomaly_key: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="warning")
    metric_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantMeasurementJob(Base):
    """Durable measurement collection jobs — separate from automation_flow jobs."""

    __tablename__ = "tenant_measurement_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "deduplication_key",
            name="uq_tenant_measurement_jobs_dedupe",
        ),
        Index("ix_tenant_measurement_jobs_claim", "status", "available_at", "priority"),
        Index("ix_tenant_measurement_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_measurement_jobs_lease", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    external_publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_external_publications.id", ondelete="CASCADE"),
        nullable=True,
    )
    publishing_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    job_kind: Mapped[str] = mapped_column(String(40), nullable=False, server_default="metrics_collect")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="scheduled")
    priority: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="100")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="5")
    deduplication_key: Mapped[str] = mapped_column(String(255), nullable=False)
    cadence_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_metadata: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantTrackedLink(Base):
    """Optional explicit tracked-link contract (no auto-rewriting of captions)."""

    __tablename__ = "tenant_tracked_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tracking_code", name="uq_tenant_tracked_links_code"),
        Index("ix_tenant_tracked_links_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    destination_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    tracking_code: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantTrackedLinkClicksDaily(Base):
    __tablename__ = "tenant_tracked_link_clicks_daily"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "tracked_link_id",
            "day_utc",
            name="uq_tenant_tracked_link_clicks_daily",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tracked_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_tracked_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_utc: Mapped[str] = mapped_column(String(10), nullable=False)
    click_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
