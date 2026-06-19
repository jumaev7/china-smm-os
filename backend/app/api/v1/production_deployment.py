"""Production Deployment Preparation v1 — readiness assessment endpoints (read-only)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.production_deployment import (
    ProductionBackupReadiness,
    ProductionDeploymentChecklist,
    ProductionDeploymentOverview,
    ProductionDeploymentRefreshResponse,
    ProductionDeploymentSummaryWidget,
    ProductionEnvironmentValidation,
    ProductionMonitoringReadiness,
    ProductionReadiness,
    ProductionSecurityReadiness,
    ProductionSummary,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.production_deployment_service import ProductionDeploymentService

router = APIRouter(prefix="/production-deployment", tags=["production-deployment"])


@router.get("/overview", response_model=ProductionDeploymentOverview)
async def production_deployment_overview(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProductionDeploymentService.overview(db),
        label="production_deployment.overview",
    )


@router.get("/readiness", response_model=ProductionReadiness)
async def production_deployment_readiness(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await ProductionDeploymentService.readiness(db)


@router.get("/environment", response_model=ProductionEnvironmentValidation)
async def production_deployment_environment(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
):
    return await ProductionDeploymentService.environment_validation()


@router.get("/checklist", response_model=ProductionDeploymentChecklist)
async def production_deployment_checklist(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await ProductionDeploymentService.checklist(db)


@router.get("/backups", response_model=ProductionBackupReadiness)
async def production_deployment_backups(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
):
    return await ProductionDeploymentService.backup_readiness()


@router.get("/monitoring", response_model=ProductionMonitoringReadiness)
async def production_deployment_monitoring(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await ProductionDeploymentService.monitoring_readiness(db)


@router.get("/security", response_model=ProductionSecurityReadiness)
async def production_deployment_security(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await ProductionDeploymentService.security_readiness(db)


@router.get("/summary", response_model=ProductionSummary)
async def production_deployment_summary(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await ProductionDeploymentService.summary(db)


@router.get("/summary-widget", response_model=ProductionDeploymentSummaryWidget)
async def production_deployment_summary_widget(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await ProductionDeploymentService.summary_widget(db)


@router.post("/refresh", response_model=ProductionDeploymentRefreshResponse)
async def production_deployment_refresh(
    admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
    db: AsyncSession = Depends(get_db),
):
    return await ProductionDeploymentService.refresh(db)
