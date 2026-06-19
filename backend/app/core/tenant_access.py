"""Tenant Authentication & Access Control v1 — FastAPI dependencies."""
from __future__ import annotations

from typing import Annotated, Callable
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.auth_service import TOKEN_TYPE_ACCESS, decode_token
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

_bearer = HTTPBearer(auto_error=False)


async def get_current_tenant_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> CurrentTenantUser:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = decode_token(credentials.credentials, expected_type=TOKEN_TYPE_ACCESS)
    user_id = UUID(payload["sub"])
    return await TenantAuthService.resolve_current_user(db, user_id)


async def get_current_tenant_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> CurrentTenantUser | None:
    if not credentials or not credentials.credentials:
        return None
    try:
        payload = decode_token(credentials.credentials, expected_type=TOKEN_TYPE_ACCESS)
        user_id = UUID(payload["sub"])
        return await TenantAuthService.resolve_current_user(db, user_id)
    except HTTPException:
        return None


def require_tenant(tenant_id: UUID, user: CurrentTenantUser) -> None:
    TenantAuthService.assert_tenant_access(user, tenant_id)


def require_role(*roles: str) -> Callable:
    async def _dep(user: CurrentTenantUser = Depends(get_current_tenant_user)) -> CurrentTenantUser:
        TenantAuthService.assert_role(user, *roles)
        return user

    return _dep


def require_permission(permission: str) -> Callable:
    async def _dep(user: CurrentTenantUser = Depends(get_current_tenant_user)) -> CurrentTenantUser:
        TenantAuthService.assert_permission(user, permission)
        return user

    return _dep


def tenant_scope_filter(user: CurrentTenantUser, tenant_id_column):
    """SQLAlchemy filter — restrict query to the authenticated user's tenant."""
    return tenant_id_column == user.tenant_id
