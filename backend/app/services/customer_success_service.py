"""Customer Success & Factory ROI Center — measures platform value for factory tenants."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.buyer_crm import Buyer
from app.models.communication import CommunicationMessage, CommunicationThread
from app.models.content_factory import ContentFactory, ContentFactoryItem
from app.models.sales_crm import SalesActivity, SalesDeal, SalesLead, SalesProposal
from app.models.tenant import Tenant, TenantUser
from app.schemas.buyer_crm import DistributionItem
from app.schemas.customer_success import (
    AdminTenantSummary,
    AdoptionDashboard,
    AdoptionMetric,
    AiInsight,
    BusinessImpactMetrics,
    ChurnRiskItem,
    CustomerSuccessDashboardResponse,
    CustomerSuccessHealthScore,
    CustomerSuccessSummaryResponse,
    ExecutiveReport,
    ExecutiveReportSection,
    FactoryRoiKpis,
    HealthScoreFactor,
    RoiCalculation,
    RoiConfigWeights,
)
from app.services.communication_hub_scope import tenant_client_ids, thread_tenant_filter
from app.services.growth_center_service import (
    ACTIVE_BUYER_STATUSES,
    ACTIVE_LEAD_STATUSES,
    OPEN_DEAL_STAGES,
    GrowthCenterService,
)
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)
MARKER = "[Customer Success]"

_REACTIVATED_STATUSES = frozenset({"inactive", "prospect", "contacted"})
_ADOPTION_WINDOW_DAYS = 30
_STALE_LOGIN_DAYS = 14
_INACTIVE_LOGIN_DAYS = 30


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


def _health_status(score: int) -> str:
    if score >= 70:
        return "healthy"
    if score >= 45:
        return "needs_attention"
    return "at_risk"


def _churn_risk_level(health: int, days_since_login: int | None, sub_status: str | None) -> str:
    if health < 35 or (days_since_login is not None and days_since_login > 30):
        return "high"
    if health < 55 or sub_status == "trial" or (days_since_login is not None and days_since_login > 14):
        return "medium"
    return "low"


def _top_items(d: dict[str, int], limit: int = 6) -> list[DistributionItem]:
    sorted_items = sorted(d.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return [DistributionItem(label=k, count=v) for k, v in sorted_items]


class CustomerSuccessService:
    """Composes Growth Center data with ROI, adoption, health, and executive reporting."""

    @classmethod
    async def _subscription_cost(cls, db: AsyncSession, tenant_id: UUID | None) -> tuple[Decimal, str, str | None]:
        if tenant_id is None:
            return Decimal("99"), "USD", "professional"
        sub, plan = await SubscriptionService._active_subscription(db, tenant_id)
        if plan:
            price = _decimal(plan.monthly_price)
            return price, "USD", sub.status if sub else None
        return Decimal("0"), "USD", sub.status if sub else "trial"

    @classmethod
    async def _count_content_items(cls, db: AsyncSession, tenant_id: UUID | None) -> int:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        if tenant_id is not None and not client_ids:
            return 0
        q = select(func.count()).select_from(ContentFactoryItem).join(
            ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id,
        )
        if tenant_id is not None and client_ids:
            q = q.where(ContentFactory.client_id.in_(client_ids))
        return int((await db.execute(q)).scalar() or 0)

    @classmethod
    async def _count_communication_messages(cls, db: AsyncSession, tenant_id: UUID | None) -> int:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        thread_filt = await thread_tenant_filter(tenant_id, client_ids)
        q = select(func.count()).select_from(CommunicationMessage).join(CommunicationThread)
        if thread_filt is not None:
            q = q.where(thread_filt)
        return int((await db.execute(q)).scalar() or 0)

    @classmethod
    async def _count_period_activity(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        since: datetime,
    ) -> dict[str, int]:
        leads_q = select(func.count()).select_from(SalesLead).where(SalesLead.created_at >= since)
        deals_q = select(func.count()).select_from(SalesDeal).where(SalesDeal.created_at >= since)
        proposals_q = select(func.count()).select_from(SalesProposal).where(SalesProposal.created_at >= since)
        activities_q = select(func.count()).select_from(SalesActivity).where(SalesActivity.activity_date >= since)
        if tenant_id is not None:
            leads_q = leads_q.where(SalesLead.tenant_id == tenant_id)
            deals_q = deals_q.where(SalesDeal.tenant_id == tenant_id)
            proposals_q = proposals_q.where(SalesProposal.tenant_id == tenant_id)
            activities_q = activities_q.where(SalesActivity.tenant_id == tenant_id)

        return {
            "leads": int((await db.execute(leads_q)).scalar() or 0),
            "deals": int((await db.execute(deals_q)).scalar() or 0),
            "proposals": int((await db.execute(proposals_q)).scalar() or 0),
            "crm_activities": int((await db.execute(activities_q)).scalar() or 0),
        }

    @classmethod
    async def _user_adoption(cls, db: AsyncSession, tenant_id: UUID | None) -> tuple[int, int, int]:
        if tenant_id is None:
            return 5, 3, 10
        since = _utcnow() - timedelta(days=_ADOPTION_WINDOW_DAYS)
        users_q = select(TenantUser).where(TenantUser.tenant_id == tenant_id, TenantUser.status == "active")
        users = list((await db.execute(users_q)).scalars().all())
        total = len(users)
        logins_30d = sum(
            1 for u in users
            if u.last_login_at and (_aware(u.last_login_at) or since) >= since
        )
        active = logins_30d
        return logins_30d, active, total

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
    async def _user_adoption_counts(cls, db: AsyncSession, tenant_id: UUID | None) -> tuple[int, int, int, int | None]:
        if tenant_id is None:
            return 5, 3, 10, None
        since = _utcnow() - timedelta(days=_ADOPTION_WINDOW_DAYS)
        total_q = select(func.count()).select_from(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.status == "active",
        )
        logins_q = select(func.count()).select_from(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.status == "active",
            TenantUser.last_login_at >= since,
        )
        last_login_q = select(func.max(TenantUser.last_login_at)).select_from(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.status == "active",
        )
        total = int((await db.execute(total_q)).scalar() or 0)
        logins_30d = int((await db.execute(logins_q)).scalar() or 0)
        last_login = (await db.execute(last_login_q)).scalar()
        days_since_login = None
        if last_login:
            days_since_login = (_utcnow() - (_aware(last_login) or _utcnow())).days
        return logins_30d, logins_30d, total, days_since_login

    @classmethod
    def _compute_roi_from_values(
        cls,
        lead_count: int,
        deal_count: int,
        pipeline_value: Decimal,
        proposal_value: Decimal,
        won_revenue: Decimal,
        expected_revenue: Decimal,
        subscription_cost: Decimal,
        config: RoiConfigWeights | None = None,
    ) -> RoiCalculation:
        cfg = config or RoiConfigWeights()
        lead_value = Decimal(lead_count) * Decimal(str(cfg.lead_value_multiplier))
        value_generated = (
            pipeline_value * Decimal(str(cfg.pipeline_weight))
            + proposal_value * Decimal(str(cfg.proposal_weight))
            + won_revenue * Decimal(str(cfg.won_deals_weight))
            + lead_value * Decimal("0.1")
        )
        revenue_influenced = won_revenue + expected_revenue
        if subscription_cost > 0:
            roi_pct = float((value_generated - subscription_cost) / subscription_cost * 100)
        elif value_generated > 0:
            roi_pct = 100.0
        else:
            roi_pct = 0.0
        if roi_pct >= 200:
            label = "Excellent ROI"
        elif roi_pct >= 50:
            label = "Positive ROI"
        elif roi_pct >= 0:
            label = "Break-even"
        else:
            label = "Building value"
        return RoiCalculation(
            subscription_cost=subscription_cost,
            leads_generated=lead_count,
            deals_created=deal_count,
            pipeline_value=pipeline_value,
            proposal_value=proposal_value,
            won_revenue=won_revenue,
            value_generated=value_generated.quantize(Decimal("0.01")),
            revenue_influenced=revenue_influenced.quantize(Decimal("0.01")),
            estimated_roi_pct=round(roi_pct, 1),
            roi_label=label,
            config=cfg,
        )

    @classmethod
    async def summary(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        roi_config: RoiConfigWeights | None = None,
    ) -> CustomerSuccessSummaryResponse:
        now = _utcnow()
        since = now - timedelta(days=_ADOPTION_WINDOW_DAYS)
        lead_count = await cls._count_table(db, SalesLead, tenant_id)
        buyer_count = await cls._count_table(db, Buyer, tenant_id)
        active_buyers = await cls._count_table(db, Buyer, tenant_id, Buyer.status.in_(tuple(ACTIVE_BUYER_STATUSES)))
        deal_count = await cls._count_table(db, SalesDeal, tenant_id)
        won_deals = await cls._count_table(db, SalesDeal, tenant_id, SalesDeal.stage == "won")
        pipeline_value = await cls._sum_column(
            db, SalesDeal, SalesDeal.value, tenant_id, SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
        )
        expected_revenue = await cls._sum_column(
            db,
            SalesDeal,
            SalesDeal.value * SalesDeal.probability / 100,
            tenant_id,
            SalesDeal.stage.in_(tuple(OPEN_DEAL_STAGES)),
        )
        proposal_value = await cls._sum_column(db, SalesProposal, SalesProposal.total, tenant_id)
        won_revenue = await cls._sum_column(db, SalesDeal, SalesDeal.value, tenant_id, SalesDeal.stage == "won")
        comm_messages = await cls._count_communication_messages(db, tenant_id)
        content_items = await cls._count_content_items(db, tenant_id)
        period_activity = await cls._count_period_activity(db, tenant_id, since)
        logins_30d, active_users, total_users, days_since_login = await cls._user_adoption_counts(db, tenant_id)
        subscription_cost, currency, subscription_status = await cls._subscription_cost(db, tenant_id)

        demo_mode = settings.DEMO_MODE or (
            tenant_id is not None
            and buyer_count == 0
            and deal_count == 0
            and lead_count == 0
        )
        if demo_mode:
            demo = cls._demo_dashboard()
            return CustomerSuccessSummaryResponse(
                customer_health_score=demo.health_score,
                adoption_score=demo.adoption_summary.engagement_score,
                roi_estimate=demo.roi,
                active_users=demo.adoption_summary.active_users,
                content_activity=demo.roi_kpis.content_items_created,
                crm_activity=demo.adoption_summary.metrics[2].count,
                churn_risk="low",
                top_insights=demo.insights[:3],
                is_demo=True,
                generated_at=demo.generated_at,
            )

        adoption = cls._build_adoption(
            logins_30d,
            active_users,
            total_users,
            period_activity,
            content_items,
            comm_messages,
            [],
        )
        buyer_score = int((active_buyers / max(buyer_count, 1)) * 100)
        for metric in adoption.metrics:
            if metric.key == "buyers":
                metric.count = active_buyers
                metric.period_count = buyer_count
                metric.score = buyer_score
                break
        adoption.engagement_score = int(sum(m.score for m in adoption.metrics) / len(adoption.metrics))
        roi = cls._compute_roi_from_values(
            lead_count,
            deal_count,
            pipeline_value,
            proposal_value,
            won_revenue,
            expected_revenue,
            subscription_cost,
            roi_config,
        )
        roi.subscription_currency = currency
        health = cls._build_health_score(adoption)
        churn_risk = _churn_risk_level(health.score, days_since_login, subscription_status)

        insights: list[AiInsight] = []
        if roi.estimated_roi_pct >= 50:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="working",
                title="Strong platform ROI",
                detail=f"Estimated ROI of {roi.estimated_roi_pct:.0f}% from pipeline, proposals, and won revenue.",
                priority="medium",
                href="/customer-success/roi",
            ))
        if adoption.engagement_score < 45:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="not_working",
                title="Adoption needs attention",
                detail=f"Engagement score is {adoption.engagement_score}/100 across users, content, CRM, and communication.",
                priority="high",
                href="/customer-success/adoption",
            ))
        if active_buyers > 0:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="buyer",
                title="Active buyer base",
                detail=f"{active_buyers} active buyers out of {buyer_count} total buyer records.",
                priority="medium",
                href="/buyers",
            ))
        if not insights:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="activity",
                title="First success signals ready",
                detail="Use content, CRM activity, and buyer outreach to build measurable ROI.",
                priority="medium",
                href="/customer-success",
            ))

        return CustomerSuccessSummaryResponse(
            customer_health_score=health,
            adoption_score=adoption.engagement_score,
            roi_estimate=roi,
            active_users=active_users,
            content_activity=content_items,
            crm_activity=period_activity.get("crm_activities", 0),
            churn_risk=churn_risk,  # type: ignore[arg-type]
            top_insights=insights[:3],
            is_demo=False,
            generated_at=now,
        )

    @classmethod
    def _compute_roi(
        cls,
        leads: list,
        deals: list,
        proposals: list,
        subscription_cost: Decimal,
        config: RoiConfigWeights | None = None,
    ) -> RoiCalculation:
        cfg = config or RoiConfigWeights()
        open_deals = [d for d in deals if d.stage in OPEN_DEAL_STAGES]
        won_deals = [d for d in deals if d.stage == "won"]

        pipeline_value = sum((_decimal(d.value) for d in open_deals), Decimal("0"))
        proposal_value = sum((_decimal(p.total) for p in proposals), Decimal("0"))
        won_revenue = sum((_decimal(d.value) for d in won_deals), Decimal("0"))
        lead_value = Decimal(len(leads)) * Decimal(str(cfg.lead_value_multiplier))

        value_generated = (
            pipeline_value * Decimal(str(cfg.pipeline_weight))
            + proposal_value * Decimal(str(cfg.proposal_weight))
            + won_revenue * Decimal(str(cfg.won_deals_weight))
            + lead_value * Decimal("0.1")
        )
        revenue_influenced = won_revenue + sum(
            (_decimal(d.value) * Decimal(d.probability) / Decimal(100) for d in open_deals),
            Decimal("0"),
        )

        if subscription_cost > 0:
            roi_pct = float((value_generated - subscription_cost) / subscription_cost * 100)
        elif value_generated > 0:
            roi_pct = 100.0
        else:
            roi_pct = 0.0

        if roi_pct >= 200:
            label = "Excellent ROI"
        elif roi_pct >= 50:
            label = "Positive ROI"
        elif roi_pct >= 0:
            label = "Break-even"
        else:
            label = "Building value"

        return RoiCalculation(
            subscription_cost=subscription_cost,
            leads_generated=len(leads),
            deals_created=len(deals),
            pipeline_value=pipeline_value,
            proposal_value=proposal_value,
            won_revenue=won_revenue,
            value_generated=value_generated.quantize(Decimal("0.01")),
            revenue_influenced=revenue_influenced.quantize(Decimal("0.01")),
            estimated_roi_pct=round(roi_pct, 1),
            roi_label=label,
            config=cfg,
        )

    @classmethod
    def _build_roi_kpis(
        cls,
        leads: list,
        deals: list,
        buyers: list,
        proposals: list,
        comm_messages: int,
        content_items: int,
    ) -> FactoryRoiKpis:
        open_deals = [d for d in deals if d.stage in OPEN_DEAL_STAGES]
        won_deals = [d for d in deals if d.stage == "won"]
        active_buyers = [b for b in buyers if b.status in ACTIVE_BUYER_STATUSES]
        pipeline_value = sum((_decimal(d.value) for d in open_deals), Decimal("0"))
        proposal_value = sum((_decimal(p.total) for p in proposals), Decimal("0"))
        revenue_influenced = sum((_decimal(d.value) for d in won_deals), Decimal("0")) + sum(
            (_decimal(d.value) * Decimal(d.probability) / Decimal(100) for d in open_deals),
            Decimal("0"),
        )

        return FactoryRoiKpis(
            total_leads_generated=len(leads),
            total_buyers_added=len(buyers),
            active_buyers=len(active_buyers),
            deals_created=len(deals),
            deals_won=len(won_deals),
            proposal_value=proposal_value,
            pipeline_value=pipeline_value,
            estimated_revenue_influenced=revenue_influenced,
            communication_messages=comm_messages,
            content_items_created=content_items,
        )

    @classmethod
    def _build_adoption(
        cls,
        logins_30d: int,
        active_users: int,
        total_users: int,
        period_activity: dict[str, int],
        content_items: int,
        comm_messages: int,
        buyers: list,
    ) -> AdoptionDashboard:
        now = _utcnow()
        since = now - timedelta(days=_ADOPTION_WINDOW_DAYS)
        buyer_activity = sum(
            1 for b in buyers
            if (_aware(b.updated_at) or now) >= since
        )

        def _score(count: int, target: int) -> int:
            if target <= 0:
                return 75 if count > 0 else 40
            return int(min(100, max(0, (count / target) * 100)))

        login_target = max(total_users, 1)
        metrics = [
            AdoptionMetric(
                key="logins",
                label="User Logins",
                count=logins_30d,
                period_count=logins_30d,
                score=_score(logins_30d, login_target),
            ),
            AdoptionMetric(
                key="content",
                label="Content Uploads",
                count=content_items,
                period_count=content_items,
                score=_score(content_items, 10),
            ),
            AdoptionMetric(
                key="crm",
                label="CRM Activity",
                count=period_activity.get("crm_activities", 0),
                period_count=period_activity.get("leads", 0) + period_activity.get("deals", 0),
                score=_score(period_activity.get("crm_activities", 0), 5),
            ),
            AdoptionMetric(
                key="buyers",
                label="Buyer Activity",
                count=buyer_activity,
                period_count=len(buyers),
                score=_score(buyer_activity, max(len(buyers), 1)),
            ),
            AdoptionMetric(
                key="communication",
                label="Communication Activity",
                count=comm_messages,
                period_count=comm_messages,
                score=_score(comm_messages, 20),
            ),
            AdoptionMetric(
                key="proposals",
                label="Proposal Activity",
                count=period_activity.get("proposals", 0),
                period_count=period_activity.get("proposals", 0),
                score=_score(period_activity.get("proposals", 0), 3),
            ),
        ]
        engagement_score = int(sum(m.score for m in metrics) / len(metrics)) if metrics else 0

        return AdoptionDashboard(
            metrics=metrics,
            engagement_score=engagement_score,
            user_logins_30d=logins_30d,
            active_users=active_users,
            total_users=total_users,
        )

    @classmethod
    def _build_business_impact(
        cls,
        leads: list,
        deals: list,
        buyers: list,
        proposals: list,
    ) -> BusinessImpactMetrics:
        now = _utcnow()
        since_90d = now - timedelta(days=90)
        acquired = sum(
            1 for b in buyers
            if (_aware(b.created_at) or now) >= since_90d
        )
        reactivated = sum(
            1 for b in buyers
            if b.status in ACTIVE_BUYER_STATUSES
            and (_aware(b.updated_at) or now) >= since_90d
            and (_aware(b.created_at) or now) < since_90d
        )

        sent_or_closed = [p for p in proposals if p.status in ("sent", "viewed", "accepted", "rejected")]
        accepted = sum(1 for p in sent_or_closed if p.status == "accepted")
        acceptance_rate = (accepted / len(sent_or_closed) * 100) if sent_or_closed else 0.0

        progression_days: list[float] = []
        for deal in deals:
            if deal.stage == "won":
                created = _aware(deal.created_at)
                updated = _aware(deal.updated_at)
                if created and updated:
                    progression_days.append((updated - created).days)

        avg_progression = sum(progression_days) / len(progression_days) if progression_days else 0.0
        won_value = sum((_decimal(d.value) for d in deals if d.stage == "won"), Decimal("0"))
        pipeline_created = sum((_decimal(d.value) for d in deals if d.stage in OPEN_DEAL_STAGES), Decimal("0"))

        return BusinessImpactMetrics(
            buyers_acquired=acquired,
            buyers_reactivated=reactivated,
            opportunities_created=len([d for d in deals if d.stage in OPEN_DEAL_STAGES]),
            proposal_acceptance_rate=round(acceptance_rate, 1),
            average_deal_progression_days=round(avg_progression, 1),
            won_deal_value=won_value,
            pipeline_created_value=pipeline_created,
        )

    @classmethod
    def _build_health_score(cls, adoption: AdoptionDashboard) -> CustomerSuccessHealthScore:
        factor_map = {
            "adoption": ("Adoption", adoption.engagement_score, 20),
            "content": ("Content Activity", next((m.score for m in adoption.metrics if m.key == "content"), 50), 15),
            "crm": ("CRM Activity", next((m.score for m in adoption.metrics if m.key == "crm"), 50), 20),
            "buyers": ("Buyer Activity", next((m.score for m in adoption.metrics if m.key == "buyers"), 50), 20),
            "communication": ("Communication", next((m.score for m in adoption.metrics if m.key == "communication"), 50), 15),
            "proposals": ("Proposal Activity", next((m.score for m in adoption.metrics if m.key == "proposals"), 50), 10),
        }
        factors: list[HealthScoreFactor] = []
        weighted_sum = 0.0
        for key, (label, score, weight) in factor_map.items():
            factors.append(HealthScoreFactor(
                factor=key,
                label=label,
                score=score,
                weight_pct=float(weight),
                summary=f"{label}: {score}/100",
            ))
            weighted_sum += score * weight

        total_score = int(round(weighted_sum / 100))
        status = _health_status(total_score)

        status_labels = {
            "healthy": "Healthy",
            "needs_attention": "Needs Attention",
            "at_risk": "At Risk",
        }

        return CustomerSuccessHealthScore(
            score=total_score,
            status=status,  # type: ignore[arg-type]
            label=status_labels.get(status, "Unknown"),
            summary=f"Platform health score {total_score}/100 — {status_labels.get(status, '')}",
            factors=factors,
        )

    @classmethod
    def _build_insights(
        cls,
        leads: list,
        deals: list,
        buyers: list,
        proposals: list,
        adoption: AdoptionDashboard,
        business_impact: BusinessImpactMetrics,
        roi: RoiCalculation,
    ) -> list[AiInsight]:
        insights: list[AiInsight] = []
        now = _utcnow()

        if roi.estimated_roi_pct >= 50:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="working",
                title="Strong platform ROI",
                detail=f"Estimated ROI of {roi.estimated_roi_pct:.0f}% — pipeline and won deals exceed subscription cost.",
                priority="medium",
                href="/customer-success/roi",
            ))

        if business_impact.proposal_acceptance_rate >= 30:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="working",
                title="Proposal conversion is healthy",
                detail=f"{business_impact.proposal_acceptance_rate:.0f}% acceptance rate on sent proposals.",
                priority="low",
                href="/proposals",
            ))

        low_adoption = [m for m in adoption.metrics if m.score < 45]
        for metric in low_adoption[:2]:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="not_working",
                title=f"Low {metric.label.lower()}",
                detail=f"Only {metric.count} {metric.label.lower()} recorded — increase engagement to improve ROI.",
                priority="high" if metric.key in ("logins", "crm") else "medium",
                href="/customer-success/adoption",
            ))

        by_country: dict[str, int] = {}
        for buyer in buyers:
            if buyer.country:
                by_country[buyer.country] = by_country.get(buyer.country, 0) + 1
        if by_country:
            top_country = max(by_country, key=by_country.get)  # type: ignore[arg-type]
            insights.append(AiInsight(
                id=str(uuid4()),
                category="market",
                title=f"Growing market: {top_country}",
                detail=f"{by_country[top_country]} buyers from {top_country} — prioritize outreach in this region.",
                priority="medium",
                href="/buyers",
            ))

        stale_buyers = [
            b for b in buyers
            if b.status in ("prospect", "contacted", "interested")
            and (_aware(b.updated_at) or now) < now - timedelta(days=7)
        ]
        for buyer in stale_buyers[:3]:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="buyer",
                title=f"Buyer needs attention: {buyer.company_name}",
                detail=f"No activity in 7+ days — status: {buyer.status.replace('_', ' ')}.",
                priority="high",
                href=f"/buyers/{buyer.id}",
            ))

        if len(leads) > 0 and sum(1 for l in leads if l.status in ACTIVE_LEAD_STATUSES) / len(leads) > 0.5:
            insights.append(AiInsight(
                id=str(uuid4()),
                category="activity",
                title="Lead generation is active",
                detail=f"{len(leads)} leads with strong active ratio — CRM activity drives pipeline value.",
                priority="low",
                href="/leads",
            ))

        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        insights.sort(key=lambda i: priority_rank.get(i.priority, 4))
        return insights[:10]

    @classmethod
    def _demo_dashboard(cls) -> CustomerSuccessDashboardResponse:
        now = _utcnow()
        roi_kpis = FactoryRoiKpis(
            total_leads_generated=47,
            total_buyers_added=23,
            active_buyers=15,
            deals_created=12,
            deals_won=4,
            proposal_value=Decimal("185000"),
            pipeline_value=Decimal("320000"),
            estimated_revenue_influenced=Decimal("412000"),
            communication_messages=156,
            content_items_created=28,
        )
        roi = RoiCalculation(
            subscription_cost=Decimal("99"),
            leads_generated=47,
            deals_created=12,
            pipeline_value=Decimal("320000"),
            proposal_value=Decimal("185000"),
            won_revenue=Decimal("92000"),
            value_generated=Decimal("248500"),
            revenue_influenced=Decimal("412000"),
            estimated_roi_pct=2508.1,
            roi_label="Excellent ROI",
        )
        adoption = AdoptionDashboard(
            metrics=[
                AdoptionMetric(key="logins", label="User Logins", count=8, period_count=8, score=80),
                AdoptionMetric(key="content", label="Content Uploads", count=28, period_count=28, score=85),
                AdoptionMetric(key="crm", label="CRM Activity", count=34, period_count=12, score=78),
                AdoptionMetric(key="buyers", label="Buyer Activity", count=18, period_count=23, score=72),
                AdoptionMetric(key="communication", label="Communication Activity", count=156, period_count=156, score=88),
                AdoptionMetric(key="proposals", label="Proposal Activity", count=7, period_count=7, score=70),
            ],
            engagement_score=79,
            user_logins_30d=8,
            active_users=5,
            total_users=6,
        )
        health = CustomerSuccessHealthScore(
            score=79,
            status="healthy",
            label="Healthy",
            summary="Platform health score 79/100 — Healthy",
            factors=[
                HealthScoreFactor(factor="adoption", label="Adoption", score=79, weight_pct=20, summary="Adoption: 79/100"),
                HealthScoreFactor(factor="content", label="Content Activity", score=85, weight_pct=15, summary="Content: 85/100"),
                HealthScoreFactor(factor="crm", label="CRM Activity", score=78, weight_pct=20, summary="CRM: 78/100"),
                HealthScoreFactor(factor="buyers", label="Buyer Activity", score=72, weight_pct=20, summary="Buyers: 72/100"),
                HealthScoreFactor(factor="communication", label="Communication", score=88, weight_pct=15, summary="Comms: 88/100"),
                HealthScoreFactor(factor="proposals", label="Proposal Activity", score=70, weight_pct=10, summary="Proposals: 70/100"),
            ],
        )
        impact = BusinessImpactMetrics(
            buyers_acquired=8,
            buyers_reactivated=3,
            opportunities_created=8,
            proposal_acceptance_rate=42.9,
            average_deal_progression_days=28.5,
            won_deal_value=Decimal("92000"),
            pipeline_created_value=Decimal("320000"),
        )
        insights = [
            AiInsight(
                id="demo-1", category="working", title="Strong platform ROI",
                detail="Estimated ROI of 2508% — pipeline and won deals far exceed subscription cost.",
                priority="medium", href="/customer-success/roi",
            ),
            AiInsight(
                id="demo-2", category="market", title="Growing market: Uzbekistan",
                detail="9 buyers from Uzbekistan — prioritize outreach in Central Asia.",
                priority="medium", href="/buyers",
            ),
            AiInsight(
                id="demo-3", category="buyer", title="Buyer needs attention: Samarkand Build Co.",
                detail="No activity in 8 days — status: interested.",
                priority="high", href="/buyers",
            ),
        ]
        return CustomerSuccessDashboardResponse(
            roi_kpis=roi_kpis,
            roi=roi,
            health_score=health,
            adoption_summary=adoption,
            business_impact=impact,
            insights=insights,
            top_markets=[
                DistributionItem(label="Uzbekistan", count=9),
                DistributionItem(label="Kazakhstan", count=7),
                DistributionItem(label="Kyrgyzstan", count=4),
            ],
            is_demo=True,
            generated_at=now,
        )

    @classmethod
    async def _load_tenant_data(cls, db: AsyncSession, tenant_id: UUID | None):
        leads = await GrowthCenterService._load_leads(db, tenant_id)
        deals = await GrowthCenterService._load_deals(db, tenant_id)
        buyers = await GrowthCenterService._load_buyers(db, tenant_id)
        proposals = await GrowthCenterService._load_proposals(db, tenant_id)
        return leads, deals, buyers, proposals

    @classmethod
    async def dashboard(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        roi_config: RoiConfigWeights | None = None,
    ) -> CustomerSuccessDashboardResponse:
        leads, deals, buyers, proposals = await cls._load_tenant_data(db, tenant_id)

        demo_mode = settings.DEMO_MODE or (
            tenant_id is not None
            and len(buyers) == 0
            and len(deals) == 0
            and len(leads) == 0
        )
        if demo_mode:
            return cls._demo_dashboard()

        since = _utcnow() - timedelta(days=_ADOPTION_WINDOW_DAYS)
        comm_messages = await cls._count_communication_messages(db, tenant_id)
        content_items = await cls._count_content_items(db, tenant_id)
        period_activity = await cls._count_period_activity(db, tenant_id, since)
        logins_30d, active_users, total_users = await cls._user_adoption(db, tenant_id)
        subscription_cost, currency, _ = await cls._subscription_cost(db, tenant_id)

        roi_kpis = cls._build_roi_kpis(leads, deals, buyers, proposals, comm_messages, content_items)
        roi = cls._compute_roi(leads, deals, proposals, subscription_cost, roi_config)
        roi.subscription_currency = currency
        adoption = cls._build_adoption(
            logins_30d, active_users, total_users, period_activity,
            content_items, comm_messages, buyers,
        )
        business_impact = cls._build_business_impact(leads, deals, buyers, proposals)
        health_score = cls._build_health_score(adoption)
        insights = cls._build_insights(leads, deals, buyers, proposals, adoption, business_impact, roi)

        by_country: dict[str, int] = {}
        for buyer in buyers:
            if buyer.country:
                by_country[buyer.country] = by_country.get(buyer.country, 0) + 1

        logger.info(
            "%s dashboard tenant=%s roi=%s health=%s",
            MARKER, tenant_id, roi.estimated_roi_pct, health_score.score,
        )

        return CustomerSuccessDashboardResponse(
            roi_kpis=roi_kpis,
            roi=roi,
            health_score=health_score,
            adoption_summary=adoption,
            business_impact=business_impact,
            insights=insights,
            top_markets=_top_items(by_country),
            is_demo=False,
            generated_at=_utcnow(),
        )

    @classmethod
    async def roi_dashboard(cls, db: AsyncSession, tenant_id: UUID | None, config: RoiConfigWeights | None = None):
        dash = await cls.dashboard(db, tenant_id, config)
        return {"roi_kpis": dash.roi_kpis, "roi": dash.roi, "health_score": dash.health_score, "generated_at": dash.generated_at}

    @classmethod
    async def adoption_dashboard(cls, db: AsyncSession, tenant_id: UUID | None):
        dash = await cls.dashboard(db, tenant_id)
        return {"adoption": dash.adoption_summary, "health_score": dash.health_score, "generated_at": dash.generated_at}

    @classmethod
    async def business_impact_dashboard(cls, db: AsyncSession, tenant_id: UUID | None):
        dash = await cls.dashboard(db, tenant_id)
        return {
            "business_impact": dash.business_impact,
            "roi_kpis": dash.roi_kpis,
            "top_markets": dash.top_markets,
            "generated_at": dash.generated_at,
        }

    @classmethod
    async def executive_report(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        period: str,
    ) -> ExecutiveReport:
        dash = await cls.dashboard(db, tenant_id)
        kpis = dash.roi_kpis
        roi = dash.roi
        health = dash.health_score
        impact = dash.business_impact

        if period == "quarterly":
            title = "Quarterly Executive Report"
            summary = (
                f"Over the quarter, the platform generated {kpis.total_leads_generated} leads, "
                f"added {kpis.total_buyers_added} buyers, and influenced "
                f"${float(kpis.estimated_revenue_influenced):,.0f} in revenue. "
                f"Estimated ROI: {roi.estimated_roi_pct:.0f}% ({roi.roi_label}). "
                f"Platform health: {health.label} ({health.score}/100)."
            )
        else:
            title = "Monthly Executive Report"
            summary = (
                f"This month: {impact.buyers_acquired} buyers acquired, "
                f"{kpis.deals_won} deals won, pipeline value "
                f"${float(kpis.pipeline_value):,.0f}. "
                f"Engagement score: {dash.adoption_summary.engagement_score}/100. "
                f"Health status: {health.label}."
            )

        sections = [
            ExecutiveReportSection(
                title="Pipeline & Revenue",
                bullets=[
                    f"Pipeline value: ${float(kpis.pipeline_value):,.0f}",
                    f"Proposal value: ${float(kpis.proposal_value):,.0f}",
                    f"Revenue influenced: ${float(kpis.estimated_revenue_influenced):,.0f}",
                    f"Deals won: {kpis.deals_won} of {kpis.deals_created}",
                ],
            ),
            ExecutiveReportSection(
                title="Buyer & Lead Growth",
                bullets=[
                    f"Total leads: {kpis.total_leads_generated}",
                    f"Buyers added: {kpis.total_buyers_added} ({kpis.active_buyers} active)",
                    f"Buyers acquired (90d): {impact.buyers_acquired}",
                    f"Buyers reactivated: {impact.buyers_reactivated}",
                ],
            ),
            ExecutiveReportSection(
                title="Platform Adoption",
                bullets=[
                    f"Engagement score: {dash.adoption_summary.engagement_score}/100",
                    f"User logins (30d): {dash.adoption_summary.user_logins_30d}",
                    f"Content items: {kpis.content_items_created}",
                    f"Communications: {kpis.communication_messages} messages",
                ],
            ),
            ExecutiveReportSection(
                title="ROI Summary",
                bullets=[
                    f"Subscription cost: ${float(roi.subscription_cost):,.0f}/mo",
                    f"Value generated: ${float(roi.value_generated):,.0f}",
                    f"Estimated ROI: {roi.estimated_roi_pct:.0f}%",
                    f"Proposal acceptance: {impact.proposal_acceptance_rate:.0f}%",
                ],
            ),
        ]

        return ExecutiveReport(
            period=period,  # type: ignore[arg-type]
            title=title,
            generated_at=_utcnow(),
            executive_summary=summary,
            sections=sections,
            kpis=kpis,
            roi=roi,
            health_score=health,
        )

    @classmethod
    async def _load_all_tenants(cls, db: AsyncSession, limit: int = 100) -> list[Tenant]:
        q = select(Tenant).order_by(Tenant.created_at.desc()).limit(limit)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def admin_tenant_overview(cls, db: AsyncSession) -> list[AdminTenantSummary]:
        tenants = await cls._load_all_tenants(db)
        summaries: list[AdminTenantSummary] = []

        for tenant in tenants:
            try:
                dash = await cls.dashboard(db, tenant.id)
                logins_30d, _, total_users = await cls._user_adoption(db, tenant.id)
                _, _, sub_status = await cls._subscription_cost(db, tenant.id)

                days_since_login: int | None = None
                users_q = select(TenantUser).where(
                    TenantUser.tenant_id == tenant.id,
                    TenantUser.status == "active",
                )
                users = list((await db.execute(users_q)).scalars().all())
                last_logins = [_aware(u.last_login_at) for u in users if u.last_login_at]
                if last_logins:
                    latest = max(last_logins)
                    days_since_login = (_utcnow() - latest).days

                churn = _churn_risk_level(dash.health_score.score, days_since_login, sub_status)
                sub, plan = await SubscriptionService._active_subscription(db, tenant.id)

                summaries.append(AdminTenantSummary(
                    tenant_id=tenant.id,
                    tenant_name=tenant.company_name,
                    status=tenant.status,
                    plan_name=plan.name if plan else None,
                    health_score=dash.health_score.score,
                    health_status=dash.health_score.status,
                    engagement_score=dash.adoption_summary.engagement_score,
                    estimated_roi_pct=dash.roi.estimated_roi_pct,
                    pipeline_value=dash.roi_kpis.pipeline_value,
                    active_buyers=dash.roi_kpis.active_buyers,
                    churn_risk=churn,  # type: ignore[arg-type]
                ))
            except Exception as exc:
                logger.warning("%s admin overview skip tenant=%s: %s", MARKER, tenant.id, exc)

        summaries.sort(key=lambda s: s.health_score)
        return summaries

    @classmethod
    async def churn_risk_report(cls, db: AsyncSession) -> list[ChurnRiskItem]:
        tenants = await cls._load_all_tenants(db)
        items: list[ChurnRiskItem] = []

        for tenant in tenants:
            dash = await cls.dashboard(db, tenant.id)
            users_q = select(TenantUser).where(
                TenantUser.tenant_id == tenant.id,
                TenantUser.status == "active",
            )
            users = list((await db.execute(users_q)).scalars().all())
            last_logins = [_aware(u.last_login_at) for u in users if u.last_login_at]
            days_since_login: int | None = None
            if last_logins:
                days_since_login = (_utcnow() - max(last_logins)).days

            _, _, sub_status = await cls._subscription_cost(db, tenant.id)
            risk = _churn_risk_level(dash.health_score.score, days_since_login, sub_status)
            if risk == "low":
                continue

            reasons: list[str] = []
            recommendations: list[str] = []

            if dash.health_score.score < 45:
                reasons.append(f"Low health score ({dash.health_score.score}/100)")
                recommendations.append("Schedule onboarding review with factory owner")
            if days_since_login is not None and days_since_login > _INACTIVE_LOGIN_DAYS:
                reasons.append(f"No user login in {days_since_login} days")
                recommendations.append("Send re-engagement email to tenant users")
            if sub_status == "trial":
                reasons.append("Trial subscription — conversion window closing")
                recommendations.append("Offer demo ROI report and upgrade consultation")
            if dash.adoption_summary.engagement_score < 40:
                reasons.append(f"Low engagement score ({dash.adoption_summary.engagement_score}/100)")
                recommendations.append("Guide tenant through CRM and buyer setup")

            items.append(ChurnRiskItem(
                tenant_id=tenant.id,
                tenant_name=tenant.company_name,
                risk_level=risk,  # type: ignore[arg-type]
                health_score=dash.health_score.score,
                days_since_login=days_since_login,
                subscription_status=sub_status,
                reasons=reasons or ["Below-average platform engagement"],
                recommendations=recommendations or ["Review tenant activity in admin dashboard"],
            ))

        priority = {"high": 0, "medium": 1, "low": 2}
        items.sort(key=lambda i: (priority.get(i.risk_level, 3), i.health_score))
        return items
