"""First Pilot Client Preparation v1 — readiness, blockers, recommendations."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.first_pilot_client import (
    FirstPilotClientBlockersResponse,
    FirstPilotClientOverview,
    FirstPilotClientReadiness,
    FirstPilotClientRecommendationsResponse,
    FirstPilotClientRefreshResponse,
    FirstPilotClientSummary,
    FirstPilotClientSummaryWidget,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.first_pilot_client_service import FirstPilotClientService

router = APIRouter(prefix="/first-pilot-client", tags=["first-pilot-client"])


@router.get("/overview", response_model=FirstPilotClientOverview)
async def first_pilot_client_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        FirstPilotClientService.overview(db),
        label="first_pilot_client.overview",
    )


@router.get("/readiness", response_model=FirstPilotClientReadiness)
async def first_pilot_client_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FirstPilotClientService.readiness(db)


@router.get("/blockers", response_model=FirstPilotClientBlockersResponse)
async def first_pilot_client_blockers(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FirstPilotClientService.blockers(db)


@router.get("/recommendations", response_model=FirstPilotClientRecommendationsResponse)
async def first_pilot_client_recommendations(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FirstPilotClientService.recommendations(db)


@router.get("/summary", response_model=FirstPilotClientSummary)
async def first_pilot_client_summary(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FirstPilotClientService.summary(db)


@router.get("/summary-widget", response_model=FirstPilotClientSummaryWidget)
async def first_pilot_client_summary_widget(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FirstPilotClientService.summary_widget(db)


@router.get("/tenant-indicator")
async def first_pilot_client_tenant_indicator(
    tenant_id: UUID = Query(...),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FirstPilotClientService.tenant_readiness_indicator(db, tenant_id)


@router.post("/refresh", response_model=FirstPilotClientRefreshResponse)
async def first_pilot_client_refresh(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await FirstPilotClientService.refresh(db)
