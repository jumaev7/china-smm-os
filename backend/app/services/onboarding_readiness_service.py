"""Onboarding readiness engine — platform vs business metrics, first-success milestones."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_crm import Buyer
from app.models.client import Client
from app.models.content import ContentItem
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.media import MediaFile
from app.models.product import Product
from app.models.publishing_account import PublishingAccount
from app.models.sales_crm import SalesDeal, SalesLead, SalesProposal
from app.models.tenant import TenantUser
from app.models.tenant_onboarding import TenantOnboardingProgress
from app.schemas.tenant_onboarding import (
    ExecutiveWalkthroughPanel,
    ExecutiveWalkthroughState,
    FirstSuccessSummary,
    OnboardingReadinessResponse,
    OnboardingStepReadiness,
)
from app.services.tenant_operations_service import ACTIVE_ACCOUNT_STATUSES, TenantOperationsService
from app.services.tenant_service import TenantService

ONBOARDING_AUTO_CONFIG_MARKER = "[OnboardingAutoConfig]"

StepStatus = Literal["completed", "missing", "recommended", "blocked"]
StepCategory = Literal["platform", "business", "first_success"]

_LEGACY_STEP_ALIASES: dict[str, str] = {
    "company_profile": "company_info",
    "first_content": "first_ai_content",
    "growth_center_viewed": "executive_walkthrough",
}


@dataclass(frozen=True)
class _StepDef:
    id: str
    label: str
    category: StepCategory
    route: str
    estimated_minutes: int
    weight: int
    required: bool
    legacy_ids: tuple[str, ...] = ()
    why_it_matters: str = ""
    next_action: str = ""
    business_value: str = ""
    blocked_by: tuple[str, ...] = ()


EXECUTIVE_WALKTHROUGH_PANEL_DEFS: tuple[tuple[str, str, str, int], ...] = (
    ("executive_dashboard", "Executive Dashboard", "/dashboard", 2),
    ("crm_pipeline", "CRM Pipeline", "/crm-pipeline", 3),
    ("publishing", "Publishing Hub", "/publishing", 2),
    ("content", "Content Studio", "/content", 2),
    ("growth_center", "Growth Center", "/growth-center", 2),
)

PLATFORM_STEP_DEFS: tuple[_StepDef, ...] = (
    _StepDef(
        "company_info", "Company information", "platform", "/onboarding/company", 3, 10, True,
        legacy_ids=("company_profile",),
        why_it_matters="Buyers and AI tools need your factory identity to personalize outreach.",
        next_action="Complete your company name, location, and contact details.",
        business_value="Professional presence that powers catalog pages and proposals.",
    ),
    _StepDef(
        "industry_selection", "Industry selection", "platform", "/onboarding/industry", 2, 8, True,
        why_it_matters="Industry drives content templates, buyer matching, and KPI benchmarks.",
        next_action="Select your primary manufacturing category.",
        business_value="Sharper AI content and more relevant buyer recommendations.",
    ),
    _StepDef(
        "logo_branding", "Logo & branding", "platform", "/onboarding/branding", 3, 7, True,
        why_it_matters="Visual identity appears on proposals, content, and your factory profile.",
        next_action="Upload your logo or set brand colors on your profile.",
        business_value="Consistent brand recognition across every buyer touchpoint.",
    ),
    _StepDef(
        "team_members", "Team members", "platform", "/onboarding/team", 5, 4, False,
        why_it_matters="Sales and operations teammates can collaborate on leads and content.",
        next_action="Invite a colleague or add a team member.",
        business_value="Faster response times and shared pipeline visibility.",
    ),
    _StepDef(
        "telegram_connected", "Connect Telegram", "platform", "/onboarding/channels", 5, 9, True,
        legacy_ids=("telegram_connected",),
        why_it_matters="Telegram ingests factory photos and buyer inquiries automatically.",
        next_action="Add the bot to your Telegram group and link it to your workspace.",
        business_value="Hands-free content intake and real-time buyer messages.",
    ),
    _StepDef(
        "facebook_connected", "Connect Facebook", "platform", "/onboarding/channels/facebook", 3, 8, True,
        blocked_by=("telegram_connected",),
        why_it_matters="Facebook is required for cross-posting and Meta Business integration.",
        next_action="Connect your Meta account on the Publishing page.",
        business_value="Reach export buyers on the largest social commerce network.",
    ),
    _StepDef(
        "instagram_connected", "Connect Instagram", "platform", "/onboarding/channels/instagram", 2, 8, True,
        blocked_by=("facebook_connected",),
        why_it_matters="Required for automatic publishing to Instagram.",
        next_action="Complete Meta OAuth — Instagram links through your Facebook page.",
        business_value="Visual product discovery for international buyers.",
    ),
    _StepDef(
        "wechat_placeholder", "Connect WeChat", "platform", "/onboarding/channels/wechat", 1, 2, False,
        why_it_matters="WeChat connects you to Chinese domestic buyer networks.",
        next_action="WeChat integration is coming soon — no action required today.",
        business_value="Future access to the largest B2B channel in China.",
    ),
    _StepDef(
        "products_imported", "Import products", "platform", "/onboarding/products", 8, 9, True,
        why_it_matters="Your catalog powers AI content, proposals, and buyer outreach.",
        next_action="Upload a product spreadsheet or add items manually.",
        business_value="Faster quotes and richer product storytelling.",
    ),
    _StepDef(
        "first_ai_content", "Generate first AI content", "platform", "/onboarding/content", 5, 9, True,
        legacy_ids=("first_content",),
        why_it_matters="AI content proves the publishing workflow before you go live.",
        next_action="Upload media and generate captions with AI.",
        business_value="First export-ready post in minutes, not hours.",
    ),
    _StepDef(
        "publishing_readiness", "Review publishing readiness", "platform", "/onboarding/publishing", 3, 8, True,
        why_it_matters="Confirms destinations, accounts, and schedule are ready to publish.",
        next_action="Review connected accounts and scheduled content.",
        business_value="Confidence that posts will reach buyers on time.",
    ),
    _StepDef(
        "executive_walkthrough", "Executive dashboard tour", "platform", "/onboarding/executive", 5, 10, True,
        legacy_ids=("growth_center_viewed",),
        why_it_matters="Learn where pipeline KPIs, publishing, and growth insights live.",
        next_action="Complete the guided tour of major platform areas.",
        business_value="Leadership visibility from day one.",
    ),
)

BUSINESS_STEP_DEFS: tuple[_StepDef, ...] = (
    _StepDef(
        "first_lead", "First lead captured", "business", "/onboarding/crm", 4, 12, True,
        legacy_ids=("first_lead",),
        why_it_matters="Leads are the top of your export sales funnel.",
        next_action="Add your first inbound lead with company and contact details.",
        business_value="Pipeline tracking starts with the first inquiry.",
    ),
    _StepDef(
        "first_buyer", "First buyer profile", "business", "/onboarding/crm", 4, 10, True,
        legacy_ids=("first_buyer",),
        why_it_matters="Buyer profiles store relationship history and deal context.",
        next_action="Create a buyer record for an interested company.",
        business_value="Repeatable relationship management for key accounts.",
    ),
    _StepDef(
        "first_deal", "First deal in pipeline", "business", "/onboarding/crm", 5, 13, True,
        legacy_ids=("first_deal",),
        why_it_matters="Deals track revenue through the 12-stage executive pipeline.",
        next_action="Create a deal and assign it to a pipeline stage.",
        business_value="Forecast revenue and spot stalled opportunities early.",
    ),
    _StepDef(
        "first_proposal", "First commercial proposal", "business", "/onboarding/proposal", 6, 15, True,
        legacy_ids=("first_proposal",),
        why_it_matters="Proposals convert interest into signed export orders.",
        next_action="Generate or create your first proposal for a buyer.",
        business_value="Professional quotes that accelerate deal closure.",
    ),
)

FIRST_SUCCESS_STEP_DEFS: tuple[_StepDef, ...] = (
    _StepDef(
        "first_published_content", "First published content", "first_success", "/content", 5, 25, True,
        why_it_matters="Publishing proves your channels work end-to-end.",
        next_action="Approve and publish your first post to a connected channel.",
        business_value="Live proof of export marketing automation.",
    ),
    _StepDef(
        "first_generated_proposal", "First generated proposal", "first_success", "/proposals", 8, 25, True,
        why_it_matters="A real proposal shows buyers you can close professionally.",
        next_action="Generate a proposal from the Sales section.",
        business_value="Faster turnaround on buyer RFQs.",
    ),
    _StepDef(
        "first_connected_social", "First connected social account", "first_success", "/publishing", 3, 25, True,
        why_it_matters="A live social connection unlocks automated distribution.",
        next_action="Complete OAuth for Facebook, Instagram, or Telegram publish.",
        business_value="Multi-channel reach without manual posting.",
    ),
    _StepDef(
        "first_real_lead", "First inbound lead", "first_success", "/crm-pipeline", 4, 25, True,
        why_it_matters="A real lead validates your intake channels are working.",
        next_action="Capture a lead from Telegram, CRM, or manual entry.",
        business_value="Measurable pipeline growth from day one.",
    ),
)

ALL_STEP_DEFS = PLATFORM_STEP_DEFS + BUSINESS_STEP_DEFS + FIRST_SUCCESS_STEP_DEFS
_STEP_BY_ID = {s.id: s for s in ALL_STEP_DEFS}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_completed_keys(steps_completed: dict[str, str] | None) -> set[str]:
    keys: set[str] = set()
    for key in (steps_completed or {}):
        keys.add(key)
        if key in _LEGACY_STEP_ALIASES:
            keys.add(_LEGACY_STEP_ALIASES[key])
        for legacy, modern in _LEGACY_STEP_ALIASES.items():
            if key == modern:
                keys.add(legacy)
    return keys


class OnboardingReadinessService:
    @staticmethod
    def walkthrough_panels(progress: TenantOnboardingProgress) -> ExecutiveWalkthroughState:
        raw = progress.executive_walkthrough_progress or {}
        completed_ids = list(raw.get("completed_panels") or [])
        panels: list[ExecutiveWalkthroughPanel] = []
        for panel_id, label, route, minutes in EXECUTIVE_WALKTHROUGH_PANEL_DEFS:
            panels.append(ExecutiveWalkthroughPanel(
                id=panel_id,
                label=label,
                route=route,
                estimated_minutes=minutes,
                completed=panel_id in completed_ids,
            ))
        total = len(EXECUTIVE_WALKTHROUGH_PANEL_DEFS)
        done = sum(1 for p in panels if p.completed)
        return ExecutiveWalkthroughState(
            panels=panels,
            completed_panels=done,
            total_panels=total,
            completed=done >= total,
        )

    @staticmethod
    async def _gather_signals(
        db: AsyncSession,
        tenant_id: UUID,
        progress: TenantOnboardingProgress,
    ) -> dict[str, Any]:
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        clients: list[Client] = []
        if client_ids:
            clients = list(
                (await db.execute(select(Client).where(Client.id.in_(client_ids)))).scalars().all()
            )

        profile = (await db.execute(
            select(FactoryPlatformProfile).where(FactoryPlatformProfile.tenant_id == tenant_id),
        )).scalar_one_or_none()
        company_data = progress.company_profile or {}

        team_count = int(
            (await db.execute(
                select(func.count()).select_from(TenantUser).where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.status == "active",
                ),
            )).scalar() or 0,
        )

        publishing_accounts = list(
            (await db.execute(
                select(PublishingAccount).where(
                    PublishingAccount.tenant_id == tenant_id,
                    PublishingAccount.status.in_(tuple(ACTIVE_ACCOUNT_STATUSES)),
                ),
            )).scalars().all()
        )
        accounts_by_platform = {a.platform: a for a in publishing_accounts}

        product_count = 0
        content_count = 0
        ai_content_count = 0
        published_count = 0
        if client_ids:
            product_count = int(
                (await db.execute(
                    select(func.count()).select_from(Product).where(Product.client_id.in_(client_ids)),
                )).scalar() or 0,
            )
            content_count = int(
                (await db.execute(
                    select(func.count()).select_from(ContentItem).where(ContentItem.client_id.in_(client_ids)),
                )).scalar() or 0,
            )
            ai_content_count = int(
                (await db.execute(
                    select(func.count()).select_from(ContentItem).where(
                        ContentItem.client_id.in_(client_ids),
                        or_(
                            ContentItem.internal_notes.ilike("%AI%"),
                            ContentItem.internal_notes.ilike("%generate%"),
                            ContentItem.caption_short_en.isnot(None),
                        ),
                    ),
                )).scalar() or 0,
            )
            published_count = int(
                (await db.execute(
                    select(func.count()).select_from(ContentItem).where(
                        ContentItem.client_id.in_(client_ids),
                        or_(
                            ContentItem.published_at.isnot(None),
                            ContentItem.status == "published",
                        ),
                        ~ContentItem.internal_notes.ilike(f"%{ONBOARDING_AUTO_CONFIG_MARKER}%"),
                    ),
                )).scalar() or 0,
            )

        media_logo = False
        if client_ids:
            logo_media = int(
                (await db.execute(
                    select(func.count()).select_from(MediaFile).where(
                        MediaFile.client_id.in_(client_ids),
                        MediaFile.original_filename.ilike("%logo%"),
                    ),
                )).scalar() or 0,
            )
            media_logo = logo_media > 0

        has_logo = bool(
            (profile and profile.logo_url)
            or any((c.logo_url or "").strip() for c in clients)
            or media_logo
        )

        lead_count = int(
            (await db.execute(
                select(func.count()).select_from(SalesLead).where(
                    SalesLead.tenant_id == tenant_id,
                    ~or_(
                        SalesLead.notes.ilike(f"%{ONBOARDING_AUTO_CONFIG_MARKER}%"),
                        SalesLead.notes.ilike("%[Onboarding Demo]%"),
                        SalesLead.notes.ilike("%[DEMO_TENANT_SEED]%"),
                    ),
                ),
            )).scalar() or 0,
        )
        deal_count = int(
            (await db.execute(
                select(func.count()).select_from(SalesDeal).where(
                    SalesDeal.tenant_id == tenant_id,
                    ~or_(
                        SalesDeal.notes.ilike(f"%{ONBOARDING_AUTO_CONFIG_MARKER}%"),
                        SalesDeal.notes.ilike("%[Onboarding Demo]%"),
                    ),
                ),
            )).scalar() or 0,
        )
        buyer_count = int(
            (await db.execute(
                select(func.count()).select_from(Buyer).where(
                    Buyer.tenant_id == tenant_id,
                    ~Buyer.notes.ilike("%[Onboarding Demo]%"),
                ),
            )).scalar() or 0,
        )
        proposal_count = int(
            (await db.execute(
                select(func.count()).select_from(SalesProposal).where(
                    SalesProposal.tenant_id == tenant_id,
                    ~or_(
                        SalesProposal.notes.ilike(f"%{ONBOARDING_AUTO_CONFIG_MARKER}%"),
                        SalesProposal.notes.ilike("%[Onboarding Demo]%"),
                    ),
                ),
            )).scalar() or 0,
        )
        user_proposal_count = proposal_count

        telegram_connected = any(
            bool(c.telegram_group_id or c.telegram_id) for c in clients
        )
        facebook_connected = "facebook" in accounts_by_platform
        instagram_connected = "instagram" in accounts_by_platform
        social_connected = bool(publishing_accounts) or any(
            bool((c.telegram_publish_chat_id or "").strip()) for c in clients
        )

        publishing_readiness = await TenantOperationsService._publishing_readiness(
            db, tenant_id, clients,
        )
        publishing_ok = (
            len(publishing_readiness.get("connected_accounts") or []) > 0
            and content_count > 0
        )

        walkthrough = OnboardingReadinessService.walkthrough_panels(progress)
        walkthrough_done = walkthrough.completed

        return {
            "company_info": bool(
                (profile and profile.company_name and profile.country)
                or company_data.get("company_name"),
            ),
            "industry_selection": bool(
                (profile and profile.industry)
                or company_data.get("industry"),
            ),
            "logo_branding": has_logo,
            "team_members": team_count >= 2,
            "telegram_connected": telegram_connected,
            "facebook_connected": facebook_connected,
            "instagram_connected": instagram_connected,
            "wechat_placeholder": False,
            "products_imported": product_count > 0,
            "first_ai_content": ai_content_count > 0 or content_count > 0,
            "publishing_readiness": publishing_ok,
            "executive_walkthrough": walkthrough_done,
            "first_lead": lead_count > 0,
            "first_buyer": buyer_count > 0,
            "first_deal": deal_count > 0,
            "first_proposal": proposal_count > 0,
            "first_published_content": published_count > 0,
            "first_generated_proposal": user_proposal_count > 0,
            "first_connected_social": social_connected,
            "first_real_lead": lead_count > 0,
            "publishing_blockers": publishing_readiness.get("blockers") or [],
        }

    @staticmethod
    def _resolve_status(
        step: _StepDef,
        completed_keys: set[str],
        signals: dict[str, Any],
    ) -> StepStatus:
        if step.id in completed_keys or signals.get(step.id):
            return "completed"
        for legacy in step.legacy_ids:
            if legacy in completed_keys:
                return "completed"

        for blocker_id in step.blocked_by:
            blocker_done = signals.get(blocker_id) or blocker_id in completed_keys
            if not blocker_done:
                return "blocked"

        if not step.required:
            return "recommended"
        return "missing"

    @staticmethod
    def _step_readiness(
        step: _StepDef,
        completed_keys: set[str],
        signals: dict[str, Any],
        steps_completed: dict[str, str],
    ) -> OnboardingStepReadiness:
        status = OnboardingReadinessService._resolve_status(step, completed_keys, signals)
        ts_key = step.id
        completed_at = _parse_ts(steps_completed.get(ts_key))
        if not completed_at:
            for legacy in step.legacy_ids:
                completed_at = _parse_ts(steps_completed.get(legacy))
                if completed_at:
                    break
        if status == "completed" and not completed_at:
            completed_at = _utcnow()

        return OnboardingStepReadiness(
            id=step.id,
            label=step.label,
            category=step.category,
            status=status,
            route=step.route,
            estimated_minutes=step.estimated_minutes,
            weight=step.weight,
            required=step.required,
            completed_at=completed_at if status == "completed" else None,
            why_it_matters=step.why_it_matters,
            next_action=step.next_action,
            business_value=step.business_value,
        )

    @staticmethod
    def _percent(steps: list[OnboardingStepReadiness]) -> int:
        total_weight = sum(s.weight for s in steps if s.required)
        if total_weight == 0:
            return 100
        earned = 0.0
        for step in steps:
            if not step.required:
                if step.status == "completed":
                    earned += step.weight * 0.5
                continue
            if step.status == "completed":
                earned += step.weight
        return min(100, round(earned / total_weight * 100))

    @staticmethod
    def _minutes_remaining(steps: list[OnboardingStepReadiness]) -> int:
        return sum(
            s.estimated_minutes
            for s in steps
            if s.status in ("missing", "blocked")
        )

    @staticmethod
    def _first_success_summary(
        steps: list[OnboardingStepReadiness],
        platform_ready: bool,
        state: dict[str, Any],
    ) -> FirstSuccessSummary | None:
        if not platform_ready:
            return None
        achieved = sum(1 for s in steps if s.status == "completed")
        return FirstSuccessSummary(
            achieved_count=achieved,
            total_count=len(steps),
            percent=round(achieved / len(steps) * 100) if steps else 0,
            milestones=steps,
            celebrated=bool(state.get("celebrated")),
        )

    @staticmethod
    async def evaluate(
        db: AsyncSession,
        tenant_id: UUID,
        progress: TenantOnboardingProgress,
    ) -> OnboardingReadinessResponse:
        signals = await OnboardingReadinessService._gather_signals(db, tenant_id, progress)
        completed_keys = _normalize_completed_keys(progress.steps_completed)
        steps_completed = dict(progress.steps_completed or {})

        platform_steps = [
            OnboardingReadinessService._step_readiness(s, completed_keys, signals, steps_completed)
            for s in PLATFORM_STEP_DEFS
        ]
        business_steps = [
            OnboardingReadinessService._step_readiness(s, completed_keys, signals, steps_completed)
            for s in BUSINESS_STEP_DEFS
        ]

        platform_ready = all(
            s.status == "completed"
            for s in platform_steps
            if s.required
        )

        first_success_steps = [
            OnboardingReadinessService._step_readiness(s, completed_keys, signals, steps_completed)
            for s in FIRST_SUCCESS_STEP_DEFS
        ]
        if not platform_ready:
            first_success_steps = [
                step.model_copy(update={"status": "missing", "completed_at": None})
                if step.status != "completed"
                else step
                for step in first_success_steps
            ]

        platform_percent = OnboardingReadinessService._percent(platform_steps)
        business_percent = OnboardingReadinessService._percent(business_steps)

        if not platform_ready:
            overall = platform_percent
            minutes = OnboardingReadinessService._minutes_remaining(platform_steps)
        else:
            overall = round(platform_percent * 0.5 + business_percent * 0.5)
            minutes = OnboardingReadinessService._minutes_remaining(
                [s for s in business_steps if s.required]
                + [s for s in first_success_steps if s.status != "completed"],
            )

        all_incomplete = (
            [s for s in platform_steps if s.status in ("missing", "blocked")]
            if not platform_ready
            else [s for s in business_steps if s.status in ("missing", "blocked")]
            + [s for s in first_success_steps if s.status in ("missing", "blocked")]
        )
        next_step = all_incomplete[0] if all_incomplete else None

        first_success = OnboardingReadinessService._first_success_summary(
            first_success_steps,
            platform_ready,
            progress.first_success_state or {},
        )

        goal = progress.north_star_goal
        goal_labels = {
            "export_leads": "More export leads",
            "better_publishing": "Better publishing",
            "more_buyers": "More buyers",
            "better_sales_pipeline": "Better sales pipeline",
            "brand_awareness": "Brand awareness",
        }

        return OnboardingReadinessResponse(
            tenant_id=tenant_id,
            platform_readiness_percent=platform_percent,
            business_readiness_percent=business_percent,
            overall_percent=overall,
            estimated_minutes_remaining=minutes,
            platform_ready=platform_ready,
            platform_steps=platform_steps,
            business_steps=business_steps,
            first_success=first_success,
            next_step=next_step,
            executive_walkthrough=OnboardingReadinessService.walkthrough_panels(progress),
            publishing_blockers=list(signals.get("publishing_blockers") or []),
            auto_config_applied=bool(progress.auto_config_applied),
            last_activity_at=progress.last_activity_at,
            onboarding_version=progress.onboarding_version or 2,
            north_star_goal=goal,
            north_star_label=goal_labels.get(goal) if goal else None,
        )

    @staticmethod
    async def sync_progress(
        db: AsyncSession,
        tenant_id: UUID,
        progress: TenantOnboardingProgress,
    ) -> OnboardingReadinessResponse:
        """Refresh detectors, persist step timestamps and readiness percentages."""
        readiness = await OnboardingReadinessService.evaluate(db, tenant_id, progress)
        now = _utcnow()
        steps_completed = dict(progress.steps_completed or {})

        for step in (
            readiness.platform_steps
            + readiness.business_steps
            + (readiness.first_success.milestones if readiness.first_success else [])
        ):
            if step.status == "completed" and step.id not in steps_completed:
                steps_completed[step.id] = (step.completed_at or now).isoformat()

        progress.steps_completed = steps_completed
        progress.platform_readiness_percent = readiness.platform_readiness_percent
        progress.business_readiness_percent = readiness.business_readiness_percent
        progress.progress_percent = readiness.overall_percent

        required_platform = [s for s in readiness.platform_steps if s.required]
        required_business = [s for s in readiness.business_steps if s.required]
        platform_done = all(s.status == "completed" for s in required_platform)
        business_done = all(s.status == "completed" for s in required_business)

        if platform_done and business_done:
            progress.status = "completed"
            if not progress.completed_at:
                progress.completed_at = now
        elif platform_done:
            progress.status = "in_progress"
        elif any(s.status == "completed" for s in readiness.platform_steps):
            progress.status = "in_progress"
            if not progress.started_at:
                progress.started_at = now
        elif progress.status == "not_started" and steps_completed:
            progress.status = "in_progress"
            if not progress.started_at:
                progress.started_at = now

        progress.last_activity_at = now
        progress.onboarding_version = 2
        await db.flush()
        return readiness

    @staticmethod
    async def record_walkthrough_panel(
        db: AsyncSession,
        tenant_id: UUID,
        progress: TenantOnboardingProgress,
        panel_id: str,
    ) -> OnboardingReadinessResponse:
        valid_ids = {p[0] for p in EXECUTIVE_WALKTHROUGH_PANEL_DEFS}
        if panel_id not in valid_ids:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=f"Unknown walkthrough panel: {panel_id}")

        raw = dict(progress.executive_walkthrough_progress or {})
        completed = list(raw.get("completed_panels") or [])
        if panel_id not in completed:
            completed.append(panel_id)
        raw["completed_panels"] = completed
        raw["last_panel_at"] = _utcnow().isoformat()
        progress.executive_walkthrough_progress = raw
        await db.flush()
        return await OnboardingReadinessService.sync_progress(db, tenant_id, progress)
