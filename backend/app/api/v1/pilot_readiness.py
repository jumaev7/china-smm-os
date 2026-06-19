"""Pilot Readiness Dashboard — demo prep health and route stability (read-only)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.pilot_readiness import PilotReadinessOverview
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.pilot_readiness_service import PilotReadinessService

router = APIRouter(prefix="/pilot-readiness", tags=["pilot-readiness"])


@router.get("/overview", response_model=PilotReadinessOverview)
async def pilot_readiness_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        PilotReadinessService.overview(db),
        label="pilot_readiness.overview",
        timeout=30.0,
    )
