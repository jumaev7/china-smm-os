"""Spend aggregation — strictly same-currency, no parent/child double counting.

Spend is money in minor units and is NEVER summed across currencies. Callers get
results grouped by currency. To avoid double counting, spend is summed at a
single entity level (default ``campaign``) rather than across the hierarchy.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    AD_CALCULATION_VERSION,
    TenantAdMetricAggregate,
)
from app.services.advertising_intelligence.errors import AdCurrencyMismatchError

_LIFETIME = "lifetime"


def sum_same_currency(amounts: list[tuple[int | None, str | None]]) -> tuple[int, str]:
    """Sum ``(minor_units, currency)`` pairs, raising on any currency mismatch."""
    currency: str | None = None
    total = 0
    for minor, cur in amounts:
        if minor is None:
            continue
        if cur is None:
            continue
        if currency is None:
            currency = cur
        elif cur != currency:
            raise AdCurrencyMismatchError(
                "cannot sum spend across differing currencies",
                details={"currencies": sorted({currency, cur})},
            )
        total += int(minor)
    return total, (currency or "")


async def spend_by_currency(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
    level: str = "campaign",
) -> dict:
    """Total spend grouped by currency at a single entity ``level``.

    Aggregating at one level avoids parent/child double counting. Returns
    ``{"level", "by_currency": [{"currency", "spend_minor", "entity_count"}]}``.
    """
    filters = [
        TenantAdMetricAggregate.tenant_id == tenant_id,
        TenantAdMetricAggregate.entity_type == level,
        TenantAdMetricAggregate.metric_key == "spend_minor",
        TenantAdMetricAggregate.window_key == _LIFETIME,
        TenantAdMetricAggregate.calculation_version == AD_CALCULATION_VERSION,
    ]
    if account_id is not None:
        filters.append(TenantAdMetricAggregate.advertising_account_id == account_id)
    rows = list((await db.execute(select(TenantAdMetricAggregate).where(*filters))).scalars().all())

    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        currency = (row.currency or "UNKNOWN").upper()
        totals[currency] += int(row.metric_value or 0)
        counts[currency] += 1

    buckets = [
        {"currency": cur, "spend_minor": totals[cur], "entity_count": counts[cur]}
        for cur in sorted(totals, key=lambda c: totals[c], reverse=True)
    ]
    return {"level": level, "by_currency": buckets}


async def entity_spend(
    db: AsyncSession,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> tuple[int | None, str | None]:
    """Return ``(spend_minor, currency)`` for a single entity (lifetime)."""
    row = (
        await db.execute(
            select(TenantAdMetricAggregate).where(
                TenantAdMetricAggregate.tenant_id == tenant_id,
                TenantAdMetricAggregate.entity_type == entity_type,
                TenantAdMetricAggregate.entity_id == entity_id,
                TenantAdMetricAggregate.metric_key == "spend_minor",
                TenantAdMetricAggregate.window_key == _LIFETIME,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None, None
    return int(row.metric_value or 0), (row.currency or None)


__all__ = ["sum_same_currency", "spend_by_currency", "entity_spend"]
