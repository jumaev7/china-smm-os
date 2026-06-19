"""Subscription & Billing v1 API — architecture only, no payment processing."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user, require_tenant
from app.schemas.subscription import (
    BillingSummaryResponse,
    CreateSubscriptionRequest,
    InvoiceListResponse,
    PlanListResponse,
    SubscriptionActionRequest,
    SubscriptionListResponse,
    SubscriptionResponse,
    SubscriptionSummaryWidget,
    UsageSummaryResponse,
)
from app.services.subscription_service import SubscriptionService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/billing", tags=["subscription-billing"])


def _scoped_tenant_id(user: CurrentTenantUser, tenant_id: UUID | None) -> UUID:
    if tenant_id is None:
        return user.tenant_id
    require_tenant(tenant_id, user)
    return tenant_id


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    return await run_guarded(
        SubscriptionService.list_plans(db),
        label="billing.plans",
    )


@router.get("/subscriptions", response_model=SubscriptionListResponse)
async def list_subscriptions(
    tenant_id: UUID | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    scoped = _scoped_tenant_id(user, tenant_id)
    return await run_guarded(
        SubscriptionService.list_subscriptions(
            db, tenant_id=scoped, status=status, skip=skip, limit=limit,
        ),
        label="billing.subscriptions",
    )


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    tenant_id: UUID | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    scoped = _scoped_tenant_id(user, tenant_id)
    return await run_guarded(
        SubscriptionService.list_invoices(
            db, tenant_id=scoped, status=status, skip=skip, limit=limit,
        ),
        label="billing.invoices",
    )


@router.get("/usage", response_model=UsageSummaryResponse)
async def billing_usage(
    tenant_id: UUID = Query(..., description="Tenant ID for usage scope"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    require_tenant(tenant_id, user)
    return await run_guarded(
        SubscriptionService.usage(db, tenant_id),
        label="billing.usage",
    )


@router.get("/summary", response_model=BillingSummaryResponse)
async def billing_summary(
    tenant_id: UUID = Query(..., description="Tenant ID for billing summary"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    require_tenant(tenant_id, user)
    return await run_guarded(
        SubscriptionService.summary(db, tenant_id),
        label="billing.summary",
    )


@router.get("/summary-widget", response_model=SubscriptionSummaryWidget)
async def billing_summary_widget(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.view")
    return await run_guarded(
        SubscriptionService.summary_widget(db, tenant_id=user.tenant_id),
        label="billing.summary_widget",
    )


@router.post("/create-subscription", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    body: CreateSubscriptionRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.manage")
    require_tenant(body.tenant_id, user)
    return await SubscriptionService.create_subscription(
        db,
        tenant_id=body.tenant_id,
        plan_code=body.plan_code,
        billing_cycle=body.billing_cycle,
        status=body.status,
    )


@router.post("/activate", response_model=SubscriptionResponse)
async def activate_subscription(
    body: SubscriptionActionRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.manage")
    sub = await SubscriptionService.get_subscription(db, body.subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    require_tenant(sub.tenant_id, user)
    return await SubscriptionService.activate_subscription(db, body.subscription_id)


@router.post("/suspend", response_model=SubscriptionResponse)
async def suspend_subscription(
    body: SubscriptionActionRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.manage")
    sub = await SubscriptionService.get_subscription(db, body.subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    require_tenant(sub.tenant_id, user)
    return await SubscriptionService.suspend_subscription(db, body.subscription_id)


@router.post("/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    body: SubscriptionActionRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "billing.manage")
    sub = await SubscriptionService.get_subscription(db, body.subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    require_tenant(sub.tenant_id, user)
    return await SubscriptionService.cancel_subscription(db, body.subscription_id)
