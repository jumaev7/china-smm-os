"""Normalize provider-native advertising metrics into catalog metrics.

Two guarantees:
- The original ``provider_metric_key`` is always preserved on the normalized
  value, so raw provider semantics are never lost.
- Derived metrics (ctr, cpc, cpm, cpa, roas, frequency, link_ctr) are computed
  from contributor metrics using the catalog's named formulas. A missing or
  zero denominator yields **no** derived value (never an interpolated one).

Money stays in integer minor units + explicit currency; cost ratios inherit the
currency of their spend contributor.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.services.advertising_intelligence.metric_catalog import (
    METRIC_CATALOG,
    normalize_action_category,
    reverse_provider_mapping,
)
from app.services.advertising_intelligence.schemas import (
    NormalizedMetricValue,
    ProviderConversion,
    ProviderMetric,
)


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def normalize_provider_metrics(
    metrics: list[ProviderMetric],
    provider: str,
    *,
    default_currency: str | None = None,
) -> list[NormalizedMetricValue]:
    """Map raw provider metrics to normalized values and append derived metrics."""
    reverse = reverse_provider_mapping(provider)
    normalized: list[NormalizedMetricValue] = []
    raw_values: dict[str, Decimal] = {}
    spend_currency: str | None = default_currency

    for pm in metrics:
        value = _to_decimal(pm.value)
        if value is None:
            continue
        metric_key = reverse.get(pm.provider_metric_key)
        if metric_key is not None:
            definition = METRIC_CATALOG.get(metric_key)
            aggregation_type = definition.aggregation_type if definition else "interval"
            value_type = definition.value_type if definition else pm.value_type
            currency = pm.currency or (default_currency if value_type == "currency_minor" else None)
            if metric_key == "spend_minor" and pm.currency:
                spend_currency = pm.currency
            raw_values[metric_key] = value
            normalized.append(
                NormalizedMetricValue(
                    metric_key=metric_key,
                    provider_metric_key=pm.provider_metric_key,
                    value=value,
                    value_type=value_type,
                    aggregation_type=aggregation_type,
                    normalization_status="normalized",
                    currency=currency,
                )
            )
        else:
            normalized.append(
                NormalizedMetricValue(
                    metric_key=pm.provider_metric_key,
                    provider_metric_key=pm.provider_metric_key,
                    value=value,
                    value_type=pm.value_type,
                    aggregation_type="interval",
                    normalization_status="provider_native",
                    currency=pm.currency,
                )
            )

    normalized.extend(_compute_derived(raw_values, spend_currency))
    return normalized


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _compute_derived(raw: dict[str, Decimal], spend_currency: str | None) -> list[NormalizedMetricValue]:
    impressions = raw.get("impressions")
    clicks = raw.get("clicks")
    link_clicks = raw.get("link_clicks")
    reach = raw.get("reach")
    spend = raw.get("spend_minor")
    conversions = raw.get("conversions")
    conversion_value = raw.get("conversion_value_minor")

    derived_specs: list[tuple[str, Decimal | None, str | None]] = [
        ("ctr", _ratio(clicks, impressions), None),
        ("link_ctr", _ratio(link_clicks, impressions), None),
        ("frequency", _ratio(impressions, reach), None),
        ("cpc_minor", _ratio(spend, clicks), spend_currency),
        (
            "cpm_minor",
            (_ratio(spend, impressions) * Decimal(1000)) if _ratio(spend, impressions) is not None else None,
            spend_currency,
        ),
        ("cpa_minor", _ratio(spend, conversions), spend_currency),
        ("roas", _ratio(conversion_value, spend), None),
    ]

    out: list[NormalizedMetricValue] = []
    for metric_key, value, currency in derived_specs:
        if value is None:
            continue
        definition = METRIC_CATALOG.get(metric_key)
        value_type = definition.value_type if definition else "ratio"
        out.append(
            NormalizedMetricValue(
                metric_key=metric_key,
                provider_metric_key=None,
                value=value,
                value_type=value_type,
                aggregation_type="derived",
                normalization_status="derived",
                currency=currency if value_type == "currency_minor" else None,
                metadata={"formula": definition.formula} if definition and definition.formula else {},
            )
        )
    return out


def compute_derived_from_raw(
    raw: dict[str, Decimal],
    *,
    spend_currency: str | None = None,
) -> list[NormalizedMetricValue]:
    """Public helper: compute derived metrics from a raw ``{key: Decimal}`` map.

    Used by aggregate roll-ups (e.g. creative-level) that sum raw contributor
    metrics and then re-derive ratios rather than averaging ratios.
    """
    return _compute_derived(raw, spend_currency)


def normalize_conversions(
    conversions: list[ProviderConversion],
    *,
    default_currency: str | None = None,
) -> list[dict]:
    """Normalize provider conversions, preserving the raw action type.

    Returns plain dicts ready to persist as ``TenantAdConversionBreakdown`` rows;
    each carries the original ``action_type`` plus a coarse ``action_category``.
    """
    out: list[dict] = []
    for conv in conversions:
        value = _to_decimal(conv.value)
        if value is None:
            continue
        out.append(
            {
                "action_type": conv.action_type,
                "action_category": normalize_action_category(conv.action_type),
                "action_destination": conv.action_destination,
                "attribution_setting": conv.attribution_setting,
                "conversion_window": conv.conversion_window,
                "value": value,
                "value_type": conv.value_type,
                "currency": conv.currency or (default_currency if conv.value_type == "currency_minor" else None),
            }
        )
    return out


__all__ = [
    "normalize_provider_metrics",
    "normalize_conversions",
]
