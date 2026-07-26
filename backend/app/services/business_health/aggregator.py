"""Pure aggregation and explainability helpers for Business Health v2."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from app.services.business_health.policy import (
    BUSINESS_HEALTH_VERSION,
    DISCLAIMER,
    DOMAIN_WEIGHTS,
    SCORE_BANDS,
    TOP_DEDUCTIONS_LIMIT,
    TOP_POSITIVE_SIGNALS_LIMIT,
)
from app.services.business_health.types import (
    BusinessHealthAssessment,
    DomainHealthAssessment,
    HealthSignal,
)


def clamp_score(value: float | int) -> int:
    return max(0, min(100, int(round(value))))


def band_for_score(score: int) -> str:
    s = clamp_score(score)
    for lower, name in SCORE_BANDS:
        if s >= lower:
            return name
    return "critical"


def normalize_effective_weights(
    domains: Iterable[DomainHealthAssessment],
) -> list[DomainHealthAssessment]:
    """Assign effective_weight only to available domains; sum to 1.0 when any exist."""
    available = [d for d in domains if d.availability == "available" and d.score is not None]
    total = sum(float(d.weight) for d in available)
    result: list[DomainHealthAssessment] = []
    for d in domains:
        if d.availability == "available" and d.score is not None and total > 0:
            d.effective_weight = float(d.weight) / total
        else:
            d.effective_weight = 0.0
        result.append(d)
    return result


def aggregate_score(domains: Iterable[DomainHealthAssessment]) -> int:
    """Weighted mean of available domain scores using effective weights."""
    normalized = normalize_effective_weights(list(domains))
    available = [d for d in normalized if d.effective_weight > 0 and d.score is not None]
    if not available:
        return 50  # empty org / no evaluable domains — neutral, not critical
    raw = sum(float(d.score) * d.effective_weight for d in available)
    return clamp_score(raw)


def _impact_sort_key(signal: HealthSignal) -> tuple[int, int, str]:
    # Larger absolute negative impact first; positives sorted by positive impact desc.
    if signal.score_impact < 0:
        return (0, signal.score_impact, signal.code)  # more negative first via ascending
    return (1, -signal.score_impact, signal.code)


def rank_deductions(signals: Iterable[HealthSignal], *, limit: int = TOP_DEDUCTIONS_LIMIT) -> list[HealthSignal]:
    negatives = [s for s in signals if s.score_impact < 0]
    negatives.sort(key=lambda s: (s.score_impact, s.code))
    return negatives[:limit]


def rank_positives(signals: Iterable[HealthSignal], *, limit: int = TOP_POSITIVE_SIGNALS_LIMIT) -> list[HealthSignal]:
    positives = [s for s in signals if s.score_impact > 0 or s.severity == "positive"]
    positives.sort(key=lambda s: (-s.score_impact, s.code))
    return positives[:limit]


def data_confidence(domains: list[DomainHealthAssessment]) -> float:
    configured = [d for d in domains if d.weight > 0]
    if not configured:
        return 0.0
    available = [d for d in configured if d.availability == "available"]
    if not available:
        return 0.0
    # Blend domain count coverage with average per-domain confidence.
    count_ratio = len(available) / len(configured)
    avg_conf = sum(d.confidence for d in available) / len(available)
    return max(0.0, min(1.0, 0.55 * count_ratio + 0.45 * avg_conf))


def build_executive_summary(assessment: BusinessHealthAssessment) -> str:
    band = assessment.status.replace("_", " ")
    parts = [
        f"Business Health: {assessment.score}/100 — {band.title()}.",
        f"{assessment.domains_evaluated} of "
        f"{assessment.domains_evaluated + assessment.domains_unavailable} domains evaluated "
        f"(coverage {int(round(assessment.data_confidence * 100))}%).",
    ]
    if assessment.deductions:
        top = assessment.deductions[0]
        parts.append(f"Largest deduction: {top.title}.")
    if assessment.positive_signals:
        parts.append(f"Supporting signal: {assessment.positive_signals[0].title}.")
    unavailable = [
        d.label for d in assessment.domains if d.availability != "available"
    ]
    if unavailable:
        parts.append(
            "Unavailable: " + ", ".join(unavailable[:4])
            + ("…" if len(unavailable) > 4 else "")
            + "."
        )
    if assessment.change is None:
        parts.append("Score history is not available for comparison.")
    return " ".join(parts)


def assemble_assessment(
    domains: list[DomainHealthAssessment],
    *,
    calculated_at: datetime | None = None,
    duration_ms: float | None = None,
) -> BusinessHealthAssessment:
    now = calculated_at or datetime.now(timezone.utc)
    # Ensure base weights from policy when missing.
    for d in domains:
        if d.weight <= 0 and d.domain in DOMAIN_WEIGHTS:
            d.weight = DOMAIN_WEIGHTS[d.domain]
        if d.score is not None:
            d.score = clamp_score(d.score)
            d.status = band_for_score(d.score)

    domains = normalize_effective_weights(domains)
    score = aggregate_score(domains)
    status = band_for_score(score)

    all_deductions: list[HealthSignal] = []
    all_positives: list[HealthSignal] = []
    for d in domains:
        if d.availability != "available":
            continue
        all_deductions.extend(d.deductions)
        all_positives.extend(d.positive_signals)

    top_deductions = rank_deductions(all_deductions)
    top_positives = rank_positives(all_positives)

    evaluated = sum(1 for d in domains if d.availability == "available")
    unavailable = sum(1 for d in domains if d.availability != "available")

    assessment = BusinessHealthAssessment(
        score=score,
        status=status,
        calculated_at=now,
        methodology_version=BUSINESS_HEALTH_VERSION,
        data_confidence=data_confidence(domains),
        domains_evaluated=evaluated,
        domains_unavailable=unavailable,
        domains=domains,
        deductions=top_deductions,
        positive_signals=top_positives,
        previous_score=None,
        change=None,
        history_available=False,
        disclaimer=DISCLAIMER,
        duration_ms=duration_ms,
    )
    assessment.executive_summary = build_executive_summary(assessment)
    return assessment
