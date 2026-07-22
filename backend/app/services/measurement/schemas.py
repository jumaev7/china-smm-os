"""Internal (non-ORM, non-HTTP) dataclasses for the measurement services.

Mirrors ``app.services.campaign_planner.schemas``: these are the typed
contracts passed between provider adapters, the ingestion pipeline, and the
aggregation/attribution/performance engines. None of these are exposed
directly over HTTP — see ``app.schemas.measurement`` for the API surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

MEASUREMENT_SERVICE_VERSION = "1.0.0"

# Capability status vocabulary reported by provider adapters.
CAPABILITY_STATUSES = frozenset({"full", "mock_only", "limited", "unsupported"})

# Fetch/response status vocabulary for a single publication's provider fetch.
FETCH_STATUSES = frozenset({"ok", "unsupported", "unavailable", "error"})


# ---------------------------------------------------------------------------
# Metric catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricDefinition:
    """One entry in the versioned metric catalog."""

    key: str
    value_type: str
    aggregation_type: str
    higher_is_better: bool
    cross_platform_comparable: bool
    provider_mappings: dict[str, str | None]
    description_key: str
    semantics_version: str = "1.0.0"
    unit: str | None = None
    derived_from: tuple[str, ...] = field(default_factory=tuple)
    comparability_caveat: str | None = None


# ---------------------------------------------------------------------------
# Provider adapter contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterCapabilities:
    """What a given adapter can do for a given platform + account status."""

    platform: str
    capability_status: str  # one of CAPABILITY_STATUSES
    supports_post_level_metrics: bool
    supported_metric_keys: frozenset[str]
    unsupported_reason: str | None = None
    notes: str | None = None


@dataclass
class PublicationMetricResult:
    """Raw provider-native metrics for a single publication."""

    provider_publication_id: str
    status: str  # one of FETCH_STATUSES
    provider_metrics: dict[str, Decimal] = field(default_factory=dict)
    provider_data_timestamp: datetime | None = None
    raw_summary: dict[str, Any] = field(default_factory=dict)
    message: str | None = None


@dataclass
class MetricFetchRequest:
    """Batch fetch request for one account across many publications."""

    tenant_id: UUID
    platform: str
    account_status: str
    provider_account_id: str | None
    publication_ids: list[str]
    since: datetime | None = None
    requested_metrics: list[str] | None = None


@dataclass
class MetricFetchResponse:
    results: dict[str, PublicationMetricResult] = field(default_factory=dict)
    provider_request_count: int = 1


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
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class AggregateResult:
    window_key: str
    metric_key: str
    metric_value: Decimal | None
    calculation_method: str
    freshness_status: str
    confidence: Decimal
    source_snapshot_ids: list[UUID] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


@dataclass
class AttributionResult:
    entity_type: str
    entity_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    attribution_method: str
    confidence: Decimal
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "active"


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


@dataclass
class FreshnessResult:
    status: str
    age_seconds: float | None
    last_observation_at: datetime | None
    reason: str | None = None


# ---------------------------------------------------------------------------
# KPI progress
# ---------------------------------------------------------------------------


@dataclass
class KpiProgressResult:
    kpi_id: UUID
    campaign_id: UUID
    metric_key: str
    target_value: Decimal | None
    current_value: Decimal | None
    comparator: str
    status: str  # not_measurable/no_data/in_progress/target_reached/target_exceeded/data_stale
    progress_ratio: Decimal | None
    confidence: Decimal
    freshness_status: str
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Baselines / performance
# ---------------------------------------------------------------------------


@dataclass
class BaselineResult:
    metric_key: str
    platform: str | None
    sample_size: int
    median: Decimal | None
    mean: Decimal | None
    p75: Decimal | None
    lookback_days: int
    sufficient: bool


@dataclass
class PerformanceClassification:
    entity_type: str
    entity_id: str
    metric_key: str
    classification: str  # above_baseline | at_baseline | below_baseline | insufficient_data
    value: Decimal | None
    baseline: BaselineResult | None
    delta_ratio: Decimal | None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecommendationEvidence:
    recommendation_key: str
    title: str
    reason: str
    evidence: dict[str, Any]
    confidence: Decimal
    metric_keys: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


__all__ = [
    "MEASUREMENT_SERVICE_VERSION",
    "CAPABILITY_STATUSES",
    "FETCH_STATUSES",
    "MetricDefinition",
    "AdapterCapabilities",
    "PublicationMetricResult",
    "MetricFetchRequest",
    "MetricFetchResponse",
    "NormalizedMetricValue",
    "AggregateResult",
    "AttributionResult",
    "FreshnessResult",
    "KpiProgressResult",
    "BaselineResult",
    "PerformanceClassification",
    "RecommendationEvidence",
]
