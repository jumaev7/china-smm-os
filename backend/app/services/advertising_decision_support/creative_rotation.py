"""Creative rotation analysis — expands Phase 1 fatigue into structured review.

Statuses: healthy_rotation | concentrated | possible_fatigue | insufficient_data.
Never auto-pauses creatives. Emits advertising.possible_fatigue_detected when
status is possible_fatigue.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCreative, TenantAdMetricAggregate
from app.models.advertising_decision_support import (
    CREATIVE_ROTATION_ENGINE_VERSION,
    CREATIVE_ROTATION_STATUSES,
)
from app.services.advertising_decision_support.concentration_analysis import (
    compute_concentration,
)
from app.services.advertising_intelligence._entity_metrics import (
    latest_metric_map,
    metric_decimal,
)
from app.services.advertising_intelligence.creative_diagnostics import (
    compute_creative_fatigue,
)
from app.services.advertising_intelligence.errors import AdCurrencyMismatchError
from app.services.advertising_intelligence.freshness_service import compute_freshness
from app.services.advertising_intelligence.spend_service import entity_spend
from app.services.automation_domain_events import emit_domain_event

_MIN_CREATIVES = 2
_MIN_IMPRESSIONS_SAMPLE = Decimal("1000")
_CONCENTRATED_TOP1 = Decimal("0.7")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_creative_rotation(
    creatives: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure rotation analysis over per-creative observation dicts.

    Expected keys per creative (optional where noted):
    id, spend_minor, impressions, frequency, ctr, freshness_status, age_days
    """
    if len(creatives) < _MIN_CREATIVES:
        return {
            "status": "insufficient_data",
            "observation": "Fewer than two creatives are available for rotation analysis.",
            "evidence": {"creative_count": len(creatives)},
            "interpretation": "Rotation health cannot be assessed with the current sample.",
            "possible_consideration": "Add or ingest additional creatives before reviewing rotation.",
            "engine_version": CREATIVE_ROTATION_ENGINE_VERSION,
            "fatigue_signals": [],
            "read_only": True,
            "kind": "OBSERVED",
        }

    total_impressions = sum(
        (Decimal(str(c["impressions"])) for c in creatives if c.get("impressions") is not None),
        Decimal("0"),
    )
    spend_pairs = [(c["id"], c.get("spend_minor")) for c in creatives]
    impression_pairs = [
        (c["id"], int(c["impressions"]))
        for c in creatives
        if c.get("impressions") is not None
    ]
    spend_conc = compute_concentration(spend_pairs)
    exposure_conc = compute_concentration(impression_pairs) if impression_pairs else {
        "status": "insufficient_data",
        "top1_share": None,
    }

    fatigue_signals: list[dict[str, Any]] = []
    for c in creatives:
        freq = c.get("frequency")
        freq_d = Decimal(str(freq)) if freq is not None else None
        imps = Decimal(str(c["impressions"])) if c.get("impressions") is not None else None
        fatigue = compute_creative_fatigue(frequency=freq_d, impressions=imps)
        fatigue_signals.append({
            "creative_id": str(c["id"]),
            **fatigue,
        })

    possible_fatigue = any(
        f["status"] in {"possible_fatigue", "strong_fatigue_signal"} for f in fatigue_signals
    )
    top1_exposure = (
        Decimal(exposure_conc["top1_share"])
        if exposure_conc.get("top1_share") is not None
        else None
    )
    concentrated = (
        (top1_exposure is not None and top1_exposure >= _CONCENTRATED_TOP1)
        or spend_conc.get("status") == "highly_concentrated"
    )

    stale_count = sum(
        1 for c in creatives if c.get("freshness_status") in {"stale", "unavailable"}
    )
    sample_ok = total_impressions >= _MIN_IMPRESSIONS_SAMPLE

    if not sample_ok and not any(c.get("frequency") is not None for c in creatives):
        status = "insufficient_data"
        observation = "Impression sample and frequency coverage are insufficient for rotation analysis."
        interpretation = "Rotation status withheld pending more delivery data."
        consideration = "Allow more delivery observations to accumulate before reviewing creative rotation."
    elif possible_fatigue:
        status = "possible_fatigue"
        observation = (
            "One or more creatives show elevated frequency consistent with a possible fatigue signal."
        )
        interpretation = (
            "Frequency heuristics suggest audience exposure may be high for some creatives. "
            "This is a possible signal, not a directive to pause or replace creatives."
        )
        consideration = "Consider preparing additional creative variants for human review."
    elif concentrated:
        status = "concentrated"
        observation = (
            "Creative exposure or spend is concentrated in a small subset of creatives."
        )
        interpretation = (
            "Rotation appears uneven: a large share of impressions/spend goes to few creatives."
        )
        consideration = "Consider whether exposure concentration matches the intended creative mix."
    else:
        status = "healthy_rotation"
        observation = "Creative exposure and frequency signals do not indicate concentration or fatigue."
        interpretation = "Observed rotation appears within healthy thresholds for the current sample."
        consideration = "Continue monitoring frequency and exposure share as delivery continues."

    assert status in CREATIVE_ROTATION_STATUSES
    return {
        "status": status,
        "observation": observation,
        "evidence": {
            "creative_count": len(creatives),
            "total_impressions": str(total_impressions),
            "spend_concentration": {
                "status": spend_conc.get("status"),
                "top1_share": spend_conc.get("top1_share"),
                "hhi": spend_conc.get("hhi"),
            },
            "exposure_concentration": {
                "status": exposure_conc.get("status"),
                "top1_share": exposure_conc.get("top1_share"),
                "hhi": exposure_conc.get("hhi"),
            },
            "stale_creative_count": stale_count,
            "sample_size_ok": sample_ok,
            "creatives": [
                {
                    "creative_id": str(c["id"]),
                    "spend_minor": c.get("spend_minor"),
                    "impressions": str(c["impressions"]) if c.get("impressions") is not None else None,
                    "frequency": str(c["frequency"]) if c.get("frequency") is not None else None,
                    "ctr": str(c["ctr"]) if c.get("ctr") is not None else None,
                    "freshness_status": c.get("freshness_status"),
                    "age_days": c.get("age_days"),
                }
                for c in creatives
            ],
        },
        "interpretation": interpretation,
        "possible_consideration": consideration,
        "fatigue_signals": fatigue_signals,
        "engine_version": CREATIVE_ROTATION_ENGINE_VERSION,
        "read_only": True,
        "kind": "OBSERVED",
    }


