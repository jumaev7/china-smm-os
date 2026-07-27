"""Coverage assessment policy ``listening_coverage_v1``.

Coverage is first-class. Strong comparisons are suppressed when coverage is
insufficient/unavailable. Manual-import cadence completeness is ``unknown``
unless an expected interval is explicitly defined (Phase 2 does not invent one).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from app.services.listening.analytics.contracts import (
    COVERAGE_POLICY_VERSION,
    CoverageStatus,
    ListeningCoverageAssessment,
)
from app.services.listening.limits import AGING_MAX_AGE_SECONDS, FRESH_MAX_AGE_SECONDS

# Deterministic thresholds (observations / distinct days).
MIN_MENTIONS_SUFFICIENT = 10
MIN_DAYS_SUFFICIENT = 3
MIN_MENTIONS_PARTIAL = 3
MIN_DAYS_PARTIAL = 1
MIN_COMPARABLE_SUBJECTS = 2


def _freshness_status(watermark: datetime | None, *, now: datetime) -> str:
    if watermark is None:
        return "unavailable"
    age = (now - watermark).total_seconds()
    if age <= FRESH_MAX_AGE_SECONDS:
        return "fresh"
    if age <= AGING_MAX_AGE_SECONDS:
        return "aging"
    return "stale"


def assess_coverage(
    *,
    eligible_mentions: Sequence[Any],
    all_scoped_mentions: Sequence[Any] | None = None,
    active_project_count: int,
    active_query_count: int,
    comparable_subject_ids: Sequence[str],
    latest_successful_ingestion: datetime | None,
    failed_ingestion_count: int = 0,
    partial_ingestion_count: int = 0,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    include_fixture: bool = False,
    now: datetime | None = None,
) -> ListeningCoverageAssessment:
    clock = now or datetime.now(timezone.utc)
    scoped = list(all_scoped_mentions if all_scoped_mentions is not None else eligible_mentions)
    eligible = list(eligible_mentions)

    origin_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    missing_ts = 0
    day_keys: set[str] = set()

    for m in eligible:
        origin = getattr(m, "observation_origin", None) or getattr(m, "source_type", None) or "unknown"
        origin_counts[str(origin)] += 1
        source_counts[str(getattr(m, "source_type", None) or "unknown")] += 1
        review_counts[str(getattr(m, "review_state", None) or "unreviewed")] += 1
        published = getattr(m, "published_at", None)
        if published is None:
            missing_ts += 1
        else:
            day_keys.add(published.astimezone(timezone.utc).date().isoformat())

    # Also count missing timestamps among scoped production mentions for quality.
    for m in scoped:
        if getattr(m, "published_at", None) is None:
            # Avoid double-counting eligible missing already tallied above when lists equal.
            pass

    unreviewed = review_counts.get("unreviewed", 0)
    unreviewed_prop = (unreviewed / len(eligible)) if eligible else None

    days = len(day_keys)
    eligible_n = len(eligible)
    comparable = [str(x) for x in comparable_subject_ids]

    limitations: list[str] = [
        "Coverage reflects configured observed sources only — not whole-market coverage.",
        "Live Facebook coverage is limited to authorized Pages via owned-content comments "
        "and tagged mentions — not global keyword listening, not competitor-wide Facebook, "
        "and not Instagram in this phase.",
        "Manual-import cadence completeness is unknown; expected interval coverage is not invented.",
        "Findings are descriptive decision support, not forecasts.",
    ]
    if not include_fixture:
        limitations.append("Fixture observations are excluded from production intelligence.")
    if failed_ingestion_count:
        limitations.append(
            f"{failed_ingestion_count} failed ingestion run(s) reduce coverage confidence; "
            "technical failure must not be read as market silence."
        )
    if partial_ingestion_count:
        limitations.append(
            f"{partial_ingestion_count} partial ingestion run(s) indicate incomplete observation intake."
        )
    if missing_ts:
        limitations.append(
            f"{missing_ts} eligible mention(s) lack published_at and are excluded from time-series."
        )
    if unreviewed_prop is not None and unreviewed_prop > 0:
        limitations.append(
            f"{round(unreviewed_prop * 100, 1)}% of eligible mentions remain unreviewed."
        )
    if len(comparable) < MIN_COMPARABLE_SUBJECTS:
        limitations.append(
            "Fewer than two comparable subjects are configured; share-of-voice comparisons are limited."
        )
    if origin_counts.get("manual_import") and not origin_counts.get("live_provider"):
        limitations.append(
            "Observations originate from manual import; live provider coverage is unavailable."
        )

    # Expected interval coverage is intentionally unknown for manual imports.
    expected_interval_coverage = None
    cadence_completeness: Any = "unknown"

    watermark = latest_successful_ingestion
    for m in eligible:
        pub = getattr(m, "published_at", None)
        obs = getattr(m, "observed_at", None)
        for candidate in (pub, obs):
            if candidate is not None and (watermark is None or candidate > watermark):
                watermark = candidate

    freshness = _freshness_status(latest_successful_ingestion or watermark, now=clock)

    # Dominant source imbalance flag.
    total_sources = sum(source_counts.values()) or 1
    dominant_share = max(source_counts.values()) / total_sources if source_counts else 0.0
    source_imbalance = {
        "counts": dict(source_counts),
        "dominant_share": round(dominant_share, 4),
        "imbalanced": dominant_share >= 0.9 and total_sources >= 5,
    }
    if source_imbalance["imbalanced"]:
        limitations.append(
            "Source composition is highly concentrated; treat volume changes cautiously."
        )

    status: CoverageStatus
    if eligible_n == 0 and (failed_ingestion_count > 0 or latest_successful_ingestion is None):
        status = "unavailable"
        limitations.append("No eligible observations and ingestion freshness is unavailable.")
    elif eligible_n == 0:
        # Healthy empty: ingestion may have succeeded with zero matches.
        status = "insufficient"
        limitations.append(
            "Zero eligible mentions in the window. If ingestion is healthy, this is observed silence "
            "within configured sources — not proof of market absence."
        )
    elif (
        eligible_n >= MIN_MENTIONS_SUFFICIENT
        and days >= MIN_DAYS_SUFFICIENT
        and failed_ingestion_count == 0
        and freshness in {"fresh", "aging"}
    ):
        status = "sufficient"
    elif eligible_n >= MIN_MENTIONS_PARTIAL and days >= MIN_DAYS_PARTIAL:
        status = "partial"
    else:
        status = "insufficient"

    if window_start and window_end and (window_end - window_start).total_seconds() <= 0:
        status = "unavailable"

    return ListeningCoverageAssessment(
        status=status,
        observed_source_count=len(source_counts),
        active_project_count=active_project_count,
        active_query_count=active_query_count,
        mention_count=len(scoped),
        eligible_mention_count=eligible_n,
        days_with_observations=days,
        expected_interval_coverage=expected_interval_coverage,
        latest_successful_ingestion=latest_successful_ingestion,
        freshness_status=freshness,
        freshness_watermark=watermark,
        limitations=limitations,
        comparable_subject_ids=comparable,
        origin_composition=dict(origin_counts),
        unreviewed_proportion=round(unreviewed_prop, 4) if unreviewed_prop is not None else None,
        missing_timestamp_count=missing_ts,
        failed_ingestion_count=failed_ingestion_count,
        partial_ingestion_count=partial_ingestion_count,
        source_imbalance=source_imbalance,
        cadence_completeness=cadence_completeness,
        policy_version=COVERAGE_POLICY_VERSION,
    )


def comparison_allowed(coverage: ListeningCoverageAssessment) -> bool:
    return coverage.status in {"sufficient", "partial"} and coverage.eligible_mention_count > 0


def strong_insights_allowed(coverage: ListeningCoverageAssessment) -> bool:
    return coverage.status == "sufficient"
