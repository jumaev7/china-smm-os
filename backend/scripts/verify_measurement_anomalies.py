"""DB verification for measurement anomaly detection.

Run from backend/:  python scripts/verify_measurement_anomalies.py
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
        TenantMeasurementAnomaly,
        TenantMetricIngestionRun,
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
    from app.services.measurement.anomaly_checks import evaluate_snapshot_anomalies
    from app.services.measurement.publication_registry import register_from_publish_attempt
    from app.services.measurement.read_service import list_anomalies

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

    async def _snap(db, tenant_id, pub, run_id, observed_at, values: dict[str, tuple[Decimal, str, str]]):
        snap = TenantPublicationMetricSnapshot(
            id=uuid4(),
            tenant_id=tenant_id,
            external_publication_id=pub.id,
            publishing_account_id=pub.publishing_account_id,
            platform=pub.platform,
            observed_at=observed_at,
            provider_data_timestamp=observed_at,
            snapshot_fingerprint=f"anom-{uuid4().hex}",
            ingestion_run_id=run_id,
            status="complete",
            source="provider",
            raw_metric_summary={"metric_count": len(values)},
        )
        db.add(snap)
        await db.flush()
        rows = []
        for key, (val, vtype, agg) in values.items():
            row = TenantPublicationMetricValue(
                id=uuid4(),
                tenant_id=tenant_id,
                metric_snapshot_id=snap.id,
                external_publication_id=pub.id,
                metric_key=key,
                provider_metric_key=key if not key.startswith("provider:") else key.split(":")[-1],
                metric_value=val,
                value_type=vtype,
                aggregation_type=agg,
                metric_semantics_version="1.0.0",
                normalization_status="normalized" if key in {"likes", "impressions"} else (
                    "derived" if key.endswith("rate") or key == "engagements" else "normalized"
                ),
            )
            if key == "engagement_rate_by_impressions":
                row.normalization_status = "derived"
            db.add(row)
            rows.append(row)
        await db.flush()
        return snap, rows

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Meas Anom A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas Anom B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"meas-anom-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(
            id=uuid4(), tenant_id=tenant_a.id, company_name=f"Anom Client {stamp}",
            business_category="manufacturing", status="active",
        )
        content_a = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["mock"], status="draft",
            caption_long_en="Anomaly verification content.",
        )
        account = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="mock",
            account_name=f"Anom Mock {stamp}", account_id=f"anom-{stamp}", status="mock",
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
        pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=attempt,
            result={
                "success": True,
                "platform": "mock",
                "platform_post_id": f"anom-post-{stamp}",
                "post_url": f"https://example.com/posts/anom-{stamp}",
                "mock": True,
            },
            account=account,
        )
        await db.commit()

        run = TenantMetricIngestionRun(
            id=uuid4(), tenant_id=tenant_a.id, publishing_account_id=account.id,
            platform="mock", status="succeeded",
            requested_at=datetime.now(timezone.utc),
            publications_requested=1, publications_succeeded=1,
        )
        db.add(run)
        await db.flush()

        t0 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        prev_snap, prev_vals = await _snap(
            db, tenant_a.id, pub, run.id, t0,
            {
                "likes": (Decimal(100), "count", "cumulative"),
                "impressions": (Decimal(1000), "count", "cumulative"),
            },
        )

        # Negative + ratio OOR + cumulative decrease + extreme jump + time regress
        cur_snap, cur_vals = await _snap(
            db, tenant_a.id, pub, run.id, t0 - timedelta(hours=1),  # time regression
            {
                "likes": (Decimal(-5), "count", "cumulative"),
                "impressions": (Decimal(50), "count", "cumulative"),  # decrease
                "engagement_rate_by_impressions": (Decimal("1.5"), "ratio", "derived"),
            },
        )
        # Fix provider timestamp regression separately by setting timestamps
        cur_snap.provider_data_timestamp = t0 - timedelta(hours=2)
        prev_snap.provider_data_timestamp = t0
        await db.flush()

        anomalies = await evaluate_snapshot_anomalies(
            db,
            tenant_id=tenant_a.id,
            external_publication_id=pub.id,
            snapshot=cur_snap,
            values=cur_vals,
            previous_snapshot=prev_snap,
            previous_values=prev_vals,
        )
        await db.commit()
        keys = {a.anomaly_key for a in anomalies}
        record("detect_negative_metric", "negative_metric" in keys)
        record("detect_ratio_out_of_range", "ratio_out_of_range" in keys)
        record("detect_cumulative_decreased", "cumulative_metric_decreased" in keys)
        record("detect_snapshot_time_regressed", "snapshot_time_regressed" in keys)
        record("detect_provider_timestamp_regressed", "provider_timestamp_regressed" in keys)

        # Extreme jump on a later snapshot
        jump_snap, jump_vals = await _snap(
            db, tenant_a.id, pub, run.id, t0 + timedelta(hours=2),
            {
                "likes": (Decimal(20000), "count", "cumulative"),
                "impressions": (Decimal(2000), "count", "cumulative"),
            },
        )
        jump_anoms = await evaluate_snapshot_anomalies(
            db,
            tenant_id=tenant_a.id,
            external_publication_id=pub.id,
            snapshot=jump_snap,
            values=jump_vals,
            previous_snapshot=prev_snap,
            previous_values=prev_vals,
        )
        await db.commit()
        jump_keys = {a.anomaly_key for a in jump_anoms}
        record("detect_extreme_jump", "extreme_jump" in jump_keys, str(sorted(jump_keys)))

        listed, listed_total = await list_anomalies(db, tenant_a.id, limit=100)
        record("list_anomalies_tenant_scoped", listed_total >= 1 and len(listed) >= 1)
        # Evidence must not contain captions/tokens
        safe = True
        for a in listed:
            blob = str(a.evidence or {}).lower()
            if "token" in blob or "caption" in blob or "jwt" in blob:
                safe = False
                break
        record("anomaly_evidence_safe", safe)

        foreign, foreign_total = await list_anomalies(db, tenant_b.id, limit=100)
        record("cross_tenant_anomalies_empty", foreign_total == 0 and foreign == [])

        # Dedup open anomalies
        again = await evaluate_snapshot_anomalies(
            db,
            tenant_id=tenant_a.id,
            external_publication_id=pub.id,
            snapshot=cur_snap,
            values=cur_vals,
            previous_snapshot=prev_snap,
            previous_values=prev_vals,
        )
        await db.commit()
        open_neg = list(
            (
                await db.execute(
                    select(TenantMeasurementAnomaly).where(
                        TenantMeasurementAnomaly.tenant_id == tenant_a.id,
                        TenantMeasurementAnomaly.external_publication_id == pub.id,
                        TenantMeasurementAnomaly.anomaly_key == "negative_metric",
                        TenantMeasurementAnomaly.status == "open",
                    )
                )
            ).scalars().all()
        )
        record("open_anomaly_deduped", len(open_neg) == 1, str(len(open_neg)))

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
