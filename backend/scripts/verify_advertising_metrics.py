"""Verify Advertising metric ingestion (immutable snapshots + normalization).

Covers: an immutable metric snapshot per (entity, content fingerprint), a
duplicate fingerprint never creating a second snapshot (idempotent re-refresh),
provider-native metric keys preserved alongside normalized + derived catalog
metrics, and strict tenant isolation of snapshots/values/aggregates.

Run from backend/:  python scripts/verify_advertising_metrics.py
"""
from __future__ import annotations

import logging
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

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def main() -> int:
    import asyncio
    return asyncio.run(_run())


async def _run() -> int:
    from sqlalchemy import func, select

    from app.core.database import (
        AsyncSessionLocal,
        engine,
        ensure_campaign_planner_schema,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
        reset_advertising_schema,
    )
    from app.models.advertising import (
        TenantAdMetricAggregate,
        TenantAdMetricSnapshot,
        TenantAdMetricValue,
    )
    from app.models.tenant import Tenant
    from app.services.advertising_intelligence import (
        account_service,
        import_service,
        metric_ingestion_service,
        metric_normalizer,
    )
    from app.services.advertising_intelligence.schemas import ProviderMetric

    engine.echo = False
    await ensure_platform_event_bus_schema()
    await ensure_campaign_planner_schema()
    await reset_advertising_schema()
    await ensure_measurement_schema()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    async def _count(db, model, **filters) -> int:
        stmt = select(func.count()).select_from(model)
        for attr, val in filters.items():
            stmt = stmt.where(getattr(model, attr) == val)
        return int((await db.execute(stmt)).scalar_one() or 0)

    # ---- Pure normalization: provider-native vs normalized vs derived ----
    normalized = metric_normalizer.normalize_provider_metrics(
        [
            ProviderMetric("impressions", Decimal("1000"), value_type="count"),
            ProviderMetric("clicks", Decimal("50"), value_type="count"),
            ProviderMetric("spend_minor", Decimal("2500"), value_type="currency_minor", currency="USD"),
            ProviderMetric("some_exotic_provider_metric", Decimal("7"), value_type="count"),
        ],
        provider="mock",
        default_currency="USD",
    )
    statuses = {n.normalization_status for n in normalized}
    record("normalizer_has_normalized", "normalized" in statuses)
    record("normalizer_has_provider_native", "provider_native" in statuses, str(sorted(statuses)))
    record("normalizer_has_derived", "derived" in statuses)
    ctr = next((n for n in normalized if n.metric_key == "ctr"), None)
    record("normalizer_derived_ctr", ctr is not None and ctr.provider_metric_key is None)
    native = next((n for n in normalized if n.metric_key == "some_exotic_provider_metric"), None)
    record(
        "normalizer_preserves_provider_key",
        native is not None and native.provider_metric_key == "some_exotic_provider_metric",
    )
    # No derived value fabricated when denominator is zero/missing.
    no_denom = metric_normalizer.normalize_provider_metrics(
        [ProviderMetric("clicks", Decimal("50"), value_type="count")], provider="mock",
    )
    record("normalizer_no_ctr_without_impressions", not any(n.metric_key == "ctr" for n in no_denom))

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"Ad Metrics {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Ad Metrics B {stamp}", status="active", plan="trial")
        db.add_all([tenant, tenant_b])
        await db.commit()

        account = await account_service.register_account(
            db, tenant.id, provider="mock",
            provider_account_id=f"mockacct-metrics-{stamp}", is_mock=True,
        )
        await db.commit()
        await import_service.import_account(db, tenant.id, account.id)
        await db.commit()

        # ---- First refresh: snapshots + values + aggregates land -----------
        run1 = await metric_ingestion_service.refresh_account_metrics(db, tenant.id, account.id)
        await db.commit()
        snap_n1 = await _count(db, TenantAdMetricSnapshot, tenant_id=tenant.id, advertising_account_id=account.id)
        val_n1 = await _count(db, TenantAdMetricValue, tenant_id=tenant.id, advertising_account_id=account.id)
        agg_n1 = await _count(db, TenantAdMetricAggregate, tenant_id=tenant.id, advertising_account_id=account.id)
        record("refresh_succeeded", run1.status == "succeeded", run1.status)
        record("snapshots_created", snap_n1 > 0 and run1.snapshots_created == snap_n1, f"{snap_n1}")
        record("metric_values_created", val_n1 > 0, str(val_n1))
        record("aggregates_created", agg_n1 > 0, str(agg_n1))

        # ---- Immutable snapshot + duplicate fingerprint --------------------
        run2 = await metric_ingestion_service.refresh_account_metrics(db, tenant.id, account.id)
        await db.commit()
        snap_n2 = await _count(db, TenantAdMetricSnapshot, tenant_id=tenant.id, advertising_account_id=account.id)
        record("refresh_idempotent_no_new_snapshots", run2.snapshots_created == 0, f"created={run2.snapshots_created}")
        record("snapshot_count_stable", snap_n2 == snap_n1, f"{snap_n2} vs {snap_n1}")

        # Every (entity_type, entity_id, fingerprint) is unique — no duplicates.
        dup_rows = (
            await db.execute(
                select(
                    TenantAdMetricSnapshot.entity_type,
                    TenantAdMetricSnapshot.entity_id,
                    TenantAdMetricSnapshot.snapshot_fingerprint,
                    func.count().label("n"),
                )
                .where(TenantAdMetricSnapshot.tenant_id == tenant.id)
                .group_by(
                    TenantAdMetricSnapshot.entity_type,
                    TenantAdMetricSnapshot.entity_id,
                    TenantAdMetricSnapshot.snapshot_fingerprint,
                )
                .having(func.count() > 1)
            )
        ).all()
        record("no_duplicate_fingerprints", not dup_rows, str(len(dup_rows)))

        # ---- Provider-native vs normalized vs derived (persisted) ----------
        persisted_statuses = set(
            (
                await db.execute(
                    select(TenantAdMetricValue.normalization_status)
                    .where(TenantAdMetricValue.tenant_id == tenant.id)
                    .distinct()
                )
            ).scalars().all()
        )
        record("persisted_has_normalized", "normalized" in persisted_statuses, str(sorted(persisted_statuses)))
        record("persisted_has_derived", "derived" in persisted_statuses)

        spend_vals = list(
            (
                await db.execute(
                    select(TenantAdMetricValue).where(
                        TenantAdMetricValue.tenant_id == tenant.id,
                        TenantAdMetricValue.metric_key == "spend_minor",
                    )
                )
            ).scalars().all()
        )
        record("spend_value_type_currency_minor",
               bool(spend_vals) and all(v.value_type == "currency_minor" for v in spend_vals))
        record("spend_has_currency",
               bool(spend_vals) and all(v.currency in ("USD", "CNY") for v in spend_vals))
        record("spend_minor_units_integral",
               bool(spend_vals) and all(v.metric_value == v.metric_value.to_integral_value() for v in spend_vals))

        # Normalized rows preserve their provider key; derived rows carry none.
        norm_rows = list(
            (
                await db.execute(
                    select(TenantAdMetricValue).where(
                        TenantAdMetricValue.tenant_id == tenant.id,
                        TenantAdMetricValue.normalization_status == "normalized",
                    )
                )
            ).scalars().all()
        )
        record("normalized_preserves_provider_key",
               bool(norm_rows) and all(v.provider_metric_key for v in norm_rows))
        derived_rows = list(
            (
                await db.execute(
                    select(TenantAdMetricValue).where(
                        TenantAdMetricValue.tenant_id == tenant.id,
                        TenantAdMetricValue.normalization_status == "derived",
                    )
                )
            ).scalars().all()
        )
        record("derived_has_no_provider_key",
               bool(derived_rows) and all(v.provider_metric_key is None for v in derived_rows))

        # ---- Tenant isolation ----------------------------------------------
        snap_b = await _count(db, TenantAdMetricSnapshot, tenant_id=tenant_b.id)
        val_b = await _count(db, TenantAdMetricValue, tenant_id=tenant_b.id)
        agg_b = await _count(db, TenantAdMetricAggregate, tenant_id=tenant_b.id)
        record("tenant_isolation_snapshots", snap_b == 0, str(snap_b))
        record("tenant_isolation_values", val_b == 0, str(val_b))
        record("tenant_isolation_aggregates", agg_b == 0, str(agg_b))

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
