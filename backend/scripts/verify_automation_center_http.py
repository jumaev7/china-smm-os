"""HTTP verification for Automation Center — tenant auth, flows, mutations, isolation."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000/api/v1")
FRONTEND_BASE = os.environ.get("VERIFY_FRONTEND_BASE", "http://127.0.0.1:3000")
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "ChangeMe_12345!"


def req(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    *,
    timeout: int = 30,
) -> tuple[int, Any, int]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode()
            duration_ms = int((time.perf_counter() - start) * 1000)
            if not raw:
                return resp.status, {}, duration_ms
            try:
                return resp.status, json.loads(raw), duration_ms
            except json.JSONDecodeError:
                return resp.status, raw, duration_ms
    except urllib.error.HTTPError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload, duration_ms
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return 0, {"detail": str(exc)}, duration_ms


def frontend_status(path: str) -> tuple[int, int]:
    request = urllib.request.Request(FRONTEND_BASE + path, method="GET")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return resp.status, duration_ms
    except urllib.error.HTTPError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return exc.code, duration_ms
    except Exception:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return 0, duration_ms


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    stamp = int(time.time())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "PASS" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" -> {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    code, admin_login, _ = req("POST", "/admin-auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if code != 200 or not isinstance(admin_login, dict) or not admin_login.get("access_token"):
        print(f"FAIL bootstrap_admin_login -> HTTP {code}: {admin_login}")
        return 1
    admin_token = admin_login["access_token"]

    email_a = f"auto-http-a-{stamp}@example.com"
    email_b = f"auto-http-b-{stamp}@example.com"
    code, created_a, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Automation HTTP A {stamp}", "owner_email": email_a, "plan": "trial"},
        token=admin_token,
    )
    code_b, created_b, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Automation HTTP B {stamp}", "owner_email": email_b, "plan": "trial"},
        token=admin_token,
    )
    if code != 201 or code_b != 201:
        record("bootstrap_tenants", False, f"A={code} B={code_b}")
        return 1

    code, login_a, _ = req(
        "POST",
        "/auth/login",
        {"email": email_a, "password": created_a["temporary_password"]},
    )
    code_b_login, login_b, _ = req(
        "POST",
        "/auth/login",
        {"email": email_b, "password": created_b["temporary_password"]},
    )
    token_a = login_a.get("access_token") if isinstance(login_a, dict) else None
    token_b = login_b.get("access_token") if isinstance(login_b, dict) else None
    record("tenant_login", code == 200 and bool(token_a), f"HTTP {code}")
    if not token_a or not token_b:
        return 1

    code, flows, _ = req("GET", "/automation", token=token_a)
    record(
        "list_flows",
        code == 200 and isinstance(flows, dict) and flows.get("total", 0) >= 3,
        f"HTTP {code} total={flows.get('total') if isinstance(flows, dict) else 'n/a'}",
    )

    code, kpis, _ = req("GET", "/automation/kpis", token=token_a)
    record(
        "kpis",
        code == 200 and isinstance(kpis, dict) and "health_score" in kpis,
        f"HTTP {code}",
    )

    flow_id = None
    if isinstance(flows, dict) and flows.get("items"):
        flow_id = flows["items"][0]["id"]

    if flow_id:
        code, detail, _ = req("GET", f"/automation/{flow_id}", token=token_a)
        record("get_detail", code == 200 and isinstance(detail, dict), f"HTTP {code}")

        code, paused, _ = req("POST", f"/automation/{flow_id}/pause", token=token_a)
        record("pause", code == 200 and paused.get("status") == "paused", f"HTTP {code}")

        code, listed_after_pause, _ = req("GET", "/automation", token=token_a)
        paused_item = next(
            (i for i in (listed_after_pause.get("items") or []) if i.get("id") == flow_id),
            None,
        ) if isinstance(listed_after_pause, dict) else None
        record(
            "pause_persists",
            paused_item is not None and paused_item.get("status") == "paused",
            str(paused_item.get("status") if paused_item else None),
        )

        code, enabled, _ = req("POST", f"/automation/{flow_id}/enable", token=token_a)
        record("enable", code == 200 and enabled.get("status") == "enabled", f"HTTP {code}")

        code, run_result, _ = req("POST", f"/automation/{flow_id}/run", token=token_a)
        record(
            "manual_run",
            code == 200 and run_result.get("is_manual_test") is True,
            f"HTTP {code} status={run_result.get('status') if isinstance(run_result, dict) else 'n/a'}",
        )

        code, wrong, _ = req("GET", f"/automation/{flow_id}", token=token_b)
        record("tenant_isolation", code == 404, f"HTTP {code}")

    code, execs, _ = req("GET", "/automation/executions?page=1&page_size=10", token=token_a)
    record(
        "executions",
        code == 200 and isinstance(execs, dict) and "items" in execs,
        f"HTTP {code} total={execs.get('total') if isinstance(execs, dict) else 'n/a'}",
    )

    code, fe_status, fe_ms = frontend_status("/automation")
    record("frontend_automation_page", fe_status in (200, 307, 308), f"HTTP {fe_status} ({fe_ms}ms)")

    print(f"\n{len(failures)} failures" if failures else "\nAll HTTP checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
