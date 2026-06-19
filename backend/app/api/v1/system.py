from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.api_error_buffer import error_counts_by_category, recent_errors, recent_slow
from app.core.database import get_db
from app.core.dependency_registry import dependency_graph
from app.core.endpoint_guard import run_guarded
from app.core.query_profiler import query_health_summary, slowest_requests
from app.schemas.system import (
    ApiHealthResponse,
    DemoResetResponse,
    DemoSeedResponse,
    DependenciesResponse,
    HealthSnapshotsResponse,
    I18nHealthResponse,
    QueryHealthResponse,
    RecentErrorsResponse,
    SchemaHealthResponse,
    SystemHealthResponse,
)
from app.services.admin_rbac_service import AdminRbacService, CurrentAdminUser
from app.services.api_health_service import ApiHealthService
from app.services.health_snapshot_service import HealthSnapshotService, list_snapshots
from app.services.i18n_health_service import I18nHealthService
from app.services.schema_health_service import SchemaHealthService
from app.services.system_health_service import SystemHealthService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=SystemHealthResponse)
async def system_health(db: AsyncSession = Depends(get_db)):
    return await run_guarded(
        SystemHealthService.health(db),
        label="system.health",
    )


@router.get("/schema-health", response_model=SchemaHealthResponse)
async def schema_health(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SchemaHealthService.check(db),
        label="system.schema_health",
    )


@router.get("/api-health", response_model=ApiHealthResponse)
async def api_health(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ApiHealthService.check(db),
        label="system.api_health",
    )


@router.get("/recent-errors", response_model=RecentErrorsResponse)
async def recent_api_errors(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
):
    return {
        "errors": recent_errors(),
        "slow": recent_slow(),
        "categories": error_counts_by_category(),
    }


@router.get("/query-health", response_model=QueryHealthResponse)
async def query_health(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
):
    return {
        "endpoints": query_health_summary(),
        "slowest_requests": slowest_requests(),
    }


@router.get("/dependencies", response_model=DependenciesResponse)
async def system_dependencies(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
    db: AsyncSession = Depends(get_db),
):
    graph = dependency_graph()
    security = await AdminRbacService.security_checks(db)
    graph["admin_security"] = security
    return graph


@router.get("/health-snapshots", response_model=HealthSnapshotsResponse)
async def health_snapshots(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
):
    return {
        "snapshots": list_snapshots(),
        "retention_hours": 48,
    }


@router.get("/i18n-health", response_model=I18nHealthResponse)
async def i18n_health(
    admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
):
    return I18nHealthService.check()


@router.post("/demo-seed", response_model=DemoSeedResponse)
async def demo_seed(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.full")),
    db: AsyncSession = Depends(get_db),
):
    return await SystemHealthService.demo_seed(db)


@router.post("/demo-reset", response_model=DemoResetResponse)
async def demo_reset(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.full")),
    db: AsyncSession = Depends(get_db),
):
    return await SystemHealthService.demo_reset(db)
