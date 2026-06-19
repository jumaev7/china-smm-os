"""Admin Authentication & RBAC v1 — FastAPI dependencies."""
from __future__ import annotations

from typing import Annotated, Callable
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.admin_auth_service import TOKEN_TYPE_ADMIN_ACCESS, decode_admin_token
from app.services.admin_rbac_service import AdminRbacService, CurrentAdminUser

_admin_bearer = HTTPBearer(auto_error=False)


async def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin_bearer)],
    db: AsyncSession = Depends(get_db),
) -> CurrentAdminUser:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    payload = decode_admin_token(credentials.credentials, expected_type=TOKEN_TYPE_ADMIN_ACCESS)
    user_id = UUID(payload["sub"])
    session_id = UUID(payload["session_id"])
    access_nonce = payload.get("access_nonce")
    return await AdminRbacService.resolve_current_admin(
        db, user_id, session_id, access_nonce=access_nonce,
    )


async def get_current_admin_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin_bearer)],
    db: AsyncSession = Depends(get_db),
) -> CurrentAdminUser | None:
    if not credentials or not credentials.credentials:
        return None
    try:
        payload = decode_admin_token(credentials.credentials, expected_type=TOKEN_TYPE_ADMIN_ACCESS)
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["session_id"])
        access_nonce = payload.get("access_nonce")
        return await AdminRbacService.resolve_current_admin(
            db, user_id, session_id, access_nonce=access_nonce,
        )
    except HTTPException:
        return None


def require_admin() -> Callable:
    async def _dep(admin: CurrentAdminUser = Depends(get_current_admin)) -> CurrentAdminUser:
        return admin

    return _dep


def require_admin_role(*roles: str) -> Callable:
    async def _dep(
        admin: CurrentAdminUser = Depends(get_current_admin),
        db: AsyncSession = Depends(get_db),
    ) -> CurrentAdminUser:
        if admin.role in roles or admin.has_permission("platform.full"):
            await AdminRbacService.record_audit(
                db,
                admin_user_id=admin.id,
                event_type="role_check",
                action="admin_role_granted",
                details=f'{{"required_roles": {list(roles)}, "role": "{admin.role}"}}',
                success=True,
            )
            return admin
        await AdminRbacService.record_audit(
            db,
            admin_user_id=admin.id,
            event_type="role_check",
            action="admin_role_denied",
            details=f'{{"required_roles": {list(roles)}, "role": "{admin.role}"}}',
            success=False,
        )
        raise HTTPException(
            status_code=403,
            detail=f"Admin role '{admin.role}' is not allowed for this action",
        )

    return _dep


def require_admin_permission(permission: str) -> Callable:
    async def _dep(
        admin: CurrentAdminUser = Depends(get_current_admin),
        db: AsyncSession = Depends(get_db),
    ) -> CurrentAdminUser:
        await AdminRbacService.assert_permission_async(db, admin, permission)
        return admin

    return _dep
