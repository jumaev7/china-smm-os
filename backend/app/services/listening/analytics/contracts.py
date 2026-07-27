"""Versioned analytical contracts for Listening Phase 2.

LLM output is never the authoritative analytical source. All metrics are
deterministic functions of eligible Phase 1 observations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

COVERAGE_POLICY_VERSION = "listening_coverage_v1"
WINDOW_METHOD_VERSION = "listening_windows_v1"
SOV_METHOD_VERSION = "listening_sov_v1"
TOPIC_METHOD_VERSION = "listening_topics_v1"
ANOMALY_METHOD_VERSION = "listening_anomaly_v1"
INSIGHT_METHOD_VERSION = "listening_insights_v1"
ELIGIBILITY_POLICY_VERSION = "listening_eligibility_v1"
MULTI_MATCH_POLICY = "fractional_attribution_v1"

CoverageStatus = Literal["sufficient", "partial", "insufficient", "unavailable"]
Granularity = Literal["hour", "day", "week"]
ChangeKind = Literal["percentage", "new_activity", "unavailable", "zero_baseline_zero_current"]
AnomalyCategory = Literal["market_signal", "data_quality"]
InsightReviewState = Literal[
    "unreviewed",
    "acknowledged",
    "dismissed",
    "monitoring",
    "resolved",
]
ReviewPolicy = Literal[
    "default_exclude_irrelevant",
    "include_all",
    "relevant_only",
]

INSIGHT_REVIEW_STATES = frozenset({
    "unreviewed",
    "acknowledged",
    "dismissed",
    "monitoring",
    "resolved",
})

PRODUCTION_ORIGINS = frozenset({"manual_import", "live_provider", "webhook"})
FIXTURE_ORIGINS = frozenset({"fixture"})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _uuid_str(value: UUID | str | None) -> str | None:
    if value is None:
        return None
    return str(value)


@dataclass(frozen=True)
class AnalysisWindow:
    start: datetime
    end: datetime
    timezone: str
    granularity: Granularity
    window_key: str
    comparison_start: datetime | None = None
    comparison_end: datetime | None = None
    comparison_valid: bool = False
    completeness_status: CoverageStatus = "unavailable"
    freshness_watermark: datetime | None = None
    method_version: str = WINDOW_METHOD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": _iso(self.start),
            "end": _iso(self.end),
            "timezone": self.timezone,
            "granularity": self.granularity,
            "window_key": self.window_key,
            "comparison_start": _iso(self.comparison_start),
            "comparison_end": _iso(self.comparison_end),
            "comparison_valid": self.comparison_valid,
            "completeness_status": self.completeness_status,
            "freshness_watermark": _iso(self.freshness_watermark),
            "method_version": self.method_version,
        }


@dataclass(frozen=True)
class ListeningCoverageAssessment:
    status: CoverageStatus
    observed_source_count: int
    active_project_count: int
    active_query_count: int
    mention_count: int
    eligible_mention_count: int
    days_with_observations: int
    expected_interval_coverage: float | None
    latest_successful_ingestion: datetime | None
    freshness_status: str
    freshness_watermark: datetime | None
    limitations: list[str] = field(default_factory=list)
    comparable_subject_ids: list[str] = field(default_factory=list)
    origin_composition: dict[str, int] = field(default_factory=dict)
    unreviewed_proportion: float | None = None
    missing_timestamp_count: int = 0
    failed_ingestion_count: int = 0
    partial_ingestion_count: int = 0
    source_imbalance: dict[str, Any] = field(default_factory=dict)
    cadence_completeness: Literal["unknown", "partial", "complete"] = "unknown"
    policy_version: str = COVERAGE_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "observed_source_count": self.observed_source_count,
            "active_project_count": self.active_project_count,
            "active_query_count": self.active_query_count,
            "mention_count": self.mention_count,
            "eligible_mention_count": self.eligible_mention_count,
            "days_with_observations": self.days_with_observations,
            "expected_interval_coverage": self.expected_interval_coverage,
            "latest_successful_ingestion": _iso(self.latest_successful_ingestion),
            "freshness_status": self.freshness_status,
            "freshness_watermark": _iso(self.freshness_watermark),
            "limitations": list(self.limitations),
            "comparable_subject_ids": list(self.comparable_subject_ids),
            "origin_composition": dict(self.origin_composition),
            "unreviewed_proportion": self.unreviewed_proportion,
            "missing_timestamp_count": self.missing_timestamp_count,
            "failed_ingestion_count": self.failed_ingestion_count,
            "partial_ingestion_count": self.partial_ingestion_count,
            "source_imbalance": dict(self.source_imbalance),
            "cadence_completeness": self.cadence_completeness,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class MentionTimeSeriesBucket:
    bucket_start: datetime
    bucket_end: datetime
    total_observed_mentions: int
    counts_by_subject: dict[str, float]
    counts_by_source: dict[str, int]
    counts_by_content_type: dict[str, int]
    unique_mention_count: int
    data_quality_flags: list[str] = field(default_factory=list)
    observed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket_start": _iso(self.bucket_start),
            "bucket_end": _iso(self.bucket_end),
            "total_observed_mentions": self.total_observed_mentions,
            "counts_by_subject": dict(self.counts_by_subject),
            "counts_by_source": dict(self.counts_by_source),
            "counts_by_content_type": dict(self.counts_by_content_type),
            "unique_mention_count": self.unique_mention_count,
            "data_quality_flags": list(self.data_quality_flags),
            "observed": self.observed,
        }


@dataclass(frozen=True)
class SubjectPerformance:
    subject_id: str
    subject_type: str
    canonical_name: str
    observed_mention_count: float
    previous_comparable_count: float | None
    absolute_change: float | None
    percentage_change: float | None
    change_kind: ChangeKind
    observed_share: float | None
    rank: int | None
    previous_rank: int | None
    evidence_mention_ids: list[str] = field(default_factory=list)
    coverage_status: CoverageStatus = "unavailable"
    confidence_status: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "canonical_name": self.canonical_name,
            "observed_mention_count": self.observed_mention_count,
            "previous_comparable_count": self.previous_comparable_count,
            "absolute_change": self.absolute_change,
            "percentage_change": self.percentage_change,
            "change_kind": self.change_kind,
            "observed_share": self.observed_share,
            "rank": self.rank,
            "previous_rank": self.previous_rank,
            "evidence_mention_ids": list(self.evidence_mention_ids),
            "coverage_status": self.coverage_status,
            "confidence_status": self.confidence_status,
            "sov_method_version": SOV_METHOD_VERSION,
            "multi_match_policy": MULTI_MATCH_POLICY,
        }


@dataclass(frozen=True)
class EmergingTopic:
    topic_id: str
    label: str
    matched_terms: list[str]
    query_ids: list[str]
    subject_ids: list[str]
    current_count: int
    baseline_count: int
    velocity: float | None
    change_kind: ChangeKind
    first_observed_at: datetime | None
    representative_mention_ids: list[str]
    confidence: str
    coverage_status: CoverageStatus
    detection_method: str = TOPIC_METHOD_VERSION
    detection_reason: str = ""
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "label": self.label,
            "matched_terms": list(self.matched_terms),
            "query_ids": list(self.query_ids),
            "subject_ids": list(self.subject_ids),
            "current_count": self.current_count,
            "baseline_count": self.baseline_count,
            "velocity": self.velocity,
            "change_kind": self.change_kind,
            "first_observed_at": _iso(self.first_observed_at),
            "representative_mention_ids": list(self.representative_mention_ids),
            "confidence": self.confidence,
            "coverage_status": self.coverage_status,
            "detection_method": self.detection_method,
            "detection_reason": self.detection_reason,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class ListeningAnomaly:
    code: str
    anomaly_type: str
    category: AnomalyCategory
    affected_subject_id: str | None
    affected_topic_id: str | None
    affected_source_type: str | None
    current_value: float | None
    baseline_value: float | None
    magnitude: float | None
    severity: Literal["low", "medium", "high", "critical"]
    evidence_mention_ids: list[str]
    detected_at: datetime
    analysis_window: dict[str, Any]
    method_version: str = ANOMALY_METHOD_VERSION
    limitations: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "anomaly_type": self.anomaly_type,
            "category": self.category,
            "affected_subject_id": self.affected_subject_id,
            "affected_topic_id": self.affected_topic_id,
            "affected_source_type": self.affected_source_type,
            "current_value": self.current_value,
            "baseline_value": self.baseline_value,
            "magnitude": self.magnitude,
            "severity": self.severity,
            "evidence_mention_ids": list(self.evidence_mention_ids),
            "detected_at": _iso(self.detected_at),
            "analysis_window": dict(self.analysis_window),
            "method_version": self.method_version,
            "limitations": list(self.limitations),
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class MarketInsight:
    insight_key: str
    code: str
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    priority: int
    title: str
    explanation: str
    observed_facts: list[str]
    evidence_mention_ids: list[str]
    affected_subject_ids: list[str]
    window: dict[str, Any]
    confidence: str
    coverage_status: CoverageStatus
    methodology_version: str = INSIGHT_METHOD_VERSION
    analyst_review_state: InsightReviewState = "unreviewed"
    generated_at: datetime | None = None
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_key": self.insight_key,
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "priority": self.priority,
            "title": self.title,
            "explanation": self.explanation,
            "observed_facts": list(self.observed_facts),
            "evidence_mention_ids": list(self.evidence_mention_ids),
            "affected_subject_ids": list(self.affected_subject_ids),
            "window": dict(self.window),
            "confidence": self.confidence,
            "coverage_status": self.coverage_status,
            "methodology_version": self.methodology_version,
            "analyst_review_state": self.analyst_review_state,
            "generated_at": _iso(self.generated_at),
            "limitations": list(self.limitations),
        }


def dataclass_to_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return asdict(obj)
