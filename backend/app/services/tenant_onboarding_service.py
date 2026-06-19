"""Factory tenant onboarding — progress tracking, auto-detection, and assistant."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.buyer_crm import Buyer
from app.models.client import Client
from app.models.content import ContentItem
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.media import MediaFile
from app.models.sales_crm import SalesDeal, SalesLead, SalesProposal
from app.models.tenant import Tenant
from app.models.tenant_onboarding import TenantOnboardingProgress
from app.schemas.tenant_onboarding import (
    OnboardingAdminAnalytics,
    OnboardingAdminTenantItem,
    OnboardingAssistantResponse,
    OnboardingChannelStatus,
    OnboardingCompanyProfile,
    OnboardingDashboardResponse,
    OnboardingMilestoneMessage,
    OnboardingStepItem,
)
from app.services.ai_service import _validate_api_key, get_openai
from app.services.factory_profile_service import FactoryProfileService
from app.services.tenant_onboarding_demo_service import TenantOnboardingDemoService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

CHECKLIST_STEPS: tuple[tuple[str, str, str, int], ...] = (
    ("company_profile", "Company profile completed", "/onboarding/company", 5),
    ("telegram_connected", "Telegram connected", "/onboarding/channels", 8),
    ("first_content", "First content uploaded", "/onboarding/content", 10),
    ("first_lead", "First lead created", "/onboarding/crm", 5),
    ("first_buyer", "First buyer created", "/onboarding/crm", 5),
    ("first_deal", "First deal created", "/onboarding/crm", 5),
    ("first_proposal", "First proposal created", "/onboarding/proposal", 8),
    ("growth_center_viewed", "Growth Center viewed", "/onboarding/growth-center", 3),
)

TOTAL_STEPS = len(CHECKLIST_STEPS)

MILESTONE_MESSAGES: dict[str, str] = {
    "company_profile": "Your company profile is set up.",
    "telegram_connected": "Telegram is connected to your workspace.",
    "first_content": "Your first content item is ready.",
    "first_lead": "Your first lead has been created.",
    "first_buyer": "Your first buyer is now in the system.",
    "first_deal": "Your first deal is tracking in the pipeline.",
    "first_proposal": "Your first proposal is ready.",
    "growth_center_viewed": "Your business dashboard is active.",
}

_RULE_GUIDANCE: list[tuple[re.Pattern[str], str, str | None]] = [
    (re.compile(r"what should i do next|next step|where (do i )?start", re.I),
     "Check your onboarding dashboard for the next recommended step. Complete company profile first, then connect Telegram and upload your first content.",
     "/onboarding"),
    (re.compile(r"upload content|create (a )?post|first content|media upload", re.I),
     "Go to Content or Media Library, upload a photo or video, then create a draft post. You can use AI to generate captions from the content page.",
     "/onboarding/content"),
    (re.compile(r"create (a )?buyer|add buyer|buyer network", re.I),
     "Open Buyers from the Sales section or complete the CRM onboarding step to create your first buyer profile.",
     "/onboarding/crm"),
    (re.compile(r"create (a )?lead|add lead|first lead", re.I),
     "Use Sales CRM → Leads or the onboarding CRM step to add your first lead with company and contact details.",
     "/onboarding/crm"),
    (re.compile(r"proposal|commercial offer|quote", re.I),
     "Create a proposal from Sales → Proposals or the onboarding proposal step. Link it to an existing buyer or deal.",
     "/onboarding/proposal"),
    (re.compile(r"telegram|connect channel|group", re.I),
     "Add the bot to your Telegram group and link it to your client profile. See the Channels onboarding step for the connection guide.",
     "/onboarding/channels"),
    (re.compile(r"growth center|kpi|dashboard|metrics", re.I),
     "Open Growth Center to see pipeline KPIs, buyer health, and AI recommendations aggregated from your CRM and communications.",
     "/onboarding/growth-center"),
    (re.compile(r"demo|sample data|try example", re.I),
     "Use the one-click Demo Environment on the onboarding dashboard to populate sample buyers, leads, deals, and communications.",
     "/onboarding"),
]

_ASSISTANT_SYSTEM = """\
You are the Factory Onboarding Assistant for China SMM OS — a B2B platform helping \
Chinese factories find buyers, manage content, and close sales in Central Asia and globally.

Answer concisely (2-4 sentences). Guide users through onboarding steps:
company profile → Telegram → content → CRM (leads/buyers/deals) → proposals → Growth Center.

If unsure, suggest visiting /onboarding dashboard.
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return round((end - start).total_seconds() / 3600, 2)


