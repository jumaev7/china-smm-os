"""Limits for Advertising Decision Support expensive operations."""
from __future__ import annotations

from app.services.advertising_decision_support.errors import (
    AdExperimentValidationError,
    AdSimulationValidationError,
)
from app.services.advertising_intelligence.errors import AdRefreshRateLimitedError

MAX_COMPARISON_ENTITIES = 8
MAX_SIMULATION_ENTITIES = 20
MAX_SIMULATION_REQUESTS_PER_TENANT_PER_HOUR = 30
MAX_EXPERIMENT_VARIANTS = 6
MAX_EXPERIMENTS_PER_TENANT = 200
MAX_CHANGE_PLAN_ITEMS = 50
ALLOCATION_SUM_TOLERANCE = 0.0001  # absolute tolerance on allocation fractions summing to 1.0


def enforce_simulation_entity_count(count: int) -> None:
    if count < 1:
        raise AdSimulationValidationError(
            "at least one campaign is required",
            details={"limit_key": "simulation_entities", "min": 1, "requested": count},
        )
    if count > MAX_SIMULATION_ENTITIES:
        raise AdSimulationValidationError(
            "too many campaigns in simulation",
            details={
                "limit_key": "simulation_entities",
                "max": MAX_SIMULATION_ENTITIES,
                "requested": count,
            },
        )


def enforce_comparison_entity_count(count: int) -> None:
    if count < 2:
        raise AdSimulationValidationError(
            "at least two entities are required for comparison",
            details={"limit_key": "comparison_entities", "min": 2, "requested": count},
        )
    if count > MAX_COMPARISON_ENTITIES:
        raise AdSimulationValidationError(
            "too many entities in comparison",
            details={
                "limit_key": "comparison_entities",
                "max": MAX_COMPARISON_ENTITIES,
                "requested": count,
            },
        )


def enforce_variant_count(count: int) -> None:
    if count < 2:
        raise AdExperimentValidationError(
            "at least two variants are required",
            details={"limit_key": "experiment_variants", "min": 2, "requested": count},
        )
    if count > MAX_EXPERIMENT_VARIANTS:
        raise AdExperimentValidationError(
            "too many experiment variants",
            details={
                "limit_key": "experiment_variants",
                "max": MAX_EXPERIMENT_VARIANTS,
                "requested": count,
            },
        )


def enforce_rate_limit(count_in_window: int, maximum: int, limit_key: str) -> None:
    if count_in_window >= maximum:
        raise AdRefreshRateLimitedError(
            f"{limit_key} rate limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "count_in_window": count_in_window},
        )


__all__ = [
    "MAX_COMPARISON_ENTITIES",
    "MAX_SIMULATION_ENTITIES",
    "MAX_SIMULATION_REQUESTS_PER_TENANT_PER_HOUR",
    "MAX_EXPERIMENT_VARIANTS",
    "MAX_EXPERIMENTS_PER_TENANT",
    "MAX_CHANGE_PLAN_ITEMS",
    "ALLOCATION_SUM_TOLERANCE",
    "enforce_simulation_entity_count",
    "enforce_comparison_entity_count",
    "enforce_variant_count",
    "enforce_rate_limit",
]
