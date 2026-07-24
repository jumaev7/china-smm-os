"""Creative fatigue diagnostics (advisory, evidence-backed).

Fatigue is inferred conservatively from creative frequency (impressions per
person). With a single observation we can only surface a *possible* signal — we
never assert causation and never recommend automatic action. Wording is
deliberately soft ("Possible fatigue signal"), never "Replace creative
immediately".

Statuses: ``insufficient_data`` | ``no_signal`` | ``possible_fatigue`` |
``strong_fatigue_signal``.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCreative, TenantAdMetricAggregate
from app.services.automation_domain_events import emit_domain_event

FATIGUE_STATUSES = ("insufficient_data", "no_signal", "possible_fatigue", "strong_fatigue_signal")

_POSSIBLE_FREQUENCY = Decimal("2.5")
_STRONG_FREQUENCY = Decimal("4.0")
_ALERT_STATUSES = frozenset({"possible_fatigue", "strong_fatigue_signal"})


def compute_creative_fatigue(
    *,
    frequency: Decimal | None,
    impressions: Decimal | None = None,
    ctr_trend: Decimal | None = None,
) -> dict:
    """Pure fatigue classification. Returns ``{status, message, evidence}``."""
    if frequency is None or (impressions is not None and impressions == 0):
        return {
            "status": "insufficient_data",
            "message": "Not enough delivery data to assess fatigue.",
            "evidence": {"frequency": str(frequency) if frequency is not None else None},
        }
    if frequency >= _STRONG_FREQUENCY:
        status = "strong_fatigue_signal"
        message = "Strong fatigue signal: audience is seeing this creative very frequently."
    elif frequency >= _POSSIBLE_FREQUENCY:
        status = "possible_fatigue"
        message = "Possible fatigue signal: creative frequency is elevated."
    else:
        status = "no_signal"
        message = "No fatigue signal from current frequency."
    evidence = {"frequency": str(frequency)}
    if ctr_trend is not None:
        evidence["ctr_trend"] = str(ctr_trend)
    return {"status": status, "message": message, "evidence": evidence}


async def _creative_metric(db: AsyncSession, tenant_id: UUID, creative_id: UUID, metric_key: str) -> Decimal | None:
    row = (
        await db.execute(
            select(TenantAdMetricAggregate.metric_value).where(
                TenantAdMetricAggregate.tenant_id == tenant_id,
                TenantAdMetricAggregate.entity_type == "creative",
                TenantAdMetricAggregate.entity_id == creative_id,
                TenantAdMetricAggregate.metric_key == metric_key,
                TenantAdMetricAggregate.window_key == "lifetime",
            )
        )
    ).scalar_one_or_none()
    return row


async def evaluate_creative_fatigue(db: AsyncSession, tenant_id: UUID, creative_id: UUID) -> dict:
    frequency = await _creative_metric(db, tenant_id, creative_id, "frequency")
    impressions = await _creative_metric(db, tenant_id, creative_id, "impressions")
    result = compute_creative_fatigue(frequency=frequency, impressions=impressions)
    result["creative_id"] = creative_id
    if result["status"] in _ALERT_STATUSES:
        await emit_domain_event(
            db,
            "advertising.creative_fatigue_detected",
            tenant_id,
            payload={
                "ad_entity_id": str(creative_id),
                "entity_type": "creative",
                "fatigue_status": result["status"],
            },
            resource_type="advertising_creative",
            resource_id=str(creative_id),
            title="Possible creative fatigue signal",
        )
    return result


async def evaluate_account_creatives(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> list[dict]:
    creative_ids = list(
        (
            await db.execute(
                select(TenantAdCreative.id).where(
                    TenantAdCreative.tenant_id == tenant_id,
                    TenantAdCreative.advertising_account_id == account_id,
                )
            )
        ).scalars().all()
    )
    results = [await evaluate_creative_fatigue(db, tenant_id, cid) for cid in creative_ids]
    await db.flush()
    return results


__all__ = [
    "FATIGUE_STATUSES",
    "compute_creative_fatigue",
    "evaluate_creative_fatigue",
    "evaluate_account_creatives",
]
