"""DB verification for external publication registration.

Run from backend/:  python scripts/verify_publication_registry.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
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
        ensure_campaign_planner_schema,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.measurement import TenantExternalPublication
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
        tenant_a = Tenant(id=uuid4(), company_name=f"Meas Reg A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Meas Reg B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"meas-reg-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(
            id=uuid4(), tenant_id=tenant_a.id, company_name=f"Meas Client A {stamp}",
            business_category="manufacturing", status="active",
        )
        content_a = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["facebook"], status="draft",
            caption_long_en="Export-ready steel components for global buyers. Contact us for a quote.",
            hashtags="#export #steel",
        )
        account_a = PublishingAccount(
            id=uuid4(), tenant_id=tenant_a.id, platform="facebook",
            account_name=f"Mock A {stamp}", account_id=f"mock-a-{stamp}", status="mock",
        )
        account_b = PublishingAccount(
            id=uuid4(), tenant_id=tenant_b.id, platform="facebook",
            account_name=f"Mock B {stamp}", account_id=f"mock-b-{stamp}", status="mock",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, account_a, account_b])
        await db.commit()
        db.add(content_a)
        await db.commit()

        attempt = PublishAttempt(
            id=uuid4(), content_id=content_a.id, platform="facebook",
            account_id=account_a.id, status="success",
        )
        db.add(attempt)
        await db.commit()

        # Successful registration
        post_id = f"mock-post-{stamp}-1"
        pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=attempt,
            result={
                "success": True,
                "platform": "facebook",
                "platform_post_id": post_id,
                "post_url": f"https://example.com/posts/{post_id}",
                "mock": True,
                "account_name": account_a.account_name,
            },
            account=account_a,
        )
        await db.commit()
        record("register_success_creates_row", pub is not None and pub.provider_publication_id == post_id)
        record("register_is_mock", pub is not None and pub.is_mock is True)
        record(
            "register_permalink_https",
            pub is not None and (pub.provider_permalink or "").startswith("https://"),
        )
        record("source_fingerprint_preserved", pub is not None and bool(pub.source_fingerprint))

        count_ok = (
            await db.execute(
                select(func.count()).select_from(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_a.id,
                    TenantExternalPublication.provider_publication_id == post_id,
                )
            )
        ).scalar_one()
        record("register_row_count_one", int(count_ok) == 1)

        # Failed publish creates none
        fail_attempt = PublishAttempt(
            id=uuid4(), content_id=content_a.id, platform="facebook",
            account_id=account_a.id, status="failed",
        )
        db.add(fail_attempt)
        await db.commit()
        before_fail = (
            await db.execute(
                select(func.count()).select_from(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_a.id,
                )
            )
        ).scalar_one()
        failed_pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=fail_attempt,
            result={
                "success": False,
                "platform": "facebook",
                "platform_post_id": f"should-not-exist-{stamp}",
                "post_url": "https://example.com/nope",
                "mock": True,
            },
            account=account_a,
        )
        await db.commit()
        after_fail = (
            await db.execute(
                select(func.count()).select_from(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_a.id,
                )
            )
        ).scalar_one()
        record("failed_publish_creates_none", failed_pub is None and int(after_fail) == int(before_fail))

        # Duplicate provider identity idempotent
        dup = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=attempt,
            result={
                "success": True,
                "platform": "facebook",
                "platform_post_id": post_id,
                "post_url": f"https://example.com/posts/{post_id}",
                "mock": True,
            },
            account=account_a,
        )
        await db.commit()
        count_dup = (
            await db.execute(
                select(func.count()).select_from(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_a.id,
                    TenantExternalPublication.provider_publication_id == post_id,
                )
            )
        ).scalar_one()
        record("duplicate_identity_idempotent", dup is not None and dup.id == pub.id and int(count_dup) == 1)

        # Wrong tenant account rejected/skipped
        wrong = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=attempt,
            result={
                "success": True,
                "platform": "facebook",
                "platform_post_id": f"wrong-tenant-{stamp}",
                "post_url": "https://example.com/wrong",
                "mock": True,
            },
            account=account_b,
        )
        await db.commit()
        record("wrong_tenant_account_skipped", wrong is None)

        # Campaign-slot linkage frozen at publish time
        campaign = await CampaignService.create_campaign(
            db, tenant_a.id,
            {
                "name": f"Meas Campaign {stamp}",
                "timezone": "UTC",
                "primary_locale": "en",
                "locales": ["en"],
                "platforms": ["facebook"],
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 7),
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
        open_slot = next(s for s in slots if s.status == "unassigned")
        assignment = await SlotAssignmentService.assign(
            db, tenant_a.id, campaign.id, plan.id, open_slot.id, content_a.id,
            allow_warnings=True, run_publish_safety=False, assigned_by=user_a.id,
        )
        await db.commit()

        linked_attempt = PublishAttempt(
            id=uuid4(), content_id=content_a.id, platform="facebook",
            account_id=account_a.id, status="success",
        )
        db.add(linked_attempt)
        await db.commit()
        linked_post = f"mock-slot-post-{stamp}"
        linked_pub = await register_from_publish_attempt(
            db,
            tenant_id=tenant_a.id,
            content=content_a,
            attempt=linked_attempt,
            result={
                "success": True,
                "platform": "facebook",
                "platform_post_id": linked_post,
                "post_url": f"https://example.com/posts/{linked_post}",
                "mock": True,
            },
            account=account_a,
        )
        await db.commit()
        record(
            "campaign_slot_frozen",
            linked_pub is not None
            and linked_pub.campaign_id == campaign.id
            and linked_pub.campaign_slot_id == open_slot.id
            and linked_pub.assignment_id == assignment.id,
            f"campaign={linked_pub.campaign_id if linked_pub else None}",
        )
        frozen_slot = linked_pub.campaign_slot_id if linked_pub else None
        frozen_fp = linked_pub.source_fingerprint if linked_pub else None

        # Reassign content elsewhere should not rewrite historical publication
        other_slots = [s for s in slots if s.id != open_slot.id and s.status == "unassigned"]
        if other_slots:
            await SlotAssignmentService.assign(
                db, tenant_a.id, campaign.id, plan.id, other_slots[0].id, content_a.id,
                allow_warnings=True, run_publish_safety=False, assigned_by=user_a.id,
            )
            await db.commit()
        refreshed = (
            await db.execute(
                select(TenantExternalPublication).where(TenantExternalPublication.id == linked_pub.id)
            )
        ).scalar_one()
        record(
            "reassignment_does_not_rewrite_pub",
            refreshed.campaign_slot_id == frozen_slot
            and refreshed.source_fingerprint == frozen_fp,
        )

        # Tenant isolation: tenant_b cannot see tenant_a pubs via list filter count
        b_count = (
            await db.execute(
                select(func.count()).select_from(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_b.id,
                )
            )
        ).scalar_one()
        record("tenant_b_no_pubs", int(b_count) == 0)

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
