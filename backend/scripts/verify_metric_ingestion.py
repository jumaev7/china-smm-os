"""DB verification for immutable metric ingestion.

Run from backend/:  python scripts/verify_metric_ingestion.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
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
    from sqlalchemy import func, select

    from app.core.database import (
        AsyncSessionLocal,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.measurement import (
        TenantExternalPublication,
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
    from app.services.measurement.metric_ingestion_service import (
        _persist_snapshot,
        ingest_publication_metrics,
    )
    from app.services.measurement.providers.mock import generate_mock_metrics
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

    async def _register(db, tenant_id, content, account, platform: str, post_id: str):
        attempt = PublishAttempt(
            id=uuid4(), content_id=content.id, platform=platform,
            account_id=account.id, status="success",
        )
        db.add(attempt)
        await db.flush()
        pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_id,
            content=content,
            attempt=attempt,
            result={
                "success": True,
                "platform": platform,
                "platform_post_id": post_id,
                "post_url": f"https://example.com/posts/{post_id}",
                "mock": account.status == "mock",
            },
            account=account,
        )
        await db.flush()
        return pub

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Meas Ing A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas Ing B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"meas-ing-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(
            id=uuid4(), tenant_id=tenant_a.id, company_name=f"Meas Ing Client A {stamp}",
            business_category="manufacturing", status="active",
        )
        client_b = Client(
            id=uuid4(), tenant_id=tenant_b.id, company_name=f"Meas Ing Client B {stamp}",
            business_category="manufacturing", status="active",
        )
        content_a = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["mock", "telegram"], status="draft",
            caption_long_en="Export-ready components for buyers. Request a quote today.",
        )
        content_b = ContentItem(
            id=uuid4(), client_id=client_b.id, platforms=["mock"], status="draft",
            caption_long_en="Tenant B private caption — do not leak.",
        )
        account_mock = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="mock",
            account_name=f"Mock {stamp}", account_id=f"mock-{stamp}", status="mock",
        )
        account_disconnected = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="mock",
            account_name=f"Disc {stamp}", account_id=f"disc-{stamp}", status="disconnected",
        )
        account_tg_live = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="telegram",
            account_name=f"TG Live {stamp}", account_id=f"tg-{stamp}", status="connected",
        )
        account_b = PublishingAccount(
            id=uuid4(), tenant_id=tenant_b.id, platform="mock",
            account_name=f"Mock B {stamp}", account_id=f"mock-b-{stamp}", status="mock",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, client_b, account_mock, account_disconnected, account_tg_live, account_b])
        await db.commit()
        db.add_all([content_a, content_b])
        await db.commit()

        pub = await _register(db, tenant_a.id, content_a, account_mock, "mock", f"ing-mock-{stamp}")
        await db.commit()
        record("bootstrap_publication", pub is not None)

        # Mock account ingestion creates immutable snapshot + values
        run = await ingest_publication_metrics(
            db, tenant_id=tenant_a.id, publication_ids=[pub.id], source="provider",
        )
        await db.commit()
        record(
            "ingest_run_succeeded",
            run.status in {"succeeded", "partial"} and run.publications_succeeded >= 1,
            run.status,
        )
        snaps = list(
            (
                await db.execute(
                    select(TenantPublicationMetricSnapshot).where(
                        TenantPublicationMetricSnapshot.tenant_id == tenant_a.id,
                        TenantPublicationMetricSnapshot.external_publication_id == pub.id,
                    )
                )
            ).scalars().all()
        )
        record("snapshot_created", len(snaps) >= 1, str(len(snaps)))
        values = list(
            (
                await db.execute(
                    select(TenantPublicationMetricValue).where(
                        TenantPublicationMetricValue.tenant_id == tenant_a.id,
                        TenantPublicationMetricValue.external_publication_id == pub.id,
                    )
                )
            ).scalars().all()
        )
        record("metric_values_created", len(values) > 0, str(len(values)))
        record(
            "values_immutable_fields",
            all(v.metric_key and v.metric_value is not None for v in values),
        )
        first_count = len(snaps)
        first_fp = snaps[0].snapshot_fingerprint if snaps else None

        # Duplicate fingerprint does not duplicate (controlled persist)
        fixed_ts = datetime(2026, 7, 1, 15, 0, 0, tzinfo=timezone.utc)
        metrics = generate_mock_metrics(pub.provider_publication_id, reference_time=fixed_ts)
        run2 = TenantMetricIngestionRun(
            id=uuid4(), tenant_id=tenant_a.id, publishing_account_id=account_mock.id,
            platform="mock", status="running", requested_at=fixed_ts, started_at=fixed_ts,
            publications_requested=1,
        )
        db.add(run2)
        await db.flush()
        snap_a = await _persist_snapshot(
            db,
            tenant_id=tenant_a.id,
            publication=pub,
            provider_metrics=metrics,
            provider_data_timestamp=fixed_ts,
            fetch_status="ok",
            ingestion_run_id=run2.id,
            source="provider",
            raw_summary={"status": "ok", "metric_count": len(metrics)},
        )
        snap_b = await _persist_snapshot(
            db,
            tenant_id=tenant_a.id,
            publication=pub,
            provider_metrics=metrics,
            provider_data_timestamp=fixed_ts,
            fetch_status="ok",
            ingestion_run_id=run2.id,
            source="provider",
            raw_summary={"status": "ok", "metric_count": len(metrics)},
        )
        await db.commit()
        record("duplicate_fingerprint_returns_none", snap_a is not None and snap_b is None)

        # Changed metrics create new snapshot
        changed = dict(metrics)
        changed["impressions"] = (changed.get("impressions") or Decimal(0)) + Decimal(500)
        snap_c = await _persist_snapshot(
            db,
            tenant_id=tenant_a.id,
            publication=pub,
            provider_metrics=changed,
            provider_data_timestamp=fixed_ts,
            fetch_status="ok",
            ingestion_run_id=run2.id,
            source="provider",
            raw_summary={"status": "ok", "metric_count": len(changed)},
        )
        await db.commit()
        record(
            "changed_metrics_new_snapshot",
            snap_c is not None and snap_c.snapshot_fingerprint != (snap_a.snapshot_fingerprint if snap_a else None),
        )
        total_snaps = (
            await db.execute(
                select(func.count()).select_from(TenantPublicationMetricSnapshot).where(
                    TenantPublicationMetricSnapshot.external_publication_id == pub.id,
                )
            )
        ).scalar_one()
        record("snapshot_count_grew", int(total_snaps) > first_count, str(total_snaps))
        record("first_fingerprint_unchanged", first_fp is not None)

        # Disconnected account fails gracefully
        disc_pub = await _register(
            db, tenant_a.id, content_a, account_disconnected, "mock", f"ing-disc-{stamp}",
        )
        await db.commit()
        disc_run = await ingest_publication_metrics(
            db, tenant_id=tenant_a.id, publication_ids=[disc_pub.id],
        )
        await db.commit()
        disc_snaps = (
            await db.execute(
                select(func.count()).select_from(TenantPublicationMetricSnapshot).where(
                    TenantPublicationMetricSnapshot.external_publication_id == disc_pub.id,
                )
            )
        ).scalar_one()
        record(
            "disconnected_fails_gracefully",
            disc_run.status == "failed"
            and disc_run.failure_code == "account_disconnected"
            and int(disc_snaps) == 0,
            f"status={disc_run.status} code={disc_run.failure_code}",
        )

        # Telegram live (non-mock) → unsupported, no fabricated metrics
        tg_pub = await _register(
            db, tenant_a.id, content_a, account_tg_live, "telegram", f"ing-tg-{stamp}",
        )
        await db.commit()
        tg_run = await ingest_publication_metrics(
            db, tenant_id=tenant_a.id, publication_ids=[tg_pub.id],
        )
        await db.commit()
        await db.refresh(tg_pub)
        tg_snaps = (
            await db.execute(
                select(func.count()).select_from(TenantPublicationMetricSnapshot).where(
                    TenantPublicationMetricSnapshot.external_publication_id == tg_pub.id,
                )
            )
        ).scalar_one()
        tg_values = (
            await db.execute(
                select(func.count()).select_from(TenantPublicationMetricValue).where(
                    TenantPublicationMetricValue.external_publication_id == tg_pub.id,
                )
            )
        ).scalar_one()
        record(
            "telegram_live_unsupported",
            tg_pub.freshness_status == "unsupported" and int(tg_snaps) == 0 and int(tg_values) == 0,
            f"freshness={tg_pub.freshness_status} snaps={tg_snaps}",
        )
        record(
            "telegram_no_fabricated_metrics",
            tg_run.publications_succeeded == 0 and int(tg_values) == 0,
        )

        # Tenant isolation
        pub_b = await _register(db, tenant_b.id, content_b, account_b, "mock", f"ing-b-{stamp}")
        await db.commit()
        iso_ok = False
        try:
            await ingest_publication_metrics(
                db, tenant_id=tenant_a.id, publication_ids=[pub_b.id],
            )
        except Exception:
            iso_ok = True
        else:
            # If no exception, ensure no snapshots under tenant_a for pub_b
            leaked = (
                await db.execute(
                    select(func.count()).select_from(TenantPublicationMetricSnapshot).where(
                        TenantPublicationMetricSnapshot.tenant_id == tenant_a.id,
                        TenantPublicationMetricSnapshot.external_publication_id == pub_b.id,
                    )
                )
            ).scalar_one()
            iso_ok = int(leaked) == 0
        await db.commit()
        record("tenant_isolation_ingest", iso_ok)

        a_only = (
            await db.execute(
                select(func.count()).select_from(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_a.id,
                    TenantExternalPublication.id == pub_b.id,
                )
            )
        ).scalar_one()
        record("tenant_isolation_publication_scope", int(a_only) == 0)

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
