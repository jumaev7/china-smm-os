"""AI Export Growth Engine — executive export growth dashboard composing CRM, buyers, content, and markets."""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.business_matching import BusinessMatchingOpportunity
from app.models.buyer_crm import Buyer
from app.models.communication import CommunicationFollowUp, CommunicationMessage, CommunicationThread
from app.models.content_factory import ContentFactory, ContentFactoryItem
from app.models.sales_crm import SalesDeal, SalesLead, SalesProposal
from app.schemas.buyer_crm import DistributionItem
from app.schemas.export_growth import (
    ExportGrowthBuyerRecommendation,
    ExportGrowthContentRecommendation,
    ExportGrowthDailyAction,
    ExportGrowthDashboardResponse,
    ExportGrowthKpis,
    ExportGrowthMarketOpportunity,
    ExportGrowthOpportunity,
    ExportGrowthSalesRecommendation,
    ExportGrowthScore,
    ExportGrowthScoreFactor,
    ExportGrowthStrategicInsight,
    ExportGrowthSummaryResponse,
)
from app.services.communication_hub_scope import tenant_client_ids, thread_tenant_filter
from app.services.market_intelligence_service import MarketIntelligenceService

logger = logging.getLogger(__name__)
MARKER = "[Export Growth]"

ACTIVE_BUYER_STATUSES = frozenset({"interested", "negotiating", "active_buyer"})
OPEN_DEAL_STAGES = frozenset({"new_lead", "contacted", "negotiation", "proposal_sent"})
_STALE_BUYER_DAYS = 7
_STALE_DEAL_DAYS = 14
_PROPOSAL_STALL_DAYS = 7

