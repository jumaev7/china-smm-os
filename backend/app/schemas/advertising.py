"""HTTP schemas for the Advertising Intelligence APIs.

Read-only toward ad providers. Money is always represented in integer MINOR
units (e.g. cents) alongside an explicit ISO currency code; values from
different currencies are never summed. Provider-reported conversions are kept
distinct from CRM-confirmed conversions.

Requests use ``extra="forbid"``; responses use ``extra="ignore"``.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class AdvertisingAccountResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    provider: str
    external_account_id: str | None = None
    name: str
    currency: str | None = None
    timezone: str | None = None
    status: str
    is_mock: bool = False
    read_only: bool = True
    last_import_at: datetime | str | None = None
    last_metric_refresh_at: datetime | str | None = None
    freshness_status: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class AccountListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[AdvertisingAccountResponse]
    total: int
    read_only: bool = True


class AccountCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str
    display_name: str | None = None
    capability_status: str
    read_only: bool = True
    supports_campaign_metrics: bool = False
    supports_ad_level_metrics: bool = False
    supports_creative_metrics: bool = False
    supports_conversions: bool = False
    supported_metric_keys: list[str] = Field(default_factory=list)
    unsupported_reason: str | None = None
    notes: str | None = None


class RegisterMockAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="mock", max_length=40)
    name: str = Field(..., min_length=1, max_length=200)
    currency: str = Field(..., min_length=3, max_length=3)
    timezone: str | None = Field(default=None, max_length=60)
    external_account_id: str | None = Field(default=None, max_length=200)


class ImportRunResponse(BaseModel):
    """Result of a provider import or a metric refresh. Reads from the provider
    only — never mutates provider state."""

    model_config = ConfigDict(extra="ignore")

    import_run_id: UUID | str
    account_id: UUID | str
    provider: str | None = None
    kind: str = "import"  # "import" | "refresh_metrics"
    status: str
    campaigns_imported: int = 0
    ad_groups_imported: int = 0
    ads_imported: int = 0
    creatives_imported: int = 0
    metrics_updated: int = 0
    failure_code: str | None = None
    requested_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    read_only: bool = True


# ---------------------------------------------------------------------------
# Campaigns / ad groups / ads
# ---------------------------------------------------------------------------


class AdCampaignResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    account_id: UUID | str
    provider: str
    external_campaign_id: str | None = None
    name: str
    status: str
    objective: str | None = None
    currency: str | None = None
    budget_amount_minor: int | None = None
    budget_type: str | None = None
    start_date: date | datetime | str | None = None
    end_date: date | datetime | str | None = None
    spend_minor: int | None = None
    impressions: int | None = None
    clicks: int | None = None
    conversions_reported: int | None = None
    conversions_crm_confirmed: int | None = None
    pacing_status: str | None = None
    freshness_status: str | None = None
    last_metric_at: datetime | str | None = None
    linked_internal_campaign_id: UUID | str | None = None
    read_only: bool = True


class CampaignListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[AdCampaignResponse]
    total: int
    read_only: bool = True


class AdGroupResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    account_id: UUID | str
    campaign_id: UUID | str | None = None
    external_ad_group_id: str | None = None
    name: str
    status: str
    currency: str | None = None
    spend_minor: int | None = None
    impressions: int | None = None
    clicks: int | None = None
    conversions_reported: int | None = None
    delivery_status: str | None = None
    freshness_status: str | None = None
    read_only: bool = True


class AdGroupListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[AdGroupResponse]
    total: int
    read_only: bool = True


class AdResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    account_id: UUID | str
    campaign_id: UUID | str | None = None
    ad_group_id: UUID | str | None = None
    external_ad_id: str | None = None
    name: str
    status: str
    creative_id: UUID | str | None = None
    currency: str | None = None
    spend_minor: int | None = None
    impressions: int | None = None
    clicks: int | None = None
    conversions_reported: int | None = None
    freshness_status: str | None = None
    read_only: bool = True


class AdListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[AdResponse]
    total: int
    read_only: bool = True


# ---------------------------------------------------------------------------
# Creatives
# ---------------------------------------------------------------------------


class CreativeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    account_id: UUID | str
    external_creative_id: str | None = None
    name: str
    format: str | None = None
    preview_url: str | None = None
    thumbnail_url: str | None = None
    status: str | None = None
    fatigue_status: str | None = None
    currency: str | None = None
    spend_minor: int | None = None
    impressions: int | None = None
    clicks: int | None = None
    frequency: float | str | None = None
    first_seen_at: datetime | str | None = None
    last_seen_at: datetime | str | None = None
    linked_content_id: UUID | str | None = None
    read_only: bool = True


class CreativeListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[CreativeResponse]
    total: int
    read_only: bool = True


class CreativeDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    creative_id: UUID | str
    fatigue_status: str
    frequency: float | str | None = None
    impressions: int | None = None
    clicks: int | None = None
    ctr: float | str | None = None
    ctr_trend: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    freshness_status: str | None = None
    read_only: bool = True


# ---------------------------------------------------------------------------
# Performance / pacing / delivery
# ---------------------------------------------------------------------------


class PacingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: UUID | str | None = None
    status: str
    currency: str | None = None
    budget_amount_minor: int | None = None
    budget_type: str | None = None
    spend_minor: int | None = None
    expected_spend_minor: int | None = None
    pace_ratio: float | str | None = None
    days_elapsed: int | None = None
    days_total: int | None = None
    read_only: bool = True


class PerformancePoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: date | datetime | str
    currency: str | None = None
    spend_minor: int | None = None
    impressions: int | None = None
    clicks: int | None = None
    conversions_reported: int | None = None


class CampaignPerformanceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: UUID | str
    currency: str | None = None
    spend_minor: int | None = None
    impressions: int | None = None
    clicks: int | None = None
    ctr: float | str | None = None
    cpc_minor: int | None = None
    cpm_minor: int | None = None
    conversions_reported: int | None = None
    conversions_crm_confirmed: int | None = None
    cost_per_conversion_minor: int | None = None
    pacing: PacingResponse | None = None
    time_series: list[PerformancePoint] = Field(default_factory=list)
    freshness_status: str | None = None
    read_only: bool = True


class DeliveryDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ad_group_id: UUID | str
    delivery_status: str
    currency: str | None = None
    spend_minor: int | None = None
    impressions: int | None = None
    reasons: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    freshness_status: str | None = None
    read_only: bool = True


# ---------------------------------------------------------------------------
# Attribution / reconciliation
# ---------------------------------------------------------------------------


class CampaignAttributionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: UUID | str
    linked_internal_campaign_id: UUID | str | None = None
    conversions_reported: int | None = None
    conversions_crm_confirmed: int | None = None
    coverage_ratio: float | str | None = None
    currency: str | None = None
    methods: list[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


class AttributionCampaignRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: UUID | str
    campaign_name: str | None = None
    provider: str | None = None
    linked_internal_campaign_id: UUID | str | None = None
    conversions_reported: int | None = None
    conversions_crm_confirmed: int | None = None
    currency: str | None = None


class AttributionCoverageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    read_only: bool = True
    linked_campaign_count: int = 0
    unlinked_campaign_count: int = 0
    coverage_ratio: float | str | None = None
    reported_conversions: int = 0
    crm_confirmed_conversions: int = 0
    by_campaign: list[AttributionCampaignRow] = Field(default_factory=list)
    note: str | None = None


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    read_only: bool = True
    reported_conversions: int = 0
    crm_confirmed_conversions: int = 0
    matched_conversions: int = 0
    unmatched_reported: int = 0
    coverage_ratio: float | str | None = None
    by_campaign: list[dict[str, Any]] = Field(default_factory=list)
    note: str | None = None


# ---------------------------------------------------------------------------
# Linkage (internal only — never touches provider state)
# ---------------------------------------------------------------------------


class LinkCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    internal_campaign_id: UUID


class LinkContentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    internal_content_id: UUID


class LinkResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_type: str
    entity_id: UUID | str
    linked_internal_id: UUID | str | None = None
    linked: bool
    read_only: bool = True


# ---------------------------------------------------------------------------
# Overview / freshness / anomalies / configuration
# ---------------------------------------------------------------------------


class SpendByCurrencyRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    currency: str
    spend_minor: int = 0
    campaign_count: int = 0


class PacingWarningRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    campaign_id: UUID | str
    campaign_name: str | None = None
    pacing_status: str | None = None
    currency: str | None = None
    spend_minor: int | None = None
    budget_amount_minor: int | None = None


class OverviewAttributionCoverage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    linked_campaign_count: int = 0
    unlinked_campaign_count: int = 0
    coverage_ratio: float | str | None = None
    reported_conversions: int = 0
    crm_confirmed_conversions: int = 0


class FreshnessCounts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fresh: int = 0
    aging: int = 0
    stale: int = 0
    unavailable: int = 0
    unsupported: int = 0


class AdvertisingOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    read_only: bool = True
    account_count: int = 0
    connected_account_count: int = 0
    mock_account_count: int = 0
    active_campaign_count: int = 0
    campaign_count: int = 0
    spend_by_currency: list[SpendByCurrencyRow] = Field(default_factory=list)
    pacing_warnings: list[PacingWarningRow] = Field(default_factory=list)
    fatigue_warning_count: int = 0
    attribution_coverage: OverviewAttributionCoverage = Field(
        default_factory=OverviewAttributionCoverage
    )
    open_anomaly_count: int = 0
    freshness: FreshnessCounts = Field(default_factory=FreshnessCounts)
    providers: list[str] = Field(default_factory=list)
    catalog_version: str | None = None
    notes: list[str] = Field(default_factory=list)


class AccountFreshnessRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    account_id: UUID | str
    name: str | None = None
    provider: str | None = None
    freshness_status: str | None = None
    last_import_at: datetime | str | None = None
    last_metric_refresh_at: datetime | str | None = None


class AdvertisingFreshnessResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    last_import_at: datetime | str | None = None
    last_metric_refresh_at: datetime | str | None = None
    counts_by_status: dict[str, int] = Field(default_factory=dict)
    accounts: list[AccountFreshnessRow] = Field(default_factory=list)
    read_only: bool = True


class AdvertisingAnomalyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    account_id: UUID | str | None = None
    campaign_id: UUID | str | None = None
    entity_type: str | None = None
    entity_id: UUID | str | None = None
    anomaly_key: str
    severity: str
    metric_key: str | None = None
    currency: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime | str | None = None
    resolved_at: datetime | str | None = None


class AdvertisingAnomalyListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[AdvertisingAnomalyResponse]
    total: int


class AdvertisingConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    read_only: bool = True
    catalog_version: str
    service_version: str
    providers: list[AccountCapabilityResponse] = Field(default_factory=list)
    metric_keys: list[str] = Field(default_factory=list)
    objective_types: list[str] = Field(default_factory=list)
    account_statuses: list[str] = Field(default_factory=list)
    campaign_statuses: list[str] = Field(default_factory=list)
    pacing_statuses: list[str] = Field(default_factory=list)
    fatigue_statuses: list[str] = Field(default_factory=list)
    delivery_statuses: list[str] = Field(default_factory=list)
    freshness_statuses: list[str] = Field(default_factory=list)
    creative_formats: list[str] = Field(default_factory=list)
    limits: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class AdvertisingRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    recommendation_key: str
    category: str = "advertising"
    priority: str
    title: str
    reason: str | None = None
    confidence: float | str | None = None
    account_id: UUID | str | None = None
    campaign_id: UUID | str | None = None
    currency: str | None = None
    action_url: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = "open"
    created_at: datetime | str | None = None
    read_only: bool = True


class AdvertisingRecommendationListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[AdvertisingRecommendationResponse]
    total: int


# ---------------------------------------------------------------------------
# Decision Support / Simulation / Experiments (Phase 2 — advisory only)
# ---------------------------------------------------------------------------


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(..., max_length=40)
    entity_ids: list[UUID] = Field(..., min_length=2, max_length=8)
    metric_keys: list[str] | None = Field(default=None, max_length=64)


class ComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_type: str
    engine_version: str | None = None
    measurement_period: dict[str, Any] = Field(default_factory=dict)
    currency: str | None = None
    provider: str | None = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    sample_coverage: dict[str, Any] = Field(default_factory=dict)
    data_quality_warnings: list[str] = Field(default_factory=list)
    attribution_method: str | None = None
    read_only: bool = True
    kind: str = "OBSERVED"
    generated_at: datetime | str | None = None


class SimulationAllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID
    allocation_pct: float = Field(..., ge=0, le=1)


class CreateSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(..., min_length=3, max_length=3)
    total_budget_minor: int = Field(..., ge=0)
    allocations: list[SimulationAllocationItem] = Field(..., min_length=1, max_length=20)
    measurement_window_key: str = Field(default="lifetime", max_length=40)
    assumptions: dict[str, Any] | None = None


class SimulationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    currency: str
    total_budget_minor: int
    measurement_window_key: str | None = None
    engine_version: str | None = None
    input_fingerprint: str | None = None
    assumptions_json: dict[str, Any] | None = None
    summary_json: dict[str, Any] | None = None
    warnings_json: dict[str, Any] | None = None
    disclaimer: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    kind: str = "SIMULATED"
    read_only: bool = True
    created_at: datetime | str | None = None


class SimulationListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[SimulationResponse]
    total: int
    read_only: bool = True


class ExperimentVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_key: str = Field(..., min_length=1, max_length=40)
    label: str = Field(..., min_length=1, max_length=255)
    entity_type: str = Field(..., max_length=40)
    entity_id: UUID
    notes: str | None = None


class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    experiment_type: str = Field(..., max_length=80)
    hypothesis: str = Field(..., min_length=1, max_length=4000)
    primary_metric_key: str = Field(..., max_length=80)
    variants: list[ExperimentVariantInput] = Field(..., min_length=2, max_length=6)
    secondary_metric_keys: list[str] | None = None
    observation_start: date | None = None
    observation_end: date | None = None
    minimum_observations: int = Field(default=100, ge=1, le=1_000_000)
    minimum_spend_minor: int | None = Field(default=None, ge=0)
    minimum_conversions: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    attribution_method: str | None = Field(default=None, max_length=80)
    notes: str | None = None


class PatchExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    hypothesis: str | None = Field(default=None, min_length=1, max_length=4000)
    primary_metric_key: str | None = Field(default=None, max_length=80)
    secondary_metric_keys: list[str] | None = None
    observation_start: date | None = None
    observation_end: date | None = None
    minimum_observations: int | None = Field(default=None, ge=1, le=1_000_000)
    minimum_spend_minor: int | None = Field(default=None, ge=0)
    minimum_conversions: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    attribution_method: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    status: str | None = Field(default=None, max_length=40)


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    name: str
    experiment_type: str
    status: str
    hypothesis: str
    primary_metric_key: str
    secondary_metric_keys: dict[str, Any] | list[str] | None = None
    observation_start: date | str | None = None
    observation_end: date | str | None = None
    minimum_observations: int | None = None
    minimum_spend_minor: int | None = None
    minimum_conversions: int | None = None
    currency: str | None = None
    attribution_method: str | None = None
    notes: str | None = None
    result_status: str | None = None
    engine_version: str | None = None
    variants: list[dict[str, Any]] = Field(default_factory=list)
    observation_started_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    cancelled_at: datetime | str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    kind: str = "OBSERVATION_PLAN"
    read_only_toward_provider: bool = True
    launches_on_provider: bool = False
    read_only_toward_providers: bool | None = None
    provider_launch: bool | None = None


class ExperimentListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[ExperimentResponse]
    total: int
    read_only_toward_provider: bool = True


class ExperimentReviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    experiment_id: UUID | str | None = None
    result_status: str
    conclusion: str
    evidence: dict[str, Any] | list[Any] = Field(default_factory=dict)
    variants: list[dict[str, Any]] = Field(default_factory=list)
    comparison: dict[str, Any] | list[Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    kind: str = "DIRECTIONAL"
    claims_statistical_significance: bool = False
    review_id: UUID | str | None = None
    engine_version: str | None = None


class ChangePlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    title: str
    status: str
    source: str | None = None
    summary: str | None = None
    engine_version: str | None = None
    evidence_json: dict[str, Any] | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    executable: bool = False
    has_provider_payload: bool = False
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    reviewed_at: datetime | str | None = None
    dismissed_at: datetime | str | None = None


class ChangePlanListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[ChangePlanResponse]
    total: int
    executable: bool = False


class DiagnosticResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str | None = None
    classification: str | None = None
    kind: str | None = None
    engine_version: str | None = None
    observation: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    interpretation: str | None = None
    possible_consideration: str | None = None
    label: str | None = None
    formula: str | None = None
    disclaimer: str | None = None
    read_only: bool = True
    details: dict[str, Any] = Field(default_factory=dict)
