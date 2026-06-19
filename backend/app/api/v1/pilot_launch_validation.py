"""Pilot Launch Validation v1 — end-to-end pilot experience validation."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.pilot_launch_validation import (
    PilotLaunchValidationBlockers,
    PilotLaunchValidationClientFacing,
    PilotLaunchValidationDataCompleteness,
    PilotLaunchValidationFlow,
    PilotLaunchValidationNextActions,
    PilotLaunchValidationOverview,
    PilotLaunchValidationReadiness,
    PilotLaunchValidationRefreshResponse,
    PilotLaunchValidationSummaryWidget,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_launch_validation_service import PilotLaunchValidationService

router = APIRouter(prefix="/pilot-launch-validation", tags=["pilot-launch-validation"])


@router.get("/overview", response_model=PilotLaunchValidationOverview)
async def pilot_launch_validation_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.overview(db),
        label="pilot_launch_validation.overview",
        timeout=30.0,
    )


@router.get("/readiness", response_model=PilotLaunchValidationReadiness)
async def pilot_launch_validation_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.readiness(db),
        label="pilot_launch_validation.readiness",
        timeout=25.0,
    )


@router.get("/admin-flow", response_model=PilotLaunchValidationFlow)
async def pilot_launch_validation_admin_flow(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.admin_flow(db),
        label="pilot_launch_validation.admin_flow",
        timeout=25.0,
    )


@router.get("/tenant-flow", response_model=PilotLaunchValidationFlow)
async def pilot_launch_validation_tenant_flow(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.tenant_flow(db),
        label="pilot_launch_validation.tenant_flow",
        timeout=25.0,
    )


@router.get("/data-completeness", response_model=PilotLaunchValidationDataCompleteness)
async def pilot_launch_validation_data_completeness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.data_completeness(db),
        label="pilot_launch_validation.data_completeness",
    )


@router.get("/client-facing-readiness", response_model=PilotLaunchValidationClientFacing)
async def pilot_launch_validation_client_facing(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.client_facing_readiness(db),
        label="pilot_launch_validation.client_facing",
        timeout=25.0,
    )


@router.get("/blockers", response_model=PilotLaunchValidationBlockers)
async def pilot_launch_validation_blockers(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.blockers(db),
        label="pilot_launch_validation.blockers",
        timeout=25.0,
    )


@router.get("/next-actions", response_model=PilotLaunchValidationNextActions)
async def pilot_launch_validation_next_actions(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.next_actions(db),
        label="pilot_launch_validation.next_actions",
        timeout=25.0,
    )


@router.get("/summary-widget", response_model=PilotLaunchValidationSummaryWidget)
async def pilot_launch_validation_summary_widget(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotLaunchValidationService.summary_widget(db),
        label="pilot_launch_validation.summary_widget",
        timeout=30.0,
    )


@router.post("/refresh", response_model=PilotLaunchValidationRefreshResponse)
async def pilot_launch_validation_refresh(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotLaunchValidationService.refresh(db)
