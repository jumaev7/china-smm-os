"""Pre-launch platform operations API — pilot program, feedback, health, audit, errors."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user, get_current_tenant_user_optional
from app.services.tenant_auth_service import CurrentTenantUser
from app.schemas.platform_ops import (
    AuditLogListResponse,
    AuditLogResponse,
    ErrorReportCreate,
    ErrorReportListResponse,
    ErrorReportResponse,
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackResponse,
    LaunchReadinessResponse,
    PilotFactoryCreate,
    PilotFactoryListResponse,
    PilotFactoryResponse,
    PilotFactoryUpdate,
    PilotSuccessDashboardResponse,
    SystemHealthDashboardResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.error_tracking_service import ErrorTrackingService
from app.services.feedback_service import FeedbackService
from app.services.launch_readiness_service import LaunchReadinessService
from app.services.pilot_program_service import PilotProgramService
from app.services.pilot_success_service import PilotSuccessService
from app.services.platform_audit_service import PlatformAuditService
from app.services.system_health_dashboard_service import SystemHealthDashboardService

router = APIRouter(prefix="/platform-ops", tags=["platform-ops"])


# --- Pilot Program ---

@router.get("/pilot-program", response_model=PilotFactoryListResponse)
async def list_pilot_factories(
    status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await PilotProgramService.list_factories(db, status=status, skip=skip, limit=limit)
    return {"items": rows, "total": total}


@router.post("/pilot-program", response_model=PilotFactoryResponse)
async def create_pilot_factory(
    body: PilotFactoryCreate,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotProgramService.create_factory(db, body)


@router.patch("/pilot-program/{factory_id}", response_model=PilotFactoryResponse)
async def update_pilot_factory(
    factory_id: UUID,
    body: PilotFactoryUpdate,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotProgramService.update_factory(db, factory_id, body)


@router.delete("/pilot-program/{factory_id}")
async def delete_pilot_factory(
    factory_id: UUID,
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.manage")),
    db: AsyncSession = Depends(get_db),
):
    await PilotProgramService.delete_factory(db, factory_id)
    return {"message": "Pilot factory deleted"}


# --- Feedback ---

@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await FeedbackService.submit(
        db, body, tenant_id=user.tenant_id, user_id=user.id,
    )


@router.get("/feedback", response_model=FeedbackListResponse)
async def list_feedback(
    category: str | None = Query(default=None),
    feedback_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await FeedbackService.list_feedback(
        db, category=category, feedback_type=feedback_type, status=status,
        skip=skip, limit=limit,
    )
    return {"items": rows, "total": total}


@router.get("/feedback/my", response_model=FeedbackListResponse)
async def list_my_feedback(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows, total = await FeedbackService.list_feedback(
        db, tenant_id=user.tenant_id, skip=skip, limit=limit,
    )
    return {"items": rows, "total": total}


# --- System Health Dashboard ---

@router.get("/system-health", response_model=SystemHealthDashboardResponse)
async def system_health_dashboard(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SystemHealthDashboardService.overview(db),
        label="platform_ops.system_health",
    )


# --- Audit Logs ---

@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    tenant_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    actor_type: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await PlatformAuditService.list_logs(
        db, tenant_id=tenant_id, event_type=event_type, actor_type=actor_type,
        skip=skip, limit=limit,
    )
    return {"items": rows, "total": total}


@router.get("/audit-logs/my", response_model=AuditLogListResponse)
async def list_my_audit_logs(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    rows, total = await PlatformAuditService.list_logs(
        db, tenant_id=user.tenant_id, skip=skip, limit=limit,
    )
    return {"items": rows, "total": total}


# --- Error Tracking ---

@router.post("/errors", response_model=ErrorReportResponse)
async def report_error(
    body: ErrorReportCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = user.tenant_id if user else None
    user_id = user.id if user else None
    return await ErrorTrackingService.report(
        db, body, tenant_id=tenant_id, user_id=user_id,
    )


@router.get("/errors", response_model=ErrorReportListResponse)
async def list_errors(
    source: str | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await ErrorTrackingService.list_reports(
        db, source=source, tenant_id=tenant_id, skip=skip, limit=limit,
    )
    snapshot = ErrorTrackingService.in_memory_snapshot()
    return {
        "items": rows,
        "total": total,
        "in_memory_errors": snapshot["errors"],
        "categories": snapshot["categories"],
    }


# --- Pilot Success ---

@router.get("/pilot-success", response_model=PilotSuccessDashboardResponse)
async def pilot_success_dashboard(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await PilotSuccessService.dashboard(db)


# --- Launch Readiness ---

@router.get("/launch-readiness", response_model=LaunchReadinessResponse)
async def launch_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("tenants.read")),
    db: AsyncSession = Depends(get_db),
):
    return await LaunchReadinessService.score(db)
