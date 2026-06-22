"""Admin Security Hardening v1 — permission-to-route matrix and route classification."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.admin_permissions import ALL_ADMIN_PERMISSIONS


@dataclass(frozen=True)
class AdminRouteSpec:
    method: str
    path: str
    permission: str
    category: str


# Every protected admin-facing route must appear here with its required permission.
ADMIN_PROTECTED_ROUTE_SPECS: tuple[AdminRouteSpec, ...] = (
    # Admin auth & RBAC
    AdminRouteSpec("POST", "/api/v1/admin-auth/logout", "platform.full", "admin_auth"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/me", "platform.full", "admin_auth"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/users", "platform.full", "admin_auth"),
    AdminRouteSpec("POST", "/api/v1/admin-auth/users", "platform.full", "admin_auth"),
    AdminRouteSpec("PATCH", "/api/v1/admin-auth/users/{user_id}", "platform.full", "admin_auth"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/roles", "logs.read", "admin_auth"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/permissions", "logs.read", "admin_auth"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/audit-logs", "logs.read", "admin_auth"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/sessions", "logs.read", "admin_auth"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/platform/tenants", "tenants.read", "platform"),
    AdminRouteSpec("POST", "/api/v1/admin-auth/platform/tenants/create-client", "tenants.manage", "platform"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/platform/billing", "billing.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/platform/analytics", "analytics.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/platform/subscriptions", "subscriptions.read", "platform"),
    AdminRouteSpec("POST", "/api/v1/admin-auth/platform/subscriptions/{subscription_id}/suspend", "subscriptions.manage", "platform"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/platform/settings", "platform.settings", "platform"),
    AdminRouteSpec("POST", "/api/v1/admin-auth/platform/billing/suspend-subscription", "billing.manage", "platform"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/support/tools", "support.tools", "support"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/security-checks", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/admin-auth/security-status", "diagnostics.read", "diagnostics"),
    # Billing administration
    AdminRouteSpec("GET", "/api/v1/billing/overview", "billing.read", "billing"),
    # Platform / tenant management
    AdminRouteSpec("GET", "/api/v1/factory-partner/applications", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/factory-partner/summary-widget", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/factory-partner/applications/{application_id}", "tenants.read", "platform"),
    AdminRouteSpec("PATCH", "/api/v1/factory-partner/applications/{application_id}", "tenants.manage", "platform"),
    AdminRouteSpec("POST", "/api/v1/factory-partner/applications/{application_id}/submit", "tenants.manage", "platform"),
    AdminRouteSpec("POST", "/api/v1/factory-partner/applications/{application_id}/approve", "tenants.manage", "platform"),
    AdminRouteSpec("POST", "/api/v1/factory-partner/applications/{application_id}/reject", "tenants.manage", "platform"),
    AdminRouteSpec("POST", "/api/v1/factory-partner/applications/{application_id}/create-client", "tenants.manage", "platform"),
    AdminRouteSpec("POST", "/api/v1/factory-partner/applications/{application_id}/create-portal-account", "tenants.manage", "platform"),
    AdminRouteSpec("POST", "/api/v1/factory-partner/applications/{application_id}/create-tenant", "tenants.manage", "platform"),
    # Diagnostics
    AdminRouteSpec("GET", "/api/v1/system/schema-health", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/system/api-health", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/system/recent-errors", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/system/query-health", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/system/dependencies", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/system/health-snapshots", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/system/i18n-health", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("POST", "/api/v1/system/demo-seed", "platform.full", "diagnostics"),
    AdminRouteSpec("POST", "/api/v1/system/demo-reset", "platform.full", "diagnostics"),
    # Pilot launch QA
    AdminRouteSpec("GET", "/api/v1/pilot-launch/overview", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/pilot-launch/readiness", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/pilot-launch/checklist", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/pilot-launch/smoke-tests", "tenants.read", "platform"),
    AdminRouteSpec("POST", "/api/v1/pilot-launch/seed-demo-data", "platform.full", "platform"),
    AdminRouteSpec("POST", "/api/v1/pilot-launch/run-qa", "tenants.read", "platform"),
    # Production deployment preparation
    AdminRouteSpec("GET", "/api/v1/production-deployment/overview", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/readiness", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/environment", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/checklist", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/backups", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/monitoring", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/security", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/summary", "platform.settings", "platform"),
    AdminRouteSpec("GET", "/api/v1/production-deployment/summary-widget", "platform.settings", "platform"),
    AdminRouteSpec("POST", "/api/v1/production-deployment/refresh", "platform.settings", "platform"),
    # Real factory pilot
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/overview", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/checklist", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/blockers", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/actions", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/readiness", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/summary", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/summary-widget", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/real-factory-pilot/candidate-indicator", "tenants.read", "platform"),
    AdminRouteSpec("POST", "/api/v1/real-factory-pilot/refresh", "tenants.read", "platform"),
    # Audit
    AdminRouteSpec("GET", "/api/v1/audit/overview", "reports.read", "audit"),
    AdminRouteSpec("POST", "/api/v1/audit/run", "reports.read", "audit"),
    AdminRouteSpec("POST", "/api/v1/audit/fixes/{issue_id}/apply", "reports.read", "audit"),
    # Executive / business intelligence
    AdminRouteSpec("GET", "/api/v1/executive-copilot/overview", "business.read", "executive"),
    AdminRouteSpec("GET", "/api/v1/executive-copilot/alerts", "business.read", "executive"),
    AdminRouteSpec("GET", "/api/v1/executive-copilot/recommendations", "business.read", "executive"),
    AdminRouteSpec("GET", "/api/v1/executive-copilot/summary-widget", "business.read", "executive"),
    AdminRouteSpec("POST", "/api/v1/executive-copilot/generate-briefing", "business.read", "executive"),
    # Revenue
    AdminRouteSpec("GET", "/api/v1/revenue/overview", "business.read", "revenue"),
    AdminRouteSpec("POST", "/api/v1/revenue/deals/{deal_id}/approve-commission", "billing.manage", "revenue"),
    AdminRouteSpec("POST", "/api/v1/revenue/deals/{deal_id}/mark-paid", "billing.manage", "revenue"),
    AdminRouteSpec("POST", "/api/v1/revenue/ai-insights", "business.read", "revenue"),
    # Platform ops (pre-launch)
    AdminRouteSpec("GET", "/api/v1/platform-ops/pilot-program", "tenants.read", "platform"),
    AdminRouteSpec("POST", "/api/v1/platform-ops/pilot-program", "tenants.manage", "platform"),
    AdminRouteSpec("PATCH", "/api/v1/platform-ops/pilot-program/{factory_id}", "tenants.manage", "platform"),
    AdminRouteSpec("DELETE", "/api/v1/platform-ops/pilot-program/{factory_id}", "tenants.manage", "platform"),
    AdminRouteSpec("GET", "/api/v1/platform-ops/feedback", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/platform-ops/system-health", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/platform-ops/audit-logs", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/platform-ops/errors", "diagnostics.read", "diagnostics"),
    AdminRouteSpec("GET", "/api/v1/platform-ops/pilot-success", "tenants.read", "platform"),
    AdminRouteSpec("GET", "/api/v1/platform-ops/launch-readiness", "tenants.read", "platform"),
)

# Routes that must stay public (auth flows, public onboarding, webhooks).
ADMIN_PUBLIC_ROUTE_PREFIXES: tuple[str, ...] = (
    "/api/v1/admin-auth/login",
    "/api/v1/admin-auth/refresh",
    "/api/v1/admin-auth/bootstrap",
    "/api/v1/auth/",
    "/api/v1/factory-partner/apply",
    "/api/v1/system/health",
    "/public/",
)

# Admin-facing categories scanned for open-route detection.
ADMIN_FACING_PREFIXES: tuple[str, ...] = (
    "/api/v1/admin-auth/",
    "/api/v1/billing/overview",
    "/api/v1/factory-partner/",
    "/api/v1/system/",
    "/api/v1/audit/",
    "/api/v1/executive-copilot/",
    "/api/v1/revenue/",
    "/api/v1/platform-ops/",
)


def permission_route_matrix() -> dict[str, list[str]]:
    """Map each permission to the routes that require it."""
    matrix: dict[str, list[str]] = {p: [] for p in sorted(ALL_ADMIN_PERMISSIONS)}
    for spec in ADMIN_PROTECTED_ROUTE_SPECS:
        route_key = f"{spec.method} {spec.path}"
        matrix.setdefault(spec.permission, []).append(route_key)
    return {k: sorted(v) for k, v in matrix.items() if v}


def permissions_without_routes() -> list[str]:
    matrix = permission_route_matrix()
    return sorted(p for p in ALL_ADMIN_PERMISSIONS if not matrix.get(p))


def compute_readiness_score(
    *,
    protected_count: int,
    open_count: int,
    permission_coverage_pct: float,
    session_checks_ok: bool,
    secrets_separated: bool,
    bootstrap_locked: bool,
) -> int:
    score = 0
    if protected_count > 0:
        score += 25
    if open_count == 0:
        score += 25
    score += int(permission_coverage_pct * 0.25)
    if session_checks_ok:
        score += 10
    if secrets_separated:
        score += 10
    if bootstrap_locked:
        score += 5
    return min(100, score)
