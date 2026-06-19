"""Pilot Client Onboarding v1 — guided admin workflow endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.pilot_onboarding import (
    PilotOnboardingActionsResponse,
    PilotOnboardingApplicationsResponse,
    PilotOnboardingBlockersResponse,
    PilotOnboardingChecklistResponse,
    PilotOnboardingDetail,
    PilotOnboardingOverview,
    PilotOnboardingRefreshResponse,
    PilotOnboardingSummaryWidget,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_onboarding_service import PilotOnboardingService

router = APIRouter(prefix="/pilot-onboarding", tags=["pilot-onboarding"])


@router.get("/overview", response_model=PilotOnboardingOverview)
async def pilot_onboarding_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotOnboardingService.overview(db),
        label="pilot_onboarding.overview",
    )


@router.get("/summary-widget", response_model=PilotOnboardingSummaryWidget)
async def pilot_onboarding_summary_widget(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotOnboardingService.summary_widget(db)


@router.get("/applications", response_model=PilotOnboardingApplicationsResponse)
async def pilot_onboarding_applications(
    status: str | None = Query(None, description="Factory application status filter"),
    onboarding_status: str | None = Query(
        None,
        description="not_started | in_progress | blocked | ready | completed",
    ),
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotOnboardingService.list_applications(
            db,
            status=status,
            search=search,
            onboarding_status=onboarding_status,
            skip=skip,
            limit=limit,
        ),
        label="pilot_onboarding.applications",
    )


@router.get("/{application_id}", response_model=PilotOnboardingDetail)
async def pilot_onboarding_detail(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotOnboardingService.get_application(db, application_id)


@router.get("/{application_id}/checklist", response_model=PilotOnboardingChecklistResponse)
async def pilot_onboarding_checklist(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotOnboardingService.checklist(db, application_id)


@router.get("/{application_id}/blockers", response_model=PilotOnboardingBlockersResponse)
async def pilot_onboarding_blockers(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotOnboardingService.blockers(db, application_id)


@router.get("/{application_id}/actions", response_model=PilotOnboardingActionsResponse)
async def pilot_onboarding_actions(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotOnboardingService.actions(db, application_id)


@router.post("/{application_id}/refresh", response_model=PilotOnboardingRefreshResponse)
async def pilot_onboarding_refresh(
    application_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotOnboardingService.refresh(db, application_id)
