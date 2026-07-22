"""HTTP schemas for Marketing Intelligence Phase 2 measurement APIs.

Clients cannot inject tenant_id or raw metric values for writes.
Requests use extra=forbid; responses use extra=ignore.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Publications
# ---------------------------------------------------------------------------


class PublicationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    content_id: UUID | str | None = None
    content_variant_id: UUID | str | None = None
    publishing_account_id: UUID | str | None = None
    platform: str
    provider_publication_id: str
    provider_permalink: str | None = None
    publication_status: str
    published_at: datetime | str | None = None
    first_seen_at: datetime | str | None = None
    last_seen_at: datetime | str | None = None
    last_metric_at: datetime | str | None = None
    freshness_status: str
    generation_method: str | None = None
    campaign_id: UUID | str | None = None
    campaign_plan_version_id: UUID | str | None = None
    campaign_slot_id: UUID | str | None = None
    assignment_id: UUID | str | None = None
    publish_attempt_id: UUID | str | None = None
    content_pillar_id: UUID | str | None = None
    campaign_phase_id: UUID | str | None = None
    locale: str | None = None
    is_mock: bool = False
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class PublicationListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[PublicationResponse]
    total: int


# ---------------------------------------------------------------------------
# Snapshots / metric values / aggregates
# ---------------------------------------------------------------------------


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    external_publication_id: UUID | str
    platform: str
    observed_at: datetime | str
    provider_data_timestamp: datetime | str | None = None
    snapshot_fingerprint: str
    ingestion_run_id: UUID | str | None = None
    status: str
    source: str
    created_at: datetime | str | None = None


class SnapshotListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[SnapshotResponse]
    total: int


class MetricValueResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str | None = None
    metric_key: str
    provider_metric_key: str | None = None
    metric_value: Decimal | float | str | None = None
    value_type: str | None = None
    aggregation_type: str | None = None
    normalization_status: str | None = None
    metric_semantics_version: str | None = None


class AggregateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str | None = None
    external_publication_id: UUID | str | None = None
    campaign_id: UUID | str | None = None
    window_key: str | None = None
    window_start: datetime | str | None = None
    window_end: datetime | str | None = None
    metric_key: str
    metric_value: Decimal | float | str | None = None
    calculation_method: str | None = None
    calculation_version: str | None = None
    aggregation_method: str | None = None
    attribution_scope: str | None = None
    freshness_status: str | None = None
    confidence: Decimal | float | str | None = None
    publication_count: int | None = None
    source_snapshot_ids: list[Any] | None = None
    calculated_at: datetime | str | None = None


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


class BaselineResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metric_key: str
    platform: str | None = None
    sample_size: int = 0
    median: Decimal | float | str | None = None
    mean: Decimal | float | str | None = None
    p75: Decimal | float | str | None = None
    lookback_days: int = 0
    sufficient: bool = False


class PerformanceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_type: str
    entity_id: str
    metric_key: str
    classification: str
    value: Decimal | float | str | None = None
    baseline: BaselineResponse | None = None
    delta_ratio: Decimal | float | str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    freshness_status: str | None = None
    confidence: Decimal | float | str | None = None


# ---------------------------------------------------------------------------
# Campaign measurement / KPI / attribution
# ---------------------------------------------------------------------------


class KpiProgressResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kpi_id: UUID | str
    campaign_id: UUID | str
    metric_key: str
    target_value: Decimal | float | str | None = None
    current_value: Decimal | float | str | None = None
    comparator: str
    status: str
    progress_ratio: Decimal | float | str | None = None
    confidence: Decimal | float | str | None = None
    freshness_status: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class AttributionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str | None = None
    entity_type: str
    entity_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    attribution_method: str
    confidence: Decimal | float | str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    created_at: datetime | str | None = None


class CampaignMeasurementResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: UUID | str
    publication_count: int = 0
    metrics: list[AggregateResponse] = Field(default_factory=list)
    kpi_progress: list[KpiProgressResponse] = Field(default_factory=list)
    attribution: list[AttributionResponse] = Field(default_factory=list)
    freshness_status: str | None = None
    confidence: Decimal | float | str | None = None


# ---------------------------------------------------------------------------
# Overview / platforms / anomalies / freshness / configuration
# ---------------------------------------------------------------------------


class OverviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    publication_count: int = 0
    fresh_count: int = 0
    aging_count: int = 0
    stale_count: int = 0
    unavailable_count: int = 0
    unsupported_count: int = 0
    open_anomaly_count: int = 0
    tracked_link_count: int = 0
    platforms: list[str] = Field(default_factory=list)
    catalog_version: str | None = None
    measurement_version: str | None = None


class PlatformCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    platform: str
    capability_status: str
    supports_post_level_metrics: bool = False
    supported_metric_keys: list[str] = Field(default_factory=list)
    unsupported_reason: str | None = None
    notes: str | None = None


class AnomalyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    external_publication_id: UUID | str | None = None
    metric_snapshot_id: UUID | str | None = None
    anomaly_key: str
    severity: str
    metric_key: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime | str | None = None
    resolved_at: datetime | str | None = None


class FreshnessResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    age_seconds: float | None = None
    last_observation_at: datetime | str | None = None
    reason: str | None = None
    publication_id: UUID | str | None = None
    counts_by_status: dict[str, int] = Field(default_factory=dict)


class ConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    catalog_version: str
    measurement_version: str
    calculation_version: str
    metric_semantics_version: str
    metric_keys: list[str] = Field(default_factory=list)
    window_keys: list[str] = Field(default_factory=list)
    attribution_methods: list[str] = Field(default_factory=list)
    freshness_statuses: list[str] = Field(default_factory=list)
    platforms: list[PlatformCapabilityResponse] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tracked links
# ---------------------------------------------------------------------------


class TrackedLinkCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_url: str = Field(..., min_length=1, max_length=2000)
    campaign_id: UUID | None = None
    content_id: UUID | None = None
    content_variant_id: UUID | None = None
    platform: str | None = Field(default=None, max_length=40)


class TrackedLinkResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    destination_url: str
    tracking_code: str
    campaign_id: UUID | str | None = None
    content_id: UUID | str | None = None
    content_variant_id: UUID | str | None = None
    platform: str | None = None
    status: str
    created_by: UUID | str | None = None
    created_at: datetime | str | None = None
    disabled_at: datetime | str | None = None


class TrackedLinkListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[TrackedLinkResponse]
    total: int


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


class RefreshResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ingestion_run_id: UUID | str
    publication_id: UUID | str | None = None
    platform: str | None = None
    status: str
    publications_requested: int = 0
    publications_succeeded: int = 0
    publications_failed: int = 0
    failure_code: str | None = None
    requested_at: datetime | str | None = None
    completed_at: datetime | str | None = None
