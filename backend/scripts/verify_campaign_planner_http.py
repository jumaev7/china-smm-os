"""HTTP verification for Campaign Planner APIs via TestClient.

Run from backend/:  python scripts/verify_campaign_planner_http.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
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
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_campaign_planner_schema, ensure_platform_event_bus_schema
    from app.main import app
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import create_access_token, hash_password
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration

    await ensure_platform_event_bus_schema()
    await ensure_campaign_planner_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"CP HTTP {stamp}", status="active", plan="trial")
        user = TenantUser(
            id=uuid4(), tenant_id=tenant.id, email=f"cp-http-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        db.add_all([tenant, user])
        await db.commit()
        token = create_access_token(
            user_id=user.id, tenant_id=tenant.id, email=user.email, role=user.role,
        )

    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/campaign-planner/campaigns", headers=headers)
        record("list_campaigns_auth", r.status_code == 200, str(r.status_code))

        r = await client.get("/api/v1/campaign-planner/campaigns")
        record("list_campaigns_unauth", r.status_code in (401, 403), str(r.status_code))

        r = await client.post(
            "/api/v1/campaign-planner/campaigns",
            headers=headers,
            json={
                "name": f"HTTP Campaign {stamp}",
                "timezone": "America/New_York",
                "primary_locale": "en",
                "locales": ["en"],
                "platforms": ["telegram"],
                "start_date": "2026-05-01",
                "end_date": "2026-05-07",
                "cadence": {"posts_per_week": 2},
            },
        )
        record("create_campaign", r.status_code == 200, str(r.status_code))
        campaign_id = r.json()["id"] if r.status_code == 200 else None

        if campaign_id:
            r = await client.post(
                f"/api/v1/campaign-planner/campaigns/{campaign_id}/plans/generate",
                headers=headers,
                json={},
            )
            record("generate_plan_http", r.status_code == 200, str(r.status_code))
            plan_id = r.json().get("id") if r.status_code == 200 else None
            if plan_id:
                r = await client.get(
                    f"/api/v1/campaign-planner/campaigns/{campaign_id}/plans/{plan_id}/slots",
                    headers=headers,
                )
                record("list_slots_http", r.status_code == 200 and r.json().get("total", 0) >= 0, str(r.status_code))

                r = await client.post(
                    f"/api/v1/campaign-planner/campaigns/{campaign_id}/plans/{plan_id}/publish",
                    headers=headers,
                )
                record("publish_plan_http", r.status_code == 200 and r.json().get("status") == "published")

            # wrong tenant id as path — still 404 when campaign doesn't belong
            fake = str(uuid4())
            r = await client.get(f"/api/v1/campaign-planner/campaigns/{fake}", headers=headers)
            record("missing_campaign_404", r.status_code == 404, str(r.status_code))

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
