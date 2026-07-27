"""Structured MarketInsight generation from deterministic analytics outputs."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Sequence

from app.services.listening.analytics.contracts import (
    INSIGHT_METHOD_VERSION,
    AnalysisWindow,
    CoverageStatus,
    EmergingTopic,
    ListeningAnomaly,
    MarketInsight,
    SubjectPerformance,
)


def build_insight_key(
    *,
    tenant_id: str,
    method_version: str,
    category: str,
    code: str,
    window_key: str,
    start_iso: str,
    end_iso: str,
    entity_ref: str = "",
) -> str:
    raw = "|".join([tenant_id, method_version, category, code, window_key, start_iso, end_iso, entity_ref])
    return "ins_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def generate_insights(
    *,
    tenant_id: str,
    window: AnalysisWindow,
    coverage_status: CoverageStatus,
    subject_rows: Sequence[SubjectPerformance],
    topics: Sequence[EmergingTopic],
    anomalies: Sequence[ListeningAnomaly],
    review_states: dict[str, str] | None = None,
    now: datetime | None = None,
) -> list[MarketInsight]:
    clock = now or datetime.now(timezone.utc)
    reviews = review_states or {}
    win = window.to_dict()
    start_iso = win["start"] or ""
    end_iso = win["end"] or ""
    out: list[MarketInsight] = []

    if coverage_status in {"unavailable", "insufficient"}:
        key = build_insight_key(
            tenant_id=tenant_id,
            method_version=INSIGHT_METHOD_VERSION,
            category="coverage",
            code="coverage_warning",
            window_key=window.window_key,
            start_iso=start_iso,
            end_iso=end_iso,
        )
        out.append(
            MarketInsight(
                insight_key=key,
                code="coverage_warning",
                category="coverage",
                severity="medium",
                priority=10,
                title="Coverage insufficient for strong market conclusions",
                explanation=(
                    "Eligible observation coverage is insufficient or unavailable. "
                    "Strong subject comparisons and market conclusions are suppressed."
                ),
                observed_facts=[
                    f"coverage_status={coverage_status}",
                    f"window={window.window_key}",
                ],
                evidence_mention_ids=[],
                affected_subject_ids=[],
                window=win,
                confidence="low",
                coverage_status=coverage_status,
                methodology_version=INSIGHT_METHOD_VERSION,
                analyst_review_state=reviews.get(key, "unreviewed"),  # type: ignore[arg-type]
                generated_at=clock,
                limitations=[
                    "This is a data-quality finding, not a market decline signal.",
                    "Business Health scoring is unchanged by listening insights.",
                ],
            )
        )
        # Still surface data-quality anomalies as insights.
        for anomaly in anomalies:
            if anomaly.category != "data_quality":
                continue
            ik = build_insight_key(
                tenant_id=tenant_id,
                method_version=INSIGHT_METHOD_VERSION,
                category="data_quality",
                code=anomaly.code,
                window_key=window.window_key,
                start_iso=start_iso,
                end_iso=end_iso,
                entity_ref=anomaly.affected_source_type or "",
            )
            out.append(
                MarketInsight(
                    insight_key=ik,
                    code=anomaly.code,
                    category="data_quality",
                    severity=anomaly.severity,
                    priority=20 + {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(anomaly.severity, 4),
                    title=anomaly.anomaly_type.replace("_", " ").title(),
                    explanation=anomaly.explanation,
                    observed_facts=[
                        f"current_value={anomaly.current_value}",
                        f"baseline_value={anomaly.baseline_value}",
                        f"category={anomaly.category}",
                    ],
                    evidence_mention_ids=list(anomaly.evidence_mention_ids),
                    affected_subject_ids=[anomaly.affected_subject_id] if anomaly.affected_subject_id else [],
                    window=win,
                    confidence="medium",
                    coverage_status=coverage_status,
                    methodology_version=INSIGHT_METHOD_VERSION,
                    analyst_review_state=reviews.get(ik, "unreviewed"),  # type: ignore[arg-type]
                    generated_at=clock,
                    limitations=list(anomaly.limitations),
                )
            )
        return out

    # Strongest subject change
    candidates = [
        r for r in subject_rows
        if r.absolute_change is not None and r.change_kind in {"percentage", "new_activity"}
    ]
    candidates.sort(key=lambda r: abs(r.absolute_change or 0), reverse=True)
    if candidates:
        top = candidates[0]
        code = "subject_observed_change"
        ik = build_insight_key(
            tenant_id=tenant_id,
            method_version=INSIGHT_METHOD_VERSION,
            category="subject_comparison",
            code=code,
            window_key=window.window_key,
            start_iso=start_iso,
            end_iso=end_iso,
            entity_ref=top.subject_id,
        )
        if top.change_kind == "new_activity":
            facts = [
                f"Subject '{top.canonical_name}' moved from 0 to {top.observed_mention_count} "
                "eligible observed mentions (new_activity).",
            ]
            explanation = (
                f"Observed mentions for '{top.canonical_name}' show new activity from a zero baseline."
            )
        else:
            facts = [
                f"Observed mentions for '{top.canonical_name}' changed from "
                f"{top.previous_comparable_count} to {top.observed_mention_count}.",
                f"Absolute change: {top.absolute_change}.",
            ]
            if top.percentage_change is not None:
                facts.append(f"Percentage change: {top.percentage_change}%.")
            explanation = (
                f"Observed mentions for '{top.canonical_name}' changed from "
                f"{top.previous_comparable_count} to {top.observed_mention_count}."
            )
        out.append(
            MarketInsight(
                insight_key=ik,
                code=code,
                category="subject_comparison",
                severity="medium" if abs(top.absolute_change or 0) >= 5 else "low",
                priority=30,
                title=f"Observed attention shift: {top.canonical_name}",
                explanation=explanation,
                observed_facts=facts,
                evidence_mention_ids=list(top.evidence_mention_ids),
                affected_subject_ids=[top.subject_id],
                window=win,
                confidence=top.confidence_status,
                coverage_status=coverage_status,
                methodology_version=INSIGHT_METHOD_VERSION,
                analyst_review_state=reviews.get(ik, "unreviewed"),  # type: ignore[arg-type]
                generated_at=clock,
                limitations=[
                    "Descriptive of eligible observed mentions only.",
                    "Does not imply sentiment, preference, or future demand.",
                ],
            )
        )

    if topics:
        topic = topics[0]
        ik = build_insight_key(
            tenant_id=tenant_id,
            method_version=INSIGHT_METHOD_VERSION,
            category="emerging_topic",
            code="emerging_topic",
            window_key=window.window_key,
            start_iso=start_iso,
            end_iso=end_iso,
            entity_ref=topic.topic_id,
        )
        out.append(
            MarketInsight(
                insight_key=ik,
                code="emerging_topic",
                category="emerging_topic",
                severity="medium" if topic.confidence != "low" else "low",
                priority=40,
                title=f"Emerging observed topic: {topic.label}",
                explanation=topic.detection_reason,
                observed_facts=[
                    f"current_count={topic.current_count}",
                    f"baseline_count={topic.baseline_count}",
                    f"change_kind={topic.change_kind}",
                    f"detection_method={topic.detection_method}",
                ],
                evidence_mention_ids=list(topic.representative_mention_ids),
                affected_subject_ids=list(topic.subject_ids),
                window=win,
                confidence=topic.confidence,
                coverage_status=coverage_status,
                methodology_version=INSIGHT_METHOD_VERSION,
                analyst_review_state=reviews.get(ik, "unreviewed"),  # type: ignore[arg-type]
                generated_at=clock,
                limitations=list(topic.limitations),
            )
        )

    for anomaly in anomalies:
        ik = build_insight_key(
            tenant_id=tenant_id,
            method_version=INSIGHT_METHOD_VERSION,
            category=anomaly.category,
            code=anomaly.code,
            window_key=window.window_key,
            start_iso=start_iso,
            end_iso=end_iso,
            entity_ref=anomaly.affected_subject_id or anomaly.affected_topic_id or anomaly.affected_source_type or "",
        )
        # Avoid duplicating the top subject / topic insight codes already emitted.
        if any(i.insight_key == ik for i in out):
            continue
        out.append(
            MarketInsight(
                insight_key=ik,
                code=anomaly.code,
                category=anomaly.category,
                severity=anomaly.severity,
                priority=50 + {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(anomaly.severity, 4),
                title=anomaly.anomaly_type.replace("_", " ").title(),
                explanation=anomaly.explanation,
                observed_facts=[
                    f"current_value={anomaly.current_value}",
                    f"baseline_value={anomaly.baseline_value}",
                    f"magnitude={anomaly.magnitude}",
                    f"category={anomaly.category}",
                ],
                evidence_mention_ids=list(anomaly.evidence_mention_ids),
                affected_subject_ids=[anomaly.affected_subject_id] if anomaly.affected_subject_id else [],
                window=win,
                confidence="medium" if coverage_status == "sufficient" else "low",
                coverage_status=coverage_status,
                methodology_version=INSIGHT_METHOD_VERSION,
                analyst_review_state=reviews.get(ik, "unreviewed"),  # type: ignore[arg-type]
                generated_at=clock,
                limitations=list(anomaly.limitations),
            )
        )

    out.sort(key=lambda i: (i.priority, i.code))
    return out
