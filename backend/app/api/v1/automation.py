"""Tenant Automation Center API."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.automation import (
    AutomationExecutionListResponse,
    AutomationFlowDetail,
    AutomationFlowListResponse,
    AutomationFlowUpdate,
    AutomationKpiResponse,
    AutomationManualRunResponse,
    AutomationStatusChangeResponse,
)
from app.services.automation_service import AutomationService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/automation", tags=["automation"])


@router.get("/kpis", response_model=AutomationKpiResponse)
async def automation_kpis(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AutomationService.get_kpis(db, user.tenant_id),
        label="automation.kpis",
    )


@router.get("/executions", response_model=AutomationExecutionListResponse)
async def list_automation_executions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    flow_id: UUID | None = None,
    status: str | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AutomationService.list_executions(
            db,
            user.tenant_id,
            page=page,
            page_size=page_size,
            flow_id=flow_id,
            status=status,
        ),
        label="automation.executions",
    )


@router.get("", response_model=AutomationFlowListResponse)
async def list_automation_flows(
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AutomationService.list_flows(
            db,
            user.tenant_id,
            status=status,
            category=category,
            search=search,
        ),
        label="automation.list",
    )


@router.get("/{flow_id}", response_model=AutomationFlowDetail)
async def get_automation_flow(
    flow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AutomationService.get_flow(db, user.tenant_id, flow_id),
        label="automation.get",
    )


@router.patch("/{flow_id}", response_model=AutomationFlowDetail)
async def update_automation_flow(
    flow_id: UUID,
    body: AutomationFlowUpdate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        AutomationService.update_flow(db, user.tenant_id, flow_id, body),
        label="automation.update",
    )


@router.post("/{flow_id}/enable", response_model=AutomationStatusChangeResponse)
async def enable_automation_flow(
    flow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AutomationService.enable_flow(db, user.tenant_id, flow_id),
        label="automation.enable",
    )
    await db.commit()
    return result


@router.post("/{flow_id}/pause", response_model=AutomationStatusChangeResponse)
async def pause_automation_flow(
    flow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AutomationService.pause_flow(db, user.tenant_id, flow_id),
        label="automation.pause",
    )
    await db.commit()
    return result


@router.post("/{flow_id}/run", response_model=AutomationManualRunResponse)
async def manual_run_automation_flow(
    flow_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AutomationService.manual_run(db, user.tenant_id, flow_id),
        label="automation.run",
    )
    await db.commit()
    return result