async def analyze_creative_rotation(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
) -> dict[str, Any]:
    """Load creatives + metrics and run rotation analysis for a tenant/account."""
    filters = [TenantAdCreative.tenant_id == tenant_id]
    if account_id is not None:
        filters.append(TenantAdCreative.advertising_account_id == account_id)
    rows = list((await db.execute(select(TenantAdCreative).where(*filters))).scalars().all())

    creatives: list[dict[str, Any]] = []
    currency: str | None = None
    now = _utcnow()
    for creative in rows:
        spend, cur = await entity_spend(db, tenant_id, "creative", creative.id)
        if cur:
            cur_u = cur.upper()
            if currency is None:
                currency = cur_u
            elif currency != cur_u:
                raise AdCurrencyMismatchError(
                    "cannot analyze creative rotation across differing currencies",
                    details={"currencies": sorted({currency, cur_u})},
                )
        metric_map = await latest_metric_map(db, tenant_id, "creative", creative.id)
        observed_at = None
        obs_entry = metric_map.pop("__observed_at__", None) if metric_map else None
        if obs_entry and obs_entry.get("value"):
            observed_at = obs_entry["value"]
        freshness = compute_freshness(observed_at)
        age_days = None
        if creative.created_at:
            ref = creative.created_at
            if ref.tzinfo is None:
                ref = ref.replace(tzinfo=timezone.utc)
            age_days = max((now - ref).total_seconds() / 86400.0, 0.0)

        # Prefer aggregate frequency when snapshot map lacks it.
        frequency = metric_decimal(metric_map, "frequency")
        if frequency is None:
            agg = (
                await db.execute(
                    select(TenantAdMetricAggregate.metric_value).where(
                        TenantAdMetricAggregate.tenant_id == tenant_id,
                        TenantAdMetricAggregate.entity_type == "creative",
                        TenantAdMetricAggregate.entity_id == creative.id,
                        TenantAdMetricAggregate.metric_key == "frequency",
                        TenantAdMetricAggregate.window_key == "lifetime",
                    )
                )
            ).scalar_one_or_none()
            frequency = agg

        creatives.append({
            "id": creative.id,
            "name": creative.name,
            "spend_minor": spend,
            "impressions": metric_decimal(metric_map, "impressions"),
            "frequency": frequency,
            "ctr": metric_decimal(metric_map, "ctr"),
            "freshness_status": freshness.get("status"),
            "age_days": round(age_days, 2) if age_days is not None else None,
        })

    result = compute_creative_rotation(creatives)
    result.update({
        "account_id": str(account_id) if account_id else None,
        "currency": currency,
    })

    if result["status"] == "possible_fatigue":
        await emit_domain_event(
            db,
            "advertising.possible_fatigue_detected",
            tenant_id,
            payload={
                "status": result["status"],
                "creative_count": len(creatives),
                "account_id": str(account_id) if account_id else None,
                "engine_version": CREATIVE_ROTATION_ENGINE_VERSION,
            },
            resource_type="advertising_account" if account_id else "tenant",
            resource_id=str(account_id) if account_id else str(tenant_id),
            title="Possible creative fatigue signal",
        )
    return result


__all__ = [
    "compute_creative_rotation",
    "analyze_creative_rotation",
]
