"""Deterministic planner limits with stable error codes.

All limits are server-controlled. Exceeding a limit raises ``LimitExceededError``
with a stable ``details.limit_key`` so clients get a consistent contract.
"""
from __future__ import annotations

from app.services.campaign_planner.errors import LimitExceededError, ValidationError

# Hard limits (deterministic).
MAX_GOALS_PER_CAMPAIGN = 25
MAX_KPIS_PER_CAMPAIGN = 25
MAX_AUDIENCES_PER_CAMPAIGN = 25
MAX_PILLARS_PER_CAMPAIGN = 20
MAX_PHASES_PER_CAMPAIGN = 12
MAX_PLATFORMS_PER_CAMPAIGN = 5
MAX_LOCALES_PER_CAMPAIGN = 4
MAX_PLAN_VERSIONS_PER_CAMPAIGN = 100
MAX_SLOTS_PER_PLAN = 1000
MAX_CAMPAIGN_DURATION_DAYS = 366
MAX_POSTS_PER_DAY_PER_PLATFORM = 10
MIN_SPACING_MINUTES = 15
MAX_BLACKOUT_DATES = 120

__all__ = [
    "LimitExceededError",
    "ValidationError",
    "MAX_GOALS_PER_CAMPAIGN",
    "MAX_KPIS_PER_CAMPAIGN",
    "MAX_AUDIENCES_PER_CAMPAIGN",
    "MAX_PILLARS_PER_CAMPAIGN",
    "MAX_PHASES_PER_CAMPAIGN",
    "MAX_PLATFORMS_PER_CAMPAIGN",
    "MAX_LOCALES_PER_CAMPAIGN",
    "MAX_PLAN_VERSIONS_PER_CAMPAIGN",
    "MAX_SLOTS_PER_PLAN",
    "MAX_CAMPAIGN_DURATION_DAYS",
    "MAX_POSTS_PER_DAY_PER_PLATFORM",
    "MIN_SPACING_MINUTES",
    "MAX_BLACKOUT_DATES",
    "enforce",
    "enforce_child_count",
    "require",
]


def enforce(count: int, maximum: int, limit_key: str) -> None:
    if count > maximum:
        raise LimitExceededError(
            f"{limit_key} limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "requested": count},
        ).to_http()


def enforce_child_count(existing: int, maximum: int, limit_key: str) -> None:
    """Guard before inserting one more child row."""
    if existing + 1 > maximum:
        raise LimitExceededError(
            f"{limit_key} limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "existing": existing},
        ).to_http()


def require(condition: bool, message: str, *, field: str | None = None) -> None:
    if not condition:
        details = {"field": field} if field else None
        raise ValidationError(message, details=details).to_http()
