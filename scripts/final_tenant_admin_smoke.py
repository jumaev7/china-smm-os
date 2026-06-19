#!/usr/bin/env python3
"""Final tenant/admin smoke test — API probes for routes in the smoke checklist."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
FRONTEND = "http://localhost:3000"

TENANT_ROUTES = {
    "/dashboard": "/dashboard/overview",
    "/content": "/content?limit=5",
    "/content-factory": "/content-factory/dashboard",
    "/media-library": "/media-library?limit=5",
    "/publishing": "/publishing/accounts",
    "/calendar": "/calendar/month/2026/6",
    "/crm": "/crm/pipeline",
    "/leads": "/sales-crm/leads?limit=20",
    "/customers": "/sales-crm/customers?limit=20",
    "/deals": "/sales-crm/deals?limit=20",
    "/proposals": "/sales-crm/proposals?limit=20",
    "/buyers": "/buyers?limit=20",
    "/communications": "/communications/dashboard",
    "/inbox": "/communications/inbox?limit=20",
    "/followups": "/communications/followups?limit=20",
    "/templates": "/communications/templates?limit=20",
    "/wechat": "/wechat/dashboard",
    "/whatsapp": "/whatsapp/dashboard",
    "/growth-center": "/growth-center/summary",
    "/export-growth": "/export-growth/summary",
    "/customer-success": "/customer-success/summary",
    "/ai-assistant": "/executive-copilot/summary-widget",
    "/tenant-users": "/tenant-auth/users",
    "/billing": "/billing/plans",
}

ADMIN_ROUTES = {
    "/tenants": "/admin-auth/platform/tenants?limit=50",
    "/billing": "/admin-auth/platform/billing",
    "/plans": "/admin-auth/platform/billing",
    "/licenses": "/admin-auth/platform/subscriptions?limit=50",
    "/pilot-program": "/platform-ops/pilot-program?limit=50",
    "/system-health": "/platform-ops/system-health",
    "/audit-logs": "/platform-ops/audit-logs?limit=50",
    "/error-tracking": "/platform-ops/errors?limit=50",
    "/demo-management": "/pilot-demo-mode/overview",
    "/platform-settings": "/admin-auth/security-checks",
}

TENANT_DENIED_ON_ADMIN = set(ADMIN_ROUTES)
ADMIN_DENIED_ON_TENANT = {
    "/tenants",
    "/pilot-program",
    "/system-health",
    "/audit-logs",
    "/error-tracking",
    "/demo-management",
    "/platform-settings",
}


def post_json(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def get_status(path: str, token: str | None, timeout: float = 20) -> tuple[int, str]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", headers=headers, method="GET")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, f"ok ({int((time.time() - t0) * 1000)}ms)"
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:120]
        return e.code, body
    except Exception as e:
        return 0, str(e)[:120]


def get_frontend(path: str) -> tuple[int, str]:
    req = urllib.request.Request(f"{FRONTEND}{path}", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read(8000).decode(errors="replace")
            issues = []
            if "Hydration failed" in html or "hydration error" in html.lower():
                issues.append("hydration")
            if "Unable to connect right now" in html:
                issues.append("fake-connection-error")
            return resp.status, "ok" if not issues else ",".join(issues)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:80]
    except Exception as e:
        return 0, str(e)[:80]


def login(email: str, password: str, admin: bool) -> str | None:
    path = "/admin-auth/login" if admin else "/auth/login"
    try:
        data = post_json(path, {"email": email, "password": password})
        return data.get("access_token")
    except Exception:
        return None


def bootstrap() -> None:
    try:
        post_json("/auth/create-demo-user", {})
    except Exception:
        pass
    try:
        post_json("/admin-auth/bootstrap", {})
    except Exception:
        pass


def audit(label: str, routes: dict[str, str], token: str | None, denied: set[str]) -> list[dict]:
    rows = []
    for route, api in routes.items():
        code, msg = get_status(api, token)
        if route in denied:
            ok = code in (401, 403)
            result = "PASS (deny)" if ok else f"FAIL (expected 401/403, got {code})"
        elif code == 0:
            result = f"FAIL (network: {msg})"
        elif 200 <= code < 400:
            result = "PASS"
        else:
            result = f"FAIL ({code}: {msg})"
        rows.append({"route": route, "api": api, "http": code, "result": result, "detail": msg})
    return rows


def main() -> int:
    print("=== Final Tenant/Admin Smoke Test ===\n")
    bootstrap()

    tenant_token = login("demo@factory.local", "demo1234", admin=False)
    admin_token = login("admin@example.com", "ChangeMe_12345!", admin=True)
    if not tenant_token:
        print("FATAL: tenant login failed")
        return 1
    if not admin_token:
        print("FATAL: admin login failed")
        return 1

    tenant_id = None
    try:
        req = urllib.request.Request(
            f"{BASE}/auth/me",
            headers={"Authorization": f"Bearer {tenant_token}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            me = json.loads(resp.read())
            tenant_id = me.get("user", {}).get("tenant_id") or me.get("tenant", {}).get("id")
    except Exception:
        pass

    tenant_routes = dict(TENANT_ROUTES)
    if tenant_id:
        tenant_routes["/billing"] = f"/billing/summary?tenant_id={tenant_id}"

    print("Logins OK\n")

    tenant_rows = audit("tenant", tenant_routes, tenant_token, ADMIN_DENIED_ON_TENANT)
    admin_rows = audit("admin", ADMIN_ROUTES, admin_token, set())

    print("--- TENANT API (demo@factory.local) ---")
    tenant_fail = 0
    for row in tenant_rows:
        print(f"  {row['route']:22} {row['result']}")
        if not row["result"].startswith("PASS"):
            tenant_fail += 1

    print("\n--- ADMIN API (admin@example.com) ---")
    admin_fail = 0
    for row in admin_rows:
        print(f"  {row['route']:22} {row['result']}")
        if not row["result"].startswith("PASS"):
            admin_fail += 1

    print("\n--- Cross-session isolation ---")
    for route, api in list(ADMIN_ROUTES.items())[:3]:
        code, _ = get_status(api, tenant_token)
        ok = code in (401, 403)
        print(f"  tenant on {route}: {'PASS (deny)' if ok else f'FAIL ({code})'}")
        if not ok:
            tenant_fail += 1
    for route, api in [("/dashboard", "/dashboard/overview"), ("/tenant-users", "/tenant-auth/users")]:
        code, _ = get_status(api, admin_token)
        ok = 200 <= code < 400
        print(f"  admin on {route}: {'PASS' if ok else f'FAIL ({code})'}")
        if not ok:
            admin_fail += 1

    print("\n--- Frontend page load (unauthenticated shell) ---")
    fe_fail = 0
    sample = ["/login", "/admin-login", "/dashboard", "/tenants"]
    for path in sample:
        code, msg = get_frontend(path)
        ok = code == 200 and "hydration" not in msg
        print(f"  {path:22} HTTP {code} {msg}")
        if not ok:
            fe_fail += 1

    print(f"\nSummary: tenant_api_fail={tenant_fail} admin_api_fail={admin_fail} frontend_fail={fe_fail}")
    return 1 if (tenant_fail or admin_fail) else 0


if __name__ == "__main__":
    sys.exit(main())
