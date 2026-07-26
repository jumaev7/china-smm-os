"""Structured explanations for decision-support findings (pure, no AI).

Every explanation uses: Observation / Evidence / Interpretation / Consideration.
"""
from __future__ import annotations

from typing import Any

from app.models.advertising_decision_support import EXPLANATION_ENGINE_VERSION


def structure_explanation(
    *,
    subject: str,
    observation: str,
    evidence: dict[str, Any] | None = None,
    interpretation: str,
    consideration: str | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Canonical explanation envelope for Phase 2 diagnostics."""
    return {
        "subject": subject,
        "observation": observation,
        "evidence": evidence or {},
        "interpretation": interpretation,
        "consideration": consideration,
        "limitations": limitations or [],
        "engine_version": EXPLANATION_ENGINE_VERSION,
        "read_only": True,
        "ai_generated": False,
    }


def explain_from_diagnostic(diagnostic: dict[str, Any], *, subject: str) -> dict[str, Any]:
    """Adapt a diagnostic payload that already uses Observation/Evidence/... fields."""
    return structure_explanation(
        subject=subject,
        observation=str(diagnostic.get("observation") or diagnostic.get("message") or subject),
        evidence=diagnostic.get("evidence") or {},
        interpretation=str(
            diagnostic.get("interpretation")
            or diagnostic.get("reasoning")
            or "Derived deterministically from observed metrics."
        ),
        consideration=(
            diagnostic.get("possible_consideration")
            or diagnostic.get("recommendation")
        ),
        limitations=list(diagnostic.get("limitations") or [])
        + [
            "Advisory only; does not mutate provider state.",
            "Missing metrics are never fabricated.",
        ],
    )


def explain_simulation(simulation: dict[str, Any]) -> dict[str, Any]:
    return structure_explanation(
        subject="budget_simulation",
        observation=(
            f"Hypothetical allocation of {simulation.get('total_budget_minor')} "
            f"{simulation.get('currency')} across "
            f"{len(simulation.get('items') or [])} campaign(s)."
        ),
        evidence={
            "input_fingerprint": simulation.get("input_fingerprint"),
            "engine_version": simulation.get("engine_version"),
            "summary": simulation.get("summary_json"),
            "disclaimer": simulation.get("disclaimer"),
        },
        interpretation=(
            "This is a mechanical reallocation of a user-entered hypothetical budget. "
            "It does not predict future advertising performance."
        ),
        consideration=(
            "Review simulated shares against observed spend shares; "
            "do not treat simulated values as provider metrics."
        ),
        limitations=[
            "Simulations do not modify provider budgets.",
            "Observed reference metrics are server-loaded; clients cannot inject them.",
        ],
    )


def explain_pacing_projection(projection: dict[str, Any]) -> dict[str, Any]:
    return structure_explanation(
        subject="pacing_projection",
        observation=str(projection.get("message") or projection.get("projection_status")),
        evidence={
            "spent_so_far_minor": projection.get("spent_so_far_minor"),
            "elapsed_fraction": projection.get("elapsed_fraction"),
            "daily_spend_rate_minor": projection.get("daily_spend_rate_minor"),
            "projected_end_spend_minor": projection.get("projected_end_spend_minor"),
            "formula": projection.get("formula"),
            "label": projection.get("label"),
        },
        interpretation=(
            "Values are a mechanical extrapolation of the current spend rate across "
            "the remaining budget period — not an AI forecast."
        ),
        consideration="Review pacing if the mechanical projection diverges from plan.",
        limitations=[
            "Assumes approximately constant spend rate.",
            "Paused, ended, stale, or incomplete inputs yield non-projected statuses.",
        ],
    )


def explain_concentration(result: dict[str, Any]) -> dict[str, Any]:
    return explain_from_diagnostic(result, subject="concentration")


def explain_diminishing_returns(result: dict[str, Any]) -> dict[str, Any]:
    base = explain_from_diagnostic(result, subject="diminishing_returns")
    base["limitations"] = list(base.get("limitations") or []) + [
        "Historical co-occurrence only; does not claim causal diminishing returns.",
    ]
    return base


def explain_creative_rotation(result: dict[str, Any]) -> dict[str, Any]:
    return explain_from_diagnostic(result, subject="creative_rotation")


def explain_experiment_review(review: dict[str, Any]) -> dict[str, Any]:
    return structure_explanation(
        subject="experiment_review",
        observation=str(review.get("conclusion") or review.get("result_status")),
        evidence=review.get("evidence") or review.get("comparison") or {},
        interpretation=(
            "Variant comparison uses directional language over observed metrics only."
        ),
        consideration="Treat results as advisory input for human review.",
        limitations=list(review.get("limitations") or []) + [
            "Statistical significance is not claimed.",
            "China SMM OS does not launch provider experiments.",
        ],
    )


def explain_recommendation(rec: dict[str, Any]) -> dict[str, Any]:
    return structure_explanation(
        subject=str(rec.get("recommendation_key") or "recommendation"),
        observation=str(rec.get("observation") or ""),
        evidence=rec.get("evidence") or {},
        interpretation=str(rec.get("reasoning") or ""),
        consideration=str(rec.get("recommendation") or ""),
        limitations=list(rec.get("limitations") or []),
    )


__all__ = [
    "structure_explanation",
    "explain_from_diagnostic",
    "explain_simulation",
    "explain_pacing_projection",
    "explain_concentration",
    "explain_diminishing_returns",
    "explain_creative_rotation",
    "explain_experiment_review",
    "explain_recommendation",
]
