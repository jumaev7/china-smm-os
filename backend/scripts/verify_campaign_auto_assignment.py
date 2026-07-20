"""Verify deterministic auto-assignment.

Run from backend/:  python scripts/verify_campaign_auto_assignment.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import asyncio
    return asyncio.run(_run())


async def _run() -> int:
    from app.core.database import AsyncSessionLocal, ensure_campaign_planner_schema
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.campaign_planner.calendar_service import CalendarService
    from app.services.campaign_planner.campaign_service import CampaignService
    from app.services.campaign_planner.planning_service import PlanningService
    from app.services.campaign_planner.slot_assignment import SlotAssignmentService

    await ensure_campaign_planner_schema()
    stamp = int(datetime.now(timezone.utc).timestamp())
    failures = []

    def record(c, ok, d=""):
        print(("OK" if ok else "FAIL") + f" {c}" + (f" — {d}" if d else ""))
        if not ok:
            failures.append(c)

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"CP Auto {stamp}", status="active", plan="trial")
        db.add(tenant)
        await db.flush()
        user = TenantUser(id=uuid4(), tenant_id=tenant.id, email=f"cpa-{stamp}@example.com",
                          password_hash=hash_password("test1234"), role="owner", status="active")
        client = Client(id=uuid4(), tenant_id=tenant.id, company_name=f"C {stamp}", business_category="mfg", status="active")
        db.add_all([user, client])
        await db.commit()
        items = []
        for i in range(5):
            items.append(ContentItem(
                id=uuid4(), client_id=client.id, platforms=["telegram"], status="draft",
                caption_long_en=f"Content piece {i} for export buyers. Contact us today.",
            ))
        db.add_all(items)
        await db.commit()

        camp = await CampaignService.create_campaign(db, tenant.id, {
            "name": "Auto", "platforms": ["telegram"], "locales": ["en"],
            "start_date": date(2026, 7, 1), "end_date": date(2026, 7, 7),
            "cadence": {"posts_per_week": 3},
        }, created_by=user.id)
        await db.commit()
        plan = await PlanningService.generate(db, tenant.id, camp.id, created_by=user.id)
        await db.commit()
        r1 = await SlotAssignmentService.auto_assign(
            db, tenant.id, camp.id, plan.id, allow_warnings=True, run_publish_safety=False, assigned_by=user.id,
        )
        await db.commit()
        record("auto_assign_some", r1["assigned"] >= 1, str(r1["assigned"]))

        # Second run should not double-assign same content into remaining if already used
        r2 = await SlotAssignmentService.auto_assign(
            db, tenant.id, camp.id, plan.id, allow_warnings=True, run_publish_safety=False, assigned_by=user.id,
        )
        await db.commit()
        slots = await CalendarService.list_slots(db, tenant.id, plan.id)
        assigned = [s for s in slots if s.status != "unassigned"]
        record("slots_assigned", len(assigned) >= r1["assigned"])
        record("idempotent_second_pass", r2["assigned"] == 0 or r2["assigned"] <= r1["skipped"])

        # content still draft
        from sqlalchemy import select
        refreshed = (await db.execute(select(ContentItem).where(ContentItem.id == items[0].id))).scalar_one()
        record("no_publish_side_effect", refreshed.status == "draft" and refreshed.scheduled_for is None)

    print()
    if failures:
        print(f"FAILED {len(failures)}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
