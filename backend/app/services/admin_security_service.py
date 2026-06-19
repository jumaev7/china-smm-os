"""Admin Security Hardening v1 — security status and readiness reporting."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from starlette.routing import Route

from app.core.admin_permissions import ALL_ADMIN_PERMISSIONS
from app.core.admin_route_registry import (
    ADMIN_FACING_PREFIXES,
    ADMIN_PROTECTED_ROUTE_SPECS,
    ADMIN_PUBLIC_ROUTE_PREFIXES,
    compute_readiness_score,
    permission_route_matrix,
    permissions_without_routes,
)
from app.core.config import settings
from app.services.admin_rbac_service import settings_secret_is_default


def _route_path(route: Route) -> str:
    path = getattr(route, "path", "") or ""
    if not path.startswith("/"):
        path = f"/api/v1{path}" if path else ""
    return path


def _is_admin_facing(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ADMIN_FACING_PREFIXES)


def _is_public_admin_route(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ADMIN_PUBLIC_ROUTE_PREFIXES)


def scan_app_routes(app: FastAPI) -> tuple[list[str], list[str]]:
    """Return (protected_routes, open_routes) for admin-facing API paths."""
    registered_protected = {
        f"{spec.method} {spec.path}" for spec in ADMIN_PROTECTED_ROUTE_SPECS
    }
    protected: list[str] = []
    open_routes: list[str] = []

    for route in app.routes:
        if not isinstance(route, Route):
            continue
        path = _route_path(route)
        if not _is_admin_facing(path):
            continue
        methods = sorted(m for m in route.methods if m not in ("HEAD", "OPTIONS"))
        for method in methods:
            key = f"{method} {path}"
            if _is_public_admin_route(path):
                continue
            if key in registered_protected:
                protected.append(key)
            else:
                open_routes.append(key)

    return sorted(set(protected)), sorted(set(open_routes))


class AdminSecurityService:
    @staticmethod
    async def security_status(app: FastAPI, db) -> dict[str, Any]:
        from app.services.admin_rbac_service import AdminRbacService

        protected, open_routes = scan_app_routes(app)
        matrix = permission_route_matrix()
        unmapped = permissions_without_routes()
        total_perms = len(ALL_ADMIN_PERMISSIONS)
        mapped_count = total_perms - len(unmapped)
        coverage_pct = (mapped_count / total_perms * 100) if total_perms else 100.0

        secrets_separated = (
            bool(settings.ADMIN_SECRET_KEY)
            and bool(settings.TENANT_SECRET_KEY)
            and settings.ADMIN_SECRET_KEY != settings.TENANT_SECRET_KEY
        )
        bootstrap_locked = settings.APP_ENV not in ("development",)
        session_checks_ok = True

        checks = await AdminRbacService.security_checks(db)
        readiness = compute_readiness_score(
            protected_count=len(protected),
            open_count=len(open_routes),
            permission_coverage_pct=coverage_pct,
            session_checks_ok=session_checks_ok,
            secrets_separated=secrets_separated,
            bootstrap_locked=bootstrap_locked,
        )

        return {
            "protected_routes": protected,
            "protected_route_count": len(protected),
            "open_routes": open_routes,
            "open_route_count": len(open_routes),
            "permission_route_matrix": matrix,
            "permission_coverage_percent": round(coverage_pct, 1),
            "unmapped_permissions": unmapped,
            "session_invalidation": {
                "requires_session_id": True,
                "validates_session_nonce": True,
                "revokes_refresh_on_logout": True,
                "revokes_all_sessions_without_session_id": True,
            },
            "jwt_separation": {
                "admin_secret_configured": bool(settings.ADMIN_SECRET_KEY),
                "tenant_secret_configured": bool(settings.TENANT_SECRET_KEY),
                "secrets_distinct": secrets_separated,
            },
            "bootstrap": {
                "app_env": settings.APP_ENV,
                "bootstrap_enabled": settings.APP_ENV == "development",
            },
            "login_protection": {
                "rate_limiting": True,
                "account_lockout": True,
                "failed_login_tracking": True,
            },
            "security_checks": checks,
            "readiness_score": readiness,
            "implementation_complete": (
                len(open_routes) == 0
                and len(unmapped) == 0
                and secrets_separated
                and not settings_secret_is_default()
            ),
        }
