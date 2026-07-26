"""Budget / creative concentration diagnostics (advisory only).

Classifications are diagnostics — concentration is not necessarily bad.
Structure: Observation, Evidence, Interpretation, Possible consideration.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCampaign, TenantAdCreative
from app.models.advertising_decision_support import (
    CONCENTRATION_ENGINE_VERSION,
    CONCENTRATION_STATUSES,
)
from app.services.advertising_intelligence.errors import AdCurrencyMismatchError
from app.services.advertising_intelligence.spend_service import entity_spend
from app.services.automation_domain_events import emit_domain_event

# HHI / top-1 thresholds (fractions 0–1)
_DIVERSIFIED_HHI = Decimal("0.15")
_DIVERSIFIED_TOP1 = Decimal("0.4")
_MODERATE_TOP1 = Decimal("0.7")


def compute_concentration(
    shares: list[tuple[Any, int | Decimal | None]],
) -> dict[str, Any]:
    """Pure concentration from ``(id, spend)`` pairs.

    Thresholds:
    - diversified: HHI < 0.15 OR top1 < 0.4
    - moderately_concentrated: top1 < 0.7
    - highly_concentrated: otherwise
    - insufficient_data: fewer than 2 entities with positive spend
    """
    cleaned: list[tuple[Any, Decimal]] = []
    for eid, spend in shares:
        if spend is None:
            continue
        val = spend if isinstance(spend, Decimal) else Decimal(int(spend))
        if val > 0:
            cleaned.append((eid, val))

    if len(cleaned) < 2:
        return {
            "status": "insufficient_data",
            "top1_share": None,
            "top3_share": None,
            "hhi": None,
            "entity_count_with_spend": len(cleaned),
            "total_spend": int(sum(v for _, v in cleaned)) if cleaned else 0,
            "ranked": [],
            "engine_version": CONCENTRATION_ENGINE_VERSION,
            "observation": "Fewer than two entities have positive observed spend.",
            "evidence": {"entity_count_with_spend": len(cleaned)},
            "interpretation": "Concentration cannot be assessed with the available spend sample.",
            "possible_consideration": "Ingest additional entity spend observations before reviewing concentration.",
        }

    total = sum(v for _, v in cleaned)
    ranked = sorted(cleaned, key=lambda x: x[1], reverse=True)
    fractions = [(eid, (val / total)) for eid, val in ranked]
    top1 = fractions[0][1]
    top3 = sum(f for _, f in fractions[:3])
    hhi = sum(f * f for _, f in fractions)

    if hhi < _DIVERSIFIED_HHI or top1 < _DIVERSIFIED_TOP1:
        status = "diversified"
        interpretation = (
            "Spend is relatively distributed across entities under the configured thresholds."
        )
        consideration = "No concentration review is specifically indicated by these thresholds."
    elif top1 < _MODERATE_TOP1:
        status = "moderately_concentrated"
        interpretation = (
            "A meaningful share of spend is concentrated in a small number of entities."
        )
        consideration = (
            "Consider whether this concentration matches the intended strategy."
        )
    else:
        status = "highly_concentrated"
        interpretation = (
            "A large share of measured spend is concentrated in one or a few entities."
        )
        consideration = (
            "Consider reviewing whether this concentration matches the intended strategy."
        )

    assert status in CONCENTRATION_STATUSES

    observation = (
        f"Top entity represents {float(top1) * 100:.1f}% of measured spend; "
        f"top 3 represent {float(top3) * 100:.1f}%; HHI={float(hhi):.4f}."
    )
    return {
        "status": status,
        "top1_share": str(top1),
        "top3_share": str(top3),
        "hhi": str(hhi),
        "entity_count_with_spend": len(cleaned),
        "total_spend": int(total),
        "ranked": [
            {"entity_id": str(eid), "spend": int(val), "share": str(frac)}
            for (eid, val), (_, frac) in zip(ranked, fractions)
        ],
        "engine_version": CONCENTRATION_ENGINE_VERSION,
        "observation": observation,
        "evidence": {
            "top1_share": str(top1),
            "top3_share": str(top3),
            "hhi": str(hhi),
            "entity_count_with_spend": len(cleaned),
            "total_spend": int(total),
        },
        "interpretation": interpretation,
        "possible_consideration": consideration,
        "read_only": True,
        "kind": "OBSERVED",
    }


async def _spend_shares(
    db: AsyncSession,
    tenant_id: UUID,
    entity_type: str,
    entity_ids: list[UUID],
) -> tuple[list[tuple[UUID, int | None]], str | None]:
    pairs: list[tuple[UUID, int | None]] = []
    currency: str | None = None
    for eid in entity_ids:
        spend, cur = await entity_spend(db, tenant_id, entity_type, eid)
        if cur:
            cur_u = cur.upper()
            if currency is None:
                currency = cur_u
            elif currency != cur_u:
                raise AdCurrencyMismatchError(
                    "cannot analyze concentration across differing currencies",
                    details={"currencies": sorted({currency, cur_u})},
                )
        pairs.append((eid, spend))
    return pairs, currency


async def analyze_campaign_concentration(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
) -> dict[str, Any]:
    """Concentration across tenant campaigns (optionally scoped to one account)."""
    filters = [TenantAdCampaign.tenant_id == tenant_id]
    if account_id is not None:
        filters.append(TenantAdCampaign.advertising_account_id == account_id)
    campaigns = list(
        (await db.execute(select(TenantAdCampaign).where(*filters))).scalars().all()
    )
    pairs, currency = await _spend_shares(
        db, tenant_id, "campaign", [c.id for c in campaigns]
    )
    result = compute_concentration(pairs)
    result.update({
        "entity_type": "campaign",
        "currency": currency,
        "account_id": str(account_id) if account_id else None,
    })
    if result["status"] == "highly_concentrated":
        await emit_domain_event(
            db,
            "advertising.concentration_detected",
            tenant_id,
            payload={
                "entity_type": "campaign",
                "status": result["status"],
                "top1_share": result["top1_share"],
                "hhi": result["hhi"],
                "currency": currency,
                "account_id": str(account_id) if account_id else None,
            },
            resource_type="advertising_account" if account_id else "tenant",
            resource_id=str(account_id) if account_id else str(tenant_id),
            title="Advertising spend concentration detected",
        )
    return result


async def analyze_creative_concentration(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
) -> dict[str, Any]:
    """Concentration across tenant creatives (optionally scoped to one account)."""
    filters = [TenantAdCreative.tenant_id == tenant_id]
    if account_id is not None:
        filters.append(TenantAdCreative.advertising_account_id == account_id)
    creatives = list(
        (await db.execute(select(TenantAdCreative).where(*filters))).scalars().all()
    )
    pairs, currency = await _spend_shares(
        db, tenant_id, "creative", [c.id for c in creatives]
    )
    result = compute_concentration(pairs)
    result.update({
        "entity_type": "creative",
        "currency": currency,
        "account_id": str(account_id) if account_id else None,
    })
    if result["status"] == "highly_concentrated":
        await emit_domain_event(
            db,
            "advertising.concentration_detected",
            tenant_id,
            payload={
                "entity_type": "creative",
                "status": result["status"],
                "top1_share": result["top1_share"],
                "hhi": result["hhi"],
                "currency": currency,
                "account_id": str(account_id) if account_id else None,
            },
            resource_type="advertising_account" if account_id else "tenant",
            resource_id=str(account_id) if account_id else str(tenant_id),
            title="Advertising creative concentration detected",
        )
    return result


__all__ = [
    "compute_concentration",
    "analyze_campaign_concentration",
    "analyze_creative_concentration",
]
