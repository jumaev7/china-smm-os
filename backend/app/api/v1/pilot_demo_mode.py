"""Pilot Demo Mode — guided demonstration workflow with isolated demo data."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.pilot_demo_mode import (
    PilotDemoModeActionResponse,
    PilotDemoModeOverview,
    PilotDemoModeResetResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_demo_mode_service import PilotDemoModeService

router = APIRouter(prefix="/pilot-demo-mode", tags=["pilot-demo-mode"])


@router.get("/overview", response_model=PilotDemoModeOverview)
async def pilot_demo_mode_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotDemoModeService.overview(db),
        label="pilot_demo_mode.overview",
    )


@router.post("/actions/{action}", response_model=PilotDemoModeActionResponse)
async def pilot_demo_mode_action(
    action: str,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotDemoModeService.run_action(db, action),
        label=f"pilot_demo_mode.action.{action}",
    )


@router.post("/reset", response_model=PilotDemoModeResetResponse)
async def pilot_demo_mode_reset(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotDemoModeService.reset_demo_data(db),
        label="pilot_demo_mode.reset",
    )
