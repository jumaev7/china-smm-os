"""Mechanical pacing projection — mathematical extrapolation, not ML forecasting.

Label is always: "Mechanical projection based on current spend rate".
Never call results AI forecast / predicted spend / guaranteed spend.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCampaign
from app.models.advertising_decision_support import PACING_PROJECTION_ENGINE_VERSION
from app.services.advertising_decision_support.errors import AdEntityNotFoundError
from app.services.advertising_intelligence.freshness_service import compute_freshness
from app.services.advertising_intelligence.spend_service import entity_spend
from app.services.advertising_intelligence._entity_metrics import latest_metric_map

PACING_PROJECTION_LABEL = "Mechanical projection based on current spend rate"
PACING_PROJECTION_FORMULA = (
    "projected_end_spend_minor = spend_so_far_minor / elapsed_fraction "
    "when 0 < elapsed_fraction <= 1; else undefined"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def project_pacing(
    *,
    spend_so_far_minor: int | None,
    budget_minor: int | None,
    period_start: datetime | None,
    period_end: datetime | None,
    now: datetime | None = None,
    effective_status: str | None = None,
    freshness_status: str | None = None,
) -> dict[str, Any]:
    """Pure mechanical pacing projection. Never raises."""
    reference = _aware(now) or _utcnow()
    start = _aware(period_start)
    end = _aware(period_end)
    status_l = (effective_status or "").lower()
    base = {
        "spent_so_far_minor": spend_so_far_minor,
        "budget_minor": budget_minor,
        "elapsed_fraction": None,
        "daily_spend_rate_minor": None,
        "projected_end_spend_minor": None,
        "utilization_ratio": None,
        "label": PACING_PROJECTION_LABEL,
        "formula": PACING_PROJECTION_FORMULA,
        "engine_version": PACING_PROJECTION_ENGINE_VERSION,
        "kind": "MECHANICAL_PROJECTION",
        "read_only": True,
    }

    if status_l in {"paused", "campaign_paused", "adset_paused"}:
        return {**base, "projection_status": "paused", "message": "Campaign is paused; projection not evaluated."}
    if status_l in {"completed", "ended", "archived", "deleted"} or (
        end is not None and reference > end
    ):
        return {**base, "projection_status": "ended", "message": "Campaign period has ended; projection not evaluated."}
    if freshness_status == "stale":
        return {**base, "projection_status": "stale", "message": "Metric data is stale; projection withheld."}
    if budget_minor is None or budget_minor <= 0:
        return {**base, "projection_status": "missing_budget", "message": "No usable budget configured."}
    if spend_so_far_minor is None:
        return {**base, "projection_status": "insufficient_data", "message": "Spend observation is missing."}
    if spend_so_far_minor == 0:
        return {
            **base,
            "projection_status": "zero_spend",
            "elapsed_fraction": None,
            "daily_spend_rate_minor": Decimal("0"),
            "projected_end_spend_minor": 0,
            "utilization_ratio": Decimal("0"),
            "message": "Zero spend so far; mechanical end-of-period projection is zero at current rate.",
        }
    if start is None or end is None or end <= start:
        return {
            **base,
            "projection_status": "insufficient_data",
            "message": "Budget period start/end are missing or invalid.",
        }

    total_seconds = (end - start).total_seconds()
    if total_seconds <= 0:
        return {**base, "projection_status": "insufficient_data", "message": "Budget period length is zero."}

    elapsed_seconds = max((reference - start).total_seconds(), 0.0)
    elapsed_fraction = Decimal(str(min(elapsed_seconds / total_seconds, 1.0)))
    remaining_seconds = max((end - reference).total_seconds(), 0.0)
    days_elapsed = max(elapsed_seconds / 86400.0, 0.0)

    utilization = Decimal(spend_so_far_minor) / Decimal(budget_minor)
    daily_rate = (
        Decimal(spend_so_far_minor) / Decimal(str(days_elapsed))
        if days_elapsed > 0
        else None
    )

    if elapsed_fraction <= 0:
        return {
            **base,
            "projection_status": "insufficient_data",
            "elapsed_fraction": str(elapsed_fraction),
            "utilization_ratio": str(utilization),
            "message": "Period has not started yet.",
        }

    projected = int(
        (Decimal(spend_so_far_minor) / elapsed_fraction).to_integral_value()
    )
    # Alternative rate-based projection when we have daily rate + remaining time.
    if daily_rate is not None and remaining_seconds >= 0:
        remaining_days = Decimal(str(remaining_seconds / 86400.0))
        rate_projected = int(Decimal(spend_so_far_minor) + daily_rate * remaining_days)
        # Prefer elapsed-fraction method as primary; keep rate as metadata.
        rate_meta = rate_projected
    else:
        rate_meta = None

    return {
        **base,
        "projection_status": "projected",
        "elapsed_fraction": str(elapsed_fraction),
        "daily_spend_rate_minor": str(daily_rate) if daily_rate is not None else None,
        "projected_end_spend_minor": projected,
        "rate_based_projected_end_spend_minor": rate_meta,
        "utilization_ratio": str(utilization),
        "message": PACING_PROJECTION_LABEL,
    }


async def project_campaign_pacing(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load campaign + observed spend and run mechanical projection."""
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

    spend_minor, spend_currency = await entity_spend(db, tenant_id, "campaign", campaign_id)
    budget_minor = campaign.lifetime_budget_minor
    if budget_minor is None and campaign.daily_budget_minor is not None:
        # For daily budgets without an explicit stop, treat a 30-day window as the period.
        budget_minor = int(campaign.daily_budget_minor) * 30

    metric_map = await latest_metric_map(db, tenant_id, "campaign", campaign_id)
    observed_at = None
    obs_entry = metric_map.get("__observed_at__")
    if obs_entry and obs_entry.get("value"):
        observed_at = obs_entry["value"]
    freshness = compute_freshness(observed_at)

    period_start = campaign.provider_start_time or campaign.created_at
    period_end = campaign.provider_stop_time
    if period_end is None and campaign.daily_budget_minor is not None and period_start is not None:
        from datetime import timedelta
        period_end = _aware(period_start) + timedelta(days=30)

    result = project_pacing(
        spend_so_far_minor=spend_minor,
        budget_minor=budget_minor,
        period_start=period_start,
        period_end=period_end,
        now=now,
        effective_status=campaign.effective_status,
        freshness_status=freshness.get("status"),
    )
    result.update({
        "campaign_id": str(campaign_id),
        "campaign_name": campaign.name,
        "currency": (spend_currency or campaign.budget_currency or "").upper() or None,
        "freshness": freshness,
        "effective_status": campaign.effective_status,
    })
    return result


__all__ = [
    "PACING_PROJECTION_LABEL",
    "PACING_PROJECTION_FORMULA",
    "project_pacing",
    "project_campaign_pacing",
]
