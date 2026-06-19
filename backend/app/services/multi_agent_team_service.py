"""Multi-Agent Sales Team v1 — role-specialized agents on AI Sales Department v3 (read-only)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.buyer_discovery_service import BuyerDiscoveryService
from app.services.buyer_network_service import BuyerNetworkService
from app.services.buyer_acquisition_service import BuyerAcquisitionService
from app.services.marketplace_service import MarketplaceService
from app.services.deal_risk_service import DealRiskService
from app.services.revenue_forecast_service import RevenueForecastService
from app.services.sales_department_orchestrator import SalesDepartmentOrchestrator

logger = logging.getLogger(__name__)

MARKER = "[Multi-Agent Sales Team]"

_PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}

AGENT_NAMES = (
    "Sales Director Agent",
    "Sales Manager Agent",
    "Lead Analyst Agent",
    "Communication Agent",
    "Operations Agent",
)


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


def _health_label(score: int) -> str:
    if score >= 75:
        return "strong"
    if score >= 50:
        return "stable"
    if score >= 35:
        return "attention"
    return "critical"


class MultiAgentTeamService:
    """Coordinates five advisory agents atop Sales Department v3 — no side effects."""

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await MultiAgentTeamService._build_context(db, client_id=client_id)
        return {
            "team_summary": ctx["coordinator"]["combined_summary"],
            "coordinator": ctx["coordinator"],
            "agents": ctx["agents"],
            "active_agent_count": len(ctx["agents"]),
            "safety_notice": ctx["safety_notice"],
            "errors": ctx["errors"],
        }

    @staticmethod
    async def agents(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await MultiAgentTeamService._build_context(db, client_id=client_id)
        agents = ctx["agents"]
        return {"agents": agents, "total": len(agents), "errors": ctx["errors"]}

    @staticmethod
    async def recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        ctx = await MultiAgentTeamService._build_context(db, client_id=client_id)
        top = ctx["coordinator"]["top_recommendations"][:limit]
        by_agent = {
            a["agent_name"]: a["recommendations"][:8]
            for a in ctx["agents"]
        }
        return {
            "top_recommendations": top,
            "by_agent": by_agent,
            "total": len(top),
            "errors": ctx["errors"],
        }

    @staticmethod
    async def health(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await MultiAgentTeamService._build_context(db, client_id=client_id)
        coord = ctx["coordinator"]
        snap = ctx["snap"]
        exec_sum = snap.executive_summary
        return {
            "department_health": coord["department_health"],
            "department_health_label": coord["department_health_label"],
            "agent_health": ctx["agent_health"],
            "hot_leads": exec_sum.get("hot_leads", 0),
            "open_risks": len(snap.coordinated_risks),
            "overdue_actions": len(snap.overdue_actions),
            "communication_health": exec_sum.get("communication_health", 50.0),
            "active_opportunities": len(snap.coordinated_opportunities),
            "top_recommendations": [
                {"title": r["title"], "priority": r["priority"], "source_agent": r.get("source_agent")}
                for r in coord["top_recommendations"][:5]
            ],
            "conflicts_count": len(coord["conflicts"]),
            "safety_notice": ctx["safety_notice"],
            "errors": ctx["errors"],
        }

    @staticmethod
    async def generate_briefing(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        ctx = await MultiAgentTeamService._build_context(db, client_id=client_id)
        coord = ctx["coordinator"]
        snap = ctx["snap"]

        agent_summaries = {a["agent_name"]: a["summary"] for a in ctx["agents"]}
        top_recs = [r["title"] for r in coord["top_recommendations"][:8]]
        if not top_recs:
            top_recs = ["Review priority leads and inbox manually"]

        conflict_lines = [
            f"{c['topic']}: {c['description']}"
            for c in coord["conflicts"]
        ]
        if not conflict_lines:
            conflict_lines = ["No cross-agent conflicts detected"]

        weekly = snap.weekly_priorities or [
            "Align sales director priorities with manager opportunity review",
            "Clear overdue operator tasks flagged by operations agent",
            "Follow up on communication agent urgent threads",
        ]

        logger.info(
            "%s briefing client=%s health=%s",
            MARKER,
            client_id,
            coord["department_health"],
        )
        return {
            "briefing_title": "Multi-Agent Sales Team Briefing",
            "combined_summary": coord["combined_summary"],
            "agent_summaries": agent_summaries,
            "top_recommendations": top_recs,
            "conflicts": conflict_lines[:6],
            "department_health": coord["department_health"],
            "weekly_priorities": weekly[:7],
            "source": "heuristic",
            "generated_at": snap.now,
            "safety_notice": ctx["safety_notice"],
            "errors": ctx["errors"],
        }

    @staticmethod
    async def agent_recommendations_panel(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Compact panel payload for Sales Department v3 / Sales Manager integrations."""
        ctx = await MultiAgentTeamService._build_context(db, client_id=client_id)
        items = [
            {
                "agent_name": r.get("source_agent", "Multi-Agent Team"),
                "title": r["title"],
                "description": r.get("description", ""),
                "priority": r.get("priority", "medium"),
            }
            for r in ctx["coordinator"]["top_recommendations"][:limit]
        ]
        return {"items": items, "total": len(items), "errors": ctx["errors"]}

    @staticmethod
    async def _build_context(
        db: AsyncSession,
        *,
        client_id: UUID | None,
    ) -> dict[str, Any]:
        snap = await SalesDepartmentOrchestrator._build_snapshot(db, client_id=client_id)
        errors = list(snap.errors)
        safety = (
            "Recommendation only — no automatic messaging, CRM updates, deal updates, or task execution."
        )

        forecast_recs: list[dict[str, Any]] = []
        buyer_recs: list[dict[str, Any]] = []
        discovery_recs: list[dict[str, Any]] = []
        marketplace_recs: list[dict[str, Any]] = []
        acquisition_recs: list[dict[str, Any]] = []
        deal_risk_recs: list[dict[str, Any]] = []
        try:
            panel = await RevenueForecastService.forecast_recommendations(
                db, client_id=client_id, limit=3,
            )
            forecast_recs = panel.get("items") or []
        except Exception as exc:
            errors.append(f"revenue_forecast: {exc}")

        try:
            buyer_panel = await BuyerIntelligenceService.buyer_recommendations(
                db, client_id=client_id, limit=3,
            )
            buyer_recs = buyer_panel.get("items") or []
        except Exception as exc:
            errors.append(f"buyer_intelligence: {exc}")

        try:
            discovery_panel = await BuyerDiscoveryService.acquisition_recommendations(
                db, client_id=client_id, limit=3,
            )
            discovery_recs = discovery_panel.get("items") or []
        except Exception as exc:
            errors.append(f"buyer_discovery: {exc}")

        try:
            marketplace_panel = await MarketplaceService.opportunity_recommendations(
                db, limit=3,
            )
            marketplace_recs = marketplace_panel.get("items") or []
        except Exception as exc:
            errors.append(f"marketplace: {exc}")

        try:
            network_panel = await BuyerNetworkService.network_recommendations(db, limit=3)
            network_recs = network_panel.get("items") or []
        except Exception as exc:
            errors.append(f"buyer_network: {exc}")

        try:
            acquisition_panel = await BuyerAcquisitionService.acquisition_recommendations(
                db, client_id=client_id, limit=3,
            )
            acquisition_recs = acquisition_panel.get("items") or []
        except Exception as exc:
            errors.append(f"buyer_acquisition: {exc}")

        try:
            deal_panel = await DealRiskService.deal_recommendations(
                db, client_id=client_id, limit=3,
            )
            deal_risk_recs = deal_panel.get("items") or []
        except Exception as exc:
            errors.append(f"deal_risk: {exc}")

        agents = [
            MultiAgentTeamService._sales_director_agent(
                snap,
                forecast_recs=forecast_recs,
                buyer_recs=buyer_recs,
                discovery_recs=discovery_recs,
                marketplace_recs=marketplace_recs,
                network_recs=network_recs,
                acquisition_recs=acquisition_recs,
                deal_risk_recs=deal_risk_recs,
            ),
            MultiAgentTeamService._sales_manager_agent(snap),
            MultiAgentTeamService._lead_analyst_agent(snap),
            MultiAgentTeamService._communication_agent(snap),
            MultiAgentTeamService._operations_agent(snap),
        ]
        coordinator = MultiAgentTeamService._coordinate(agents, snap)
        agent_health = MultiAgentTeamService._agent_health_scores(agents, snap)

        return {
            "snap": snap,
            "agents": agents,
            "coordinator": coordinator,
            "agent_health": agent_health,
            "buyer_discovery_recommendations": discovery_recs,
            "marketplace_recommendations": marketplace_recs,
            "buyer_network_recommendations": network_recs,
            "buyer_acquisition_recommendations": acquisition_recs,
            "safety_notice": safety,
            "errors": errors,
        }

    @staticmethod
    def _sales_director_agent(
        snap: Any,
        *,
        forecast_recs: list[dict[str, Any]] | None = None,
        buyer_recs: list[dict[str, Any]] | None = None,
        discovery_recs: list[dict[str, Any]] | None = None,
        marketplace_recs: list[dict[str, Any]] | None = None,
        network_recs: list[dict[str, Any]] | None = None,
        acquisition_recs: list[dict[str, Any]] | None = None,
        deal_risk_recs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        exec_sum = snap.executive_summary
        forecast = snap.revenue_forecast
        health = exec_sum.get("business_health_score", 50)
        recs: list[str] = []

        if exec_sum.get("hot_leads", 0) > 0:
            recs.append(
                f"Prioritize {exec_sum['hot_leads']} hot lead(s) for revenue acceleration this week"
            )
        if exec_sum.get("open_risks", 0) > 3:
            recs.append("Schedule executive review of elevated department risks")
        if forecast.get("pipeline_value"):
            recs.append(
                f"Set revenue focus on pipeline value and 30-day forecast alignment"
            )
        for wp in (snap.weekly_priorities or [])[:3]:
            recs.append(wp)
        for fr in (forecast_recs or [])[:3]:
            recs.append(fr.get("title") or "Review revenue forecast")
        for br in (buyer_recs or [])[:3]:
            recs.append(br.get("title") or "Review buyer intelligence")
        for dr in (discovery_recs or [])[:3]:
            recs.append(dr.get("title") or "Review export buyer discovery")
        for mr in (marketplace_recs or [])[:3]:
            recs.append(mr.get("title") or "Review marketplace opportunity")
        for nr in (network_recs or [])[:3]:
            recs.append(nr.get("title") or "Review buyer network intelligence")
        for ar in (acquisition_recs or [])[:3]:
            recs.append(ar.get("title") or "Review buyer acquisition workspace")
        for dr in (deal_risk_recs or [])[:3]:
            recs.append(dr.get("title") or "Review deal risk interventions")
        dr_snap = getattr(snap, "deal_risk", None) or {}
        if dr_snap.get("requiring_intervention", 0) > 0:
            recs.append(
                f"{dr_snap['requiring_intervention']} deal(s) require manual intervention — review Deal Risk"
            )
        rf = getattr(snap, "revenue_forecast", None) or {}
        if rf.get("forecast_30d"):
            recs.append(
                f"Department 30d forecast {_decimal(rf['forecast_30d']):,.0f} UZS — "
                "align targets with Revenue Forecast module"
            )
        if not recs:
            recs.append("Maintain steady pipeline growth and weekly executive check-in")

        priority = "high" if health < 50 or exec_sum.get("open_risks", 0) > 5 else "medium"
        summary = exec_sum.get(
            "summary",
            "Executive layer stable — review revenue targets and department priorities manually.",
        )
        return {
            "agent_name": AGENT_NAMES[0],
            "summary": summary,
            "recommendations": recs[:6],
            "priority": priority,
        }

    @staticmethod
    def _sales_manager_agent(snap: Any) -> dict[str, Any]:
        opps = snap.coordinated_opportunities[:6]
        risks = snap.coordinated_risks[:4]
        recs: list[str] = []

        for o in opps[:4]:
            recs.append(
                f"Review {o['title']}: health {o['opportunity_health']}, "
                f"close {o['closing_probability']}%, risk {o['deal_risk']}"
            )
        for r in risks[:3]:
            recs.append(f"Mitigate risk: {r['issue']} ({r['severity']})")
        dr = getattr(snap, "deal_risk", None) or {}
        for row in (dr.get("highest_risk_deals") or [])[:2]:
            recs.append(
                f"Deal intervention: {row.get('title')} — {row.get('risk_level', '').replace('_', ' ')}"
            )
        for mr in snap.manager_recommendations[:2]:
            recs.append(mr.get("title") or mr.get("action", "Review sales manager recommendation"))

        if not recs:
            recs.append("Scan deal room and CRM pipeline for opportunities needing manual follow-up")

        high_risk = sum(1 for o in opps if o.get("deal_risk") in ("high", "critical"))
        priority = "urgent" if high_risk >= 2 else "high" if high_risk else "medium"
        avg_close = (
            round(sum(o.get("closing_probability", 0) for o in opps) / len(opps), 1)
            if opps
            else 0
        )
        summary = (
            f"Tracking {len(snap.coordinated_opportunities)} opportunities "
            f"with avg closing probability {avg_close}%. "
            f"{len(risks)} deal risks flagged — manual deal review only."
        )
        return {
            "agent_name": AGENT_NAMES[1],
            "summary": summary,
            "recommendations": recs[:6],
            "priority": priority,
        }

    @staticmethod
    def _lead_analyst_agent(snap: Any) -> dict[str, Any]:
        leads = snap.priority_leads[:8]
        metrics = snap.lead_metrics or {}
        recs: list[str] = []

        for lead in leads[:5]:
            recs.append(
                f"Lead {lead['name']}: score {lead.get('lead_score', 0)}, "
                f"urgency {lead.get('urgency', 'medium')} — {lead.get('recommended_action') or 'qualify manually'}"
            )
        inactive = metrics.get("inactive_count") or metrics.get("inactive_leads") or 0
        if inactive:
            recs.append(f"Recovery plan for {inactive} inactive lead(s) — manual outreach only")
        cold = metrics.get("cold_count") or metrics.get("cold_leads") or 0
        if cold:
            recs.append(f"Re-engage {cold} cold lead(s) with nurture sequence (manual)")

        if not recs:
            recs.append("Run lead intelligence review and update CRM qualification manually")

        hot = exec_hot = snap.executive_summary.get("hot_leads", 0)
        priority = "urgent" if hot >= 5 else "high" if hot >= 2 else "medium"
        summary = (
            f"Prioritized {len(leads)} leads from intelligence layer. "
            f"{exec_hot} hot lead(s), qualification and scoring advisory only."
        )
        return {
            "agent_name": AGENT_NAMES[2],
            "summary": summary,
            "recommendations": recs[:6],
            "priority": priority,
        }

    @staticmethod
    def _communication_agent(snap: Any) -> dict[str, Any]:
        convs = snap.priority_conversations[:8]
        comm = snap.comm_overview or {}
        recs: list[str] = []
        channels_seen: set[str] = set()

        for c in convs[:5]:
            ch = c.get("channel", "unknown")
            channels_seen.add(ch)
            recs.append(
                f"[{ch}] {c.get('contact_name') or c['conversation_id']}: "
                f"urgency {c.get('response_urgency', 'medium')} — "
                f"{c.get('recommended_action') or 'manual follow-up'}"
            )

        health = comm.get("communication_health_score") or comm.get("avg_health") or 50
        if health < 50:
            recs.append("Communication health below target — review unified inbox backlog")
        recs.append("Sources: Unified Inbox, WeChat Center, WhatsApp Center (read-only monitoring)")

        urgent = sum(1 for c in convs if c.get("response_urgency") in ("urgent", "high"))
        priority = "urgent" if urgent >= 3 else "high" if urgent else "medium"
        summary = (
            f"Monitoring {len(convs)} priority conversations across "
            f"{', '.join(sorted(channels_seen)) or 'inbox channels'}. "
            f"Communication health {round(float(snap.executive_summary.get('communication_health', health)), 1)}. "
            "No automatic messaging."
        )
        return {
            "agent_name": AGENT_NAMES[3],
            "summary": summary,
            "recommendations": recs[:6],
            "priority": priority,
        }

    @staticmethod
    def _operations_agent(snap: Any) -> dict[str, Any]:
        overdue = snap.overdue_actions
        escalations = snap.escalation_list
        actions = snap.recommended_actions[:6]
        workflow = snap.workflow_summary or {}
        recs: list[str] = []

        for a in overdue[:4]:
            recs.append(f"OVERDUE: {a['title']} — {a.get('description', '')[:80]}")
        for e in escalations[:3]:
            recs.append(f"ESCALATE: {e['title']} ({e.get('priority', 'high')})")
        for a in actions[:3]:
            if not a.get("is_overdue"):
                recs.append(f"Task: {a['title']} ({a.get('priority', 'medium')})")
        bottlenecks = workflow.get("bottlenecks") or workflow.get("bottleneck_count") or 0
        if bottlenecks:
            recs.append(f"Workflow bottleneck(s) detected ({bottlenecks}) — manual process review")

        if not recs:
            recs.append("Operator task queue stable — continue manual workflow monitoring")

        priority = "urgent" if len(overdue) >= 3 else "high" if overdue else "medium"
        summary = (
            f"{len(snap.recommended_actions)} recommended actions, "
            f"{len(overdue)} overdue, {len(escalations)} escalation(s). "
            "No automatic task execution."
        )
        return {
            "agent_name": AGENT_NAMES[4],
            "summary": summary,
            "recommendations": recs[:6],
            "priority": priority,
        }

    @staticmethod
    def _coordinate(agents: list[dict[str, Any]], snap: Any) -> dict[str, Any]:
        exec_sum = snap.executive_summary
        dept_health = exec_sum.get("business_health_score", 50)

        structured_recs: list[dict[str, Any]] = []
        for agent in agents:
            for text in agent["recommendations"]:
                structured_recs.append({
                    "title": text[:120] if len(text) > 120 else text,
                    "description": text,
                    "priority": agent["priority"],
                    "source_agent": agent["agent_name"],
                    "category": agent["agent_name"].replace(" Agent", "").lower().replace(" ", "_"),
                })

        structured_recs.sort(
            key=lambda x: _PRIORITY_RANK.get(x.get("priority", "medium"), 3),
        )
        top = structured_recs[:12]

        conflicts: list[dict[str, Any]] = []
        director = agents[0]
        operations = agents[4]
        if director["priority"] in ("high", "urgent") and operations["priority"] == "urgent":
            conflicts.append({
                "topic": "Growth vs operations capacity",
                "agents": [director["agent_name"], operations["agent_name"]],
                "description": (
                    "Executive priorities emphasize revenue acceleration while operations "
                    "flags overdue tasks — balance manually before increasing outreach."
                ),
            })
        manager = agents[1]
        comm = agents[3]
        if manager["priority"] == "urgent" and comm["priority"] == "urgent":
            conflicts.append({
                "topic": "Deal push vs inbox response",
                "agents": [manager["agent_name"], comm["agent_name"]],
                "description": (
                    "High deal risk and urgent inbox threads compete for operator attention — "
                    "sequence responses manually."
                ),
            })

        combined = (
            f"Five-agent sales team advisory: department health {dept_health}/100 "
            f"({_health_label(dept_health)}). "
            f"{len(snap.priority_leads)} priority leads, "
            f"{len(snap.coordinated_opportunities)} opportunities, "
            f"{len(snap.overdue_actions)} overdue actions. "
            "All outputs are recommendations only."
        )

        return {
            "combined_summary": combined,
            "top_recommendations": top,
            "conflicts": conflicts,
            "department_health": dept_health,
            "department_health_label": _health_label(dept_health),
        }

    @staticmethod
    def _agent_health_scores(
        agents: list[dict[str, Any]],
        snap: Any,
    ) -> dict[str, int]:
        exec_health = snap.executive_summary.get("business_health_score", 50)
        comm_health = int(snap.executive_summary.get("communication_health", 50))
        overdue_penalty = min(40, len(snap.overdue_actions) * 8)
        risk_penalty = min(30, len(snap.coordinated_risks) * 3)

        base_scores = {
            AGENT_NAMES[0]: exec_health,
            AGENT_NAMES[1]: max(20, exec_health - risk_penalty),
            AGENT_NAMES[2]: max(25, exec_health - max(0, 10 - snap.executive_summary.get("hot_leads", 0) * 2)),
            AGENT_NAMES[3]: comm_health,
            AGENT_NAMES[4]: max(15, 100 - overdue_penalty - risk_penalty // 2),
        }
        for agent in agents:
            if agent["priority"] == "urgent":
                name = agent["agent_name"]
                base_scores[name] = max(15, base_scores.get(name, 50) - 10)
        return base_scores
