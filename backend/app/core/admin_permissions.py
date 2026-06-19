"""Admin Authentication & RBAC v1 — platform role permission definitions."""
from __future__ import annotations

ADMIN_ROLES = frozenset({"super_admin", "platform_admin", "support_admin", "auditor"})

ADMIN_USER_STATUSES = frozenset({"invited", "active", "suspended", "removed"})

ADMIN_SESSION_STATUSES = frozenset({"active", "revoked", "expired"})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "super_admin": frozenset({"platform.full"}),
    "platform_admin": frozenset({
        "tenants.manage",
        "tenants.read",
        "billing.manage",
        "billing.read",
        "subscriptions.manage",
        "subscriptions.read",
        "platform.settings",
        "business.read",
    }),
    "support_admin": frozenset({
        "support.tools",
        "diagnostics.read",
        "business.read",
        "tenants.read",
    }),
    "auditor": frozenset({
        "reports.read",
        "logs.read",
        "analytics.read",
    }),
}

_ROLE_RANK = {
    "auditor": 0,
    "support_admin": 1,
    "platform_admin": 2,
    "super_admin": 3,
}


def permissions_for_role(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


def role_has_permission(role: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, frozenset())
    if "platform.full" in perms:
        return True
    return permission in perms


ALL_ADMIN_PERMISSIONS: frozenset[str] = frozenset(
    perm for perms in ROLE_PERMISSIONS.values() for perm in perms
) | frozenset({"platform.full"})


def can_assign_admin_role(current_role: str | None, new_role: str) -> bool:
    if new_role not in ADMIN_ROLES:
        return False
    if current_role == "super_admin":
        return True
    if new_role == "super_admin":
        return False
    new_rank = _ROLE_RANK.get(new_role, 0)
    cur_rank = _ROLE_RANK.get(current_role or "auditor", 0)
    return new_rank <= cur_rank
