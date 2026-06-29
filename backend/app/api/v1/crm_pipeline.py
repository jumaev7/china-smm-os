"""Executive CRM pipeline API — stage transitions, timeline, notes, meetings."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.crm_pipeline import (
    CrmPipelineEventListResponse,
    CrmPipelineEventResponse,
    PipelineMeetingCreate,
    PipelineNoteCreate,
    PipelineStageUpdate,
)
from app.schemas.sales_crm import SalesDealListResponse, SalesDealResponse
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.crm_pipeline_service import CrmPipelineService
from app.services.publishing_tenant_scope import resolve_publishing_tenant_id
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService
from app.core.tenant_access import get_current_tenant_user_optional

router = APIRouter(prefix="/crm-pipeline", tags=["crm-pipeline"])


def _resolve_tenant_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
    tenant_id: UUID | None,
) -> UUID:
    return resolve_publishing_tenant_id(user, admin, tenant_id)


def _require_pipeline_view(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "leads.view")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_pipeline_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "deals.manage")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/deals", response_model=SalesDealListResponse)
async def list_pipeline_deals(
    stage: str | None = None,
    customer_id: UUID | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_pipeline_view(user, admin)
    scope = _resolve_tenant_scope(user, admin, tenant_id)
    items, total = await run_guarded(
        CrmPipelineService.list_pipeline_deals(
            db, scope, stage=stage, customer_id=customer_id, skip=skip, limit=limit,
        ),
        label="crm-pipeline.deals.list",
    )
    return SalesDealListResponse(items=items, total=total)


@router.patch("/deals/{deal_id}/stage", response_model=SalesDealResponse)
async def update_deal_stage(
    deal_id: UUID,
    body: PipelineStageUpdate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_pipeline_manage(user, admin)
    scope = _resolve_tenant_scope(user, admin, tenant_id)
    return await run_guarded(
        CrmPipelineService.transition_stage(
            db,
            deal_id,
            scope,
            body,
            stage_source="manual",
            actor=user.email if user else (admin.email if admin else None),
        ),
        label="crm-pipeline.deals.stage",
    )


@router.get("/deals/{deal_id}/timeline", response_model=CrmPipelineEventListResponse)
async def get_deal_timeline(
    deal_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_pipeline_view(user, admin)
    scope = _resolve_tenant_scope(user, admin, tenant_id)
    items, total = await run_guarded(
        CrmPipelineService.get_deal_timeline(db, deal_id, scope, skip=skip, limit=limit),
        label="crm-pipeline.deals.timeline",
    )
    return CrmPipelineEventListResponse(
        items=[CrmPipelineEventResponse.model_validate(e) for e in items],
        total=total,
    )


@router.get("/leads/{lead_id}/timeline", response_model=CrmPipelineEventListResponse)
async def get_lead_timeline(
    lead_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_pipeline_view(user, admin)
    scope = _resolve_tenant_scope(user, admin, tenant_id)
    items, total = await run_guarded(
        CrmPipelineService.get_lead_timeline(db, lead_id, scope, skip=skip, limit=limit),
        label="crm-pipeline.leads.timeline",
    )
    return CrmPipelineEventListResponse(
        items=[CrmPipelineEventResponse.model_validate(e) for e in items],
        total=total,
    )


@router.post("/deals/{deal_id}/notes", response_model=CrmPipelineEventResponse, status_code=201)
async def add_deal_note(
    deal_id: UUID,
    body: PipelineNoteCreate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_pipeline_manage(user, admin)
    scope = _resolve_tenant_scope(user, admin, tenant_id)
    actor = user.email if user else (admin.email if admin else None)
    result = await run_guarded(
        CrmPipelineService.add_note(
            db, deal_id, scope, body, actor=actor,
        ),
        label="crm-pipeline.deals.notes",
    )
    event = result["event"]
    if not event:
        raise HTTPException(status_code=500, detail="Failed to create timeline note")
    return CrmPipelineEventResponse.model_validate(event)


@router.post("/deals/{deal_id}/meetings")
async def schedule_deal_meeting(
    deal_id: UUID,
    body: PipelineMeetingCreate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_pipeline_manage(user, admin)
    scope = _resolve_tenant_scope(user, admin, tenant_id)
    actor = user.email if user else (admin.email if admin else None)
    return await run_guarded(
        CrmPipelineService.schedule_meeting(
            db, deal_id, scope, body, actor=actor,
        ),
        label="crm-pipeline.deals.meetings",
    )
