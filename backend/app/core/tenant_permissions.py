"""Tenant Authentication & Access Control v1 — role permission definitions."""
from __future__ import annotations

TENANT_USER_ROLES = frozenset({"owner", "manager", "sales", "operator", "viewer"})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset({
        "tenant.full",
        "tenant.read",
        "executive.copilot.view",
        "users.manage",
        "billing.manage",
        "billing.view",
        "company.profile.manage",
        "leads.manage",
        "deals.manage",
        "products.manage",
        "buyers.view",
        "buyers.manage",
        "proposals.view",
        "proposals.manage",
        "tasks.manage",
        "inbox.manage",
        "leads.view",
    }),
    "manager": frozenset({
        "tenant.read",
        "leads.manage",
        "deals.manage",
        "products.manage",
        "billing.view",
        "buyers.view",
        "buyers.manage",
        "proposals.view",
        "proposals.manage",
        "leads.view",
    }),
    "sales": frozenset({
        "tenant.read",
        "leads.manage",
        "deals.manage",
        "buyers.view",
        "buyers.manage",
        "proposals.view",
        "proposals.manage",
    }),
    "operator": frozenset({
        "tenant.read",
        "tasks.manage",
        "inbox.manage",
        "leads.view",
    }),
    "viewer": frozenset({
        "tenant.read",
        "read_only",
    }),
}

_ROLE_RANK = {"viewer": 0, "operator": 1, "sales": 2, "manager": 3, "owner": 4}


def permissions_for_role(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


def role_has_permission(role: str, permission: str) -> bool:
    perms = ROLE_PERMISSIONS.get(role, frozenset())
    if "tenant.full" in perms:
        return True
    return permission in perms


def can_assign_role(current_role: str | None, new_role: str) -> bool:
    if new_role not in TENANT_USER_ROLES:
        return False
    if new_role == "owner":
        return current_role == "owner" or current_role is None
    new_rank = _ROLE_RANK.get(new_role, 0)
    cur_rank = _ROLE_RANK.get(current_role or "viewer", 0)
    return new_rank <= cur_rank + 1 or current_role == "owner"
