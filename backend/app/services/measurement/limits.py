"""Deterministic measurement limits with stable error codes.

All limits are server-controlled. Exceeding a limit raises ``LimitExceededError``
(or ``RefreshRateLimitedError`` for the rate-limit case) with a stable
``details.limit_key`` so clients get a consistent contract. Mirrors
``app.services.campaign_planner.limits``.
"""
from __future__ import annotations

from app.services.measurement.errors import (
    LimitExceededError,
    RefreshRateLimitedError,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
MAX_PUBLICATIONS_PER_INGESTION_RUN = 50
MAX_SNAPSHOTS_PER_PUBLICATION_PER_DAY = 48
MAX_METRIC_VALUES_PER_SNAPSHOT = 64

# ---------------------------------------------------------------------------
# Analytics / query surface
# ---------------------------------------------------------------------------
MAX_ANALYTICS_DATE_RANGE_DAYS = 366
MAX_GROUP_CARDINALITY = 50

# ---------------------------------------------------------------------------
# Refresh (manual on-demand collection) rate limiting
# ---------------------------------------------------------------------------
MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR = 30

# ---------------------------------------------------------------------------
# Baselines / benchmarking
# ---------------------------------------------------------------------------
MAX_BASELINE_LOOKBACK_DAYS = 90
MIN_BASELINE_SAMPLE_SIZE = 5

# ---------------------------------------------------------------------------
# Tracked links
# ---------------------------------------------------------------------------
MAX_TRACKED_LINKS = 500

__all__ = [
    "MAX_PUBLICATIONS_PER_INGESTION_RUN",
    "MAX_SNAPSHOTS_PER_PUBLICATION_PER_DAY",
    "MAX_METRIC_VALUES_PER_SNAPSHOT",
    "MAX_ANALYTICS_DATE_RANGE_DAYS",
    "MAX_GROUP_CARDINALITY",
    "MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR",
    "MAX_BASELINE_LOOKBACK_DAYS",
    "MIN_BASELINE_SAMPLE_SIZE",
    "MAX_TRACKED_LINKS",
    "enforce",
    "enforce_child_count",
    "enforce_rate_limit",
    "require",
]


def enforce(count: int, maximum: int, limit_key: str) -> None:
    if count > maximum:
        raise LimitExceededError(
            f"{limit_key} limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "requested": count},
        )


def enforce_child_count(existing: int, maximum: int, limit_key: str) -> None:
    """Guard before inserting one more child row."""
    if existing + 1 > maximum:
        raise LimitExceededError(
            f"{limit_key} limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "existing": existing},
        )


def enforce_rate_limit(count_in_window: int, maximum: int, limit_key: str) -> None:
    if count_in_window >= maximum:
        raise RefreshRateLimitedError(
            f"{limit_key} rate limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "count_in_window": count_in_window},
        )


def require(condition: bool, message: str, *, field: str | None = None) -> None:
    if not condition:
        details = {"field": field} if field else None
        raise ValidationError(message, details=details)
