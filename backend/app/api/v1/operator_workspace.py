"""Operator Workspace Phase 1 — daily operational attention aggregation."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import get_auth_context
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.operator_workspace import (
    AttentionCategory,
    AttentionPriority,
    OperatorWorkspaceItemsResponse,
    OperatorWorkspaceSummaryResponse,
    ResponsibleParty,
)
from app.services.operator_workspace_service import OperatorWorkspaceService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/operator-workspace", tags=["operator-workspace"])

_bearer = HTTPBearer(auto_error=False)

# Operational daily queue — not a general CRM/sales surface.
_WORKSPACE_ROLES = ("owner", "manager", "operator")


async def require_operator_workspace_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentTenantUser | None:
    """Allow platform admins or tenant owner/manager/operator. Deny sales/viewer."""
    ctx = get_auth_context()
    if ctx and ctx.is_admin:
        return None
    if not credentials or not credentials.credentials:
        # Middleware should already reject anonymous; keep explicit for clarity.
        raise HTTPException(status_code=401, detail="Authentication required")
    user = await get_current_tenant_user(credentials, db)
    TenantAuthService.assert_role(user, *_WORKSPACE_ROLES)
    return user


@router.get("/summary", response_model=OperatorWorkspaceSummaryResponse)
async def operator_workspace_summary(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _user: CurrentTenantUser | None = Depends(require_operator_workspace_access),
):
    return await run_guarded(
        OperatorWorkspaceService.get_summary(db, client_id=client_id),
        label="operator-workspace.summary",
    )


@router.get("/items", response_model=OperatorWorkspaceItemsResponse)
async def operator_workspace_items(
    client_id: UUID | None = None,
    category: AttentionCategory | None = None,
    priority: AttentionPriority | None = None,
    responsible_party: ResponsibleParty | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: CurrentTenantUser | None = Depends(require_operator_workspace_access),
):
    return await run_guarded(
        OperatorWorkspaceService.list_items(
            db,
            client_id=client_id,
            category=category,
            priority=priority,
            responsible_party=responsible_party,
            page=page,
            page_size=page_size,
        ),
        label="operator-workspace.items",
    )
