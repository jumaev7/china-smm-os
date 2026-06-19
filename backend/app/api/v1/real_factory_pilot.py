"""First Real Factory Pilot v1 — operational execution workspace."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.real_factory_pilot import (
    RealFactoryPilotActionsResponse,
    RealFactoryPilotBlockersResponse,
    RealFactoryPilotCandidateIndicator,
    RealFactoryPilotChecklist,
    RealFactoryPilotOverview,
    RealFactoryPilotReadiness,
    RealFactoryPilotRefreshResponse,
    RealFactoryPilotSummary,
    RealFactoryPilotSummaryWidget,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.real_factory_pilot_service import RealFactoryPilotService

router = APIRouter(prefix="/real-factory-pilot", tags=["real-factory-pilot"])


@router.get("/overview", response_model=RealFactoryPilotOverview)
async def real_factory_pilot_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        RealFactoryPilotService.overview(db),
        label="real_factory_pilot.overview",
        timeout=20.0,
    )


@router.get("/checklist", response_model=RealFactoryPilotChecklist)
async def real_factory_pilot_checklist(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.checklist(db)


@router.get("/blockers", response_model=RealFactoryPilotBlockersResponse)
async def real_factory_pilot_blockers(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.blockers(db)


@router.get("/actions", response_model=RealFactoryPilotActionsResponse)
async def real_factory_pilot_actions(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.actions(db)


@router.get("/readiness", response_model=RealFactoryPilotReadiness)
async def real_factory_pilot_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.readiness(db)


@router.get("/summary", response_model=RealFactoryPilotSummary)
async def real_factory_pilot_summary(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.summary(db)


@router.get("/summary-widget", response_model=RealFactoryPilotSummaryWidget)
async def real_factory_pilot_summary_widget(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.summary_widget(db)


@router.get("/candidate-indicator", response_model=RealFactoryPilotCandidateIndicator)
async def real_factory_pilot_candidate_indicator(
    application_id: UUID = Query(...),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.candidate_indicator(db, application_id)


@router.post("/refresh", response_model=RealFactoryPilotRefreshResponse)
async def real_factory_pilot_refresh(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await RealFactoryPilotService.refresh(db)
