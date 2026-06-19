#!/usr/bin/env python3
"""Verify Pilot Demo Mode — admin access, tenant denial, workflow actions."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "ChangeMe_12345!"
TENANT_EMAIL = "demo@factory.local"
TENANT_PASSWORD = "demo1234"


def post(path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body or {}).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def get(path: str, token: str | None = None) -> tuple[int, dict]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def login_admin() -> str:
    code, data = post("/admin-auth/login", body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert code == 200, f"Admin login failed: {code} {data}"
    return data["access_token"]


def login_tenant() -> str:
    code, data = post("/auth/login", body={"email": TENANT_EMAIL, "password": TENANT_PASSWORD})
    assert code == 200, f"Tenant login failed: {code} {data}"
    return data["access_token"]


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    # Admin login
    try:
        admin_token = login_admin()
        results.append(("admin_login", True, "OK"))
    except Exception as e:
        results.append(("admin_login", False, str(e)))
        print_results(results)
        return 1

    # Tenant denied on overview
    try:
        tenant_token = login_tenant()
        code, _ = get("/pilot-demo-mode/overview", tenant_token)
        results.append(("tenant_access_denied", code in (401, 403), f"HTTP {code}"))
    except Exception as e:
        results.append(("tenant_access_denied", False, str(e)))

    # Admin overview
    try:
        code, data = get("/pilot-demo-mode/overview", admin_token)
        ok = code == 200 and "workflow_steps" in data and len(data["workflow_steps"]) == 7
        results.append(("admin_overview", ok, f"HTTP {code}, steps={len(data.get('workflow_steps', []))}"))
    except Exception as e:
        results.append(("admin_overview", False, str(e)))
        print_results(results)
        return 1

    # Reset first (clean slate)
    try:
        code, data = post("/pilot-demo-mode/reset", admin_token)
        results.append(("reset", code == 200, data.get("message", f"HTTP {code}")))
    except Exception as e:
        results.append(("reset", False, str(e)))

    # Full workflow
    actions = [
        "create_sample_brief",
        "generate_sample_plan",
        "approve_sample_plan",
        "create_sample_tasks",
        "simulate_publishing_pipeline",
        "generate_sample_revenue_metrics",
    ]
    for action in actions:
        try:
            code, data = post(f"/pilot-demo-mode/actions/{action}", admin_token)
            ok = code == 200 and data.get("success")
            progress = data.get("overview", {}).get("progress_percent", "?")
            results.append((action, ok, f"{data.get('message', '')} progress={progress}%"))
        except Exception as e:
            results.append((action, False, str(e)))

    # Final overview check
    try:
        code, data = get("/pilot-demo-mode/overview", admin_token)
        ok = code == 200 and data.get("progress_percent", 0) == 100
        results.append(("workflow_complete", ok, f"progress={data.get('progress_percent')}%"))
    except Exception as e:
        results.append(("workflow_complete", False, str(e)))

    # Final reset
    try:
        code, data = post("/pilot-demo-mode/reset", admin_token)
        ok = code == 200 and data.get("overview", {}).get("demo_data_present") is False
        results.append(("final_reset", ok, data.get("message", "")))
    except Exception as e:
        results.append(("final_reset", False, str(e)))

    print_results(results)
    failed = [r for r in results if not r[1]]
    return 1 if failed else 0


def print_results(results: list[tuple[str, bool, str]]) -> None:
    print("\n=== Pilot Demo Mode Verification ===")
    for name, ok, msg in results:
        status = "PASS" if ok else "FAIL"
        safe_msg = msg.encode("ascii", errors="replace").decode("ascii")
        print(f"  [{status}] {name}: {safe_msg}")
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nTotal: {passed}/{len(results)} passed")


if __name__ == "__main__":
    sys.exit(main())
