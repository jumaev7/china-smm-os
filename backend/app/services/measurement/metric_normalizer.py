"""Maps provider-native metric keys to normalized catalog metrics.

Provider-specific keys that have no catalog mapping are kept with
``normalization_status="provider_native"`` rather than dropped, so operators
retain visibility into everything a provider actually sent. Derived metrics
(``engagements``, rates, averages) are computed here whenever their
contributor metrics are available — never fabricated when contributors are
missing, and never interpolated.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models.measurement import METRIC_SEMANTICS_VERSION
from app.services.measurement.metric_catalog import METRIC_CATALOG, reverse_provider_mapping
from app.services.measurement.schemas import NormalizedMetricValue


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def normalize_provider_metrics(
    provider_metrics: dict[str, object],
    *,
    platform: str,
) -> list[NormalizedMetricValue]:
    """Normalize raw provider metrics and compute derived metrics.

    ``provider_metrics`` keys are provider-native (e.g. Facebook's
    ``post_impressions``, or already-catalog-shaped keys for the mock
    provider, which mirrors the catalog 1:1).
    """
    reverse_map = reverse_provider_mapping(platform)
    normalized: dict[str, NormalizedMetricValue] = {}
    provider_native: list[NormalizedMetricValue] = []

    for provider_key, raw_value in provider_metrics.items():
        value = _to_decimal(raw_value)
        if value is None:
            continue
        catalog_key = reverse_map.get(provider_key)
        if catalog_key is not None:
            definition = METRIC_CATALOG[catalog_key]
            normalized[catalog_key] = NormalizedMetricValue(
                metric_key=catalog_key,
                provider_metric_key=provider_key,
                value=value,
                value_type=definition.value_type,
                aggregation_type=definition.aggregation_type,
                normalization_status="normalized",
                metadata={"semantics_version": METRIC_SEMANTICS_VERSION},
            )
        else:
            provider_native.append(
                NormalizedMetricValue(
                    metric_key=f"provider:{platform}:{provider_key}",
                    provider_metric_key=provider_key,
                    value=value,
                    value_type="count",
                    aggregation_type="cumulative",
                    normalization_status="provider_native",
                    metadata={"platform": platform},
                )
            )

    derived = _compute_derived_metrics(normalized)

    return [*normalized.values(), *derived, *provider_native]


def _compute_derived_metrics(
    normalized: dict[str, NormalizedMetricValue],
) -> list[NormalizedMetricValue]:
    """Compute derived catalog metrics from whatever contributors exist.

    Every named formula documents its denominator; a zero or missing
    denominator always yields "no metric emitted" — never an interpolated
    or assumed value.
    """
    derived: list[NormalizedMetricValue] = []

    def _val(key: str) -> Decimal | None:
        item = normalized.get(key)
        return item.value if item is not None else None

    # engagements = sum of whichever of (likes, comments, shares, saves) are
    # present. At least one contributor must be present.
    contributor_keys = ("likes", "comments", "shares", "saves")
    contributors_present = [k for k in contributor_keys if _val(k) is not None]
    if contributors_present:
        engagements_value = sum((_val(k) or Decimal(0)) for k in contributors_present)
        definition = METRIC_CATALOG["engagements"]
        derived.append(
            NormalizedMetricValue(
                metric_key="engagements",
                provider_metric_key=None,
                value=engagements_value,
                value_type=definition.value_type,
                aggregation_type=definition.aggregation_type,
                normalization_status="derived",
                metadata={
                    "formula": "sum(likes, comments, shares, saves)",
                    "contributors_used": contributors_present,
                    "semantics_version": METRIC_SEMANTICS_VERSION,
                },
            )
        )
        engagements = engagements_value
    else:
        engagements = None

    def _ratio(
        metric_key: str,
        numerator: Decimal | None,
        denominator: Decimal | None,
        *,
        formula: str,
    ) -> None:
        if numerator is None or denominator is None or denominator == 0:
            return
        definition = METRIC_CATALOG[metric_key]
        value = numerator / denominator
        derived.append(
            NormalizedMetricValue(
                metric_key=metric_key,
                provider_metric_key=None,
                value=value,
                value_type=definition.value_type,
                aggregation_type=definition.aggregation_type,
                normalization_status="derived",
                metadata={"formula": formula, "semantics_version": METRIC_SEMANTICS_VERSION},
            )
        )

    _ratio(
        "engagement_rate_by_impressions", engagements, _val("impressions"),
        formula="engagements / impressions",
    )
    _ratio(
        "engagement_rate_by_reach", engagements, _val("reach"),
        formula="engagements / reach",
    )

    click_numerator = _val("link_clicks")
    click_formula = "link_clicks / impressions"
    if click_numerator is None:
        click_numerator = _val("clicks")
        click_formula = "clicks / impressions"
    _ratio(
        "click_through_rate", click_numerator, _val("impressions"),
        formula=click_formula,
    )

    _ratio(
        "completion_rate", _val("completion_count"), _val("views"),
        formula="completion_count / views",
    )
    _ratio(
        "average_watch_time_seconds", _val("watch_time_seconds"), _val("views"),
        formula="watch_time_seconds / views",
    )

    return derived


__all__ = ["normalize_provider_metrics"]
