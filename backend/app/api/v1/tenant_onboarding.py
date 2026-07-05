"""Factory tenant onboarding — tenant wizard and admin analytics."""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.tenant_onboarding import (
    OnboardingAdminActionResponse,
    OnboardingAdminAnalytics,
    OnboardingAdminReadinessOverview,
    OnboardingAssistantRequest,
    OnboardingAssistantResponse,
    OnboardingChannelStatus,
    OnboardingCompanyProfile,
    OnboardingCompanySaveResponse,
    OnboardingDashboardResponse,
    OnboardingDemoDataResponse,
    OnboardingGrowthCenterVisitResponse,
    OnboardingNorthStarGoalRequest,
    OnboardingNorthStarGoalResponse,
    OnboardingReadinessResponse,
    OnboardingRefreshResponse,
    ExecutiveWalkthroughPanelRequest,
    ExecutiveWalkthroughPanelResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.tenant_auth_service import CurrentTenantUser
from app.services.tenant_onboarding_service import TenantOnboardingService

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/readiness", response_model=OnboardingReadinessResponse)
async def onboarding_readiness(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        TenantOnboardingService.readiness(db, user.tenant_id),
        label="onboarding.readiness",
    )


@router.post("/executive-walkthrough/panel", response_model=ExecutiveWalkthroughPanelResponse)
async def onboarding_executive_walkthrough_panel(
    body: ExecutiveWalkthroughPanelRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    readiness = await TenantOnboardingService.record_executive_walkthrough_panel(
        db, user.tenant_id, body.panel_id,
    )
    return ExecutiveWalkthroughPanelResponse(
        recorded=True,
        panel_id=body.panel_id,
        readiness=readiness,
    )


@router.get("/dashboard", response_model=OnboardingDashboardResponse)
async def onboarding_dashboard(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        TenantOnboardingService.dashboard(db, user.tenant_id),
        label="onboarding.dashboard",
    )


@router.post("/refresh", response_model=OnboardingRefreshResponse)
async def onboarding_refresh(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    progress = await TenantOnboardingService.dashboard(db, user.tenant_id)
    return OnboardingRefreshResponse(refreshed=True, progress=progress)


@router.post("/north-star-goal", response_model=OnboardingNorthStarGoalResponse)
async def onboarding_save_north_star_goal(
    body: OnboardingNorthStarGoalRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    goal, label = await TenantOnboardingService.save_north_star_goal(
        db, user.tenant_id, body.goal,
    )
    return OnboardingNorthStarGoalResponse(saved=True, goal=goal, label=label)


@router.post("/company", response_model=OnboardingCompanySaveResponse)
async def onboarding_save_company(
    body: OnboardingCompanyProfile,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    progress = await TenantOnboardingService.save_company_profile(db, user.tenant_id, body)
    return OnboardingCompanySaveResponse(saved=True, profile=body, progress=progress)


@router.get("/channels/status", response_model=OnboardingChannelStatus)
async def onboarding_channel_status(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantOnboardingService.channel_status(db, user.tenant_id)


@router.post("/demo-data", response_model=OnboardingDemoDataResponse)
async def onboarding_generate_demo_data(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    counts, progress = await TenantOnboardingService.generate_demo_data(db, user.tenant_id)
    return OnboardingDemoDataResponse(
        generated=True,
        message="Demo environment created. Explore buyers, leads, deals, and communications.",
        counts=counts,
        progress=progress,
    )


@router.post("/growth-center/visit", response_model=OnboardingGrowthCenterVisitResponse)
async def onboarding_growth_center_visit(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    progress = await TenantOnboardingService.record_growth_center_visit(db, user.tenant_id)
    return OnboardingGrowthCenterVisitResponse(recorded=True, progress=progress)


@router.post("/assistant/chat", response_model=OnboardingAssistantResponse)
async def onboarding_assistant_chat(
    body: OnboardingAssistantRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantOnboardingService.assistant_chat(
        db, user.tenant_id, body.message, body.context_step,
    )


@router.get("/admin/readiness", response_model=OnboardingAdminReadinessOverview)
async def onboarding_admin_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        TenantOnboardingService.admin_readiness_overview(db),
        label="onboarding.admin_readiness",
    )


@router.get("/admin/analytics", response_model=OnboardingAdminAnalytics)
async def onboarding_admin_analytics(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        TenantOnboardingService.admin_analytics(db),
        label="onboarding.admin_analytics",
    )


@router.post("/admin/tenants/{tenant_id}/reset", response_model=OnboardingAdminActionResponse)
async def onboarding_admin_reset(
    tenant_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    progress = await TenantOnboardingService.admin_reset(db, tenant_id)
    return OnboardingAdminActionResponse(
        success=True,
        message="Onboarding progress reset for tenant.",
        progress=progress,
    )


@router.post("/admin/tenants/{tenant_id}/complete", response_model=OnboardingAdminActionResponse)
async def onboarding_admin_complete(
    tenant_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    progress = await TenantOnboardingService.admin_mark_complete(db, tenant_id)
    return OnboardingAdminActionResponse(
        success=True,
        message="Onboarding marked complete for tenant.",
        progress=progress,
    )
