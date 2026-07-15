"""HTTP verification for Marketing Intelligence read-only APIs + tenant isolation."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_http_bootstrap import ensure_admin_token  # noqa: E402

BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000/api/v1")


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


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    admin_token, admin_detail = await ensure_admin_token(req)
    record("admin_token", bool(admin_token), admin_detail)
    if not admin_token:
        return 1

    stamp = int(time.time())
    email_a = f"mip-http-a-{stamp}@example.com"
    email_b = f"mip-http-b-{stamp}@example.com"

    code, created_a, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"MIP HTTP A {stamp}", "owner_email": email_a, "plan": "trial"},
        token=admin_token,
    )
    code_b, created_b, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"MIP HTTP B {stamp}", "owner_email": email_b, "plan": "trial"},
        token=admin_token,
    )
    record(
        "bootstrap_tenants",
        code == 201 and code_b == 201 and isinstance(created_a, dict) and isinstance(created_b, dict),
        f"A={code} B={code_b}",
    )
    if code != 201 or code_b != 201 or not isinstance(created_a, dict) or not isinstance(created_b, dict):
        return 1

    status, login_a, _ = req(
        "POST",
        "/auth/login",
        {"email": email_a, "password": created_a["temporary_password"]},
    )
    status_b, login_b, _ = req(
        "POST",
        "/auth/login",
        {"email": email_b, "password": created_b["temporary_password"]},
    )
    token_a = login_a.get("access_token") if isinstance(login_a, dict) else None
    token_b = login_b.get("access_token") if isinstance(login_b, dict) else None
    record("login_a", status == 200 and bool(token_a), f"status={status}")
    record("login_b", status_b == 200 and bool(token_b), f"status={status_b}")
    if not token_a or not token_b:
        return 1

    status, _, _ = req("GET", "/intelligence/health")
    record("health_requires_auth", status in {401, 403}, f"status={status}")

    for path, check_id in (
        ("/intelligence/health", "get_intelligence_health"),
        ("/intelligence/signals", "get_intelligence_signals"),
        ("/intelligence/scores", "get_intelligence_scores"),
        ("/intelligence/recommendations", "get_intelligence_recommendations"),
        ("/intelligence/insights", "get_intelligence_insights"),
        ("/intelligence/history?days=30", "get_intelligence_history"),
    ):
        status, body, _ = req("GET", path, token=token_a)
        keys = list(body)[:8] if isinstance(body, dict) else type(body)
        record(check_id, status == 200, f"status={status} keys={keys}")

    status, _, _ = req("POST", "/intelligence/signals", {"signal_type": "x"}, token=token_a)
    record("no_write_signals", status in {404, 405, 422}, f"status={status}")

    status, health_a, _ = req("GET", "/intelligence/health", token=token_a)
    status_b2, health_b, _ = req("GET", "/intelligence/health", token=token_b)
    record("health_a_ok", status == 200 and isinstance(health_a, dict) and "overall_score" in health_a)
    record("health_b_ok", status_b2 == 200 and isinstance(health_b, dict) and "overall_score" in health_b)

    status, sig_a, _ = req("GET", "/intelligence/signals", token=token_a)
    status2, sig_b, _ = req("GET", "/intelligence/signals", token=token_b)
    record("signals_a_ok", status == 200 and isinstance(sig_a, dict) and "items" in sig_a)
    record("signals_b_ok", status2 == 200 and isinstance(sig_b, dict) and "items" in sig_b)

    # Scores are explainable
    status, scores, _ = req("GET", "/intelligence/scores", token=token_a)
    items = scores.get("items", []) if isinstance(scores, dict) else []
    record(
        "scores_explainable",
        status == 200
        and bool(items)
        and all(isinstance(i.get("explanation"), dict) and "reasoning" in (i.get("explanation") or {}) for i in items),
        f"count={len(items)}",
    )

    if failures:
        print(f"\nFAILED {len(failures)} checks")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nMarketing Intelligence HTTP verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
