"""AI Sales Department Dashboard — executive factory sales performance (read-only)."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.attribution_link import AttributionLink, ClickEvent
from app.models.buyer_recommendation import BuyerRecommendation
from app.models.crm_deal import CrmDeal
from app.models.crm_document import CrmDocument
from app.models.crm_lead import CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.export_agent import ExportOpportunity
from app.models.landing_page import LandingLead, LandingPage
from app.models.partner import Partner
from app.models.product import Product
from app.models.sales_agent_recommendation import SalesAgentRecommendation
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.crm_attribution import ATTRIBUTION_LABELS, attribution_source_expr, normalize_attribution_key
from app.services.dashboard_service import DashboardService
from app.services.export_agent_service import _lead_matches_product
from app.services.lead_intelligence_service import LeadIntelligenceService
from app.services.operator_task_engine_service import OperatorTaskEngineService
from app.services.sales_assistant_service import SalesAssistantService
from app.services.sales_manager_service import SalesManagerService
from app.services.schema_guard import SchemaGuard

logger = logging.getLogger(__name__)

_MARKER = "[Sales Department Dashboard]"

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})

_FUNNEL_STATUSES = (
    "new", "contacted", "qualified", "proposal_sent", "negotiation", "won", "lost",
)

_AI_SYSTEM = """\
You are an executive briefing assistant for a Chinese factory's AI sales department.
Analyze sales metrics and return ONLY JSON:
{
  "executive_summary": "2-4 sentences on sales department performance",
  "what_is_working": ["item 1", "item 2"],
  "risks": ["risk 1", "risk 2"],
  "opportunities": ["opportunity 1", "opportunity 2"],
  "recommended_actions": ["manual action 1", "manual action 2"],
  "priority_score": 0 to 100
}

Rules:
- Read-only advisory — never suggest auto-messaging, auto status changes, or payments
- Recommend manual operator review only
- Be specific using metrics from the context
- Max 5 items per list
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: datetime | None) -> datetime | None:
    if raw is None:
        return None
    if raw.tzinfo is None:
        return raw.replace(tzinfo=timezone.utc)
    return raw


