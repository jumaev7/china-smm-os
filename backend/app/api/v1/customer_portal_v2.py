"""Customer Portal v2 — tenant-scoped partner workspace (read-only)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user
from app.schemas.customer_portal_v2 import (
    CustomerPortalV2BillingResponse,
    CustomerPortalV2DashboardResponse,
    CustomerPortalV2DealsResponse,
    CustomerPortalV2FactorySnapshotResponse,
    CustomerPortalV2OpportunitiesResponse,
    CustomerPortalV2ProposalsResponse,
    CustomerPortalV2ReportsResponse,
    CustomerPortalV2SummaryWidget,
)
from app.services.customer_portal_v2_service import CustomerPortalV2Service
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/customer-portal-v2", tags=["customer-portal-v2"])


@router.get("/summary-widget", response_model=CustomerPortalV2SummaryWidget)
async def customer_portal_v2_summary_widget(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await CustomerPortalV2Service.summary_widget(db, user.tenant_id)


@router.get("/dashboard", response_model=CustomerPortalV2DashboardResponse)
async def customer_portal_v2_dashboard(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await run_guarded(
        CustomerPortalV2Service.dashboard(db, user.tenant_id),
        label="customer_portal_v2.dashboard",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/opportunities", response_model=CustomerPortalV2OpportunitiesResponse)
async def customer_portal_v2_opportunities(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await run_guarded(
        CustomerPortalV2Service.opportunities(
            db, user.tenant_id, skip=skip, limit=limit,
        ),
        label="customer_portal_v2.opportunities",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/deals", response_model=CustomerPortalV2DealsResponse)
async def customer_portal_v2_deals(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await run_guarded(
        CustomerPortalV2Service.deals(db, user.tenant_id, skip=skip, limit=limit),
        label="customer_portal_v2.deals",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/proposals", response_model=CustomerPortalV2ProposalsResponse)
async def customer_portal_v2_proposals(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await run_guarded(
        CustomerPortalV2Service.proposals(db, user.tenant_id, skip=skip, limit=limit),
        label="customer_portal_v2.proposals",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/reports", response_model=CustomerPortalV2ReportsResponse)
async def customer_portal_v2_reports(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await run_guarded(
        CustomerPortalV2Service.reports(db, user.tenant_id),
        label="customer_portal_v2.reports",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/billing", response_model=CustomerPortalV2BillingResponse)
async def customer_portal_v2_billing(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    return await run_guarded(
        CustomerPortalV2Service.billing(db, user.tenant_id),
        label="customer_portal_v2.billing",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/factory-snapshot", response_model=CustomerPortalV2FactorySnapshotResponse)
async def customer_portal_v2_factory_snapshot(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.read")
    return await run_guarded(
        CustomerPortalV2Service.factory_snapshot(db, user.tenant_id),
        label="customer_portal_v2.factory_snapshot",
        timeout=SCAN_TIMEOUT_SEC,
    )
