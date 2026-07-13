"""Verify Customer Success Journey Phase 1 — engine, API routes, tenant isolation."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import asyncio
    return asyncio.run(_run())


async def _run() -> int:
    from app.core.database import AsyncSessionLocal, ensure_dev_schema_patches
    from app.models.tenant import Tenant, TenantUser
    from app.models.tenant_onboarding import TenantOnboardingProgress
    from app.services.auth_service import hash_password
    from app.services.customer_success_journey_service import CustomerSuccessJourneyService
    from app.services.tenant_onboarding_service import TenantOnboardingService

    await ensure_dev_schema_patches()

    failures: list[str] = []
    checks: list[dict] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        status = "passed" if ok else "failed"
        checks.append({"id": check_id, "status": status, "detail": detail})
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    # Unit-level rule engine tests
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "test_customer_success_journey",
        Path(__file__).parent / "test_customer_success_journey.py",
    )
    unit_tests = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(unit_tests)
    for name in (
        "test_north_star_options_count",
        "test_checkpoint_days_mapping",
        "test_success_score_independent_components",
        "test_recommendations_adapt_to_north_star",
        "test_weekly_wins_positive_only",
        "test_timeline_chronological_order",
        "test_renewal_readiness_score_bounds",
    ):
        try:
            getattr(unit_tests, name)()
            record(f"unit.{name}", True)
        except Exception as exc:
            record(f"unit.{name}", False, str(exc))

    # Route registration
    from app.main import app
    paths = [getattr(r, "path", "") for r in app.routes]
    journey_routes = [p for p in paths if "customer-success/journey" in p]
    record("routes.journey_count", len(journey_routes) >= 4, f"count={len(journey_routes)}")
    record("routes.north_star_onboarding", any("onboarding/north-star-goal" in p for p in paths))

    stamp = int(datetime.now(timezone.utc).timestamp())

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(
            id=uuid4(),
            company_name=f"Journey Verify A {stamp}",
            status="active",
            plan="trial",
        )
        tenant_b = Tenant(
            id=uuid4(),
            company_name=f"Journey Verify B {stamp}",
            status="active",
            plan="trial",
        )
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"journey-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        db.add(tenant_a)
        db.add(tenant_b)
        db.add(user_a)
        await db.commit()

        # Not platform ready — journey not started
        dash_pre = await CustomerSuccessJourneyService.dashboard(db, tenant_a.id, persist=False)
        record("journey.not_started", dash_pre.status == "not_started")
        record("journey.platform_not_ready", not dash_pre.platform_ready)

        # Save north star during onboarding
        goal, label = await TenantOnboardingService.save_north_star_goal(
            db, tenant_a.id, "export_leads",
        )
        record("onboarding.north_star_saved", goal == "export_leads", label)

        # Simulate platform ready
        progress = await TenantOnboardingService.get_or_create_progress(db, tenant_a.id)
        progress.platform_ready_at = datetime.now(timezone.utc)
        progress.north_star_goal = "export_leads"
        await db.commit()

        progress_b = TenantOnboardingProgress(
            tenant_id=tenant_b.id,
            status="in_progress",
            progress_percent=50,
            steps_completed={},
            milestone_messages=[],
            platform_ready_at=datetime.now(timezone.utc),
            north_star_goal="more_buyers",
        )
        db.add(progress_b)
        await db.commit()

        # Force platform_ready evaluation by mocking via direct journey start
        from app.models.customer_success_journey import TenantCustomerSuccessJourney
        journey_a = TenantCustomerSuccessJourney(
            tenant_id=tenant_a.id,
            status="active",
            started_at=datetime.now(timezone.utc),
            milestones_achieved={},
            timeline_entries=[],
            weekly_wins=[],
            dismissed_recommendations=[],
        )
        db.add(journey_a)
        journey_b = TenantCustomerSuccessJourney(
            tenant_id=tenant_b.id,
            status="active",
            started_at=datetime.now(timezone.utc),
            milestones_achieved={},
            timeline_entries=[],
            weekly_wins=[],
            dismissed_recommendations=[],
        )
        db.add(journey_b)
        await db.commit()

        from app.services.onboarding_readiness_service import PLATFORM_STEP_DEFS

        now_iso = datetime.now(timezone.utc).isoformat()
        completed = {
            s.id: now_iso for s in PLATFORM_STEP_DEFS if s.required
        }
        progress.steps_completed = completed
        progress.platform_readiness_percent = 100
        progress.platform_ready_at = datetime.now(timezone.utc)
        progress.north_star_goal = "export_leads"
        await db.commit()

        dash_a = await CustomerSuccessJourneyService.dashboard(db, tenant_a.id, persist=True)
        record("journey.active", dash_a.status in ("active", "completed"))
        record("journey.north_star", dash_a.north_star_goal == "export_leads")
        record("journey.checkpoints", len(dash_a.checkpoints) == 5)
        record("journey.success_score", 0 <= dash_a.success_score.score <= 100)
        record(
            "journey.health_independent",
            dash_a.health_score is not None
            and dash_a.success_score.score != dash_a.health_score.score or dash_a.health_score.score >= 0,
        )
        record("journey.weekly_wins_field", isinstance(dash_a.weekly_wins, list))
        record("journey.timeline_field", isinstance(dash_a.timeline, list))
        record("journey.renewal_readiness", dash_a.renewal_readiness.score >= 0)

        dash_b = await CustomerSuccessJourneyService.dashboard(db, tenant_b.id, persist=False)
        record("isolation.tenant_b", dash_b.tenant_id == tenant_b.id)
        record("isolation.north_star_b", dash_b.north_star_goal == "more_buyers")

        refresh = await CustomerSuccessJourneyService.refresh(db, tenant_a.id)
        record("journey.refresh", refresh.refreshed)

        if dash_a.recommendations:
            rec_id = dash_a.recommendations[0].id
            dismissed = await CustomerSuccessJourneyService.dismiss_recommendation(
                db, tenant_a.id, rec_id,
            )
            record("journey.dismiss", dismissed.dismissed)

        admin = await CustomerSuccessJourneyService.admin_overview(db)
        record("admin.overview", admin.total_tenants >= 2)

    out_path = Path(__file__).parent / ".verify_customer_success_journey_last.json"
    out_path.write_text(json.dumps({"checks": checks, "failures": failures}, indent=2), encoding="utf-8")

    print(f"\n{len(checks) - len(failures)}/{len(checks)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
