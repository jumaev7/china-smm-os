"""Advertising Decision Support — Phase 2 advisory / simulation domain.

Consumes normalized Phase 1 measurement observations only. NEVER queries
provider SDKs. NEVER mutates provider campaigns, budgets, bids, creatives, or
schedules. Simulations and experiments are planning/observation artifacts.
"""
from __future__ import annotations

from app.models.advertising_decision_support import (
    BUDGET_SIMULATION_ENGINE_VERSION,
    COMPARISON_ENGINE_VERSION,
    CONCENTRATION_ENGINE_VERSION,
    CREATIVE_ROTATION_ENGINE_VERSION,
    DECISION_SUPPORT_VERSION,
    DIMINISHING_RETURNS_ENGINE_VERSION,
    EXPERIMENT_PLANNER_ENGINE_VERSION,
    EXPLANATION_ENGINE_VERSION,
    PACING_PROJECTION_ENGINE_VERSION,
    RECOMMENDATION_ENGINE_VERSION,
)

__all__ = [
    "DECISION_SUPPORT_VERSION",
    "COMPARISON_ENGINE_VERSION",
    "BUDGET_SIMULATION_ENGINE_VERSION",
    "PACING_PROJECTION_ENGINE_VERSION",
    "CONCENTRATION_ENGINE_VERSION",
    "DIMINISHING_RETURNS_ENGINE_VERSION",
    "CREATIVE_ROTATION_ENGINE_VERSION",
    "EXPERIMENT_PLANNER_ENGINE_VERSION",
    "RECOMMENDATION_ENGINE_VERSION",
    "EXPLANATION_ENGINE_VERSION",
]
