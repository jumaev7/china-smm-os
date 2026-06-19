"""AI Revenue Forecasting v1 — heuristic revenue prediction (read-only)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.proposal_document import ProposalDocument
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.deal_risk_service import DealRiskService
from app.services.lead_intelligence_service import HOT_LEVELS, QUALIFIED_LEVELS
from app.services.sales_department_orchestrator import SalesDepartmentOrchestrator
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Revenue Forecast]"

PERIODS = ("7d", "30d", "90d")
_PERIOD_FACTORS = {"7d": Decimal("0.12"), "30d": Decimal("0.35"), "90d": Decimal("0.75")}

_STAGE_WIN_PROB = {
    "lead": 0.08,
    "qualified": 0.22,
    "proposal": 0.42,
    "negotiation": 0.65,
    "closing": 0.82,
}

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return Decimal("0")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


@dataclass
class _ForecastContext:
    now: datetime
    client_id: UUID | None = None
    client_ids: list[UUID] | None = None
    errors: list[str] = field(default_factory=list)
    snap: Any = None
    lead_metrics: dict[str, Any] = field(default_factory=dict)
    pipeline_stages: list[dict[str, Any]] = field(default_factory=list)
    total_pipeline_forecast: Decimal = Decimal("0")
    forecasts: list[dict[str, Any]] = field(default_factory=list)
    risks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    executive: dict[str, Any] = field(default_factory=dict)
    growth_opportunities: list[dict[str, Any]] = field(default_factory=list)
    inputs_summary: dict[str, Any] = field(default_factory=dict)
    confidence: str = "medium"


class RevenueForecastService:
    """Heuristic revenue forecasts from CRM, deals, proposals, intelligence, and department data."""

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_id, client_ids = await TenantService.resolve_tenant_client_scope(
            db, tenant_id=tenant_id, client_id=client_id,
        )
        ctx = await RevenueForecastService._build_overview_context(
            db, client_id=client_id, client_ids=client_ids,
        )
        return {
            "forecasts": ctx.forecasts,
            "currency": "UZS",
            "confidence": ctx.confidence,
            "inputs_summary": ctx.inputs_summary,
            "safety_notice": RevenueForecastService._safety_notice(),
            "errors": ctx.errors,
        }

    @staticmethod
    async def pipeline(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await RevenueForecastService._build_context(db, client_id=client_id)
        return {
            "stages": ctx.pipeline_stages,
            "total_pipeline_forecast": ctx.total_pipeline_forecast,
            "currency": "UZS",
            "errors": ctx.errors,
        }

    @staticmethod
    async def risks(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await RevenueForecastService._build_context(db, client_id=client_id)
        r = ctx.risks
        total = sum(len(v) for v in r.values())
        return {
            "inactive_deals": r.get("inactive_deals", []),
            "overdue_opportunities": r.get("overdue_opportunities", []),
            "proposals_at_risk": r.get("proposals_at_risk", []),
            "communication_risks": r.get("communication_risks", []),
            "total": total,
            "errors": ctx.errors,
        }

    @staticmethod
    async def executive(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await RevenueForecastService._build_context(db, client_id=client_id)
        return {
            "executive": ctx.executive,
            "forecasts": ctx.forecasts,
            "errors": ctx.errors,
        }

    @staticmethod
    async def generate_forecast(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await RevenueForecastService._build_context(db, client_id=client_id)
        logger.info("%s generated client=%s periods=%s", MARKER, client_id, len(ctx.forecasts))
        return {
            "forecasts": ctx.forecasts,
            "pipeline": ctx.pipeline_stages,
            "executive": ctx.executive,
            "risks_total": sum(len(v) for v in ctx.risks.values()),
            "currency": "UZS",
            "source": "heuristic",
            "generated_at": ctx.now,
            "safety_notice": RevenueForecastService._safety_notice(),
            "errors": ctx.errors,
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await RevenueForecastService._build_widget_context(db, client_id=client_id)
        f30 = next((f for f in ctx.forecasts if f["period"] == "30d"), None)
        return {
            "expected_30d": f30["expected_case"] if f30 else Decimal("0"),
            "best_case_30d": f30["best_case"] if f30 else Decimal("0"),
            "worst_case_30d": f30["worst_case"] if f30 else Decimal("0"),
            "pipeline_forecast": ctx.total_pipeline_forecast,
            "confidence": ctx.confidence,
            "top_growth": [
                {"title": g["title"], "expected_impact": g["expected_impact"], "priority": g["priority"]}
                for g in ctx.growth_opportunities[:3]
            ],
            "top_risks": [
                {"title": r["title"], "severity": r["severity"], "category": r["category"]}
                for r in RevenueForecastService._flatten_risks(ctx.risks)[:3]
            ],
            "currency": "UZS",
            "errors": ctx.errors,
        }

    @staticmethod
    async def _build_widget_context(
        db: AsyncSession,
        *,
        client_id: UUID | None,
    ) -> _ForecastContext:
        """Fast path for summary-widget — pipeline + lead metrics only (no department snapshot)."""
        from app.core.endpoint_guard import safe_section
        from app.services.lead_intelligence_service import LeadIntelligenceService

        errors: list[str] = []
        ctx = _ForecastContext(
            now=_utc_now(), client_id=client_id, errors=errors,
        )
        ctx.lead_metrics = await safe_section(
            "lead_intelligence",
            LeadIntelligenceService.metrics(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
            timeout=5.0,
        )
        await RevenueForecastService._load_pipeline_stages(db, ctx)
        RevenueForecastService._compute_period_forecasts(ctx)
        RevenueForecastService._build_growth_opportunities(ctx)
        RevenueForecastService._build_risks(ctx)
        return ctx

    @staticmethod
    async def _build_overview_context(
        db: AsyncSession,
        *,
        client_id: UUID | None,
        client_ids: list[UUID] | None = None,
    ) -> _ForecastContext:
        """Fast path for /overview — summary forecasts without department snapshot."""
        errors: list[str] = []
        ctx = _ForecastContext(
            now=_utc_now(), client_id=client_id, client_ids=client_ids, errors=errors,
        )
        ctx.lead_metrics = await RevenueForecastService._overview_lead_metrics(
            db, client_id=client_id, client_ids=client_ids,
        )
        await RevenueForecastService._load_pipeline_stages(db, ctx, max_records=300)
        RevenueForecastService._compute_period_forecasts(ctx)
        RevenueForecastService._build_inputs_summary_light(ctx)
        return ctx

    @staticmethod
    async def _overview_lead_metrics(
        db: AsyncSession,
        *,
        client_id: UUID | None,
        client_ids: list[UUID] | None,
    ) -> dict[str, Any]:
        """Aggregate SQL counts — avoids per-lead scans in LeadIntelligenceService.metrics."""
        from sqlalchemy import func, or_

        active = CrmLead.status.notin_(("won", "lost"))
        hot_cond = or_(
            CrmLead.qualification_level.in_(tuple(HOT_LEVELS)),
            CrmLead.lead_score >= 70,
        )
        qual_cond = CrmLead.qualification_level.in_(tuple(QUALIFIED_LEVELS))

        def _scoped(q):
            if client_id:
                return q.where(CrmLead.client_id == client_id)
            if client_ids is not None:
                if not client_ids:
                    return None
                return q.where(CrmLead.client_id.in_(client_ids))
            return q

        if client_ids is not None and not client_ids:
            return {
                "hot_leads": 0,
                "qualified_leads": 0,
                "neglected_leads": 0,
                "leads_without_activity": 0,
            }

        hot_q = _scoped(select(func.count()).select_from(CrmLead).where(active, hot_cond))
        qual_q = _scoped(select(func.count()).select_from(CrmLead).where(active, qual_cond))
        total_q = _scoped(select(func.count()).select_from(CrmLead).where(active))

        hot = int(await db.scalar(hot_q) or 0)
        qualified = int(await db.scalar(qual_q) or 0)
        total = int(await db.scalar(total_q) or 0)
        return {
            "hot_leads": hot,
            "qualified_leads": qualified,
            "neglected_leads": 0,
            "leads_without_activity": max(0, total - hot - qualified),
        }

    @staticmethod
    def _build_inputs_summary_light(ctx: _ForecastContext) -> None:
        ctx.inputs_summary = {
            "active_leads": int(ctx.lead_metrics.get("hot_leads") or 0)
            + int(ctx.lead_metrics.get("qualified_leads") or 0),
            "hot_leads": int(ctx.lead_metrics.get("hot_leads") or 0),
            "qualified_leads": int(ctx.lead_metrics.get("qualified_leads") or 0),
            "proposals_in_pipeline": next(
                (s["count"] for s in ctx.pipeline_stages if s["stage"] == "proposal"), 0
            ),
            "opportunities": sum(int(s.get("count") or 0) for s in ctx.pipeline_stages),
            "revenue_attribution_loaded": False,
            "communication_health": 50,
            "overdue_operator_tasks": 0,
            "pipeline_stages": len(ctx.pipeline_stages),
            "overview_mode": "summary",
        }

    @staticmethod
    async def forecast_recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Compact recommendations for Multi-Agent and department panels."""
        ctx = await RevenueForecastService._build_context(db, client_id=client_id)
        items: list[dict[str, Any]] = []
        f30 = next((f for f in ctx.forecasts if f["period"] == "30d"), None)
        if f30:
            items.append({
                "title": f"30-day expected revenue: {_quantize(f30['expected_case']):,.0f} UZS",
                "description": (
                    f"Range {_quantize(f30['worst_case']):,.0f} – {_quantize(f30['best_case']):,.0f} UZS "
                    f"({ctx.confidence} confidence). Manual review only."
                ),
                "priority": "high",
                "source": "revenue_forecast",
            })
        for g in ctx.growth_opportunities[: max(0, limit - len(items))]:
            items.append({
                "title": g["title"],
                "description": g.get("description", ""),
                "priority": g.get("priority", "medium"),
                "source": "revenue_forecast",
            })
        for r in RevenueForecastService._flatten_risks(ctx.risks)[: max(0, limit - len(items))]:
            items.append({
                "title": r["title"],
                "description": r.get("description", ""),
                "priority": "high" if r.get("severity") in ("critical", "high") else "medium",
                "source": "revenue_forecast",
            })
        return {"items": items[:limit], "total": len(items), "errors": ctx.errors}

    @staticmethod
    def _safety_notice() -> str:
        return (
            "Read-only forecasting — no automatic messaging, CRM updates, deal updates, or task execution."
        )

    @staticmethod
    def _flatten_risks(risks: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key in ("inactive_deals", "overdue_opportunities", "proposals_at_risk", "communication_risks"):
            out.extend(risks.get(key, []))
        return out

    @staticmethod
    async def _build_context(
        db: AsyncSession,
        *,
        client_id: UUID | None,
        client_ids: list[UUID] | None = None,
    ) -> _ForecastContext:
        errors: list[str] = []
        ctx = _ForecastContext(
            now=_utc_now(), client_id=client_id, client_ids=client_ids, errors=errors,
        )

        try:
            ctx.snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        except Exception as exc:
            logger.warning("%s snapshot failed: %s", MARKER, exc)
            errors.append(f"sales_department_snapshot: {exc}")

        if ctx.snap:
            ctx.lead_metrics = ctx.snap.lead_metrics or {}

        try:
            ctx.inputs_summary["deal_risk_confidence"] = await DealRiskService.forecast_confidence_inputs(
                db, client_id=client_id,
            )
        except Exception as exc:
            logger.warning("%s deal risk confidence failed: %s", MARKER, exc)
            errors.append(f"deal_risk: {exc}")

        await RevenueForecastService._load_pipeline_stages(db, ctx)
        RevenueForecastService._compute_period_forecasts(ctx)
        RevenueForecastService._build_risks(ctx)
        RevenueForecastService._build_growth_opportunities(ctx)
        RevenueForecastService._build_executive(ctx)
        RevenueForecastService._build_inputs_summary(ctx)
        try:
            from app.core.endpoint_guard import safe_section
            from app.models.client import Client
            from app.services.factory_profile_service import FactoryProfileService

            probe_tenant_id = None
            if client_id:
                client = await db.get(Client, client_id)
                if client and client.tenant_id:
                    probe_tenant_id = client.tenant_id

            factory_probe = await safe_section(
                "factory_platform",
                FactoryProfileService.integration_probe(db, tenant_id=probe_tenant_id),
                default={"ok": False},
                errors=ctx.errors,
                db=db,
            )
            ctx.inputs_summary["factory_platform"] = factory_probe
        except Exception:
            ctx.inputs_summary["factory_platform"] = {"ok": False}

        try:
            ctx.inputs_summary["buyer_contributions"] = await BuyerIntelligenceService.buyer_contributions(
                db, client_id=client_id, limit=5,
            )
        except Exception as exc:
            logger.warning("%s buyer contributions failed: %s", MARKER, exc)
            errors.append(f"buyer_intelligence: {exc}")

        return ctx

    @staticmethod
    async def _load_pipeline_stages(
        db: AsyncSession,
        ctx: _ForecastContext,
        *,
        max_records: int | None = None,
    ) -> None:
        client_id = ctx.client_id
        client_ids = ctx.client_ids
        lead_q = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
        deal_q = select(CrmDeal).where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)))
        prop_q = select(ProposalDocument).where(
            ProposalDocument.status.notin_(("accepted", "rejected")),
        )
        if client_id:
            lead_q = lead_q.where(CrmLead.client_id == client_id)
            deal_q = deal_q.where(CrmDeal.client_id == client_id)
            prop_q = prop_q.where(ProposalDocument.client_id == client_id)
            if max_records:
                lead_q = lead_q.limit(max_records)
                deal_q = deal_q.limit(max_records)
                prop_q = prop_q.limit(max_records)
            leads = list((await db.execute(lead_q)).scalars().all())
            deals = list((await db.execute(deal_q)).scalars().all())
            proposals = list((await db.execute(prop_q)).scalars().all())
        elif client_ids is not None:
            if not client_ids:
                leads, deals, proposals = [], [], []
            else:
                lead_q = lead_q.where(CrmLead.client_id.in_(client_ids))
                deal_q = deal_q.where(CrmDeal.client_id.in_(client_ids))
                prop_q = prop_q.where(ProposalDocument.client_id.in_(client_ids))
                if max_records:
                    lead_q = lead_q.limit(max_records)
                    deal_q = deal_q.limit(max_records)
                    prop_q = prop_q.limit(max_records)
                leads = list((await db.execute(lead_q)).scalars().all())
                deals = list((await db.execute(deal_q)).scalars().all())
                proposals = list((await db.execute(prop_q)).scalars().all())
        else:
            if max_records:
                lead_q = lead_q.limit(max_records)
                deal_q = deal_q.limit(max_records)
                prop_q = prop_q.limit(max_records)
            leads = list((await db.execute(lead_q)).scalars().all())
            deals = list((await db.execute(deal_q)).scalars().all())
            proposals = list((await db.execute(prop_q)).scalars().all())

        buckets: dict[str, list[Decimal]] = {
            "lead": [],
            "qualified": [],
            "proposal": [],
            "negotiation": [],
            "closing": [],
        }

        for lead in leads:
            val = _decimal(lead.estimated_value) or Decimal("5000000")
            level = (lead.qualification_level or "").lower()
            status = (lead.status or "new").lower()

            if status in ("negotiation",) or level == "opportunity":
                buckets["negotiation"].append(val)
            elif level in QUALIFIED_LEVELS or status == "qualified":
                buckets["qualified"].append(val)
            elif level in HOT_LEVELS or (lead.lead_score or 0) >= 70:
                buckets["qualified"].append(val * Decimal("1.1"))
            else:
                buckets["lead"].append(val * Decimal("0.6"))

        for deal in deals:
            val = _decimal(deal.expected_value) or _decimal(deal.deal_amount) or Decimal("10000000")
            status = (deal.status or "new").lower()
            prob = int(deal.probability or 10)

            if status == "waiting_payment" or prob >= 60:
                buckets["closing"].append(val)
            elif status in ("contract", "invoice"):
                buckets["negotiation"].append(val)
            elif status == "proposal":
                buckets["proposal"].append(val)
            else:
                buckets["lead"].append(val * Decimal("0.5"))

        for prop in proposals:
            val = Decimal("8000000")
            if prop.status in ("sent", "pending"):
                buckets["proposal"].append(val)
            else:
                buckets["proposal"].append(val * Decimal("0.7"))

        stages: list[dict[str, Any]] = []
        total = Decimal("0")
        for stage in ("lead", "qualified", "proposal", "negotiation", "closing"):
            values = buckets[stage]
            count = len(values)
            avg = sum(values, Decimal("0")) / max(count, 1) if count else Decimal("0")
            win = _STAGE_WIN_PROB[stage]
            forecast_rev = _quantize(avg * Decimal(str(count)) * Decimal(str(win)))
            total += forecast_rev
            stages.append({
                "stage": stage,
                "count": count,
                "forecast_revenue": forecast_rev,
                "win_probability": win,
            })

        ctx.pipeline_stages = stages
        ctx.total_pipeline_forecast = _quantize(total)

    @staticmethod
    def _compute_period_forecasts(ctx: _ForecastContext) -> None:
        snap = ctx.snap
        if snap:
            rev_forecast = (snap.revenue_forecast if snap else {}) or {}
            rev_overview = (snap.revenue_overview if snap else {}) or {}

            weighted = _decimal(rev_forecast.get("weighted_pipeline"))
            pipeline = _decimal(rev_forecast.get("pipeline_value") or rev_overview.get("total_pipeline_value"))
            closed = _decimal(rev_forecast.get("closed_revenue") or rev_overview.get("total_closed_revenue"))

            if weighted <= 0 and pipeline > 0:
                weighted = pipeline * Decimal("0.3")

            hot = int(ctx.lead_metrics.get("hot_leads") or (snap.executive_summary.get("hot_leads", 0) if snap else 0))
            qualified = int(ctx.lead_metrics.get("qualified_leads") or 0)
            comm_health = float(
                (snap.executive_summary.get("communication_health", 50) if snap else 50)
            )
            overdue = len(snap.overdue_actions) if snap else 0
            opp_count = len(snap.coordinated_opportunities) if snap else 0
        else:
            weighted = ctx.total_pipeline_forecast
            pipeline = ctx.total_pipeline_forecast
            closed = Decimal("0")
            hot = int(ctx.lead_metrics.get("hot_leads") or 0)
            qualified = int(ctx.lead_metrics.get("qualified_leads") or 0)
            comm_health = 50.0
            overdue = int(ctx.lead_metrics.get("neglected_leads") or 0)
            opp_count = sum(int(s.get("count") or 0) for s in ctx.pipeline_stages)

        activity_boost = Decimal(str(min(0.15, hot * 0.02 + qualified * 0.01)))
        comm_factor = Decimal(str(max(0.85, min(1.15, comm_health / 50.0))))
        risk_penalty = Decimal(str(min(0.25, overdue * 0.03 + max(0, 5 - opp_count) * 0.02)))

        deal_risk_penalty = Decimal("0")
        dr_inputs = (ctx.inputs_summary or {}).get("deal_risk_confidence") or {}
        if dr_inputs.get("confidence_penalty"):
            deal_risk_penalty = Decimal(str(dr_inputs["confidence_penalty"]))
            risk_penalty = min(Decimal("0.35"), risk_penalty + deal_risk_penalty)

        if snap:
            ctx.confidence = rev_forecast.get("confidence") or (
                "high" if opp_count >= 5 and weighted > 0 and deal_risk_penalty < Decimal("0.1") else
                "medium" if weighted > 0 else "low"
            )
        else:
            ctx.confidence = (
                "high" if opp_count >= 5 and weighted > 0 else
                "medium" if weighted > 0 else "low"
            )
        if deal_risk_penalty >= Decimal("0.2") and ctx.confidence == "high":
            ctx.confidence = "medium"
        elif deal_risk_penalty >= Decimal("0.25"):
            ctx.confidence = "low"

        forecasts: list[dict[str, Any]] = []
        for period in PERIODS:
            factor = _PERIOD_FACTORS[period]
            base = weighted * factor + closed * factor * Decimal("0.15")
            base = base * comm_factor * (Decimal("1") + activity_boost)
            expected = _quantize(base)
            best = _quantize(expected * Decimal("1.35") + Decimal(str(hot * 500000)) * factor)
            worst = _quantize(max(Decimal("0"), expected * Decimal("0.55") - risk_penalty * expected))
            if worst > expected:
                worst = _quantize(expected * Decimal("0.4"))

            forecasts.append({
                "period": period,
                "best_case": best,
                "expected_case": expected,
                "worst_case": worst,
                "currency": "UZS",
            })

        ctx.forecasts = forecasts

    @staticmethod
    def _build_risks(ctx: _ForecastContext) -> None:
        snap = ctx.snap
        inactive_deals: list[dict[str, Any]] = []
        overdue_opps: list[dict[str, Any]] = []
        proposals_risk: list[dict[str, Any]] = []
        comm_risks: list[dict[str, Any]] = []

        if snap:
            for room in snap.deal_rooms:
                prob = float(room.get("probability") or 0)
                if prob >= 20:
                    continue
                inactive_deals.append({
                    "risk_id": str(uuid4()),
                    "category": "inactive_deal",
                    "title": f"Stalled deal: {room.get('deal_name', 'Deal')}",
                    "description": f"Deal room probability {prob}% — revenue at risk",
                    "severity": "high" if prob < 10 else "medium",
                    "entity_type": "deal_room",
                    "entity_id": str(room.get("id") or ""),
                })

            for risk in snap.coordinated_risks[:8]:
                if risk.get("category") in ("stalled_deal", "inactive_conversations"):
                    item = {
                        "risk_id": risk.get("risk_id", str(uuid4())),
                        "category": risk.get("category", "opportunity"),
                        "title": risk.get("title", "Risk"),
                        "description": risk.get("issue", ""),
                        "severity": risk.get("severity", "medium"),
                        "entity_type": "deal" if risk.get("deal_id") else None,
                        "entity_id": str(risk.get("deal_id") or risk.get("conversation_id") or ""),
                    }
                    if risk.get("category") == "stalled_deal":
                        inactive_deals.append(item)
                    else:
                        comm_risks.append(item)
                elif risk.get("severity") in ("critical", "high"):
                    overdue_opps.append({
                        "risk_id": risk.get("risk_id", str(uuid4())),
                        "category": "overdue_opportunity",
                        "title": risk.get("title", "Opportunity risk"),
                        "description": risk.get("issue", ""),
                        "severity": risk.get("severity", "medium"),
                        "entity_type": "opportunity",
                        "entity_id": str(risk.get("deal_id") or risk.get("lead_id") or ""),
                    })

            for action in snap.overdue_actions[:6]:
                overdue_opps.append({
                    "risk_id": str(action.get("action_id", uuid4())),
                    "category": "overdue_action",
                    "title": action.get("title", "Overdue action"),
                    "description": action.get("description", "Manual follow-up required"),
                    "severity": "high",
                    "entity_type": "task",
                    "entity_id": str(action.get("action_id") or ""),
                })

            comm = snap.comm_overview or {}
            if int(comm.get("inactive_conversations") or 0) > 0:
                comm_risks.append({
                    "risk_id": str(uuid4()),
                    "category": "communication_risk",
                    "title": "Inactive buyer conversations",
                    "description": (
                        f"{comm['inactive_conversations']} threads inactive — "
                        "forecast may miss re-engagement revenue"
                    ),
                    "severity": "medium",
                    "entity_type": None,
                    "entity_id": None,
                })

        neglected = int(ctx.lead_metrics.get("neglected_leads") or 0)
        if neglected > 0:
            proposals_risk.append({
                "risk_id": str(uuid4()),
                "category": "neglected_leads",
                "title": f"{neglected} neglected lead(s)",
                "description": "Lead intelligence flags neglected accounts — pipeline decay risk",
                "severity": "medium",
                "entity_type": "lead",
                "entity_id": None,
            })

        if snap and snap.executive_summary.get("open_risks", 0) > 3:
            proposals_risk.append({
                "risk_id": str(uuid4()),
                "category": "proposals_at_risk",
                "title": "Elevated proposal follow-up risk",
                "description": "Multiple open risks may delay proposal conversions",
                "severity": "high",
                "entity_type": None,
                "entity_id": None,
            })

        ctx.risks = {
            "inactive_deals": inactive_deals[:10],
            "overdue_opportunities": overdue_opps[:10],
            "proposals_at_risk": proposals_risk[:10],
            "communication_risks": comm_risks[:10],
        }

    @staticmethod
    def _build_growth_opportunities(ctx: _ForecastContext) -> None:
        snap = ctx.snap
        items: list[dict[str, Any]] = []

        if snap:
            for opp in snap.coordinated_opportunities[:6]:
                ev = _decimal(opp.get("expected_value"))
                prob = float(opp.get("closing_probability") or 0) / 100.0
                impact = _quantize(ev * Decimal(str(prob)))
                items.append({
                    "opportunity_id": str(opp.get("opportunity_id", uuid4())),
                    "title": opp.get("title", "Opportunity"),
                    "description": (
                        f"Health {opp.get('opportunity_health')}, close {opp.get('closing_probability')}% — "
                        "manual pursuit only"
                    ),
                    "expected_impact": impact,
                    "priority": opp.get("priority", "medium"),
                    "source": opp.get("source", "crm"),
                })

            for lead in snap.priority_leads[:4]:
                items.append({
                    "opportunity_id": str(lead.get("lead_id", uuid4())),
                    "title": f"Hot lead: {lead.get('name', 'Lead')}",
                    "description": lead.get("recommended_action") or "Qualify and advance manually",
                    "expected_impact": _quantize(_decimal(lead.get("revenue_potential"))),
                    "priority": lead.get("urgency", "high"),
                    "source": "lead_intelligence",
                })

        if not items and ctx.pipeline_stages:
            top_stage = max(ctx.pipeline_stages, key=lambda s: s["forecast_revenue"])
            items.append({
                "opportunity_id": str(uuid4()),
                "title": f"Focus {top_stage['stage']} stage ({top_stage['count']} items)",
                "description": f"Pipeline stage forecast {_quantize(top_stage['forecast_revenue']):,.0f} UZS",
                "expected_impact": top_stage["forecast_revenue"],
                "priority": "medium",
                "source": "pipeline_forecast",
            })

        ctx.growth_opportunities = items[:8]

    @staticmethod
    def _build_executive(ctx: _ForecastContext) -> None:
        f30 = next((f for f in ctx.forecasts if f["period"] == "30d"), None)
        expected = _quantize(f30["expected_case"]) if f30 else Decimal("0")
        best = _quantize(f30["best_case"]) if f30 else Decimal("0")
        worst = _quantize(f30["worst_case"]) if f30 else Decimal("0")

        summary = (
            f"Heuristic 30-day revenue forecast: expected {expected:,.0f} UZS "
            f"(range {worst:,.0f} – {best:,.0f}). "
            f"Pipeline stage forecast {ctx.total_pipeline_forecast:,.0f} UZS "
            f"with {ctx.confidence} confidence. "
            "No automatic CRM or deal updates."
        )

        flat_risks = RevenueForecastService._flatten_risks(ctx.risks)
        ctx.executive = {
            "forecast_summary": summary,
            "top_growth_opportunities": ctx.growth_opportunities[:6],
            "top_revenue_risks": flat_risks[:6],
        }

    @staticmethod
    def _build_inputs_summary(ctx: _ForecastContext) -> None:
        snap = ctx.snap
        ctx.inputs_summary = {
            "active_leads": len(snap.priority_leads) if snap else 0,
            "hot_leads": int(ctx.lead_metrics.get("hot_leads") or 0),
            "qualified_leads": int(ctx.lead_metrics.get("qualified_leads") or 0),
            "proposals_in_pipeline": next(
                (s["count"] for s in ctx.pipeline_stages if s["stage"] == "proposal"), 0
            ),
            "opportunities": len(snap.coordinated_opportunities) if snap else 0,
            "revenue_attribution_loaded": bool(snap and snap.revenue_insights),
            "communication_health": (
                snap.executive_summary.get("communication_health", 50) if snap else 50
            ),
            "overdue_operator_tasks": len(snap.overdue_actions) if snap else 0,
            "pipeline_stages": len(ctx.pipeline_stages),
        }
