"""Tenant Authentication v1 — tenant-scoped user management."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.core.tenant_access import get_current_tenant_user
from app.schemas.auth import AuthUserResponse
from app.schemas.tenant_auth import (
    TenantAuthUserCreateRequest,
    TenantAuthUserListResponse,
    TenantAuthUserUpdateRequest,
)
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/tenant-auth", tags=["tenant-auth"])


@router.get("/users", response_model=TenantAuthUserListResponse)
async def list_tenant_auth_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantAuthService.list_users(db, user, skip=skip, limit=limit)


@router.post("/users", response_model=AuthUserResponse, status_code=201)
async def create_tenant_auth_user(
    body: TenantAuthUserCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantAuthService.create_user(
        db,
        user,
        email=body.email,
        role=body.role,
        password=body.password,
        status=body.status,
    )


@router.patch("/users/{user_id}", response_model=AuthUserResponse)
async def update_tenant_auth_user(
    user_id: UUID,
    body: TenantAuthUserUpdateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantAuthService.update_user(
        db,
        user,
        user_id,
        role=body.role,
        email=body.email,
        password=body.password,
    )


@router.post("/users/{user_id}/disable", response_model=AuthUserResponse)
async def disable_tenant_auth_user(
    user_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantAuthService.set_user_status(db, user, user_id, status="suspended")


@router.post("/users/{user_id}/enable", response_model=AuthUserResponse)
async def enable_tenant_auth_user(
    user_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await TenantAuthService.set_user_status(db, user, user_id, status="active")
