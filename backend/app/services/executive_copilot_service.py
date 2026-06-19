"""AI Executive Copilot v1 — business-wide executive command center (heuristic, read-only)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.endpoint_guard import safe_section
from app.models.communication import CommunicationThread
from app.models.crm_lead import CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.operator_task import OperatorTask
from app.services.operator_task_service import TERMINAL_STATUSES
from app.services.revenue_service import RevenueService
from app.services.sales_manager_service import SalesManagerService
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.buyer_discovery_service import BuyerDiscoveryService
from app.services.buyer_network_service import BuyerNetworkService
from app.services.buyer_acquisition_service import BuyerAcquisitionService
from app.services.buyer_acquisition_engine_service import BuyerAcquisitionEngineService
from app.services.marketplace_service import MarketplaceService
from app.services.deal_risk_service import DealRiskService
from app.services.revenue_attribution_service import RevenueAttributionService
from app.services.wechat_sync_service import WeChatSyncService
from app.services.wechat_provider_service import WeChatProviderService
from app.services.whatsapp_sync_service import WhatsAppSyncService
from app.services.whatsapp_provider_service import WhatsAppProviderService
from app.services.factory_partner_portal_service import FactoryPartnerPortalService
from app.services.pilot_onboarding_service import PilotOnboardingService
from app.services.pilot_execution_service import PilotExecutionService
from app.services.pilot_launch_service import PilotLaunchService
from app.services.pilot_demo_service import PilotDemoService
from app.services.pilot_sales_demo_service import PilotSalesDemoService
from app.services.pilot_launch_validation_service import PilotLaunchValidationService
from app.services.first_pilot_client_service import FirstPilotClientService
from app.services.production_deployment_service import ProductionDeploymentService
from app.services.real_factory_pilot_service import RealFactoryPilotService
from app.services.revenue_engine_service import RevenueEngineService
from app.services.tenant_service import TenantService
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

MARKER = "[Executive Copilot]"

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _priority_rank(p: str) -> int:
    return {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(p, 4)


def _severity_rank(s: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(s, 4)


def _decimal_to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class _ExecutiveSnapshot:
    now: datetime
    client_id: UUID | None = None
    sales_overview: dict[str, Any] = field(default_factory=dict)
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    lead_metrics: dict[str, Any] = field(default_factory=dict)
    revenue: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class ExecutiveCopilotService:
    """Aggregates CRM, lead intelligence, sales manager, inbox, proposals, workflows — advisory only."""

    @staticmethod
    def _overview_from_snapshot(snap: _ExecutiveSnapshot) -> dict[str, Any]:
        ov = snap.sales_overview
        inbox = ov.get("inbox_activity") or {}
        workload = ov.get("operator_workload") or {}
        rev = snap.revenue

        active_conversations = int(inbox.get("open_conversations") or 0) + int(
            inbox.get("whatsapp_threads") or 0,
        )

        return {
            "revenue": {
                "closed_revenue": _decimal_to_float(rev.get("closed_revenue")),
                "pipeline_value": _decimal_to_float(rev.get("pipeline_value")),
                "deals_won": int(rev.get("deals_won") or 0),
                "pending_commission": _decimal_to_float(rev.get("pending_commission")),
                "currency": "UZS",
            },
            "opportunities": int(ov.get("opportunities_count") or len(snap.opportunities)),
            "hot_leads": int(ov.get("hot_leads") or snap.lead_metrics.get("hot_leads") or 0),
            "overdue_tasks": int(ov.get("overdue_tasks") or workload.get("overdue_tasks") or 0),
            "active_conversations": active_conversations,
            "proposals_pending": int(ov.get("active_proposals") or 0),
            "risk_count": len(snap.risks),
            "business_health_score": ExecutiveCopilotService._health_score(snap),
            "leads_count": int(ov.get("leads_count") or 0),
            "open_tasks": int(workload.get("open_tasks") or 0),
            "workflow_recommendations": int(ov.get("workflow_recommendations") or 0),
            "revenue_attribution": snap.lead_metrics.get("revenue_attribution") or {},
            "wechat_sync": snap.lead_metrics.get("wechat_sync") or {},
            "wechat_provider": snap.lead_metrics.get("wechat_provider") or {},
            "whatsapp_sync": snap.lead_metrics.get("whatsapp_sync") or {},
            "whatsapp_provider": snap.lead_metrics.get("whatsapp_provider") or {},
            "tenants": snap.lead_metrics.get("tenants") or {},
            "subscription_billing": snap.lead_metrics.get("subscription_billing") or {},
            "errors": snap.errors,
        }

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        if tenant_id:
            client_id, _ = await TenantService.resolve_tenant_client_scope(
                db, tenant_id=tenant_id, client_id=client_id,
            )
        snap = await ExecutiveCopilotService._build_overview_snapshot(db, client_id=client_id)
        return ExecutiveCopilotService._overview_from_snapshot(snap)

    @staticmethod
    async def alerts(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        snap = await ExecutiveCopilotService._build_snapshot(db, client_id=client_id)
        items = ExecutiveCopilotService._build_alerts(snap)[:limit]
        return {"items": items, "total": len(items)}

    @staticmethod
    async def recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        snap = await ExecutiveCopilotService._build_snapshot(db, client_id=client_id)
        ExecutiveCopilotService._build_executive_recommendations(snap)
        items = snap.recommendations[:limit]
        return {"items": items, "total": len(snap.recommendations)}

    @staticmethod
    async def generate_briefing(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await ExecutiveCopilotService._build_snapshot(db, client_id=client_id)
        ExecutiveCopilotService._build_executive_recommendations(snap)
        now = snap.now
        ov = snap.sales_overview
        rev = snap.revenue
        health = ExecutiveCopilotService._health_score(snap)

        summary = (
            f"Executive business snapshot (health {health}/100): "
            f"{int(ov.get('leads_count') or 0)} active leads ({int(ov.get('hot_leads') or 0)} hot). "
            f"Revenue closed {_decimal_to_float(rev.get('closed_revenue')):,.0f} UZS, "
            f"pipeline {_decimal_to_float(rev.get('pipeline_value')):,.0f} UZS. "
            f"{len(snap.opportunities)} opportunities, {len(snap.risks)} risks, "
            f"{int(ov.get('overdue_tasks') or 0)} overdue operator tasks, "
            f"{int(ov.get('active_proposals') or 0)} pending proposals. "
            "All actions require manual operator approval."
        )

        opportunities = [
            f"{o['title']} — {o.get('action', 'Review manually')}"
            for o in snap.opportunities[:6]
        ]
        if not opportunities:
            opportunities = ["Pipeline stable — continue proactive outreach"]

        risks = [r["issue"] for r in snap.risks[:6]]
        if not risks:
            risks = ["No critical business risks flagged"]

        recs = [
            f"{r['title']}: {r['description']}"
            for r in snap.recommendations[:6]
        ]
        if not recs:
            recs = [
                "Review CRM pipeline and hot leads",
                "Check unified inbox and messaging channels",
                "Review operator task queue for overdue items",
            ]

        comm_intel = snap.lead_metrics.get("communication_intelligence") or {}
        comm_lines: list[str] = []
        if comm_intel:
            comm_lines.append(
                f"Communication intelligence: {comm_intel.get('hot_buyers', 0)} hot buyer conversations, "
                f"{comm_intel.get('follow_ups_required', 0)} follow-ups required, "
                f"{comm_intel.get('inactive_conversations', 0)} inactive threads."
            )
        if comm_lines:
            recs = comm_lines[:2] + recs

        rev_attr = snap.lead_metrics.get("revenue_attribution") or {}
        if rev_attr.get("summary"):
            recs = [f"Revenue attribution: {rev_attr['summary']}"] + recs

        logger.info("%s briefing generated client=%s health=%s", MARKER, client_id, health)
        return {
            "summary": summary,
            "business_health_score": health,
            "opportunities": opportunities,
            "risks": risks,
            "recommendations": recs,
            "communication_intelligence": comm_intel,
            "source": "heuristic",
            "generated_at": now,
            "errors": snap.errors,
        }

    @staticmethod
    def _apply_client_filter(query, column, client_id: UUID | None):
        if client_id:
            return query.where(column == client_id)
        return query

    @staticmethod
    async def _build_widget_snapshot(db: AsyncSession, *, client_id: UUID | None) -> _ExecutiveSnapshot:
        """Fast path for summary-widget — aggregate SQL counts, no per-lead scans."""
        now = _utc_now()
        errors: list[str] = []
        snap = _ExecutiveSnapshot(now=now, client_id=client_id, errors=errors)

        async def _counts() -> dict[str, Any]:
            hot_q = select(func.count()).select_from(CrmLead).where(
                CrmLead.status.notin_(("won", "lost")),
                or_(
                    CrmLead.priority == "hot",
                    CrmLead.qualification_level.in_(("hot", "qualified_hot")),
                    CrmLead.lead_score >= 70,
                ),
            )
            hot_q = ExecutiveCopilotService._apply_client_filter(hot_q, CrmLead.client_id, client_id)

            leads_q = select(func.count()).select_from(CrmLead).where(
                CrmLead.status.notin_(("won", "lost")),
            )
            leads_q = ExecutiveCopilotService._apply_client_filter(leads_q, CrmLead.client_id, client_id)

            overdue_q = select(func.count()).select_from(OperatorTask).where(
                OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
                OperatorTask.due_at.isnot(None),
                OperatorTask.due_at < now,
            )
            overdue_q = ExecutiveCopilotService._apply_client_filter(
                overdue_q, OperatorTask.client_id, client_id,
            )

            open_tasks_q = select(func.count()).select_from(OperatorTask).where(
                OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            )
            open_tasks_q = ExecutiveCopilotService._apply_client_filter(
                open_tasks_q, OperatorTask.client_id, client_id,
            )

            proposals_q = select(func.count()).select_from(CrmProposal).where(
                CrmProposal.status.in_(("draft", "sent")),
            )
            proposals_q = ExecutiveCopilotService._apply_client_filter(
                proposals_q, CrmProposal.client_id, client_id,
            )

            conversations_q = select(func.count()).select_from(CommunicationThread).where(
                CommunicationThread.status.in_(("open", "waiting")),
            )
            conversations_q = ExecutiveCopilotService._apply_client_filter(
                conversations_q, CommunicationThread.client_id, client_id,
            )

            hot_leads = int(await db.scalar(hot_q) or 0)
            overdue_tasks = int(await db.scalar(overdue_q) or 0)
            open_tasks = int(await db.scalar(open_tasks_q) or 0)
            active_proposals = int(await db.scalar(proposals_q) or 0)
            active_conversations = int(await db.scalar(conversations_q) or 0)
            leads_count = int(await db.scalar(leads_q) or 0)

            opportunities = hot_leads + active_proposals
            risks: list[dict[str, Any]] = []
            opps: list[dict[str, Any]] = []

            if overdue_tasks:
                risks.append({
                    "issue": f"{overdue_tasks} overdue operator task(s)",
                    "severity": "high" if overdue_tasks >= 5 else "medium",
                    "recommendation": "Review operator task queue and assign owners manually",
                    "type": "overdue_tasks",
                    "source": "operator_tasks",
                })
            if hot_leads:
                opps.append({
                    "type": "hot_lead_follow_up",
                    "source": "crm",
                    "priority": "high",
                    "action": "Review hot leads in CRM",
                    "title": f"{hot_leads} hot lead(s) need attention",
                    "summary": "Manual follow-up recommended",
                })

            return {
                "sales_overview": {
                    "hot_leads": hot_leads,
                    "leads_count": leads_count,
                    "overdue_tasks": overdue_tasks,
                    "active_proposals": active_proposals,
                    "inbox_activity": {"open_conversations": active_conversations},
                    "operator_workload": {"open_tasks": open_tasks, "overdue_tasks": overdue_tasks},
                },
                "opportunities": opps,
                "risks": risks,
                "opportunity_count": opportunities,
            }

        counts = await safe_section(
            "executive_widget_counts",
            _counts(),
            default={
                "sales_overview": {},
                "opportunities": [],
                "risks": [],
                "opportunity_count": 0,
            },
            errors=errors,
            db=db,
            timeout=6.0,
        )

        snap.sales_overview = counts["sales_overview"]
        snap.opportunities = counts["opportunities"]
        snap.risks = counts["risks"]
        snap.sales_overview["opportunities_count"] = counts["opportunity_count"]

        async def _revenue() -> dict[str, Any]:
            data = await RevenueService.overview(db, deals_limit=5)
            return {
                "closed_revenue": data.get("total_closed_revenue"),
                "pipeline_value": data.get("total_pipeline_value"),
                "deals_won": data.get("deals_won"),
                "pending_commission": data.get("pending_commission"),
            }

        snap.revenue = await safe_section(
            "revenue",
            _revenue(),
            default={},
            errors=errors,
            db=db,
            timeout=6.0,
        )
        snap.lead_metrics["factory_partner_portal"] = await safe_section(
            "factory_partner_portal",
            FactoryPartnerPortalService.executive_pending(db, limit=10),
            default={"pending": [], "counts": {}},
            errors=errors,
            db=db,
            timeout=4.0,
        )
        snap.lead_metrics["subscription_billing"] = await safe_section(
            "subscription_billing",
            SubscriptionService.executive_overview(db),
            default={
                "mrr": 0.0,
                "active_subscriptions": 0,
                "trial_subscriptions": 0,
                "plan_distribution": {},
            },
            errors=errors,
            db=db,
            timeout=4.0,
        )
        return snap

    @staticmethod
    async def _build_overview_snapshot(
        db: AsyncSession,
        *,
        client_id: UUID | None,
    ) -> _ExecutiveSnapshot:
        """Fast path for /overview — widget aggregates plus key integration strips."""
        snap = await ExecutiveCopilotService._build_widget_snapshot(db, client_id=client_id)
        errors = snap.errors

        snap.lead_metrics["revenue_attribution"] = await safe_section(
            "revenue_attribution",
            RevenueAttributionService.insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
            timeout=2.0,
        )
        snap.lead_metrics["wechat_sync"] = await safe_section(
            "wechat_sync",
            WeChatSyncService.status_overview(db),
            default={},
            errors=errors,
            db=db,
            timeout=2.0,
        )
        snap.lead_metrics["whatsapp_sync"] = await safe_section(
            "whatsapp_sync",
            WhatsAppSyncService.status_overview(db),
            default={},
            errors=errors,
            db=db,
            timeout=2.0,
        )
        return snap

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await ExecutiveCopilotService._build_widget_snapshot(db, client_id=client_id)
        ExecutiveCopilotService._build_executive_recommendations(snap)
        ov = ExecutiveCopilotService._overview_from_snapshot(snap)
        alerts = ExecutiveCopilotService._build_alerts(snap)[:3]
        return {
            "business_health_score": ov["business_health_score"],
            "hot_leads": ov["hot_leads"],
            "opportunities": ov["opportunities"],
            "risk_count": ov["risk_count"],
            "overdue_tasks": ov["overdue_tasks"],
            "active_conversations": ov["active_conversations"],
            "proposals_pending": ov["proposals_pending"],
            "closed_revenue": ov["revenue"]["closed_revenue"],
            "revenue_attribution": snap.lead_metrics.get("revenue_attribution") or {},
            "top_alerts": alerts,
            "top_recommendations": snap.recommendations[:3],
            "factory_partner_pending": int(
                (snap.lead_metrics.get("factory_partner_portal") or {})
                .get("counts", {})
                .get("pending_review", 0),
            ),
            "subscription_mrr": float(
                (snap.lead_metrics.get("subscription_billing") or {}).get("mrr", 0),
            ),
            "active_subscriptions": int(
                (snap.lead_metrics.get("subscription_billing") or {}).get("active_subscriptions", 0),
            ),
        }

    @staticmethod
    async def _build_snapshot(db: AsyncSession, *, client_id: UUID | None) -> _ExecutiveSnapshot:
        now = _utc_now()
        errors: list[str] = []
        snap = _ExecutiveSnapshot(now=now, client_id=client_id, errors=errors)

        async def _sales_snapshot():
            inner = await SalesManagerService._build_snapshot(db, client_id=client_id)
            return inner

        inner = await safe_section(
            "sales_manager",
            _sales_snapshot(),
            default=None,
            errors=errors,
            db=db,
        )

        if inner is not None:
            snap.sales_overview = inner.overview or {}
            snap.opportunities = list(inner.opportunities or [])
            snap.risks = list(inner.risks or [])
            snap.lead_metrics = dict(inner.lead_metrics or {})

        async def _revenue() -> dict[str, Any]:
            data = await RevenueService.overview(db, deals_limit=5)
            return {
                "closed_revenue": data.get("total_closed_revenue"),
                "pipeline_value": data.get("total_pipeline_value"),
                "deals_won": data.get("deals_won"),
                "pending_commission": data.get("pending_commission"),
            }

        snap.revenue = await safe_section(
            "revenue",
            _revenue(),
            default={},
            errors=errors,
            db=db,
        )

        async def _comm_overview() -> dict[str, Any]:
            return await CommunicationIntelligenceService.overview(db, client_id=client_id)

        snap.lead_metrics["communication_intelligence"] = await safe_section(
            "communication_intelligence",
            _comm_overview(),
            default={},
            errors=errors,
            db=db,
        )

        async def _revenue_attribution() -> dict[str, Any]:
            return await RevenueAttributionService.insights(db, client_id=client_id)

        snap.lead_metrics["revenue_attribution"] = await safe_section(
            "revenue_attribution",
            _revenue_attribution(),
            default={},
            errors=errors,
            db=db,
        )

        async def _wechat_sync() -> dict[str, Any]:
            return await WeChatSyncService.status_overview(db)

        snap.lead_metrics["wechat_sync"] = await safe_section(
            "wechat_sync",
            _wechat_sync(),
            default={},
            errors=errors,
            db=db,
        )

        async def _wechat_provider() -> dict[str, Any]:
            return await WeChatProviderService.provider_health(db)

        snap.lead_metrics["wechat_provider"] = await safe_section(
            "wechat_provider",
            _wechat_provider(),
            default={},
            errors=errors,
            db=db,
        )

        async def _whatsapp_sync() -> dict[str, Any]:
            return await WhatsAppSyncService.status_overview(db)

        snap.lead_metrics["whatsapp_sync"] = await safe_section(
            "whatsapp_sync",
            _whatsapp_sync(),
            default={},
            errors=errors,
            db=db,
        )

        async def _whatsapp_provider() -> dict[str, Any]:
            return await WhatsAppProviderService.provider_health(db)

        snap.lead_metrics["whatsapp_provider"] = await safe_section(
            "whatsapp_provider",
            _whatsapp_provider(),
            default={},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["buyer_intelligence"] = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.executive_insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["buyer_discovery"] = await safe_section(
            "buyer_discovery",
            BuyerDiscoveryService.executive_insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["marketplace"] = await safe_section(
            "marketplace",
            MarketplaceService.executive_summary(db),
            default={},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["buyer_network"] = await safe_section(
            "buyer_network",
            BuyerNetworkService.executive_summary(db),
            default={},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["buyer_acquisition"] = await safe_section(
            "buyer_acquisition",
            BuyerAcquisitionService.executive_overview(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["buyer_acquisition_engine"] = await safe_section(
            "buyer_acquisition_engine",
            BuyerAcquisitionEngineService.executive_summary(db, client_id=client_id),
            default={"readiness_score": 0, "total_buyers": 0, "matched_buyers": 0},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["revenue_engine"] = await safe_section(
            "revenue_engine",
            RevenueEngineService.executive_summary(db, client_id=client_id),
            default={
                "readiness_score": 0,
                "health_status": "warning",
                "total_pipeline_value": 0,
                "forecasted_revenue": 0,
                "active_deals": 0,
            },
            errors=errors,
            db=db,
        )

        snap.lead_metrics["deal_risk"] = await safe_section(
            "deal_risk",
            DealRiskService.executive_insights(db, client_id=client_id),
            default={},
            errors=errors,
            db=db,
        )

        from app.services.deal_room_v2_service import DealRoomV2Service

        snap.lead_metrics["deal_room_v2"] = await safe_section(
            "deal_room_v2",
            DealRoomV2Service.executive_summary(db, client_id=client_id),
            default={
                "readiness_score": 0,
                "total_deal_rooms": 0,
                "active_deal_rooms": 0,
                "total_pipeline_value": 0,
            },
            errors=errors,
            db=db,
        )

        snap.lead_metrics["factory_partner_portal"] = await safe_section(
            "factory_partner_portal",
            FactoryPartnerPortalService.executive_pending(db, limit=10),
            default={"pending": [], "counts": {}},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["pilot_onboarding"] = await safe_section(
            "pilot_onboarding",
            PilotOnboardingService.executive_overview(db, limit=8),
            default={"pilot_ready_count": 0, "launch_candidates": []},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["pilot_launch"] = await safe_section(
            "pilot_launch",
            PilotLaunchService.executive_summary(db),
            default={"readiness_score": 0, "demo_data_present": False},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["pilot_execution"] = await safe_section(
            "pilot_execution",
            PilotExecutionService.executive_summary(db),
            default={
                "execution_data_present": False,
                "implementation_complete": False,
                "readiness_after": {},
            },
            errors=errors,
            db=db,
        )

        snap.lead_metrics["pilot_demo"] = await safe_section(
            "pilot_demo",
            PilotDemoService.executive_summary(db),
            default={"readiness_score": 0, "demo_data_present": False},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["pilot_sales_demo"] = await safe_section(
            "pilot_sales_demo",
            PilotSalesDemoService.executive_summary(db),
            default={
                "readiness_score": 0,
                "execution_data_present": False,
                "implementation_complete": False,
            },
            errors=errors,
            db=db,
        )

        snap.lead_metrics["pilot_launch_validation"] = await safe_section(
            "pilot_launch_validation",
            PilotLaunchValidationService.executive_summary(db),
            default={
                "readiness_score": 0,
                "execution_data_present": False,
                "implementation_complete": False,
            },
            errors=errors,
            db=db,
        )

        snap.lead_metrics["first_pilot_client"] = await safe_section(
            "first_pilot_client",
            FirstPilotClientService.executive_summary(db),
            default={"readiness_score": 0, "launch_ready": False, "client_identified": False},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["production_deployment"] = await safe_section(
            "production_deployment",
            ProductionDeploymentService.executive_summary(db),
            default={"production_readiness_score": 0, "deployment_ready": False},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["real_factory_pilot"] = await safe_section(
            "real_factory_pilot",
            RealFactoryPilotService.executive_summary(db),
            default={"readiness_score": 0, "status": "not_started", "factory_identified": False},
            errors=errors,
            db=db,
        )

        probe_tenant_id = None
        if client_id:
            from app.models.client import Client
            client = await db.get(Client, client_id)
            if client and client.tenant_id:
                probe_tenant_id = client.tenant_id

        async def _customer_portal() -> dict[str, Any]:
            from app.services.customer_portal_service import CustomerPortalService
            return await CustomerPortalService.partner_overview(db, limit=10)

        snap.lead_metrics["customer_portal"] = await safe_section(
            "customer_portal",
            _customer_portal(),
            default={"active_accounts": 0, "accounts": []},
            errors=errors,
            db=db,
        )

        async def _customer_portal_v2() -> dict[str, Any]:
            from app.services.customer_portal_v2_service import CustomerPortalV2Service
            return await CustomerPortalV2Service.health_overview(db, tenant_id=probe_tenant_id)

        snap.lead_metrics["customer_portal_v2"] = await safe_section(
            "customer_portal_v2",
            _customer_portal_v2(),
            default={"readiness": "needs_attention", "active_buyers": 0},
            errors=errors,
            db=db,
        )

        async def _tenants() -> dict[str, Any]:
            data = await TenantService.list_tenants(db, status="active", limit=10)
            return {
                "active_tenants": data["total"],
                "tenants": data["items"][:10],
            }

        snap.lead_metrics["tenants"] = await safe_section(
            "tenants",
            _tenants(),
            default={"active_tenants": 0, "tenants": []},
            errors=errors,
            db=db,
        )

        snap.lead_metrics["subscription_billing"] = await safe_section(
            "subscription_billing",
            SubscriptionService.executive_overview(db),
            default={
                "mrr": 0.0,
                "active_subscriptions": 0,
                "trial_subscriptions": 0,
                "plan_distribution": {},
            },
            errors=errors,
            db=db,
        )

        from app.services.factory_profile_service import FactoryProfileService

        snap.lead_metrics["factory_platform"] = await safe_section(
            "factory_platform",
            FactoryProfileService.executive_overview(db, tenant_id=probe_tenant_id),
            default={"performance": {}, "readiness": {}},
            errors=errors,
            db=db,
        )

        return snap

    @staticmethod
    def _health_score(snap: _ExecutiveSnapshot) -> int:
        """Heuristic 0–100 score — higher is healthier."""
        ov = snap.sales_overview
        score = 100

        overdue = int(ov.get("overdue_tasks") or 0)
        score -= min(30, overdue * 4)

        risks = len(snap.risks)
        score -= min(25, risks * 3)

        neglected = int(snap.lead_metrics.get("neglected_leads") or ov.get("neglected_leads") or 0)
        score -= min(15, neglected * 2)

        inactive = int(snap.lead_metrics.get("inactive_leads") or 0)
        score -= min(10, inactive)

        unanswered = int((ov.get("inbox_activity") or {}).get("unanswered") or 0)
        score -= min(15, unanswered * 3)

        unassigned = int((ov.get("operator_workload") or {}).get("unassigned_tasks") or 0)
        score -= min(10, unassigned * 2)

        hot = int(ov.get("hot_leads") or 0)
        if hot > 0 and snap.opportunities:
            hot_followups = sum(1 for o in snap.opportunities if o.get("type") == "hot_lead_no_followup")
            score -= min(10, hot_followups * 5)

        return max(0, min(100, score))

    @staticmethod
    def _build_alerts(snap: _ExecutiveSnapshot) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []

        for risk in snap.risks:
            items.append({
                "id": str(uuid4()),
                "type": risk.get("type") or "risk",
                "severity": risk.get("severity") or "medium",
                "title": (risk.get("issue") or "Risk")[:200],
                "message": risk.get("recommendation") or "Review manually",
                "source": risk.get("source") or "crm",
                "lead_id": risk.get("lead_id"),
                "deal_id": risk.get("deal_id"),
                "conversation_id": risk.get("conversation_id"),
            })

        for opp in snap.opportunities:
            if opp.get("priority") not in ("urgent", "high"):
                continue
            items.append({
                "id": str(uuid4()),
                "type": opp.get("type") or "opportunity",
                "severity": "high" if opp.get("priority") == "urgent" else "medium",
                "title": (opp.get("title") or "Opportunity")[:200],
                "message": opp.get("action") or opp.get("summary") or "Review manually",
                "source": opp.get("source") or "crm",
                "lead_id": opp.get("lead_id"),
                "deal_id": opp.get("deal_id"),
                "conversation_id": opp.get("conversation_id"),
            })

        factory_data = snap.lead_metrics.get("factory_partner_portal") or {}
        for app in factory_data.get("pending") or []:
            items.append({
                "id": str(app.get("id") or uuid4()),
                "type": "factory_partner_application",
                "severity": "medium",
                "title": f"Factory application: {app.get('company_name') or 'Unknown'}",
                "message": f"Status {app.get('status')} — review in Factory Partners admin",
                "source": "factory_partner_portal",
                "application_id": app.get("id"),
            })

        items.sort(key=lambda x: (_severity_rank(x["severity"]), x["title"]))
        return items

    @staticmethod
    def _build_executive_recommendations(snap: _ExecutiveSnapshot) -> None:
        recs: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _add(
            category: str,
            title: str,
            description: str,
            priority: str,
            *,
            lead_id: UUID | None = None,
            conversation_id: str | None = None,
            entity_id: str | None = None,
            source: str = "crm",
        ) -> None:
            key = f"{category}:{title}"
            if key in seen:
                return
            seen.add(key)
            recs.append({
                "category": category,
                "title": title,
                "description": description,
                "priority": priority,
                "lead_id": lead_id,
                "conversation_id": conversation_id,
                "entity_id": entity_id,
                "source": source,
            })

        for opp in snap.opportunities:
            otype = opp.get("type") or ""
            if otype == "hot_lead_no_followup":
                _add(
                    "hot_lead_follow_up",
                    opp["title"],
                    opp.get("action") or "Schedule manual follow-up with hot lead",
                    opp.get("priority") or "high",
                    lead_id=opp.get("lead_id"),
                    entity_id=opp.get("entity_id"),
                    source=opp.get("source") or "crm",
                )
            elif otype == "proposal_no_followup":
                _add(
                    "proposal_follow_up",
                    opp["title"],
                    opp.get("action") or "Follow up on proposal manually",
                    opp.get("priority") or "high",
                    lead_id=opp.get("lead_id"),
                    entity_id=opp.get("entity_id"),
                    source="proposals",
                )
            elif otype in ("reply_needed", "unanswered_inbox"):
                _add(
                    "conversation_response_reminder",
                    opp["title"],
                    opp.get("action") or "Reply manually — no auto-send",
                    opp.get("priority") or "high",
                    lead_id=opp.get("lead_id"),
                    conversation_id=opp.get("conversation_id"),
                    entity_id=opp.get("entity_id"),
                    source=opp.get("source") or "unified_inbox",
                )
            elif otype == "overdue_operator_task":
                _add(
                    "overdue_task_escalation",
                    opp["title"],
                    opp.get("action") or "Complete or reschedule task manually",
                    opp.get("priority") or "urgent",
                    lead_id=opp.get("lead_id"),
                    entity_id=opp.get("entity_id"),
                    source="operator_tasks",
                )

        inactive = int(snap.lead_metrics.get("inactive_leads") or 0)
        if inactive:
            _add(
                "inactive_lead_recovery",
                f"Recover {inactive} inactive lead(s)",
                "Review inactive leads in CRM and plan manual re-engagement",
                "medium" if inactive < 5 else "high",
                source="lead_intelligence",
            )

        for lead in snap.lead_metrics.get("inactive_lead_samples") or []:
            _add(
                "inactive_lead_recovery",
                f"Inactive lead: {lead.get('name', 'Lead')}",
                lead.get("recommended_action") or "Manual outreach to re-activate",
                "medium",
                lead_id=lead.get("lead_id"),
                source="lead_intelligence",
            )

        for risk in snap.risks:
            rtype = risk.get("type") or ""
            if rtype == "neglected_leads":
                _add(
                    "inactive_lead_recovery",
                    "Address neglected leads",
                    risk.get("recommendation") or "Review CRM neglected leads",
                    "high",
                    source="crm",
                )
            elif rtype == "overdue_proposal":
                _add(
                    "proposal_follow_up",
                    risk["issue"],
                    risk.get("recommendation") or "Chase proposal manually",
                    "high",
                    source="proposals",
                )
            elif rtype == "unanswered_inbox":
                _add(
                    "conversation_response_reminder",
                    risk["issue"],
                    risk.get("recommendation") or "Reply manually",
                    "high" if risk.get("severity") in ("critical", "high") else "medium",
                    conversation_id=risk.get("conversation_id"),
                    source=risk.get("source") or "unified_inbox",
                )
            elif rtype in ("unanswered_conversation", "inactive_conversation"):
                _add(
                    "conversation_response_reminder",
                    risk["issue"],
                    risk.get("recommendation") or "Review communication intelligence",
                    "high" if risk.get("severity") in ("critical", "high") else "medium",
                    lead_id=risk.get("lead_id"),
                    conversation_id=risk.get("conversation_id"),
                    source="communication_intelligence",
                )
            elif rtype == "unassigned_tasks":
                _add(
                    "overdue_task_escalation",
                    risk["issue"],
                    risk.get("recommendation") or "Assign tasks manually",
                    "medium",
                    source="operator_tasks",
                )

        recs.sort(key=lambda x: (_priority_rank(x["priority"]), x["title"]))
        snap.recommendations = recs[:30]
