"""AI Export Growth Engine API — executive export growth dashboard."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.export_growth import ExportGrowthDashboardResponse, ExportGrowthSummaryResponse
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.export_growth_service import ExportGrowthService
from app.core.tenant_access import get_current_tenant_user_optional
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/export-growth", tags=["export-growth"])
SUMMARY_TIMEOUT_SEC = 8.0


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_export_growth_view(
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


@router.get("/dashboard", response_model=ExportGrowthDashboardResponse)
async def export_growth_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_export_growth_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        ExportGrowthService.dashboard(db, tenant_id),
        label="export-growth.dashboard",
    )


@router.get("/summary", response_model=ExportGrowthSummaryResponse)
async def export_growth_summary(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_export_growth_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        ExportGrowthService.summary(db, tenant_id),
        label="export-growth.summary",
        timeout=SUMMARY_TIMEOUT_SEC,
    )
