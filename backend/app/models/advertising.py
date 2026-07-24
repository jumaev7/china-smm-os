"""Advertising Intelligence Phase 1 — read-only advertising foundation (tenant-scoped).

Canonical, tenant-scoped mirror of external advertising objects (accounts,
campaigns, ad groups, ads, creatives) plus immutable metric observations and
derived aggregates. Deliberately read-only: this domain never creates, edits,
pauses, activates, or budgets any provider-side object.

Design notes:
- READ-ONLY. There are no write paths to any provider from this domain.
- Money is always stored as integer *minor units* (e.g. cents) plus an explicit
  3-letter ``currency`` string. Metric magnitudes use ``Numeric(24, 6)``.
- Metric snapshots and entity-history rows are append-only (immutable); prior
  observations are never overwritten.
- NO secrets. Provider tokens/credentials live exclusively on
  ``publishing_accounts`` (via the optional ``integration_id`` pointer) and are
  never duplicated onto any advertising table.
- Every table is tenant-scoped; cross-tenant references are impossible by
  construction (all FKs carry ``tenant_id`` and are validated in the service
  layer, which resolves cross-tenant access to 404).
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

ADVERTISING_VERSION = "1.0.0"
AD_CALCULATION_VERSION = "1.0.0"
AD_METRIC_SEMANTICS_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Providers / platforms
# ---------------------------------------------------------------------------
# Only Meta (live, read-only) and Mock (deterministic demo/QA data) are wired
# in Phase 1. New providers are added here once their read-only adapter exists.
ADVERTISING_PROVIDERS = frozenset({"meta", "mock"})

# Delivery surfaces / platforms a provider account can serve.
ADVERTISING_PLATFORMS = frozenset({
    "facebook",
    "instagram",
    "audience_network",
    "messenger",
    "mock",
})

# ---------------------------------------------------------------------------
# Account lifecycle
# ---------------------------------------------------------------------------
# Provider-reported account status (what the ad account itself reports).
ACCOUNT_STATUSES = frozenset({
    "active",
    "disabled",
    "unsettled",
    "pending_risk_review",
    "pending_settlement",
    "in_grace_period",
    "pending_closure",
    "closed",
    "any_active",
    "any_closed",
    "unknown",
})

# Our local connection state for the tenant's link to the account.
CONNECTION_STATUSES = frozenset({
    "connected",
    "disconnected",
    "expired",
    "revoked",
    "permission_blocked",
    "error",
    "unknown",
})

# ---------------------------------------------------------------------------
# Entity delivery statuses (campaigns / ad groups / ads)
# ---------------------------------------------------------------------------
# Config status = the desired state as configured by the advertiser.
AD_CONFIG_STATUSES = frozenset({
    "active",
    "paused",
    "deleted",
    "archived",
    "unknown",
})

# Effective status = the actual delivery state as reported by the provider.
AD_EFFECTIVE_STATUSES = frozenset({
    "active",
    "paused",
    "deleted",
    "archived",
    "pending_review",
    "disapproved",
    "preapproved",
    "pending_billing_info",
    "campaign_paused",
    "adset_paused",
    "in_process",
    "with_issues",
    "completed",
    "unknown",
})

# ---------------------------------------------------------------------------
# Entity taxonomy
# ---------------------------------------------------------------------------
AD_ENTITY_TYPES = frozenset({
    "account",
    "campaign",
    "ad_group",
    "ad",
    "creative",
})

# Insight aggregation levels supported by the read pipeline.
AD_INSIGHT_LEVELS = frozenset({"account", "campaign", "ad_group", "ad"})

# ---------------------------------------------------------------------------
# Import / ingestion run vocab
# ---------------------------------------------------------------------------
IMPORT_RUN_STATUSES = frozenset({
    "pending",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
})

IMPORT_SCOPES = frozenset({
    "account",
    "campaigns",
    "ad_groups",
    "ads",
    "creatives",
    "full",
})

METRIC_INGESTION_RUN_STATUSES = frozenset({
    "pending",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
})

SNAPSHOT_STATUSES = frozenset({"complete", "partial", "unavailable", "invalid"})

# ---------------------------------------------------------------------------
# Metric vocab
# ---------------------------------------------------------------------------
VALUE_TYPES = frozenset({
    "count",
    "ratio",
    "currency_minor",
    "duration_seconds",
    "score",
})

AGGREGATION_TYPES = frozenset({"cumulative", "interval", "point_in_time", "derived"})

NORMALIZATION_STATUSES = frozenset({
    "normalized",
    "provider_native",
    "derived",
    "unmapped",
})

WINDOW_KEYS = frozenset({"24h", "72h", "7d", "14d", "30d", "lifetime"})

FRESHNESS_STATUSES = frozenset({
    "fresh",
    "aging",
    "stale",
    "unavailable",
    "unsupported",
})

# ---------------------------------------------------------------------------
# Change history (immutable)
# ---------------------------------------------------------------------------
ENTITY_CHANGE_TYPES = frozenset({
    "created",
    "updated",
    "status_changed",
    "budget_changed",
    "observed",
    "deleted",
})

CHANGE_SOURCES = frozenset({"provider", "mock", "system"})

# ---------------------------------------------------------------------------
# Budget / pacing
# ---------------------------------------------------------------------------
BUDGET_TYPES = frozenset({"daily", "lifetime", "unlimited", "unknown"})

PACING_STATUSES = frozenset({
    "not_applicable",
    "insufficient_data",
    "on_pace",
    "underspending",
    "overspending",
    "budget_exhausted",
    "ended",
    "paused",
})

# ---------------------------------------------------------------------------
# Delivery anomalies
# ---------------------------------------------------------------------------
DELIVERY_ANOMALY_KEYS = frozenset({
    "spend_without_impressions",
    "impressions_without_spend",
    "cumulative_metric_decreased",
    "negative_metric",
    "ratio_out_of_range",
    "budget_overspend",
    "zero_delivery_active_entity",
    "ctr_spike",
    "cpa_spike",
    "provider_timestamp_regressed",
    "duplicate_provider_identity",
    "missing_required_metric",
    "currency_mismatch",
})

ANOMALY_SEVERITIES = frozenset({"info", "warning", "error", "critical"})
ANOMALY_STATUSES = frozenset({"open", "acknowledged", "resolved", "dismissed"})

# ---------------------------------------------------------------------------
# Linking (attribution to internal content/campaigns)
# ---------------------------------------------------------------------------
LINK_METHODS = frozenset({
    "manual_link",
    "provider_reference",
    "url_match",
    "creative_asset_match",
    "unlinked",
})

LINK_STATUSES = frozenset({"active", "superseded", "revoked"})

# ---------------------------------------------------------------------------
# Advertising durable job kinds (share tenant_measurement_jobs table)
# ---------------------------------------------------------------------------
ADVERTISING_JOB_KINDS = frozenset({
    "advertising_account_import",
    "advertising_insights_ingestion",
    "advertising_freshness_check",
    "advertising_aggregate_rebuild",
})

# Domain discriminator on tenant_measurement_jobs.job_domain
ADVERTISING_JOB_DOMAIN = "advertising"


class TenantAdvertisingAccount(Base):
    """Tenant-scoped mirror of an external advertising account (read-only).

    ``integration_id`` optionally points at a ``publishing_accounts`` row that
    owns the OAuth credential. No tokens are ever stored on this table.
    """

    __tablename__ = "tenant_advertising_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_account_id",
            name="uq_tenant_advertising_accounts_provider_identity",
        ),
        Index("ix_tenant_advertising_accounts_tenant_provider", "tenant_id", "provider"),
        Index("ix_tenant_advertising_accounts_tenant_conn", "tenant_id", "connection_status"),
        Index("ix_tenant_advertising_accounts_integration", "integration_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Optional pointer to the credential-owning publishing account. Tokens live
    # there, never here.
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_business_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unknown",
    )
    connection_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unknown",
    )
    capabilities: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    permission_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    last_import_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_metrics_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_mock: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantAdCampaign(Base):
    """Tenant-scoped mirror of a provider ad campaign (read-only)."""

    __tablename__ = "tenant_ad_campaigns"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "advertising_account_id",
            "provider_campaign_id",
            name="uq_tenant_ad_campaigns_provider_identity",
        ),
        Index("ix_tenant_ad_campaigns_account", "tenant_id", "advertising_account_id"),
        Index("ix_tenant_ad_campaigns_tenant_status", "tenant_id", "effective_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_campaign_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    objective: Mapped[str | None] = mapped_column(String(80), nullable=True)
    buying_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    config_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    effective_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    bid_strategy: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Money is stored as integer minor units + explicit currency.
    daily_budget_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    lifetime_budget_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    budget_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    spend_cap_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    special_ad_categories: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    attribution_spec: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    provider_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_stop_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_updated_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantAdGroup(Base):
    """Tenant-scoped mirror of a provider ad group / ad set (read-only)."""

    __tablename__ = "tenant_ad_groups"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "advertising_account_id",
            "provider_ad_group_id",
            name="uq_tenant_ad_groups_provider_identity",
        ),
        Index("ix_tenant_ad_groups_account", "tenant_id", "advertising_account_id"),
        Index("ix_tenant_ad_groups_campaign", "tenant_id", "campaign_id"),
        Index("ix_tenant_ad_groups_tenant_status", "tenant_id", "effective_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_ad_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_campaign_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    effective_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    optimization_goal: Mapped[str | None] = mapped_column(String(80), nullable=True)
    billing_event: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bid_amount_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    bid_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    daily_budget_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    lifetime_budget_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    budget_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    targeting_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    provider_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_stop_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_updated_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantAd(Base):
    """Tenant-scoped mirror of a provider ad (read-only)."""

    __tablename__ = "tenant_ads"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "advertising_account_id",
            "provider_ad_id",
            name="uq_tenant_ads_provider_identity",
        ),
        Index("ix_tenant_ads_account", "tenant_id", "advertising_account_id"),
        Index("ix_tenant_ads_ad_group", "tenant_id", "ad_group_id"),
        Index("ix_tenant_ads_campaign", "tenant_id", "campaign_id"),
        Index("ix_tenant_ads_tenant_status", "tenant_id", "effective_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    ad_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_groups.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    creative_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_creatives.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_ad_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_ad_group_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_creative_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    effective_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    tracking_specs: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    provider_created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_updated_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantAdCreative(Base):
    """Tenant-scoped mirror of a provider ad creative (read-only, no assets stored)."""

    __tablename__ = "tenant_ad_creatives"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "advertising_account_id",
            "provider_creative_id",
            name="uq_tenant_ad_creatives_provider_identity",
        ),
        Index("ix_tenant_ad_creatives_account", "tenant_id", "advertising_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_creative_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text(), nullable=True)
    call_to_action_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    permalink_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    object_story_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    asset_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantAdEntityHistory(Base):
    """Immutable, append-only history of observed advertising-entity changes.

    Rows are never updated or deleted in normal operation; each observation
    captures a fingerprint diff for a single entity.
    """

    __tablename__ = "tenant_ad_entity_history"
    __table_args__ = (
        Index("ix_tenant_ad_entity_history_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_tenant_ad_entity_history_account", "tenant_id", "advertising_account_id"),
        Index("ix_tenant_ad_entity_history_observed", "tenant_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    provider_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="observed")
    field_changes: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    previous_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    import_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_import_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="provider")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdImportRun(Base):
    """A single structural import run (accounts/campaigns/ad groups/ads/creatives)."""

    __tablename__ = "tenant_ad_import_runs"
    __table_args__ = (
        Index("ix_tenant_ad_import_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_tenant_ad_import_runs_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_ad_import_runs_account", "advertising_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    scope: Mapped[str] = mapped_column(String(40), nullable=False, server_default="full")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor_before: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entities_requested: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    entities_created: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    entities_updated: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    entities_unchanged: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    entities_failed: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    provider_request_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_metadata: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdMetricIngestionRun(Base):
    """A single insights/metrics ingestion run for an account at a given level."""

    __tablename__ = "tenant_ad_metric_ingestion_runs"
    __table_args__ = (
        Index("ix_tenant_ad_metric_ingestion_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_tenant_ad_metric_ingestion_runs_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_ad_metric_ingestion_runs_account", "advertising_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    level: Mapped[str] = mapped_column(String(40), nullable=False, server_default="account")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    date_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_stop: Mapped[str | None] = mapped_column(String(10), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cursor_before: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entities_requested: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    entities_succeeded: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    entities_failed: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    snapshots_created: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    provider_request_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_metadata: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdMetricSnapshot(Base):
    """Immutable observation of provider metrics for one entity at a point in time."""

    __tablename__ = "tenant_ad_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "snapshot_fingerprint",
            name="uq_tenant_ad_metric_snapshots_fingerprint",
        ),
        Index("ix_tenant_ad_metric_snapshots_entity_observed", "entity_type", "entity_id", "observed_at"),
        Index("ix_tenant_ad_metric_snapshots_tenant_observed", "tenant_id", "observed_at"),
        Index("ix_tenant_ad_metric_snapshots_account", "tenant_id", "advertising_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[str] = mapped_column(String(40), nullable=False, server_default="account")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_data_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_stop: Mapped[str | None] = mapped_column(String(10), nullable=True)
    snapshot_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_metric_ingestion_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="complete")
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="provider")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    raw_metric_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdMetricValue(Base):
    """Individual normalized metric value belonging to a snapshot."""

    __tablename__ = "tenant_ad_metric_values"
    __table_args__ = (
        Index("ix_tenant_ad_metric_values_snapshot", "metric_snapshot_id"),
        Index("ix_tenant_ad_metric_values_entity_key", "entity_type", "entity_id", "metric_key"),
        Index("ix_tenant_ad_metric_values_tenant_key", "tenant_id", "metric_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    metric_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_metric_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_metric_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    value_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="count")
    aggregation_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="interval")
    # For currency_minor value types, the value is expressed in this currency's
    # minor units; NULL for non-monetary metrics.
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    metric_semantics_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AD_METRIC_SEMANTICS_VERSION,
    )
    normalization_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="normalized",
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdMetricAggregate(Base):
    """Derived per-entity windowed aggregate (recomputable)."""

    __tablename__ = "tenant_ad_metric_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "window_key",
            "metric_key",
            "calculation_version",
            name="uq_tenant_ad_metric_aggregates_window",
        ),
        Index("ix_tenant_ad_metric_aggregates_entity", "entity_type", "entity_id", "window_key"),
        Index("ix_tenant_ad_metric_aggregates_account", "tenant_id", "advertising_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    window_key: Mapped[str] = mapped_column(String(20), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    value_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="count")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    calculation_method: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="sum_interval",
    )
    calculation_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=AD_CALCULATION_VERSION,
    )
    freshness_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unavailable",
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="1.000")
    source_snapshot_ids: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdConversionBreakdown(Base):
    """Per-action-type conversion breakdown observed from provider insights.

    Attribution settings and windows are always explicit; no probabilistic MTA.
    """

    __tablename__ = "tenant_ad_conversion_breakdowns"
    __table_args__ = (
        Index("ix_tenant_ad_conversion_breakdowns_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_tenant_ad_conversion_breakdowns_snapshot", "metric_snapshot_id"),
        Index("ix_tenant_ad_conversion_breakdowns_action", "tenant_id", "action_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_metric_snapshots.id", ondelete="CASCADE"),
        nullable=True,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(120), nullable=False)
    action_destination: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attribution_setting: Mapped[str | None] = mapped_column(String(80), nullable=True)
    conversion_window: Mapped[str | None] = mapped_column(String(40), nullable=True)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    value_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="count")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    date_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_stop: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdBudgetSnapshot(Base):
    """Point-in-time budget/pacing observation for a campaign or ad group."""

    __tablename__ = "tenant_ad_budget_snapshots"
    __table_args__ = (
        Index("ix_tenant_ad_budget_snapshots_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_tenant_ad_budget_snapshots_observed", "tenant_id", "observed_at"),
        Index("ix_tenant_ad_budget_snapshots_account", "tenant_id", "advertising_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    budget_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    # Money as integer minor units + currency.
    budget_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    spend_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    remaining_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    utilization_ratio: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    pacing_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="provider")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdDeliveryAnomaly(Base):
    """Detected advertising delivery/data-quality anomaly (advisory only)."""

    __tablename__ = "tenant_ad_delivery_anomalies"
    __table_args__ = (
        Index("ix_tenant_ad_delivery_anomalies_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_ad_delivery_anomalies_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_tenant_ad_delivery_anomalies_account", "advertising_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    metric_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_metric_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    anomaly_key: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, server_default="warning")
    metric_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantAdCreativeLink(Base):
    """Explicit link between an ad creative and internal content / publication.

    Never auto-mutates content; only records an evidence-backed association so
    advertising performance can be correlated with organic content.
    """

    __tablename__ = "tenant_ad_creative_links"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "creative_id",
            "target_type",
            "target_id",
            name="uq_tenant_ad_creative_links_target",
        ),
        Index("ix_tenant_ad_creative_links_creative", "tenant_id", "creative_id"),
        Index("ix_tenant_ad_creative_links_target", "tenant_id", "target_type", "target_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    creative_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_creatives.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Generic (target_type, target_id) plus typed convenience FKs for the two
    # most common targets.
    target_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="content_item")
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    external_publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_external_publications.id", ondelete="SET NULL"),
        nullable=True,
    )
    link_method: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual_link")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="1.000")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAdCampaignLink(Base):
    """Explicit link between a provider ad campaign and an internal marketing campaign."""

    __tablename__ = "tenant_ad_campaign_links"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ad_campaign_id",
            "marketing_campaign_id",
            name="uq_tenant_ad_campaign_links_pair",
        ),
        Index("ix_tenant_ad_campaign_links_ad_campaign", "tenant_id", "ad_campaign_id"),
        Index("ix_tenant_ad_campaign_links_marketing", "tenant_id", "marketing_campaign_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    advertising_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_advertising_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    ad_campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ad_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    marketing_campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_campaign_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    link_method: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual_link")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="1.000")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


__all__ = [
    "ADVERTISING_VERSION",
    "AD_CALCULATION_VERSION",
    "AD_METRIC_SEMANTICS_VERSION",
    "ADVERTISING_PROVIDERS",
    "ADVERTISING_PLATFORMS",
    "ACCOUNT_STATUSES",
    "CONNECTION_STATUSES",
    "AD_CONFIG_STATUSES",
    "AD_EFFECTIVE_STATUSES",
    "AD_ENTITY_TYPES",
    "AD_INSIGHT_LEVELS",
    "IMPORT_RUN_STATUSES",
    "IMPORT_SCOPES",
    "METRIC_INGESTION_RUN_STATUSES",
    "SNAPSHOT_STATUSES",
    "VALUE_TYPES",
    "AGGREGATION_TYPES",
    "NORMALIZATION_STATUSES",
    "WINDOW_KEYS",
    "FRESHNESS_STATUSES",
    "ENTITY_CHANGE_TYPES",
    "CHANGE_SOURCES",
    "BUDGET_TYPES",
    "PACING_STATUSES",
    "DELIVERY_ANOMALY_KEYS",
    "ANOMALY_SEVERITIES",
    "ANOMALY_STATUSES",
    "LINK_METHODS",
    "LINK_STATUSES",
    "ADVERTISING_JOB_KINDS",
    "ADVERTISING_JOB_DOMAIN",
    "TenantAdvertisingAccount",
    "TenantAdCampaign",
    "TenantAdGroup",
    "TenantAd",
    "TenantAdCreative",
    "TenantAdEntityHistory",
    "TenantAdImportRun",
    "TenantAdMetricIngestionRun",
    "TenantAdMetricSnapshot",
    "TenantAdMetricValue",
    "TenantAdMetricAggregate",
    "TenantAdConversionBreakdown",
    "TenantAdBudgetSnapshot",
    "TenantAdDeliveryAnomaly",
    "TenantAdCreativeLink",
    "TenantAdCampaignLink",
]
