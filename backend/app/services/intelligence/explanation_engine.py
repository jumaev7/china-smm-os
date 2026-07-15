"""Deterministic explanation engine — every insight must explain itself."""
from __future__ import annotations

from typing import Any

from app.services.intelligence.types import EXPLANATION_ENGINE_VERSION, Explanation


class ExplanationEngine:
    """Build structured Observation → Evidence → Reasoning → Recommendation payloads."""

    version = EXPLANATION_ENGINE_VERSION

    @staticmethod
    def build(
        *,
        observation: str,
        evidence: list[str] | None = None,
        reasoning: str,
        recommendation: str | None = None,
    ) -> Explanation:
        return Explanation(
            observation=observation,
            evidence=list(evidence or []),
            reasoning=reasoning,
            recommendation=recommendation,
            engine_version=EXPLANATION_ENGINE_VERSION,
        )

    @staticmethod
    def for_score(
        *,
        category: str,
        score: int,
        evidence_lines: list[str],
        reasoning: str,
        recommendation: str | None = None,
    ) -> dict[str, Any]:
        return ExplanationEngine.build(
            observation=f"{category.replace('_', ' ').title()} score is {score}/100",
            evidence=evidence_lines,
            reasoning=reasoning,
            recommendation=recommendation,
        ).to_dict()

    @staticmethod
    def for_recommendation(
        *,
        title: str,
        evidence_lines: list[str],
        reasoning: str,
        recommendation: str,
    ) -> dict[str, Any]:
        return ExplanationEngine.build(
            observation=title,
            evidence=evidence_lines,
            reasoning=reasoning,
            recommendation=recommendation,
        ).to_dict()
