"""Versioned normalized advertising metric catalog.

Design rules (do not violate without bumping ``METRIC_SEMANTICS_VERSION``):

- ``clicks`` (all clicks) and ``link_clicks`` (outbound link clicks) are never
  conflated — different providers scope "click" differently.
- ``impressions`` (every render, repeats included) and ``reach`` (distinct
  people) are never conflated.
- ``conversions`` here always means provider-reported conversions. They are
  NEVER treated as CRM-confirmed outcomes — CRM reconciliation is a separate,
  explicit step (see ``conversion_reconciliation``).
- Spend/currency metrics carry ``currency_behavior="currency"`` and are stored
  in **minor units**; they must never be summed across differing currencies.
- Derived ratios (ctr, cpc, cpm, cpa, roas, frequency) are computed from
  contributor metrics with a named, versioned formula. A missing/zero
  denominator yields ``None`` — never an interpolated value. Cost ratios use
  ``direction="lower_is_better"``.
- Only metrics with broadly consistent provider definitions are marked
  ``cross_provider_comparable`` and even then comparisons carry caveats.
"""
from __future__ import annotations

from app.models.advertising import AD_METRIC_SEMANTICS_VERSION
from app.services.advertising_intelligence.schemas import AdMetricDefinition

METRIC_SEMANTICS_VERSION = AD_METRIC_SEMANTICS_VERSION
CATALOG_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Raw (non-derived) metrics — provider-reported directly.
# ---------------------------------------------------------------------------

_RAW_DEFINITIONS: tuple[AdMetricDefinition, ...] = (
    AdMetricDefinition(
        metric_key="spend_minor",
        value_type="currency_minor",
        aggregation_type="interval",
        currency_behavior="currency",
        cross_provider_comparable=False,
        direction="neutral",
        provider_mappings={"mock": "spend_minor", "meta": "spend"},
        description_key="ad_metric.spend_minor",
        unit="minor_currency_unit",
        comparability_caveat="Spend is currency-specific and must not be summed across currencies.",
    ),
    AdMetricDefinition(
        metric_key="impressions",
        value_type="count",
        aggregation_type="interval",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": "impressions", "meta": "impressions"},
        description_key="ad_metric.impressions",
        comparability_caveat="Impression counting (repeat views, sampling) differs by provider.",
    ),
    AdMetricDefinition(
        metric_key="reach",
        value_type="count",
        aggregation_type="point_in_time",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": "reach", "meta": "reach"},
        description_key="ad_metric.reach",
        comparability_caveat="Distinct-people estimation methodology differs by provider; reach is not additive across windows.",
    ),
    AdMetricDefinition(
        metric_key="clicks",
        value_type="count",
        aggregation_type="interval",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": "clicks", "meta": "clicks"},
        description_key="ad_metric.clicks",
        comparability_caveat="'Click' scope (any element vs. link-only) differs by provider.",
    ),
    AdMetricDefinition(
        metric_key="link_clicks",
        value_type="count",
        aggregation_type="interval",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": "link_clicks", "meta": "inline_link_clicks"},
        description_key="ad_metric.link_clicks",
        comparability_caveat="Outbound link clicks only — distinct from all clicks.",
    ),
    AdMetricDefinition(
        metric_key="video_views",
        value_type="count",
        aggregation_type="interval",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": "video_views", "meta": "video_play_actions"},
        description_key="ad_metric.video_views",
        comparability_caveat="Minimum watch-time threshold to count a 'view' differs by provider.",
    ),
    AdMetricDefinition(
        metric_key="video_thruplays",
        value_type="count",
        aggregation_type="interval",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": "video_thruplays", "meta": "video_thruplay_watched_actions"},
        description_key="ad_metric.video_thruplays",
    ),
    AdMetricDefinition(
        metric_key="conversions",
        value_type="count",
        aggregation_type="interval",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        direction="higher_is_better",
        provider_mappings={"mock": "conversions", "meta": "conversions"},
        description_key="ad_metric.conversions",
        comparability_caveat="Provider-reported conversions — NOT CRM-confirmed; reconcile separately.",
    ),
    AdMetricDefinition(
        metric_key="conversion_value_minor",
        value_type="currency_minor",
        aggregation_type="interval",
        currency_behavior="currency",
        cross_provider_comparable=False,
        direction="neutral",
        provider_mappings={"mock": "conversion_value_minor", "meta": "conversion_values"},
        description_key="ad_metric.conversion_value_minor",
        unit="minor_currency_unit",
        comparability_caveat="Provider-attributed value in minor units; currency-specific, not summable across currencies.",
    ),
)


