"""Emerging topic detection ``listening_topics_v1``.

Deterministic, explainable: uses matched terms / query terms / subject aliases
already retained by Phase 1 matching. No unsupervised topic modeling.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Sequence

from app.services.listening.analytics.contracts import (
    CoverageStatus,
    EmergingTopic,
    TOPIC_METHOD_VERSION,
)
from app.services.listening.analytics.windows import relative_change

# Conservative stop / noise terms (EN/RU/ZH-ish common tokens).
STOP_TERMS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "this", "that", "it", "with", "as", "at", "by", "from",
    "и", "в", "на", "не", "что", "это", "как", "для", "по", "из", "к", "а",
    "的", "了", "是", "在", "和", "有", "我", "你", "他", "她", "们",
    "http", "https", "www", "com",
})

MIN_CURRENT_VOLUME = 3
MIN_DISTINCT_MENTIONS = 2


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", (term or "").strip().casefold())


def _topic_id(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    return f"topic_{digest}"


def detect_emerging_topics(
    *,
    current_mentions: Sequence[Any],
    previous_mentions: Sequence[Any],
    matches_by_mention: dict[Any, list[Any]],
    coverage_status: CoverageStatus,
    comparison_valid: bool,
    evidence_limit: int = 5,
    now: datetime | None = None,
) -> list[EmergingTopic]:
    if coverage_status in {"unavailable", "insufficient"}:
        return []

    def collect(mentions: Sequence[Any]) -> dict[str, dict[str, Any]]:
        acc: dict[str, dict[str, Any]] = {}
        for m in mentions:
            mid = getattr(m, "id")
            rows = matches_by_mention.get(mid) or []
            seen_terms: set[str] = set()
            for row in rows:
                raw = getattr(row, "matched_term", None) or ""
                term = _normalize_term(str(raw))
                if not term or term in STOP_TERMS or len(term) < 2:
                    continue
                if term in seen_terms:
                    continue
                seen_terms.add(term)
                bucket = acc.setdefault(term, {
                    "count": 0,
                    "mention_ids": [],
                    "query_ids": set(),
                    "subject_ids": set(),
                    "first_observed_at": None,
                    "terms": set(),
                })
                bucket["count"] += 1
                bucket["terms"].add(term)
                mid_s = str(mid)
                if mid_s not in bucket["mention_ids"] and len(bucket["mention_ids"]) < evidence_limit:
                    bucket["mention_ids"].append(mid_s)
                qid = getattr(row, "query_id", None)
                sid = getattr(row, "subject_id", None)
                if qid is not None:
                    bucket["query_ids"].add(str(qid))
                if sid is not None:
                    bucket["subject_ids"].add(str(sid))
                ts = getattr(m, "published_at", None) or getattr(m, "first_observed_at", None)
                if ts is not None:
                    prev = bucket["first_observed_at"]
                    if prev is None or ts < prev:
                        bucket["first_observed_at"] = ts
        return acc

    current = collect(current_mentions)
    baseline = collect(previous_mentions) if comparison_valid else {}

    topics: list[EmergingTopic] = []
    for term, data in current.items():
        cur_n = int(data["count"])
        if cur_n < MIN_CURRENT_VOLUME:
            continue
        if len(data["mention_ids"]) < MIN_DISTINCT_MENTIONS and cur_n < MIN_CURRENT_VOLUME + 1:
            # Single-mention trends are not high-confidence emerging topics.
            continue
        base_n = int(baseline.get(term, {}).get("count", 0)) if comparison_valid else 0
        if comparison_valid:
            velocity, kind = relative_change(float(cur_n), float(base_n))
        else:
            velocity, kind = None, "unavailable"

        # Require growth or new activity relative to baseline when comparison valid.
        if comparison_valid and kind == "percentage" and (velocity or 0) < 50:
            continue
        if comparison_valid and kind == "zero_baseline_zero_current":
            continue
        if comparison_valid and cur_n <= base_n:
            continue

        confidence = "medium"
        limitations = [
            "Detected from deterministic match terms / aliases — not unsupervised topic modeling.",
            "Emerging topics require minimum current volume and multi-mention evidence.",
        ]
        if coverage_status != "sufficient":
            confidence = "low"
            limitations.append("Coverage is only partial; treat emergence cautiously.")
        if not comparison_valid:
            confidence = "low"
            limitations.append("Baseline comparison unavailable.")
        if kind == "new_activity":
            confidence = "medium" if coverage_status == "sufficient" else "low"

        reason = (
            f"Term '{term}' appeared in {cur_n} eligible mention match(es) "
            f"versus baseline {base_n} ({kind})."
        )
        topics.append(
            EmergingTopic(
                topic_id=_topic_id(term),
                label=term,
                matched_terms=sorted(data["terms"]),
                query_ids=sorted(data["query_ids"]),
                subject_ids=sorted(data["subject_ids"]),
                current_count=cur_n,
                baseline_count=base_n,
                velocity=None if velocity is None else round(velocity, 4),
                change_kind=kind,  # type: ignore[arg-type]
                first_observed_at=data["first_observed_at"],
                representative_mention_ids=list(data["mention_ids"]),
                confidence=confidence,
                coverage_status=coverage_status,
                detection_method=TOPIC_METHOD_VERSION,
                detection_reason=reason,
                limitations=limitations,
            )
        )

    topics.sort(key=lambda t: (-t.current_count, t.label))
    return topics[:25]
