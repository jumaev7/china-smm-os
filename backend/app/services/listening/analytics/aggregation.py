"""Time-series aggregation and subject comparison (deterministic)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from app.services.listening.analytics.contracts import (
    AnalysisWindow,
    CoverageStatus,
    MentionTimeSeriesBucket,
    SubjectPerformance,
)
from app.services.listening.analytics.eligibility import analytical_timestamp
from app.services.listening.analytics.windows import iter_buckets, relative_change


def _mention_id(m: Any) -> str:
    return str(getattr(m, "id"))


def subject_weights_for_mention(
    mention_id: Any,
    matches_by_mention: dict[Any, list[Any]],
    comparable_subject_ids: set[str],
) -> dict[str, float]:
    """Fractional attribution across comparable subjects matched to one mention.

    Policy: ``fractional_attribution_v1`` — if a mention matches N distinct
    comparable subjects, each receives ``1/N``. Non-comparable subject matches
    are ignored for share-of-voice / subject performance denominators.
    """
    rows = matches_by_mention.get(mention_id) or []
    subjects: set[str] = set()
    for row in rows:
        sid = getattr(row, "subject_id", None)
        if sid is None:
            continue
        sid_s = str(sid)
        if sid_s in comparable_subject_ids:
            subjects.add(sid_s)
    if not subjects:
        return {}
    weight = 1.0 / len(subjects)
    return {sid: weight for sid in subjects}


def build_time_series(
    *,
    window: AnalysisWindow,
    mentions: Sequence[Any],
    matches_by_mention: dict[Any, list[Any]],
    comparable_subject_ids: set[str],
) -> list[MentionTimeSeriesBucket]:
    buckets = iter_buckets(
        window.start,
        window.end,
        window.granularity,
        timezone_name=window.timezone,
    )
    # Pre-bucket mentions by analytical timestamp.
    indexed: list[tuple[datetime, Any]] = []
    for m in mentions:
        ts = analytical_timestamp(m)
        if ts is None:
            continue
        indexed.append((ts, m))

    result: list[MentionTimeSeriesBucket] = []
    for b_start, b_end in buckets:
        in_bucket = [m for ts, m in indexed if b_start <= ts < b_end]
        by_subject: dict[str, float] = defaultdict(float)
        by_source: dict[str, int] = defaultdict(int)
        by_ctype: dict[str, int] = defaultdict(int)
        flags: list[str] = []
        for m in in_bucket:
            by_source[str(getattr(m, "source_type", None) or "unknown")] += 1
            by_ctype[str(getattr(m, "content_type", None) or "other")] += 1
            weights = subject_weights_for_mention(
                getattr(m, "id"), matches_by_mention, comparable_subject_ids,
            )
            for sid, w in weights.items():
                by_subject[sid] += w
        if not in_bucket:
            flags.append("empty_bucket")
        result.append(
            MentionTimeSeriesBucket(
                bucket_start=b_start,
                bucket_end=b_end,
                total_observed_mentions=len(in_bucket),
                counts_by_subject=dict(by_subject),
                counts_by_source=dict(by_source),
                counts_by_content_type=dict(by_ctype),
                unique_mention_count=len({_mention_id(m) for m in in_bucket}),
                data_quality_flags=flags,
                observed=True,  # bucket exists in calendar; count may be zero
            )
        )
    return result


def compute_subject_performance(
    *,
    subjects: Sequence[Any],
    current_mentions: Sequence[Any],
    previous_mentions: Sequence[Any] | None,
    matches_by_mention: dict[Any, list[Any]],
    comparable_subject_ids: set[str],
    coverage_status: CoverageStatus,
    comparison_valid: bool,
    evidence_limit: int = 5,
) -> list[SubjectPerformance]:
    current_counts: dict[str, float] = defaultdict(float)
    previous_counts: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[str]] = defaultdict(list)

    for m in current_mentions:
        weights = subject_weights_for_mention(
            getattr(m, "id"), matches_by_mention, comparable_subject_ids,
        )
        for sid, w in weights.items():
            current_counts[sid] += w
            if len(evidence[sid]) < evidence_limit:
                mid = _mention_id(m)
                if mid not in evidence[sid]:
                    evidence[sid].append(mid)

    if previous_mentions is not None and comparison_valid:
        for m in previous_mentions:
            weights = subject_weights_for_mention(
                getattr(m, "id"), matches_by_mention, comparable_subject_ids,
            )
            for sid, w in weights.items():
                previous_counts[sid] += w

    denominator = sum(current_counts.get(sid, 0.0) for sid in comparable_subject_ids)
    ranked = sorted(
        ((sid, current_counts.get(sid, 0.0)) for sid in comparable_subject_ids),
        key=lambda x: (-x[1], x[0]),
    )
    rank_map = {sid: i + 1 for i, (sid, _) in enumerate(ranked) if sid in comparable_subject_ids}

    prev_ranked = sorted(
        ((sid, previous_counts.get(sid, 0.0)) for sid in comparable_subject_ids),
        key=lambda x: (-x[1], x[0]),
    ) if comparison_valid else []
    prev_rank_map = {sid: i + 1 for i, (sid, _) in enumerate(prev_ranked)}

    subject_meta = {str(s.id): s for s in subjects}
    rows: list[SubjectPerformance] = []
    for sid in sorted(comparable_subject_ids, key=lambda x: (rank_map.get(x, 9999), x)):
        meta = subject_meta.get(sid)
        if meta is None:
            continue
        cur = float(current_counts.get(sid, 0.0))
        prev = float(previous_counts.get(sid, 0.0)) if comparison_valid else None
        if comparison_valid and prev is not None:
            abs_change = cur - prev
            pct, kind = relative_change(cur, prev)
        else:
            abs_change = None
            pct, kind = None, "unavailable"

        share = None
        if denominator > 0:
            share = round((cur / denominator) * 100.0, 4)
        elif coverage_status in {"insufficient", "unavailable"}:
            share = None
        else:
            # Empty comparable denominator → unavailable (not zero).
            share = None

        confidence = "high" if coverage_status == "sufficient" else (
            "medium" if coverage_status == "partial" else "low"
        )
        rows.append(
            SubjectPerformance(
                subject_id=sid,
                subject_type=str(getattr(meta, "subject_type", "other")),
                canonical_name=str(getattr(meta, "canonical_name", sid)),
                observed_mention_count=round(cur, 4),
                previous_comparable_count=None if prev is None else round(prev, 4),
                absolute_change=None if abs_change is None else round(abs_change, 4),
                percentage_change=None if pct is None else round(pct, 4),
                change_kind=kind,  # type: ignore[arg-type]
                observed_share=share,
                rank=rank_map.get(sid),
                previous_rank=prev_rank_map.get(sid) if comparison_valid else None,
                evidence_mention_ids=list(evidence.get(sid, [])),
                coverage_status=coverage_status,
                confidence_status=confidence,
            )
        )
    return rows


def observed_share_of_voice(
    performances: Sequence[SubjectPerformance],
    *,
    coverage_status: CoverageStatus,
) -> dict[str, Any]:
    """Scoped Observed Share of Voice envelope."""
    denom = sum(p.observed_mention_count for p in performances)
    comparison_set = [
        {
            "subject_id": p.subject_id,
            "subject_type": p.subject_type,
            "canonical_name": p.canonical_name,
        }
        for p in performances
    ]
    if denom <= 0 or coverage_status in {"unavailable"}:
        return {
            "metric_name": "observed_share_of_voice",
            "label": "Observed Share of Voice",
            "available": False,
            "denominator": denom,
            "comparison_set": comparison_set,
            "shares": [],
            "limitations": [
                "Observed Share of Voice is unavailable: insufficient comparable denominator.",
                "This is not total market share.",
            ],
            "multi_match_policy": "fractional_attribution_v1",
            "method_version": "listening_sov_v1",
            "coverage_status": coverage_status,
        }

    shares = []
    total_pct = 0.0
    for p in performances:
        pct = round((p.observed_mention_count / denom) * 100.0, 2) if denom else None
        if pct is not None:
            total_pct += pct
        shares.append({
            "subject_id": p.subject_id,
            "canonical_name": p.canonical_name,
            "subject_type": p.subject_type,
            "observed_mention_count": p.observed_mention_count,
            "observed_share_pct": pct,
            "rank": p.rank,
        })

    return {
        "metric_name": "observed_share_of_voice",
        "label": "Observed Share of Voice",
        "available": True,
        "denominator": round(denom, 4),
        "comparison_set": comparison_set,
        "shares": shares,
        "share_sum_pct": round(total_pct, 2),
        "limitations": [
            "Observed Share of Voice uses eligible mentions matched to configured comparable subjects only.",
            "This is not total market share or statistically representative public opinion.",
            "Multi-subject mentions use fractional attribution (1/N).",
        ],
        "multi_match_policy": "fractional_attribution_v1",
        "method_version": "listening_sov_v1",
        "coverage_status": coverage_status,
    }
