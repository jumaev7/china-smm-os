"""Internal (non-ORM, non-HTTP) dataclasses for the Advertising Intelligence services.

Mirrors ``app.services.measurement.schemas``: these are the typed contracts
passed between read-only provider adapters, the import/ingestion pipelines, and
the aggregation/pacing/diagnostics/attribution engines.

None of these are exposed directly over HTTP. Money is always represented as
integer *minor units* plus an explicit currency string; magnitudes that are not
money use ``Decimal``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

ADVERTISING_SERVICE_VERSION = "1.0.0"

# Capability status vocabulary reported by provider adapters.
CAPABILITY_STATUSES = frozenset({"full", "mock_only", "limited", "unsupported"})

# Fetch/response status vocabulary for a single provider fetch.
FETCH_STATUSES = frozenset({"ok", "unsupported", "unavailable", "permission_blocked", "error"})


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Money:
    """Money as integer minor units + explicit ISO-4217 currency string."""

    minor_units: int
    currency: str


# ---------------------------------------------------------------------------
# Metric catalog definition (consumed by ``metric_catalog``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdMetricDefinition:
    """Versioned definition of a single normalized advertising metric.

    Field set is dictated by ``metric_catalog``: raw metrics carry
    ``provider_mappings`` while derived metrics additionally carry a named
    ``formula`` plus its contributor metric keys.
    """

    metric_key: str
    value_type: str  # one of VALUE_TYPES
    aggregation_type: str  # cumulative | interval | point_in_time | derived
    currency_behavior: str  # currency | currency_ratio | currency_free
    provider_mappings: dict[str, str | None] = field(default_factory=dict)
    description_key: str = ""
    cross_provider_comparable: bool = False
    direction: str = "neutral"  # higher_is_better | lower_is_better | neutral
    unit: str | None = None
    comparability_caveat: str | None = None
    formula: str | None = None
    numerator_metric: str | None = None
    denominator_metric: str | None = None


# ---------------------------------------------------------------------------
# Provider adapter capability description
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdvertisingCapabilities:
    """What a given adapter can do for a given provider + connection status."""

    provider: str
    capability_status: str  # one of CAPABILITY_STATUSES
    supports_structure_import: bool
    supports_insights: bool
    supports_conversions: bool
    supports_breakdowns: bool
    supported_metric_keys: frozenset[str] = frozenset()
    supported_breakdowns: frozenset[str] = frozenset()
    unsupported_reason: str | None = None
    notes: str | None = None


@dataclass
class ProviderHealth:
    provider: str
    status: str  # ok | unavailable | permission_blocked | error
    connection_status: str
    capability_status: str
    checked_at: datetime
    message: str | None = None


# ---------------------------------------------------------------------------
# Structural import (accounts / campaigns / ad groups / ads / creatives)
# ---------------------------------------------------------------------------


@dataclass
class ProviderAccount:
    provider_account_id: str
    name: str | None = None
    currency: str | None = None
    timezone: str | None = None
    account_status: str = "unknown"
    provider_business_id: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    permission_summary: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderCampaign:
    provider_campaign_id: str
    name: str | None = None
    objective: str | None = None
    buying_type: str | None = None
    config_status: str = "unknown"
    effective_status: str = "unknown"
    bid_strategy: str | None = None
    daily_budget: Money | None = None
    lifetime_budget: Money | None = None
    spend_cap: Money | None = None
    special_ad_categories: list[str] = field(default_factory=list)
    attribution_spec: dict[str, Any] = field(default_factory=dict)
    start_time: datetime | None = None
    stop_time: datetime | None = None
    created_time: datetime | None = None
    updated_time: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderAdGroup:
    provider_ad_group_id: str
    provider_campaign_id: str | None = None
    name: str | None = None
    config_status: str = "unknown"
    effective_status: str = "unknown"
    optimization_goal: str | None = None
    billing_event: str | None = None
    bid_amount: Money | None = None
    daily_budget: Money | None = None
    lifetime_budget: Money | None = None
    targeting_summary: dict[str, Any] = field(default_factory=dict)
    start_time: datetime | None = None
    stop_time: datetime | None = None
    created_time: datetime | None = None
    updated_time: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderAd:
    provider_ad_id: str
    provider_ad_group_id: str | None = None
    provider_creative_id: str | None = None
    name: str | None = None
    config_status: str = "unknown"
    effective_status: str = "unknown"
    tracking_specs: dict[str, Any] = field(default_factory=dict)
    created_time: datetime | None = None
    updated_time: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderCreative:
    provider_creative_id: str
    name: str | None = None
    title: str | None = None
    body: str | None = None
    call_to_action_type: str | None = None
    object_type: str | None = None
    thumbnail_url: str | None = None
    permalink_url: str | None = None
    object_story_id: str | None = None
    asset_summary: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StructureFetchRequest:
    tenant_id: UUID
    provider: str
    connection_status: str
    provider_account_id: str
    scope: str = "full"
    cursor: str | None = None
    limit: int = 500


@dataclass
class StructureFetchResponse:
    account: ProviderAccount | None = None
    campaigns: list[ProviderCampaign] = field(default_factory=list)
    ad_groups: list[ProviderAdGroup] = field(default_factory=list)
    ads: list[ProviderAd] = field(default_factory=list)
    creatives: list[ProviderCreative] = field(default_factory=list)
    next_cursor: str | None = None
    provider_request_count: int = 1
    status: str = "ok"  # one of FETCH_STATUSES
    message: str | None = None


# ---------------------------------------------------------------------------
# Insights / metrics
# ---------------------------------------------------------------------------


@dataclass
class ProviderMetric:
    """A single provider-native metric value.

    ``currency`` is set only for monetary metrics (``value_type ==
    'currency_minor'``), where ``value`` is expressed in minor units.
    """

    provider_metric_key: str
    value: Decimal
    value_type: str = "count"
    currency: str | None = None


@dataclass
class ProviderConversion:
    action_type: str
    value: Decimal
    action_destination: str | None = None
    attribution_setting: str | None = None
    conversion_window: str | None = None
    value_type: str = "count"
    currency: str | None = None


@dataclass
class EntityInsightResult:
    """Raw provider-native insights for a single entity at one level."""

    provider_entity_id: str
    entity_type: str
    level: str
    status: str  # one of FETCH_STATUSES
    metrics: list[ProviderMetric] = field(default_factory=list)
    conversions: list[ProviderConversion] = field(default_factory=list)
    currency: str | None = None
    date_start: str | None = None
    date_stop: str | None = None
    provider_data_timestamp: datetime | None = None
    raw_summary: dict[str, Any] = field(default_factory=dict)
    message: str | None = None


@dataclass
class InsightsFetchRequest:
    tenant_id: UUID
    provider: str
    connection_status: str
    provider_account_id: str
    level: str
    date_start: str
    date_stop: str
    provider_entity_ids: list[str] = field(default_factory=list)
    breakdowns: list[str] = field(default_factory=list)
    requested_metrics: list[str] | None = None
    cursor: str | None = None


@dataclass
class InsightsFetchResponse:
    results: list[EntityInsightResult] = field(default_factory=list)
    next_cursor: str | None = None
    provider_request_count: int = 1
    status: str = "ok"
    message: str | None = None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@dataclass
class NormalizedMetricValue:
    metric_key: str
    provider_metric_key: str | None
    value: Decimal
    value_type: str
    aggregation_type: str
    normalization_status: str  # normalized | provider_native | derived | unmapped
    currency: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class AggregateResult:
    entity_type: str
    entity_id: UUID
    window_key: str
    metric_key: str
    metric_value: Decimal | None
    value_type: str
    calculation_method: str
    freshness_status: str
    confidence: Decimal
    currency: str | None = None
    source_snapshot_ids: list[UUID] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None


# ---------------------------------------------------------------------------
# Pacing / budget
# ---------------------------------------------------------------------------


@dataclass
class PacingResult:
    entity_type: str
    entity_id: UUID
    budget_type: str
    budget: Money | None
    spend: Money | None
    remaining: Money | None
    utilization_ratio: Decimal | None
    pacing_status: str  # on_pace | underspending | overspending | budget_exhausted | paused | ended | not_applicable | insufficient_data
    observed_at: datetime | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


@dataclass
class FreshnessResult:
    status: str  # fresh | aging | stale | unavailable | unsupported
    age_seconds: float | None
    last_observation_at: datetime | None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Diagnostics / anomalies
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticFinding:
    anomaly_key: str
    severity: str  # info | warning | error | critical
    entity_type: str | None
    entity_id: UUID | None
    metric_key: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeliveryDiagnostics:
    checked_entities: int
    findings: list[DiagnosticFinding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Attribution / linking
# ---------------------------------------------------------------------------


@dataclass
class LinkResult:
    creative_id: UUID | None
    ad_campaign_id: UUID | None
    target_type: str
    target_id: str
    link_method: str
    confidence: Decimal
    status: str = "active"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttributionSummary:
    """Explicit, deterministic attribution — never probabilistic MTA."""

    entity_type: str
    entity_id: UUID
    linked_target_type: str | None
    linked_target_id: str | None
    attribution_method: str
    confidence: Decimal
    metric_keys: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ADVERTISING_SERVICE_VERSION",
    "CAPABILITY_STATUSES",
    "FETCH_STATUSES",
    "Money",
    "AdMetricDefinition",
    "AdvertisingCapabilities",
    "ProviderHealth",
    "ProviderAccount",
    "ProviderCampaign",
    "ProviderAdGroup",
    "ProviderAd",
    "ProviderCreative",
    "StructureFetchRequest",
    "StructureFetchResponse",
    "ProviderMetric",
    "ProviderConversion",
    "EntityInsightResult",
    "InsightsFetchRequest",
    "InsightsFetchResponse",
    "NormalizedMetricValue",
    "AggregateResult",
    "PacingResult",
    "FreshnessResult",
    "DiagnosticFinding",
    "DeliveryDiagnostics",
    "LinkResult",
    "AttributionSummary",
]
