"""Verify Executive CRM Pipeline Phase 3 — dashboard KPIs, forecast, manager metrics."""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run() -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_dev_schema_patches
    from app.models.publishing_account import PublishingAccount
    from app.models.sales_crm import SalesCustomer, SalesDeal
    from app.models.tenant import Tenant, TenantUser
    from app.services.crm_pipeline_dashboard_service import (
        CrmPipelineDashboardService,
        _month_key,
        _weighted_revenue,
    )

    failures: list[str] = []
    stamp = int(datetime.now(timezone.utc).timestamp())
    now = datetime.now(timezone.utc)

    await ensure_dev_schema_patches()
    print("OK schema patches applied")

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(Tenant).limit(2))).scalars().all()
        if len(tenants) < 2:
            print("FAIL need at least 2 tenants in database")
            return 1
        tenant_a, tenant_b = tenants[0], tenants[1]
        print(f"OK tenants {tenant_a.id} / {tenant_b.id}")

        owner_a = (await db.execute(
            select(TenantUser).where(TenantUser.tenant_id == tenant_a.id).limit(1)
        )).scalar_one_or_none()
        owner_id = owner_a.id if owner_a else None

        customer_a = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            name=f"Dashboard KPI A {stamp}",
            company="KPI Co A",
        )
        customer_b = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            name=f"Dashboard KPI B {stamp}",
            company="KPI Co B",
        )
        db.add_all([customer_a, customer_b])
        await db.flush()

        baseline_a = await CrmPipelineDashboardService.dashboard(db, tenant_a.id)
        baseline_b = await CrmPipelineDashboardService.dashboard(db, tenant_b.id)

        meta_account_a = PublishingAccount(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            platform="facebook",
            account_name=f"Verify Meta A {stamp}",
            account_id=f"fb-verify-{stamp}",
            status="connected",
        )
        meta_account_b = PublishingAccount(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            platform="facebook",
            account_name=f"Verify Meta B {stamp}",
            account_id=f"fb-verify-b-{stamp}",
            status="connected",
        )
        db.add_all([meta_account_a, meta_account_b])
        await db.flush()

        customer_a.primary_publishing_account_id = meta_account_a.id
        await db.flush()

        created_open = now - timedelta(days=30)
        stale_updated = now - timedelta(days=20)
        closed_created = now - timedelta(days=40)
        closed_at = now - timedelta(days=10)

        deals_a = [
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Open Deal 1 {stamp}",
                value=Decimal("10000"),
                stage="negotiation",
                probability=55,
                owner_id=owner_id,
                created_at=created_open,
                updated_at=now,
                expected_close_date=now + timedelta(days=30),
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Open Deal 2 {stamp}",
                value=Decimal("5000"),
                stage="proposal_sent",
                probability=40,
                owner_id=owner_id,
                created_at=created_open,
                updated_at=now,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Stale Deal {stamp}",
                value=Decimal("2000"),
                stage="lead",
                probability=5,
                created_at=created_open,
                updated_at=stale_updated,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Won Deal {stamp}",
                value=Decimal("8000"),
                stage="closed_won",
                probability=100,
                owner_id=owner_id,
                created_at=closed_created,
                updated_at=closed_at,
                closed_at=closed_at,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Lost Deal {stamp}",
                value=Decimal("3000"),
                stage="closed_lost",
                probability=0,
                created_at=closed_created,
                updated_at=closed_at,
                closed_at=closed_at,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Client Active {stamp}",
                value=Decimal("12000"),
                stage="client_active",
                probability=85,
                created_at=created_open,
                updated_at=now,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Publishing Active {stamp}",
                value=Decimal("15000"),
                stage="publishing_active",
                probability=90,
                created_at=created_open,
                updated_at=now,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Null Value Deal {stamp}",
                value=None,
                stage="qualified",
                probability=15,
                created_at=created_open,
                updated_at=now,
            ),
        ]
        deal_b = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            customer_id=customer_b.id,
            title=f"Tenant B Pipeline {stamp}",
            value=Decimal("999999"),
            stage="negotiation",
            probability=90,
            created_at=created_open,
            updated_at=now,
        )
        db.add_all([*deals_a, deal_b])
        await db.commit()
        print("OK dashboard fixture data created")

        dash_a = await CrmPipelineDashboardService.dashboard(db, tenant_a.id)
        dash_b = await CrmPipelineDashboardService.dashboard(db, tenant_b.id)

        delta_pipeline = dash_a.pipeline_value - baseline_a.pipeline_value
        delta_weighted = dash_a.weighted_expected_revenue - baseline_a.weighted_expected_revenue
        delta_open = dash_a.open_deals_count - baseline_a.open_deals_count
        delta_stale = dash_a.stale_deals_count - baseline_a.stale_deals_count
        delta_won = dash_a.deals_won_count - baseline_a.deals_won_count
        delta_lost = dash_a.deals_lost_count - baseline_a.deals_lost_count
        delta_clients_active = dash_a.clients_active_count - baseline_a.clients_active_count
        delta_clients_publishing = dash_a.clients_publishing_count - baseline_a.clients_publishing_count
        delta_clients_meta = dash_a.clients_connected_to_meta - baseline_a.clients_connected_to_meta
        delta_meta_accounts = (
            dash_a.publishing_health.meta_connected_count
            - baseline_a.publishing_health.meta_connected_count
        )

        expected_pipeline = Decimal("44000")
        if delta_pipeline != expected_pipeline:
            failures.append(
                f"pipeline_value delta expected {expected_pipeline} got {delta_pipeline}",
            )
        else:
            print(f"OK pipeline_value delta={delta_pipeline}")

        expected_weighted = Decimal("31300")
        if delta_weighted != expected_weighted:
            failures.append(
                f"weighted_expected_revenue delta expected {expected_weighted} got {delta_weighted}",
            )
        else:
            print(f"OK weighted_expected_revenue delta={delta_weighted}")

        if delta_won != 1:
            failures.append(f"deals_won delta expected 1 got {delta_won}")
        if delta_lost != 1:
            failures.append(f"deals_lost delta expected 1 got {delta_lost}")
        if delta_won == 1 and delta_lost == 1:
            print("OK win_rate contribution (1 won, 1 lost in fixture)")

        closed_fixture = [d for d in deals_a if d.stage in ("closed_won", "closed_lost")]
        fixture_avg = CrmPipelineDashboardService._average_deal_time_days(closed_fixture)
        if fixture_avg != 30.0:
            failures.append(f"fixture average_deal_time_days expected 30.0 got {fixture_avg}")
        else:
            print(f"OK fixture average_deal_time_days={fixture_avg}")

        if delta_open != 6:
            failures.append(f"open_deals_count delta expected 6 got {delta_open}")
        else:
            print("OK open_deals_count delta=6")

        if delta_stale != 1:
            failures.append(f"stale_deals_count delta expected 1 got {delta_stale}")
        else:
            print("OK stale_deals_count delta=1")

        if delta_clients_active != 1:
            failures.append(f"clients_active_count delta expected 1 got {delta_clients_active}")
        else:
            print("OK clients_active_count delta=1")

        if delta_clients_publishing != 1:
            failures.append(
                f"clients_publishing_count delta expected 1 got {delta_clients_publishing}",
            )
        else:
            print("OK clients_publishing_count delta=1")

        if delta_clients_meta != 1:
            failures.append(
                f"clients_connected_to_meta delta expected 1 got {delta_clients_meta}",
            )
        else:
            print("OK clients_connected_to_meta delta=1")

        delta_b_pipeline = dash_b.pipeline_value - baseline_b.pipeline_value
        if delta_b_pipeline != Decimal("999999"):
            failures.append(f"tenant B pipeline delta expected 999999 got {delta_b_pipeline}")
        else:
            print("OK tenant B pipeline isolation delta")

        if dash_b.clients_connected_to_meta != baseline_b.clients_connected_to_meta:
            failures.append(
                f"tenant B meta clients leaked: {dash_b.clients_connected_to_meta}",
            )
        else:
            print("OK tenant B meta client isolation")

        if delta_meta_accounts < 1:
            failures.append("tenant A meta_connected_count delta should be >= 1")
        else:
            print(f"OK meta_connected_count delta={delta_meta_accounts}")

        forecast = await CrmPipelineDashboardService.revenue_forecast(db, tenant_a.id)
        if not forecast.rows:
            failures.append("revenue forecast returned no rows")
        else:
            open_fixture = [d for d in deals_a if d.stage not in ("closed_won", "closed_lost")]
            fixture_weighted = sum((_weighted_revenue(d) for d in open_fixture), Decimal("0"))
            month_keys = {_month_key(d.expected_close_date or d.created_at) for d in open_fixture}
            fixture_rows = [r for r in forecast.rows if r.month in month_keys]
            fixture_total = sum((r.weighted_revenue for r in fixture_rows), Decimal("0"))
            if fixture_total < fixture_weighted:
                failures.append(
                    f"forecast fixture weighted expected >= {fixture_weighted} got {fixture_total}",
                )
            elif forecast.total_weighted_revenue < dash_a.weighted_expected_revenue:
                failures.append("forecast total_weighted_revenue below dashboard weighted revenue")
            else:
                print(f"OK revenue_forecast rows={len(forecast.rows)}")

        managers = await CrmPipelineDashboardService.manager_performance(db, tenant_a.id)
        if owner_id:
            owner_rows = [m for m in managers.managers if m.owner_id == owner_id]
            if len(owner_rows) != 1:
                failures.append("manager performance missing owner row")
            else:
                row = owner_rows[0]
                owner_pipeline = Decimal("10000") + Decimal("5000")
                if row.pipeline_value < owner_pipeline:
                    failures.append(
                        f"manager pipeline_value expected >= {owner_pipeline} got {row.pipeline_value}",
                    )
                elif row.deals_won < 1:
                    failures.append("manager won count too low")
                else:
                    print("OK manager performance metrics")
        else:
            print("SKIP manager performance (no tenant user on tenant A)")

        if managers.unassigned and managers.unassigned.open_deals >= 4:
            print("OK unassigned manager bucket")
        elif managers.unassigned:
            failures.append("unassigned bucket under-counted open deals")
        else:
            failures.append("unassigned bucket missing")

    if failures:
        print("\nFAILURES:")
        for item in failures:
            print(" -", item)
        return 1

    print("\nALL CRM PIPELINE DASHBOARD CHECKS PASSED")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
