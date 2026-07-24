"""Deterministic, read-only advertising recommendations.

Recommendations are derived entirely from persisted evidence (budget pacing
snapshots, open delivery anomalies, creative frequency) — never from opaque
prediction. They are advisory and describe what to *review*; they never instruct
automatic action.

Wording guardrails (never emitted): "Increase budget now", "Pause this
campaign", "Replace creative automatically", "Guaranteed ROAS", "AI predicts",
"This will improve conversions".
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAdCampaign,
    TenantAdCreative,
    TenantAdDeliveryAnomaly,
    TenantAdMetricAggregate,
    TenantAdBudgetSnapshot,
)

_PACING_PRIORITY = {"budget_exhausted": "high", "overspending": "medium", "underspending": "low"}
_PACING_REASON = {
    "budget_exhausted": "Budget appears fully consumed for the current window; review remaining budget.",
    "overspending": "Spend is pacing ahead of plan; review budget and delivery settings.",
    "underspending": "Spend is pacing behind plan; review targeting and delivery.",
}
_SEVERITY_PRIORITY = {"critical": "high", "error": "high", "warning": "medium", "info": "low"}
_FATIGUE_POSSIBLE = Decimal("2.5")
_FATIGUE_STRONG = Decimal("4.0")


def _rec(
    *,
    recommendation_key: str,
    priority: str,
    title: str,
    reason: str,
    confidence: Decimal,
    account_id: UUID | None,
    campaign_id: UUID | None,
    currency: str | None,
    evidence: dict,
    created_at,
) -> dict:
    entity = campaign_id or account_id or "account"
    return {
        "id": f"{recommendation_key}:{entity}",
        "recommendation_key": recommendation_key,
        "category": "advertising",
        "priority": priority,
        "title": title,
        "reason": reason,
        "confidence": confidence,
        "account_id": account_id,
        "campaign_id": campaign_id,
        "currency": currency,
        "action_url": None,
        "evidence": evidence,
        "status": "open",
        "created_at": created_at,
        "read_only": True,
    }


async def _pacing_recommendations(db: AsyncSession, tenant_id: UUID) -> list[dict]:
    rows = list(
        (
            await db.execute(
                select(TenantAdBudgetSnapshot)
                .where(
                    TenantAdBudgetSnapshot.tenant_id == tenant_id,
                    TenantAdBudgetSnapshot.entity_type == "campaign",
                    TenantAdBudgetSnapshot.pacing_status.in_(list(_PACING_PRIORITY.keys())),
                )
                .order_by(TenantAdBudgetSnapshot.observed_at.desc())
            )
        ).scalars().all()
    )
    seen: set[UUID] = set()
    recs: list[dict] = []
    for row in rows:
        if row.entity_id in seen:
            continue
        seen.add(row.entity_id)
        recs.append(
            _rec(
                recommendation_key="advertising.review_budget_pacing",
                priority=_PACING_PRIORITY[row.pacing_status],
                title="Review budget pacing",
                reason=_PACING_REASON[row.pacing_status],
                confidence=Decimal("0.900"),
                account_id=row.advertising_account_id,
                campaign_id=row.entity_id,
                currency=row.currency,
                evidence={
                    "pacing_status": row.pacing_status,
                    "spend_minor": row.spend_minor,
                    "budget_minor": row.budget_minor,
                },
                created_at=row.created_at,
            )
        )
    return recs


async def _delivery_recommendations(db: AsyncSession, tenant_id: UUID) -> list[dict]:
    rows = list(
        (
            await db.execute(
                select(TenantAdDeliveryAnomaly)
                .where(
                    TenantAdDeliveryAnomaly.tenant_id == tenant_id,
                    TenantAdDeliveryAnomaly.status == "open",
                    TenantAdDeliveryAnomaly.severity.in_(["warning", "error", "critical"]),
                )
                .order_by(TenantAdDeliveryAnomaly.created_at.desc())
            )
        ).scalars().all()
    )
    recs: list[dict] = []
    for row in rows:
        recs.append(
            _rec(
                recommendation_key="advertising.investigate_delivery",
                priority=_SEVERITY_PRIORITY.get(row.severity, "medium"),
                title=f"Investigate delivery issue: {row.anomaly_key}",
                reason="A delivery anomaly was detected from ingested metrics; review the affected entity.",
                confidence=Decimal("0.850"),
                account_id=row.advertising_account_id,
                campaign_id=row.entity_id if row.entity_type == "campaign" else None,
                currency=None,
                evidence={"anomaly_key": row.anomaly_key, "severity": row.severity, **(row.evidence or {})},
                created_at=row.created_at,
            )
        )
    return recs


async def _fatigue_recommendations(db: AsyncSession, tenant_id: UUID) -> list[dict]:
    rows = list(
        (
            await db.execute(
                select(TenantAdMetricAggregate).where(
                    TenantAdMetricAggregate.tenant_id == tenant_id,
                    TenantAdMetricAggregate.entity_type == "creative",
                    TenantAdMetricAggregate.metric_key == "frequency",
                    TenantAdMetricAggregate.window_key == "lifetime",
                    TenantAdMetricAggregate.metric_value >= _FATIGUE_POSSIBLE,
                )
            )
        ).scalars().all()
    )
    recs: list[dict] = []
    for row in rows:
        strong = (row.metric_value or Decimal(0)) >= _FATIGUE_STRONG
        recs.append(
            _rec(
                recommendation_key="advertising.review_creative_fatigue",
                priority="medium" if strong else "low",
                title="Possible creative fatigue — consider refreshing creative",
                reason="Creative frequency is elevated; a fresh creative may help audience response.",
                confidence=Decimal("0.700"),
                account_id=row.advertising_account_id,
                campaign_id=None,
                currency=None,
                evidence={"frequency": str(row.metric_value), "creative_id": str(row.entity_id)},
                created_at=row.calculated_at,
            )
        )
    return recs


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


async def compute_recommendations(db: AsyncSession, tenant_id: UUID) -> list[dict]:
    recs: list[dict] = []
    recs.extend(await _pacing_recommendations(db, tenant_id))
    recs.extend(await _delivery_recommendations(db, tenant_id))
    recs.extend(await _fatigue_recommendations(db, tenant_id))
    recs.sort(key=lambda r: (_PRIORITY_ORDER.get(r["priority"], 3), r["recommendation_key"]))
    return recs


async def list_recommendations(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = "open",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    if status is not None and status != "open":
        return [], 0
    recs = await compute_recommendations(db, tenant_id)
    total = len(recs)
    return recs[offset: offset + limit], total


__all__ = ["compute_recommendations", "list_recommendations"]