def _rate(num: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return round(num / denom * 100, 2)


def _lead_in_range(lead: CrmLead, date_from: datetime | None, date_to: datetime | None) -> bool:
    created = _parse_dt(lead.created_at)
    if date_from and created and created < date_from:
        return False
    if date_to and created and created > date_to:
        return False
    return True


def _deal_in_range(deal: CrmDeal, date_from: datetime | None, date_to: datetime | None) -> bool:
    ts = _parse_dt(deal.updated_at or deal.created_at)
    if date_from and ts and ts < date_from:
        return False
    if date_to and ts and ts > date_to:
        return False
    return True


def _infer_country_from_lead(lead: CrmLead) -> str | None:
    blob = " ".join(filter(None, [lead.notes, lead.interest, lead.company]))
    for c in (
        "Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan", "Turkmenistan",
        "Russia", "China", "Turkey", "UAE", "Saudi Arabia", "India", "Pakistan",
    ):
        if c.lower() in blob.lower():
            return c
    return None


class SalesDepartmentDashboardService:
    @staticmethod
    async def _safe_section(
        name: str,
        coro,
        *,
        default: Any,
        errors: list[str],
        db: AsyncSession | None = None,
        timeout: float = 10.0,
    ) -> Any:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except Exception as exc:
            msg = f"{name}: {exc}"
            logger.warning("%s section failed: %s", _MARKER, msg)
            errors.append(msg)
            if db is not None:
                await db.rollback()
            return default

    @staticmethod
    def _filters_payload(
        client_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> dict[str, Any]:
        return {
            "client_id": str(client_id) if client_id else None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        }

    @staticmethod
    async def dashboard(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        now = _utc_now()
        filters = SalesDepartmentDashboardService._filters_payload(client_id, date_from, date_to)

        async def _load_leads() -> list[CrmLead]:
            q = select(CrmLead)
            if client_id:
                q = q.where(CrmLead.client_id == client_id)
            if date_from:
                q = q.where(CrmLead.created_at >= date_from)
            if date_to:
                q = q.where(CrmLead.created_at <= date_to)
            q = await SchemaGuard.apply_crm_lead_query_options(db, q)
            r = await db.execute(q)
            return list(r.scalars().all())

        async def _load_deals() -> list[CrmDeal]:
            q = select(CrmDeal).options(selectinload(CrmDeal.lead))
            if client_id:
                q = q.where(CrmDeal.client_id == client_id)
            r = await db.execute(q)
            deals = list(r.scalars().all())
            if date_from or date_to:
                deals = [d for d in deals if _deal_in_range(d, date_from, date_to)]
            return deals

        leads = await SalesDepartmentDashboardService._safe_section(
            "leads", _load_leads(), default=[], errors=errors, db=db,
        )
        deals = await SalesDepartmentDashboardService._safe_section(
            "deals", _load_deals(), default=[], errors=errors, db=db,
        )

        async def _overview() -> dict[str, Any]:
            active = [d for d in deals if d.status in _ACTIVE_DEAL_STATUSES]
            won = [d for d in deals if d.status == "won"]
            lost = [d for d in deals if d.status == "lost"]

            partner_q = select(func.count()).select_from(Partner).where(Partner.status == "active")
            partners = int(await db.scalar(partner_q) or 0)

            buyer_q = select(func.count()).select_from(BuyerRecommendation)
            if client_id:
                buyer_q = buyer_q.where(BuyerRecommendation.client_id == client_id)
            if date_from:
                buyer_q = buyer_q.where(BuyerRecommendation.created_at >= date_from)
            if date_to:
                buyer_q = buyer_q.where(BuyerRecommendation.created_at <= date_to)
            buyer_count = int(await db.scalar(buyer_q) or 0)

            landing_q = (
                select(func.count())
                .select_from(LandingLead)
                .join(LandingPage, LandingLead.landing_page_id == LandingPage.id)
            )
            if client_id:
                landing_q = landing_q.where(LandingPage.client_id == client_id)
            if date_from:
                landing_q = landing_q.where(LandingLead.created_at >= date_from)
            if date_to:
                landing_q = landing_q.where(LandingLead.created_at <= date_to)
            landing_leads = int(await db.scalar(landing_q) or 0)

            clicks_q = select(func.coalesce(func.sum(AttributionLink.clicks_count), 0))
            if client_id:
                clicks_q = clicks_q.where(AttributionLink.client_id == client_id)
            link_clicks = int(await db.scalar(clicks_q) or 0)

            if date_from or date_to:
                ev_q = select(func.count()).select_from(ClickEvent).join(
                    AttributionLink, ClickEvent.attribution_link_id == AttributionLink.id,
                )
                if client_id:
                    ev_q = ev_q.where(AttributionLink.client_id == client_id)
                if date_from:
                    ev_q = ev_q.where(ClickEvent.created_at >= date_from)
                if date_to:
                    ev_q = ev_q.where(ClickEvent.created_at <= date_to)
                link_clicks = int(await db.scalar(ev_q) or 0)

            pending_q = select(func.coalesce(func.sum(CrmDeal.commission_amount), 0)).where(
                CrmDeal.status == "won",
                (CrmDeal.commission_status.is_(None))
                | (CrmDeal.commission_status.in_(("pending", "approved"))),
            )
            if client_id:
                pending_q = pending_q.where(CrmDeal.client_id == client_id)
            pending = Decimal(str(await db.scalar(pending_q) or 0))

            return {
                "total_leads": len(leads),
                "new_leads": sum(1 for l in leads if l.status == "new"),
                "qualified_leads": sum(1 for l in leads if l.status == "qualified"),
                "active_deals": len(active),
                "won_deals": len(won),
                "lost_deals": len(lost),
                "pipeline_value": sum((d.expected_value or Decimal("0")) for d in active),
                "closed_revenue": sum((d.deal_amount or Decimal("0")) for d in won),
                "commission_earned": sum((d.commission_amount or Decimal("0")) for d in won),
                "pending_commission": pending,
                "partner_count": partners,
                "buyer_recommendations_count": buyer_count,
                "landing_page_leads": landing_leads,
                "attribution_clicks": link_clicks,
            }

        async def _funnel() -> dict[str, int]:
            counts = {s: 0 for s in _FUNNEL_STATUSES}
            for lead in leads:
                st = lead.status if lead.status in counts else "new"
                counts[st] = counts.get(st, 0) + 1
            return {
                "leads": len(leads),
                "contacted": counts.get("contacted", 0),
                "qualified": counts.get("qualified", 0),
                "proposal_sent": counts.get("proposal_sent", 0),
                "negotiation": counts.get("negotiation", 0),
                "won": counts.get("won", 0),
                "lost": counts.get("lost", 0),
            }

        async def _top_products() -> list[dict[str, Any]]:
            pq = select(Product)
            if client_id:
                pq = pq.where(Product.client_id == client_id)
            products = list((await db.execute(pq)).scalars().all())
            if not products:
                return []

            buyer_counts: dict[UUID, int] = {}
            br = await db.execute(
                select(BuyerRecommendation.product_id, func.count())
                .group_by(BuyerRecommendation.product_id)
            )
            for pid, cnt in br.all():
                buyer_counts[pid] = int(cnt)

            lead_by_id = {l.id: l for l in leads}
            rows: list[dict[str, Any]] = []
            for product in products:
                matched_leads = [l for l in leads if _lead_matches_product(l, product)]
                matched_lead_ids = {l.id for l in matched_leads}
                matched_deals = [d for d in deals if d.lead_id in matched_lead_ids]
                won = [d for d in matched_deals if d.status == "won"]
                rows.append({
                    "product_id": product.id,
                    "product_name": product.name,
                    "leads_count": len(matched_leads),
                    "deals_count": len(matched_deals),
                    "revenue": sum((d.deal_amount or Decimal("0")) for d in won),
                    "buyer_recommendations_count": buyer_counts.get(product.id, 0),
                })
            rows.sort(key=lambda x: (x["revenue"], x["leads_count"]), reverse=True)
            return rows[:10]

        async def _top_countries() -> list[dict[str, Any]]:
            country_leads: Counter[str] = Counter()
            country_deals: Counter[str] = Counter()
            country_rev: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

            for lead in leads:
                c = _infer_country_from_lead(lead)
                if c:
                    country_leads[c] += 1

            pr = await db.execute(select(Partner).where(Partner.status == "active"))
            for p in pr.scalars().all():
                if p.country:
                    country_leads[p.country] += 1

            lead_map = {l.id: l for l in leads}
            for deal in deals:
                lead = deal.lead or lead_map.get(deal.lead_id)
                c = _infer_country_from_lead(lead) if lead else None
                if not c and lead and lead.partner_id:
                    continue
                if c:
                    country_deals[c] += 1
                    if deal.status == "won":
                        country_rev[c] += deal.deal_amount or Decimal("0")

            opp_scores: dict[str, float] = {}
            oq = select(ExportOpportunity)
            if client_id:
                oq = oq.where(ExportOpportunity.client_id == client_id)
            for opp in (await db.execute(oq)).scalars().all():
                prev = opp_scores.get(opp.country, 0.0)
                opp_scores[opp.country] = max(prev, float(opp.score or 0))

            countries = set(country_leads) | set(country_deals) | set(opp_scores)
            rows = [
                {
                    "country": c,
                    "leads_count": country_leads.get(c, 0),
                    "deals_count": country_deals.get(c, 0),
                    "revenue": country_rev.get(c, Decimal("0")),
                    "opportunity_score": opp_scores.get(c, 0.0),
                }
                for c in countries
            ]
            rows.sort(key=lambda x: (x["revenue"], x["leads_count"]), reverse=True)
            return rows[:10]

        async def _attribution_sources() -> list[dict[str, Any]]:
            lead_cols = await SchemaGuard.table_columns(db, "crm_leads")
            include_attr = "attribution_source" in lead_cols
            src_expr = attribution_source_expr(include_attribution_source=include_attr)
            lead_by_src: dict[str, int] = {}
            if leads:
                lead_rows = await db.execute(
                    select(src_expr, func.count())
                    .select_from(CrmLead)
                    .where(CrmLead.id.in_(lead_ids))
                    .group_by(src_expr)
                )
                for src, cnt in lead_rows.all():
                    key = normalize_attribution_key(str(src) if src else "other")
                    lead_by_src[key] = lead_by_src.get(key, 0) + int(cnt or 0)

            deals_by_src: dict[str, int] = {}
            rev_by_src: dict[str, Decimal] = {}
            won_deal_ids = [d.id for d in deals if d.status == "won"]
            if won_deal_ids:
                deal_rows = await db.execute(
                    select(src_expr, func.count(), func.coalesce(func.sum(CrmDeal.deal_amount), 0))
                    .select_from(CrmDeal)
                    .join(CrmLead, CrmDeal.lead_id == CrmLead.id)
                    .where(CrmDeal.id.in_(won_deal_ids))
                    .group_by(src_expr)
                )
                for src, cnt, rev in deal_rows.all():
                    key = normalize_attribution_key(str(src) if src else "other")
                    deals_by_src[key] = deals_by_src.get(key, 0) + int(cnt or 0)
                    rev_by_src[key] = rev_by_src.get(key, Decimal("0")) + Decimal(str(rev or 0))

            link_q = select(AttributionLink.channel, func.coalesce(func.sum(AttributionLink.clicks_count), 0), func.coalesce(func.sum(AttributionLink.leads_count), 0))
            if client_id:
                link_q = link_q.where(AttributionLink.client_id == client_id)
            link_q = link_q.group_by(AttributionLink.channel)
            clicks_by_src: dict[str, int] = {}
            link_leads_by_src: dict[str, int] = {}
            for ch, clicks, lcount in (await db.execute(link_q)).all():
                key = normalize_attribution_key(str(ch))
                clicks_by_src[key] = clicks_by_src.get(key, 0) + int(clicks or 0)
                link_leads_by_src[key] = link_leads_by_src.get(key, 0) + int(lcount or 0)

            all_src = set(lead_by_src) | set(deals_by_src) | set(clicks_by_src) | set(ATTRIBUTION_LABELS)
            rows: list[dict[str, Any]] = []
            for src in all_src:
                clicks = clicks_by_src.get(src, 0)
                lead_cnt = lead_by_src.get(src, 0) + link_leads_by_src.get(src, 0)
                deal_cnt = deals_by_src.get(src, 0)
                revenue = rev_by_src.get(src, Decimal("0"))
                conv = _rate(deal_cnt, clicks) if clicks else _rate(deal_cnt, lead_cnt)
                if lead_cnt or deal_cnt or clicks:
                    rows.append({
                        "source": src,
                        "clicks": clicks,
                        "leads": lead_cnt,
                        "deals": deal_cnt,
                        "revenue": revenue,
                        "conversion_rate": conv,
                    })
            rows.sort(key=lambda x: x["revenue"], reverse=True)
            return rows[:12]

        async def _partner_performance() -> list[dict[str, Any]]:
            perf: dict[UUID, dict[str, Any]] = {}
            partner_rows = list((await db.execute(select(Partner))).scalars().all())
            partner_map = {p.id: p for p in partner_rows}

            for lead in leads:
                if not lead.partner_id:
                    continue
                pid = lead.partner_id
                p = partner_map.get(pid)
                if not p:
                    continue
                bucket = perf.setdefault(pid, {
                    "partner_id": pid,
                    "partner_name": p.name,
                    "leads": 0,
                    "deals": 0,
                    "revenue": Decimal("0"),
                    "commission": Decimal("0"),
                })
                bucket["leads"] += 1

            for deal in deals:
                lead = deal.lead or next((l for l in leads if l.id == deal.lead_id), None)
                if not lead or not lead.partner_id:
                    continue
                pid = lead.partner_id
                if pid not in perf:
                    p = partner_map.get(pid)
                    if not p:
                        continue
                    perf[pid] = {
                        "partner_id": pid,
                        "partner_name": p.name,
                        "leads": 0,
                        "deals": 0,
                        "revenue": Decimal("0"),
                        "commission": Decimal("0"),
                    }
                perf[pid]["deals"] += 1
                if deal.status == "won":
                    perf[pid]["revenue"] += deal.deal_amount or Decimal("0")
                    perf[pid]["commission"] += deal.partner_commission_amount or Decimal("0")

            rows = list(perf.values())
            rows.sort(key=lambda x: x["revenue"], reverse=True)
            return rows[:10]

        async def _action_queue() -> dict[str, Any]:
            lead_ids = [l.id for l in leads]
            overdue: list[dict[str, Any]] = []
            for lead in leads:
                if (
                    lead.next_follow_up_at
                    and _parse_dt(lead.next_follow_up_at) < now
                    and lead.status not in ("won", "lost")
                ):
                    overdue.append({
                        "lead_id": lead.id,
                        "name": lead.name,
                        "due_at": lead.next_follow_up_at,
                    })
            overdue.sort(key=lambda x: x["due_at"] or now)

            pending_proposals: list[dict[str, Any]] = []
            if lead_ids:
                pr = await db.execute(
                    select(CrmProposal)
                    .where(CrmProposal.lead_id.in_(lead_ids), CrmProposal.status.in_(("draft", "sent")))
                    .order_by(CrmProposal.updated_at.desc())
                    .limit(15)
                )
                pending_proposals = [
                    {
                        "proposal_id": p.id,
                        "lead_id": p.lead_id,
                        "title": p.title,
                        "status": p.status,
                    }
                    for p in pr.scalars().all()
                ]

            unpaid: list[dict[str, Any]] = []
            if lead_ids:
                ir = await db.execute(
                    select(CrmDocument)
                    .where(
                        CrmDocument.lead_id.in_(lead_ids),
                        CrmDocument.document_type == "invoice",
                        CrmDocument.status == "sent",
                    )
                    .limit(15)
                )
                unpaid = [
                    {
                        "document_id": d.id,
                        "lead_id": d.lead_id,
                        "title": d.title,
                    }
                    for d in ir.scalars().all()
                ]

            sa_q = select(SalesAgentRecommendation).where(
                SalesAgentRecommendation.priority == "high",
                SalesAgentRecommendation.status.in_(("new", "accepted")),
            )
            if client_id:
                sa_q = sa_q.where(SalesAgentRecommendation.client_id == client_id)
            sa_q = sa_q.order_by(SalesAgentRecommendation.created_at.desc()).limit(10)
            agent_recs = [
                {
                    "id": r.id,
                    "title": r.title,
                    "priority": r.priority,
                    "recommendation_type": r.recommendation_type,
                    "lead_id": r.lead_id,
                    "deal_id": r.deal_id,
                }
                for r in (await db.execute(sa_q)).scalars().all()
            ]

            risky = await DashboardService._detect_deal_risks(db, now)
            if client_id:
                deal_ids_client = {d.id for d in deals}
                risky = [r for r in risky if r.get("deal_id") in deal_ids_client]

            return {
                "overdue_followups": overdue[:15],
                "pending_proposals": pending_proposals,
                "unpaid_invoices": unpaid,
                "high_priority_sales_agent_recommendations": agent_recs,
                "risky_deals": [
                    {
                        "deal_id": r["deal_id"],
                        "lead_id": r["lead_id"],
                        "deal_title": r["deal_title"],
                        "lead_name": r.get("lead_name"),
                        "risk_type": r["risk_type"],
                        "title": r["title"],
                        "severity": r.get("severity", "medium"),
                    }
                    for r in risky[:15]
                ],
            }

        _empty_overview = {
            "total_leads": 0, "new_leads": 0, "qualified_leads": 0,
            "active_deals": 0, "won_deals": 0, "lost_deals": 0,
            "pipeline_value": Decimal("0"), "closed_revenue": Decimal("0"),
            "commission_earned": Decimal("0"), "pending_commission": Decimal("0"),
            "partner_count": 0, "buyer_recommendations_count": 0,
            "landing_page_leads": 0, "attribution_clicks": 0,
        }

        overview = await SalesDepartmentDashboardService._safe_section(
            "overview", _overview(), default=_empty_overview, errors=errors, db=db,
        )
        funnel = await SalesDepartmentDashboardService._safe_section(
            "sales_funnel",
            _funnel(),
            default={
                "leads": 0, "contacted": 0, "qualified": 0, "proposal_sent": 0,
                "negotiation": 0, "won": 0, "lost": 0,
            },
            errors=errors,
            db=db,
        )
        top_products = await SalesDepartmentDashboardService._safe_section(
            "top_products", _top_products(), default=[], errors=errors, db=db,
        )
        top_countries = await SalesDepartmentDashboardService._safe_section(
            "top_countries", _top_countries(), default=[], errors=errors, db=db,
        )
        top_attribution = await SalesDepartmentDashboardService._safe_section(
            "top_attribution_sources", _attribution_sources(), default=[], errors=errors, db=db,
        )
        partner_perf = await SalesDepartmentDashboardService._safe_section(
            "partner_performance", _partner_performance(), default=[], errors=errors, db=db,
        )
        action_queue = await SalesDepartmentDashboardService._safe_section(
            "action_queue", _action_queue(), default={
                "overdue_followups": [],
                "pending_proposals": [],
                "unpaid_invoices": [],
                "high_priority_sales_agent_recommendations": [],
                "risky_deals": [],
            },
            errors=errors,
            db=db,
        )

        async def _lead_intel() -> dict[str, Any]:
            return await LeadIntelligenceService.metrics(db, client_id=client_id)

        lead_intelligence = await SalesDepartmentDashboardService._safe_section(
            "lead_intelligence",
            _lead_intel(),
            default={
                "hot_leads": 0,
                "qualified_leads": 0,
                "neglected_leads": 0,
                "leads_without_activity": 0,
                "top_hot_leads": [],
            },
            errors=errors,
            db=db,
        )

        async def _sales_assistant_widget() -> dict[str, Any]:
            summary = await SalesAssistantService.list_recommendations(
                db, status="open", client_id=client_id, limit=5,
            )
            sm = summary.get("summary") or {}
            top = [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "priority": r["priority"],
                    "recommendation_type": r["recommendation_type"],
                    "lead_id": r.get("lead_id"),
                    "deal_id": r.get("deal_id"),
                    "conversation_id": r.get("conversation_id"),
                }
                for r in (summary.get("items") or [])[:5]
            ]
            return {
                "open_count": sm.get("open_count", 0),
                "urgent_count": sm.get("urgent_count", 0),
                "top_recommendations": top,
            }

        sales_assistant = await SalesDepartmentDashboardService._safe_section(
            "sales_assistant",
            _sales_assistant_widget(),
            default={"open_count": 0, "urgent_count": 0, "top_recommendations": []},
            errors=errors,
            db=db,
        )

        async def _operator_tasks_widget() -> dict[str, Any]:
            listing = await OperatorTaskEngineService.list_tasks(
                db, client_id=client_id, limit=8,
            )
            sm = listing.get("summary") or {}
            top = [
                {
                    "id": t["id"],
                    "title": t["title"],
                    "priority": t["priority"],
                    "action_type": t.get("action_type"),
                    "due_at": t.get("due_at"),
                    "status": t.get("status"),
                }
                for t in (listing.get("items") or [])[:8]
            ]
            return {
                "open_count": sm.get("open_count", 0),
                "urgent_count": sm.get("urgent_count", 0),
                "overdue_count": sm.get("overdue_count", 0),
                "top_tasks": top,
            }

        operator_tasks = await SalesDepartmentDashboardService._safe_section(
            "operator_tasks",
            _operator_tasks_widget(),
            default={"open_count": 0, "urgent_count": 0, "overdue_count": 0, "top_tasks": []},
            errors=errors,
            db=db,
        )

        async def _sales_manager_widget() -> dict[str, Any]:
            overview = await SalesManagerService.overview(db, client_id=client_id)
            recs = await SalesManagerService.recommendations(db, client_id=client_id, limit=5)
            return {
                "leads_count": overview.get("leads_count", 0),
                "hot_leads": overview.get("hot_leads", 0),
                "opportunities_count": overview.get("opportunities_count", 0),
                "risks_count": overview.get("risks_count", 0),
                "overdue_tasks": overview.get("overdue_tasks", 0),
                "active_proposals": overview.get("active_proposals", 0),
                "top_recommendations": [
                    {
                        "category": r["category"],
                        "title": r["title"],
                        "priority": r["priority"],
                    }
                    for r in (recs.get("items") or [])[:5]
                ],
            }

        sales_manager = await SalesDepartmentDashboardService._safe_section(
            "sales_manager",
            _sales_manager_widget(),
            default={
                "leads_count": 0,
                "hot_leads": 0,
                "opportunities_count": 0,
                "risks_count": 0,
                "overdue_tasks": 0,
                "active_proposals": 0,
                "top_recommendations": [],
            },
            errors=errors,
            db=db,
        )

        logger.info(
            "%s overview: client=%s leads=%s active_deals=%s revenue=%s errors=%s",
            _MARKER,
            client_id,
            overview.get("total_leads", 0),
            overview.get("active_deals", 0),
            overview.get("closed_revenue", 0),
            len(errors),
        )

        return {
            "overview": overview,
            "sales_funnel": funnel,
            "top_products": top_products,
            "top_countries": top_countries,
            "top_attribution_sources": top_attribution,
            "partner_performance": partner_perf,
            "action_queue": action_queue,
            "sales_assistant": sales_assistant,
            "operator_tasks": operator_tasks,
            "sales_manager": sales_manager,
            "lead_intelligence": lead_intelligence,
            "errors": errors,
            "filters": filters,
        }

    @staticmethod
    async def ai_briefing(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        data = await SalesDepartmentDashboardService.dashboard(db, client_id=client_id)
        errors.extend(data.get("errors") or [])

        ctx_lines = [
            "SALES DEPARTMENT METRICS (read-only briefing):",
            f"Overview: {json.dumps({k: str(v) for k, v in (data.get('overview') or {}).items()}, default=str)}",
            f"Funnel: {data.get('sales_funnel')}",
            f"Top products: {(data.get('top_products') or [])[:5]}",
            f"Top countries: {(data.get('top_countries') or [])[:5]}",
            f"Attribution: {(data.get('top_attribution_sources') or [])[:5]}",
            f"Partners: {(data.get('partner_performance') or [])[:5]}",
            f"Action queue counts: overdue={len((data.get('action_queue') or {}).get('overdue_followups', []))}, "
            f"proposals={len((data.get('action_queue') or {}).get('pending_proposals', []))}, "
            f"invoices={len((data.get('action_queue') or {}).get('unpaid_invoices', []))}, "
            f"agent_recs={len((data.get('action_queue') or {}).get('high_priority_sales_agent_recommendations', []))}, "
            f"risky_deals={len((data.get('action_queue') or {}).get('risky_deals', []))}",
        ]
        context = "\n".join(ctx_lines)

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                result = SalesDepartmentDashboardService._heuristic_briefing(data)
            else:
                _validate_api_key()
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _AI_SYSTEM},
                        {"role": "user", "content": context[:14000]},
                    ],
                    temperature=0.35,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                result = {
                    "executive_summary": str(parsed.get("executive_summary") or ""),
                    "what_is_working": list(parsed.get("what_is_working") or [])[:5],
                    "risks": list(parsed.get("risks") or [])[:5],
                    "opportunities": list(parsed.get("opportunities") or [])[:5],
                    "recommended_actions": list(parsed.get("recommended_actions") or [])[:5],
                    "priority_score": float(parsed.get("priority_score") or 50),
                    "source": "ai",
                }
        except Exception as exc:
            logger.warning("%s ai briefing fallback: %s", _MARKER, exc)
            errors.append(f"ai_briefing: {exc}")
            result = SalesDepartmentDashboardService._heuristic_briefing(data)

        result["errors"] = errors
        logger.info(
            "%s ai briefing: source=%s priority=%s client=%s",
            _MARKER, result.get("source"), result.get("priority_score"), client_id,
        )
        return result

    @staticmethod
    def _heuristic_briefing(data: dict[str, Any]) -> dict[str, Any]:
        ov = data.get("overview") or {}
        aq = data.get("action_queue") or {}
        overdue = len(aq.get("overdue_followups") or [])
        risky = len(aq.get("risky_deals") or [])
        unpaid = len(aq.get("unpaid_invoices") or [])
        won = int(ov.get("won_deals") or 0)
        pipeline = ov.get("pipeline_value") or 0
        revenue = ov.get("closed_revenue") or 0
        buyers = int(ov.get("buyer_recommendations_count") or 0)

        working: list[str] = []
        risks: list[str] = []
        opportunities: list[str] = []
        actions: list[str] = []

        if won:
            working.append(f"{won} deals closed with {revenue} revenue recorded")
        if buyers:
            working.append(f"{buyers} buyer recommendations generated by AI Buyer Finder")
        if int(ov.get("landing_page_leads") or 0):
            working.append(f"{ov['landing_page_leads']} leads captured from landing pages")

        if overdue:
            risks.append(f"{overdue} overdue CRM follow-ups need attention")
            actions.append("Review overdue follow-ups in CRM manually")
        if unpaid:
            risks.append(f"{unpaid} unpaid invoices awaiting collection")
            actions.append("Open Deal Room and review sent invoices")
        if risky:
            risks.append(f"{risky} deals flagged with risk signals")

        top_countries = data.get("top_countries") or []
        if top_countries:
            best = top_countries[0]
            opportunities.append(
                f"Strong activity in {best.get('country')} — {best.get('leads_count')} leads",
            )

        top_products = data.get("top_products") or []
        if top_products:
            opportunities.append(f"Top product {top_products[0].get('product_name')} driving pipeline interest")

        if not actions:
            actions.append("Run Buyer Finder analysis on key catalog products")
        if not working:
            working.append("Sales pipeline is building — continue capturing leads across channels")

        priority = 70.0
        priority -= min(30.0, overdue * 5 + risky * 4 + unpaid * 3)
        priority += min(15.0, won * 2)
        priority = max(10.0, min(95.0, priority))

        summary = (
            f"AI sales department tracking {ov.get('total_leads', 0)} leads, "
            f"{ov.get('active_deals', 0)} active deals, and {pipeline} pipeline value. "
            f"Closed revenue {revenue} with {ov.get('pending_commission', 0)} commission pending."
        )

        return {
            "executive_summary": summary,
            "what_is_working": working[:5],
            "risks": risks[:5] or ["Monitor pipeline stagnation"],
            "opportunities": opportunities[:5] or ["Expand buyer finder analysis to top products"],
            "recommended_actions": actions[:5],
            "priority_score": round(priority, 1),
            "source": "fallback",
        }
