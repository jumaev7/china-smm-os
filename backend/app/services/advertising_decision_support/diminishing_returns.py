"""Conservative historical diminishing-efficiency indicators.

Never claims causal diminishing returns. Wording stays cautious and historical.
Statuses: no_evidence | possible_diminishing_efficiency | stable | insufficient_data.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCampaign, TenantAdMetricAggregate
from app.models.advertising_decision_support import (
    DIMINISHING_RETURNS_ENGINE_VERSION,
    DIMINISHING_RETURN_STATUSES,
)
from app.services.advertising_decision_support.errors import AdEntityNotFoundError

# Prefer shorter windows as "higher intensity" proxies when available.
_WINDOW_ORDER = ("24h", "72h", "7d", "14d", "30d", "lifetime")
_MIN_BUCKETS = 3
# Relative efficiency drop threshold between higher-spend and lower-spend buckets.
_EFFICIENCY_DROP = Decimal("0.15")


def compute_diminishing_returns(
    buckets: list[dict[str, Any]],
    *,
    efficiency_key: str = "cpa_minor",
    direction: str = "lower_is_better",
) -> dict[str, Any]:
    """Pure indicator over spend/efficiency buckets.

    Each bucket: ``{window_key, spend_minor, efficiency}`` where efficiency is
    e.g. CPA (lower better) or ROAS (higher better).
    """
    usable = [
        b for b in buckets
        if b.get("spend_minor") is not None
        and b.get("efficiency") is not None
        and Decimal(str(b["spend_minor"])) > 0
    ]
    if len(usable) < _MIN_BUCKETS:
        return {
            "status": "insufficient_data",
            "observation": "Fewer than three comparable spend/efficiency windows are available.",
            "evidence": {"bucket_count": len(usable), "efficiency_key": efficiency_key},
            "interpretation": "A diminishing-efficiency indicator cannot be formed yet.",
            "possible_consideration": "Continue collecting windowed metrics before reviewing efficiency patterns.",
            "engine_version": DIMINISHING_RETURNS_ENGINE_VERSION,
            "read_only": True,
            "kind": "OBSERVED",
        }

    ranked = sorted(usable, key=lambda b: Decimal(str(b["spend_minor"])))
    low = ranked[: max(1, len(ranked) // 3)]
    high = ranked[-max(1, len(ranked) // 3) :]

    def _avg_eff(group: list[dict[str, Any]]) -> Decimal:
        vals = [Decimal(str(g["efficiency"])) for g in group]
        return sum(vals) / Decimal(len(vals))

    low_eff = _avg_eff(low)
    high_eff = _avg_eff(high)
    low_spend = sum(Decimal(str(g["spend_minor"])) for g in low) / Decimal(len(low))
    high_spend = sum(Decimal(str(g["spend_minor"])) for g in high) / Decimal(len(high))

    if low_eff == 0:
        status = "insufficient_data"
        observation = "Low-spend bucket efficiency is zero; comparison is not meaningful."
        interpretation = "Indicator withheld due to invalid efficiency baseline."
        consideration = "Verify efficiency metrics for lower-spend windows."
    else:
        if direction == "lower_is_better":
            # Higher CPA at higher spend → possible diminishing efficiency
            relative = (high_eff - low_eff) / abs(low_eff)
            worsened = relative >= _EFFICIENCY_DROP
        else:
            # Lower ROAS at higher spend → possible diminishing efficiency
            relative = (low_eff - high_eff) / abs(low_eff)
            worsened = relative >= _EFFICIENCY_DROP

        if worsened and high_spend > low_spend:
            status = "possible_diminishing_efficiency"
            observation = (
                "Historical observations show lower conversion efficiency during "
                "higher-spend periods."
            )
            interpretation = (
                "Windowed metrics are consistent with reduced efficiency at higher "
                "spend intensity. This is a historical pattern, not a causal claim."
            )
            consideration = (
                "Consider reviewing whether higher-spend windows coincide with "
                "other changes (audience, creative, seasonality) before adjusting plans."
            )
        elif abs(relative) < _EFFICIENCY_DROP:
            status = "stable"
            observation = (
                "Historical spend windows show broadly stable efficiency relative "
                "to the configured threshold."
            )
            interpretation = "No clear diminishing-efficiency pattern under current thresholds."
            consideration = "Continue monitoring as more comparable windows accumulate."
        else:
            status = "no_evidence"
            observation = (
                "Higher-spend windows do not show worse efficiency under the "
                "configured threshold."
            )
            interpretation = "No diminishing-efficiency signal from available windows."
            consideration = "No specific efficiency-pattern review is indicated by this indicator."

    assert status in DIMINISHING_RETURN_STATUSES
    return {
        "status": status,
        "observation": observation,
        "evidence": {
            "efficiency_key": efficiency_key,
            "direction": direction,
            "bucket_count": len(usable),
            "low_spend_avg_minor": str(low_spend),
            "high_spend_avg_minor": str(high_spend),
            "low_efficiency_avg": str(low_eff),
            "high_efficiency_avg": str(high_eff),
            "buckets": [
                {
                    "window_key": b.get("window_key"),
                    "spend_minor": int(b["spend_minor"]),
                    "efficiency": str(b["efficiency"]),
                }
                for b in ranked
            ],
        },
        "interpretation": interpretation,
        "possible_consideration": consideration,
        "engine_version": DIMINISHING_RETURNS_ENGINE_VERSION,
        "read_only": True,
        "kind": "OBSERVED",
        "disclaimer": (
            "This indicator describes historical co-occurrence only and does not "
            "claim that increasing budget will reduce efficiency."
        ),
    }


async def analyze_campaign_diminishing_returns(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
    *,
    efficiency_key: str = "cpa_minor",
) -> dict[str, Any]:
    """Load windowed aggregates for a campaign and compute the indicator."""
    campaign = (
        await db.execute(
            select(TenantAdCampaign).where(
                TenantAdCampaign.tenant_id == tenant_id,
                TenantAdCampaign.id == campaign_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise AdEntityNotFoundError(
            "advertising campaign not found",
            details={"entity_type": "campaign", "entity_id": str(campaign_id)},
        )

    rows = list(
        (
            await db.execute(
                select(TenantAdMetricAggregate).where(
                    TenantAdMetricAggregate.tenant_id == tenant_id,
                    TenantAdMetricAggregate.entity_type == "campaign",
                    TenantAdMetricAggregate.entity_id == campaign_id,
                    TenantAdMetricAggregate.metric_key.in_(["spend_minor", efficiency_key]),
                )
            )
        ).scalars().all()
    )
    by_window: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = by_window.setdefault(row.window_key, {"window_key": row.window_key})
        if row.metric_key == "spend_minor":
            bucket["spend_minor"] = int(row.metric_value or 0)
        elif row.metric_key == efficiency_key:
            bucket["efficiency"] = row.metric_value

    # Prefer known window order; drop incomplete.
    ordered = [by_window[w] for w in _WINDOW_ORDER if w in by_window]
    # Include any other windows.
    for w, bucket in by_window.items():
        if w not in _WINDOW_ORDER:
            ordered.append(bucket)

    direction = "lower_is_better" if efficiency_key.endswith("_minor") or efficiency_key in {
        "cpa_minor", "cpc_minor", "cpm_minor",
    } else "higher_is_better"
    if efficiency_key == "roas":
        direction = "higher_is_better"

    result = compute_diminishing_returns(
        ordered, efficiency_key=efficiency_key, direction=direction,
    )
    result.update({
        "campaign_id": str(campaign_id),
        "campaign_name": campaign.name,
    })
    return result


__all__ = [
    "compute_diminishing_returns",
    "analyze_campaign_diminishing_returns",
]
