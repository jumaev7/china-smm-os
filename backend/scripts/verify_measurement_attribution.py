"""DB verification for measurement attribution methods.

Run from backend/:  python scripts/verify_measurement_attribution.py
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
    from sqlalchemy import select

    from app.core.database import (
        AsyncSessionLocal,
        ensure_campaign_planner_schema,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.measurement import TenantAttributionRecord, TenantExternalPublication
    from app.models.publish_attempt import PublishAttempt
    from app.models.publishing_account import PublishingAccount
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.campaign_planner.calendar_service import CalendarService
    from app.services.campaign_planner.campaign_service import CampaignService
    from app.services.campaign_planner.planning_service import PlanningService
    from app.services.campaign_planner.slot_assignment import SlotAssignmentService
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.measurement.attribution_service import (
        create_manual_link,
        list_attribution_for_publication,
        record_publish_attribution,
        to_result,
    )
    from app.services.measurement.confidence_engine import confidence_for_method
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
        tenant_a = Tenant(id=uuid4(), company_name=f"Meas Attr A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas Attr B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"meas-attr-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(
            id=uuid4(), tenant_id=tenant_a.id, company_name=f"Attr Client {stamp}",
            business_category="manufacturing", status="active",
        )
        content_slot = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["facebook"], status="draft",
            caption_long_en="Slot attribution content.",
        )
        content_plain = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["facebook"], status="draft",
            caption_long_en="Unattributed content.",
        )
        content_campaign = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["facebook"], status="draft",
            caption_long_en="Campaign-only attribution content.",
        )
        account = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="facebook",
            account_name=f"Attr Mock {stamp}", account_id=f"attr-{stamp}", status="mock",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, account])
        await db.commit()
        db.add_all([content_slot, content_plain, content_campaign])
        await db.commit()

        campaign = await CampaignService.create_campaign(
            db, tenant_a.id,
            {
                "name": f"Attr Campaign {stamp}",
                "timezone": "UTC",
                "primary_locale": "en",
                "locales": ["en"],
                "platforms": ["facebook"],
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 14),
                "cadence": {"posts_per_week": 3},
            },
            created_by=user_a.id,
        )
        campaign2 = await CampaignService.create_campaign(
            db, tenant_a.id,
            {
                "name": f"Attr Campaign 2 {stamp}",
                "timezone": "UTC",
                "primary_locale": "en",
                "locales": ["en"],
                "platforms": ["facebook"],
                "start_date": date(2026, 8, 1),
                "end_date": date(2026, 8, 14),
                "cadence": {"posts_per_week": 2},
            },
            created_by=user_a.id,
        )
        await db.commit()

        plan = await PlanningService.generate(db, tenant_a.id, campaign.id, created_by=user_a.id)
        await db.commit()
        await PlanningService.publish(db, tenant_a.id, campaign.id, plan.id, published_by=user_a.id)
        await db.commit()
        slots = await CalendarService.list_slots(db, tenant_a.id, plan.id)
        slot = next(s for s in slots if s.status == "unassigned")
        await SlotAssignmentService.assign(
            db, tenant_a.id, campaign.id, plan.id, slot.id, content_slot.id,
            allow_warnings=True, run_publish_safety=False, assigned_by=user_a.id,
        )
        await db.commit()

        async def _reg(content, post_id: str) -> TenantExternalPublication:
            attempt = PublishAttempt(
                id=uuid4(), content_id=content.id, platform="facebook",
                account_id=account.id, status="success",
            )
            db.add(attempt)
            await db.flush()
            pub = await register_from_publish_attempt(
                db,
                tenant_id=tenant_a.id,
                content=content,
                attempt=attempt,
                result={
                    "success": True,
                    "platform": "facebook",
                    "platform_post_id": post_id,
                    "post_url": f"https://example.com/posts/{post_id}",
                    "mock": True,
                },
                account=account,
            )
            await db.flush()
            assert pub is not None
            return pub

        # direct_slot_assignment
        pub_slot = await _reg(content_slot, f"attr-slot-{stamp}")
        await db.commit()
        attrs_slot = await list_attribution_for_publication(db, tenant_a.id, pub_slot.id)
        active_slot = [a for a in attrs_slot if a.status == "active"]
        record(
            "direct_slot_assignment",
            len(active_slot) == 1 and active_slot[0].attribution_method == "direct_slot_assignment",
            active_slot[0].attribution_method if active_slot else "none",
        )
        record(
            "confidence_slot_exposed",
            active_slot and active_slot[0].confidence == confidence_for_method("direct_slot_assignment"),
            str(active_slot[0].confidence if active_slot else None),
        )

        # unattributed
        pub_plain = await _reg(content_plain, f"attr-plain-{stamp}")
        await db.commit()
        attrs_plain = await list_attribution_for_publication(db, tenant_a.id, pub_plain.id)
        active_plain = [a for a in attrs_plain if a.status == "active"]
        record(
            "unattributed",
            len(active_plain) == 1 and active_plain[0].attribution_method == "unattributed",
        )
        record(
            "confidence_unattributed_zero",
            active_plain and active_plain[0].confidence == Decimal("0.000"),
        )

        # direct_campaign_publication (campaign_id, no slot)
        pub_camp = await _reg(content_campaign, f"attr-camp-{stamp}")
        pub_camp.campaign_id = campaign.id
        pub_camp.campaign_slot_id = None
        pub_camp.assignment_id = None
        # Replace auto unattributed with campaign attribution
        for row in await list_attribution_for_publication(db, tenant_a.id, pub_camp.id):
            if row.status == "active":
                row.status = "superseded"
        attr_camp = await record_publish_attribution(db, publication=pub_camp)
        await db.commit()
        record(
            "direct_campaign_publication",
            attr_camp.attribution_method == "direct_campaign_publication",
            attr_camp.attribution_method,
        )
        record(
            "confidence_campaign_exposed",
            attr_camp.confidence == confidence_for_method("direct_campaign_publication"),
        )

        # manual_link supersedes — no duplicate full attribution
        manual = await create_manual_link(
            db, tenant_a.id,
            publication_id=pub_camp.id,
            campaign_id=campaign2.id,
            confidence_override=Decimal("0.65"),
            evidence={"note": "operator_link"},
        )
        await db.commit()
        record("manual_link", manual.attribution_method == "manual_link")
        record("manual_confidence_override", manual.confidence == Decimal("0.65"))

        all_camp = await list_attribution_for_publication(db, tenant_a.id, pub_camp.id)
        active_after = [a for a in all_camp if a.status == "active" and a.target_type == "campaign"]
        superseded = [a for a in all_camp if a.status == "superseded"]
        record("manual_supersedes_no_duplicate_active", len(active_after) == 1 and active_after[0].id == manual.id)
        record("prior_attribution_superseded", len(superseded) >= 1, str(len(superseded)))

        result = to_result(manual)
        record("to_result_exposes_confidence", result.confidence == Decimal("0.65"))

        # Cross-tenant rejection
        iso = False
        try:
            await create_manual_link(
                db, tenant_b.id,
                publication_id=pub_camp.id,
                campaign_id=campaign.id,
            )
        except Exception:
            iso = True
        record("cross_tenant_manual_link_rejected", iso)

        # Ensure tenant_b cannot list tenant_a attribution
        foreign = await list_attribution_for_publication(db, tenant_b.id, pub_camp.id)
        record("cross_tenant_list_empty", foreign == [])

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