class TenantOnboardingService:
    @staticmethod
    async def get_or_create_progress(db: AsyncSession, tenant_id: UUID) -> TenantOnboardingProgress:
        result = await db.execute(
            select(TenantOnboardingProgress).where(TenantOnboardingProgress.tenant_id == tenant_id),
        )
        row = result.scalar_one_or_none()
        if row:
            return row
        row = TenantOnboardingProgress(
            tenant_id=tenant_id,
            status="not_started",
            progress_percent=0,
            steps_completed={},
            milestone_messages=[],
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def _detect_step_completion(
        db: AsyncSession,
        tenant_id: UUID,
        progress: TenantOnboardingProgress,
    ) -> dict[str, datetime]:
        now = _utcnow()
        detected: dict[str, datetime] = {}

        profile = (await db.execute(
            select(FactoryPlatformProfile).where(FactoryPlatformProfile.tenant_id == tenant_id),
        )).scalar_one_or_none()
        company_data = progress.company_profile or {}
        if (profile and profile.company_name and profile.industry and profile.country) or (
            company_data.get("company_name") and company_data.get("industry")
        ):
            detected["company_profile"] = now

        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        if client_ids:
            tg = (await db.execute(
                select(func.count()).select_from(Client).where(
                    Client.id.in_(client_ids),
                    (Client.telegram_group_id.isnot(None)) | (Client.telegram_id.isnot(None)),
                ),
            )).scalar_one()
            if tg > 0:
                detected["telegram_connected"] = now

            content_count = (await db.execute(
                select(func.count()).select_from(ContentItem).where(ContentItem.client_id.in_(client_ids)),
            )).scalar_one()
            media_count = (await db.execute(
                select(func.count()).select_from(MediaFile).where(MediaFile.client_id.in_(client_ids)),
            )).scalar_one()
            if content_count > 0 or media_count > 0:
                detected["first_content"] = now

        if (await db.execute(
            select(func.count()).select_from(SalesLead).where(SalesLead.tenant_id == tenant_id),
        )).scalar_one() > 0:
            detected["first_lead"] = now

        if (await db.execute(
            select(func.count()).select_from(Buyer).where(Buyer.tenant_id == tenant_id),
        )).scalar_one() > 0:
            detected["first_buyer"] = now

        if (await db.execute(
            select(func.count()).select_from(SalesDeal).where(SalesDeal.tenant_id == tenant_id),
        )).scalar_one() > 0:
            detected["first_deal"] = now

        if (await db.execute(
            select(func.count()).select_from(SalesProposal).where(SalesProposal.tenant_id == tenant_id),
        )).scalar_one() > 0:
            detected["first_proposal"] = now

        if progress.growth_center_viewed_at:
            detected["growth_center_viewed"] = progress.growth_center_viewed_at

        return detected

    @staticmethod
    def _build_steps(steps_completed: dict[str, str]) -> list[OnboardingStepItem]:
        items: list[OnboardingStepItem] = []
        for step_id, label, route, minutes in CHECKLIST_STEPS:
            ts = _parse_ts(steps_completed.get(step_id))
            items.append(OnboardingStepItem(
                id=step_id,
                label=label,
                completed=step_id in steps_completed,
                completed_at=ts,
                route=route,
                estimated_minutes=minutes,
            ))
        return items

    @staticmethod
    async def refresh_progress(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        return_new_milestones: bool = True,
    ) -> tuple[TenantOnboardingProgress, list[OnboardingMilestoneMessage]]:
        progress = await TenantOnboardingService.get_or_create_progress(db, tenant_id)
        detected = await TenantOnboardingService._detect_step_completion(db, tenant_id, progress)
        steps_completed: dict[str, str] = dict(progress.steps_completed or {})
        shown: set[str] = {
            m.get("step_id") for m in (progress.milestone_messages or []) if isinstance(m, dict)
        }
        new_milestones: list[OnboardingMilestoneMessage] = []
        now = _utcnow()

        for step_id, ts in detected.items():
            if step_id not in steps_completed:
                steps_completed[step_id] = ts.isoformat()
                if step_id == "first_content" and not progress.first_content_at:
                    progress.first_content_at = ts
                elif step_id == "first_lead" and not progress.first_lead_at:
                    progress.first_lead_at = ts
                elif step_id == "first_buyer" and not progress.first_buyer_at:
                    progress.first_buyer_at = ts
                elif step_id == "first_deal" and not progress.first_deal_at:
                    progress.first_deal_at = ts
                elif step_id == "first_proposal" and not progress.first_proposal_at:
                    progress.first_proposal_at = ts

            if return_new_milestones and step_id not in shown and step_id in MILESTONE_MESSAGES:
                msg = OnboardingMilestoneMessage(
                    step_id=step_id,
                    message=MILESTONE_MESSAGES[step_id],
                    shown_at=now,
                )
                new_milestones.append(msg)
                shown.add(step_id)

        if new_milestones:
            existing = list(progress.milestone_messages or [])
            existing.extend([m.model_dump(mode="json") for m in new_milestones])
            progress.milestone_messages = existing

        completed_count = sum(1 for s, _, _, _ in CHECKLIST_STEPS if s in steps_completed)
        progress.steps_completed = steps_completed
        progress.progress_percent = round(completed_count / TOTAL_STEPS * 100)

        if completed_count == 0 and progress.status == "not_started":
            pass
        elif completed_count >= TOTAL_STEPS or progress.manually_completed:
            progress.status = "completed"
            if not progress.completed_at:
                progress.completed_at = now
        else:
            progress.status = "in_progress"
            if not progress.started_at:
                progress.started_at = now

        await db.flush()
        return progress, new_milestones

    @staticmethod
    def _dashboard_from_progress(
        progress: TenantOnboardingProgress,
        new_milestones: list[OnboardingMilestoneMessage] | None = None,
    ) -> OnboardingDashboardResponse:
        steps = TenantOnboardingService._build_steps(progress.steps_completed or {})
        completed = sum(1 for s in steps if s.completed)
        remaining = [s for s in steps if not s.completed]
        est_remaining = sum(s.estimated_minutes for s in remaining)
        next_step = remaining[0] if remaining else None

        return OnboardingDashboardResponse(
            tenant_id=progress.tenant_id,
            status=progress.status,
            progress_percent=progress.progress_percent,
            completed_steps=completed,
            total_steps=TOTAL_STEPS,
            remaining_steps=len(remaining),
            estimated_minutes_remaining=est_remaining,
            steps=steps,
            next_step=next_step,
            demo_data_generated=progress.demo_data_generated,
            new_milestones=new_milestones or [],
            started_at=progress.started_at,
            completed_at=progress.completed_at,
        )

    @staticmethod
    async def dashboard(db: AsyncSession, tenant_id: UUID) -> OnboardingDashboardResponse:
        progress, milestones = await TenantOnboardingService.refresh_progress(db, tenant_id)
        return TenantOnboardingService._dashboard_from_progress(progress, milestones)

    @staticmethod
    async def save_company_profile(
        db: AsyncSession,
        tenant_id: UUID,
        profile: OnboardingCompanyProfile,
    ) -> OnboardingDashboardResponse:
        progress = await TenantOnboardingService.get_or_create_progress(db, tenant_id)
        progress.company_profile = profile.model_dump()
        if not progress.started_at:
            progress.started_at = _utcnow()
            progress.status = "in_progress"

        tenant = await TenantService.get_tenant(db, tenant_id)
        if profile.company_name.strip():
            tenant.company_name = profile.company_name.strip()

        try:
            existing = await FactoryProfileService.profile(db, tenant_id)
            if existing.get("profile"):
                await FactoryProfileService.update_profile(
                    db,
                    tenant_id,
                    {
                        "company_name": profile.company_name,
                        "industry": profile.industry,
                        "country": profile.country,
                        "city": profile.city,
                        "website": profile.website,
                        "contact_name": profile.contact_person,
                        "contact_email": profile.email,
                        "contact_phone": profile.phone,
                    },
                )
        except HTTPException:
            pass

        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        if client_ids and profile.preferred_languages:
            client = await db.get(Client, client_ids[0])
            if client:
                client.preferred_languages = profile.preferred_languages
                if profile.company_name:
                    client.company_name = profile.company_name

        await db.flush()
        progress, milestones = await TenantOnboardingService.refresh_progress(db, tenant_id)
        return TenantOnboardingService._dashboard_from_progress(progress, milestones)

    @staticmethod
    async def channel_status(db: AsyncSession, tenant_id: UUID) -> OnboardingChannelStatus:
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        telegram_connected = False
        telegram_group: str | None = None
        if client_ids:
            result = await db.execute(
                select(Client).where(Client.id.in_(client_ids)).limit(1),
            )
            client = result.scalar_one_or_none()
            if client:
                telegram_connected = bool(client.telegram_group_id or client.telegram_id)
                telegram_group = client.telegram_group_title

        return OnboardingChannelStatus(
            telegram={
                "available": True,
                "connected": telegram_connected,
                "group_title": telegram_group,
                "verification_status": "verified" if telegram_connected else "pending",
                "guide_steps": [
                    "Add @YourFactoryBot to your Telegram group",
                    "Send /link in the group to connect your workspace",
                    "Upload a test photo to verify content ingestion",
                ],
            },
            wechat={
                "available": False,
                "connected": False,
                "status": "coming_soon",
                "message": "WeChat integration is planned for a future release.",
            },
            whatsapp={
                "available": False,
                "connected": False,
                "status": "coming_soon",
                "message": "WhatsApp Business integration is planned for a future release.",
            },
        )

    @staticmethod
    async def generate_demo_data(db: AsyncSession, tenant_id: UUID) -> tuple[dict[str, int], OnboardingDashboardResponse]:
        progress = await TenantOnboardingService.get_or_create_progress(db, tenant_id)
        counts = await TenantOnboardingDemoService.generate_for_tenant(db, tenant_id)
        progress.demo_data_generated = True
        progress.demo_data_generated_at = _utcnow()
        if not progress.started_at:
            progress.started_at = _utcnow()
            progress.status = "in_progress"
        await db.flush()
        progress, milestones = await TenantOnboardingService.refresh_progress(db, tenant_id)
        return counts, TenantOnboardingService._dashboard_from_progress(progress, milestones)

    @staticmethod
    async def record_growth_center_visit(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> OnboardingDashboardResponse:
        progress = await TenantOnboardingService.get_or_create_progress(db, tenant_id)
        if not progress.growth_center_viewed_at:
            progress.growth_center_viewed_at = _utcnow()
        await db.flush()
        progress, milestones = await TenantOnboardingService.refresh_progress(db, tenant_id)
        return TenantOnboardingService._dashboard_from_progress(progress, milestones)

    @staticmethod
    async def assistant_chat(
        db: AsyncSession,
        tenant_id: UUID,
        message: str,
        context_step: str | None = None,
    ) -> OnboardingAssistantResponse:
        text = (message or "").strip()
        if not text:
            return OnboardingAssistantResponse(
                reply="Ask me what to do next, how to upload content, create buyers, or build proposals.",
                suggested_route="/onboarding",
                source="rules",
            )

        for pattern, reply, route in _RULE_GUIDANCE:
            if pattern.search(text):
                return OnboardingAssistantResponse(reply=reply, suggested_route=route, source="rules")

        progress = await TenantOnboardingService.get_or_create_progress(db, tenant_id)
        steps = TenantOnboardingService._build_steps(progress.steps_completed or {})
        remaining = [s for s in steps if not s.completed]
        if re.search(r"help|assist|guide", text, re.I) and remaining:
            nxt = remaining[0]
            return OnboardingAssistantResponse(
                reply=f"Your next step is: {nxt.label}. It takes about {nxt.estimated_minutes} minutes.",
                suggested_route=nxt.route,
                source="rules",
            )

        if _validate_api_key(settings.OPENAI_API_KEY):
            try:
                client = get_openai()
                dash = await TenantOnboardingService.dashboard(db, tenant_id)
                ctx = (
                    f"Progress: {dash.progress_percent}%. "
                    f"Next step: {dash.next_step.label if dash.next_step else 'Complete'}. "
                    f"Context step: {context_step or 'general'}."
                )
                resp = await client.chat.completions.create(
                    model=settings.OPENAI_MODEL or "gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": _ASSISTANT_SYSTEM},
                        {"role": "user", "content": f"{ctx}\n\nUser: {text}"},
                    ],
                    max_tokens=300,
                )
                reply = (resp.choices[0].message.content or "").strip()
                if reply:
                    return OnboardingAssistantResponse(reply=reply, source="ai")
            except Exception:
                logger.exception("Onboarding AI assistant fallback")

        return OnboardingAssistantResponse(
            reply=(
                "I can help with onboarding steps: company setup, Telegram, content, CRM, proposals, "
                "and Growth Center. Try asking 'What should I do next?' or visit the onboarding dashboard."
            ),
            suggested_route="/onboarding",
            source="rules",
        )

    @staticmethod
    def _drop_off_step(steps_completed: dict[str, str] | None) -> str | None:
        completed = set((steps_completed or {}).keys())
        for step_id, label, _, _ in CHECKLIST_STEPS:
            if step_id not in completed:
                return step_id
        return None

    @staticmethod
    async def admin_analytics(db: AsyncSession) -> OnboardingAdminAnalytics:
        tenants = (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()).limit(200))).scalars().all()
        progress_rows = (await db.execute(select(TenantOnboardingProgress))).scalars().all()
        by_tenant = {p.tenant_id: p for p in progress_rows}

        items: list[OnboardingAdminTenantItem] = []
        drop_offs: dict[str, int] = {}
        started = completed = demo_usage = 0
        t_content: list[float] = []
        t_lead: list[float] = []
        t_proposal: list[float] = []
        t_gc: list[float] = []

        for tenant in tenants:
            p = by_tenant.get(tenant.id)
            steps = p.steps_completed if p else {}
            completed_count = sum(1 for s, _, _, _ in CHECKLIST_STEPS if s in (steps or {}))
            status = p.status if p else "not_started"
            if status != "not_started":
                started += 1
            if status == "completed" or (p and p.manually_completed):
                completed += 1
            if p and p.demo_data_generated:
                demo_usage += 1

            drop = TenantOnboardingService._drop_off_step(steps)
            if drop and status == "in_progress":
                drop_offs[drop] = drop_offs.get(drop, 0) + 1

            base = p.started_at or p.created_at if p else tenant.created_at
            if p:
                if p.first_content_at:
                    h = _hours_between(base, p.first_content_at)
                    if h is not None:
                        t_content.append(h)
                if p.first_lead_at:
                    h = _hours_between(base, p.first_lead_at)
                    if h is not None:
                        t_lead.append(h)
                if p.first_proposal_at:
                    h = _hours_between(base, p.first_proposal_at)
                    if h is not None:
                        t_proposal.append(h)
                if p.growth_center_viewed_at:
                    h = _hours_between(base, p.growth_center_viewed_at)
                    if h is not None:
                        t_gc.append(h)

            items.append(OnboardingAdminTenantItem(
                tenant_id=tenant.id,
                company_name=tenant.company_name,
                status=status,
                progress_percent=p.progress_percent if p else 0,
                completed_steps=completed_count,
                total_steps=TOTAL_STEPS,
                demo_data_generated=bool(p and p.demo_data_generated),
                started_at=p.started_at if p else None,
                completed_at=p.completed_at if p else None,
                time_to_first_content_hours=_hours_between(base, p.first_content_at) if p else None,
                time_to_first_lead_hours=_hours_between(base, p.first_lead_at) if p else None,
                time_to_first_proposal_hours=_hours_between(base, p.first_proposal_at) if p else None,
                time_to_growth_center_hours=_hours_between(base, p.growth_center_viewed_at) if p else None,
                drop_off_step=drop if status == "in_progress" else None,
            ))

        total = len(tenants)
        rate = round(completed / total * 100, 1) if total else 0.0

        def _avg(vals: list[float]) -> float | None:
            return round(sum(vals) / len(vals), 2) if vals else None

        return OnboardingAdminAnalytics(
            total_tenants=total,
            started_count=started,
            completed_count=completed,
            completion_rate_percent=rate,
            demo_data_usage_count=demo_usage,
            avg_time_to_first_content_hours=_avg(t_content),
            avg_time_to_first_lead_hours=_avg(t_lead),
            avg_time_to_first_proposal_hours=_avg(t_proposal),
            avg_time_to_growth_center_hours=_avg(t_gc),
            drop_off_by_step=drop_offs,
            tenants=items,
        )

    @staticmethod
    async def admin_reset(db: AsyncSession, tenant_id: UUID) -> OnboardingDashboardResponse:
        await TenantService.get_tenant(db, tenant_id)
        result = await db.execute(
            select(TenantOnboardingProgress).where(TenantOnboardingProgress.tenant_id == tenant_id),
        )
        progress = result.scalar_one_or_none()
        if progress:
            await db.delete(progress)
            await db.flush()
        fresh = await TenantOnboardingService.get_or_create_progress(db, tenant_id)
        fresh.manually_reset_at = _utcnow()
        await db.flush()
        return TenantOnboardingService._dashboard_from_progress(fresh)

    @staticmethod
    async def admin_mark_complete(db: AsyncSession, tenant_id: UUID) -> OnboardingDashboardResponse:
        progress = await TenantOnboardingService.get_or_create_progress(db, tenant_id)
        now = _utcnow()
        progress.manually_completed = True
        progress.status = "completed"
        progress.progress_percent = 100
        progress.completed_at = now
        steps = {s: now.isoformat() for s, _, _, _ in CHECKLIST_STEPS}
        progress.steps_completed = steps
        await db.flush()
        return TenantOnboardingService._dashboard_from_progress(progress)
