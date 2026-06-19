"""AI Sales Department v3 — central coordination layer across sales modules (read-only)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.endpoint_guard import safe_section
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.deal_room_service import DealRoomService
from app.services.executive_copilot_service import ExecutiveCopilotService
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.buyer_discovery_service import BuyerDiscoveryService
from app.services.buyer_network_service import BuyerNetworkService
from app.services.marketplace_service import MarketplaceService
from app.services.deal_risk_service import DealRiskService
from app.services.lead_intelligence_service import LeadIntelligenceService
from app.services.operator_task_engine_service import OperatorTaskEngineService
from app.services.revenue_attribution_service import RevenueAttributionService
from app.services.revenue_service import RevenueService
from app.services.sales_manager_service import SalesManagerService
from app.services.sales_workflow_service import SalesWorkflowService

logger = logging.getLogger(__name__)

MARKER = "[Sales Department v3]"

_URGENCY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
_PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


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


def _clamp_score(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, round(value, 1)))


def _urgency_from_score(score: float) -> str:
    if score >= 80:
        return "urgent"
    if score >= 65:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


@dataclass
class _DepartmentSnapshot:
    now: datetime
    client_id: UUID | None = None
    errors: list[str] = field(default_factory=list)
    lead_metrics: dict[str, Any] = field(default_factory=dict)
    comm_overview: dict[str, Any] = field(default_factory=dict)
    comm_conversations: list[dict[str, Any]] = field(default_factory=list)
    revenue_insights: dict[str, Any] = field(default_factory=dict)
    revenue_overview: dict[str, Any] = field(default_factory=dict)
    sales_manager: dict[str, Any] = field(default_factory=dict)
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    manager_recommendations: list[dict[str, Any]] = field(default_factory=list)
    deal_rooms: list[dict[str, Any]] = field(default_factory=list)
    operator_tasks: dict[str, Any] = field(default_factory=dict)
    workflow_summary: dict[str, Any] = field(default_factory=dict)
    executive_overview: dict[str, Any] = field(default_factory=dict)
    priority_leads: list[dict[str, Any]] = field(default_factory=list)
    priority_conversations: list[dict[str, Any]] = field(default_factory=list)
    coordinated_opportunities: list[dict[str, Any]] = field(default_factory=list)
    coordinated_risks: list[dict[str, Any]] = field(default_factory=list)
    recommended_actions: list[dict[str, Any]] = field(default_factory=list)
    overdue_actions: list[dict[str, Any]] = field(default_factory=list)
    escalation_list: list[dict[str, Any]] = field(default_factory=list)
    revenue_forecast: dict[str, Any] = field(default_factory=dict)
    buyer_intelligence: dict[str, Any] = field(default_factory=dict)
    buyer_discovery: dict[str, Any] = field(default_factory=dict)
    marketplace: dict[str, Any] = field(default_factory=dict)
    buyer_network: dict[str, Any] = field(default_factory=dict)
    deal_risk: dict[str, Any] = field(default_factory=dict)
    executive_summary: dict[str, Any] = field(default_factory=dict)
    weekly_priorities: list[str] = field(default_factory=list)


class SalesDepartmentOrchestrator:
    """Coordinates lead, opportunity, communication, task, and executive layers — advisory only."""

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        return {
            "executive_summary": snap.executive_summary,
            "top_opportunities": snap.coordinated_opportunities[:8],
            "top_risks": snap.coordinated_risks[:8],
            "priority_leads": snap.priority_leads[:10],
            "priority_conversations": snap.priority_conversations[:10],
            "recommended_actions": snap.recommended_actions[:12],
            "revenue_forecast": snap.revenue_forecast,
            "buyer_intelligence": snap.buyer_intelligence,
            "buyer_discovery": snap.buyer_discovery,
            "marketplace": snap.marketplace,
            "buyer_network": snap.buyer_network,
            "deal_risk": snap.deal_risk,
            "weekly_priorities": snap.weekly_priorities,
            "coordination": SalesDepartmentOrchestrator._coordination_payload(snap),
            "errors": snap.errors,
        }

    @staticmethod
    async def priorities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        leads = snap.priority_leads[:limit]
        convs = snap.priority_conversations[:limit]
        return {
            "priority_leads": leads,
            "priority_conversations": convs,
            "total": len(leads) + len(convs),
            "errors": snap.errors,
        }

    @staticmethod
    async def opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        items = snap.coordinated_opportunities[:limit]
        return {"items": items, "total": len(snap.coordinated_opportunities), "errors": snap.errors}

    @staticmethod
    async def risks(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        items = snap.coordinated_risks[:limit]
        return {"items": items, "total": len(snap.coordinated_risks), "errors": snap.errors}

    @staticmethod
    async def recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        recs = snap.recommended_actions[:limit]
        overdue = snap.overdue_actions[:limit]
        escalations = snap.escalation_list[:limit]
        return {
            "recommended_actions": recs,
            "overdue_actions": overdue,
            "escalation_list": escalations,
            "total": len(snap.recommended_actions),
            "errors": snap.errors,
        }

    @staticmethod
    async def generate_briefing(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        exec_sum = snap.executive_summary
        forecast = snap.revenue_forecast

        top_opps = [
            f"{o['title']} — health {o['opportunity_health']}, close {o['closing_probability']}%"
            for o in snap.coordinated_opportunities[:6]
        ]
        if not top_opps:
            top_opps = ["Pipeline stable — continue proactive outreach"]

        top_risks = [r["issue"] for r in snap.coordinated_risks[:6]]
        if not top_risks:
            top_risks = ["No critical department risks flagged"]

        actions = [
            f"{a['title']}: {a['description']}"
            for a in snap.recommended_actions[:6]
        ]
        if not actions:
            actions = [
                "Review priority leads in CRM manually",
                "Check unified inbox and messaging channels",
                "Review operator task queue for overdue items",
            ]

        weekly = snap.weekly_priorities or [
            "Follow up on hot leads and priority conversations",
            "Review deal room opportunities with elevated risk",
            "Clear overdue operator tasks and workflow bottlenecks",
        ]

        forecast_note = (
            f"Pipeline {_decimal(forecast.get('pipeline_value')):,.0f} UZS, "
            f"weighted {_decimal(forecast.get('weighted_pipeline')):,.0f} UZS, "
            f"30-day forecast {_decimal(forecast.get('forecast_30d')):,.0f} UZS. "
            "Manual review only — no automatic deal updates."
        )

        logger.info("%s briefing generated client=%s health=%s", MARKER, client_id, exec_sum.get("business_health_score"))
        return {
            "executive_summary": exec_sum.get("summary", ""),
            "top_opportunities": top_opps,
            "top_risks": top_risks,
            "weekly_priorities": weekly[:7],
            "recommended_actions": actions,
            "revenue_forecast_note": forecast_note,
            "source": "heuristic",
            "generated_at": snap.now,
            "errors": snap.errors,
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        exec_sum = snap.executive_summary
        forecast = snap.revenue_forecast
        return {
            "business_health_score": exec_sum.get("business_health_score", 50),
            "priority_leads": len(snap.priority_leads),
            "hot_leads": exec_sum.get("hot_leads", 0),
            "active_opportunities": len(snap.coordinated_opportunities),
            "open_risks": len(snap.coordinated_risks),
            "overdue_actions": len(snap.overdue_actions),
            "pipeline_value": forecast.get("pipeline_value", Decimal("0")),
            "closed_revenue": forecast.get("closed_revenue", Decimal("0")),
            "communication_health": exec_sum.get("communication_health", 50.0),
            "top_opportunities": [
                {"title": o["title"], "closing_probability": o["closing_probability"], "priority": o["priority"]}
                for o in snap.coordinated_opportunities[:3]
            ],
            "top_risks": [
                {"issue": r["issue"], "severity": r["severity"]}
                for r in snap.coordinated_risks[:3]
            ],
            "top_actions": [
                {"title": a["title"], "priority": a["priority"], "is_overdue": a.get("is_overdue", False)}
                for a in snap.recommended_actions[:3]
            ],
            "weekly_priorities": snap.weekly_priorities[:5],
            "errors": snap.errors,
        }

    @staticmethod
    async def department_recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        items: list[dict[str, Any]] = []
        for action in snap.recommended_actions[:limit]:
            items.append({
                "category": action.get("category", "task"),
                "title": action["title"],
                "description": action.get("description", ""),
                "priority": action.get("priority", "medium"),
                "source": action.get("source", "sales_department_v3"),
            })
        for rec in snap.manager_recommendations[: max(0, limit - len(items))]:
            items.append({
                "category": rec.get("category", "sales_manager"),
                "title": rec.get("title", "Review opportunity"),
                "description": rec.get("description", rec.get("action", "")),
                "priority": rec.get("priority", "medium"),
                "source": "sales_manager",
            })
        items.sort(key=lambda x: _PRIORITY_RANK.get(x.get("priority", "medium"), 3))
        return {"items": items[:limit], "total": len(items), "errors": snap.errors}

    @staticmethod
    async def _build_snapshot(db: AsyncSession, *, client_id: UUID | None) -> _DepartmentSnapshot:
        now = _utc_now()
        errors: list[str] = []
        snap = _DepartmentSnapshot(now=now, client_id=client_id, errors=errors)

        snap.lead_metrics = await safe_section(
            "lead_intelligence",
            LeadIntelligenceService.metrics(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.comm_overview = await safe_section(
            "communication_intelligence",
            CommunicationIntelligenceService.overview(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        async def _comm_list() -> dict[str, Any]:
            return await CommunicationIntelligenceService.list_conversations(
                db, client_id=client_id, limit=40,
            )

        comm_list = await safe_section(
            "communication_conversations",
            _comm_list(),
            default={"items": []},
            errors=errors,
            db=db,
        )
        snap.comm_conversations = list(comm_list.get("items") or [])

        snap.revenue_insights = await safe_section(
            "revenue_attribution",
            RevenueAttributionService.insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.revenue_overview = await safe_section(
            "revenue",
            RevenueService.overview(db, deals_limit=5),
            default={},
            errors=errors,
            db=db,
        )

        snap.sales_manager = await safe_section(
            "sales_manager",
            SalesManagerService.overview(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        opp_data = await safe_section(
            "sales_manager_opportunities",
            SalesManagerService.opportunities(db, client_id=client_id, limit=30),
            default={"items": []},
            errors=errors,
            db=db,
        )
        snap.opportunities = list(opp_data.get("items") or [])

        risk_data = await safe_section(
            "sales_manager_risks",
            SalesManagerService.risks(db, client_id=client_id, limit=30),
            default={"items": []},
            errors=errors,
            db=db,
        )
        snap.risks = list(risk_data.get("items") or [])

        rec_data = await safe_section(
            "sales_manager_recommendations",
            SalesManagerService.recommendations(db, client_id=client_id, limit=15),
            default={"items": []},
            errors=errors,
            db=db,
        )
        snap.manager_recommendations = list(rec_data.get("items") or [])

        deal_data = await safe_section(
            "deal_room",
            DealRoomService.list_rooms(db, crm_client_id=client_id, status="active", limit=30),
            default={"items": []},
            errors=errors,
            db=db,
        )
        snap.deal_rooms = list(deal_data.get("items") or [])

        snap.operator_tasks = await safe_section(
            "operator_tasks",
            OperatorTaskEngineService.list_tasks(db, client_id=client_id, limit=20),
            default={"items": [], "summary": {}},
            errors=errors,
            db=db,
        )

        snap.workflow_summary = await safe_section(
            "workflow_automation",
            SalesWorkflowService.summary_widget(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.executive_overview = await safe_section(
            "executive_copilot",
            ExecutiveCopilotService.overview(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        SalesDepartmentOrchestrator._coordinate_leads(snap)
        SalesDepartmentOrchestrator._coordinate_communications(snap)
        SalesDepartmentOrchestrator._coordinate_opportunities(snap)
        SalesDepartmentOrchestrator._coordinate_risks(snap)
        SalesDepartmentOrchestrator._coordinate_tasks(snap)
        SalesDepartmentOrchestrator._coordinate_executive(snap)
        SalesDepartmentOrchestrator._build_revenue_forecast(snap)

        snap.buyer_intelligence = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.executive_insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.buyer_discovery = await safe_section(
            "buyer_discovery",
            BuyerDiscoveryService.executive_insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.marketplace = await safe_section(
            "marketplace",
            MarketplaceService.executive_summary(db),
            default={},
            errors=errors,
            db=db,
        )

        snap.buyer_network = await safe_section(
            "buyer_network",
            BuyerNetworkService.executive_summary(db),
            default={},
            errors=errors,
            db=db,
        )

        snap.deal_risk = await safe_section(
            "deal_risk",
            DealRiskService.executive_insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        return snap

    @staticmethod
    def _coordinate_leads(snap: _DepartmentSnapshot) -> None:
        rev_perf = snap.revenue_insights or {}
        best_source_score = 15.0 if rev_perf.get("best_source") else 0.0
        items: list[dict[str, Any]] = []

        for lead in snap.lead_metrics.get("top_hot_leads") or []:
            lead_score = int(lead.get("lead_score") or 0)
            comm_boost = 10.0 if snap.comm_overview.get("hot_buyers") else 0.0
            if snap.comm_overview.get("follow_ups_required"):
                comm_boost += 5.0
            priority_score = _clamp_score(lead_score * 0.55 + comm_boost + best_source_score)
            revenue_potential = _clamp_score(
                lead_score * 0.6 + (20.0 if lead.get("qualification_level") in ("hot", "qualified") else 0.0),
            )
            sources = ["lead_intelligence"]
            if comm_boost:
                sources.append("communication_intelligence")
            if best_source_score:
                sources.append("revenue_attribution")

            items.append({
                "lead_id": lead["lead_id"],
                "name": lead.get("name") or "Lead",
                "company": lead.get("company"),
                "priority_score": priority_score,
                "urgency": _urgency_from_score(priority_score),
                "revenue_potential": revenue_potential,
                "lead_score": lead_score,
                "qualification_level": lead.get("qualification_level"),
                "recommended_action": lead.get("recommended_action") or "Manual follow-up recommended",
                "sources": sources,
            })

        items.sort(key=lambda x: (-x["priority_score"], -x["revenue_potential"]))
        snap.priority_leads = items

    @staticmethod
    def _coordinate_communications(snap: _DepartmentSnapshot) -> None:
        avg_health = float(snap.comm_overview.get("avg_health_score") or 50.0)
        if not avg_health and snap.comm_conversations:
            scores = [
                float((c.get("intelligence") or {}).get("health_score") or 50)
                for c in snap.comm_conversations
            ]
            avg_health = sum(scores) / len(scores) if scores else 50.0

        items: list[dict[str, Any]] = []
        for conv in snap.comm_conversations:
            intel = conv.get("intelligence") or {}
            health = float(intel.get("health_score") or conv.get("communication_health") or 50.0)
            urgency = str(intel.get("urgency") or conv.get("urgency") or "medium")
            classification = intel.get("classification") or conv.get("classification")
            follow_priority = urgency
            if classification in ("hot_buyer", "proposal_request", "negotiation"):
                follow_priority = "high" if follow_priority != "urgent" else "urgent"
            if snap.comm_overview.get("follow_ups_required") and urgency in ("urgent", "high"):
                follow_priority = "urgent"

            response_urgency = urgency
            channel = str(conv.get("channel") or conv.get("source") or "unknown").lower()
            source = str(conv.get("source") or channel)
            actions = intel.get("recommended_actions") or conv.get("recommended_actions") or []
            recommended = actions[0] if actions else "Manual response review recommended"

            items.append({
                "conversation_id": str(conv.get("conversation_id") or uuid4()),
                "channel": channel,
                "source": source,
                "contact_name": conv.get("contact_name") or conv.get("title"),
                "response_urgency": response_urgency,
                "follow_up_priority": follow_priority,
                "communication_health": _clamp_score(health),
                "classification": classification,
                "recommended_action": recommended,
            })

        items.sort(
            key=lambda x: (
                _URGENCY_RANK.get(x["response_urgency"], 3),
                -x["communication_health"],
            ),
        )
        snap.priority_conversations = items
        snap.comm_overview["avg_health_score"] = _clamp_score(avg_health)

    @staticmethod
    def _coordinate_opportunities(snap: _DepartmentSnapshot) -> None:
        seen: set[str] = set()
        items: list[dict[str, Any]] = []

        for room in snap.deal_rooms:
            key = f"room:{room['id']}"
            if key in seen:
                continue
            seen.add(key)
            prob = float(room.get("probability") or 0)
            health = _clamp_score(prob * 0.7 + (20 if room.get("status") == "active" else 0))
            deal_risk = "high" if prob < 25 else "medium" if prob < 55 else "low"
            items.append({
                "opportunity_id": key,
                "title": room.get("deal_name") or "Deal Room opportunity",
                "source": "deal_room",
                "opportunity_health": health,
                "deal_risk": deal_risk,
                "closing_probability": prob,
                "expected_value": room.get("expected_value"),
                "lead_id": None,
                "deal_room_id": room.get("id"),
                "priority": "high" if prob >= 60 else "medium" if prob >= 35 else "low",
            })

        for opp in snap.opportunities:
            key = f"sm:{opp.get('entity_id') or opp.get('title')}"
            if key in seen:
                continue
            seen.add(key)
            priority = str(opp.get("priority") or "medium")
            health = _clamp_score(
                70 - _PRIORITY_RANK.get(priority, 2) * 12 + (10 if opp.get("classification") == "hot" else 0),
            )
            items.append({
                "opportunity_id": key,
                "title": opp.get("title") or "Sales opportunity",
                "source": str(opp.get("source") or "sales_manager"),
                "opportunity_health": health,
                "deal_risk": "low",
                "closing_probability": float(opp.get("score") or health * 0.8),
                "expected_value": opp.get("expected_value"),
                "lead_id": opp.get("lead_id"),
                "deal_room_id": None,
                "priority": priority,
            })

        bi = snap.buyer_intelligence or {}
        for row in bi.get("top_buyers") or []:
            key = f"buyer:{row.get('buyer_id')}"
            if key in seen:
                continue
            seen.add(key)
            score = int(row.get("buyer_score") or 0)
            items.append({
                "opportunity_id": key,
                "title": f"Buyer opportunity: {row.get('name')}",
                "source": "buyer_intelligence",
                "opportunity_health": _clamp_score(score),
                "deal_risk": "low" if score >= 70 else "medium",
                "closing_probability": float(score * 0.85),
                "expected_value": row.get("annual_potential"),
                "lead_id": row.get("buyer_id"),
                "deal_room_id": None,
                "priority": "high" if score >= 75 else "medium",
            })

        bd = snap.buyer_discovery or {}
        for row in bd.get("highest_potential_buyers") or []:
            key = f"discovery:{row.get('buyer_id')}"
            if key in seen:
                continue
            seen.add(key)
            score = int(row.get("opportunity_score") or 0)
            items.append({
                "opportunity_id": key,
                "title": f"Export discovery: {row.get('company_name')}",
                "source": "buyer_discovery",
                "opportunity_health": _clamp_score(score),
                "deal_risk": "low" if score >= 70 else "medium",
                "closing_probability": float(score * 0.75),
                "expected_value": None,
                "lead_id": row.get("buyer_id"),
                "deal_room_id": None,
                "priority": "high" if score >= 75 else "medium",
            })

        mp = snap.marketplace or {}
        for row in mp.get("best_opportunities") or []:
            key = f"marketplace:{row.get('opportunity_id')}"
            if key in seen:
                continue
            seen.add(key)
            score = int(row.get("rank_score") or 0)
            items.append({
                "opportunity_id": key,
                "title": f"Marketplace: {row.get('title')}",
                "source": "marketplace",
                "opportunity_health": _clamp_score(score),
                "deal_risk": "low",
                "closing_probability": float(score * 0.7),
                "expected_value": row.get("estimated_value"),
                "lead_id": None,
                "deal_room_id": None,
                "priority": "high" if score >= 70 else "medium",
            })

        dr = snap.deal_risk or {}
        for row in dr.get("likely_close_this_month") or []:
            key = f"deal_risk:{row.get('deal_id')}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "opportunity_id": key,
                "title": f"High close probability: {row.get('title')}",
                "source": "deal_risk",
                "opportunity_health": _clamp_score(int(row.get("deal_health_score") or 70)),
                "deal_risk": "low",
                "closing_probability": float(row.get("close_probability") or 70),
                "expected_value": row.get("revenue"),
                "lead_id": None,
                "deal_room_id": None,
                "deal_id": row.get("deal_id"),
                "priority": "high",
            })

        items.sort(
            key=lambda x: (
                -float(x["closing_probability"]),
                _PRIORITY_RANK.get(x["priority"], 3),
            ),
        )
        snap.coordinated_opportunities = items

    @staticmethod
    def _coordinate_risks(snap: _DepartmentSnapshot) -> None:
        seen: set[str] = set()
        items: list[dict[str, Any]] = []

        for risk in snap.risks:
            key = f"{risk.get('type') or 'risk'}:{risk.get('entity_id') or risk.get('issue')}"
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "risk_id": str(uuid4()),
                "title": risk.get("title") or risk.get("issue") or "Risk",
                "issue": risk.get("issue") or risk.get("title") or "Review manually",
                "severity": str(risk.get("severity") or "medium"),
                "source": str(risk.get("source") or "sales_manager"),
                "category": risk.get("type") or risk.get("category"),
                "lead_id": risk.get("lead_id"),
                "deal_id": risk.get("deal_id"),
                "conversation_id": risk.get("conversation_id"),
            })

        for room in snap.deal_rooms:
            prob = float(room.get("probability") or 0)
            if prob >= 25:
                continue
            items.append({
                "risk_id": str(uuid4()),
                "title": f"Low-probability deal: {room.get('deal_name')}",
                "issue": f"Deal room at {prob}% probability — manual review recommended",
                "severity": "high" if prob < 15 else "medium",
                "source": "deal_room",
                "category": "stalled_deal",
                "lead_id": None,
                "deal_id": None,
                "conversation_id": None,
            })

        if snap.comm_overview.get("inactive_conversations"):
            items.append({
                "risk_id": str(uuid4()),
                "title": "Inactive buyer conversations",
                "issue": f"{snap.comm_overview['inactive_conversations']} inactive conversations need re-engagement",
                "severity": "medium",
                "source": "communication_intelligence",
                "category": "inactive_conversations",
            })

        dr = snap.deal_risk or {}
        for row in dr.get("highest_risk_deals") or []:
            key = f"deal_risk:{row.get('deal_id')}"
            if key in seen:
                continue
            seen.add(key)
            severity = "critical" if row.get("risk_level") in ("critical", "lost_probability_high") else "high"
            items.append({
                "risk_id": str(uuid4()),
                "title": f"Deal risk: {row.get('title')}",
                "issue": "; ".join(row.get("risk_reasons") or []) or f"Health {row.get('deal_health_score')}/100",
                "severity": severity,
                "source": "deal_risk",
                "category": row.get("risk_level") or "at_risk",
                "lead_id": None,
                "deal_id": row.get("deal_id"),
                "conversation_id": None,
            })

        items.sort(key=lambda x: (_SEVERITY_RANK.get(x["severity"], 3), x["title"]))
        snap.coordinated_risks = items

    @staticmethod
    def _coordinate_tasks(snap: _DepartmentSnapshot) -> None:
        now = snap.now
        recommended: list[dict[str, Any]] = []
        overdue: list[dict[str, Any]] = []
        escalations: list[dict[str, Any]] = []

        for task in snap.operator_tasks.get("items") or []:
            due = task.get("due_at")
            is_overdue = False
            if due:
                due_dt = due if isinstance(due, datetime) else None
                if due_dt and due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                is_overdue = bool(due_dt and due_dt < now)

            priority = str(task.get("priority") or "medium")
            action = {
                "action_id": str(task.get("id") or uuid4()),
                "title": task.get("title") or "Operator task",
                "description": task.get("recommended_action") or "Manual execution required",
                "priority": priority,
                "source": "operator_tasks",
                "category": task.get("action_type") or "task",
                "lead_id": task.get("lead_id"),
                "deal_id": task.get("deal_id"),
                "conversation_id": task.get("conversation_id"),
                "due_at": due,
                "is_overdue": is_overdue,
                "requires_escalation": is_overdue and priority in ("urgent", "high"),
            }
            recommended.append(action)
            if is_overdue:
                overdue.append(action)
            if action["requires_escalation"]:
                escalations.append(action)

        for wf in snap.workflow_summary.get("top_recommendations") or []:
            recommended.append({
                "action_id": str(wf.get("id") or uuid4()),
                "title": wf.get("title") or "Workflow recommendation",
                "description": wf.get("description") or wf.get("recommended_action") or "Review workflow manually",
                "priority": str(wf.get("priority") or "medium"),
                "source": "workflow_automation",
                "category": wf.get("workflow_type") or "workflow",
                "lead_id": wf.get("lead_id"),
                "deal_id": wf.get("deal_id"),
                "conversation_id": None,
                "due_at": None,
                "is_overdue": False,
                "requires_escalation": wf.get("priority") == "urgent",
            })

        dr = snap.deal_risk or {}
        for row in dr.get("highest_risk_deals") or []:
            if row.get("risk_level") not in ("critical", "at_risk", "stalled", "lost_probability_high"):
                continue
            recommended.append({
                "action_id": str(row.get("deal_id") or uuid4()),
                "title": f"Deal intervention: {row.get('title')}",
                "description": "; ".join(row.get("risk_reasons") or []) or "Review deal risk manually",
                "priority": "urgent" if row.get("risk_level") in ("critical", "lost_probability_high") else "high",
                "source": "deal_risk",
                "category": "deal_intervention",
                "lead_id": None,
                "deal_id": row.get("deal_id"),
                "conversation_id": None,
                "due_at": None,
                "is_overdue": False,
                "requires_escalation": row.get("risk_level") in ("critical", "lost_probability_high"),
            })

        recommended.sort(key=lambda x: (_PRIORITY_RANK.get(x["priority"], 3), x.get("is_overdue", False) is False))
        snap.recommended_actions = recommended
        snap.overdue_actions = overdue
        snap.escalation_list = escalations

    @staticmethod
    def _coordinate_executive(snap: _DepartmentSnapshot) -> None:
        sm = snap.sales_manager
        ex = snap.executive_overview
        comm_health = float(snap.comm_overview.get("avg_health_score") or 50.0)

        health = int(ex.get("business_health_score") or 50)
        hot = int(snap.lead_metrics.get("hot_leads") or sm.get("hot_leads") or 0)

        summary = (
            f"AI Sales Department v3 coordinating {len(snap.priority_leads)} priority leads, "
            f"{len(snap.coordinated_opportunities)} opportunities, and {len(snap.coordinated_risks)} risks. "
            f"Business health {health}/100 with {hot} hot leads, "
            f"{len(snap.overdue_actions)} overdue actions, and communication health {comm_health:.0f}/100. "
            "All recommendations require manual operator approval."
        )

        snap.executive_summary = {
            "summary": summary,
            "business_health_score": health,
            "hot_leads": hot,
            "priority_leads": len(snap.priority_leads),
            "active_opportunities": len(snap.coordinated_opportunities),
            "open_risks": len(snap.coordinated_risks),
            "overdue_actions": len(snap.overdue_actions),
            "communication_health": comm_health,
        }

        weekly: list[str] = []
        if snap.priority_leads:
            weekly.append(f"Follow up on {min(3, len(snap.priority_leads))} priority leads")
        if snap.priority_conversations:
            weekly.append(f"Respond to {min(3, len(snap.priority_conversations))} priority conversations")
        if snap.coordinated_opportunities:
            weekly.append("Review top deal room and CRM opportunities")
        if snap.overdue_actions:
            weekly.append(f"Clear {len(snap.overdue_actions)} overdue operator tasks")
        if snap.coordinated_risks:
            weekly.append(f"Mitigate {min(3, len(snap.coordinated_risks))} department risks")
        if snap.workflow_summary.get("active_recommendations"):
            weekly.append("Address workflow automation bottlenecks manually")
        if not weekly:
            weekly = [
                "Maintain pipeline hygiene in CRM",
                "Monitor unified inbox and channel centers",
                "Run weekly sales department briefing",
            ]
        snap.weekly_priorities = weekly[:7]

    @staticmethod
    def _build_revenue_forecast(snap: _DepartmentSnapshot) -> None:
        rev = snap.revenue_overview
        pipeline = _decimal(rev.get("total_pipeline_value"))
        closed = _decimal(rev.get("total_closed_revenue"))

        weighted = Decimal("0")
        for opp in snap.coordinated_opportunities:
            ev = _decimal(opp.get("expected_value"))
            prob = Decimal(str(opp.get("closing_probability") or 0)) / Decimal("100")
            weighted += ev * prob

        if weighted <= 0 and pipeline > 0:
            avg_prob = (
                sum(float(o.get("closing_probability") or 0) for o in snap.coordinated_opportunities) /
                max(len(snap.coordinated_opportunities), 1)
            ) / 100.0
            weighted = pipeline * Decimal(str(max(avg_prob, 0.25)))

        forecast_30d = weighted * Decimal("0.35") + closed * Decimal("0.05")
        forecast_90d = weighted * Decimal("0.75") + closed * Decimal("0.15")

        confidence = "high" if len(snap.coordinated_opportunities) >= 5 else "medium"
        if len(snap.coordinated_opportunities) == 0:
            confidence = "low"

        snap.revenue_forecast = {
            "pipeline_value": pipeline,
            "weighted_pipeline": weighted.quantize(Decimal("0.01")),
            "closed_revenue": closed,
            "forecast_30d": forecast_30d.quantize(Decimal("0.01")),
            "forecast_90d": forecast_90d.quantize(Decimal("0.01")),
            "currency": "UZS",
            "confidence": confidence,
        }

    @staticmethod
    def _coordination_payload(snap: _DepartmentSnapshot) -> dict[str, Any]:
        return {
            "lead_coordination": {
                "sources": ["lead_intelligence", "communication_intelligence", "revenue_attribution"],
                "priority_leads": len(snap.priority_leads),
            },
            "opportunity_coordination": {
                "sources": ["deal_room", "crm", "sales_manager"],
                "opportunities": len(snap.coordinated_opportunities),
            },
            "communication_coordination": {
                "sources": ["unified_inbox", "wechat_center", "whatsapp_center"],
                "priority_conversations": len(snap.priority_conversations),
                "communication_health": snap.executive_summary.get("communication_health", 50.0),
            },
            "task_coordination": {
                "sources": ["operator_tasks", "workflow_automation"],
                "recommended_actions": len(snap.recommended_actions),
                "overdue_actions": len(snap.overdue_actions),
                "escalations": len(snap.escalation_list),
            },
            "executive_coordination": {
                "sources": ["executive_copilot", "sales_manager"],
                "business_health_score": snap.executive_summary.get("business_health_score", 50),
            },
        }