# ---------------------------------------------------------------------------
# Derived metrics — never stored raw; always computed from contributors.
# ---------------------------------------------------------------------------

_DERIVED_DEFINITIONS: tuple[AdMetricDefinition, ...] = (
    AdMetricDefinition(
        metric_key="ctr",
        value_type="ratio",
        aggregation_type="derived",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": None, "meta": None},
        description_key="ad_metric.ctr",
        formula="clicks / impressions",
        numerator_metric="clicks",
        denominator_metric="impressions",
    ),
    AdMetricDefinition(
        metric_key="link_ctr",
        value_type="ratio",
        aggregation_type="derived",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        provider_mappings={"mock": None, "meta": None},
        description_key="ad_metric.link_ctr",
        formula="link_clicks / impressions",
        numerator_metric="link_clicks",
        denominator_metric="impressions",
    ),
    AdMetricDefinition(
        metric_key="frequency",
        value_type="ratio",
        aggregation_type="derived",
        currency_behavior="currency_free",
        cross_provider_comparable=False,
        direction="neutral",
        provider_mappings={"mock": None, "meta": None},
        description_key="ad_metric.frequency",
        formula="impressions / reach",
        numerator_metric="impressions",
        denominator_metric="reach",
    ),
    AdMetricDefinition(
        metric_key="cpc_minor",
        value_type="currency_minor",
        aggregation_type="derived",
        currency_behavior="currency_ratio",
        cross_provider_comparable=False,
        direction="lower_is_better",
        provider_mappings={"mock": None, "meta": None},
        description_key="ad_metric.cpc_minor",
        formula="spend_minor / clicks",
        numerator_metric="spend_minor",
        denominator_metric="clicks",
        unit="minor_currency_unit",
    ),
    AdMetricDefinition(
        metric_key="cpm_minor",
        value_type="currency_minor",
        aggregation_type="derived",
        currency_behavior="currency_ratio",
        cross_provider_comparable=False,
        direction="lower_is_better",
        provider_mappings={"mock": None, "meta": None},
        description_key="ad_metric.cpm_minor",
        formula="(spend_minor / impressions) * 1000",
        numerator_metric="spend_minor",
        denominator_metric="impressions",
        unit="minor_currency_unit",
    ),
    AdMetricDefinition(
        metric_key="cpa_minor",
        value_type="currency_minor",
        aggregation_type="derived",
        currency_behavior="currency_ratio",
        cross_provider_comparable=False,
        direction="lower_is_better",
        provider_mappings={"mock": None, "meta": None},
        description_key="ad_metric.cpa_minor",
        formula="spend_minor / conversions",
        numerator_metric="spend_minor",
        denominator_metric="conversions",
        unit="minor_currency_unit",
        comparability_caveat="Cost per provider-reported conversion — not per CRM-confirmed outcome.",
    ),
    AdMetricDefinition(
        metric_key="roas",
        value_type="ratio",
        aggregation_type="derived",
        currency_behavior="currency_ratio",
        cross_provider_comparable=False,
        direction="higher_is_better",
        provider_mappings={"mock": None, "meta": None},
        description_key="ad_metric.roas",
        formula="conversion_value_minor / spend_minor",
        numerator_metric="conversion_value_minor",
        denominator_metric="spend_minor",
        comparability_caveat="Uses provider-attributed value; valid only within a single currency.",
    ),
)


METRIC_CATALOG: dict[str, AdMetricDefinition] = {
    d.metric_key: d for d in (*_RAW_DEFINITIONS, *_DERIVED_DEFINITIONS)
}

RAW_METRIC_KEYS = frozenset(d.metric_key for d in _RAW_DEFINITIONS)
DERIVED_METRIC_KEYS = frozenset(d.metric_key for d in _DERIVED_DEFINITIONS)
ALL_METRIC_KEYS = frozenset(METRIC_CATALOG.keys())
CURRENCY_METRIC_KEYS = frozenset(
    key for key, d in METRIC_CATALOG.items()
    if d.currency_behavior in {"currency", "currency_ratio"}
)
CROSS_PROVIDER_COMPARABLE_KEYS = frozenset(
    key for key, d in METRIC_CATALOG.items() if d.cross_provider_comparable
)

# Normalized conversion action categories (provider action types map into these,
# but the raw provider_action_type is always preserved alongside).
CONVERSION_ACTION_CATEGORIES = frozenset({
    "purchase",
    "lead",
    "complete_registration",
    "add_to_cart",
    "initiate_checkout",
    "add_payment_info",
    "subscribe",
    "contact",
    "landing_page_view",
    "link_click",
    "other",
})

