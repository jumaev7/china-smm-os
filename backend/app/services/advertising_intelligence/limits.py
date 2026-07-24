"""Deterministic advertising limits with stable error codes.

All limits are server-controlled. Exceeding a limit raises an
``AdvertisingError`` subclass carrying a stable ``details.limit_key`` so clients
get a consistent contract. Mirrors ``app.services.measurement.limits``.
"""
from __future__ import annotations

from app.services.advertising_intelligence.errors import (
    AdInvalidBreakdownError,
    AdInvalidDateRangeError,
    AdRefreshRateLimitedError,
    AdvertisingError,
)

# ---------------------------------------------------------------------------
# Structural import
# ---------------------------------------------------------------------------
MAX_ACCOUNTS_PER_TENANT = 25
MAX_CAMPAIGNS_PER_IMPORT_RUN = 500
MAX_AD_GROUPS_PER_IMPORT_RUN = 2000
MAX_ADS_PER_IMPORT_RUN = 5000
MAX_CREATIVES_PER_IMPORT_RUN = 5000
MAX_ENTITIES_PER_IMPORT_RUN = 10000

# ---------------------------------------------------------------------------
# Insights / metric ingestion
# ---------------------------------------------------------------------------
MAX_ENTITIES_PER_INGESTION_RUN = 1000
MAX_METRIC_VALUES_PER_SNAPSHOT = 128
MAX_CONVERSION_BREAKDOWNS_PER_SNAPSHOT = 128
MAX_SNAPSHOTS_PER_ENTITY_PER_DAY = 24

# ---------------------------------------------------------------------------
# Analytics / query surface
# ---------------------------------------------------------------------------
MAX_ANALYTICS_DATE_RANGE_DAYS = 366
MAX_INSIGHTS_LOOKBACK_DAYS = 730
MAX_GROUP_CARDINALITY = 100
MAX_BREAKDOWNS_PER_QUERY = 3

# Provider-supported breakdown dimensions (Phase 1). Requesting anything else
# raises ``AdInvalidBreakdownError``.
SUPPORTED_BREAKDOWNS = frozenset({
    "age",
    "gender",
    "country",
    "region",
    "publisher_platform",
    "platform_position",
    "device_platform",
    "impression_device",
})

# ---------------------------------------------------------------------------
# Refresh (manual on-demand collection) rate limiting
# ---------------------------------------------------------------------------
MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR = 20
MAX_IMPORT_REQUESTS_PER_ACCOUNT_PER_HOUR = 6

# ---------------------------------------------------------------------------
# Freshness thresholds (seconds)
# ---------------------------------------------------------------------------
FRESH_MAX_AGE_SECONDS = 6 * 3600          # <= 6h -> fresh
AGING_MAX_AGE_SECONDS = 24 * 3600         # <= 24h -> aging, else stale

# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------
MAX_CREATIVE_LINKS_PER_CREATIVE = 25
MAX_CAMPAIGN_LINKS_PER_AD_CAMPAIGN = 10

__all__ = [
    "MAX_ACCOUNTS_PER_TENANT",
    "MAX_CAMPAIGNS_PER_IMPORT_RUN",
    "MAX_AD_GROUPS_PER_IMPORT_RUN",
    "MAX_ADS_PER_IMPORT_RUN",
    "MAX_CREATIVES_PER_IMPORT_RUN",
    "MAX_ENTITIES_PER_IMPORT_RUN",
    "MAX_ENTITIES_PER_INGESTION_RUN",
    "MAX_METRIC_VALUES_PER_SNAPSHOT",
    "MAX_CONVERSION_BREAKDOWNS_PER_SNAPSHOT",
    "MAX_SNAPSHOTS_PER_ENTITY_PER_DAY",
    "MAX_ANALYTICS_DATE_RANGE_DAYS",
    "MAX_INSIGHTS_LOOKBACK_DAYS",
    "MAX_GROUP_CARDINALITY",
    "MAX_BREAKDOWNS_PER_QUERY",
    "SUPPORTED_BREAKDOWNS",
    "MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR",
    "MAX_IMPORT_REQUESTS_PER_ACCOUNT_PER_HOUR",
    "FRESH_MAX_AGE_SECONDS",
    "AGING_MAX_AGE_SECONDS",
    "MAX_CREATIVE_LINKS_PER_CREATIVE",
    "MAX_CAMPAIGN_LINKS_PER_AD_CAMPAIGN",
    "enforce",
    "enforce_child_count",
    "enforce_rate_limit",
    "enforce_date_range",
    "enforce_breakdowns",
]


def enforce(count: int, maximum: int, limit_key: str) -> None:
    if count > maximum:
        raise AdvertisingError(
            f"{limit_key} limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "requested": count},
        )


def enforce_child_count(existing: int, maximum: int, limit_key: str) -> None:
    """Guard before inserting one more child row."""
    if existing + 1 > maximum:
        raise AdvertisingError(
            f"{limit_key} limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "existing": existing},
        )


def enforce_rate_limit(count_in_window: int, maximum: int, limit_key: str) -> None:
    if count_in_window >= maximum:
        raise AdRefreshRateLimitedError(
            f"{limit_key} rate limit exceeded",
            details={"limit_key": limit_key, "max": maximum, "count_in_window": count_in_window},
        )


def enforce_date_range(days: int, *, maximum: int = MAX_ANALYTICS_DATE_RANGE_DAYS) -> None:
    if days <= 0:
        raise AdInvalidDateRangeError(
            "date range must be positive",
            details={"requested_days": days},
        )
    if days > maximum:
        raise AdInvalidDateRangeError(
            "date range exceeds maximum",
            details={"limit_key": "analytics_date_range_days", "max": maximum, "requested_days": days},
        )


def enforce_breakdowns(breakdowns: list[str]) -> None:
    if len(breakdowns) > MAX_BREAKDOWNS_PER_QUERY:
        raise AdInvalidBreakdownError(
            "too many breakdown dimensions",
            details={"max": MAX_BREAKDOWNS_PER_QUERY, "requested": len(breakdowns)},
        )
    unsupported = [b for b in breakdowns if b not in SUPPORTED_BREAKDOWNS]
    if unsupported:
        raise AdInvalidBreakdownError(
            "unsupported breakdown dimension(s)",
            details={"unsupported": unsupported, "supported": sorted(SUPPORTED_BREAKDOWNS)},
        )
