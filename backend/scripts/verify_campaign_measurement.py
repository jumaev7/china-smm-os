"""DB verification for campaign measurement KPIs.

Run from backend/:  python scripts/verify_campaign_measurement.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
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
    from app.core.database import (
        AsyncSessionLocal,
        ensure_campaign_planner_schema,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.measurement import (
        CALCULATION_VERSION,
        TenantExternalPublication,
        TenantPublicationMetricAggregate,
    )
    from app.models.publish_attempt import PublishAttempt
    from app.models.publishing_account import PublishingAccount
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.campaign_planner.campaign_service import CampaignService
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.measurement.campaign_measurement import evaluate_campaign_kpis
    from app.services.measurement.publication_registry import register_from_publish_attempt

    await ensure_platform_event_bus_schema()
    await ensure_campaign_planner_schema()
    await ensure_measurement_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Meas KPI A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas KPI B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"meas-kpi-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(
            id=uuid4(), tenant_id=tenant_a.id, company_name=f"KPI Client {stamp}",
            business_category="manufacturing", status="active",
        )
        content_a = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["mock"], status="draft",
            caption_long_en="Campaign KPI verification content.",
        )
        account = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="mock",
            account_name=f"KPI Mock {stamp}", account_id=f"kpi-{stamp}", status="mock",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, account])
        await db.commit()
        db.add(content_a)
        await db.commit()

        campaign = await CampaignService.create_campaign(
            db, tenant_a.id,
            {
                "name": f"KPI Campaign {stamp}",
                "timezone": "UTC",
                "primary_locale": "en",
                "locales": ["en"],
                "platforms": ["facebook"],
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 31),
                "cadence": {"posts_per_week": 2},
            },
            created_by=user_a.id,
        )
        await db.commit()
        await CampaignService.add_kpi(
            db, tenant_a.id, campaign.id,
            {"name": "Likes target", "metric_key": "likes", "target_value": 100, "comparator": ">="},
        )
        await CampaignService.add_kpi(
            db, tenant_a.id, campaign.id,
            {"name": "Lead count", "metric_key": "leads", "target_value": 10, "comparator": ">="},
        )
        await CampaignService.add_kpi(
            db, tenant_a.id, campaign.id,
            {"name": "Sales", "metric_key": "sales", "target_value": 5, "comparator": ">="},
        )
        await db.commit()

        # no_data: campaign with KPIs but no attributed publications
        results_empty = await evaluate_campaign_kpis(db, tenant_a.id, campaign.id)
        await db.commit()
        by_key = {r.metric_key: r for r in results_empty}
        record("lead_not_measurable", by_key.get("leads") is not None and by_key["leads"].status == "not_measurable")
        record("sales_not_measurable", by_key.get("sales") is not None and by_key["sales"].status == "not_measurable")
        record(
            "lead_not_inferred_from_engagement",
            by_key["leads"].current_value is None
            and (by_key["leads"].evidence or {}).get("engagement_inference_forbidden") is True,
        )
        record("likes_no_data", by_key.get("likes") is not None and by_key["likes"].status == "no_data")

        # Attach publication + aggregate for likes
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
                "platform_post_id": f"kpi-post-{stamp}",
                "post_url": f"https://example.com/posts/kpi-{stamp}",
                "mock": True,
            },
            account=account,
        )
        await db.commit()
        # Freeze campaign linkage for attribution rollup
        pub.campaign_id = campaign.id
        pub.freshness_status = "fresh"
        pub.last_metric_at = datetime.now(timezone.utc)
        db.add(
            TenantPublicationMetricAggregate(
                id=uuid4(),
                tenant_id=tenant_a.id,
                external_publication_id=pub.id,
                window_key="lifetime",
                metric_key="likes",
                metric_value=Decimal(150),
                calculation_method="latest_cumulative",
                calculation_version=CALCULATION_VERSION,
                freshness_status="fresh",
                confidence=Decimal("1.000"),
                source_snapshot_ids=[],
                calculated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        results = await evaluate_campaign_kpis(db, tenant_a.id, campaign.id)
        await db.commit()
        by_key = {r.metric_key: r for r in results}
        record(
            "likes_target_reached",
            by_key.get("likes") is not None and by_key["likes"].status in {"target_reached", "target_exceeded"},
            by_key["likes"].status if by_key.get("likes") else "missing",
        )
        record(
            "likes_measurable",
            by_key["likes"].status != "not_measurable" and by_key["likes"].current_value == Decimal(150),
        )
        record(
            "lead_still_not_measurable_with_engagement",
            by_key["leads"].status == "not_measurable",
        )

        # data_stale when all pubs stale/unavailable
        pub.freshness_status = "stale"
        await db.commit()
        stale_results = await evaluate_campaign_kpis(db, tenant_a.id, campaign.id)
        await db.commit()
        likes_stale = next(r for r in stale_results if r.metric_key == "likes")
        record("likes_data_stale", likes_stale.status == "data_stale", likes_stale.status)

        # Cross-tenant rejection
        iso = False
        try:
            await evaluate_campaign_kpis(db, tenant_b.id, campaign.id)
        except Exception:
            iso = True
        record("cross_tenant_campaign_kpi_rejected", iso)

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
