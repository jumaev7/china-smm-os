"""DB verification for publication metric aggregation.

Run from backend/:  python scripts/verify_metric_aggregation.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
    from sqlalchemy import select

    from app.core.database import (
        AsyncSessionLocal,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.measurement import (
        CALCULATION_VERSION,
        TenantExternalPublication,
        TenantMetricIngestionRun,
        TenantPublicationMetricAggregate,
        TenantPublicationMetricSnapshot,
        TenantPublicationMetricValue,
    )
    from app.models.publish_attempt import PublishAttempt
    from app.models.publishing_account import PublishingAccount
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.measurement.aggregation_service import (
        calculate_publication_aggregates,
        get_publication_aggregates,
        interval_delta,
    )
    from app.services.measurement.publication_registry import register_from_publish_attempt

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

    async def _add_snapshot(db, tenant_id, pub, run_id, observed_at, likes: Decimal, impressions: Decimal):
        snap = TenantPublicationMetricSnapshot(
            id=uuid4(),
            tenant_id=tenant_id,
            external_publication_id=pub.id,
            publishing_account_id=pub.publishing_account_id,
            platform=pub.platform,
            observed_at=observed_at,
            provider_data_timestamp=observed_at,
            snapshot_fingerprint=f"agg-{pub.id}-{observed_at.isoformat()}-{likes}",
            ingestion_run_id=run_id,
            status="complete",
            source="provider",
            raw_metric_summary={"metric_count": 2},
        )
        db.add(snap)
        await db.flush()
        for key, val, vtype in (
            ("likes", likes, "count"),
            ("impressions", impressions, "count"),
        ):
            db.add(
                TenantPublicationMetricValue(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    metric_snapshot_id=snap.id,
                    external_publication_id=pub.id,
                    metric_key=key,
                    provider_metric_key=key,
                    metric_value=val,
                    value_type=vtype,
                    aggregation_type="cumulative",
                    metric_semantics_version="1.0.0",
                    normalization_status="normalized",
                )
            )
        await db.flush()
        return snap

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Meas Agg A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas Agg B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"meas-agg-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(
            id=uuid4(), tenant_id=tenant_a.id, company_name=f"Agg Client {stamp}",
            business_category="manufacturing", status="active",
        )
        content_a = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["mock"], status="draft",
            caption_long_en="Aggregation verification content for measurement.",
        )
        account = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="mock",
            account_name=f"Agg Mock {stamp}", account_id=f"agg-{stamp}", status="mock",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, account])
        await db.commit()
        db.add(content_a)
        await db.commit()

        attempt = PublishAttempt(
            id=uuid4(), content_id=content_a.id, platform="mock",
            account_id=account.id, status="success",
        )
        db.add(attempt)
        await db.commit()
        published_at = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
        content_a.published_at = published_at
        await db.commit()

        pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=attempt,
            result={
                "success": True,
                "platform": "mock",
                "platform_post_id": f"agg-post-{stamp}",
                "post_url": f"https://example.com/posts/agg-{stamp}",
                "mock": True,
            },
            account=account,
        )
        await db.commit()
        pub.published_at = published_at
        await db.commit()

        run = TenantMetricIngestionRun(
            id=uuid4(), tenant_id=tenant_a.id, publishing_account_id=account.id,
            platform="mock", status="succeeded", requested_at=published_at,
            started_at=published_at, completed_at=published_at,
            publications_requested=1, publications_succeeded=1,
        )
        db.add(run)
        await db.flush()

        # Insufficient observations → no fabricated 24h window beyond latest if only one late snap
        late_only = await _add_snapshot(
            db, tenant_a.id, pub, run.id,
            published_at + timedelta(days=3),
            likes=Decimal(10), impressions=Decimal(1000),
        )
        pub.last_metric_at = late_only.observed_at
        await db.commit()

        aggs_late = await calculate_publication_aggregates(
            db,
            tenant_id=tenant_a.id,
            external_publication_id=pub.id,
            published_at=published_at,
            last_metric_at=pub.last_metric_at,
            metric_keys=["likes", "impressions"],
        )
        await db.commit()
        by_window = {(a.window_key, a.metric_key): a for a in aggs_late}
        record("latest_cumulative_present", ("lifetime", "likes") in by_window)
        record(
            "latest_cumulative_value",
            by_window.get(("lifetime", "likes")) is not None
            and by_window[("lifetime", "likes")].metric_value == Decimal(10),
        )
        record(
            "insufficient_obs_no_24h",
            ("24h", "likes") not in by_window,
            "24h must not be fabricated without in-window observations",
        )
        record(
            "calculation_version_set",
            all(a.calculation_version == CALCULATION_VERSION for a in aggs_late),
            CALCULATION_VERSION,
        )
        record(
            "calculation_method_latest",
            by_window[("lifetime", "likes")].calculation_method == "latest_cumulative",
        )

        # Add in-window observations for 24h
        snap1 = await _add_snapshot(
            db, tenant_a.id, pub, run.id,
            published_at + timedelta(hours=2),
            likes=Decimal(4), impressions=Decimal(400),
        )
        snap2 = await _add_snapshot(
            db, tenant_a.id, pub, run.id,
            published_at + timedelta(hours=20),
            likes=Decimal(9), impressions=Decimal(900),
        )
        pub.last_metric_at = snap2.observed_at
        await db.commit()

        aggs = await calculate_publication_aggregates(
            db,
            tenant_id=tenant_a.id,
            external_publication_id=pub.id,
            published_at=published_at,
            last_metric_at=pub.last_metric_at,
            metric_keys=["likes", "impressions"],
        )
        await db.commit()
        by_window = {(a.window_key, a.metric_key): a for a in aggs}
        record("window_24h_when_observations_exist", ("24h", "likes") in by_window)
        w24 = by_window.get(("24h", "likes"))
        record(
            "window_24h_no_interpolation",
            w24 is not None
            and w24.calculation_method in {"window_delta", "window_latest"}
            and w24.metric_value is not None,
            w24.calculation_method if w24 else "missing",
        )
        # Lifetime should be latest across all snaps (day-3 with 10 likes is latest by observed_at)
        lifetime = by_window.get(("lifetime", "likes"))
        record(
            "latest_is_most_recent_observation",
            lifetime is not None and lifetime.metric_value == Decimal(10),
            str(lifetime.metric_value if lifetime else None),
        )

        # interval_delta never invents
        record(
            "interval_delta_cumulative",
            interval_delta(Decimal(4), Decimal(9), aggregation_type="cumulative") == Decimal(5),
        )
        record(
            "interval_delta_non_cumulative_none",
            interval_delta(Decimal(4), Decimal(9), aggregation_type="derived") is None,
        )

        fetched = await get_publication_aggregates(db, tenant_a.id, pub.id, window_key="lifetime")
        record("get_aggregates_filters_window", all(a.window_key == "lifetime" for a in fetched) and len(fetched) > 0)

        # Tenant isolation
        other = await get_publication_aggregates(db, tenant_b.id, pub.id)
        record("cross_tenant_aggregates_empty", other == [])

        # Ensure no None-valued fabricated rows
        all_aggs = list(
            (
                await db.execute(
                    select(TenantPublicationMetricAggregate).where(
                        TenantPublicationMetricAggregate.external_publication_id == pub.id,
                    )
                )
            ).scalars().all()
        )
        record("no_null_metric_values", all(a.metric_value is not None for a in all_aggs))

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
