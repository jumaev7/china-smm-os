"""Structured, evidence-backed explanations for advertising findings.

Every explanation is descriptive (what was observed + why we say it) plus its
limitations — never prescriptive or predictive. These are pure functions with no
side effects, safe to call from read endpoints.
"""
from __future__ import annotations

from typing import Any

from app.services.advertising_intelligence.metric_catalog import (
    METRIC_CATALOG,
    get_description,
)


def _explanation(
    *,
    subject: str,
    observation: str,
    evidence: dict[str, Any],
    reasoning: str,
    limitations: list[str],
    recommendation: str | None = None,
) -> dict:
    return {
        "subject": subject,
        "observation": observation,
        "evidence": evidence,
        "reasoning": reasoning,
        "limitations": limitations,
        "recommendation": recommendation,
        "read_only": True,
    }


def explain_metric(metric_key: str) -> dict:
    definition = METRIC_CATALOG.get(metric_key)
    if definition is None:
        return _explanation(
            subject=metric_key,
            observation=f"'{metric_key}' is not a recognized normalized metric.",
            evidence={},
            reasoning="The metric is not present in the versioned catalog.",
            limitations=["Unknown metric; no semantics available."],
        )
    limitations = [definition.comparability_caveat] if definition.comparability_caveat else []
    if not definition.cross_provider_comparable:
        limitations.append("Not marked cross-provider comparable; compare within one provider only.")
    return _explanation(
        subject=metric_key,
        observation=get_description(metric_key) or metric_key,
        evidence={
            "value_type": definition.value_type,
            "aggregation_type": definition.aggregation_type,
            "currency_behavior": definition.currency_behavior,
            "formula": definition.formula,
        },
        reasoning=(
            f"'{metric_key}' is a {definition.aggregation_type} metric "
            f"({definition.value_type})."
            + (f" Computed as {definition.formula}." if definition.formula else "")
        ),
        limitations=limitations,
    )


def explain_pacing(pacing: dict) -> dict:
    status = pacing.get("pacing_status", "unknown")
    reasoning = {
        "not_applicable": "No budget is configured, so pacing does not apply.",
        "unknown": "Insufficient spend data to compute pacing.",
        "underspending": "Spend is below the expected pace for the window (descriptive only).",
        "on_pace": "Spend is within the expected pace band (0.8–1.2).",
        "overspending": "Spend is above the expected pace for the window.",
        "budget_exhausted": "The budget for the window appears fully consumed.",
        "paused": "Campaign or ad set is paused; pacing is not evaluated.",
        "ended": "Campaign window has ended; pacing is not evaluated.",
        "insufficient_data": "Not enough spend or budget data to evaluate pacing.",
    }.get(status, "Pacing status computed from spend vs expected spend.")
    return _explanation(
        subject="pacing",
        observation=f"Pacing status: {status}.",
        evidence={
            "pace_ratio": str(pacing.get("pace_ratio")) if pacing.get("pace_ratio") is not None else None,
            "expected_spend_minor": pacing.get("expected_spend_minor"),
            "remaining_minor": pacing.get("remaining_minor"),
        },
        reasoning=reasoning,
        limitations=[
            "Pacing compares spend to a linear expected spend; it does not model "
            "scheduling, dayparting, or learning phases.",
        ],
        recommendation="Review budget and delivery settings." if status in ("overspending", "budget_exhausted", "underspending") else None,
    )


def explain_delivery(finding: dict) -> dict:
    key = finding.get("anomaly_key", "unknown")
    descriptions = {
        "zero_delivery_active_entity": "An active entity has no impressions.",
        "spend_without_impressions": "Spend was recorded without any impressions.",
        "impressions_without_spend": "Impressions were recorded without any spend.",
    }
    return _explanation(
        subject="delivery",
        observation=descriptions.get(key, f"Delivery anomaly: {key}."),
        evidence=finding.get("evidence", {}),
        reasoning="Derived deterministically from the latest ingested metrics for the entity.",
        limitations=[
            "Advisory only; may reflect normal provider reporting lag rather than a real problem.",
        ],
        recommendation="Investigate the affected entity's status and configuration.",
    )


def explain_creative_fatigue(fatigue: dict) -> dict:
    status = fatigue.get("status", "insufficient_data")
    return _explanation(
        subject="creative_fatigue",
        observation=fatigue.get("message", status),
        evidence=fatigue.get("evidence", {}),
        reasoning="Inferred from creative frequency (impressions per person).",
        limitations=[
            "Single-point frequency heuristic; a real fatigue assessment needs a "
            "CTR/frequency trend over time.",
            "This is a possible signal, not a directive.",
        ],
        recommendation="Consider preparing a fresh creative variant." if status in ("possible_fatigue", "strong_fatigue_signal") else None,
    )


def explain_reconciliation(item: dict) -> dict:
    status = item.get("reconciliation_status", "not_available")
    return _explanation(
        subject="conversion_reconciliation",
        observation=f"Reconciliation status: {status}.",
        evidence={
            "conversions_reported": item.get("conversions_reported"),
            "conversions_crm_confirmed": item.get("conversions_crm_confirmed"),
            "linked": item.get("linked"),
        },
        reasoning=(
            "Provider-reported conversions are compared to CRM-confirmed outcomes "
            "only when explicit linkage evidence exists."
        ),
        limitations=[
            "CRM confirmation requires explicit ids/UTM/tracked link/lead-source; "
            "timing alone is never sufficient.",
        ],
    )


__all__ = [
    "explain_metric",
    "explain_pacing",
    "explain_delivery",
    "explain_creative_fatigue",
    "explain_reconciliation",
]
