"""Factory Growth Center — executive dashboard aggregating tenant sales, buyers, and comms."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.buyer_crm import Buyer
from app.models.communication import CommunicationFollowUp, CommunicationMessage, CommunicationThread
from app.models.sales_crm import (
    SalesActivity,
    SalesDeal,
    SalesLead,
    SalesProposal,
)
from app.schemas.buyer_crm import DistributionItem
from app.schemas.growth_center import (
    GrowthCenterDashboardResponse,
    GrowthCenterHealthIndicator,
    GrowthCenterHealthScores,
    GrowthCenterMarketInsights,
    GrowthCenterOpportunity,
    GrowthCenterOverviewKpis,
    GrowthCenterRecommendation,
    GrowthCenterSummaryResponse,
    GrowthCenterTimelineItem,
    GrowthCenterTrendPoint,
    HealthStatus,
)
from app.services.communication_hub_scope import tenant_client_ids, thread_tenant_filter
from app.services.growth_center_export_service import growth_center_export_service

logger = logging.getLogger(__name__)
MARKER = "[Growth Center]"

ACTIVE_LEAD_STATUSES = frozenset({"new", "contacted", "qualified"})
ACTIVE_BUYER_STATUSES = frozenset({"interested", "negotiating", "active_buyer"})
OPEN_DEAL_STAGES = frozenset({"new_lead", "contacted", "negotiation", "proposal_sent"})
_STALE_LEAD_DAYS = 7
_STALE_DEAL_DAYS = 14
_PROPOSAL_STALL_DAYS = 7


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


def _health_status(score: int) -> HealthStatus:
    if score >= 70:
        return "healthy"
    if score >= 45:
        return "warning"
    return "critical"


def _top_items(d: dict[str, int], limit: int = 8) -> list[DistributionItem]:
    sorted_items = sorted(d.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return [DistributionItem(label=k, count=v) for k, v in sorted_items]


def _month_key(dt: datetime) -> str:
    aware_dt = _aware(dt) or _utcnow()
    return aware_dt.strftime("%Y-%m")


class GrowthCenterService:
    @classmethod
    async def _load_leads(cls, db: AsyncSession, tenant_id: UUID | None) -> list[SalesLead]:
        q = select(SalesLead)
        if tenant_id is not None:
            q = q.where(SalesLead.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

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
    async def _follow_ups_due(cls, db: AsyncSession, tenant_id: UUID | None) -> int:
        if tenant_id is None:
            fu_q = select(func.count()).select_from(CommunicationFollowUp).where(
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date <= _utcnow() + timedelta(days=1),
            )
        else:
            fu_q = select(func.count()).select_from(CommunicationFollowUp).where(
                CommunicationFollowUp.tenant_id == tenant_id,
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date <= _utcnow() + timedelta(days=1),
            )
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
    async def summary(cls, db: AsyncSession, tenant_id: UUID | None) -> GrowthCenterSummaryResponse:
        now = _utcnow()
        stale_lead_cutoff = now - timedelta(days=_STALE_LEAD_DAYS)
        stale_deal_cutoff = now - timedelta(days=_STALE_DEAL_DAYS)
        proposal_cutoff = now - timedelta(days=_PROPOSAL_STALL_DAYS)

        total_leads = await cls._count_table(db, SalesLead, tenant_id)
        active_leads = await cls._count_table(db, SalesLead, tenant_id, SalesLead.status.in_(tuple(ACTIVE_LEAD_STATUSES)))
        total_buyers = await cls._count_table(db, Buyer, tenant_id)
        active_buyers = await cls._count_table(db, Buyer, tenant_id, Buyer.status.in_(tuple(ACTIVE_BUYER_STATUSES)))
        total_deals = await cls._count_table(db, SalesDeal, tenant_id)
        open_deals = await cls._count_table(db, SalesDeal, tenant_id, SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)))
        pipeline_value = await cls._sum_column(
            db, SalesDeal, SalesDeal.value, tenant_id, SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
        )
        proposal_value = await cls._sum_column(db, SalesProposal, SalesProposal.total, tenant_id)
        followups_due = await cls._follow_ups_due(db, tenant_id)

        stale_leads = await cls._limited_rows(
            db,
            SalesLead,
            tenant_id,
            SalesLead.status.in_(tuple(ACTIVE_LEAD_STATUSES)),
            SalesLead.updated_at <= stale_lead_cutoff,
            limit=3,
        )
        stale_deals = await cls._limited_rows(
            db,
            SalesDeal,
            tenant_id,
            SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
            SalesDeal.updated_at <= stale_deal_cutoff,
            limit=3,
        )
        stale_buyers = await cls._limited_rows(
            db,
            Buyer,
            tenant_id,
            Buyer.status.in_(("prospect", "contacted")),
            Buyer.updated_at <= stale_lead_cutoff,
            limit=3,
        )
        stale_proposals = await cls._limited_rows(
            db,
            SalesProposal,
            tenant_id,
            SalesProposal.status.in_(("sent", "viewed")),
            SalesProposal.updated_at <= proposal_cutoff,
            limit=3,
        )

        recommendations = cls._build_recommendations(
            stale_leads,
            stale_deals,
            stale_buyers,
            stale_proposals,
            [],
            followups_due,
        )[:3]

        lead_score = int((active_leads / max(total_leads, 1)) * 100)
        buyer_score = int((active_buyers / max(total_buyers, 1)) * 100)
        deal_score = int((open_deals / max(total_deals, 1)) * 100)
        followup_penalty = min(30, followups_due * 5)
        growth_score = max(0, min(100, int((lead_score + buyer_score + deal_score) / 3) - followup_penalty))

        return GrowthCenterSummaryResponse(
            total_leads=total_leads,
            total_buyers=total_buyers,
            active_buyers=active_buyers,
            total_deals=total_deals,
            pipeline_value=pipeline_value,
            proposal_value=proposal_value,
            followups_due=followups_due,
            growth_score=growth_score,
            top_recommendations=recommendations,
            generated_at=now,
        )

    @classmethod
    def _build_kpis(
        cls,
        leads: list[SalesLead],
        deals: list[SalesDeal],
        buyers: list[Buyer],
        proposals: list[SalesProposal],
        follow_ups_due: int,
    ) -> GrowthCenterOverviewKpis:
        open_deals = [d for d in deals if d.stage in OPEN_DEAL_STAGES]
        won_deals = [d for d in deals if d.stage == "won"]
        lost_deals = [d for d in deals if d.stage == "lost"]
        active_leads = [l for l in leads if l.status in ACTIVE_LEAD_STATUSES]
        active_buyers = [b for b in buyers if b.status in ACTIVE_BUYER_STATUSES]

        pipeline_value = sum((_decimal(d.value) for d in open_deals), Decimal("0"))
        expected_revenue = sum(
            (_decimal(d.value) * Decimal(d.probability) / Decimal(100) for d in open_deals),
            Decimal("0"),
        )
        total_proposal_value = sum((_decimal(p.total) for p in proposals), Decimal("0"))

        return GrowthCenterOverviewKpis(
            total_leads=len(leads),
            total_buyers=len(buyers),
            active_buyers=len(active_buyers),
            active_leads=len(active_leads),
            total_deals=len(deals),
            deals_won=len(won_deals),
            deals_lost=len(lost_deals),
            total_proposal_value=total_proposal_value,
            pipeline_value=pipeline_value,
            expected_revenue=expected_revenue,
            follow_ups_due=follow_ups_due,
        )

    @classmethod
    def _build_market_insights(
        cls,
        leads: list[SalesLead],
        buyers: list[Buyer],
        proposals: list[SalesProposal],
    ) -> GrowthCenterMarketInsights:
        by_country: dict[str, int] = {}
        by_industry: dict[str, int] = {}
        by_source: dict[str, int] = {}

        for buyer in buyers:
            if buyer.country:
                by_country[buyer.country] = by_country.get(buyer.country, 0) + 1
            if buyer.industry:
                by_industry[buyer.industry] = by_industry.get(buyer.industry, 0) + 1

        for lead in leads:
            by_source[lead.source] = by_source.get(lead.source, 0) + 1

        sent_or_closed = [p for p in proposals if p.status in ("sent", "viewed", "accepted", "rejected")]
        accepted = sum(1 for p in sent_or_closed if p.status == "accepted")
        acceptance_rate = (accepted / len(sent_or_closed) * 100) if sent_or_closed else 0.0

        now = _utcnow()
        month_counts: dict[str, int] = {}
        for i in range(5, -1, -1):
            month_dt = (now.replace(day=1) - timedelta(days=i * 28)).replace(day=1)
            month_counts[_month_key(month_dt)] = 0
        for buyer in buyers:
            key = _month_key(buyer.created_at)
            if key in month_counts:
                month_counts[key] += 1

        trend = [
            GrowthCenterTrendPoint(period=k, count=v)
            for k, v in sorted(month_counts.items())
        ]

        return GrowthCenterMarketInsights(
            buyers_by_country=_top_items(by_country),
            buyers_by_industry=_top_items(by_industry),
            leads_by_source=_top_items(by_source),
            proposal_acceptance_rate=round(acceptance_rate, 1),
            buyer_growth_trend=trend,
        )

    @classmethod
    def _build_health_scores(
        cls,
        leads: list[SalesLead],
        deals: list[SalesDeal],
        buyers: list[Buyer],
        follow_ups_due: int,
        unanswered_count: int,
        total_threads: int,
    ) -> GrowthCenterHealthScores:
        total_leads = len(leads) or 1
        active_leads = sum(1 for l in leads if l.status in ACTIVE_LEAD_STATUSES)
        lost_leads = sum(1 for l in leads if l.status == "lost")
        lead_score = int(min(100, max(0, (active_leads / total_leads) * 100 - (lost_leads / total_leads) * 30)))

        total_buyers = len(buyers) or 1
        active_buyers = sum(1 for b in buyers if b.status in ACTIVE_BUYER_STATUSES)
        inactive = sum(1 for b in buyers if b.status == "inactive")
        buyer_score = int(min(100, max(0, (active_buyers / total_buyers) * 100 - (inactive / total_buyers) * 25)))

        total_deals = len(deals) or 1
        won = sum(1 for d in deals if d.stage == "won")
        lost = sum(1 for d in deals if d.stage == "lost")
        open_deals = sum(1 for d in deals if d.stage in OPEN_DEAL_STAGES)
        deal_score = int(min(100, max(0, (won / total_deals) * 60 + (open_deals / total_deals) * 40 - (lost / total_deals) * 20)))

        if total_threads == 0:
            comm_score = 75 if follow_ups_due == 0 else 55
        else:
            unanswered_ratio = unanswered_count / total_threads
            comm_score = int(min(100, max(0, 100 - unanswered_ratio * 80 - min(follow_ups_due, 10) * 3)))

        return GrowthCenterHealthScores(
            lead_health=GrowthCenterHealthIndicator(
                score=lead_score,
                status=_health_status(lead_score),
                label="Lead Health",
                summary=f"{active_leads} active of {len(leads)} leads",
            ),
            buyer_health=GrowthCenterHealthIndicator(
                score=buyer_score,
                status=_health_status(buyer_score),
                label="Buyer Health",
                summary=f"{active_buyers} active of {len(buyers)} buyers",
            ),
            deal_health=GrowthCenterHealthIndicator(
                score=deal_score,
                status=_health_status(deal_score),
                label="Deal Health",
                summary=f"{won} won, {open_deals} in pipeline",
            ),
            communication_health=GrowthCenterHealthIndicator(
                score=comm_score,
                status=_health_status(comm_score),
                label="Communication Health",
                summary=f"{unanswered_count} unanswered, {follow_ups_due} follow-ups due",
            ),
        )

    @classmethod
    def _build_opportunities(cls, deals: list[SalesDeal]) -> list[GrowthCenterOpportunity]:
        open_deals = [d for d in deals if d.stage in OPEN_DEAL_STAGES]
        scored: list[tuple[Decimal, GrowthCenterOpportunity]] = []
        for deal in open_deals:
            value = _decimal(deal.value)
            prob = Decimal(deal.probability) / Decimal(100)
            score = value * prob
            buyer_name = (
                deal.customer.name if deal.customer
                else deal.lead.name if deal.lead
                else deal.title
            )
            country = (
                deal.customer.country if deal.customer and deal.customer.country
                else deal.lead.country if deal.lead and deal.lead.country
                else None
            )
            scored.append((
                score,
                GrowthCenterOpportunity(
                    id=deal.id,
                    buyer=buyer_name,
                    country=country,
                    potential_value=value,
                    currency=deal.currency,
                    deal_stage=deal.stage,
                    probability=deal.probability,
                    score=score,
                ),
            ))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:10]]

    @classmethod
    def _build_recommendations(
        cls,
        leads: list[SalesLead],
        deals: list[SalesDeal],
        buyers: list[Buyer],
        proposals: list[SalesProposal],
        unanswered_threads: list[CommunicationThread],
        follow_ups_due: int,
    ) -> list[GrowthCenterRecommendation]:
        now = _utcnow()
        recs: list[GrowthCenterRecommendation] = []

        for lead in leads:
            if lead.status not in ACTIVE_LEAD_STATUSES:
                continue
            updated = _aware(lead.updated_at) or now
            if (now - updated).days >= _STALE_LEAD_DAYS:
                recs.append(GrowthCenterRecommendation(
                    id=str(uuid4()),
                    priority="high" if lead.priority == "high" else "medium",
                    title=f"Follow up lead: {lead.name}",
                    expected_impact="Recover stalled pipeline momentum",
                    reason=f"No activity for {(now - updated).days} days",
                    recommended_action="Contact lead and update status",
                    href=f"/leads",
                    entity_type="lead",
                    entity_id=lead.id,
                ))

        for deal in deals:
            if deal.stage not in OPEN_DEAL_STAGES:
                continue
            updated = _aware(deal.updated_at) or now
            if (now - updated).days >= _STALE_DEAL_DAYS:
                action = "Move to Negotiation" if deal.stage in ("contacted", "new_lead") else "Advance deal stage"
                recs.append(GrowthCenterRecommendation(
                    id=str(uuid4()),
                    priority="high" if _decimal(deal.value) >= Decimal("10000") else "medium",
                    title=f"{action}: {deal.title}",
                    expected_impact=f"Potential {_decimal(deal.value):,.0f} {deal.currency}",
                    reason=f"Deal unchanged for {(now - updated).days} days at {deal.stage.replace('_', ' ')}",
                    recommended_action=action,
                    href=f"/deals",
                    entity_type="deal",
                    entity_id=deal.id,
                ))

        for proposal in proposals:
            if proposal.status not in ("sent", "viewed"):
                continue
            updated = _aware(proposal.updated_at) or now
            if (now - updated).days >= _PROPOSAL_STALL_DAYS:
                recs.append(GrowthCenterRecommendation(
                    id=str(uuid4()),
                    priority="medium",
                    title=f"Follow up proposal: {proposal.title}",
                    expected_impact=f"Proposal value {_decimal(proposal.total):,.0f} {proposal.currency}",
                    reason=f"Sent/viewed { (now - updated).days } days ago without response",
                    recommended_action="Send follow-up on proposal",
                    href=f"/proposals/{proposal.id}",
                    entity_type="proposal",
                    entity_id=proposal.id,
                ))

        for buyer in buyers:
            if buyer.status in ("prospect", "contacted"):
                updated = _aware(buyer.updated_at) or now
                if (now - updated).days >= _STALE_LEAD_DAYS:
                    recs.append(GrowthCenterRecommendation(
                        id=str(uuid4()),
                        priority="medium",
                        title=f"Re-engage buyer: {buyer.company_name}",
                        expected_impact="Convert prospect to active buyer",
                        reason=f"Buyer status {buyer.status.replace('_', ' ')} with no recent activity",
                        recommended_action="Schedule outreach or meeting",
                        href=f"/buyers/{buyer.id}",
                        entity_type="buyer",
                        entity_id=buyer.id,
                    ))

        for thread in unanswered_threads[:3]:
            recs.append(GrowthCenterRecommendation(
                id=str(uuid4()),
                priority="urgent",
                title=f"Reply to: {thread.title}",
                expected_impact="Prevent buyer disengagement",
                reason="Inbound message awaiting response",
                recommended_action="Send reply in Communication Hub",
                href=f"/communications/threads/{thread.id}",
                entity_type="thread",
                entity_id=thread.id,
            ))

        if follow_ups_due > 0:
            recs.append(GrowthCenterRecommendation(
                id=str(uuid4()),
                priority="high",
                title=f"Complete {follow_ups_due} follow-up(s) due",
                expected_impact="Maintain buyer trust and deal velocity",
                reason="Pending follow-ups due today or overdue",
                recommended_action="Review follow-up queue",
                href="/communications/followups",
            ))

        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        recs.sort(key=lambda r: priority_rank.get(r.priority, 4))
        return recs[:12]

    @classmethod
    async def _build_timeline(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        leads: list[SalesLead],
        buyers: list[Buyer],
        proposals: list[SalesProposal],
        deals: list[SalesDeal],
    ) -> list[GrowthCenterTimelineItem]:
        items: list[GrowthCenterTimelineItem] = []

        for lead in sorted(leads, key=lambda l: l.created_at, reverse=True)[:5]:
            items.append(GrowthCenterTimelineItem(
                id=f"lead-{lead.id}",
                type="lead",
                title=f"New lead: {lead.name}",
                subtitle=lead.company or lead.source,
                occurred_at=lead.created_at,
                href="/leads",
            ))

        for buyer in sorted(buyers, key=lambda b: b.created_at, reverse=True)[:5]:
            items.append(GrowthCenterTimelineItem(
                id=f"buyer-{buyer.id}",
                type="buyer",
                title=f"Buyer added: {buyer.company_name}",
                subtitle=buyer.country,
                occurred_at=buyer.created_at,
                href=f"/buyers/{buyer.id}",
            ))

        for proposal in sorted(proposals, key=lambda p: p.created_at, reverse=True)[:5]:
            items.append(GrowthCenterTimelineItem(
                id=f"proposal-{proposal.id}",
                type="proposal",
                title=f"Proposal: {proposal.title}",
                subtitle=f"{proposal.status} · {_decimal(proposal.total):,.0f} {proposal.currency}",
                occurred_at=proposal.created_at,
                href=f"/proposals/{proposal.id}",
            ))

        for deal in sorted(deals, key=lambda d: d.updated_at, reverse=True)[:5]:
            items.append(GrowthCenterTimelineItem(
                id=f"deal-{deal.id}",
                type="deal_change",
                title=f"Deal updated: {deal.title}",
                subtitle=f"Stage: {deal.stage.replace('_', ' ')}",
                occurred_at=deal.updated_at,
                href="/deals",
            ))

        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        thread_filt = await thread_tenant_filter(tenant_id, client_ids)
        msg_q = (
            select(CommunicationMessage, CommunicationThread)
            .join(CommunicationThread)
            .order_by(CommunicationMessage.created_at.desc())
            .limit(8)
        )
        if thread_filt is not None:
            msg_q = msg_q.where(thread_filt)
        rows = (await db.execute(msg_q)).all()
        for msg, thread in rows:
            items.append(GrowthCenterTimelineItem(
                id=f"msg-{msg.id}",
                type="communication",
                title=f"{msg.direction.title()} — {thread.title}",
                subtitle=thread.channel,
                occurred_at=msg.created_at,
                href=f"/communications/threads/{thread.id}",
            ))

        activity_q = select(SalesActivity).order_by(SalesActivity.activity_date.desc()).limit(5)
        if tenant_id is not None:
            activity_q = activity_q.where(SalesActivity.tenant_id == tenant_id)
        activities = (await db.execute(activity_q)).scalars().all()
        for act in activities:
            items.append(GrowthCenterTimelineItem(
                id=f"activity-{act.id}",
                type="activity",
                title=act.title,
                subtitle=act.type,
                occurred_at=act.activity_date,
                href="/sales",
            ))

        items.sort(key=lambda i: i.occurred_at, reverse=True)
        return items[:20]

    @classmethod
    async def _communication_stats(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
    ) -> tuple[int, list[CommunicationThread]]:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        thread_filt = await thread_tenant_filter(tenant_id, client_ids)
        q = (
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .order_by(CommunicationThread.last_message_at.desc().nullslast())
            .limit(100)
        )
        if thread_filt is not None:
            q = q.where(thread_filt)
        threads = list((await db.execute(q)).scalars().all())

        unanswered: list[CommunicationThread] = []
        for thread in threads:
            messages = thread.messages or []
            if not messages:
                continue
            last = messages[-1]
            if last.direction == "inbound" and last.status in ("unanswered", "sent", "delivered", "read"):
                unanswered.append(thread)

        return len(unanswered), unanswered

    @classmethod
    async def dashboard(cls, db: AsyncSession, tenant_id: UUID | None) -> GrowthCenterDashboardResponse:
        leads = await cls._load_leads(db, tenant_id)
        deals = await cls._load_deals(db, tenant_id)
        buyers = await cls._load_buyers(db, tenant_id)
        proposals = await cls._load_proposals(db, tenant_id)
        follow_ups_due = await cls._follow_ups_due(db, tenant_id)
        unanswered_count, unanswered_threads = await cls._communication_stats(db, tenant_id)
        total_threads = max(unanswered_count, len(unanswered_threads))

        kpis = cls._build_kpis(leads, deals, buyers, proposals, follow_ups_due)
        market = cls._build_market_insights(leads, buyers, proposals)
        health = cls._build_health_scores(
            leads, deals, buyers, follow_ups_due, unanswered_count, total_threads,
        )
        opportunities = cls._build_opportunities(deals)
        recommendations = cls._build_recommendations(
            leads, deals, buyers, proposals, unanswered_threads, follow_ups_due,
        )
        timeline = await cls._build_timeline(db, tenant_id, leads, buyers, proposals, deals)

        logger.info(
            "%s dashboard tenant=%s leads=%s buyers=%s deals=%s",
            MARKER,
            tenant_id,
            kpis.total_leads,
            kpis.total_buyers,
            kpis.total_deals,
        )

        return GrowthCenterDashboardResponse(
            kpis=kpis,
            market_insights=market,
            health_scores=health,
            recommendations=recommendations,
            opportunities=opportunities,
            timeline=timeline,
            export_formats=growth_center_export_service.list_formats(),
            generated_at=_utcnow(),
        )
