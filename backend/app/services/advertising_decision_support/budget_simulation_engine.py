"""Deterministic hypothetical budget allocation simulator.

THIS IS NOT A PREDICTION ENGINE. Simulations store user-entered assumptions and
mechanical allocation math alongside server-observed reference metrics. They
never modify provider budgets and never accept client-injected observed metrics.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCampaign
from app.models.advertising_decision_support import (
    BUDGET_SIMULATION_ENGINE_VERSION,
    TenantAdBudgetSimulation,
    TenantAdBudgetSimulationItem,
)
from app.services.advertising_decision_support.errors import (
    AdEntityNotFoundError,
    AdSimulationNotFoundError,
    AdSimulationValidationError,
)
from app.services.advertising_decision_support.limits import (
    ALLOCATION_SUM_TOLERANCE,
    MAX_SIMULATION_REQUESTS_PER_TENANT_PER_HOUR,
    enforce_rate_limit,
    enforce_simulation_entity_count,
)
from app.services.advertising_intelligence._entity_metrics import (
    latest_metric_map,
    metric_decimal,
)
from app.services.advertising_intelligence.errors import AdCurrencyMismatchError
from app.services.advertising_intelligence.freshness_service import compute_freshness
from app.services.advertising_intelligence.spend_service import entity_spend
from app.services.automation_domain_events import emit_domain_event

SIMULATION_DISCLAIMER = (
    "Simulation does not predict future advertising performance "
    "and does not modify provider budgets."
)

_REFERENCE_METRIC_KEYS = (
    "spend_minor",
    "impressions",
    "clicks",
    "conversions",
    "ctr",
    "cpa_minor",
    "roas",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def compute_allocation(
    total_budget_minor: int,
    allocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pure allocation: ``allocation_pct`` is a fraction 0–1 summing to ~1.0.

    Returns items with ``simulated_budget_minor`` and ``simulated_share``.
    Remainder cents are assigned to the last item so the sum matches total.
    """
    if total_budget_minor < 0:
        raise AdSimulationValidationError(
            "total_budget_minor must be >= 0",
            details={"total_budget_minor": total_budget_minor},
        )
    if not allocations:
        raise AdSimulationValidationError("at least one allocation is required")

    out: list[dict[str, Any]] = []
    assigned = 0
    for i, raw in enumerate(allocations):
        campaign_id = raw["campaign_id"]
        pct = _dec(raw["allocation_pct"])
        if pct < 0 or pct > 1:
            raise AdSimulationValidationError(
                "allocation_pct must be between 0 and 1",
                details={"campaign_id": str(campaign_id), "allocation_pct": str(pct)},
            )
        if i < len(allocations) - 1:
            minor = int((Decimal(total_budget_minor) * pct).to_integral_value(rounding=ROUND_HALF_UP))
            assigned += minor
        else:
            minor = max(total_budget_minor - assigned, 0)
        share = (
            (Decimal(minor) / Decimal(total_budget_minor))
            if total_budget_minor > 0
            else Decimal("0")
        )
        out.append({
            "campaign_id": campaign_id,
            "allocation_pct": pct,
            "simulated_budget_minor": int(minor),
            "simulated_share": share,
        })
    return out


