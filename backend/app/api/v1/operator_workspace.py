"""Operator Workspace — daily operational attention aggregation + Phase 1 actions."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.api_auth_context import get_auth_context
from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.operator_workspace import (
    AttentionCategory,
    AttentionPriority,
    OperatorWorkspaceActionRequest,
    OperatorWorkspaceActionResult,
    OperatorWorkspaceItemsResponse,
    OperatorWorkspaceSummaryResponse,
    ResponsibleParty,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.operator_workspace_actions import OperatorWorkspaceActionService
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


def _actor_id(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
) -> UUID | None:
    if user is not None:
        return getattr(user, "id", None) or getattr(user, "user_id", None)
    if admin is not None:
        return getattr(admin, "id", None) or getattr(admin, "user_id", None)
    return None


def _tenant_id_hint(
    user: CurrentTenantUser | None,
    tenant_id: UUID | None,
) -> UUID | None:
    if user is not None:
        return user.tenant_id
    return tenant_id


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


@router.post(
    "/items/{attention_id}/actions/{action_id}",
    response_model=OperatorWorkspaceActionResult,
)
async def execute_operator_workspace_action(
    attention_id: str,
    action_id: str,
    body: OperatorWorkspaceActionRequest | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(require_operator_workspace_access),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Route a Phase 1 safe action to the owning canonical domain service.

    Does not implement domain logic. Always revalidates eligibility server-side.
    """
    note = body.note if body else None

    return await run_guarded(
        OperatorWorkspaceActionService.execute(
            db,
            attention_id=attention_id,
            action_id=action_id,
            actor_id=_actor_id(user, admin),
            tenant_id=_tenant_id_hint(user, tenant_id),
            note=note,
        ),
        label="operator-workspace.action",
        timeout=SCAN_TIMEOUT_SEC,
    )
