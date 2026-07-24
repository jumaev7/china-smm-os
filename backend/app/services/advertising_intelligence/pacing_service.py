"""Deterministic budget pacing.

``compute_pacing`` is a pure function; ``evaluate_account_pacing`` persists a
``TenantAdBudgetSnapshot`` per budgeted entity and emits
``advertising.budget_pacing_updated`` for off-track entities.

Thresholds (pacing_ratio = spend / expected_spend), version 1.0.0:
    < 0.8            -> underspending
    0.8 .. 1.2       -> on_pace
    > 1.2            -> overspending
    remaining <= 0   -> budget_exhausted   (capped/lifetime budgets only)

``budget_exhausted`` is scoped to capped budgets (lifetime): once a lifetime
budget is spent there is nothing left, so that outcome takes precedence. Daily
budgets are a per-day rate rather than a hard cap, so sustained overspend
against the projected window surfaces as ``overspending`` instead of
``budget_exhausted``.

Underspending is descriptive only — it does not imply harm or require action.

Persisted ``pacing_status`` uses the canonical model vocabulary
(``app.models.advertising.PACING_STATUSES``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAdBudgetSnapshot,
    TenantAdCampaign,
    TenantAdGroup,
)
from app.services.advertising_intelligence import spend_service
from app.services.automation_domain_events import emit_domain_event

PACING_CALCULATION_VERSION = "1.0.0"

_UNDER = Decimal("0.8")
_OVER = Decimal("1.2")
_ALERT_STATUSES = frozenset({"underspending", "overspending", "budget_exhausted"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_pacing(
    *,
    budget_minor: int | None,
    budget_type: str | None,
    spend_minor: int | None,
    window_days: int = 30,
    effective_status: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    now: datetime | None = None,
) -> dict:
    """Pure pacing computation. Returns a dict (never raises)."""
    calculation_version = PACING_CALCULATION_VERSION
    status_l = (effective_status or "").lower()
    if status_l in {"paused", "campaign_paused", "adset_paused"}:
        return {
            "pacing_status": "paused",
            "pacing_ratio": None,
            "pace_ratio": None,
            "expected_spend_minor": None,
            "remaining_budget_minor": None,
            "remaining_minor": None,
            "utilization_ratio": None,
            "elapsed_fraction": None,
            "spend_fraction": None,
            "calculation_version": calculation_version,
        }
    if status_l in {"completed", "ended", "archived", "deleted"} or (
        end_time is not None and (now or _utcnow()) > end_time
    ):
        return {
            "pacing_status": "ended",
            "pacing_ratio": None,
            "pace_ratio": None,
            "expected_spend_minor": None,
            "remaining_budget_minor": None,
            "remaining_minor": None,
            "utilization_ratio": None,
            "elapsed_fraction": None,
            "spend_fraction": None,
            "calculation_version": calculation_version,
        }

    if not budget_minor or budget_type in (None, "unlimited", "unknown"):
        return {
            "pacing_status": "not_applicable",
            "pacing_ratio": None,
            "pace_ratio": None,
            "expected_spend_minor": None,
            "remaining_budget_minor": None,
            "remaining_minor": None,
            "utilization_ratio": None,
            "elapsed_fraction": None,
            "spend_fraction": None,
            "calculation_version": calculation_version,
        }
    if spend_minor is None:
        return {
            "pacing_status": "insufficient_data",
            "pacing_ratio": None,
            "pace_ratio": None,
            "expected_spend_minor": None,
            "remaining_budget_minor": None,
            "remaining_minor": None,
            "utilization_ratio": None,
            "elapsed_fraction": None,
            "spend_fraction": None,
            "calculation_version": calculation_version,
        }

    reference = now or _utcnow()
    elapsed_fraction: Decimal | None = None
    if budget_type == "daily":
        expected = budget_minor * max(1, window_days)
        if start_time is not None:
            total_seconds = max(window_days, 1) * 86400
            elapsed_seconds = max((reference - start_time).total_seconds(), 0)
            elapsed_fraction = Decimal(str(min(elapsed_seconds / total_seconds, 1.0)))
    else:  # lifetime
        expected = budget_minor
        if start_time is not None and end_time is not None and end_time > start_time:
            total_seconds = (end_time - start_time).total_seconds()
            elapsed_seconds = max((reference - start_time).total_seconds(), 0)
            elapsed_fraction = Decimal(str(min(elapsed_seconds / total_seconds, 1.0)))
            expected = int(Decimal(budget_minor) * (elapsed_fraction or Decimal("1")))
            if expected <= 0:
                expected = budget_minor

    remaining = expected - spend_minor
    pace_ratio = (Decimal(spend_minor) / Decimal(expected)) if expected else None
    utilization = (Decimal(spend_minor) / Decimal(budget_minor)) if budget_minor else None
    spend_fraction = utilization

    if pace_ratio is None:
        status = "insufficient_data"
    elif budget_type != "daily" and remaining <= 0 and spend_minor >= budget_minor:
        status = "budget_exhausted"
    elif pace_ratio < _UNDER:
        status = "underspending"
    elif pace_ratio > _OVER:
        status = "overspending"
    else:
        status = "on_pace"

    return {
        "pacing_status": status,
        "pacing_ratio": pace_ratio,
        "pace_ratio": pace_ratio,  # alias for older callers
        "expected_spend_minor": int(expected),
        "remaining_budget_minor": int(remaining),
        "remaining_minor": int(remaining),  # alias
        "utilization_ratio": utilization,
        "elapsed_fraction": elapsed_fraction,
        "spend_fraction": spend_fraction,
        "budget_minor": int(budget_minor),
        "spend_minor": int(spend_minor),
        "calculation_version": calculation_version,
    }


def _campaign_budget(campaign: TenantAdCampaign) -> tuple[int | None, str, str | None]:
    if campaign.daily_budget_minor is not None:
        return campaign.daily_budget_minor, "daily", campaign.budget_currency
    if campaign.lifetime_budget_minor is not None:
        return campaign.lifetime_budget_minor, "lifetime", campaign.budget_currency
    return None, "unknown", campaign.budget_currency


def _ad_group_budget(ad_group: TenantAdGroup) -> tuple[int | None, str, str | None]:
    if ad_group.daily_budget_minor is not None:
        return ad_group.daily_budget_minor, "daily", ad_group.budget_currency
    if ad_group.lifetime_budget_minor is not None:
        return ad_group.lifetime_budget_minor, "lifetime", ad_group.budget_currency
    return None, "unknown", ad_group.budget_currency


async def _persist_and_alert(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    entity_type: str,
    entity_id: UUID,
    budget_minor: int | None,
    budget_type: str,
    budget_currency: str | None,
    observed_at: datetime,
    window_days: int,
) -> str:
    spend_minor, spend_currency = await spend_service.entity_spend(db, tenant_id, entity_type, entity_id)
    currency = spend_currency or budget_currency
    result = compute_pacing(
        budget_minor=budget_minor, budget_type=budget_type,
        spend_minor=spend_minor, window_days=window_days,
    )
    status = result["pacing_status"]
    if status == "not_applicable":
        return status

    db.add(
        TenantAdBudgetSnapshot(
            tenant_id=tenant_id,
            advertising_account_id=account_id,
            entity_type=entity_type,
            entity_id=entity_id,
            budget_type=budget_type,
            budget_minor=budget_minor,
            spend_minor=spend_minor,
            remaining_minor=result["remaining_minor"],
            currency=currency,
            utilization_ratio=result["utilization_ratio"],
            pacing_status=status,
            observed_at=observed_at,
            source="system",
            metadata_json={
                "pace_ratio": str(result["pace_ratio"]) if result["pace_ratio"] is not None else None,
                "expected_spend_minor": result["expected_spend_minor"],
                "calculation_version": PACING_CALCULATION_VERSION,
                "window_days": window_days,
            },
        )
    )

    if status in _ALERT_STATUSES:
        await emit_domain_event(
            db,
            "advertising.budget_pacing_alert",
            tenant_id,
            payload={
                "ad_account_id": str(account_id),
                "campaign_id": str(entity_id) if entity_type == "campaign" else None,
                "entity_type": entity_type,
                "pacing_status": status,
                "pace_ratio": str(result["pace_ratio"]) if result["pace_ratio"] is not None else None,
                "currency": currency,
            },
            resource_type=f"advertising_{entity_type}",
            resource_id=str(entity_id),
            title="Advertising budget pacing alert",
        )
    return status


async def evaluate_account_pacing(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    *,
    observed_at: datetime | None = None,
    window_days: int = 30,
) -> list[str]:
    """Compute + persist pacing for all budgeted campaigns and ad groups."""
    observed_at = observed_at or _utcnow()
    statuses: list[str] = []

    campaigns = list(
        (
            await db.execute(
                select(TenantAdCampaign).where(
                    TenantAdCampaign.tenant_id == tenant_id,
                    TenantAdCampaign.advertising_account_id == account_id,
                )
            )
        ).scalars().all()
    )
    for campaign in campaigns:
        budget_minor, budget_type, currency = _campaign_budget(campaign)
        statuses.append(
            await _persist_and_alert(
                db, tenant_id=tenant_id, account_id=account_id, entity_type="campaign",
                entity_id=campaign.id, budget_minor=budget_minor, budget_type=budget_type,
                budget_currency=currency, observed_at=observed_at, window_days=window_days,
            )
        )

    ad_groups = list(
        (
            await db.execute(
                select(TenantAdGroup).where(
                    TenantAdGroup.tenant_id == tenant_id,
                    TenantAdGroup.advertising_account_id == account_id,
                )
            )
        ).scalars().all()
    )
    for ad_group in ad_groups:
        budget_minor, budget_type, currency = _ad_group_budget(ad_group)
        if budget_minor is None:
            continue
        statuses.append(
            await _persist_and_alert(
                db, tenant_id=tenant_id, account_id=account_id, entity_type="ad_group",
                entity_id=ad_group.id, budget_minor=budget_minor, budget_type=budget_type,
                budget_currency=currency, observed_at=observed_at, window_days=window_days,
            )
        )
    await db.flush()
    return statuses


__all__ = ["PACING_CALCULATION_VERSION", "compute_pacing", "evaluate_account_pacing"]
