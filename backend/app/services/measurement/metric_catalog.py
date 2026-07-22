"""Versioned normalized metric catalog for Marketing Intelligence Phase 2.

Design rules (do not violate without bumping ``METRIC_SEMANTICS_VERSION``):

- ``impressions`` and ``reach`` are never conflated. Impressions count every
  view (repeats included); reach counts distinct accounts/viewers. Providers
  that only expose one of the two must NOT populate the other.
- Only metrics with broadly consistent provider definitions are marked
  ``cross_platform_comparable`` — and even then, comparisons carry caveats
  (different audience bases, different UI surfaces for "like"/"react", etc).
  Impressions/reach/views/clicks are NOT marked comparable because provider
  counting methodologies diverge too much (sampling, bot filtering, unique
  windows) to be safely compared platform-to-platform.
- Derived metrics (``engagements``, rates, averages) are never stored as raw
  provider values; they are always computed from contributor metrics with a
  named, versioned formula. A missing/zero denominator yields ``None`` — never
  an interpolated or assumed value.
"""
from __future__ import annotations

from app.services.measurement.schemas import MetricDefinition

CATALOG_VERSION = "1.0.0"


def _mock_identity(*keys: str) -> dict[str, str]:
    """Mock provider mirrors catalog keys 1:1 (deterministic, full support)."""
    return {key: key for key in keys}


# ---------------------------------------------------------------------------
# Raw (non-derived) metrics
# ---------------------------------------------------------------------------

_RAW_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        key="impressions",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "impressions",
            "telegram": None,
            "facebook": "post_impressions",
        },
        description_key="metric.impressions",
        comparability_caveat="Impression counting (repeat views, sampling) differs by provider.",
    ),
    MetricDefinition(
        key="reach",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "reach",
            "telegram": None,
            "facebook": "post_impressions_unique",
        },
        description_key="metric.reach",
        comparability_caveat="Distinct-viewer estimation methodology differs by provider.",
    ),
    MetricDefinition(
        key="views",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "views",
            "telegram": "views",
            "facebook": "post_impressions",
        },
        description_key="metric.views",
        comparability_caveat="Some providers count a 'view' as any impression; others require dwell time.",
    ),
    MetricDefinition(
        key="video_views",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "video_views",
            "telegram": None,
            "facebook": "post_video_views",
        },
        description_key="metric.video_views",
        comparability_caveat="Minimum watch-time threshold to count as a 'view' differs by provider.",
    ),
    MetricDefinition(
        key="reactions",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "reactions",
            "telegram": "reactions",
            "facebook": "post_reactions_by_type_total",
        },
        description_key="metric.reactions",
        comparability_caveat="'Reaction' taxonomies (like/love/haha/etc.) differ by platform.",
    ),
    MetricDefinition(
        key="likes",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=True,
        provider_mappings={
            "mock": "likes",
            "telegram": None,
            "facebook": "post_reactions_like_total",
        },
        description_key="metric.likes",
        comparability_caveat="Comparable in kind, but audience size/composition still differs by platform.",
    ),
    MetricDefinition(
        key="comments",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=True,
        provider_mappings={
            "mock": "comments",
            "telegram": None,
            "facebook": "post_comments",
        },
        description_key="metric.comments",
        comparability_caveat="Comparable in kind, but comment UI prominence differs by platform.",
    ),
    MetricDefinition(
        key="shares",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=True,
        provider_mappings={
            "mock": "shares",
            "telegram": None,
            "facebook": "post_shares",
        },
        description_key="metric.shares",
        comparability_caveat="Comparable in kind (share/forward/repost), but reach-per-share differs by platform.",
    ),
    MetricDefinition(
        key="saves",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=True,
        provider_mappings={
            "mock": "saves",
            "telegram": None,
            "facebook": None,
        },
        description_key="metric.saves",
        comparability_caveat="Not all platforms surface a 'save' action; absence does not imply zero saves.",
    ),
    MetricDefinition(
        key="clicks",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "clicks",
            "telegram": None,
            "facebook": "post_clicks",
        },
        description_key="metric.clicks",
        comparability_caveat="'Click' scope (any element vs. link-only) differs by provider.",
    ),
    MetricDefinition(
        key="link_clicks",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "link_clicks",
            "telegram": None,
            "facebook": "post_clicks_link_clicks",
        },
        description_key="metric.link_clicks",
    ),
    MetricDefinition(
        key="profile_visits",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "profile_visits",
            "telegram": None,
            "facebook": None,
        },
        description_key="metric.profile_visits",
    ),
    MetricDefinition(
        key="follows",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "follows",
            "telegram": None,
            "facebook": None,
        },
        description_key="metric.follows",
    ),
    MetricDefinition(
        key="watch_time_seconds",
        value_type="duration_seconds",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "watch_time_seconds",
            "telegram": None,
            "facebook": None,
        },
        description_key="metric.watch_time_seconds",
        unit="seconds",
    ),
    MetricDefinition(
        key="completion_count",
        value_type="count",
        aggregation_type="cumulative",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={
            "mock": "completion_count",
            "telegram": None,
            "facebook": "post_video_complete_views_30s",
        },
        description_key="metric.completion_count",
    ),
)

# ---------------------------------------------------------------------------
# Derived metrics — never stored raw; always computed from contributors.
# ---------------------------------------------------------------------------

