"""Verify Advertising structural import (read-only mirror + immutable history).

Covers: importing the full campaign/ad-group/ad/creative tree from the mock
provider, idempotent re-import, mirror updates on change, append-only immutable
entity history, and partial-import accounting (a single failed entity never
fails the whole run).

Run from backend/:  python scripts/verify_advertising_import.py
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
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
        TenantAd,
        TenantAdCampaign,
        TenantAdCreative,
        TenantAdEntityHistory,
        TenantAdGroup,
    )
    from app.models.tenant import Tenant
    from app.services.advertising_intelligence import (
        account_service,
        identity_registry,
        import_service,
        providers as ad_providers,
    )
    from app.services.advertising_intelligence.providers.base import (
        AdvertisingProviderAdapter,
    )
    from app.services.advertising_intelligence.schemas import (
        AdvertisingCapabilities,
        ProviderAccount,
        ProviderCampaign,
        ProviderHealth,
        StructureFetchResponse,
        InsightsFetchResponse,
    )
    from app.services.advertising_platform.interfaces import utcnow

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

    async def _count(db, model, tenant_id, account_id) -> int:
        return int(
            (
                await db.execute(
                    select(func.count()).select_from(model).where(
                        model.tenant_id == tenant_id,
                        model.advertising_account_id == account_id,
                    )
                )
            ).scalar_one()
            or 0
        )

    # ---- Partial-import adapter: one valid campaign + one that raises -----
    class _PartialAdapter(AdvertisingProviderAdapter):
        provider = "mockpartial"

        def capabilities(self, *, connection_status: str) -> AdvertisingCapabilities:
            return AdvertisingCapabilities(
                provider=self.provider, capability_status="mock_only",
                supports_structure_import=True, supports_insights=True,
                supports_conversions=False, supports_breakdowns=False,
            )

        async def health_check(self, *, connection_status: str) -> ProviderHealth:
            return ProviderHealth(
                provider=self.provider, status="ok", connection_status=connection_status,
                capability_status="mock_only", checked_at=utcnow(),
            )

        async def fetch_structure(self, request) -> StructureFetchResponse:
            good = ProviderCampaign(
                provider_campaign_id=f"{request.provider_account_id}-ok",
                name="Valid", effective_status="active", config_status="active",
            )
            bad = ProviderCampaign(
                provider_campaign_id=f"{request.provider_account_id}-bad",
                name="Bad",
            )
            # A non-Money budget makes identity_registry raise in Python *before*
            # any DB write, isolating the failure without poisoning the txn.
            bad.daily_budget = object()  # type: ignore[assignment]
            return StructureFetchResponse(
                account=ProviderAccount(provider_account_id=request.provider_account_id, currency="USD"),
                campaigns=[good, bad], status="ok", provider_request_count=1,
            )

        async def fetch_insights(self, request) -> InsightsFetchResponse:
            return InsightsFetchResponse(results=[], status="ok")

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"Ad Import {stamp}", status="active", plan="trial")
        db.add(tenant)
        await db.commit()

        account = await account_service.register_account(
            db, tenant.id, provider="mock",
            provider_account_id=f"mockacct-import-{stamp}", is_mock=True,
        )
        await db.commit()

        # ---- First import: full tree ------------------------------------
        run1 = await import_service.import_account(db, tenant.id, account.id)
        await db.commit()
        camp_n = await _count(db, TenantAdCampaign, tenant.id, account.id)
        group_n = await _count(db, TenantAdGroup, tenant.id, account.id)
        ad_n = await _count(db, TenantAd, tenant.id, account.id)
        cre_n = await _count(db, TenantAdCreative, tenant.id, account.id)
        record("import_status_succeeded", run1.status == "succeeded", run1.status)
        record("import_campaigns", camp_n >= 2, str(camp_n))
        record("import_ad_groups", group_n >= 1, str(group_n))
        record("import_ads", ad_n >= 1, str(ad_n))
        record("import_creatives", cre_n >= 1, str(cre_n))
        record("import_created_count", run1.entities_created == camp_n + group_n + ad_n + cre_n,
               f"created={run1.entities_created}")
        record("import_no_failures", run1.entities_failed == 0)

        hist_after_create = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantAdEntityHistory).where(
                        TenantAdEntityHistory.tenant_id == tenant.id,
                        TenantAdEntityHistory.advertising_account_id == account.id,
                    )
                )
            ).scalar_one()
        )
        record("history_created_rows", hist_after_create == run1.entities_created, str(hist_after_create))

        # ---- Idempotent re-import: nothing changes ----------------------
        run2 = await import_service.import_account(db, tenant.id, account.id)
        await db.commit()
        record("reimport_no_new_entities", run2.entities_created == 0, f"created={run2.entities_created}")
        record("reimport_all_unchanged",
               run2.entities_unchanged == camp_n + group_n + ad_n + cre_n,
               f"unchanged={run2.entities_unchanged}")
        camp_n2 = await _count(db, TenantAdCampaign, tenant.id, account.id)
        record("reimport_stable_campaign_count", camp_n2 == camp_n)
        hist_after_reimport = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantAdEntityHistory).where(
                        TenantAdEntityHistory.tenant_id == tenant.id,
                        TenantAdEntityHistory.advertising_account_id == account.id,
                    )
                )
            ).scalar_one()
        )
        record("history_immutable_no_growth_on_unchanged", hist_after_reimport == hist_after_create,
               f"{hist_after_reimport} vs {hist_after_create}")

        # ---- Mirror update + immutable history via identity_registry ----
        observed = utcnow()
        camp = ProviderCampaign(
            provider_campaign_id=f"idreg-{stamp}", name="IDReg Campaign",
            effective_status="active", config_status="active",
        )
        row_c, change_c = await identity_registry.upsert_campaign(
            db, tenant_id=tenant.id, account_id=account.id, provider="mock",
            campaign=camp, observed_at=observed, source="mock",
        )
        await db.flush()
        record("idreg_created", change_c == "created")

        camp_changed = ProviderCampaign(
            provider_campaign_id=f"idreg-{stamp}", name="IDReg Campaign",
            effective_status="paused", config_status="active",
        )
        row_c2, change_c2 = await identity_registry.upsert_campaign(
            db, tenant_id=tenant.id, account_id=account.id, provider="mock",
            campaign=camp_changed, observed_at=utcnow(), source="mock",
        )
        await db.flush()
        record("idreg_updated", change_c2 == "updated")
        record("mirror_reflects_update", row_c2.effective_status == "paused" and row_c2.id == row_c.id)

        _, change_c3 = await identity_registry.upsert_campaign(
            db, tenant_id=tenant.id, account_id=account.id, provider="mock",
            campaign=camp_changed, observed_at=utcnow(), source="mock",
        )
        await db.flush()
        record("idreg_unchanged_when_identical", change_c3 == "unchanged")

        hist_rows = list(
            (
                await db.execute(
                    select(TenantAdEntityHistory).where(
                        TenantAdEntityHistory.tenant_id == tenant.id,
                        TenantAdEntityHistory.entity_id == row_c.id,
                    ).order_by(TenantAdEntityHistory.created_at)
                )
            ).scalars().all()
        )
        change_types = [h.change_type for h in hist_rows]
        record("history_append_only_two_rows", change_types == ["created", "updated"], str(change_types))
        updated_row = next((h for h in hist_rows if h.change_type == "updated"), None)
        record(
            "history_records_field_change",
            updated_row is not None
            and bool(updated_row.field_changes)
            and "effective_status" in (updated_row.field_changes or {}),
            str(updated_row.field_changes if updated_row else None),
        )
        await db.commit()

    # ---- Partial import (separate session/tenant) -----------------------
    ad_providers._instances["mockpartial"] = _PartialAdapter()
    async with AsyncSessionLocal() as db:
        tenant2 = Tenant(id=uuid4(), company_name=f"Ad Import Partial {stamp}", status="active", plan="trial")
        db.add(tenant2)
        await db.commit()
        acct2 = await account_service.register_account(
            db, tenant2.id, provider="mockpartial",
            provider_account_id=f"partial-{stamp}", is_mock=True,
        )
        await db.commit()
        run_p = await import_service.import_account(db, tenant2.id, acct2.id)
        await db.commit()
        record("partial_status", run_p.status == "partial", run_p.status)
        record("partial_created_one", run_p.entities_created == 1, f"created={run_p.entities_created}")
        record("partial_failed_one", run_p.entities_failed == 1, f"failed={run_p.entities_failed}")
        good_n = await _count(db, TenantAdCampaign, tenant2.id, acct2.id)
        record("partial_valid_entity_persisted", good_n == 1, str(good_n))

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
