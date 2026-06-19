"""Customer Portal v1 — company-scoped read-only endpoints for factory partners."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user, require_tenant
from app.schemas.customer_portal import (
    CustomerPortalAccountListResponse,
    CustomerPortalBillingResponse,
    CustomerPortalBuyersResponse,
    CustomerPortalDashboardResponse,
    CustomerPortalDealsResponse,
    CustomerPortalProposalsResponse,
    CustomerPortalReportsResponse,
    CustomerPortalSummaryWidget,
)
from app.services.customer_portal_service import CustomerPortalService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/customer-portal", tags=["customer-portal"])


@router.get("/summary-widget", response_model=CustomerPortalSummaryWidget)
async def customer_portal_summary_widget(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await CustomerPortalService.summary_widget(db, tenant_id=user.tenant_id)


@router.get("/accounts", response_model=CustomerPortalAccountListResponse)
async def list_customer_portal_accounts(
    portal_status: str | None = Query(None, description="pending | active | suspended"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await CustomerPortalService.list_accounts(
        db, portal_status=portal_status, skip=skip, limit=limit, tenant_id=user.tenant_id,
    )


@router.get("/dashboard", response_model=CustomerPortalDashboardResponse)
async def customer_portal_dashboard(
    portal_account_id: UUID = Query(..., description="Active portal account ID (company scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await TenantAuthService.validate_portal_account_access(db, user, portal_account_id)
    return await run_guarded(
        CustomerPortalService.dashboard(db, portal_account_id),
        label="customer_portal.dashboard",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/buyers", response_model=CustomerPortalBuyersResponse)
async def customer_portal_buyers(
    portal_account_id: UUID = Query(..., description="Active portal account ID (company scope)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await TenantAuthService.validate_portal_account_access(db, user, portal_account_id)
    return await run_guarded(
        CustomerPortalService.buyers(db, portal_account_id, skip=skip, limit=limit),
        label="customer_portal.buyers",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/deals", response_model=CustomerPortalDealsResponse)
async def customer_portal_deals(
    portal_account_id: UUID = Query(..., description="Active portal account ID (company scope)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await TenantAuthService.validate_portal_account_access(db, user, portal_account_id)
    return await run_guarded(
        CustomerPortalService.deals(db, portal_account_id, skip=skip, limit=limit),
        label="customer_portal.deals",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/proposals", response_model=CustomerPortalProposalsResponse)
async def customer_portal_proposals(
    portal_account_id: UUID = Query(..., description="Active portal account ID (company scope)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await TenantAuthService.validate_portal_account_access(db, user, portal_account_id)
    return await run_guarded(
        CustomerPortalService.proposals(db, portal_account_id, skip=skip, limit=limit),
        label="customer_portal.proposals",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/reports", response_model=CustomerPortalReportsResponse)
async def customer_portal_reports(
    portal_account_id: UUID = Query(..., description="Active portal account ID (company scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await TenantAuthService.validate_portal_account_access(db, user, portal_account_id)
    return await run_guarded(
        CustomerPortalService.reports(db, portal_account_id),
        label="customer_portal.reports",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/billing", response_model=CustomerPortalBillingResponse)
async def customer_portal_billing(
    portal_account_id: UUID = Query(..., description="Active portal account ID (company scope)"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    await TenantAuthService.validate_portal_account_access(db, user, portal_account_id)
    return await run_guarded(
        CustomerPortalService.billing(db, portal_account_id),
        label="customer_portal.billing",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/factory-snapshot")
async def customer_portal_factory_snapshot(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.factory_profile_service import FactoryProfileService

    TenantAuthService.assert_permission(user, "tenant.read")
    return await run_guarded(
        FactoryProfileService.factory_snapshot(db, tenant_id=user.tenant_id),
        label="customer_portal.factory_snapshot",
        timeout=SCAN_TIMEOUT_SEC,
    )
