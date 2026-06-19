from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.services.admin_rbac_service import CurrentAdminUser
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.schemas.audit import AuditFixApplyResponse, AuditOverviewResponse
from app.services.audit_fix_service import AuditFixService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/overview", response_model=AuditOverviewResponse)
async def audit_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("reports.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AuditService.run(db),
        label="audit.overview",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/run", response_model=AuditOverviewResponse)
async def audit_run(
    admin: CurrentAdminUser = Depends(require_admin_permission("reports.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AuditService.run(db),
        label="audit.run",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/fixes/{issue_id}/apply", response_model=AuditFixApplyResponse)
async def audit_apply_fix(
    issue_id: str,
    admin: CurrentAdminUser = Depends(require_admin_permission("reports.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AuditFixService.apply(db, issue_id),
        label="audit.fix.apply",
        timeout=SCAN_TIMEOUT_SEC,
    )
