"""Factory Partner Platform v1 — tenant-scoped factory business workspace."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user, require_tenant
from app.schemas.factory_platform import (
    FactoryPlatformCompanyResponse,
    FactoryPlatformDashboardResponse,
    FactoryPlatformInsightsResponse,
    FactoryPlatformProductsResponse,
    FactoryPlatformReportsResponse,
)
from app.services.factory_platform_service import FactoryPlatformService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/factory-platform", tags=["factory-platform"])


@router.get("/dashboard", response_model=FactoryPlatformDashboardResponse)
async def factory_platform_dashboard(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryPlatformService.dashboard(db, tenant_id),
        label="factory_platform.dashboard",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/company", response_model=FactoryPlatformCompanyResponse)
async def factory_platform_company(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryPlatformService.company(db, tenant_id),
        label="factory_platform.company",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/products", response_model=FactoryPlatformProductsResponse)
async def factory_platform_products(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryPlatformService.products(db, tenant_id, skip=skip, limit=limit),
        label="factory_platform.products",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/reports", response_model=FactoryPlatformReportsResponse)
async def factory_platform_reports(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryPlatformService.reports(db, tenant_id),
        label="factory_platform.reports",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/insights", response_model=FactoryPlatformInsightsResponse)
async def factory_platform_insights(
    tenant_id: UUID = Query(..., description="Factory tenant ID (required scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    require_tenant(tenant_id, user)
    return await run_guarded(
        FactoryPlatformService.insights(db, tenant_id),
        label="factory_platform.insights",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/workspaces")
async def factory_platform_workspaces(
    limit: int = Query(50, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Tenants with linked company clients — scoped to authenticated tenant."""
    return await FactoryPlatformService.list_workspaces(
        db, limit=limit, tenant_id=user.tenant_id,
    )
