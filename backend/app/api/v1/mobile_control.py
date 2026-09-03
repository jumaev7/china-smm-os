"""Mobile Operator Control Plane API — thin read aggregation for future native apps.

Mutations remain on Operator Workspace / canonical domain endpoints.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import get_auth_context
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.mobile_control import (
    MobileControlHomeResponse,
    MobileControlSystemResponse,
)
from app.services.mobile_control_service import MobileControlService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/mobile-control", tags=["mobile-control"])

_bearer = HTTPBearer(auto_error=False)

# Same operational gate as Operator Workspace / Integration Health.
_MOBILE_ROLES = ("owner", "manager", "operator")


async def require_mobile_control_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentTenantUser | None:
    """Allow platform admins or tenant owner/manager/operator. Deny sales/viewer."""
    ctx = get_auth_context()
    if ctx and ctx.is_admin:
        return None
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = await get_current_tenant_user(credentials, db)
    TenantAuthService.assert_role(user, *_MOBILE_ROLES)
    return user


@router.get("/home", response_model=MobileControlHomeResponse)
async def mobile_control_home(
    client_id: UUID | None = None,
    urgent_limit: int = Query(10, ge=1, le=25),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(require_mobile_control_access),
):
    """Compact owner/operator home. No provider calls. No mutations."""
    tenant_id = user.tenant_id if user is not None else None

    return await run_guarded(
        MobileControlService.get_home(
            db,
            client_id=client_id,
            urgent_limit=urgent_limit,
            tenant_id=tenant_id,
        ),
        label="mobile-control.home",
    )


@router.get("/system", response_model=MobileControlSystemResponse)
async def mobile_control_system(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentTenantUser | None = Depends(require_mobile_control_access),
):
    """SYSTEM tab — sanitized health + integration attention count. No secrets."""
    return await run_guarded(
        MobileControlService.get_system(db, client_id=client_id),
        label="mobile-control.system",
    )