_DEMO_COUNTRIES = ("Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan")
_DEMO_INDUSTRIES = ("Construction materials", "Food processing", "Textiles", "Machinery")
_DEMO_PRODUCTS = ("Ceramic tiles", "Packaging film", "Industrial pumps", "LED lighting")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _decimal(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _top_items(d: dict[str, int], limit: int = 8) -> list[DistributionItem]:
    sorted_items = sorted(d.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return [DistributionItem(label=k, count=v) for k, v in sorted_items]


class ExportGrowthService:
    @classmethod
    async def _load_deals(cls, db: AsyncSession, tenant_id: UUID | None) -> list[SalesDeal]:
        q = select(SalesDeal).options(
            selectinload(SalesDeal.customer),
            selectinload(SalesDeal.lead),
        )
        if tenant_id is not None:
            q = q.where(SalesDeal.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_buyers(cls, db: AsyncSession, tenant_id: UUID | None) -> list[Buyer]:
        q = select(Buyer)
        if tenant_id is not None:
            q = q.where(Buyer.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_proposals(cls, db: AsyncSession, tenant_id: UUID | None) -> list[SalesProposal]:
        q = select(SalesProposal)
        if tenant_id is not None:
            q = q.where(SalesProposal.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_leads(cls, db: AsyncSession, tenant_id: UUID | None) -> list[SalesLead]:
        q = select(SalesLead)
        if tenant_id is not None:
            q = q.where(SalesLead.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_matching_opportunities(
        cls, db: AsyncSession, tenant_id: UUID | None,
    ) -> list[BusinessMatchingOpportunity]:
        q = select(BusinessMatchingOpportunity).order_by(
            BusinessMatchingOpportunity.score.desc(),
        )
        if tenant_id is not None:
            q = q.where(BusinessMatchingOpportunity.tenant_id == tenant_id)
        return list((await db.execute(q.limit(20))).scalars().all())

    @classmethod
    async def _load_content_items(
        cls, db: AsyncSession, tenant_id: UUID | None,
    ) -> list[ContentFactoryItem]:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        if tenant_id is not None and not client_ids:
            return []
        q = (
            select(ContentFactoryItem)
            .join(ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id)
            .order_by(ContentFactoryItem.created_at.desc())
            .limit(50)
        )
        if tenant_id is not None and client_ids:
            q = q.where(ContentFactory.client_id.in_(client_ids))
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _follow_ups_due(cls, db: AsyncSession, tenant_id: UUID | None) -> int:
        fu_q = select(func.count()).select_from(CommunicationFollowUp).where(
            CommunicationFollowUp.status == "pending",
            CommunicationFollowUp.due_date <= _utcnow() + timedelta(days=1),
        )
        if tenant_id is not None:
            fu_q = fu_q.where(CommunicationFollowUp.tenant_id == tenant_id)
        return int((await db.execute(fu_q)).scalar() or 0)

    @classmethod
    async def _count_table(cls, db: AsyncSession, model, tenant_id: UUID | None, *filters) -> int:
        q = select(func.count()).select_from(model)
        if tenant_id is not None:
            q = q.where(model.tenant_id == tenant_id)
        if filters:
            q = q.where(*filters)
        return int((await db.execute(q)).scalar() or 0)

    @classmethod
    async def _sum_column(cls, db: AsyncSession, model, column, tenant_id: UUID | None, *filters) -> Decimal:
        q = select(func.coalesce(func.sum(column), 0)).select_from(model)
        if tenant_id is not None:
            q = q.where(model.tenant_id == tenant_id)
        if filters:
            q = q.where(*filters)
        return _decimal((await db.execute(q)).scalar())

    @classmethod
    async def _limited_rows(cls, db: AsyncSession, model, tenant_id: UUID | None, *filters, limit: int = 3):
        q = select(model)
        if tenant_id is not None:
            q = q.where(model.tenant_id == tenant_id)
        if filters:
            q = q.where(*filters)
        q = q.order_by(model.updated_at.asc()).limit(limit)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _count_content_items_light(cls, db: AsyncSession, tenant_id: UUID | None, *filters) -> int:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        if tenant_id is not None and not client_ids:
            return 0
        q = select(func.count()).select_from(ContentFactoryItem).join(
            ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id,
        )
        if tenant_id is not None and client_ids:
            q = q.where(ContentFactory.client_id.in_(client_ids))
        if filters:
            q = q.where(*filters)
        return int((await db.execute(q)).scalar() or 0)

    @classmethod
    async def _pending_content_light(cls, db: AsyncSession, tenant_id: UUID | None) -> list[ContentFactoryItem]:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        if tenant_id is not None and not client_ids:
            return []
        q = (
            select(ContentFactoryItem)
            .join(ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id)
            .where(ContentFactoryItem.review_status.in_(("generated", "approved")))
            .order_by(ContentFactoryItem.created_at.desc())
            .limit(3)
        )
        if tenant_id is not None and client_ids:
            q = q.where(ContentFactory.client_id.in_(client_ids))
        return list((await db.execute(q)).scalars().all())

    @classmethod
    def _summary_score(
        cls,
        active_buyers: int,
        total_buyers: int,
        open_deals: int,
        total_deals: int,
        accepted_proposals: int,
        sent_proposals: int,
        published_recent: int,
        content_total: int,
        comm_health: int,
    ) -> ExportGrowthScore:
        buyer_score = int((active_buyers / max(total_buyers, 1)) * 100)
        deal_score = int((open_deals / max(total_deals, 1)) * 100)
        proposal_score = int((accepted_proposals / max(sent_proposals, 1)) * 100)
        content_score = int(min(100, (published_recent / max(content_total, 1)) * 100 + min(published_recent, 5) * 8))
        weights = [
            ("Content activity", 20, content_score, f"{published_recent} published in the last 30 days"),
            ("Buyer activity", 25, buyer_score, f"{active_buyers} active of {total_buyers} buyers"),
            ("Deal activity", 25, deal_score, f"{open_deals} open of {total_deals} deals"),
            ("Proposal activity", 15, proposal_score, f"{accepted_proposals} accepted of {sent_proposals} sent proposals"),
            ("Communication activity", 15, comm_health, "Based on due follow-ups"),
        ]
        factors: list[ExportGrowthScoreFactor] = []
        total = 0.0
        for name, weight, score, summary in weights:
            contribution = score * weight / 100
            total += contribution
            factors.append(ExportGrowthScoreFactor(
                factor=name,
                weight_pct=weight,
                score=score,
                weighted_contribution=round(contribution, 1),
                summary=summary,
            ))
        final_score = int(min(100, max(0, round(total))))
        if final_score >= 70:
            label, summary = "Strong export momentum", "Buyer, deal, proposal, and content activity are balanced."
        elif final_score >= 45:
            label, summary = "Moderate growth potential", "Focus on stalled deals and buyer outreach to accelerate exports."
        else:
            label, summary = "Early stage - action needed", "Increase buyer engagement, content publishing, and deal follow-ups."
        return ExportGrowthScore(score=final_score, label=label, summary=summary, factors=factors)

    @classmethod
    async def summary(cls, db: AsyncSession, tenant_id: UUID | None) -> ExportGrowthSummaryResponse:
        now = _utcnow()
        stale_buyer_cutoff = now - timedelta(days=_STALE_BUYER_DAYS)
        stale_deal_cutoff = now - timedelta(days=_STALE_DEAL_DAYS)
        proposal_cutoff = now - timedelta(days=_PROPOSAL_STALL_DAYS)
        recent_cutoff = now - timedelta(days=30)

        total_buyers, active_buyers, total_deals, open_deals, matching_open = await asyncio.gather(
            cls._count_table(db, Buyer, tenant_id),
            cls._count_table(db, Buyer, tenant_id, Buyer.status.in_(tuple(ACTIVE_BUYER_STATUSES))),
            cls._count_table(db, SalesDeal, tenant_id),
            cls._count_table(db, SalesDeal, tenant_id, SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES))),
            cls._count_table(
                db,
                BusinessMatchingOpportunity,
                tenant_id,
                BusinessMatchingOpportunity.status.in_(("new", "contacted", "qualified", "negotiation")),
            ),
        )
        (
            high_value_deals,
            high_value_matches,
            expected_revenue,
            buyers_to_contact,
            deals_at_risk,
            sent_proposals,
            accepted_proposals,
            content_total,
            published_recent,
            follow_ups_due,
        ) = await asyncio.gather(
            cls._count_table(
                db,
                SalesDeal,
                tenant_id,
                SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
                SalesDeal.value >= Decimal("10000"),
            ),
            cls._count_table(
                db,
                BusinessMatchingOpportunity,
                tenant_id,
                BusinessMatchingOpportunity.status.in_(("new", "contacted", "qualified", "negotiation")),
                BusinessMatchingOpportunity.estimated_value >= Decimal("10000"),
            ),
            cls._sum_column(
                db,
                SalesDeal,
                SalesDeal.value * SalesDeal.probability / 100,
                tenant_id,
                SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
            ),
            cls._count_table(
                db,
                Buyer,
                tenant_id,
                Buyer.status.in_(("prospect", "contacted", "interested")),
                Buyer.updated_at <= stale_buyer_cutoff,
            ),
            cls._count_table(
                db,
                SalesDeal,
                tenant_id,
                SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
                SalesDeal.updated_at <= stale_deal_cutoff,
            ),
            cls._count_table(
                db,
                SalesProposal,
                tenant_id,
                SalesProposal.status.in_(("sent", "viewed", "accepted", "rejected")),
            ),
            cls._count_table(db, SalesProposal, tenant_id, SalesProposal.status == "accepted"),
            cls._count_content_items_light(db, tenant_id),
            cls._count_content_items_light(
                db,
                tenant_id,
                ContentFactoryItem.review_status == "published",
                ContentFactoryItem.created_at >= recent_cutoff,
            ),
            cls._follow_ups_due(db, tenant_id),
        )
        comm_health = 75 if follow_ups_due == 0 else max(35, 75 - min(follow_ups_due, 10) * 4)

        stale_buyers, stale_deals, stale_proposals, pending_content = await asyncio.gather(
            cls._limited_rows(
                db,
                Buyer,
                tenant_id,
                Buyer.status.in_(("prospect", "contacted", "interested")),
                Buyer.updated_at <= stale_buyer_cutoff,
                limit=3,
            ),
            cls._limited_rows(
                db,
                SalesDeal,
                tenant_id,
                SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
                SalesDeal.updated_at <= stale_deal_cutoff,
                limit=3,
            ),
            cls._limited_rows(
                db,
                SalesProposal,
                tenant_id,
                SalesProposal.status.in_(("sent", "viewed")),
                SalesProposal.updated_at <= proposal_cutoff,
                limit=3,
            ),
            cls._pending_content_light(db, tenant_id),
        )

        top_actions = cls._build_daily_actions(
            stale_buyers,
            stale_deals,
            stale_proposals,
            pending_content,
            follow_ups_due,
        )[:3]
        score = cls._summary_score(
            active_buyers,
            total_buyers,
            open_deals,
            total_deals,
            accepted_proposals,
            sent_proposals,
            published_recent,
            content_total,
            comm_health,
        )
        demo_mode = settings.DEMO_MODE or (
            tenant_id is not None
            and total_buyers == 0
            and total_deals == 0
        )
        if demo_mode and not top_actions:
            top_actions, _, _ = cls._inject_demo_data([], [], [])
            top_actions = top_actions[:3]

        return ExportGrowthSummaryResponse(
            export_growth_score=score,
            active_opportunities=open_deals + matching_open,
            high_value_opportunities=high_value_deals + high_value_matches,
            expected_revenue=expected_revenue,
            buyers_to_contact=buyers_to_contact,
            deals_at_risk=deals_at_risk,
            top_actions=top_actions,
            demo_mode=demo_mode,
            generated_at=now,
        )

    @classmethod
    async def _communication_health(
        cls, db: AsyncSession, tenant_id: UUID | None, follow_ups_due: int,
    ) -> int:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        thread_filt = await thread_tenant_filter(tenant_id, client_ids)
        q = select(CommunicationThread).options(
            selectinload(CommunicationThread.messages),
        ).limit(100)
        if thread_filt is not None:
            q = q.where(thread_filt)
        threads = list((await db.execute(q)).scalars().all())
        if not threads:
            return 75 if follow_ups_due == 0 else 55
        unanswered = 0
        for thread in threads:
            messages = thread.messages or []
            if not messages:
                continue
            last = messages[-1]
            if last.direction == "inbound" and last.status in (
                "unanswered", "sent", "delivered", "read",
            ):
                unanswered += 1
        ratio = unanswered / len(threads)
        return int(min(100, max(0, 100 - ratio * 80 - min(follow_ups_due, 10) * 3)))

    @classmethod
    def _buyer_growth_pct(cls, buyers: list[Buyer]) -> float:
        now = _utcnow()
        this_month = sum(
            1 for b in buyers
            if (_aware(b.created_at) or now).month == now.month
            and (_aware(b.created_at) or now).year == now.year
        )
        last_month_dt = (now.replace(day=1) - timedelta(days=1))
        last_month = sum(
            1 for b in buyers
            if (_aware(b.created_at) or now).month == last_month_dt.month
            and (_aware(b.created_at) or now).year == last_month_dt.year
        )
        if last_month == 0:
            return float(this_month * 100) if this_month else 0.0
        return round((this_month - last_month) / last_month * 100, 1)

    @classmethod
    def _proposal_acceptance_rate(cls, proposals: list[SalesProposal]) -> float:
        sent_or_closed = [p for p in proposals if p.status in (
            "sent", "viewed", "accepted", "rejected",
        )]
        if not sent_or_closed:
            return 0.0
        accepted = sum(1 for p in sent_or_closed if p.status == "accepted")
        return round(accepted / len(sent_or_closed) * 100, 1)

    @classmethod
    def _build_kpis(
        cls,
        deals: list[SalesDeal],
        buyers: list[Buyer],
        proposals: list[SalesProposal],
        opportunities: list[ExportGrowthOpportunity],
        comm_health: int,
        growth_score: ExportGrowthScore,
        follow_ups_due: int,
    ) -> ExportGrowthKpis:
        open_deals = [d for d in deals if d.stage in OPEN_DEAL_STAGES]
        active_buyers = [b for b in buyers if b.status in ACTIVE_BUYER_STATUSES]
        pipeline_value = sum((_decimal(d.value) for d in open_deals), Decimal("0"))
        expected_revenue = sum(
            (_decimal(d.value) * Decimal(d.probability) / Decimal(100) for d in open_deals),
            Decimal("0"),
        )
        opp_value = sum((_decimal(o.estimated_value) for o in opportunities), Decimal("0"))

        return ExportGrowthKpis(
            pipeline_value=pipeline_value,
            expected_revenue=expected_revenue,
            opportunity_value=opp_value,
            active_buyers=len(active_buyers),
            buyer_growth_pct=cls._buyer_growth_pct(buyers),
            proposal_acceptance_rate=cls._proposal_acceptance_rate(proposals),
            communication_health=comm_health,
            export_growth_score=growth_score.score,
        )

    @classmethod
    def _compute_export_growth_score(
        cls,
        buyers: list[Buyer],
        deals: list[SalesDeal],
        proposals: list[SalesProposal],
        content_items: list[ContentFactoryItem],
        comm_health: int,
    ) -> ExportGrowthScore:
        now = _utcnow()
        recent_cutoff = now - timedelta(days=30)

        published_recent = sum(
            1 for c in content_items
            if c.review_status == "published"
            and (_aware(c.updated_at) or now) >= recent_cutoff
        )
        content_total = max(len(content_items), 1)
        content_score = int(min(100, (published_recent / content_total) * 100 + min(published_recent, 5) * 8))

        active_buyers = sum(1 for b in buyers if b.status in ACTIVE_BUYER_STATUSES)
        buyer_total = max(len(buyers), 1)
        recent_buyers = sum(
            1 for b in buyers if (_aware(b.created_at) or now) >= recent_cutoff
        )
        buyer_score = int(min(100, (active_buyers / buyer_total) * 70 + min(recent_buyers, 5) * 6))

        open_deals = [d for d in deals if d.stage in OPEN_DEAL_STAGES]
        won = sum(1 for d in deals if d.stage == "closed_won")
        deal_total = max(len(deals), 1)
        deal_score = int(min(100, (len(open_deals) / deal_total) * 50 + (won / deal_total) * 50))

        sent = [p for p in proposals if p.status in ("sent", "viewed", "accepted", "rejected")]
        accepted = sum(1 for p in sent if p.status == "accepted")
        proposal_score = int(min(100, (accepted / max(len(sent), 1)) * 100 + min(len(sent), 5) * 5))

        weights = [
            ("Content activity", 20, content_score,
             f"{published_recent} content pieces published in last 30 days"),
            ("Buyer activity", 25, buyer_score,
             f"{active_buyers} active buyers, {recent_buyers} added this month"),
            ("Deal activity", 25, deal_score,
             f"{len(open_deals)} open deals, {won} won"),
            ("Proposal activity", 15, proposal_score,
             f"{accepted} accepted of {len(sent)} sent proposals"),
            ("Communication activity", 15, comm_health,
             "Based on response rate and follow-up completion"),
        ]

        factors: list[ExportGrowthScoreFactor] = []
        total = 0.0
        for name, weight, score, summary in weights:
            contribution = score * weight / 100
            total += contribution
            factors.append(ExportGrowthScoreFactor(
                factor=name,
                weight_pct=weight,
                score=score,
                weighted_contribution=round(contribution, 1),
                summary=summary,
            ))

        final_score = int(min(100, max(0, round(total))))
        if final_score >= 70:
            label, summary = "Strong export momentum", "Your export activities are well balanced across buyers, deals, and content."
        elif final_score >= 45:
            label, summary = "Moderate growth potential", "Focus on stalled deals and buyer outreach to accelerate exports."
        else:
            label, summary = "Early stage — action needed", "Increase buyer engagement, content publishing, and deal follow-ups."

        return ExportGrowthScore(score=final_score, label=label, summary=summary, factors=factors)

    @classmethod
    def _build_daily_actions(
        cls,
        buyers: list[Buyer],
        deals: list[SalesDeal],
        proposals: list[SalesProposal],
        content_items: list[ContentFactoryItem],
        follow_ups_due: int,
    ) -> list[ExportGrowthDailyAction]:
        now = _utcnow()
        actions: list[ExportGrowthDailyAction] = []

        for buyer in buyers:
            if buyer.status in ("prospect", "contacted", "interested"):
                updated = _aware(buyer.updated_at) or now
                if (now - updated).days >= _STALE_BUYER_DAYS:
                    actions.append(ExportGrowthDailyAction(
                        id=str(uuid4()),
                        priority="high" if buyer.status == "interested" else "medium",
                        title=f"Contact buyer: {buyer.company_name}",
                        expected_impact="Convert prospect to active export buyer",
                        reason=f"No activity for {(now - updated).days} days",
                        recommended_action="Send personalized outreach",
                        href=f"/buyers/{buyer.id}",
                        entity_type="buyer",
                        entity_id=buyer.id,
                    ))

        for deal in deals:
            if deal.stage not in OPEN_DEAL_STAGES:
                continue
            updated = _aware(deal.updated_at) or now
            if (now - updated).days >= _STALE_DEAL_DAYS:
                actions.append(ExportGrowthDailyAction(
                    id=str(uuid4()),
                    priority="urgent" if _decimal(deal.value) >= Decimal("20000") else "high",
                    title=f"Follow up deal: {deal.title}",
                    expected_impact=f"Potential {_decimal(deal.value):,.0f} {deal.currency}",
                    reason=f"Deal stalled at {deal.stage.replace('_', ' ')} for {(now - updated).days} days",
                    recommended_action="Schedule call or send proposal update",
                    href="/deals",
                    entity_type="deal",
                    entity_id=deal.id,
                ))

        for proposal in proposals:
            if proposal.status not in ("sent", "viewed"):
                continue
            updated = _aware(proposal.updated_at) or now
            if (now - updated).days >= _PROPOSAL_STALL_DAYS:
                actions.append(ExportGrowthDailyAction(
                    id=str(uuid4()),
                    priority="medium",
                    title=f"Follow up proposal: {proposal.title}",
                    expected_impact=f"Proposal value {_decimal(proposal.total):,.0f} {proposal.currency}",
                    reason=f"No response for {(now - updated).days} days",
                    recommended_action="Send follow-up message",
                    href=f"/proposals/{proposal.id}",
                    entity_type="proposal",
                    entity_id=proposal.id,
                ))

        pending_content = [
            c for c in content_items
            if c.review_status in ("generated", "approved") and c.review_status != "published"
        ]
        for item in pending_content[:3]:
            actions.append(ExportGrowthDailyAction(
                id=str(uuid4()),
                priority="medium",
                title=f"Publish content: {item.title or item.theme or 'Untitled'}",
                expected_impact="Increase market visibility and buyer engagement",
                reason=f"Content ready for publishing ({item.review_status})",
                recommended_action="Review and publish via Content Factory",
                href="/content-factory/review",
                entity_type="content",
                entity_id=item.id,
            ))

        if follow_ups_due > 0:
            actions.append(ExportGrowthDailyAction(
                id=str(uuid4()),
                priority="urgent",
                title=f"Complete {follow_ups_due} follow-up(s) due today",
                expected_impact="Maintain buyer trust and deal velocity",
                reason="Pending follow-ups due today or overdue",
                recommended_action="Review follow-up queue",
                href="/communications/followups",
            ))

        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        actions.sort(key=lambda a: priority_rank.get(a.priority, 4))
        return actions[:15]

    @classmethod
    def _build_opportunities(
        cls,
        deals: list[SalesDeal],
        buyers: list[Buyer],
        matching: list[BusinessMatchingOpportunity],
    ) -> list[ExportGrowthOpportunity]:
        opps: list[tuple[int, ExportGrowthOpportunity]] = []

        for deal in deals:
            if deal.stage not in OPEN_DEAL_STAGES:
                continue
            value = _decimal(deal.value)
            prob = deal.probability
            score = int(min(100, prob + min(30, int(value / Decimal("1000")))))
            country = (
                deal.customer.country if deal.customer and deal.customer.country
                else deal.lead.country if deal.lead and deal.lead.country
                else None
            )
            opps.append((score, ExportGrowthOpportunity(
                id=f"deal-{deal.id}",
                category="deal",
                title=deal.title,
                country=country,
                opportunity_score=score,
                estimated_value=value,
                currency=deal.currency,
                recommended_action="Advance deal stage or send updated proposal",
                confidence_score=min(95, prob + 10),
                href="/deals",
                entity_type="deal",
                entity_id=deal.id,
            )))

        for buyer in buyers:
            if buyer.status not in ACTIVE_BUYER_STATUSES and buyer.status != "prospect":
                continue
            score = 55 if buyer.status in ACTIVE_BUYER_STATUSES else 40
            if buyer.country in _DEMO_COUNTRIES[:2]:
                score += 10
            opps.append((score, ExportGrowthOpportunity(
                id=f"buyer-{buyer.id}",
                category="buyer",
                title=f"Export opportunity: {buyer.company_name}",
                country=buyer.country,
                industry=buyer.industry,
                opportunity_score=score,
                estimated_value=Decimal("15000"),
                recommended_action="Schedule discovery call and share product catalog",
                confidence_score=score,
                href=f"/buyers/{buyer.id}",
                entity_type="buyer",
                entity_id=buyer.id,
            )))

        for match in matching:
            score = int(match.score or 50)
            opps.append((score, ExportGrowthOpportunity(
                id=f"match-{match.id}",
                category="matching",
                title=match.title or "Business matching opportunity",
                opportunity_score=score,
                estimated_value=_decimal(match.estimated_value),
                recommended_action="Contact matched buyer and initiate negotiation",
                confidence_score=int(match.confidence_score or 50),
                href="/business-matching/opportunities",
                entity_type="matching",
                entity_id=match.id,
            )))

        opps.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in opps[:12]]

    @classmethod
    async def _build_market_opportunities(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        buyers: list[Buyer],
    ) -> list[ExportGrowthMarketOpportunity]:
        country_counter: Counter[str] = Counter()
        industry_counter: Counter[str] = Counter()
        product_counter: Counter[str] = Counter()

        for buyer in buyers:
            if buyer.country:
                country_counter[buyer.country] += 1
            if buyer.industry:
                industry_counter[buyer.industry] += 1
            for cat in (buyer.product_categories or []):
                if isinstance(cat, str) and cat.strip():
                    product_counter[cat.strip()] += 1

        top_markets = await MarketIntelligenceService.get_top_markets(db, tenant_id)
        for item in top_markets:
            if item.label not in country_counter:
                country_counter[item.label] = item.count // 4

        opps: list[ExportGrowthMarketOpportunity] = []

        for country, count in country_counter.most_common(5):
            demand = min(100, 40 + count * 8 + (15 if country in _DEMO_COUNTRIES else 0))
            opps.append(ExportGrowthMarketOpportunity(
                id=f"country-{country.lower().replace(' ', '-')}",
                type="country",
                name=country,
                growth_score=demand,
                demand_index=demand,
                buyer_count=count,
                estimated_value=Decimal(str(count * 12000)),
                recommended_action=f"Target {country} with localized content and buyer outreach",
                data_source="tenant_data" if count > 0 else "market_intelligence",
            ))

        for industry, count in industry_counter.most_common(4):
            score = min(100, 35 + count * 10)
            opps.append(ExportGrowthMarketOpportunity(
                id=f"industry-{industry.lower().replace(' ', '-')[:40]}",
                type="industry",
                name=industry,
                growth_score=score,
                demand_index=score,
                buyer_count=count,
                estimated_value=Decimal(str(count * 8000)),
                recommended_action=f"Create industry-specific proposals for {industry}",
                data_source="tenant_data",
            ))

        for product, count in product_counter.most_common(4):
            score = min(100, 45 + count * 12)
            opps.append(ExportGrowthMarketOpportunity(
                id=f"product-{product.lower().replace(' ', '-')[:40]}",
                type="product",
                name=product,
                growth_score=score,
                demand_index=score,
                buyer_count=count,
                estimated_value=Decimal(str(count * 6000)),
                recommended_action=f"Promote {product} in top export markets",
                data_source="tenant_data",
            ))

        if not opps:
            for i, country in enumerate(_DEMO_COUNTRIES):
                opps.append(ExportGrowthMarketOpportunity(
                    id=f"demo-country-{i}",
                    type="country",
                    name=country,
                    growth_score=72 - i * 5,
                    demand_index=68 - i * 4,
                    buyer_count=0,
                    estimated_value=Decimal(str(45000 - i * 5000)),
                    recommended_action=f"Explore {country} as a new export market",
                    data_source="demo",
                ))
            for i, industry in enumerate(_DEMO_INDUSTRIES[:3]):
                opps.append(ExportGrowthMarketOpportunity(
                    id=f"demo-industry-{i}",
                    type="industry",
                    name=industry,
                    growth_score=65 - i * 4,
                    demand_index=60 - i * 3,
                    buyer_count=0,
                    estimated_value=Decimal(str(30000)),
                    recommended_action=f"Research {industry} buyer segments",
                    data_source="demo",
                ))

        return opps[:12]

    @classmethod
    def _build_buyer_recommendations(cls, buyers: list[Buyer]) -> list[ExportGrowthBuyerRecommendation]:
        now = _utcnow()
        recs: list[ExportGrowthBuyerRecommendation] = []

        for buyer in buyers:
            updated = _aware(buyer.updated_at) or now
            days_stale = (now - updated).days

            if buyer.status in ("prospect", "contacted") and days_stale >= _STALE_BUYER_DAYS:
                recs.append(ExportGrowthBuyerRecommendation(
                    id=str(uuid4()),
                    type="follow_up",
                    company_name=buyer.company_name,
                    country=buyer.country,
                    match_score=50,
                    reason=f"No contact for {days_stale} days",
                    recommended_action="Send follow-up email or WhatsApp message",
                    href=f"/buyers/{buyer.id}",
                    buyer_id=buyer.id,
                ))
            elif buyer.status in ACTIVE_BUYER_STATUSES:
                score = 70 + (10 if buyer.country in _DEMO_COUNTRIES else 0)
                recs.append(ExportGrowthBuyerRecommendation(
                    id=str(uuid4()),
                    type="high_potential",
                    company_name=buyer.company_name,
                    country=buyer.country,
                    match_score=min(95, score),
                    reason="Active buyer with export engagement potential",
                    recommended_action="Propose new product line or volume discount",
                    href=f"/buyers/{buyer.id}",
                    buyer_id=buyer.id,
                ))
            elif buyer.status == "inactive":
                recs.append(ExportGrowthBuyerRecommendation(
                    id=str(uuid4()),
                    type="inactive",
                    company_name=buyer.company_name,
                    country=buyer.country,
                    match_score=30,
                    reason="Buyer marked inactive — re-engagement opportunity",
                    recommended_action="Send re-engagement campaign with new offers",
                    href=f"/buyers/{buyer.id}",
                    buyer_id=buyer.id,
                ))

        existing_countries = {b.country for b in buyers if b.country}
        for country in _DEMO_COUNTRIES:
            if country not in existing_countries:
                recs.append(ExportGrowthBuyerRecommendation(
                    id=str(uuid4()),
                    type="new_target",
                    company_name=f"Target buyers in {country}",
                    country=country,
                    match_score=60,
                    reason=f"No active buyers in {country} yet",
                    recommended_action="Use Buyer Discovery to find importers",
                    href="/buyer-discovery",
                ))

        return recs[:10]

    @classmethod
    def _build_content_recommendations(
        cls,
        content_items: list[ContentFactoryItem],
        buyers: list[Buyer],
    ) -> list[ExportGrowthContentRecommendation]:
        recs: list[ExportGrowthContentRecommendation] = []
        top_countries = Counter(b.country for b in buyers if b.country).most_common(3)
        lang_map = {"Uzbekistan": "uz", "Kazakhstan": "kk", "Kyrgyzstan": "ky", "Russia": "ru"}

        pending = [c for c in content_items if c.review_status in ("generated", "approved")]
        for item in pending[:3]:
            recs.append(ExportGrowthContentRecommendation(
                id=str(uuid4()),
                type="publish",
                title=item.title or item.theme or "Ready content",
                language="en",
                platform="LinkedIn",
                products=[item.theme] if item.theme else [],
                reason=f"Content in {item.review_status} status — ready to publish",
                recommended_action="Review and publish to reach export buyers",
                href="/content-factory/review",
            ))

        for country, _ in top_countries:
            lang = lang_map.get(country, "en")
            recs.append(ExportGrowthContentRecommendation(
                id=str(uuid4()),
                type="localize" if lang != "en" else "create",
                title=f"Market content for {country}",
                language=lang,
                platform="WeChat" if country in ("Uzbekistan", "Kazakhstan") else "LinkedIn",
                products=_DEMO_PRODUCTS[:2],
                reason=f"{country} is a top buyer market — localized content drives engagement",
                recommended_action=f"Generate {lang.upper()} product showcase content",
                href="/content-factory/generate",
            ))

        if not recs:
            recs.append(ExportGrowthContentRecommendation(
                id=str(uuid4()),
                type="create",
                title="Product showcase for Central Asia",
                language="en",
                platform="LinkedIn",
                products=list(_DEMO_PRODUCTS[:3]),
                reason="No recent content — start building export visibility",
                recommended_action="Create product highlight post via Content Factory",
                href="/content-factory/generate",
            ))

        return recs[:8]

    @classmethod
    def _build_sales_recommendations(cls, deals: list[SalesDeal]) -> list[ExportGrowthSalesRecommendation]:
        now = _utcnow()
        recs: list[ExportGrowthSalesRecommendation] = []

        for deal in deals:
            if deal.stage not in OPEN_DEAL_STAGES:
                continue
            value = _decimal(deal.value)
            updated = _aware(deal.updated_at) or now
            days_stale = (now - updated).days
            buyer_name = (
                deal.customer.name if deal.customer
                else deal.lead.name if deal.lead
                else None
            )

            if days_stale >= _STALE_DEAL_DAYS and value >= Decimal("10000"):
                recs.append(ExportGrowthSalesRecommendation(
                    id=str(uuid4()),
                    type="at_risk",
                    deal_title=deal.title,
                    buyer=buyer_name,
                    value=value,
                    currency=deal.currency,
                    stage=deal.stage,
                    probability=deal.probability,
                    reason=f"High-value deal stalled for {days_stale} days",
                    recommended_action="Executive intervention — schedule urgent call",
                    href="/deals",
                    deal_id=deal.id,
                ))
            elif deal.probability >= 70 and deal.stage in ("negotiation", "proposal_sent"):
                recs.append(ExportGrowthSalesRecommendation(
                    id=str(uuid4()),
                    type="fast_close",
                    deal_title=deal.title,
                    buyer=buyer_name,
                    value=value,
                    currency=deal.currency,
                    stage=deal.stage,
                    probability=deal.probability,
                    reason=f"{deal.probability}% probability — close within 2 weeks",
                    recommended_action="Send final terms and request signature",
                    href="/deals",
                    deal_id=deal.id,
                ))
            elif value >= Decimal("25000"):
                recs.append(ExportGrowthSalesRecommendation(
                    id=str(uuid4()),
                    type="high_value",
                    deal_title=deal.title,
                    buyer=buyer_name,
                    value=value,
                    currency=deal.currency,
                    stage=deal.stage,
                    probability=deal.probability,
                    reason="Top pipeline deal by value",
                    recommended_action="Assign senior sales owner and weekly check-ins",
                    href="/deals",
                    deal_id=deal.id,
                ))
            elif days_stale >= _STALE_DEAL_DAYS:
                recs.append(ExportGrowthSalesRecommendation(
                    id=str(uuid4()),
                    type="stalled",
                    deal_title=deal.title,
                    buyer=buyer_name,
                    value=value,
                    currency=deal.currency,
                    stage=deal.stage,
                    probability=deal.probability,
                    reason=f"No progress for {days_stale} days",
                    recommended_action="Identify blockers and update deal stage",
                    href="/deals",
                    deal_id=deal.id,
                ))

        type_rank = {"at_risk": 0, "fast_close": 1, "high_value": 2, "stalled": 3}
        recs.sort(key=lambda r: type_rank.get(r.type, 4))
        return recs[:10]

    @classmethod
    async def _build_strategic_insights(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        buyers: list[Buyer],
        deals: list[SalesDeal],
        content_items: list[ContentFactoryItem],
    ) -> list[ExportGrowthStrategicInsight]:
        insights: list[ExportGrowthStrategicInsight] = []

        country_counter = Counter(b.country for b in buyers if b.country)
        if country_counter:
            top_country, count = country_counter.most_common(1)[0]
            insights.append(ExportGrowthStrategicInsight(
                id=str(uuid4()),
                category="market",
                title="Most promising country",
                insight=f"{top_country} leads with {count} buyer(s) — highest export concentration",
                confidence=min(95, 50 + count * 8),
                recommended_action=f"Double down on {top_country} with targeted campaigns",
            ))

        industry_counter = Counter(b.industry for b in buyers if b.industry)
        if industry_counter:
            top_ind, count = industry_counter.most_common(1)[0]
            insights.append(ExportGrowthStrategicInsight(
                id=str(uuid4()),
                category="segment",
                title="Most promising buyer segment",
                insight=f"{top_ind} buyers represent your strongest segment ({count} contacts)",
                confidence=min(90, 45 + count * 10),
                recommended_action=f"Create {top_ind}-specific product bundles",
            ))

        type_counter = Counter(c.content_type for c in content_items if c.content_type)
        if type_counter:
            top_type, count = type_counter.most_common(1)[0]
            insights.append(ExportGrowthStrategicInsight(
                id=str(uuid4()),
                category="content",
                title="Most effective content type",
                insight=f"{top_type.replace('_', ' ').title()} content has highest production volume ({count} items)",
                confidence=70,
                recommended_action=f"Produce more {top_type.replace('_', ' ')} for export markets",
            ))

        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        thread_filt = await thread_tenant_filter(tenant_id, client_ids)
        q = select(CommunicationThread).limit(200)
        if thread_filt is not None:
            q = q.where(thread_filt)
        threads = list((await db.execute(q)).scalars().all())
        channel_counter = Counter(t.channel for t in threads if t.channel)
        if channel_counter:
            top_channel, count = channel_counter.most_common(1)[0]
            insights.append(ExportGrowthStrategicInsight(
                id=str(uuid4()),
                category="communication",
                title="Most active communication channel",
                insight=f"{top_channel.title()} handles {count} conversation(s) — primary buyer touchpoint",
                confidence=min(92, 55 + count * 5),
                recommended_action=f"Prioritize response SLAs on {top_channel}",
            ))

        open_pipeline = sum(_decimal(d.value) for d in deals if d.stage in OPEN_DEAL_STAGES)
        if open_pipeline > 0:
            insights.append(ExportGrowthStrategicInsight(
                id=str(uuid4()),
                category="revenue",
                title="Export revenue potential",
                insight=f"Open pipeline value: {open_pipeline:,.0f} USD across active deals",
                confidence=80,
                recommended_action="Focus on top 3 deals to maximize near-term exports",
            ))

        if not insights:
            top_markets = await MarketIntelligenceService.get_top_markets(db, tenant_id)
            if top_markets:
                insights.append(ExportGrowthStrategicInsight(
                    id=str(uuid4()),
                    category="market",
                    title="Most promising country",
                    insight=f"{top_markets[0].label} shows highest regional demand index",
                    confidence=65,
                    recommended_action="Start buyer discovery in this market",
                ))

        return insights[:6]

    @classmethod
    def _inject_demo_data(
        cls,
        daily_actions: list[ExportGrowthDailyAction],
        opportunities: list[ExportGrowthOpportunity],
        buyer_recs: list[ExportGrowthBuyerRecommendation],
    ) -> tuple[list[ExportGrowthDailyAction], list[ExportGrowthOpportunity], list[ExportGrowthBuyerRecommendation]]:
        if daily_actions and opportunities and buyer_recs:
            return daily_actions, opportunities, buyer_recs

        demo_actions = daily_actions or [
            ExportGrowthDailyAction(
                id="demo-action-1",
                priority="urgent",
                title="Contact Buyer: Tashkent Trading LLC",
                expected_impact="Potential $45,000 export order",
                reason="High match score buyer awaiting first contact",
                recommended_action="Send introduction email with product catalog",
                href="/buyers",
            ),
            ExportGrowthDailyAction(
                id="demo-action-2",
                priority="high",
                title="Follow up Proposal: Ceramic Tiles Q2",
                expected_impact="$28,000 proposal value",
                reason="Proposal sent 10 days ago without response",
                recommended_action="Send WhatsApp follow-up",
                href="/proposals",
            ),
            ExportGrowthDailyAction(
                id="demo-action-3",
                priority="medium",
                title="Publish Product D: LED Industrial Lighting",
                expected_impact="Increase visibility in Kazakhstan market",
                reason="Approved content ready for publishing",
                recommended_action="Publish via Content Factory",
                href="/content-factory/review",
            ),
        ]

        demo_opps = opportunities or [
            ExportGrowthOpportunity(
                id="demo-opp-1",
                category="market",
                title="Uzbekistan construction materials demand",
                country="Uzbekistan",
                industry="Construction materials",
                opportunity_score=82,
                estimated_value=Decimal("65000"),
                recommended_action="Target importers via Buyer Discovery",
                confidence_score=78,
                href="/buyer-discovery",
            ),
            ExportGrowthOpportunity(
                id="demo-opp-2",
                category="buyer",
                title="Kazakhstan food processing distributor",
                country="Kazakhstan",
                industry="Food processing",
                opportunity_score=74,
                estimated_value=Decimal("42000"),
                recommended_action="Schedule video call and send samples",
                confidence_score=72,
                href="/buyers",
            ),
        ]

        demo_buyers = buyer_recs or [
            ExportGrowthBuyerRecommendation(
                id="demo-buyer-1",
                type="high_potential",
                company_name="Almaty Import Group",
                country="Kazakhstan",
                match_score=85,
                reason="Strong industry fit for packaging products",
                recommended_action="Send tailored proposal",
                href="/buyer-discovery",
            ),
            ExportGrowthBuyerRecommendation(
                id="demo-buyer-2",
                type="follow_up",
                company_name="Samarkand Build Co.",
                country="Uzbekistan",
                match_score=70,
                reason="Interested buyer — no contact in 8 days",
                recommended_action="Follow up via WhatsApp",
                href="/buyers",
            ),
        ]

        return demo_actions, demo_opps, demo_buyers

    @classmethod
    async def dashboard(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
    ) -> ExportGrowthDashboardResponse:
        deals = await cls._load_deals(db, tenant_id)
        buyers = await cls._load_buyers(db, tenant_id)
        proposals = await cls._load_proposals(db, tenant_id)
        leads = await cls._load_leads(db, tenant_id)
        matching = await cls._load_matching_opportunities(db, tenant_id)
        content_items = await cls._load_content_items(db, tenant_id)
        follow_ups_due = await cls._follow_ups_due(db, tenant_id)
        comm_health = await cls._communication_health(db, tenant_id, follow_ups_due)

        growth_score = cls._compute_export_growth_score(
            buyers, deals, proposals, content_items, comm_health,
        )

        opportunities = cls._build_opportunities(deals, buyers, matching)
        market_opportunities = await cls._build_market_opportunities(db, tenant_id, buyers)
        daily_actions = cls._build_daily_actions(
            buyers, deals, proposals, content_items, follow_ups_due,
        )
        buyer_recs = cls._build_buyer_recommendations(buyers)
        content_recs = cls._build_content_recommendations(content_items, buyers)
        sales_recs = cls._build_sales_recommendations(deals)
        strategic_insights = await cls._build_strategic_insights(
            db, tenant_id, buyers, deals, content_items,
        )

        demo_mode = settings.DEMO_MODE or (
            tenant_id is not None
            and len(buyers) == 0
            and len(deals) == 0
            and len(leads) == 0
        )
        if demo_mode:
            daily_actions, opportunities, buyer_recs = cls._inject_demo_data(
                daily_actions, opportunities, buyer_recs,
            )

        kpis = cls._build_kpis(
            deals, buyers, proposals, opportunities, comm_health, growth_score, follow_ups_due,
        )

        country_counter = Counter(b.country for b in buyers if b.country)
        growing_markets = _top_items(dict(country_counter))
        if not growing_markets:
            top_markets = await MarketIntelligenceService.get_top_markets(db, tenant_id)
            growing_markets = top_markets[:5]

        logger.info(
            "%s dashboard tenant=%s buyers=%s deals=%s score=%s demo=%s",
            MARKER, tenant_id, len(buyers), len(deals), growth_score.score, demo_mode,
        )

        return ExportGrowthDashboardResponse(
            kpis=kpis,
            export_growth_score=growth_score,
            daily_actions=daily_actions,
            opportunities=opportunities,
            market_opportunities=market_opportunities,
            buyer_recommendations=buyer_recs,
            content_recommendations=content_recs,
            sales_recommendations=sales_recs,
            strategic_insights=strategic_insights,
            growing_markets=growing_markets,
            demo_mode=demo_mode,
            generated_at=_utcnow(),
        )

export_growth_service = ExportGrowthService()
