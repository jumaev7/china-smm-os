"""API authentication middleware — require tenant or admin JWT on protected routes."""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import ColumnElement
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.admin_auth_service import TOKEN_TYPE_ADMIN_ACCESS, decode_admin_token
from app.services.auth_service import TOKEN_TYPE_ACCESS, decode_token
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

# Routes that must remain reachable without tenant/admin JWT.
PUBLIC_API_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/create-demo-user",
    "/api/v1/admin-auth/login",
    "/api/v1/admin-auth/refresh",
    "/api/v1/admin-auth/bootstrap",
    "/api/v1/factory-partner/apply",
    "/api/v1/telegram/webhook",
    "/api/v1/publishing/meta/oauth/callback",
    "/api/webhooks/whatsapp",
    "/api/v1/system/health",
    "/public/",
)

PUBLIC_EXACT_PATHS: frozenset[str] = frozenset({"/health"})


@dataclass(frozen=True)
class ApiAuthContext:
    kind: Literal["tenant", "admin"]
    tenant_id: UUID | None = None
    client_ids: tuple[UUID, ...] = ()

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"

    @property
    def is_tenant(self) -> bool:
        return self.kind == "tenant"


_auth_ctx: ContextVar[ApiAuthContext | None] = ContextVar("api_auth_ctx", default=None)


def get_auth_context() -> ApiAuthContext | None:
    return _auth_ctx.get()


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_API_PREFIXES)


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    return token or None


async def _resolve_auth_context(token: str) -> ApiAuthContext | None:
    from app.services.admin_rbac_service import AdminRbacService
    from app.services.tenant_auth_service import TenantAuthService

    try:
        admin_payload = decode_admin_token(token, expected_type=TOKEN_TYPE_ADMIN_ACCESS)
        async with AsyncSessionLocal() as db:
            admin = await AdminRbacService.resolve_current_admin(
                db,
                UUID(admin_payload["sub"]),
                UUID(admin_payload["session_id"]),
                access_nonce=admin_payload.get("access_nonce"),
            )
        return ApiAuthContext(kind="admin", tenant_id=None, client_ids=())
    except HTTPException:
        pass

    try:
        tenant_payload = decode_token(token, expected_type=TOKEN_TYPE_ACCESS)
        user_id = UUID(tenant_payload["sub"])
        async with AsyncSessionLocal() as db:
            user = await TenantAuthService.resolve_current_user(db, user_id)
            client_ids = await TenantService.get_client_ids_for_tenant(db, user.tenant_id)
        return ApiAuthContext(
            kind="tenant",
            tenant_id=user.tenant_id,
            client_ids=tuple(client_ids),
        )
    except HTTPException:
        return None


class ApiAuthMiddleware(BaseHTTPMiddleware):
    """Require valid tenant or admin JWT for all /api routes except public whitelist."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method

        if method == "OPTIONS":
            return await call_next(request)

        if not path.startswith("/api/"):
            return await call_next(request)

        if _is_public_path(path):
            return await call_next(request)

        token = _extract_bearer(request)
        if not token:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})

        ctx = await _resolve_auth_context(token)
        if ctx is None:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

        reset = _auth_ctx.set(ctx)
        request.state.api_auth = ctx
        try:
            return await call_next(request)
        finally:
            _auth_ctx.reset(reset)


def assert_client_in_scope(client_id: UUID) -> None:
    """Reject cross-tenant client access for tenant-authenticated requests."""
    ctx = get_auth_context()
    if ctx is None or ctx.is_admin:
        return
    if client_id not in ctx.client_ids:
        raise HTTPException(
            status_code=403,
            detail="Client does not belong to this tenant — isolation enforced",
        )


def assert_tenant_resource(client_id: UUID | None) -> None:
    """Validate a loaded resource's client_id belongs to the authenticated tenant."""
    if client_id is None:
        return
    assert_client_in_scope(client_id)


def apply_client_scope(
    *,
    client_id: UUID | None,
    column: ColumnElement,
) -> ColumnElement | None:
    """
    Build a SQLAlchemy filter for client-scoped legacy tables.
    Returns None when no filter should be applied (admin, unscoped).
    """
    ctx = get_auth_context()
    if ctx is None or ctx.is_admin:
        if client_id is not None:
            return column == client_id
        return None

    if client_id is not None:
        assert_client_in_scope(client_id)
        return column == client_id

    if not ctx.client_ids:
        return column.is_(None) & column.isnot(None)  # empty tenant — no accessible clients

    return column.in_(ctx.client_ids)


def resolve_tenant_id_param(tenant_id: UUID | None) -> UUID | None:
    """Resolve tenant_id query param — tenant users cannot scope to other tenants."""
    ctx = get_auth_context()
    if ctx is None or ctx.is_admin:
        return tenant_id
    if tenant_id is not None and tenant_id != ctx.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot access another tenant's data",
        )
    return ctx.tenant_id


def scoped_tenant_id_dependency():
    """FastAPI dependency factory — tenant_id query param with isolation enforcement."""
    from fastapi import Query

    async def _dep(
        tenant_id: UUID | None = Query(None, description="Tenant scope — enforced for tenant users"),
    ) -> UUID | None:
        return resolve_tenant_id_param(tenant_id)

    return _dep


def apply_tenant_direct_scope(
    *,
    tenant_id_column: ColumnElement,
) -> ColumnElement | None:
    """Filter rows that carry tenant_id directly (e.g. Client.tenant_id)."""
    ctx = get_auth_context()
    if ctx is None or ctx.is_admin:
        return None
    return tenant_id_column == ctx.tenant_id
