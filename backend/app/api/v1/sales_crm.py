"""Tenant-scoped Sales CRM API — leads, customers, deals, activities."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user, get_current_tenant_user_optional
from app.schemas.sales_crm import (
    SalesActivityCreate,
    SalesActivityListResponse,
    SalesActivityResponse,
    SalesCustomerCreate,
    SalesCustomerListResponse,
    SalesCustomerResponse,
    SalesCustomerUpdate,
    SalesDashboardResponse,
    SalesDealCreate,
    SalesDealListResponse,
    SalesDealResponse,
    SalesDealStageUpdate,
    SalesDealUpdate,
    SalesLeadCreate,
    SalesLeadListResponse,
    SalesLeadResponse,
    SalesLeadUpdate,
    SalesProposalCreate,
    SalesProposalListResponse,
    SalesProposalResponse,
    SalesProposalStatusUpdate,
    SalesProposalUpdate,
)
from app.models.sales_crm import SalesDeal, SalesLead
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.sales_crm_service import SalesCrmService
from app.services.sales_proposal_service import SalesProposalService
from app.services.platform_relationships_service import PlatformRelationshipsService
from app.schemas.platform_relationships import PlatformRelationshipsResponse
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/sales-crm", tags=["sales-crm"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_leads_view(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "leads.view")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_leads_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "leads.manage")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_deals_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "deals.manage")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_proposals_view(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "proposals.view")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_proposals_manage(user: CurrentTenantUser | None, admin: CurrentAdminUser | None) -> None:
    if admin:
        return
    if user:
        TenantAuthService.assert_permission(user, "proposals.manage")
        return
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/dashboard", response_model=SalesDashboardResponse)
async def sales_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        SalesCrmService.dashboard(db, tenant_id),
        label="sales-crm.dashboard",
    )


@router.get("/customers", response_model=SalesCustomerListResponse)
async def list_customers(
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await SalesCrmService.list_customers(
        db, tenant_id, search=search, skip=skip, limit=limit,
    )
    return SalesCustomerListResponse(items=items, total=total)


@router.get("/customers/{customer_id}", response_model=SalesCustomerResponse)
async def get_customer(
    customer_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    customer = await SalesCrmService.get_customer(db, customer_id, tenant_id)
    deal_count = (await db.execute(
        select(func.count()).select_from(SalesDeal).where(SalesDeal.customer_id == customer.id)
    )).scalar_one()
    lead_count = (await db.execute(
        select(func.count()).select_from(SalesLead).where(SalesLead.customer_id == customer.id)
    )).scalar_one()
    base = SalesCustomerResponse.model_validate(customer)
    return base.model_copy(update={"deal_count": deal_count, "lead_count": lead_count})


@router.post("/customers", response_model=SalesCustomerResponse, status_code=201)
async def create_customer(
    body: SalesCustomerCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "leads.manage")
    row = await SalesCrmService.create_customer(db, body, tenant_id=user.tenant_id)
    base = SalesCustomerResponse.model_validate(row)
    return base.model_copy(update={"deal_count": 0, "lead_count": 0})


@router.patch("/customers/{customer_id}", response_model=SalesCustomerResponse)
async def update_customer(
    customer_id: UUID,
    body: SalesCustomerUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    row = await SalesCrmService.update_customer(db, customer_id, body, tenant_id)
    base = SalesCustomerResponse.model_validate(row)
    return base.model_copy(update={"deal_count": 0, "lead_count": 0})


@router.delete("/customers/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await SalesCrmService.delete_customer(db, customer_id, tenant_id)


@router.get("/leads", response_model=SalesLeadListResponse)
async def list_leads(
    search: str | None = None,
    status: str | None = None,
    source: str | None = None,
    priority: str | None = None,
    customer_id: UUID | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await SalesCrmService.list_leads(
        db, tenant_id, search=search, status=status, source=source,
        priority=priority, customer_id=customer_id, skip=skip, limit=limit,
    )
    return SalesLeadListResponse(items=items, total=total)


@router.get("/leads/{lead_id}", response_model=SalesLeadResponse)
async def get_lead(
    lead_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesCrmService.get_lead(db, lead_id, tenant_id)


@router.get("/leads/{lead_id}/related", response_model=PlatformRelationshipsResponse)
async def get_lead_related(
    lead_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await PlatformRelationshipsService.for_lead(db, lead_id, tenant_id)


@router.post("/leads", response_model=SalesLeadResponse, status_code=201)
async def create_lead(
    body: SalesLeadCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "leads.manage")
    return await SalesCrmService.create_lead(
        db, body, tenant_id=user.tenant_id, created_by=user.email,
    )


@router.patch("/leads/{lead_id}", response_model=SalesLeadResponse)
async def update_lead(
    lead_id: UUID,
    body: SalesLeadUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesCrmService.update_lead(db, lead_id, body, tenant_id)


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await SalesCrmService.delete_lead(db, lead_id, tenant_id)


@router.get("/deals", response_model=SalesDealListResponse)
async def list_deals(
    stage: str | None = None,
    customer_id: UUID | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await SalesCrmService.list_deals(
        db, tenant_id, stage=stage, customer_id=customer_id, skip=skip, limit=limit,
    )
    return SalesDealListResponse(items=items, total=total)


@router.get("/deals/{deal_id}", response_model=SalesDealResponse)
async def get_deal(
    deal_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesCrmService.get_deal(db, deal_id, tenant_id)


@router.get("/deals/{deal_id}/related", response_model=PlatformRelationshipsResponse)
async def get_deal_related(
    deal_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await PlatformRelationshipsService.for_deal(db, deal_id, tenant_id)


@router.post("/deals", response_model=SalesDealResponse, status_code=201)
async def create_deal(
    body: SalesDealCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "deals.manage")
    return await SalesCrmService.create_deal(
        db, body, tenant_id=user.tenant_id, created_by=user.email,
    )


@router.patch("/deals/{deal_id}", response_model=SalesDealResponse)
async def update_deal(
    deal_id: UUID,
    body: SalesDealUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_deals_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesCrmService.update_deal(db, deal_id, body, tenant_id)


@router.patch("/deals/{deal_id}/stage", response_model=SalesDealResponse)
async def move_deal_stage(
    deal_id: UUID,
    body: SalesDealStageUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_deals_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesCrmService.move_deal_stage(
        db, deal_id, body, tenant_id, created_by=user.email if user else None,
    )


@router.delete("/deals/{deal_id}", status_code=204)
async def delete_deal(
    deal_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_deals_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await SalesCrmService.delete_deal(db, deal_id, tenant_id)


@router.get("/activities", response_model=SalesActivityListResponse)
async def list_activities(
    lead_id: UUID | None = None,
    customer_id: UUID | None = None,
    deal_id: UUID | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_leads_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await SalesCrmService.list_activities(
        db, tenant_id, lead_id=lead_id, customer_id=customer_id,
        deal_id=deal_id, skip=skip, limit=limit,
    )
    return SalesActivityListResponse(items=items, total=total)


@router.post("/activities", response_model=SalesActivityResponse, status_code=201)
async def create_activity(
    body: SalesActivityCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "leads.manage")
    return await SalesCrmService.create_activity(
        db, body, tenant_id=user.tenant_id, created_by=user.email,
    )


# ─── Commercial Proposals ────────────────────────────────────────────────────


@router.get("/proposals", response_model=SalesProposalListResponse)
async def list_proposals(
    search: str | None = None,
    status: str | None = None,
    customer_id: UUID | None = None,
    deal_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_proposals_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    items, total = await SalesProposalService.list_proposals(
        db, tenant_id, search=search, status=status, customer_id=customer_id,
        deal_id=deal_id, date_from=date_from, date_to=date_to, skip=skip, limit=limit,
    )
    return SalesProposalListResponse(items=items, total=total)


@router.get("/proposals/{proposal_id}", response_model=SalesProposalResponse)
async def get_proposal(
    proposal_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_proposals_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesProposalService.get_proposal(db, proposal_id, tenant_id)


@router.get("/proposals/{proposal_id}/related", response_model=PlatformRelationshipsResponse)
async def get_proposal_related(
    proposal_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_proposals_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await PlatformRelationshipsService.for_proposal(db, proposal_id, tenant_id)


@router.post("/proposals", response_model=SalesProposalResponse, status_code=201)
async def create_proposal(
    body: SalesProposalCreate,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "proposals.manage")
    return await SalesProposalService.create_proposal(db, body, tenant_id=user.tenant_id)


@router.post("/proposals/from-lead/{lead_id}", response_model=SalesProposalResponse, status_code=201)
async def create_proposal_from_lead(
    lead_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "proposals.manage")
    return await SalesProposalService.create_from_lead(db, lead_id, tenant_id=user.tenant_id)


@router.post("/proposals/from-deal/{deal_id}", response_model=SalesProposalResponse, status_code=201)
async def create_proposal_from_deal(
    deal_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "proposals.manage")
    return await SalesProposalService.create_from_deal(db, deal_id, tenant_id=user.tenant_id)


@router.patch("/proposals/{proposal_id}", response_model=SalesProposalResponse)
async def update_proposal(
    proposal_id: UUID,
    body: SalesProposalUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_proposals_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesProposalService.update_proposal(db, proposal_id, body, tenant_id)


@router.patch("/proposals/{proposal_id}/status", response_model=SalesProposalResponse)
async def update_proposal_status(
    proposal_id: UUID,
    body: SalesProposalStatusUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_proposals_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesProposalService.update_status(db, proposal_id, body, tenant_id)


@router.post("/proposals/{proposal_id}/duplicate", response_model=SalesProposalResponse, status_code=201)
async def duplicate_proposal(
    proposal_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_proposals_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await SalesProposalService.duplicate_proposal(db, proposal_id, tenant_id)


@router.delete("/proposals/{proposal_id}", status_code=204)
async def delete_proposal(
    proposal_id: UUID,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_proposals_manage(user, admin)
    tenant_id = _resolve_scope(user, admin)
    await SalesProposalService.delete_proposal(db, proposal_id, tenant_id)
