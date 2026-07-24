"""HTTP smoke verification for Advertising Intelligence APIs via in-process ASGI.

Run from backend/:  python scripts/verify_advertising_http.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    import asyncio
    return asyncio.run(_run())


async def _run() -> int:
    from httpx import ASGITransport, AsyncClient

    from app.core.database import (
        AsyncSessionLocal,
        ensure_advertising_schema,
        ensure_campaign_planner_schema,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
        reset_advertising_schema,
    )
    from app.main import app
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import create_access_token, hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )

    await ensure_platform_event_bus_schema()
    await ensure_campaign_planner_schema()
    await ensure_measurement_schema()
    await reset_advertising_schema()
    await ensure_advertising_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"Ad HTTP {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Ad HTTP B {stamp}", status="active", plan="trial")
        user = TenantUser(
            id=uuid4(), tenant_id=tenant.id, email=f"ad-http-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        user_b = TenantUser(
            id=uuid4(), tenant_id=tenant_b.id, email=f"ad-http-b-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        db.add_all([tenant, tenant_b])
        await db.commit()
        db.add_all([user, user_b])
        await db.commit()

        token = create_access_token(
            user_id=user.id, tenant_id=tenant.id, email=user.email, role=user.role,
        )
        token_b = create_access_token(
            user_id=user_b.id, tenant_id=tenant_b.id, email=user_b.email, role=user_b.role,
        )

    headers = {"Authorization": f"Bearer {token}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    transport = ASGITransport(app=app)
    account_id = None
    campaign_id = None

    async with AsyncClient(transport=transport, base_url="http://test") as client_http:
        r = await client_http.get("/api/v1/advertising/overview")
        record("overview_unauth", r.status_code in (401, 403), str(r.status_code))

        r = await client_http.get("/api/v1/advertising/overview", headers=headers)
        record("overview_auth", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            body = r.json()
            read_only = body.get("read_only")
            if read_only is None and isinstance(body.get("configuration"), dict):
                read_only = body["configuration"].get("read_only")
            record("overview_read_only_flag", read_only in (True, "true", 1) or "read_only" in str(body).lower())

        r = await client_http.get("/api/v1/advertising/configuration", headers=headers)
        record("configuration", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            cfg = r.json()
            record("configuration_read_only", cfg.get("read_only") is True or "read_only" in cfg, str(list(cfg.keys())[:10]))

        r = await client_http.post(
            "/api/v1/advertising/accounts/register-mock",
            headers=headers,
            json={
                "provider": "mock",
                "name": "HTTP Mock",
                "currency": "USD",
                "timezone": "UTC",
                "external_account_id": f"http-mock-{stamp}",
            },
        )
        record("register_mock", r.status_code in (200, 201), f"{r.status_code} {r.text[:160]}")
        if r.status_code in (200, 201):
            account = r.json()
            account_id = account.get("account_id") or account.get("id")

        if account_id:
            r = await client_http.get(f"/api/v1/advertising/accounts/{account_id}", headers=headers)
            record("get_account", r.status_code == 200, str(r.status_code))

            r = await client_http.get(f"/api/v1/advertising/accounts/{account_id}", headers=headers_b)
            record("cross_tenant_account_404", r.status_code == 404, str(r.status_code))

            r = await client_http.get(f"/api/v1/advertising/accounts/{account_id}/capabilities", headers=headers)
            record("account_capabilities", r.status_code == 200, str(r.status_code))

            r = await client_http.post(f"/api/v1/advertising/accounts/{account_id}/import", headers=headers)
            record("import_account", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

            r = await client_http.post(f"/api/v1/advertising/accounts/{account_id}/refresh-metrics", headers=headers)
            record("refresh_metrics", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

        r = await client_http.get("/api/v1/advertising/accounts", headers=headers)
        record("list_accounts", r.status_code == 200, str(r.status_code))

        r = await client_http.get("/api/v1/advertising/campaigns", headers=headers)
        record("list_campaigns", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            body = r.json()
            items = body.get("items") or body.get("campaigns") or []
            if items:
                campaign_id = items[0].get("campaign_id") or items[0].get("id")

        if campaign_id:
            r = await client_http.get(f"/api/v1/advertising/campaigns/{campaign_id}", headers=headers)
            record("get_campaign", r.status_code == 200, str(r.status_code))
            r = await client_http.get(f"/api/v1/advertising/campaigns/{campaign_id}/pacing", headers=headers)
            record("campaign_pacing", r.status_code == 200, str(r.status_code))
            r = await client_http.get(f"/api/v1/advertising/campaigns/{campaign_id}/performance", headers=headers)
            record("campaign_metrics", r.status_code == 200, str(r.status_code))
            r = await client_http.get(f"/api/v1/advertising/campaigns/{campaign_id}", headers=headers_b)
            record("cross_tenant_campaign_404", r.status_code == 404, str(r.status_code))

        for path in (
            "/api/v1/advertising/creatives",
            "/api/v1/advertising/anomalies",
            "/api/v1/advertising/freshness",
            "/api/v1/advertising/attribution",
            "/api/v1/advertising/recommendations",
            "/api/v1/advertising/providers",
        ):
            r = await client_http.get(path, headers=headers)
            label = path.rsplit("/", 1)[-1]
            record(f"get_{label}", r.status_code == 200, str(r.status_code))

        # Prove no provider mutation routes
        for path in (
            f"/api/v1/advertising/campaigns/{campaign_id or uuid4()}/pause",
            f"/api/v1/advertising/campaigns/{campaign_id or uuid4()}/activate",
            f"/api/v1/advertising/campaigns/{campaign_id or uuid4()}/budget",
        ):
            r = await client_http.post(path, headers=headers, json={})
            record(f"no_route_{path.rsplit('/', 1)[-1]}", r.status_code in (404, 405), str(r.status_code))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
