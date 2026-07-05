"""Customer Success Journey service — post-platform-ready 30-day adoption engine."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_crm import Buyer
from app.models.content import ContentItem
from app.models.customer_success_journey import TenantCustomerSuccessJourney
from app.models.publishing_account import PublishingAccount
from app.models.publish_attempt import PublishAttempt
from app.models.tenant import Tenant, TenantUser
from app.models.tenant_onboarding import TenantOnboardingProgress
from app.schemas.customer_success import CustomerSuccessHealthScore
from app.schemas.customer_success_journey import (
    CustomerSuccessJourneyDashboard,
    JourneyAdminOverview,
    JourneyAdminTenantItem,
    JourneyDismissRecommendationResponse,
    JourneyRefreshResponse,
    NorthStarGoalOption,
)
from app.services.customer_success_journey_rule_engine import (
    CHECKPOINT_DAYS,
    CustomerSuccessJourneyRuleEngine,
    JourneyRuleContext,
    NORTH_STAR_OPTIONS,
)
from app.services.customer_success_service import CustomerSuccessService
from app.services.growth_center_service import GrowthCenterService, OPEN_DEAL_STAGES
from app.services.onboarding_readiness_service import OnboardingReadinessService
from app.services.subscription_service import SubscriptionService
from app.services.tenant_operations_service import ACTIVE_ACCOUNT_STATUSES
from app.services.tenant_onboarding_service import TenantOnboardingService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)
MARKER = "[Customer Success Journey]"
_JOURNEY_DAYS = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _north_star_label(goal: str | None) -> str | None:
    if not goal:
        return None
    for key, label, _ in NORTH_STAR_OPTIONS:
        if key == goal:
            return label
    return goal.replace("_", " ").title()


class CustomerSuccessJourneyService:
    """Tenant-scoped adoption journey — starts when platform is ready, separate from onboarding."""

    @classmethod
    def north_star_options(cls) -> list[NorthStarGoalOption]:
        return [
            NorthStarGoalOption(key=key, label=label, description=desc)  # type: ignore[arg-type]
            for key, label, desc in NORTH_STAR_OPTIONS
        ]

    @classmethod
    async def _get_progress(cls, db: AsyncSession, tenant_id: UUID) -> TenantOnboardingProgress:
        return await TenantOnboardingService.get_or_create_progress(db, tenant_id)

    @classmethod
    async def _get_journey(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
    ) -> TenantCustomerSuccessJourney | None:
        return (await db.execute(
            select(TenantCustomerSuccessJourney).where(
                TenantCustomerSuccessJourney.tenant_id == tenant_id,
            ),
        )).scalar_one_or_none()

    @classmethod
    async def _ensure_journey(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        platform_ready: bool,
        platform_ready_at: datetime | None,
    ) -> TenantCustomerSuccessJourney | None:
        if not platform_ready:
            return None

        journey = await cls._get_journey(db, tenant_id)
        if journey is None:
            journey = TenantCustomerSuccessJourney(
                tenant_id=tenant_id,
                status="active",
                started_at=platform_ready_at or _utcnow(),
                milestones_achieved={},
                timeline_entries=[],
                weekly_wins=[],
                dismissed_recommendations=[],
            )
            db.add(journey)
            await db.flush()
            logger.info("%s started tenant=%s", MARKER, tenant_id)
        elif journey.status == "not_started":
            journey.status = "active"
            journey.started_at = journey.started_at or platform_ready_at or _utcnow()
        return journey

    @classmethod
    def _journey_day(cls, started_at: datetime | None) -> int:
        if started_at is None:
            return 0
        start = _aware(started_at)
        if start is None:
            return 0
        days = (_utcnow() - start).days + 1
        return max(1, min(_JOURNEY_DAYS, days))

    @classmethod
    async def _gather_journey_signals(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        progress: TenantOnboardingProgress,
    ) -> dict:
        onboarding_signals = await OnboardingReadinessService._gather_signals(
            db, tenant_id, progress,
        )
        leads, deals, buyers, proposals = await CustomerSuccessService._load_tenant_data(
            db, tenant_id,
        )
        since_30d = _utcnow() - timedelta(days=30)
        since_7d = _utcnow() - timedelta(days=7)
        since_week = _utcnow() - timedelta(days=7)

        period_activity = await CustomerSuccessService._count_period_activity(
            db, tenant_id, since_week,
        )
        comm_messages = await CustomerSuccessService._count_communication_messages(db, tenant_id)
        content_items = await CustomerSuccessService._count_content_items(db, tenant_id)
        logins_30d, active_users, total_users = await CustomerSuccessService._user_adoption(
            db, tenant_id,
        )

        logins_period = int(
            (await db.execute(
                select(func.count()).select_from(TenantUser).where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.status == "active",
                    TenantUser.last_login_at >= since_week,
                ),
            )).scalar() or 0,
        )

        buyers_period = int(
            (await db.execute(
                select(func.count()).select_from(Buyer).where(
                    Buyer.tenant_id == tenant_id,
                    Buyer.created_at >= since_week,
                ),
            )).scalar() or 0,
        )

        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)

        publishing_account_count = int(
            (await db.execute(
                select(func.count()).select_from(PublishingAccount).where(
                    PublishingAccount.tenant_id == tenant_id,
                    PublishingAccount.status.in_(tuple(ACTIVE_ACCOUNT_STATUSES)),
                ),
            )).scalar() or 0,
        )

        publish_attempts_7d = 0
        if client_ids:
            publish_attempts_7d = int(
                (await db.execute(
                    select(func.count()).select_from(PublishAttempt).join(
                        ContentItem, PublishAttempt.content_id == ContentItem.id,
                    ).where(
                        ContentItem.client_id.in_(client_ids),
                        PublishAttempt.created_at >= since_7d,
                    ),
                )).scalar() or 0,
            )

        published_recent = 0
        if client_ids:
            published_recent = int(
                (await db.execute(
                    select(func.count()).select_from(ContentItem).where(
                        ContentItem.client_id.in_(client_ids),
                        or_(
                            ContentItem.published_at >= since_7d,
                            ContentItem.status == "published",
                        ),
                    ),
                )).scalar() or 0,
            )

        walkthrough = OnboardingReadinessService.walkthrough_panels(progress)
        open_deals = [d for d in deals if d.stage in OPEN_DEAL_STAGES]
        pipeline_value = sum(
            (Decimal(str(d.value or 0)) for d in open_deals),
            Decimal("0"),
        )

        return {
            **onboarding_signals,
            "leads_count": len(leads),
            "deals_count": len(deals),
            "buyers_count": len(buyers),
            "proposals_count": len(proposals),
            "leads_period": period_activity.get("leads", 0),
            "deals_period": period_activity.get("deals", 0),
            "buyers_period": buyers_period,
            "proposals_period": period_activity.get("proposals", 0),
            "crm_activities": period_activity.get("crm_activities", 0),
            "comm_period": comm_messages,
            "comm_messages": comm_messages,
            "content_items": content_items,
            "logins_30d": logins_30d,
            "logins_period": logins_period,
            "active_users": active_users,
            "total_users": total_users,
            "published_count": 1 if onboarding_signals.get("first_published_content") else 0,
            "published_recent": published_recent,
            "publish_attempts_7d": publish_attempts_7d,
            "walkthrough_completed": walkthrough.completed,
            "growth_center_viewed": bool(progress.growth_center_viewed_at),
            "publishing_accounts": publishing_account_count,
            "team_count": total_users,
            "meta_connected": bool(
                onboarding_signals.get("facebook_connected")
                or onboarding_signals.get("instagram_connected"),
            ),
            "pipeline_value": pipeline_value,
            "since_30d": since_30d,
        }

    @classmethod
    async def _plan_usage_pct(cls, db: AsyncSession, tenant_id: UUID) -> float:
        try:
            usage = await SubscriptionService.usage(db, tenant_id)
            pcts: list[float] = []
            for key, data in (usage or {}).items():
                if isinstance(data, dict):
                    limit = data.get("limit") or 0
                    used = data.get("used") or 0
                    if limit and limit > 0:
                        pcts.append(float(used) / float(limit) * 100)
            return max(pcts) if pcts else 0.0
        except Exception:
            return 0.0

    @classmethod
    async def _renewal_context(cls, db: AsyncSession, tenant_id: UUID) -> tuple[int | None, str | None]:
        try:
            summary = await SubscriptionService.summary(db, tenant_id)
            next_renewal = summary.get("next_renewal")
            status = summary.get("status")
            days: int | None = None
            if next_renewal:
                nr = _aware(next_renewal) if isinstance(next_renewal, datetime) else None
                if nr:
                    days = max(0, (nr - _utcnow()).days)
            return days, status
        except Exception:
            return None, None

    @classmethod
    def _empty_dashboard(
        cls,
        tenant_id: UUID,
        platform_ready: bool,
        north_star_goal: str | None,
    ) -> CustomerSuccessJourneyDashboard:
        empty_success = CustomerSuccessJourneyRuleEngine.compute_success_score([], [], {})
        empty_renewal = CustomerSuccessJourneyRuleEngine.compute_renewal_readiness(
            None, 0, None, None, 0,
        )
        return CustomerSuccessJourneyDashboard(
            tenant_id=tenant_id,
            status="not_started",
            north_star_goal=north_star_goal,  # type: ignore[arg-type]
            north_star_label=_north_star_label(north_star_goal),
            platform_ready=platform_ready,
            journey_day=0,
            days_remaining=_JOURNEY_DAYS,
            success_score=empty_success,
            health_score=None,
            renewal_readiness=empty_renewal,
            generated_at=_utcnow(),
        )

    @classmethod
    async def _maybe_mark_platform_ready(
        cls,
        db: AsyncSession,
        progress: TenantOnboardingProgress,
        platform_ready: bool,
    ) -> datetime | None:
        if not platform_ready:
            return None
        if progress.platform_ready_at is None:
            progress.platform_ready_at = _utcnow()
            await db.flush()
        return _aware(progress.platform_ready_at)

    @classmethod
    async def _persist_journey_state(
        cls,
        journey: TenantCustomerSuccessJourney,
        checkpoints: list,
        timeline: list,
        weekly_wins: list,
    ) -> None:
        achieved: dict[str, str] = dict(journey.milestones_achieved or {})
        now = _utcnow()
        for cp in checkpoints:
            if cp.status == "achieved" and cp.id not in achieved:
                achieved[cp.id] = _iso(cp.achieved_at or now)

        journey.milestones_achieved = achieved
        journey.timeline_entries = [t.model_dump(mode="json") for t in timeline]
        journey.weekly_wins = [w.model_dump(mode="json") for w in weekly_wins]
        journey.last_refreshed_at = now

        current = "day_30"
        for cp_id in ("day_1", "day_3", "day_7", "day_14", "day_30"):
            if cp_id not in achieved:
                current = cp_id
                break
        journey.current_checkpoint = current

        started = _aware(journey.started_at)
        if started and (_utcnow() - started).days >= _JOURNEY_DAYS and achieved.get("day_30"):
            journey.status = "completed"
            journey.completed_at = journey.completed_at or now

    @classmethod
    async def dashboard(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        persist: bool = True,
    ) -> CustomerSuccessJourneyDashboard:
        progress = await cls._get_progress(db, tenant_id)
        readiness = await OnboardingReadinessService.evaluate(db, tenant_id, progress)
        north_star = progress.north_star_goal

        if not readiness.platform_ready:
            return cls._empty_dashboard(tenant_id, False, north_star)

        platform_ready_at = await cls._maybe_mark_platform_ready(
            db, progress, readiness.platform_ready,
        )
        journey = await cls._ensure_journey(
            db, tenant_id, readiness.platform_ready, platform_ready_at,
        )
        if journey is None:
            return cls._empty_dashboard(tenant_id, True, north_star)

        signals = await cls._gather_journey_signals(db, tenant_id, progress)
        since_30d = signals["since_30d"]
        period_activity = await CustomerSuccessService._count_period_activity(
            db, tenant_id, since_30d,
        )
        logins_30d, active_users, total_users = await CustomerSuccessService._user_adoption(
            db, tenant_id,
        )
        adoption = CustomerSuccessService._build_adoption(
            logins_30d, active_users, total_users, period_activity,
            signals["content_items"], signals["comm_messages"],
            await GrowthCenterService._load_buyers(db, tenant_id),
        )
        health_score: CustomerSuccessHealthScore = CustomerSuccessService._build_health_score(adoption)

        journey_day = cls._journey_day(journey.started_at)
        dismissed = set(journey.dismissed_recommendations or [])
        prior_achieved = dict(journey.milestones_achieved or {})

        for cp_id, ts in prior_achieved.items():
            if cp_id in CHECKPOINT_DAYS and journey_day >= CHECKPOINT_DAYS[cp_id]:
                pass

        ctx = JourneyRuleContext(
            journey_day=journey_day,
            north_star_goal=north_star,  # type: ignore[arg-type]
            signals=signals,
            adoption=adoption,
            engagement_score=adoption.engagement_score,
            pipeline_value=signals.get("pipeline_value", Decimal("0")),
            roi_measurable=signals.get("leads_count", 0) >= 3,
            dismissed_ids=dismissed,
        )

        checkpoints = CustomerSuccessJourneyRuleEngine.evaluate_checkpoints(ctx, prior_achieved)
        for cp in checkpoints:
            if cp.status == "achieved" and not cp.achieved_at and cp.id in prior_achieved:
                cp.achieved_at = datetime.fromisoformat(
                    prior_achieved[cp.id].replace("Z", "+00:00"),
                )

        features = CustomerSuccessJourneyRuleEngine.evaluate_features(ctx)
        recommendations = CustomerSuccessJourneyRuleEngine.build_recommendations(ctx)
        for rec in recommendations:
            rec.dismissed = rec.id in dismissed

        since_week = _utcnow() - timedelta(days=7)
        weekly_wins = CustomerSuccessJourneyRuleEngine.build_weekly_wins(ctx, since_week)
        prior_timeline = list(journey.timeline_entries or [])
        timeline = CustomerSuccessJourneyRuleEngine.build_timeline_entries(
            checkpoints, features, weekly_wins, prior_timeline,
        )

        success_score = CustomerSuccessJourneyRuleEngine.compute_success_score(
            checkpoints, features, signals,
        )
        milestone_pct = success_score.checkpoint_completion_pct
        days_to_renewal, sub_status = await cls._renewal_context(db, tenant_id)
        renewal = CustomerSuccessJourneyRuleEngine.compute_renewal_readiness(
            health_score.score, milestone_pct, days_to_renewal, sub_status, logins_30d,
        )

        plan_usage = await cls._plan_usage_pct(db, tenant_id)
        unused = [f.label for f in features if not f.adopted][:3]
        expansion = CustomerSuccessJourneyRuleEngine.compute_expansion_opportunities(
            ctx, plan_usage, unused,
        )

        if persist:
            await cls._persist_journey_state(journey, checkpoints, timeline, weekly_wins)
            await db.commit()

        days_remaining = max(0, _JOURNEY_DAYS - journey_day)
        status = journey.status
        if status == "not_started":
            status = "active"

        logger.info(
            "%s dashboard tenant=%s day=%s success=%s health=%s",
            MARKER, tenant_id, journey_day, success_score.score, health_score.score,
        )

        return CustomerSuccessJourneyDashboard(
            tenant_id=tenant_id,
            status=status,  # type: ignore[arg-type]
            north_star_goal=north_star,  # type: ignore[arg-type]
            north_star_label=_north_star_label(north_star),
            platform_ready=True,
            journey_day=journey_day,
            days_remaining=days_remaining,
            started_at=journey.started_at,
            current_checkpoint=journey.current_checkpoint,
            checkpoints=checkpoints,
            features=features,
            recommendations=recommendations,
            weekly_wins=weekly_wins,
            timeline=timeline,
            success_score=success_score,
            health_score=health_score,
            renewal_readiness=renewal,
            expansion_opportunities=expansion,
            generated_at=_utcnow(),
        )

    @classmethod
    async def refresh(cls, db: AsyncSession, tenant_id: UUID) -> JourneyRefreshResponse:
        journey = await cls.dashboard(db, tenant_id, persist=True)
        return JourneyRefreshResponse(refreshed=True, journey=journey)

    @classmethod
    async def dismiss_recommendation(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        recommendation_id: str,
    ) -> JourneyDismissRecommendationResponse:
        record = await cls._get_journey(db, tenant_id)
        if record is None:
            journey = await cls.dashboard(db, tenant_id, persist=True)
        else:
            dismissed = list(record.dismissed_recommendations or [])
            if recommendation_id not in dismissed:
                dismissed.append(recommendation_id)
            record.dismissed_recommendations = dismissed
            await db.commit()
            journey = await cls.dashboard(db, tenant_id, persist=False)
        return JourneyDismissRecommendationResponse(
            dismissed=True,
            recommendation_id=recommendation_id,
            journey=journey,
        )

    @classmethod
    async def admin_overview(cls, db: AsyncSession) -> JourneyAdminOverview:
        tenants = list((await db.execute(select(Tenant).where(Tenant.status == "active"))).scalars().all())
        items: list[JourneyAdminTenantItem] = []
        active = completed = at_risk = 0
        now = _utcnow()

        for tenant in tenants:
            progress = (await db.execute(
                select(TenantOnboardingProgress).where(
                    TenantOnboardingProgress.tenant_id == tenant.id,
                ),
            )).scalar_one_or_none()
            if progress is None:
                continue

            readiness = await OnboardingReadinessService.evaluate(db, tenant.id, progress)
            if not readiness.platform_ready:
                continue

            journey_rec = await cls._get_journey(db, tenant.id)
            dash = await cls.dashboard(db, tenant.id, persist=False)

            if dash.status == "active":
                active += 1
            elif dash.status == "completed":
                completed += 1

            days_since_login: int | None = None
            last_login = (await db.execute(
                select(func.max(TenantUser.last_login_at)).where(
                    TenantUser.tenant_id == tenant.id,
                    TenantUser.status == "active",
                ),
            )).scalar()
            if last_login:
                ll = _aware(last_login)
                if ll:
                    days_since_login = (now - ll).days

            health_val = dash.health_score.score if dash.health_score else None
            risky = (
                (health_val is not None and health_val < 45)
                or (days_since_login is not None and days_since_login > 14)
                or dash.success_score.score < 35
            )
            if risky:
                at_risk += 1

            items.append(JourneyAdminTenantItem(
                tenant_id=tenant.id,
                tenant_name=tenant.company_name,
                journey_status=dash.status,
                journey_day=dash.journey_day,
                north_star_goal=dash.north_star_goal,
                success_score=dash.success_score.score,
                health_score=health_val,
                current_checkpoint=journey_rec.current_checkpoint if journey_rec else dash.current_checkpoint,
                at_risk=risky,
                days_since_login=days_since_login,
            ))

        items.sort(key=lambda i: (-int(i.at_risk), -i.journey_day))
        return JourneyAdminOverview(
            total_tenants=len(tenants),
            active_journeys=active,
            completed_journeys=completed,
            at_risk_count=at_risk,
            tenants=items,
            generated_at=now,
        )