_DERIVED_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        key="engagements",
        value_type="count",
        aggregation_type="derived",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={"mock": None, "telegram": None, "facebook": None},
        description_key="metric.engagements",
        derived_from=("likes", "comments", "shares", "saves"),
        comparability_caveat="Sum of whichever contributor metrics the provider actually exposes.",
    ),
    MetricDefinition(
        key="average_watch_time_seconds",
        value_type="duration_seconds",
        aggregation_type="derived",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={"mock": None, "telegram": None, "facebook": None},
        description_key="metric.average_watch_time_seconds",
        unit="seconds",
        derived_from=("watch_time_seconds", "views"),
    ),
    MetricDefinition(
        key="completion_rate",
        value_type="ratio",
        aggregation_type="derived",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={"mock": None, "telegram": None, "facebook": None},
        description_key="metric.completion_rate",
        derived_from=("completion_count", "views"),
    ),
    MetricDefinition(
        key="engagement_rate_by_impressions",
        value_type="ratio",
        aggregation_type="derived",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={"mock": None, "telegram": None, "facebook": None},
        description_key="metric.engagement_rate_by_impressions",
        derived_from=("engagements", "impressions"),
    ),
    MetricDefinition(
        key="engagement_rate_by_reach",
        value_type="ratio",
        aggregation_type="derived",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={"mock": None, "telegram": None, "facebook": None},
        description_key="metric.engagement_rate_by_reach",
        derived_from=("engagements", "reach"),
    ),
    MetricDefinition(
        key="click_through_rate",
        value_type="ratio",
        aggregation_type="derived",
        higher_is_better=True,
        cross_platform_comparable=False,
        provider_mappings={"mock": None, "telegram": None, "facebook": None},
        description_key="metric.click_through_rate",
        derived_from=("link_clicks", "clicks", "impressions"),
    ),
)

METRIC_CATALOG: dict[str, MetricDefinition] = {
    d.key: d for d in (*_RAW_DEFINITIONS, *_DERIVED_DEFINITIONS)
}

RAW_METRIC_KEYS = frozenset(d.key for d in _RAW_DEFINITIONS)
DERIVED_METRIC_KEYS = frozenset(d.key for d in _DERIVED_DEFINITIONS)
ALL_METRIC_KEYS = frozenset(METRIC_CATALOG.keys())

CROSS_PLATFORM_COMPARABLE_KEYS = frozenset(
    key for key, d in METRIC_CATALOG.items() if d.cross_platform_comparable
)

# Human-readable descriptions keyed by ``description_key`` (used by the API /
# explanation layer; kept separate from the catalog so copy changes don't
# bump METRIC_SEMANTICS_VERSION).
METRIC_DESCRIPTIONS: dict[str, str] = {
    "metric.impressions": "Total number of times the publication was displayed, including repeats.",
    "metric.reach": "Estimated number of distinct accounts/viewers that saw the publication.",
    "metric.views": "Number of times the publication content was viewed.",
    "metric.video_views": "Number of times video content met the provider's view threshold.",
    "metric.reactions": "Total reactions of any kind (like, love, etc.) on the publication.",
    "metric.likes": "Number of 'like' reactions on the publication.",
    "metric.comments": "Number of comments/replies on the publication.",
    "metric.shares": "Number of times the publication was shared, reposted, or forwarded.",
    "metric.saves": "Number of times viewers saved/bookmarked the publication.",
    "metric.clicks": "Number of clicks on any interactive element of the publication.",
    "metric.link_clicks": "Number of clicks specifically on outbound links in the publication.",
    "metric.profile_visits": "Number of profile/page visits attributed to the publication.",
    "metric.follows": "Number of new follows attributed to the publication.",
    "metric.watch_time_seconds": "Total cumulative watch time in seconds across all viewers.",
    "metric.completion_count": "Number of views that reached the provider's completion threshold.",
    "metric.engagements": "Sum of likes, comments, shares, and saves available for this publication.",
    "metric.average_watch_time_seconds": "Average watch time per view (watch_time_seconds / views).",
    "metric.completion_rate": "Share of views that reached completion (completion_count / views).",
    "metric.engagement_rate_by_impressions": "Engagements divided by impressions.",
    "metric.engagement_rate_by_reach": "Engagements divided by reach.",
    "metric.click_through_rate": "Link clicks (or clicks) divided by impressions.",
}


def get_metric_definition(metric_key: str) -> MetricDefinition | None:
    return METRIC_CATALOG.get(metric_key)


def get_description(metric_key: str) -> str | None:
    definition = METRIC_CATALOG.get(metric_key)
    if definition is None:
        return None
    return METRIC_DESCRIPTIONS.get(definition.description_key)


def provider_key_for(metric_key: str, platform: str) -> str | None:
    definition = METRIC_CATALOG.get(metric_key)
    if definition is None:
        return None
    return definition.provider_mappings.get(platform)


def reverse_provider_mapping(platform: str) -> dict[str, str]:
    """Provider-native key -> normalized catalog key, for one platform."""
    mapping: dict[str, str] = {}
    for key, definition in METRIC_CATALOG.items():
        provider_key = definition.provider_mappings.get(platform)
        if provider_key:
            mapping[provider_key] = key
    return mapping


def supported_metric_keys_for(platform: str) -> frozenset[str]:
    return frozenset(
        key for key, d in METRIC_CATALOG.items()
        if d.provider_mappings.get(platform) is not None
    )


__all__ = [
    "CATALOG_VERSION",
    "METRIC_CATALOG",
    "RAW_METRIC_KEYS",
    "DERIVED_METRIC_KEYS",
    "ALL_METRIC_KEYS",
    "CROSS_PLATFORM_COMPARABLE_KEYS",
    "METRIC_DESCRIPTIONS",
    "get_metric_definition",
    "get_description",
    "provider_key_for",
    "reverse_provider_mapping",
    "supported_metric_keys_for",
]
