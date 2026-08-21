"""Read-only integration health API."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import get_auth_context
from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.integration_health import (
    IntegrationHealthDetailResponse,
    IntegrationHealthListResponse,
    IntegrationHealthOut,
)
from app.services.integration_health.service import IntegrationHealthService
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService

router = APIRouter(prefix="/integrations", tags=["integration-health"])

_bearer = HTTPBearer(auto_error=False)

# Align with Operator Workspace — operational surface, not sales/viewer.
_HEALTH_ROLES = ("owner", "manager", "operator")


async def require_integration_health_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> CurrentTenantUser | None:
    ctx = get_auth_context()
    if ctx and ctx.is_admin:
        return None
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = await get_current_tenant_user(credentials, db)
    TenantAuthService.assert_role(user, *_HEALTH_ROLES)
    return user


@router.get("/health", response_model=IntegrationHealthListResponse)
async def list_integration_health(
    client_id: UUID | None = None,
    platform: str | None = None,
    status: str | None = None,
    requires_action: bool | None = None,
    live_check: bool = Query(
        False,
        description=(
            "When true, may call provider READ APIs (Meta debug_token, Telegram "
            "getWebhookInfo). Default false returns local/persisted evaluation."
        ),
    ),
    tenant_id: UUID | None = Query(None, description="Required for platform admin"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(require_integration_health_access),
):
    """List integration health. Read-only. No provider mutations."""
    scoped = user.tenant_id if user is not None else tenant_id

    async def _run():
        raw = await IntegrationHealthService.list_health(
            db,
            tenant_id=scoped,
            client_id=client_id,
            platform=platform,
            status=status,
            requires_action=requires_action,
            live_check=live_check,
        )
        return IntegrationHealthListResponse(**raw)

    return await run_guarded(_run(), label="integrations.health.list")


@router.get("/{integration_id}/health", response_model=IntegrationHealthDetailResponse)
async def get_integration_health(
    integration_id: str,
    live_check: bool = Query(False),
    tenant_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(require_integration_health_access),
):
    """Single integration health. Read-only. No provider mutations."""
    scoped = user.tenant_id if user is not None else tenant_id

    async def _run():
        result = await IntegrationHealthService.get_one(
            db,
            integration_id,
            tenant_id=scoped,
            live_check=live_check,
        )
        return IntegrationHealthDetailResponse(
            item=IntegrationHealthOut(**result.to_public_dict()),
            cache_semantics=(
                "live_provider_probe"
                if live_check
                else "local_evaluation_with_persisted_diagnostics"
            ),
            live_check=live_check,
        )

    return await run_guarded(_run(), label="integrations.health.detail")
