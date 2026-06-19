"""Factory Growth Center API — executive business growth dashboard."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.growth_center import (
    ExportFormat,
    GrowthCenterDashboardResponse,
    GrowthCenterExportFormatInfo,
    GrowthCenterExportRequest,
    GrowthCenterExportResponse,
    GrowthCenterSummaryResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.growth_center_export_service import growth_center_export_service
from app.services.growth_center_service import GrowthCenterService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/growth-center", tags=["growth-center"])
SUMMARY_TIMEOUT_SEC = 1.0


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_growth_center_view(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> None:
    if admin:
        return
    if user:
        if user.has_permission("leads.view") or user.has_permission("buyers.view"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/dashboard", response_model=GrowthCenterDashboardResponse)
async def growth_center_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_growth_center_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        GrowthCenterService.dashboard(db, tenant_id),
        label="growth-center.dashboard",
    )


@router.get("/summary", response_model=GrowthCenterSummaryResponse)
async def growth_center_summary(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_growth_center_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        GrowthCenterService.summary(db, tenant_id),
        label="growth-center.summary",
        timeout=SUMMARY_TIMEOUT_SEC,
    )


@router.get("/export/formats", response_model=list[GrowthCenterExportFormatInfo])
async def list_export_formats(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    _require_growth_center_view(user, admin)
    return growth_center_export_service.list_formats()


@router.post("/export/{fmt}", response_model=GrowthCenterExportResponse)
async def export_growth_center(
    fmt: ExportFormat,
    body: GrowthCenterExportRequest | None = None,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_growth_center_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    dashboard = await GrowthCenterService.dashboard(db, tenant_id)
    return await growth_center_export_service.export(
        db,
        tenant_id,
        dashboard,
        fmt,
        body,
    )
