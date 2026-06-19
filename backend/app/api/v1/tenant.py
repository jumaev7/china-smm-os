"""Multi-Tenant SaaS Foundation v1 — tenant management API."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user, require_tenant
from app.schemas.tenant import (
    TenantCreateRequest,
    TenantCreateResponse,
    TenantDashboardResponse,
    TenantIsolationCheckResponse,
    TenantListResponse,
    TenantResponse,
    TenantUpdateRequest,
    TenantUserCreateRequest,
    TenantUserListResponse,
    TenantUserResponse,
)
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=TenantListResponse)
async def list_tenants(
    status: str | None = Query(None, description="pending | active | suspended | archived"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.full")
    detail = await TenantService.get_tenant_detail(db, user.tenant_id)
    tenant = detail["tenant"]
    if status and tenant["status"] != status:
        return {"items": [], "total": 0}
    return {"items": [tenant], "total": 1}


@router.post("", response_model=TenantCreateResponse, status_code=201)
async def create_tenant(
    body: TenantCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.full")
    raise HTTPException(
        status_code=403,
        detail="Tenant creation via API is restricted — use factory partner workflow",
    )


@router.get("/{tenant_id}", response_model=TenantDashboardResponse)
async def get_tenant(
    tenant_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.full")
    require_tenant(tenant_id, user)
    return await run_guarded(
        TenantService.get_tenant_detail(db, tenant_id),
        label="tenants.detail",
    )


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def patch_tenant(
    tenant_id: UUID,
    body: TenantUpdateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.full")
    require_tenant(tenant_id, user)
    payload = body.model_dump(exclude_unset=True)
    return await TenantService.update_tenant(db, tenant_id, payload)


@router.get("/{tenant_id}/users", response_model=TenantUserListResponse)
async def list_tenant_users(
    tenant_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "users.manage")
    require_tenant(tenant_id, user)
    return await TenantService.list_users(db, tenant_id, skip=skip, limit=limit)


@router.post("/{tenant_id}/users", response_model=TenantUserResponse, status_code=201)
async def create_tenant_user(
    tenant_id: UUID,
    body: TenantUserCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "users.manage")
    require_tenant(tenant_id, user)
    return await TenantService.add_tenant_user(
        db,
        tenant_id,
        email=body.email,
        role=body.role,
        status=body.status,
    )


@router.get("/{tenant_id}/isolation-check", response_model=TenantIsolationCheckResponse)
async def tenant_isolation_check(
    tenant_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    TenantAuthService.assert_permission(user, "tenant.full")
    require_tenant(tenant_id, user)
    return await TenantService.isolation_check(db, tenant_id)
