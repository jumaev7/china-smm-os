"""Conservative anomaly policy ``listening_anomaly_v1``."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from app.services.listening.analytics.contracts import (
    ANOMALY_METHOD_VERSION,
    AnalysisWindow,
    CoverageStatus,
    EmergingTopic,
    ListeningAnomaly,
    SubjectPerformance,
)
from app.services.listening.analytics.windows import relative_change

MIN_BASELINE_FOR_SPIKE = 3
VOLUME_SPIKE_PCT = 100.0
VOLUME_DROP_PCT = -60.0
SOURCE_CONCENTRATION_THRESHOLD = 0.9


def _severity_from_magnitude(abs_pct: float) -> str:
    if abs_pct >= 200:
        return "high"
    if abs_pct >= 100:
        return "medium"
    return "low"


def detect_anomalies(
    *,
    window: AnalysisWindow,
    coverage_status: CoverageStatus,
    current_count: int,
    previous_count: int | None,
    comparison_valid: bool,
    subject_rows: Sequence[SubjectPerformance],
    topics: Sequence[EmergingTopic],
    source_composition_current: dict[str, int],
    source_composition_previous: dict[str, int] | None,
    failed_ingestion_count: int,
    freshness_status: str,
    evidence_mention_ids: Sequence[str],
    now: datetime | None = None,
) -> list[ListeningAnomaly]:
    clock = now or datetime.now(timezone.utc)
    win = window.to_dict()
    out: list[ListeningAnomaly] = []
    evidence = list(evidence_mention_ids)[:5]

    # Data-quality anomalies first.
    if failed_ingestion_count > 0:
        out.append(
            ListeningAnomaly(
                code="ingestion_failures_in_window",
                anomaly_type="interrupted_observation_coverage",
                category="data_quality",
                affected_subject_id=None,
                affected_topic_id=None,
                affected_source_type=None,
                current_value=float(failed_ingestion_count),
                baseline_value=0.0,
                magnitude=float(failed_ingestion_count),
                severity="medium" if failed_ingestion_count < 3 else "high",
                evidence_mention_ids=[],
                detected_at=clock,
                analysis_window=win,
                method_version=ANOMALY_METHOD_VERSION,
                limitations=[
                    "This is a data-quality anomaly, not a market decline.",
                    "Failed ingestion must not be interpreted as observed silence.",
                ],
                explanation=(
                    f"Observed {failed_ingestion_count} failed ingestion run(s) affecting coverage."
                ),
            )
        )
    if freshness_status in {"stale", "unavailable"}:
        out.append(
            ListeningAnomaly(
                code="stale_or_unavailable_ingestion",
                anomaly_type="stale_observation_coverage",
                category="data_quality",
                affected_subject_id=None,
                affected_topic_id=None,
                affected_source_type=None,
                current_value=None,
                baseline_value=None,
                magnitude=None,
                severity="medium",
                evidence_mention_ids=[],
                detected_at=clock,
                analysis_window=win,
                method_version=ANOMALY_METHOD_VERSION,
                limitations=[
                    "Stale ingestion is a data-quality warning, not a market signal.",
                ],
                explanation=f"Ingestion freshness status is '{freshness_status}'.",
            )
        )

    # Suppress strong market anomalies on sparse/unavailable coverage.
    if coverage_status in {"unavailable", "insufficient"} or not comparison_valid:
        return out

    if previous_count is not None and previous_count >= MIN_BASELINE_FOR_SPIKE:
        pct, kind = relative_change(float(current_count), float(previous_count))
        if kind == "percentage" and pct is not None:
            if pct >= VOLUME_SPIKE_PCT:
                out.append(
                    ListeningAnomaly(
                        code="observed_volume_spike",
                        anomaly_type="observed_volume_spike",
                        category="market_signal",
                        affected_subject_id=None,
                        affected_topic_id=None,
                        affected_source_type=None,
                        current_value=float(current_count),
                        baseline_value=float(previous_count),
                        magnitude=round(pct, 4),
                        severity=_severity_from_magnitude(abs(pct)),  # type: ignore[arg-type]
                        evidence_mention_ids=evidence,
                        detected_at=clock,
                        analysis_window=win,
                        method_version=ANOMALY_METHOD_VERSION,
                        limitations=[
                            "Volume change is descriptive of eligible observed mentions only.",
                            "Not a forecast and not sentiment.",
                        ],
                        explanation=(
                            f"Observed mentions increased from {previous_count} to {current_count} "
                            f"({round(pct, 1)}%)."
                        ),
                    )
                )
            elif pct <= VOLUME_DROP_PCT:
                out.append(
                    ListeningAnomaly(
                        code="observed_volume_drop",
                        anomaly_type="observed_volume_drop",
                        category="market_signal",
                        affected_subject_id=None,
                        affected_topic_id=None,
                        affected_source_type=None,
                        current_value=float(current_count),
                        baseline_value=float(previous_count),
                        magnitude=round(pct, 4),
                        severity=_severity_from_magnitude(abs(pct)),  # type: ignore[arg-type]
                        evidence_mention_ids=evidence,
                        detected_at=clock,
                        analysis_window=win,
                        method_version=ANOMALY_METHOD_VERSION,
                        limitations=[
                            "A drop in observed mentions may reflect coverage gaps, not market decline.",
                        ],
                        explanation=(
                            f"Observed mentions decreased from {previous_count} to {current_count} "
                            f"({round(pct, 1)}%)."
                        ),
                    )
                )
    elif previous_count == 0 and current_count >= MIN_BASELINE_FOR_SPIKE:
        out.append(
            ListeningAnomaly(
                code="new_subject_activity_volume",
                anomaly_type="new_activity",
                category="market_signal",
                affected_subject_id=None,
                affected_topic_id=None,
                affected_source_type=None,
                current_value=float(current_count),
                baseline_value=0.0,
                magnitude=None,
                severity="medium",
                evidence_mention_ids=evidence,
                detected_at=clock,
                analysis_window=win,
                method_version=ANOMALY_METHOD_VERSION,
                limitations=["Baseline was zero; change_kind is new_activity, not infinite growth."],
                explanation=(
                    f"Observed mentions rose from a zero baseline to {current_count} (new_activity)."
                ),
            )
        )

    for row in subject_rows:
        if (
            row.change_kind == "new_activity"
            and row.observed_mention_count >= MIN_BASELINE_FOR_SPIKE
            and row.previous_comparable_count == 0
        ):
            out.append(
                ListeningAnomaly(
                    code=f"new_subject_activity:{row.subject_id}",
                    anomaly_type="new_subject_activity",
                    category="market_signal",
                    affected_subject_id=row.subject_id,
                    affected_topic_id=None,
                    affected_source_type=None,
                    current_value=float(row.observed_mention_count),
                    baseline_value=0.0,
                    magnitude=None,
                    severity="medium",
                    evidence_mention_ids=list(row.evidence_mention_ids)[:5],
                    detected_at=clock,
                    analysis_window=win,
                    method_version=ANOMALY_METHOD_VERSION,
                    limitations=["new_activity — percentage growth is not defined from a zero baseline."],
                    explanation=(
                        f"Subject '{row.canonical_name}' moved from 0 to "
                        f"{row.observed_mention_count} eligible observed mentions."
                    ),
                )
            )

    for topic in topics[:5]:
        out.append(
            ListeningAnomaly(
                code=f"emerging_topic:{topic.topic_id}",
                anomaly_type="emerging_topic",
                category="market_signal",
                affected_subject_id=topic.subject_ids[0] if topic.subject_ids else None,
                affected_topic_id=topic.topic_id,
                affected_source_type=None,
                current_value=float(topic.current_count),
                baseline_value=float(topic.baseline_count),
                magnitude=topic.velocity,
                severity="low" if topic.confidence == "low" else "medium",
                evidence_mention_ids=list(topic.representative_mention_ids)[:5],
                detected_at=clock,
                analysis_window=win,
                method_version=ANOMALY_METHOD_VERSION,
                limitations=list(topic.limitations),
                explanation=topic.detection_reason,
            )
        )

    total_cur = sum(source_composition_current.values()) or 0
    if total_cur >= 5:
        dominant_src, dominant_n = max(source_composition_current.items(), key=lambda x: x[1])
        share = dominant_n / total_cur
        prev_share = None
        if source_composition_previous:
            total_prev = sum(source_composition_previous.values()) or 0
            if total_prev > 0:
                prev_share = source_composition_previous.get(dominant_src, 0) / total_prev
        if share >= SOURCE_CONCENTRATION_THRESHOLD and (prev_share is None or share - (prev_share or 0) >= 0.2):
            out.append(
                ListeningAnomaly(
                    code="source_concentration_shift",
                    anomaly_type="source_concentration_shift",
                    category="data_quality",
                    affected_subject_id=None,
                    affected_topic_id=None,
                    affected_source_type=dominant_src,
                    current_value=round(share * 100, 2),
                    baseline_value=None if prev_share is None else round(prev_share * 100, 2),
                    magnitude=None if prev_share is None else round((share - prev_share) * 100, 2),
                    severity="low",
                    evidence_mention_ids=[],
                    detected_at=clock,
                    analysis_window=win,
                    method_version=ANOMALY_METHOD_VERSION,
                    limitations=[
                        "Source concentration is a data-quality concern for interpretation, "
                        "not an independent market preference signal.",
                    ],
                    explanation=(
                        f"Source '{dominant_src}' represents {round(share * 100, 1)}% of eligible "
                        "observed mentions in the current window."
                    ),
                )
            )

    # Deterministic severity clamp already applied via helper; stable sort.
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    out.sort(key=lambda a: (severity_rank.get(a.severity, 9), a.code))
    return out
