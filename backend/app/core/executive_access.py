"""Executive Copilot — dual auth for platform admin or tenant owner access."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.admin_auth_service import TOKEN_TYPE_ADMIN_ACCESS, decode_admin_token
from app.services.admin_rbac_service import AdminRbacService, CurrentAdminUser
from app.services.auth_service import TOKEN_TYPE_ACCESS, decode_token
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

_bearer = HTTPBearer(auto_error=False)


@dataclass
class ExecutiveCopilotActor:
    kind: Literal["admin", "tenant"]
    admin: CurrentAdminUser | None = None
    tenant: CurrentTenantUser | None = None

    @property
    def tenant_id(self) -> UUID | None:
        if self.tenant:
            return self.tenant.tenant_id
        return None


async def get_executive_copilot_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: AsyncSession = Depends(get_db),
) -> ExecutiveCopilotActor:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    token = credentials.credentials

    try:
        admin_payload = decode_admin_token(token, expected_type=TOKEN_TYPE_ADMIN_ACCESS)
        admin = await AdminRbacService.resolve_current_admin(
            db,
            UUID(admin_payload["sub"]),
            UUID(admin_payload["session_id"]),
            access_nonce=admin_payload.get("access_nonce"),
        )
        if admin.role in {"super_admin", "platform_admin"} or admin.has_permission("business.read"):
            return ExecutiveCopilotActor(kind="admin", admin=admin)
    except HTTPException:
        pass

    try:
        tenant_payload = decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
        tenant = await TenantAuthService.resolve_current_user(db, UUID(tenant_payload["sub"]))
        if tenant.role == "owner" or tenant.has_permission("executive.copilot.view"):
            return ExecutiveCopilotActor(kind="tenant", tenant=tenant)
    except HTTPException:
        pass

    raise HTTPException(status_code=403, detail="Executive Copilot access denied")
