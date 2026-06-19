"""Pilot Launch QA & Demo Data v1 — demo seed, QA, readiness, smoke tests."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.pilot_launch import (
    PilotLaunchChecklist,
    PilotLaunchDemoSeedRequest,
    PilotLaunchDemoSeedResponse,
    PilotLaunchOverview,
    PilotLaunchQaResponse,
    PilotLaunchReadiness,
    PilotLaunchSmokeTestsResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_launch_service import PilotLaunchService

router = APIRouter(prefix="/pilot-launch", tags=["pilot-launch"])


@router.get("/overview", response_model=PilotLaunchOverview)
async def pilot_launch_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchService.overview(db),
        label="pilot_launch.overview",
    )


@router.get("/readiness", response_model=PilotLaunchReadiness)
async def pilot_launch_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotLaunchService.readiness(db)


@router.get("/checklist", response_model=PilotLaunchChecklist)
async def pilot_launch_checklist(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotLaunchService.checklist(db)


@router.get("/smoke-tests", response_model=PilotLaunchSmokeTestsResponse)
async def pilot_launch_smoke_tests(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchService.smoke_tests(),
        label="pilot_launch.smoke_tests",
    )


@router.post("/seed-demo-data", response_model=PilotLaunchDemoSeedResponse)
async def pilot_launch_seed_demo_data(
    body: PilotLaunchDemoSeedRequest | None = None,
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.full")),
    db: AsyncSession = Depends(get_db),
):
    force = bool(body.force) if body else False
    return await PilotLaunchService.seed_demo_data(db, force=force)


@router.post("/run-qa", response_model=PilotLaunchQaResponse)
async def pilot_launch_run_qa(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchService.run_qa(db),
        label="pilot_launch.run_qa",
    )
