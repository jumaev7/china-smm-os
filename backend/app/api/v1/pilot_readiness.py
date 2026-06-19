"""Pilot Readiness Dashboard — demo prep health and route stability (read-only)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.pilot_readiness import PilotReadinessOverview
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_readiness_service import PilotReadinessService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/pilot-readiness", tags=["pilot-readiness"])


@router.get("/overview", response_model=PilotReadinessOverview)
async def pilot_readiness_overview(
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if not admin and not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return await run_guarded(
        PilotReadinessService.overview(db),
        label="pilot_readiness.overview",
        timeout=30.0,
    )
