from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.publishing import (
    MetaConnectionHealthResponse,
    MetaConnectionSummaryResponse,
    MetaOAuthStartResponse,
    MetaRefreshResponse,
    MetaDisconnectResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.meta_connection_service import MetaConnectionService
from app.services.meta_oauth_service import MetaOAuthService
from app.services.publishing_tenant_scope import resolve_publishing_tenant_id
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/publishing/meta", tags=["meta-publishing"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
    tenant_id: UUID | None,
) -> UUID:
    return resolve_publishing_tenant_id(user, admin, tenant_id)


@router.get("/oauth/start", response_model=MetaOAuthStartResponse)
async def meta_oauth_start(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Return Meta OAuth authorize URL (Facebook Login for Pages + Instagram Business)."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return MetaOAuthService.start_oauth(scope_tenant_id)


@router.get("/oauth/callback")
async def meta_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """OAuth redirect handler — exchanges code, stores tokens, redirects to admin UI."""
    try:
        await MetaOAuthService.handle_callback(
            db,
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )
        return RedirectResponse(MetaOAuthService.frontend_redirect_url(success=True))
    except Exception as exc:
        message = getattr(exc, "detail", None) or str(exc)
        if isinstance(message, dict):
            message = message.get("message") or str(message)
        return RedirectResponse(MetaOAuthService.frontend_redirect_url(success=False, message=str(message)))


@router.post("/oauth/demo-connect", response_model=MetaConnectionSummaryResponse)
async def meta_oauth_demo_connect(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Demo-only Meta connect when OAuth credentials are not configured."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    await MetaOAuthService.demo_connect(db, scope_tenant_id)
    return await MetaConnectionService.get_connection_summary(db, scope_tenant_id)


@router.get("/connection", response_model=MetaConnectionSummaryResponse)
async def meta_connection_summary(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Connected Meta account summary — health, permissions, token expiry (no secrets)."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await MetaConnectionService.get_connection_summary(db, scope_tenant_id)


@router.get("/health", response_model=MetaConnectionHealthResponse)
async def meta_connection_health(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Live token + permission health for connected Meta accounts."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    summary = await MetaConnectionService.get_connection_summary(db, scope_tenant_id)
    return {
        "oauth_configured": summary["oauth_configured"],
        "connected": summary["connected"],
        "health": summary["health"],
        "token_expired": summary["token_expired"],
        "expires_at": summary["expires_at"],
        "permissions": summary["permissions"],
        "missing_permissions": summary["missing_permissions"],
        "facebook": summary["facebook"],
        "instagram": summary["instagram"],
        "blockers": summary["blockers"],
        "publish_implementation": summary["publish_implementation"],
    }


@router.post("/refresh", response_model=MetaRefreshResponse)
async def meta_refresh_tokens(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Refresh Meta long-lived user token and page access token."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await MetaConnectionService.refresh_tokens(db, scope_tenant_id)


@router.post("/disconnect", response_model=MetaDisconnectResponse)
async def meta_disconnect(
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    """Disconnect Meta — clears stored tokens and marks accounts disconnected."""
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    return await MetaConnectionService.disconnect(db, scope_tenant_id)