def _input_fingerprint(
    *,
    campaign_allocations: list[dict[str, Any]],
    total_budget_minor: int,
    currency: str,
    window_key: str,
    assumptions: dict[str, Any] | None,
) -> str:
    payload = {
        "allocations": sorted(
            [
                {
                    "campaign_id": str(a["campaign_id"]),
                    "allocation_pct": str(_dec(a["allocation_pct"])),
                }
                for a in campaign_allocations
            ],
            key=lambda x: x["campaign_id"],
        ),
        "total_budget_minor": int(total_budget_minor),
        "currency": currency.upper(),
        "window_key": window_key,
        "assumptions": assumptions or {},
        "engine_version": BUDGET_SIMULATION_ENGINE_VERSION,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _serialize_simulation(sim: TenantAdBudgetSimulation, items: list[TenantAdBudgetSimulationItem]) -> dict[str, Any]:
    return {
        "id": str(sim.id),
        "tenant_id": str(sim.tenant_id),
        "currency": sim.currency,
        "total_budget_minor": sim.total_budget_minor,
        "measurement_window_key": sim.measurement_window_key,
        "window_start": sim.window_start.isoformat() if sim.window_start else None,
        "window_end": sim.window_end.isoformat() if sim.window_end else None,
        "engine_version": sim.engine_version,
        "input_fingerprint": sim.input_fingerprint,
        "assumptions_json": sim.assumptions_json,
        "summary_json": sim.summary_json,
        "warnings_json": sim.warnings_json,
        "disclaimer": sim.disclaimer,
        "created_by_user_id": str(sim.created_by_user_id) if sim.created_by_user_id else None,
        "created_at": sim.created_at.isoformat() if sim.created_at else None,
        "kind": "SIMULATED",
        "read_only": True,
        "items": [
            {
                "id": str(item.id),
                "campaign_id": str(item.campaign_id),
                "campaign_name": item.campaign_name,
                "observed_spend_minor": item.observed_spend_minor,
                "observed_share": str(item.observed_share) if item.observed_share is not None else None,
                "allocation_pct": str(item.allocation_pct),
                "simulated_budget_minor": item.simulated_budget_minor,
                "simulated_share": str(item.simulated_share),
                "historical_reference_metrics": item.historical_reference_metrics,
                "freshness_status": item.freshness_status,
                "warnings_json": item.warnings_json,
            }
            for item in items
        ],
    }


async def create_simulation(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    campaign_allocations: list[dict[str, Any]],
    total_budget_minor: int,
    currency: str,
    window_key: str = "lifetime",
    assumptions: dict[str, Any] | None = None,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """Create an immutable budget simulation from server-observed spend."""
    enforce_simulation_entity_count(len(campaign_allocations))
    if total_budget_minor < 0:
        raise AdSimulationValidationError(
            "total_budget_minor must be >= 0",
            details={"total_budget_minor": total_budget_minor},
        )
    currency = (currency or "").upper()
    if len(currency) != 3:
        raise AdSimulationValidationError(
            "currency must be a 3-letter code",
            details={"currency": currency},
        )

    # Reject client-injected observed metrics.
    for raw in campaign_allocations:
        for forbidden in (
            "observed_spend_minor",
            "observed_share",
            "historical_reference_metrics",
            "spend_minor",
            "metrics",
        ):
            if forbidden in raw:
                raise AdSimulationValidationError(
                    "client must not inject observed metrics",
                    details={"forbidden_key": forbidden},
                )

    campaign_ids = [UUID(str(a["campaign_id"])) for a in campaign_allocations]
    if len(set(campaign_ids)) != len(campaign_ids):
        raise AdSimulationValidationError("duplicate campaign_id in allocations")

    pct_sum = sum(_dec(a["allocation_pct"]) for a in campaign_allocations)
    if abs(pct_sum - Decimal("1")) > Decimal(str(ALLOCATION_SUM_TOLERANCE)):
        raise AdSimulationValidationError(
            "allocation percentages must sum to approximately 1.0",
            details={"sum": str(pct_sum), "tolerance": ALLOCATION_SUM_TOLERANCE},
        )

    since = _utcnow() - timedelta(hours=1)
    recent_count = (
        await db.execute(
            select(func.count())
            .select_from(TenantAdBudgetSimulation)
            .where(
                TenantAdBudgetSimulation.tenant_id == tenant_id,
                TenantAdBudgetSimulation.created_at >= since,
            )
        )
    ).scalar_one()
    enforce_rate_limit(
        int(recent_count or 0),
        MAX_SIMULATION_REQUESTS_PER_TENANT_PER_HOUR,
        "simulation_requests_per_hour",
    )

    campaigns = list(
        (
            await db.execute(
                select(TenantAdCampaign).where(
                    TenantAdCampaign.tenant_id == tenant_id,
                    TenantAdCampaign.id.in_(campaign_ids),
                )
            )
        ).scalars().all()
    )
    by_id = {c.id: c for c in campaigns}
    for cid in campaign_ids:
        if cid not in by_id:
            raise AdEntityNotFoundError(
                "advertising campaign not found",
                details={"entity_type": "campaign", "entity_id": str(cid)},
            )

    # Currency consistency across campaigns vs simulation currency.
    for campaign in campaigns:
        budget_cur = (campaign.budget_currency or "").upper() or None
        if budget_cur and budget_cur != currency:
            raise AdCurrencyMismatchError(
                "campaign budget currency does not match simulation currency",
                details={
                    "campaign_id": str(campaign.id),
                    "campaign_currency": budget_cur,
                    "simulation_currency": currency,
                },
            )

    computed = compute_allocation(total_budget_minor, campaign_allocations)
    computed_by_id = {UUID(str(row["campaign_id"])): row for row in computed}

    observed_pairs: list[tuple[UUID, int | None, str | None]] = []
    for cid in campaign_ids:
        spend_minor, spend_currency = await entity_spend(db, tenant_id, "campaign", cid)
        if spend_currency and spend_currency.upper() != currency:
            raise AdCurrencyMismatchError(
                "observed spend currency does not match simulation currency",
                details={
                    "campaign_id": str(cid),
                    "spend_currency": spend_currency.upper(),
                    "simulation_currency": currency,
                },
            )
        observed_pairs.append((cid, spend_minor, spend_currency))

    total_observed = sum(s for _, s, _ in observed_pairs if s is not None)
    warnings: list[str] = []
    items_out: list[TenantAdBudgetSimulationItem] = []

    fingerprint = _input_fingerprint(
        campaign_allocations=campaign_allocations,
        total_budget_minor=total_budget_minor,
        currency=currency,
        window_key=window_key,
        assumptions=assumptions,
    )

    sim = TenantAdBudgetSimulation(
        tenant_id=tenant_id,
        currency=currency,
        total_budget_minor=int(total_budget_minor),
        measurement_window_key=window_key,
        engine_version=BUDGET_SIMULATION_ENGINE_VERSION,
        input_fingerprint=fingerprint,
        assumptions_json=assumptions,
        disclaimer=SIMULATION_DISCLAIMER,
        created_by_user_id=user_id,
    )
    db.add(sim)
    await db.flush()

    for cid, spend_minor, _spend_cur in observed_pairs:
        campaign = by_id[cid]
        alloc = computed_by_id[cid]
        metric_map = await latest_metric_map(db, tenant_id, "campaign", cid)
        observed_at = None
        obs_entry = metric_map.pop("__observed_at__", None)
        if obs_entry and obs_entry.get("value"):
            observed_at = obs_entry["value"]
        freshness = compute_freshness(observed_at)
        item_warnings: list[str] = []
        if freshness.get("status") in {"stale", "unavailable"}:
            item_warnings.append(f"Metrics freshness is {freshness.get('status')}.")
            warnings.append(f"Campaign {cid}: freshness {freshness.get('status')}.")

        reference: dict[str, Any] = {}
        for key in _REFERENCE_METRIC_KEYS:
            val = metric_decimal(metric_map, key)
            if val is None:
                continue
            entry = metric_map.get(key) or {}
            reference[key] = {
                "value": str(val),
                "currency": entry.get("currency"),
                "kind": "OBSERVED",
            }

        observed_share = None
        if spend_minor is not None and total_observed > 0:
            observed_share = Decimal(spend_minor) / Decimal(total_observed)
        elif spend_minor is None:
            item_warnings.append("No observed spend available for this campaign.")

        item = TenantAdBudgetSimulationItem(
            tenant_id=tenant_id,
            simulation_id=sim.id,
            campaign_id=cid,
            campaign_name=campaign.name,
            observed_spend_minor=spend_minor,
            observed_share=observed_share,
            allocation_pct=alloc["allocation_pct"],
            simulated_budget_minor=alloc["simulated_budget_minor"],
            simulated_share=alloc["simulated_share"],
            historical_reference_metrics=reference or None,
            freshness_status=freshness.get("status"),
            warnings_json={"warnings": item_warnings} if item_warnings else None,
        )
        db.add(item)
        items_out.append(item)

    sim.summary_json = {
        "campaign_count": len(campaign_ids),
        "total_observed_spend_minor": total_observed,
        "kind": "SIMULATED",
        "label": "Hypothetical allocation — not a performance forecast",
    }
    sim.warnings_json = {"warnings": warnings} if warnings else None
    await db.flush()

    await emit_domain_event(
        db,
        "advertising.simulation_created",
        tenant_id,
        payload={
            "simulation_id": str(sim.id),
            "currency": currency,
            "total_budget_minor": int(total_budget_minor),
            "campaign_count": len(campaign_ids),
            "engine_version": BUDGET_SIMULATION_ENGINE_VERSION,
            "input_fingerprint": fingerprint,
        },
        actor_type="user" if user_id else "system",
        actor_id=user_id,
        resource_type="advertising_budget_simulation",
        resource_id=str(sim.id),
        title="Advertising budget simulation created",
    )
    return _serialize_simulation(sim, items_out)


async def get_simulation(
    db: AsyncSession,
    tenant_id: UUID,
    simulation_id: UUID,
) -> dict[str, Any]:
    sim = (
        await db.execute(
            select(TenantAdBudgetSimulation).where(
                TenantAdBudgetSimulation.tenant_id == tenant_id,
                TenantAdBudgetSimulation.id == simulation_id,
            )
        )
    ).scalar_one_or_none()
    if sim is None:
        raise AdSimulationNotFoundError(
            "budget simulation not found",
            details={"simulation_id": str(simulation_id)},
        )
    items = list(
        (
            await db.execute(
                select(TenantAdBudgetSimulationItem)
                .where(
                    TenantAdBudgetSimulationItem.tenant_id == tenant_id,
                    TenantAdBudgetSimulationItem.simulation_id == simulation_id,
                )
                .order_by(TenantAdBudgetSimulationItem.created_at.asc())
            )
        ).scalars().all()
    )
    return _serialize_simulation(sim, items)


async def list_simulations(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    total = (
        await db.execute(
            select(func.count())
            .select_from(TenantAdBudgetSimulation)
            .where(TenantAdBudgetSimulation.tenant_id == tenant_id)
        )
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(TenantAdBudgetSimulation)
                .where(TenantAdBudgetSimulation.tenant_id == tenant_id)
                .order_by(TenantAdBudgetSimulation.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
    )
    results: list[dict[str, Any]] = []
    for sim in rows:
        items = list(
            (
                await db.execute(
                    select(TenantAdBudgetSimulationItem).where(
                        TenantAdBudgetSimulationItem.tenant_id == tenant_id,
                        TenantAdBudgetSimulationItem.simulation_id == sim.id,
                    )
                )
            ).scalars().all()
        )
        results.append(_serialize_simulation(sim, items))
    return results, int(total or 0)


__all__ = [
    "SIMULATION_DISCLAIMER",
    "compute_allocation",
    "create_simulation",
    "get_simulation",
    "list_simulations",
]
