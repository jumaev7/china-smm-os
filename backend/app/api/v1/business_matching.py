"""Business Matching Center API — B2B matching dashboard and discovery."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.business_matching import (
    BusinessMatchingBuyerListResponse,
    BusinessMatchingDashboardResponse,
    BusinessMatchingOpportunityCreate,
    BusinessMatchingOpportunityItem,
    BusinessMatchingOpportunityListResponse,
    BusinessMatchingOpportunityUpdate,
    BusinessMatchingSupplierListResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.business_matching_service import BusinessMatchingService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/business-matching", tags=["business-matching"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if admin:
        return None
    if user:
        return user.tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _require_matching_view(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> None:
    if admin:
        return
    if user:
        if user.has_permission("buyers.view") or user.has_permission("leads.view"):
            return
        raise HTTPException(status_code=403, detail="Permission denied")
    raise HTTPException(status_code=401, detail="Authentication required")


@router.get("/dashboard", response_model=BusinessMatchingDashboardResponse)
async def business_matching_dashboard(
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_matching_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BusinessMatchingService.dashboard(db, tenant_id),
        label="business-matching.dashboard",
    )


@router.get("/opportunities", response_model=BusinessMatchingOpportunityListResponse)
async def list_opportunities(
    country: str | None = None,
    industry: str | None = None,
    product_category: str | None = None,
    min_score: int | None = Query(None, ge=0, le=100),
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_matching_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BusinessMatchingService.list_opportunities(
            db, tenant_id,
            country=country,
            industry=industry,
            product_category=product_category,
            min_score=min_score,
            status=status,
            skip=skip,
            limit=limit,
        ),
        label="business-matching.opportunities",
    )


@router.get("/buyers", response_model=BusinessMatchingBuyerListResponse)
async def list_buyers(
    min_score: int = Query(0, ge=0, le=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_matching_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BusinessMatchingService.list_buyers(db, tenant_id, min_score=min_score, skip=skip, limit=limit),
        label="business-matching.buyers",
    )


@router.get("/suppliers", response_model=BusinessMatchingSupplierListResponse)
async def list_suppliers(
    min_score: int = Query(0, ge=0, le=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_matching_view(user, admin)
    tenant_id = _resolve_scope(user, admin)
    return await run_guarded(
        BusinessMatchingService.list_suppliers(db, tenant_id, min_score=min_score, skip=skip, limit=limit),
        label="business-matching.suppliers",
    )


@router.post("/opportunities", response_model=BusinessMatchingOpportunityItem)
async def create_opportunity(
    body: BusinessMatchingOpportunityCreate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    if admin:
        raise HTTPException(status_code=403, detail="Admin cannot create tenant opportunities")
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    TenantAuthService.assert_permission(user, "buyers.manage")
    try:
        return await BusinessMatchingService.create_opportunity(db, user.tenant_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/opportunities/{opportunity_id}", response_model=BusinessMatchingOpportunityItem)
async def update_opportunity(
    opportunity_id: UUID,
    body: BusinessMatchingOpportunityUpdate,
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_matching_view(user, admin)
    tenant_id = _resolve_scope(user, admin) if not admin else None
    if user and not user.has_permission("buyers.manage"):
        raise HTTPException(status_code=403, detail="Permission denied")
    try:
        return await BusinessMatchingService.update_opportunity(
            db, tenant_id if user else None, opportunity_id, body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