# Human-readable descriptions keyed by ``description_key`` (kept separate so
# copy changes do not bump METRIC_SEMANTICS_VERSION).
METRIC_DESCRIPTIONS: dict[str, str] = {
    "ad_metric.spend_minor": "Amount spent, in minor currency units, for the entity and window.",
    "ad_metric.impressions": "Number of times ads were on screen, including repeats.",
    "ad_metric.reach": "Estimated number of distinct people who saw the ads (not additive across windows).",
    "ad_metric.clicks": "All clicks on the ad, of any type.",
    "ad_metric.link_clicks": "Clicks specifically on outbound links in the ad.",
    "ad_metric.video_views": "Number of video plays meeting the provider's view threshold.",
    "ad_metric.video_thruplays": "Number of ThruPlays / completed-enough video plays as defined by the provider.",
    "ad_metric.conversions": "Provider-reported conversions (not CRM-confirmed).",
    "ad_metric.conversion_value_minor": "Provider-attributed conversion value, in minor currency units.",
    "ad_metric.ctr": "Click-through rate: clicks divided by impressions.",
    "ad_metric.link_ctr": "Outbound link click-through rate: link_clicks divided by impressions.",
    "ad_metric.frequency": "Average impressions per person: impressions divided by reach.",
    "ad_metric.cpc_minor": "Cost per click, in minor currency units.",
    "ad_metric.cpm_minor": "Cost per 1,000 impressions, in minor currency units.",
    "ad_metric.cpa_minor": "Cost per provider-reported conversion, in minor currency units.",
    "ad_metric.roas": "Return on ad spend: provider-attributed conversion value divided by spend.",
}


def get_metric_definition(metric_key: str) -> AdMetricDefinition | None:
    return METRIC_CATALOG.get(metric_key)


def get_description(metric_key: str) -> str | None:
    definition = METRIC_CATALOG.get(metric_key)
    if definition is None:
        return None
    return METRIC_DESCRIPTIONS.get(definition.description_key)


def provider_key_for(metric_key: str, provider: str) -> str | None:
    definition = METRIC_CATALOG.get(metric_key)
    if definition is None:
        return None
    return definition.provider_mappings.get(provider)


def reverse_provider_mapping(provider: str) -> dict[str, str]:
    """Provider-native metric key -> normalized catalog key, for one provider."""
    mapping: dict[str, str] = {}
    for key, definition in METRIC_CATALOG.items():
        provider_key = definition.provider_mappings.get(provider)
        if provider_key:
            mapping[provider_key] = key
    return mapping


def supported_metric_keys_for(provider: str) -> frozenset[str]:
    return frozenset(
        key for key, d in METRIC_CATALOG.items()
        if d.provider_mappings.get(provider) is not None
    )


def normalize_action_category(provider_action_type: str) -> str:
    """Map a provider action type into a normalized conversion category.

    The provider action type is ALWAYS preserved verbatim by callers; this only
    provides a coarse category for grouping. Unknown types fall back to "other".
    """
    text = (provider_action_type or "").lower()
    # Order matters: check more specific tokens first.
    if "purchase" in text:
        return "purchase"
    if "add_payment_info" in text:
        return "add_payment_info"
    if "initiate_checkout" in text or "initiatecheckout" in text:
        return "initiate_checkout"
    if "add_to_cart" in text or "addtocart" in text:
        return "add_to_cart"
    if "complete_registration" in text or "completeregistration" in text:
        return "complete_registration"
    if "subscribe" in text:
        return "subscribe"
    if "lead" in text:
        return "lead"
    if "contact" in text:
        return "contact"
    if "landing_page_view" in text or "landingpageview" in text:
        return "landing_page_view"
    if "link_click" in text:
        return "link_click"
    return "other"


__all__ = [
    "METRIC_SEMANTICS_VERSION",
    "CATALOG_VERSION",
    "METRIC_CATALOG",
    "RAW_METRIC_KEYS",
    "DERIVED_METRIC_KEYS",
    "ALL_METRIC_KEYS",
    "CURRENCY_METRIC_KEYS",
    "CROSS_PROVIDER_COMPARABLE_KEYS",
    "CONVERSION_ACTION_CATEGORIES",
    "METRIC_DESCRIPTIONS",
    "get_metric_definition",
    "get_description",
    "provider_key_for",
    "reverse_provider_mapping",
    "supported_metric_keys_for",
    "normalize_action_category",
]
