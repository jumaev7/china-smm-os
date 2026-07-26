"""Deterministic entity comparison engine.

Compares compatible advertising entities using observed normalized metrics.
Never fabricates missing metrics. Never silently mixes currencies. Never
labels a higher metric as "better" unless metric semantics support it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAd,
    TenantAdCampaign,
    TenantAdCreative,
    TenantAdGroup,
    TenantAdvertisingAccount,
)
from app.models.advertising_decision_support import (
    COMPARABLE_ENTITY_TYPES,
    COMPARISON_ENGINE_VERSION,
)
from app.services.advertising_decision_support.errors import (
    AdComparisonIncompatibleError,
    AdEntityNotFoundError,
)
from app.services.advertising_decision_support.limits import enforce_comparison_entity_count
from app.services.advertising_intelligence._entity_metrics import latest_metric_map, metric_decimal
from app.services.advertising_intelligence.freshness_service import compute_freshness
from app.services.advertising_intelligence.metric_catalog import get_metric_definition

_ENTITY_MODELS = {
    "campaign": TenantAdCampaign,
    "ad_group": TenantAdGroup,
    "ad": TenantAd,
    "creative": TenantAdCreative,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def compute_metric_delta(
    *,
    left: Decimal | None,
    right: Decimal | None,
    direction: str = "neutral",
) -> dict[str, Any]:
    """Pure metric delta. Percentage only when mathematically valid."""
    if left is None or right is None:
        return {
            "left_value": str(left) if left is not None else None,
            "right_value": str(right) if right is not None else None,
            "absolute_difference": None,
            "percentage_difference": None,
            "favorable_side": None,
            "availability": "missing",
        }
    absolute = right - left
    pct: Decimal | None
    if left == 0:
        pct = None
    else:
        pct = (absolute / left) * Decimal("100")

    favorable: str | None = None
    if direction == "higher_is_better":
        if absolute > 0:
            favorable = "right"
        elif absolute < 0:
            favorable = "left"
    elif direction == "lower_is_better":
        if absolute < 0:
            favorable = "right"
        elif absolute > 0:
            favorable = "left"
    # direction == "neutral" → never auto-label better

    return {
        "left_value": str(left),
        "right_value": str(right),
        "absolute_difference": str(absolute),
        "percentage_difference": str(pct) if pct is not None else None,
        "favorable_side": favorable,
        "availability": "observed",
        "direction": direction,
    }


async def _load_entity(
    db: AsyncSession,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> Any:
    model = _ENTITY_MODELS.get(entity_type)
    if model is None:
        raise AdComparisonIncompatibleError(
            f"unsupported entity type: {entity_type}",
            details={"entity_type": entity_type, "supported": sorted(COMPARABLE_ENTITY_TYPES)},
        )
    row = (
        await db.execute(
            select(model).where(model.tenant_id == tenant_id, model.id == entity_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AdEntityNotFoundError(
            "advertising entity not found",
            details={"entity_type": entity_type, "entity_id": str(entity_id)},
        )
    return row


async def _account_currency(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> str | None:
    row = (
        await db.execute(
            select(TenantAdvertisingAccount).where(
                TenantAdvertisingAccount.tenant_id == tenant_id,
                TenantAdvertisingAccount.id == account_id,
            )
        )
    ).scalar_one_or_none()
    return (row.currency.upper() if row and row.currency else None)


async def compare_entities(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    entity_type: str,
    entity_ids: list[UUID],
    metric_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Compare 2+ compatible entities of the same type.

    Compatibility requires same entity_type, same provider, and same currency
    for any currency-bearing metrics present.
    """
    enforce_comparison_entity_count(len(entity_ids))
    if entity_type not in COMPARABLE_ENTITY_TYPES:
        raise AdComparisonIncompatibleError(
            "unsupported entity type for comparison",
            details={"entity_type": entity_type},
        )

    entities = []
    for eid in entity_ids:
        row = await _load_entity(db, tenant_id, entity_type, eid)
        account_id = getattr(row, "advertising_account_id", None)
        currency = await _account_currency(db, tenant_id, account_id) if account_id else None
        # Prefer budget_currency when present on campaigns/ad groups.
        budget_currency = getattr(row, "budget_currency", None)
        if budget_currency:
            currency = budget_currency.upper()
        metric_map = await latest_metric_map(db, tenant_id, entity_type, eid)
        observed_at = None
        obs_entry = metric_map.pop("__observed_at__", None)
        if obs_entry and obs_entry.get("value"):
            observed_at = obs_entry["value"]
        spend_currency = None
        spend_entry = metric_map.get("spend_minor")
        if spend_entry and spend_entry.get("currency"):
            spend_currency = str(spend_entry["currency"]).upper()
            currency = currency or spend_currency

        freshness = compute_freshness(observed_at) if observed_at else {
            "status": "unavailable",
            "age_seconds": None,
        }
        entities.append({
            "entity_id": eid,
            "entity_type": entity_type,
            "name": getattr(row, "name", None),
            "provider": getattr(row, "provider", None),
            "currency": currency,
            "metric_map": metric_map,
            "observed_at": observed_at,
            "freshness": freshness,
        })

    providers = {e["provider"] for e in entities}
    if len(providers) > 1:
        raise AdComparisonIncompatibleError(
            "entities from different providers cannot be compared",
            details={"providers": sorted(p for p in providers if p)},
        )

    currencies = {e["currency"] for e in entities if e["currency"]}
    if len(currencies) > 1:
        raise AdComparisonIncompatibleError(
            "entities with different currencies cannot be compared",
            details={"currencies": sorted(currencies)},
        )

    # Default metrics: union of observed keys excluding internal markers.
    if metric_keys is None:
        keys: set[str] = set()
        for e in entities:
            keys.update(k for k in e["metric_map"] if not k.startswith("__"))
        metric_keys = sorted(keys)

    warnings: list[str] = []
    if any(e["freshness"].get("status") in {"stale", "unavailable"} for e in entities):
        warnings.append("One or more entities have stale or unavailable metric freshness.")

    metrics_out: list[dict[str, Any]] = []
    # Pairwise: first entity is baseline (left), others compared to it.
    baseline = entities[0]
    for key in metric_keys:
        definition = get_metric_definition(key)
        direction = definition.direction if definition else "neutral"
        currency_behavior = definition.currency_behavior if definition else "currency_free"
        left_val = metric_decimal(baseline["metric_map"], key)
        entity_values = []
        for e in entities:
            val = metric_decimal(e["metric_map"], key)
            entry = e["metric_map"].get(key) or {}
            entity_values.append({
                "entity_id": str(e["entity_id"]),
                "value": str(val) if val is not None else None,
                "currency": entry.get("currency"),
                "availability": "observed" if val is not None else "missing",
            })
            if currency_behavior == "currency" and entry.get("currency"):
                if baseline["currency"] and entry["currency"].upper() != baseline["currency"]:
                    raise AdComparisonIncompatibleError(
                        "currency mismatch in metric values",
                        details={"metric_key": key, "currencies": [baseline["currency"], entry["currency"]]},
                    )
        deltas = []
        for e in entities[1:]:
            right_val = metric_decimal(e["metric_map"], key)
            deltas.append({
                "left_entity_id": str(baseline["entity_id"]),
                "right_entity_id": str(e["entity_id"]),
                **compute_metric_delta(left=left_val, right=right_val, direction=direction),
            })
        metrics_out.append({
            "metric_key": key,
            "direction": direction,
            "currency_behavior": currency_behavior,
            "values": entity_values,
            "deltas_vs_baseline": deltas,
            "note": (
                "Favorable side is only indicated when metric semantics support "
                "higher_is_better or lower_is_better; spend and similar neutral "
                "metrics are never auto-labeled as better."
                if direction == "neutral"
                else None
            ),
        })

    sample_coverage = {
        "entities_with_metrics": sum(1 for e in entities if e["metric_map"]),
        "entities_total": len(entities),
    }

    return {
        "entity_type": entity_type,
        "engine_version": COMPARISON_ENGINE_VERSION,
        "measurement_period": {
            "kind": "latest_snapshot",
            "baseline_observed_at": (
                baseline["observed_at"].isoformat() if baseline["observed_at"] else None
            ),
        },
        "currency": next(iter(currencies), None),
        "provider": next(iter(providers), None),
        "entities": [
            {
                "entity_id": str(e["entity_id"]),
                "entity_type": e["entity_type"],
                "name": e["name"],
                "provider": e["provider"],
                "currency": e["currency"],
                "observed_at": e["observed_at"].isoformat() if e["observed_at"] else None,
                "freshness": e["freshness"],
            }
            for e in entities
        ],
        "metrics": metrics_out,
        "sample_coverage": sample_coverage,
        "data_quality_warnings": warnings,
        "attribution_method": None,  # filled by caller when attribution context exists
        "read_only": True,
        "kind": "OBSERVED",
        "generated_at": _utcnow().isoformat(),
    }


__all__ = ["compute_metric_delta", "compare_entities"]
