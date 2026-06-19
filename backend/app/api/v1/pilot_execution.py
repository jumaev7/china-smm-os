"""Pilot Client Onboarding Execution v1 — seed, report, page verification."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.pilot_execution import (
    PilotExecutionOverview,
    PilotExecutionReport,
    PilotExecutionSeedRequest,
    PilotExecutionSeedResponse,
    PilotExecutionVerifyResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_execution_service import PilotExecutionService

router = APIRouter(prefix="/pilot-execution", tags=["pilot-execution"])


@router.get("/overview", response_model=PilotExecutionOverview)
async def pilot_execution_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotExecutionService.overview(db),
        label="pilot_execution.overview",
    )


@router.get("/report", response_model=PilotExecutionReport)
async def pilot_execution_report(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotExecutionService.execution_report(db),
        label="pilot_execution.report",
        timeout=25.0,
    )


@router.post("/seed-pilot-data", response_model=PilotExecutionSeedResponse)
async def pilot_execution_seed_pilot_data(
    body: PilotExecutionSeedRequest | None = None,
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.full")),
    db: AsyncSession = Depends(get_db),
):
    force = bool(body.force) if body else False
    return await PilotExecutionService.seed_pilot_data(db, force=force)


@router.post("/verify-pages", response_model=PilotExecutionVerifyResponse)
async def pilot_execution_verify_pages(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
):
    return await run_guarded(
        PilotExecutionService.verify_pages(),
        label="pilot_execution.verify_pages",
    )
