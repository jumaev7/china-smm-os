"""DB verification for measurement freshness classification.

Run from backend/:  python scripts/verify_measurement_freshness.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    import asyncio
    return asyncio.run(_run())


async def _run() -> int:
    from app.core.database import (
        AsyncSessionLocal,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.publish_attempt import PublishAttempt
    from app.models.publishing_account import PublishingAccount
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.measurement.freshness_service import (
        compute_freshness,
        next_collection_at,
        refresh_publication_freshness,
    )
    from app.services.measurement.publication_registry import register_from_publish_attempt
    from app.services.measurement.read_service import freshness_overview

    await ensure_platform_event_bus_schema()
    await ensure_measurement_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)

    # Pure compute checks
    record("compute_fresh", compute_freshness(last_metric_at=now - timedelta(hours=2), now=now).status == "fresh")
    record("compute_aging", compute_freshness(last_metric_at=now - timedelta(hours=20), now=now).status == "aging")
    record("compute_stale", compute_freshness(last_metric_at=now - timedelta(hours=40), now=now).status == "stale")
    record(
        "compute_unsupported",
        compute_freshness(last_metric_at=None, capability_status="unsupported", now=now).status == "unsupported",
    )
    record("compute_unavailable", compute_freshness(last_metric_at=None, now=now).status == "unavailable")
    record(
        "compute_disconnected",
        compute_freshness(
            last_metric_at=now - timedelta(hours=1), account_status="disconnected", now=now,
        ).status == "unavailable",
    )
    nxt = next_collection_at(published_at=now - timedelta(hours=2), last_metric_at=now - timedelta(hours=1), now=now)
    record("next_collection_in_future_or_now", nxt >= now)

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Meas Fresh A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas Fresh B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"meas-fresh-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(
            id=uuid4(), tenant_id=tenant_a.id, company_name=f"Fresh Client {stamp}",
            business_category="manufacturing", status="active",
        )
        content_a = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["mock", "telegram"], status="draft",
            caption_long_en="Freshness verification content.",
        )
        account_mock = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="mock",
            account_name=f"Fresh Mock {stamp}", account_id=f"fresh-{stamp}", status="mock",
        )
        account_tg = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="telegram",
            account_name=f"Fresh TG {stamp}", account_id=f"fresh-tg-{stamp}", status="connected",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, account_mock, account_tg])
        await db.commit()
        db.add(content_a)
        await db.commit()

        attempt = PublishAttempt(
            id=uuid4(), content_id=content_a.id, platform="mock",
            account_id=account_mock.id, status="success",
        )
        db.add(attempt)
        await db.commit()
        pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=attempt,
            result={
                "success": True,
                "platform": "mock",
                "platform_post_id": f"fresh-post-{stamp}",
                "post_url": f"https://example.com/posts/fresh-{stamp}",
                "mock": True,
            },
            account=account_mock,
        )
        await db.commit()

        pub.last_metric_at = now - timedelta(hours=1)
        await db.commit()
        result = await refresh_publication_freshness(db, tenant_a.id, pub.id, now=now)
        await db.commit()
        await db.refresh(pub)
        record("refresh_persists_fresh", result.status == "fresh" and pub.freshness_status == "fresh")

        pub.last_metric_at = now - timedelta(hours=48)
        await db.commit()
        result = await refresh_publication_freshness(db, tenant_a.id, pub.id, now=now)
        await db.commit()
        await db.refresh(pub)
        record("refresh_persists_stale", result.status == "stale" and pub.freshness_status == "stale")

        tg_attempt = PublishAttempt(
            id=uuid4(), content_id=content_a.id, platform="telegram",
            account_id=account_tg.id, status="success",
        )
        db.add(tg_attempt)
        await db.commit()
        tg_pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=tg_attempt,
            result={
                "success": True,
                "platform": "telegram",
                "platform_post_id": f"fresh-tg-{stamp}",
                "post_url": f"https://t.me/c/1/{stamp}",
                "mock": False,
            },
            account=account_tg,
        )
        await db.commit()
        tg_result = await refresh_publication_freshness(db, tenant_a.id, tg_pub.id, now=now)
        await db.commit()
        record(
            "telegram_live_unsupported_or_unavailable",
            tg_result.status in {"unsupported", "unavailable"},
            tg_result.status,
        )

        overview = await freshness_overview(db, tenant_a.id)
        record(
            "freshness_overview_has_counts",
            isinstance(overview, dict) and "counts_by_status" in overview,
            str(sorted(overview.keys()) if isinstance(overview, dict) else type(overview)),
        )
        record("freshness_overview_callable", overview is not None)

        iso = False
        try:
            await refresh_publication_freshness(db, tenant_b.id, pub.id, now=now)
        except Exception:
            iso = True
        record("cross_tenant_freshness_rejected", iso)

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
