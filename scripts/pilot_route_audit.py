#!/usr/bin/env python3
"""Route stability audit for pilot demo — tenant and admin sessions."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
FRONTEND = "http://localhost:3000"

ROUTES = [
    "/dashboard",
    "/executive-copilot",
    "/deal-room",
    "/deal-risk",
    "/revenue-forecast",
    "/revenue-analytics",
    "/briefs",
    "/content",
    "/tasks",
    "/calendar",
    "/marketplace",
    "/buyer-search",
    "/buyer-network",
]

ROUTE_APIS = {
    "/dashboard": "/dashboard/overview",
    "/executive-copilot": "/executive-copilot/overview",
    "/deal-room": "/deal-room/v2/overview",
    "/deal-risk": "/deal-risk/overview",
    "/revenue-forecast": "/revenue-forecast/overview",
    "/revenue-analytics": "/analytics/overview",
    "/briefs": "/client-briefs",
    "/content": "/content",
    "/tasks": "/tasks",
    "/calendar": "/calendar",
    "/marketplace": "/marketplace/overview",
    "/buyer-search": "/buyer-discovery/overview",
    "/buyer-network": "/buyer-network/overview",
}

TENANT_DENIED = {"/revenue-forecast"}
ADMIN_ONLY_FRONTEND = {"/revenue-forecast", "/pilot-readiness"}


def post_json(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_json(path: str, token: str | None = None) -> tuple[int, dict | str]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw.decode()[:200]
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return e.code, body


def audit_session(label: str, token: str | None, denied_routes: set[str]) -> list[dict]:
    results = []
    for route in ROUTES:
        api = ROUTE_APIS[route]
        code, _ = get_json(api, token)
        if route in denied_routes:
            ok = code in (401, 403) or (label == "tenant" and route in TENANT_DENIED)
            status = "PASS (denied expected)" if ok else f"FAIL (got {code}, expected deny)"
        else:
            ok = 200 <= code < 400
            status = "PASS" if ok else f"FAIL ({code})"
        results.append({"route": route, "api": api, "http": code, "result": status})
    return results


def main() -> int:
    print("=== Pilot Route API Audit ===\n")

    tenant_token = None
    admin_token = None

    for email, password, kind in [
        ("demo@factory.local", "demo1234", "tenant"),
        ("admin@example.com", "ChangeMe_12345!", "admin"),
    ]:
        path = "/auth/login" if kind == "tenant" else "/admin-auth/login"
        try:
            r = post_json(path, {"email": email, "password": password})
            token = r.get("access_token")
            if kind == "tenant":
                tenant_token = token
            else:
                admin_token = token
            print(f"{kind.upper()} login OK: {email}")
        except Exception as exc:
            print(f"{kind.upper()} login FAIL ({email}): {exc}")

    if not tenant_token:
        print("Trying create-demo-user...")
        try:
            post_json("/auth/create-demo-user", {})
            r = post_json("/auth/login", {"email": "demo@factory.local", "password": "demo1234"})
            tenant_token = r.get("access_token")
            print("Demo user created and logged in")
        except Exception as exc:
            print(f"Demo bootstrap failed: {exc}")

    if not admin_token:
        print("Trying admin bootstrap...")
        try:
            post_json("/admin-auth/bootstrap", {})
            r = post_json("/admin-auth/login", {"email": "admin@example.com", "password": "ChangeMe_12345!"})
            admin_token = r.get("access_token")
            print("Admin bootstrap OK")
        except Exception as exc:
            print(f"Admin bootstrap failed: {exc}")

    print("\n--- demo@factory.local (tenant) ---")
    for row in audit_session("tenant", tenant_token, TENANT_DENIED):
        print(f"  {row['route']:22} {row['result']:28} HTTP {row['http']}")

    print("\n--- admin@example.com (admin) ---")
    for row in audit_session("admin", admin_token, set()):
        print(f"  {row['route']:22} {row['result']:28} HTTP {row['http']}")

    if admin_token:
        print("\n--- Pilot Readiness Dashboard ---")
        code, data = get_json("/pilot-readiness/overview", admin_token)
        if code == 200 and isinstance(data, dict):
            print(f"  Score: {data.get('readiness_score')}  Status: {data.get('status')}")
            print(f"  Routes pass: {data.get('routes_pass_count')}/{len(data.get('route_audits', []))}")
            print(f"  Open issues: {len(data.get('open_issues', []))}")
        else:
            print(f"  FAIL HTTP {code}: {str(data)[:200]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
