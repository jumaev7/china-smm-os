"""DB integration verification for Campaign Planner.

Run from backend/:  python scripts/verify_campaign_planner.py
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


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


async def _run() -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_campaign_planner_schema, ensure_platform_event_bus_schema
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.campaign_planner.calendar_service import CalendarService
    from app.services.campaign_planner.campaign_service import CampaignService
    from app.services.campaign_planner.planning_service import PlanningService
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration

    await ensure_platform_event_bus_schema()
    await ensure_campaign_planner_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"CP Verify A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"CP Verify B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(), tenant_id=tenant_a.id, email=f"cp-a-{stamp}@example.com",
            password_hash=hash_password("test1234"), role="owner", status="active",
        )
        client_a = Client(id=uuid4(), tenant_id=tenant_a.id, company_name=f"CP Client A {stamp}", business_category="manufacturing", status="active")
        content_a = ContentItem(
            id=uuid4(), client_id=client_a.id, platforms=["telegram", "instagram"], status="draft",
            caption_long_en="Export-ready steel components for global buyers. Contact us for a quote.",
            hashtags="#export #steel",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a])
        await db.commit()
        db.add(content_a)
        await db.commit()

        campaign = await CampaignService.create_campaign(
            db, tenant_a.id,
            {
                "name": f"Spring Launch {stamp}",
                "timezone": "Asia/Tashkent",
                "primary_locale": "en",
                "locales": ["en", "ru"],
                "platforms": ["telegram", "instagram"],
                "start_date": date(2026, 4, 1),
                "end_date": date(2026, 4, 14),
                "blackout_dates": ["2026-04-05"],
                "cadence": {"posts_per_week": 3, "max_posts_per_day_per_platform": 2, "min_spacing_minutes": 120},
            },
            created_by=user_a.id,
        )
        await db.commit()
        record("campaign_created", campaign.status == "draft")

        pillar = await CampaignService.create_pillar(db, tenant_a.id, {"name": "Education", "slug": "edu"}, created_by=user_a.id)
        await CampaignService.add_campaign_pillar(db, tenant_a.id, campaign.id, {"pillar_id": pillar.id, "weight": 2})
        await CampaignService.add_phase(
            db, tenant_a.id, campaign.id,
            {"name": "Launch", "phase_type": "launch", "start_date": "2026-04-01", "end_date": "2026-04-07"},
        )
        await db.commit()

        plan1 = await PlanningService.generate(db, tenant_a.id, campaign.id, created_by=user_a.id)
        await db.commit()
        plan2 = await PlanningService.generate(db, tenant_a.id, campaign.id, created_by=user_a.id)
        await db.commit()
        record("plan_generated", plan1.slot_count > 0, str(plan1.slot_count))
        record("deterministic_fingerprint", plan1.plan_fingerprint == plan2.plan_fingerprint, plan1.plan_fingerprint[:12])
        record("campaign_status_planning", (await CampaignService.load_campaign(db, tenant_a.id, campaign.id)).status == "planning")

        slots = await CalendarService.list_slots(db, tenant_a.id, plan1.id)
        record("slots_created", len(slots) == plan1.slot_count)
        record("no_blackout", all(s.scheduled_date != date(2026, 4, 5) for s in slots))
        record("suggested_time_label", all(s.suggested_time_label for s in slots))

        # Tenant isolation
        iso = False
        try:
            await CampaignService.load_campaign(db, tenant_b.id, campaign.id)
        except Exception as exc:
            iso = _status_code(exc) == 404
        record("cross_tenant_campaign_404", iso)

        # Publish immutability
        published = await PlanningService.publish(db, tenant_a.id, campaign.id, plan1.id, published_by=user_a.id)
        await db.commit()
        record("plan_published", published.status == "published")
        immutable = False
        try:
            await CalendarService.create_slot(
                db, tenant_a.id, campaign.id, plan1.id,
                {"platform": "telegram", "locale": "en", "scheduled_date": "2026-04-10", "scheduled_time": "09:00"},
            )
        except Exception as exc:
            immutable = _status_code(exc) == 409
        record("published_plan_immutable", immutable)

        # Assignment does not publish content
        open_slot = next(s for s in slots if s.status == "unassigned")
        from app.services.campaign_planner.slot_assignment import SlotAssignmentService
        assignment = await SlotAssignmentService.assign(
            db, tenant_a.id, campaign.id, plan1.id, open_slot.id, content_a.id,
            allow_warnings=True, run_publish_safety=False, assigned_by=user_a.id,
        )
        await db.commit()
        refreshed = (await db.execute(select(ContentItem).where(ContentItem.id == content_a.id))).scalar_one()
        record("assign_ok", assignment.assignment_status in {"assigned", "ready", "ready_with_warnings", "blocked"})
        record("assign_does_not_publish", (refreshed.status or "draft") not in {"published", "scheduled", "publishing"}, str(refreshed.status))
        record("assign_does_not_schedule", refreshed.scheduled_for is None)

        review = await PlanningService.review(db, tenant_a.id, campaign.id, plan1.id, created_by=user_a.id)
        await db.commit()
        record("review_created", review.total_slots == plan1.slot_count)

        archived = await CampaignService.archive_campaign(db, tenant_a.id, campaign.id)
        await db.commit()
        record("campaign_archived", archived.status == "archived")

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
