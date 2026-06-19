"""Revenue Engine v1 — deal pipeline, forecasting, and factory revenue analytics (read-only)."""
from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.client import Client
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.services.buyer_acquisition_engine_service import BuyerAcquisitionEngineService
from app.services.real_factory_pilot_service import RealFactoryPilotService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Revenue Engine]"

DEAL_STAGES: tuple[str, ...] = (
    "lead",
    "qualified",
    "negotiation",
    "quotation",
    "sample",
    "contract",
    "won",
    "lost",
)

_STAGE_LABELS: dict[str, str] = {
    "lead": "Lead",
    "qualified": "Qualified",
    "negotiation": "Negotiation",
    "quotation": "Quotation",
    "sample": "Sample",
    "contract": "Contract",
    "won": "Won",
    "lost": "Lost",
}

_ACTIVE_STAGES = frozenset({
    "lead", "qualified", "negotiation", "quotation", "sample", "contract",
})

_STAGE_DEFAULT_PROB: dict[str, int] = {
    "lead": 5,
    "qualified": 15,
    "negotiation": 30,
    "quotation": 45,
    "sample": 55,
    "contract": 75,
    "won": 100,
    "lost": 0,
}

_LEAD_TO_STAGE: dict[str, str] = {
    "new": "lead",
    "contacted": "lead",
    "qualified": "qualified",
    "proposal_sent": "quotation",
    "negotiation": "negotiation",
    "won": "won",
    "lost": "lost",
}

_DEAL_TO_STAGE: dict[str, str] = {
    "new": "lead",
    "proposal": "quotation",
    "contract": "contract",
    "invoice": "contract",
    "waiting_payment": "contract",
    "won": "won",
    "lost": "lost",
}

_ACTION_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "open_buyer_acquisition_engine",
        "Open Buyer Acquisition Engine",
        "Review buyer matches and pipeline for revenue opportunities.",
        "/buyer-acquisition-engine",
    ),
    (
        "open_crm",
        "Open CRM",
        "Review deals and leads in CRM — manual actions only.",
        "/crm",
    ),
    (
        "open_real_factory_pilot",
        "Open Real Factory Pilot",
        "Check pilot readiness and factory workspace for revenue tracking.",
        "/real-factory-pilot",
    ),
    (
        "open_factory_platform",
        "Open Factory Platform",
        "Review factory profile, catalog, and export markets.",
        "/factory-platform",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Read-only revenue intelligence and deal management — no payments, invoicing, "
        "accounting, ERP integration, or automatic CRM updates."
    )


def _decimal_float(val: Decimal | None) -> float:
    if val is None:
        return 0.0
    return float(val)


