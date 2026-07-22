"""HTTP smoke verification for Measurement APIs via in-process ASGI.

Run from backend/:  python scripts/verify_measurement_http.py
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
        ensure_campaign_planner_schema,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
    )
    from app.main import app
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.publish_attempt import PublishAttempt
    from app.models.publishing_account import PublishingAccount
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import create_access_token, hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.measurement.metric_ingestion_service import ingest_publication_metrics
    from app.services.measurement.publication_registry import register_from_publish_attempt

    await ensure_platform_event_bus_schema()
    await ensure_campaign_planner_schema()
    await ensure_measurement_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"Meas HTTP {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas HTTP B {stamp}", status="active", plan="trial")
        user = TenantUser(
            id=uuid4(), tenant_id=tenant.id, email=f"meas-http-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        user_b = TenantUser(
            id=uuid4(), tenant_id=tenant_b.id, email=f"meas-http-b-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client = Client(
            id=uuid4(), tenant_id=tenant.id, company_name=f"HTTP Client {stamp}",
            business_category="manufacturing", status="active",
        )
        content = ContentItem(
            id=uuid4(), client_id=client.id, platforms=["mock"], status="draft",
            caption_long_en="HTTP measurement verification content.",
        )
        account = PublishingAccount(
            id=uuid4(), tenant_id=tenant.id, platform="mock",
            account_name=f"HTTP Mock {stamp}", account_id=f"http-{stamp}", status="mock",
        )
        db.add_all([tenant, tenant_b])
        await db.commit()
        db.add_all([user, user_b, client, account])
        await db.commit()
        db.add(content)
        await db.commit()

        attempt = PublishAttempt(
            id=uuid4(), content_id=content.id, platform="mock",
            account_id=account.id, status="success",
        )
        db.add(attempt)
        await db.commit()
        pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant.id,
            content=content,
            attempt=attempt,
            result={
                "success": True,
                "platform": "mock",
                "platform_post_id": f"http-post-{stamp}",
                "post_url": f"https://example.com/posts/http-{stamp}",
                "mock": True,
            },
            account=account,
        )
        await db.commit()
        if pub is not None:
            await ingest_publication_metrics(db, tenant_id=tenant.id, publication_ids=[pub.id])
            await db.commit()

        token = create_access_token(
            user_id=user.id, tenant_id=tenant.id, email=user.email, role=user.role,
        )
        token_b = create_access_token(
            user_id=user_b.id, tenant_id=tenant_b.id, email=user_b.email, role=user_b.role,
        )
        publication_id = str(pub.id) if pub else None

    headers = {"Authorization": f"Bearer {token}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client_http:
        r = await client_http.get("/api/v1/measurement/overview", headers=headers)
        record("overview_auth", r.status_code == 200, str(r.status_code))

        r = await client_http.get("/api/v1/measurement/overview")
        record("overview_unauth", r.status_code in (401, 403), str(r.status_code))

        r = await client_http.get("/api/v1/measurement/publications", headers=headers)
        record("list_publications", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            body = r.json()
            total = body.get("total", 0)
            record("list_publications_nonempty", total >= 1, str(total))

        r = await client_http.get("/api/v1/measurement/platforms", headers=headers)
        record("platforms", r.status_code == 200, str(r.status_code))

        r = await client_http.get("/api/v1/measurement/configuration", headers=headers)
        record("configuration", r.status_code == 200, str(r.status_code))
        if r.status_code == 200:
            cfg = r.json()
            # Never assert on secrets; just ensure catalog metadata present
            record(
                "configuration_has_catalog",
                "catalog_version" in cfg or "metric_keys" in cfg or "measurement_version" in cfg,
                str(sorted(cfg.keys())[:8]),
            )

        r = await client_http.get("/api/v1/measurement/freshness", headers=headers)
        record("freshness", r.status_code == 200, str(r.status_code))

        r = await client_http.get("/api/v1/measurement/anomalies", headers=headers)
        record("anomalies", r.status_code == 200, str(r.status_code))

        if publication_id:
            r = await client_http.get(
                f"/api/v1/measurement/publications/{publication_id}", headers=headers,
            )
            record("get_publication", r.status_code == 200, str(r.status_code))

            r = await client_http.get(
                f"/api/v1/measurement/publications/{publication_id}/snapshots", headers=headers,
            )
            record("list_snapshots", r.status_code == 200, str(r.status_code))

            r = await client_http.get(
                f"/api/v1/measurement/publications/{publication_id}/metrics", headers=headers,
            )
            record("publication_metrics", r.status_code == 200, str(r.status_code))

            r = await client_http.post(
                f"/api/v1/measurement/publications/{publication_id}/refresh", headers=headers,
            )
            record("refresh_publication", r.status_code == 200, str(r.status_code))

            # Cross-tenant: tenant B must not see tenant A publication
            r = await client_http.get(
                f"/api/v1/measurement/publications/{publication_id}", headers=headers_b,
            )
            record("cross_tenant_publication_404", r.status_code == 404, str(r.status_code))

        fake = str(uuid4())
        r = await client_http.get(f"/api/v1/measurement/publications/{fake}", headers=headers)
        record("missing_publication_404", r.status_code == 404, str(r.status_code))

        r = await client_http.get("/api/v1/measurement/tracked-links", headers=headers)
        record("tracked_links_list", r.status_code == 200, str(r.status_code))

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
