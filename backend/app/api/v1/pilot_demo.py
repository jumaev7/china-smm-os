"""Pilot Demo Scenario v1 — guided presentation and demo readiness (read-only)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.pilot_demo import (
    PilotDemoJourney,
    PilotDemoOverview,
    PilotDemoPresentationFlow,
    PilotDemoReadiness,
    PilotDemoRefreshResponse,
    PilotDemoScenariosResponse,
    PilotDemoSummary,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_demo_service import PilotDemoService

router = APIRouter(prefix="/pilot-demo", tags=["pilot-demo"])


@router.get("/overview", response_model=PilotDemoOverview)
async def pilot_demo_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotDemoService.overview(db),
        label="pilot_demo.overview",
    )


@router.get("/scenarios", response_model=PilotDemoScenariosResponse)
async def pilot_demo_scenarios(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
):
    return PilotDemoService.scenarios()


@router.get("/factory-owner", response_model=PilotDemoJourney)
async def pilot_demo_factory_owner(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotDemoService.factory_owner_journey(db)


@router.get("/executive", response_model=PilotDemoJourney)
async def pilot_demo_executive(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotDemoService.executive_journey(db)


@router.get("/readiness", response_model=PilotDemoReadiness)
async def pilot_demo_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotDemoService.readiness(db)


@router.get("/presentation-flow", response_model=PilotDemoPresentationFlow)
async def pilot_demo_presentation_flow(
    scenario_id: str = Query(default="factory_owner_demo"),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotDemoService.presentation_flow(db, scenario_id=scenario_id)


@router.get("/summary", response_model=PilotDemoSummary)
async def pilot_demo_summary(
    scenario_id: str = Query(default="factory_owner_demo"),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotDemoService.summary(db, scenario_id=scenario_id)


@router.post("/refresh", response_model=PilotDemoRefreshResponse)
async def pilot_demo_refresh(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotDemoService.refresh(db)