class RevenueEngineService:
    @staticmethod
    def _resolve_stage(lead: CrmLead | None, deal: CrmDeal) -> str:
        deal_status = (deal.status or "new").lower()
        if deal_status in ("won", "lost"):
            return _DEAL_TO_STAGE.get(deal_status, deal_status)
        if deal_status in _DEAL_TO_STAGE:
            mapped = _DEAL_TO_STAGE[deal_status]
            if mapped not in ("won", "lost"):
                return mapped
        if lead:
            lead_status = (lead.status or "new").lower()
            return _LEAD_TO_STAGE.get(lead_status, "lead")
        return "lead"

    @staticmethod
    def _deal_value(deal: CrmDeal, lead: CrmLead | None) -> float:
        if deal.deal_amount is not None:
            return _decimal_float(deal.deal_amount)
        if deal.expected_value is not None:
            return _decimal_float(deal.expected_value)
        if lead and lead.estimated_value is not None:
            return _decimal_float(lead.estimated_value)
        return 0.0

    @staticmethod
    def _deal_probability(stage: str, deal: CrmDeal) -> int:
        if stage == "won":
            return 100
        if stage == "lost":
            return 0
        prob = deal.probability
        if prob is not None and prob > 0:
            return _clamp(prob)
        return _STAGE_DEFAULT_PROB.get(stage, 10)

    @staticmethod
    async def _resolve_scope(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> tuple[UUID | None, list[UUID] | None]:
        return await TenantService.resolve_tenant_client_scope(
            db, tenant_id=tenant_id, client_id=client_id,
        )

    @staticmethod
    async def _load_deals(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        client_ids: list[UUID] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        errors: list[str] = []
        try:
            q = (
                select(CrmDeal)
                .options(
                    selectinload(CrmDeal.lead),
                    selectinload(CrmDeal.client),
                )
            )
            if client_id:
                q = q.where(CrmDeal.client_id == client_id)
            elif client_ids:
                q = q.where(CrmDeal.client_id.in_(client_ids))
            rows = await db.execute(q)
            deals = list(rows.scalars().all())
        except Exception as exc:
            logger.info("%s load deals: %s", MARKER, exc)
            return [], [f"crm_deals: {exc}"]

        records: list[dict[str, Any]] = []
        for deal in deals:
            lead = deal.lead
            stage = RevenueEngineService._resolve_stage(lead, deal)
            if stage not in DEAL_STAGES:
                stage = "lead"
            value = RevenueEngineService._deal_value(deal, lead)
            prob = RevenueEngineService._deal_probability(stage, deal)
            buyer_name = lead.name if lead else None
            buyer_company = (lead.company or lead.name) if lead else None
            factory_name = deal.client.company_name if deal.client else None
            sources = ["crm"]
            if lead and lead.source:
                sources.append(f"lead:{lead.source}")

            records.append({
                "deal_id": deal.id,
                "title": deal.title,
                "buyer_name": buyer_name,
                "buyer_company": buyer_company,
                "factory_id": deal.client_id,
                "factory_name": factory_name,
                "value": round(value, 2),
                "currency": deal.currency or "UZS",
                "stage": stage,
                "stage_label": _STAGE_LABELS[stage],
                "probability": prob,
                "expected_close_date": deal.expected_close_date,
                "lead_id": deal.lead_id,
                "crm_deal_status": deal.status,
                "lead_status": lead.status if lead else None,
                "sources": sources,
                "weighted_value": round(value * prob / 100.0, 2),
            })
        return records, errors

    @staticmethod
    def _pipeline_metrics(deals: list[dict[str, Any]]) -> dict[str, Any]:
        stage_counts: Counter[str] = Counter()
        stage_values: dict[str, float] = defaultdict(float)
        stage_weighted: dict[str, float] = defaultdict(float)

        for d in deals:
            st = d["stage"]
            stage_counts[st] += 1
            stage_values[st] += d["value"]
            stage_weighted[st] += d["weighted_value"]

        stages = [
            {
                "stage": st,
                "label": _STAGE_LABELS[st],
                "count": stage_counts.get(st, 0),
                "value": round(stage_values.get(st, 0.0), 2),
                "weighted_value": round(stage_weighted.get(st, 0.0), 2),
            }
            for st in DEAL_STAGES
        ]
        active = sum(stage_counts.get(st, 0) for st in _ACTIVE_STAGES)
        pipeline_value = sum(d["value"] for d in deals if d["stage"] in _ACTIVE_STAGES)
        weighted = sum(d["weighted_value"] for d in deals if d["stage"] in _ACTIVE_STAGES)

        return {
            "stages": stages,
            "total_deals": len(deals),
            "active_deals": active,
            "pipeline_value": round(pipeline_value, 2),
            "weighted_pipeline_value": round(weighted, 2),
        }

    @staticmethod
    def _forecast_metrics(deals: list[dict[str, Any]]) -> dict[str, Any]:
        active_deals = [d for d in deals if d["stage"] in _ACTIVE_STAGES]
        won = [d for d in deals if d["stage"] == "won"]
        lost = [d for d in deals if d["stage"] == "lost"]

        pipeline_value = sum(d["value"] for d in active_deals)
        weighted = sum(d["weighted_value"] for d in active_deals)
        won_revenue = sum(d["value"] for d in won)
        lost_revenue = sum(d["value"] for d in lost)
        expected = weighted + won_revenue * 0.1

        deals_with_value = sum(1 for d in deals if d["value"] > 0)
        deals_with_close = sum(1 for d in active_deals if d.get("expected_close_date"))
        quality = "low"
        if deals:
            ratio = deals_with_value / len(deals)
            close_ratio = deals_with_close / max(len(active_deals), 1)
            if ratio >= 0.6 and close_ratio >= 0.4:
                quality = "high"
            elif ratio >= 0.35 or close_ratio >= 0.25:
                quality = "medium"

        return {
            "pipeline_value": round(pipeline_value, 2),
            "weighted_pipeline_value": round(weighted, 2),
            "expected_revenue": round(expected, 2),
            "won_revenue": round(won_revenue, 2),
            "lost_revenue": round(lost_revenue, 2),
            "forecast_quality": quality,
            "active_deals": len(active_deals),
            "won_deals": len(won),
            "lost_deals": len(lost),
        }

    @staticmethod
    def _factory_views(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_factory: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for d in deals:
            by_factory[d["factory_id"]].append(d)

        views: list[dict[str, Any]] = []
        for factory_id, factory_deals in by_factory.items():
            name = factory_deals[0].get("factory_name") or "Factory"
            active = [d for d in factory_deals if d["stage"] in _ACTIVE_STAGES]
            won = [d for d in factory_deals if d["stage"] == "won"]
            lost = [d for d in factory_deals if d["stage"] == "lost"]
            pipeline_value = sum(d["value"] for d in active)
            weighted = sum(d["weighted_value"] for d in active)
            won_revenue = sum(d["value"] for d in won)
            all_with_value = [d for d in factory_deals if d["value"] > 0]
            avg_size = (
                sum(d["value"] for d in all_with_value) / len(all_with_value)
                if all_with_value else 0.0
            )
            views.append({
                "factory_id": factory_id,
                "factory_name": name,
                "tenant_id": None,
                "active_deals": len(active),
                "won_deals": len(won),
                "lost_deals": len(lost),
                "pipeline_value": round(pipeline_value, 2),
                "weighted_pipeline_value": round(weighted, 2),
                "expected_revenue": round(weighted, 2),
                "won_revenue": round(won_revenue, 2),
                "average_deal_size": round(avg_size, 2),
                "currency": factory_deals[0].get("currency", "UZS"),
            })
        views.sort(key=lambda x: (-x["pipeline_value"], x["factory_name"]))
        return views

    @staticmethod
    def _opportunities(deals: list[dict[str, Any]]) -> dict[str, Any]:
        active = sorted(
            [d for d in deals if d["stage"] in _ACTIVE_STAGES],
            key=lambda x: (-x["weighted_value"], -x["value"]),
        )
        top_opps = [
            {
                "opportunity_id": f"deal-{d['deal_id']}",
                "title": d["title"],
                "subtitle": d.get("buyer_company") or d.get("buyer_name"),
                "buyer_name": d.get("buyer_company") or d.get("buyer_name"),
                "factory_name": d.get("factory_name"),
                "value": d["value"],
                "stage": d["stage"],
                "probability": d["probability"],
                "score": _clamp(int(d["probability"] * 0.6 + min(100, d["value"] / 10000))),
                "sources": d.get("sources", []),
                "recommended_action": "Review deal in CRM — manual follow-up only",
            }
            for d in active[:15]
        ]

        buyer_totals: dict[str, dict[str, Any]] = {}
        for d in active:
            key = (d.get("buyer_company") or d.get("buyer_name") or "Unknown").strip()
            if key not in buyer_totals:
                buyer_totals[key] = {"name": key, "value": 0.0, "deals": 0, "weighted": 0.0}
            buyer_totals[key]["value"] += d["value"]
            buyer_totals[key]["weighted"] += d["weighted_value"]
            buyer_totals[key]["deals"] += 1

        top_buyers = sorted(buyer_totals.values(), key=lambda x: -x["value"])[:10]
        highest_buyers = [
            {
                "opportunity_id": f"buyer-{b['name'][:40].lower().replace(' ', '-')}",
                "title": b["name"],
                "subtitle": f"{b['deals']} deal(s)",
                "buyer_name": b["name"],
                "factory_name": None,
                "value": round(b["value"], 2),
                "stage": None,
                "probability": 0,
                "score": _clamp(int(min(100, b["value"] / 5000))),
                "sources": ["crm"],
                "recommended_action": "Prioritize high-value buyer relationships in CRM",
            }
            for b in top_buyers
        ]

        factory_views = RevenueEngineService._factory_views(deals)
        highest_factories = [
            {
                "opportunity_id": f"factory-{f['factory_id']}",
                "title": f["factory_name"],
                "subtitle": f"{f['active_deals']} active · {f['won_deals']} won",
                "buyer_name": None,
                "factory_name": f["factory_name"],
                "value": f["pipeline_value"],
                "stage": None,
                "probability": 0,
                "score": _clamp(int(min(100, f["pipeline_value"] / 10000))),
                "sources": ["crm"],
                "recommended_action": "Open factory platform for revenue performance review",
            }
            for f in factory_views[:10]
        ]

        return {
            "top_revenue_opportunities": top_opps,
            "highest_value_buyers": highest_buyers,
            "highest_value_factories": highest_factories,
            "total": len(top_opps) + len(highest_buyers) + len(highest_factories),
        }

    @staticmethod
    def _health_metrics(
        deals: list[dict[str, Any]],
        forecast: dict[str, Any],
    ) -> dict[str, Any]:
        active = forecast["active_deals"]
        won = forecast["won_deals"]
        lost = forecast["lost_deals"]
        closed = won + lost
        win_rate = (won / closed * 100.0) if closed > 0 else 0.0

        target_coverage = 1_000_000.0
        pipeline_value = forecast["pipeline_value"]
        coverage_ratio = pipeline_value / target_coverage if target_coverage else 0.0

        factors: list[dict[str, Any]] = []

        if coverage_ratio >= 0.5:
            cov_status = "healthy"
            cov_score = _clamp(int(coverage_ratio * 100))
        elif coverage_ratio >= 0.2:
            cov_status = "warning"
            cov_score = _clamp(int(coverage_ratio * 80))
        else:
            cov_status = "critical"
            cov_score = _clamp(int(coverage_ratio * 50))

        factors.append({
            "key": "pipeline_coverage",
            "label": "Pipeline coverage",
            "status": cov_status,
            "score": cov_score,
            "message": f"Active pipeline {pipeline_value:,.0f} vs coverage target",
        })

        if active >= 5:
            act_status = "healthy"
            act_score = min(100, active * 12)
        elif active >= 2:
            act_status = "warning"
            act_score = active * 20
        else:
            act_status = "critical"
            act_score = max(10, active * 15)

        factors.append({
            "key": "active_deals",
            "label": "Active deals",
            "status": act_status,
            "score": _clamp(act_score),
            "message": f"{active} active deal(s) in pipeline",
        })

        if win_rate >= 30:
            wr_status = "healthy"
        elif win_rate >= 15 or closed == 0:
            wr_status = "warning"
        else:
            wr_status = "critical"

        factors.append({
            "key": "win_rate",
            "label": "Win rate",
            "status": wr_status,
            "score": _clamp(int(win_rate)) if closed else 50,
            "message": f"{win_rate:.1f}% win rate ({won} won / {closed} closed)" if closed else "No closed deals yet",
        })

        fq = forecast.get("forecast_quality", "medium")
        if fq == "high":
            fq_status = "healthy"
            fq_score = 85
        elif fq == "medium":
            fq_status = "warning"
            fq_score = 55
        else:
            fq_status = "critical"
            fq_score = 25

        factors.append({
            "key": "forecast_quality",
            "label": "Forecast quality",
            "status": fq_status,
            "score": fq_score,
            "message": f"Forecast data quality: {fq}",
        })

        status_rank = {"critical": 0, "warning": 1, "healthy": 2}
        worst = min(factors, key=lambda f: status_rank.get(f["status"], 1))
        overall_status = worst["status"]
        health_score = _clamp(int(sum(f["score"] for f in factors) / len(factors))) if factors else 0

        return {
            "status": overall_status,
            "health_score": health_score,
            "factors": factors,
            "pipeline_coverage_ratio": round(coverage_ratio, 3),
            "win_rate": round(win_rate, 2),
            "active_deals": active,
            "forecast_quality": fq,
        }

    @staticmethod
    def _readiness_score(
        deals: list[dict[str, Any]],
        health: dict[str, Any],
        forecast: dict[str, Any],
    ) -> int:
        if not deals:
            return 10
        base = min(35, len(deals) * 5)
        active_bonus = min(25, forecast["active_deals"] * 5)
        value_bonus = min(20, int(forecast["pipeline_value"] / 50000))
        health_bonus = int(health["health_score"] * 0.2)
        return _clamp(base + active_bonus + value_bonus + health_bonus)

    @staticmethod
    def _executive_dashboard(
        deals: list[dict[str, Any]],
        forecast: dict[str, Any],
        pipeline: dict[str, Any],
    ) -> dict[str, Any]:
        active_opps = sum(1 for d in deals if d["stage"] in _ACTIVE_STAGES)
        return {
            "total_pipeline_value": pipeline["pipeline_value"],
            "forecasted_revenue": forecast["expected_revenue"],
            "won_revenue": forecast["won_revenue"],
            "lost_revenue": forecast["lost_revenue"],
            "active_opportunities": active_opps,
            "deal_count": len(deals),
            "weighted_pipeline_value": pipeline["weighted_pipeline_value"],
            "currency": "UZS",
        }

    @staticmethod
    def _guided_actions(
        *,
        tenant_id: UUID | None,
        client_id: UUID | None,
    ) -> list[dict[str, Any]]:
        tenant_q = f"?tenant_id={tenant_id}" if tenant_id else ""
        items: list[dict[str, Any]] = []
        for key, title, desc, route in _ACTION_SPECS:
            full_route = route
            if key in ("open_factory_platform", "open_buyer_acquisition_engine") and tenant_q:
                full_route = f"{route}{tenant_q}"
            items.append({
                "key": key,
                "title": title,
                "description": desc,
                "route": full_route,
                "enabled": True,
            })
        return items

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        async def _probe(module: str, coro: Any, message: str) -> None:
            try:
                await coro
                checks.append({"module": module, "status": "ok", "message": message, "details": {}})
            except Exception as exc:
                checks.append({
                    "module": module,
                    "status": "degraded",
                    "message": str(exc)[:200],
                    "details": {},
                })

        await _probe(
            "buyer_acquisition_engine",
            BuyerAcquisitionEngineService.overview(db),
            "Buyer Acquisition Engine overview reachable",
        )
        await _probe(
            "real_factory_pilot",
            RealFactoryPilotService.overview(db),
            "Real Factory Pilot overview reachable",
        )
        return checks

    @staticmethod
    async def _snapshot(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        resolved_id, client_ids = await RevenueEngineService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        deals, errors = await RevenueEngineService._load_deals(
            db, client_id=resolved_id, client_ids=client_ids,
        )
        pipeline = RevenueEngineService._pipeline_metrics(deals)
        forecast = RevenueEngineService._forecast_metrics(deals)
        health = RevenueEngineService._health_metrics(deals, forecast)
        opps = RevenueEngineService._opportunities(deals)
        factories = RevenueEngineService._factory_views(deals)
        executive = RevenueEngineService._executive_dashboard(deals, forecast, pipeline)
        readiness = RevenueEngineService._readiness_score(deals, health, forecast)

        return {
            "deals": deals,
            "errors": errors,
            "pipeline": pipeline,
            "forecast": forecast,
            "health": health,
            "opportunities": opps,
            "factories": factories,
            "executive": executive,
            "readiness_score": readiness,
            "resolved_client_id": resolved_id,
            "tenant_id": tenant_id,
        }

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        checks = await RevenueEngineService.integration_checks(db)
        guided = RevenueEngineService._guided_actions(
            tenant_id=snap.get("tenant_id"),
            client_id=snap.get("resolved_client_id"),
        )
        pipeline = snap["pipeline"]
        forecast = snap["forecast"]
        health = snap["health"]

        return {
            "executive_dashboard": snap["executive"],
            "forecast": {
                **forecast,
                "currency": "UZS",
                "errors": snap["errors"],
                "safety_notice": _safety_notice(),
            },
            "pipeline": {
                **pipeline,
                "currency": "UZS",
                "errors": snap["errors"],
                "safety_notice": _safety_notice(),
            },
            "health": {
                **health,
                "errors": snap["errors"],
                "safety_notice": _safety_notice(),
            },
            "top_opportunities": snap["opportunities"]["top_revenue_opportunities"][:8],
            "factory_count": len(snap["factories"]),
            "readiness_score": snap["readiness_score"],
            "integration_checks": checks,
            "guided_actions": guided,
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def list_deals(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        stage: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        items = snap["deals"]
        if stage:
            items = [d for d in items if d["stage"] == stage]
        items = sorted(items, key=lambda x: (-x["weighted_value"], -x["value"]))
        total = len(items)
        limit = clamp_limit(limit)
        page = items[skip: skip + limit]
        return {
            "items": page,
            "total": total,
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def pipeline(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            **snap["pipeline"],
            "currency": "UZS",
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def forecast(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            **snap["forecast"],
            "currency": "UZS",
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def factories(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        items = snap["factories"]
        total = len(items)
        limit = clamp_limit(limit)
        page = items[skip: skip + limit]
        return {
            "items": page,
            "total": total,
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        out = snap["opportunities"]
        out["errors"] = snap["errors"]
        out["safety_notice"] = _safety_notice()
        return out

    @staticmethod
    async def health(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            **snap["health"],
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            "executive_dashboard": snap["executive"],
            "health_status": snap["health"]["status"],
            "health_score": snap["health"]["health_score"],
            "readiness_score": snap["readiness_score"],
            "forecast_quality": snap["forecast"]["forecast_quality"],
            "win_rate": snap["health"]["win_rate"],
            "active_deals": snap["forecast"]["active_deals"],
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def guided_actions(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            "items": RevenueEngineService._guided_actions(
                tenant_id=snap.get("tenant_id"),
                client_id=snap.get("resolved_client_id"),
            ),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def refresh(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        logger.info(
            "%s refresh %.0fms deals=%s",
            MARKER, (time.perf_counter() - t0) * 1000, len(snap["deals"]),
        )
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": snap["readiness_score"],
            "health_status": snap["health"]["status"],
            "total_pipeline_value": snap["executive"]["total_pipeline_value"],
            "forecasted_revenue": snap["executive"]["forecasted_revenue"],
            "active_deals": snap["forecast"]["active_deals"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        top = snap["opportunities"]["top_revenue_opportunities"]
        top_opp = top[0] if top else None
        return {
            "readiness_score": snap["readiness_score"],
            "health_status": snap["health"]["status"],
            "health_score": snap["health"]["health_score"],
            "total_pipeline_value": snap["executive"]["total_pipeline_value"],
            "forecasted_revenue": snap["executive"]["forecasted_revenue"],
            "won_revenue": snap["executive"]["won_revenue"],
            "active_deals": snap["forecast"]["active_deals"],
            "deal_count": snap["executive"]["deal_count"],
            "top_opportunity_title": top_opp["title"] if top_opp else None,
            "top_opportunity_value": top_opp["value"] if top_opp else 0.0,
            "currency": "UZS",
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def executive_summary(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            "readiness_score": snap["readiness_score"],
            "health_status": snap["health"]["status"],
            "health_score": snap["health"]["health_score"],
            "total_pipeline_value": snap["executive"]["total_pipeline_value"],
            "forecasted_revenue": snap["executive"]["forecasted_revenue"],
            "won_revenue": snap["executive"]["won_revenue"],
            "active_deals": snap["forecast"]["active_deals"],
            "deal_count": snap["executive"]["deal_count"],
            "win_rate": snap["health"]["win_rate"],
            "top_opportunities": snap["opportunities"]["top_revenue_opportunities"][:5],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def revenue_impact_panel(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, tenant_id=tenant_id, client_id=client_id,
        )
        return {
            "readiness_score": snap["readiness_score"],
            "health_status": snap["health"]["status"],
            "total_pipeline_value": snap["executive"]["total_pipeline_value"],
            "forecasted_revenue": snap["executive"]["forecasted_revenue"],
            "won_revenue": snap["executive"]["won_revenue"],
            "active_deals": snap["forecast"]["active_deals"],
            "win_rate": snap["health"]["win_rate"],
            "top_opportunities": snap["opportunities"]["top_revenue_opportunities"][:5],
            "message": (
                f"Revenue engine readiness {snap['readiness_score']}/100 — "
                f"{snap['forecast']['active_deals']} active deal(s), "
                f"pipeline {snap['executive']['total_pipeline_value']:,.0f}"
            ),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def revenue_readiness_panel(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(db, tenant_id=tenant_id)
        return {
            "readiness_score": snap["readiness_score"],
            "health_status": snap["health"]["status"],
            "health_score": snap["health"]["health_score"],
            "total_pipeline_value": snap["executive"]["total_pipeline_value"],
            "forecasted_revenue": snap["executive"]["forecasted_revenue"],
            "active_deals": snap["forecast"]["active_deals"],
            "won_deals": snap["forecast"]["won_deals"],
            "forecast_quality": snap["forecast"]["forecast_quality"],
            "message": (
                f"Revenue readiness {snap['readiness_score']}/100 — "
                f"health {snap['health']['status']}, "
                f"{snap['forecast']['active_deals']} active deal(s)"
            ),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def revenue_performance_panel(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await RevenueEngineService._snapshot(
            db, tenant_id=tenant_id, client_id=client_id,
        )
        factories = snap["factories"]
        top_factory = factories[0] if factories else None
        return {
            "readiness_score": snap["readiness_score"],
            "total_pipeline_value": snap["executive"]["total_pipeline_value"],
            "forecasted_revenue": snap["executive"]["forecasted_revenue"],
            "won_revenue": snap["executive"]["won_revenue"],
            "active_deals": snap["forecast"]["active_deals"],
            "factory_count": len(factories),
            "top_factory_name": top_factory["factory_name"] if top_factory else None,
            "top_factory_pipeline": top_factory["pipeline_value"] if top_factory else 0.0,
            "average_deal_size": (
                sum(f["average_deal_size"] for f in factories) / len(factories)
                if factories else 0.0
            ),
            "currency": "UZS",
            "safety_notice": _safety_notice(),
        }
