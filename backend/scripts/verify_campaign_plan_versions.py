"""Verify plan version immutability after publish.

Run from backend/:  python scripts/verify_campaign_plan_versions.py
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


def _sc(exc):
    return getattr(exc, "status_code", None)


async def _run() -> int:
    from app.core.database import AsyncSessionLocal, ensure_campaign_planner_schema
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.campaign_planner.calendar_service import CalendarService
    from app.services.campaign_planner.campaign_service import CampaignService
    from app.services.campaign_planner.planning_service import PlanningService

    await ensure_campaign_planner_schema()
    stamp = int(datetime.now(timezone.utc).timestamp())
    failures = []

    def record(c, ok, d=""):
        print(("OK" if ok else "FAIL") + f" {c}" + (f" — {d}" if d else ""))
        if not ok:
            failures.append(f"{c}: {d}")

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"CP Ver {stamp}", status="active", plan="trial")
        user = TenantUser(id=uuid4(), tenant_id=tenant.id, email=f"cpv-{stamp}@example.com",
                          password_hash=hash_password("test1234"), role="owner", status="active")
        db.add_all([tenant, user])
        await db.commit()
        camp = await CampaignService.create_campaign(db, tenant.id, {
            "name": "Versions", "timezone": "UTC", "platforms": ["telegram"], "locales": ["en"],
            "start_date": date(2026, 6, 1), "end_date": date(2026, 6, 7),
            "cadence": {"posts_per_week": 2},
        }, created_by=user.id)
        await db.commit()
        p1 = await PlanningService.generate(db, tenant.id, camp.id, created_by=user.id)
        await db.commit()
        p2 = await PlanningService.clone(db, tenant.id, camp.id, p1.id, created_by=user.id)
        await db.commit()
        record("clone_draft", p2.status == "draft" and p2.parent_version_id == p1.id)
        record("clone_new_version", p2.version == p1.version + 1)

        await PlanningService.publish(db, tenant.id, camp.id, p1.id, published_by=user.id)
        await db.commit()
        blocked = False
        try:
            await CalendarService.update_slot(db, tenant.id, camp.id, p1.id,
                (await CalendarService.list_slots(db, tenant.id, p1.id))[0].id,
                {"notes": "x"})
        except Exception as e:
            blocked = _sc(e) == 409
        record("published_slot_update_409", blocked)

        await PlanningService.publish(db, tenant.id, camp.id, p2.id, published_by=user.id)
        await db.commit()
        p1_ref = await CalendarService.load_plan(db, tenant.id, camp.id, p1.id)
        record("prior_superseded", p1_ref.status == "superseded")
        p2_ref = await CalendarService.load_plan(db, tenant.id, camp.id, p2.id)
        record("new_published", p2_ref.status == "published")

    print()
    if failures:
        print(f"FAILED {len(failures)}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
