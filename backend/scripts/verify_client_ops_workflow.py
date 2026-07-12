"""Verify admin client creation + tenant operations workflow (dev smoke)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000/api/v1")


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload


def main() -> int:
    code, data = req("POST", "/admin-auth/login", {"email": "admin@example.com", "password": "ChangeMe_12345!"})
    if code != 200:
        print("FAIL admin_login", code, data)
        return 1
    admin_token = data["access_token"]
    print("OK admin_login")

    stamp = int(time.time())
    email = f"ops-test-{stamp}@example.com"
    company = f"Ops Test Co {stamp}"
    code, created = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": company, "owner_email": email, "plan": "trial"},
        token=admin_token,
    )
    if code != 201:
        print("FAIL create_client", code, data)
        return 1
    print("OK create_client", created["tenant_id"], created["client_id"])
    print("  next_steps:", len(created.get("next_steps", [])))

    code, ops = req(
        "GET",
        f"/admin-auth/platform/tenants/{created['tenant_id']}/operations",
        token=admin_token,
    )
    if code != 200:
        print("FAIL operations", code, ops)
        return 1
    print("OK operations readiness=", ops.get("readiness"), "blockers=", ops.get("blockers"))

    code, tlogin = req(
        "POST",
        "/auth/login",
        {"email": email, "password": created["temporary_password"]},
    )
    if code != 200:
        print("FAIL tenant_login", code, tlogin)
        return 1
    tenant_token = tlogin["access_token"]
    print("OK tenant_login")

    code, content = req("GET", "/content?limit=5", token=tenant_token)
    if code != 200:
        print("FAIL content_list", code, content)
        return 1
    items = content.get("items") or []
    print("OK content_list total=", content.get("total"), "items=", len(items))

    item_id = items[0]["id"] if items else None
    if item_id:
        code, gen = req(
            "POST",
            f"/content/{item_id}/generate",
            {"languages": ["en", "ru"]},
            token=tenant_token,
        )
        if code != 200:
            print("FAIL ai_generate", code, gen)
            return 1
        print("OK ai_generate status=", gen.get("status"))

        code, sched = req(
            "POST",
            "/calendar/schedule",
            {
                "content_item_id": item_id,
                "scheduled_date": "2026-07-01",
                "time_slot": "morning",
                "scheduled_for": "2026-07-01T09:00:00Z",
                "platforms": ["instagram"],
            },
            token=tenant_token,
        )
        if code not in (200, 201):
            print("FAIL schedule", code, sched)
            return 1
        print("OK schedule")
    else:
        print("SKIP ai_generate schedule (no seeded content)")

    out = Path(__file__).resolve().parents[1] / "scripts" / ".verify_client_ops_last.json"
    out.write_text(json.dumps({"created": created, "operations": ops}, indent=2), encoding="utf-8")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
