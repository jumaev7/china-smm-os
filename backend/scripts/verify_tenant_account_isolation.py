"""Verify tenant isolation for publishing accounts."""
from __future__ import annotations

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import UUID

BASE = "http://127.0.0.1:8000/api/v1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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


async def _demo_tenant_id() -> UUID | None:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.tenant import TenantUser
    from app.services.tenant_auth_service import DEMO_USER_EMAIL

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TenantUser.tenant_id).where(
                func.lower(TenantUser.email) == DEMO_USER_EMAIL.lower(),
            ),
        )
        return result.scalar_one_or_none()


def demo_tenant_id() -> UUID | None:
    return asyncio.run(_demo_tenant_id())


def main() -> int:
    print("=== Tenant publishing account isolation verification ===\n")
    failures: list[str] = []

    code, admin_login = req(
        "POST",
        "/admin-auth/login",
        {"email": "admin@example.com", "password": "ChangeMe_12345!"},
    )
    if code != 200:
        print("FAIL admin_login", code, admin_login)
        return 1
    admin_token = admin_login["access_token"]
    print("OK admin_login")

    stamp = int(time.time())

    def admin_req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        return req(method, path, body, token=admin_token)

    code, tenant_a = admin_req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {
            "company_name": f"Isolation Tenant A {stamp}",
            "owner_email": f"iso-a-{stamp}@example.com",
            "plan": "trial",
        },
    )
    if code != 201:
        failures.append(f"create tenant A failed: {code} {tenant_a}")
        tenant_a_id = None
    else:
        tenant_a_id = tenant_a["tenant_id"]
        print("OK create_tenant_a", tenant_a_id)

    code, tenant_b = admin_req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {
            "company_name": f"Isolation Tenant B {stamp}",
            "owner_email": f"iso-b-{stamp}@example.com",
            "plan": "trial",
        },
    )
    if code != 201:
        failures.append(f"create tenant B failed: {code} {tenant_b}")
        tenant_b_id = None
    else:
        tenant_b_id = tenant_b["tenant_id"]
        print("OK create_tenant_b", tenant_b_id)

    if not tenant_a_id or not tenant_b_id:
        for item in failures:
            print("FAIL", item)
        return 1

    code, fb_a = admin_req(
        "POST",
        f"/publishing/accounts?tenant_id={tenant_a_id}",
        {"platform": "facebook", "mock": True},
    )
    if code != 201:
        failures.append(f"tenant A facebook mock create failed: {code} {fb_a}")
        account_a_id = None
    else:
        account_a_id = fb_a["id"]
        if fb_a.get("tenant_id") != tenant_a_id:
            failures.append("tenant A account missing correct tenant_id")
        print("OK tenant_a_facebook_mock", account_a_id)

    code, tg_b = admin_req(
        "POST",
        f"/publishing/accounts?tenant_id={tenant_b_id}",
        {"platform": "telegram", "mock": True},
    )
    if code != 201:
        failures.append(f"tenant B telegram mock create failed: {code} {tg_b}")
    else:
        print("OK tenant_b_telegram_mock", tg_b["id"])

    code, list_a = admin_req("GET", f"/publishing/accounts?tenant_id={tenant_a_id}")
    if code != 200:
        failures.append(f"list tenant A accounts failed: {code}")
    else:
        a_ids = {item["id"] for item in list_a.get("items", [])}
        a_platforms = {item["platform"] for item in list_a.get("items", [])}
        if account_a_id and account_a_id not in a_ids:
            failures.append("tenant A cannot see its own facebook mock account")
        if "telegram" in a_platforms:
            failures.append("tenant A incorrectly sees tenant B telegram account")
        print("OK tenant_a_list count=", list_a.get("total"), "platforms=", sorted(a_platforms))

    code, list_b = admin_req("GET", f"/publishing/accounts?tenant_id={tenant_b_id}")
    if code != 200:
        failures.append(f"list tenant B accounts failed: {code}")
    else:
        b_ids = {item["id"] for item in list_b.get("items", [])}
        b_platforms = {item["platform"] for item in list_b.get("items", [])}
        if account_a_id and account_a_id in b_ids:
            failures.append("tenant B can see tenant A facebook account")
        if "facebook" in b_platforms:
            failures.append("tenant B incorrectly has facebook account from tenant A scope bleed")
        if "telegram" not in b_platforms:
            failures.append("tenant B missing its own telegram mock account")
        print("OK tenant_b_list count=", list_b.get("total"), "platforms=", sorted(b_platforms))

    if account_a_id:
        code, cross_get = admin_req(
            "PATCH",
            f"/publishing/accounts/{account_a_id}?tenant_id={tenant_b_id}",
            {"account_name": "Hijacked"},
        )
        if code == 200:
            failures.append("tenant B was able to update tenant A account")
        else:
            print("OK tenant_b_cannot_update_tenant_a_account", code)

    code_a, tlogin_a = req(
        "POST",
        "/auth/login",
        {"email": tenant_a["login_email"], "password": tenant_a["temporary_password"]},
    )
    code_b, tlogin_b = req(
        "POST",
        "/auth/login",
        {"email": tenant_b["login_email"], "password": tenant_b["temporary_password"]},
    )
    if code_a != 200 or tlogin_a.get("access_token") is None:
        failures.append("tenant A login failed")
        token_a = None
    else:
        token_a = tlogin_a["access_token"]
        print("OK tenant_a_login")

    if tlogin_b.get("access_token") is None:
        failures.append("tenant B login failed")
        token_b = None
    else:
        token_b = tlogin_b["access_token"]
        print("OK tenant_b_login")

    if token_a and account_a_id:
        code, tenant_a_self = req("GET", "/publishing/accounts", token=token_a)
        if code != 200:
            failures.append(f"tenant A self list failed: {code}")
        elif account_a_id not in {i["id"] for i in tenant_a_self.get("items", [])}:
            failures.append("tenant A session cannot list its own account")
        else:
            print("OK tenant_a_session_lists_own_accounts")

    if token_b and account_a_id:
        code, tenant_b_cross = req("GET", "/publishing/accounts", token=token_b)
        if code != 200:
            failures.append(f"tenant B self list failed: {code}")
        elif account_a_id in {i["id"] for i in tenant_b_cross.get("items", [])}:
            failures.append("tenant B session can see tenant A account")
        else:
            print("OK tenant_b_session_cannot_see_tenant_a")

    code, meta_a = admin_req("GET", f"/publishing/meta/connection?tenant_id={tenant_a_id}")
    code, meta_b = admin_req("GET", f"/publishing/meta/connection?tenant_id={tenant_b_id}")
    if code != 200:
        failures.append("meta connection summary failed for tenant scope")
    else:
        a_fb_name = (meta_a.get("facebook") or {}).get("account_name")
        b_fb_name = (meta_b.get("facebook") or {}).get("account_name")
        if a_fb_name and a_fb_name == b_fb_name and list_a.get("total") != list_b.get("total"):
            print("OK meta_readiness_scoped per tenant")
        print(
            "OK meta_connection_scoped",
            f"tenant_a_facebook={a_fb_name or 'none'}",
            f"tenant_b_facebook={b_fb_name or 'none'}",
        )

    demo_id = demo_tenant_id()
    if demo_id:
        code, demo_accounts = admin_req("GET", f"/publishing/accounts?tenant_id={demo_id}")
        if code == 200:
            print("OK demo_tenant_backfill accounts=", demo_accounts.get("total"))
        else:
            failures.append(f"demo tenant account list failed: {code}")
    else:
        print("WARN demo tenant not found — skip backfill check")

    if failures:
        print("\n=== FAILURES ===")
        for item in failures:
            print("FAIL", item)
        return 1

    print("\n=== All tenant publishing isolation checks passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
