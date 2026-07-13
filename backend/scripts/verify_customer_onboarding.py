"""Verify customer onboarding readiness engine (Phase A backend foundation)."""
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
    from app.schemas.tenant_onboarding import OnboardingCompanyProfile
    from app.services.auth_service import hash_password
    from app.services.onboarding_auto_config_service import OnboardingAutoConfigService
    from app.services.onboarding_readiness_service import (
        BUSINESS_STEP_DEFS,
        FIRST_SUCCESS_STEP_DEFS,
        PLATFORM_STEP_DEFS,
        OnboardingReadinessService,
    )
    from app.services.tenant_onboarding_service import TenantOnboardingService

    await ensure_dev_schema_patches()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []
    checks: list[dict] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        status = "passed" if ok else "failed"
        checks.append({"id": check_id, "status": status, "detail": detail})
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    record("step_defs_platform", len(PLATFORM_STEP_DEFS) == 12, f"count={len(PLATFORM_STEP_DEFS)}")
    record("step_defs_business", len(BUSINESS_STEP_DEFS) == 4, f"count={len(BUSINESS_STEP_DEFS)}")
    record("step_defs_first_success", len(FIRST_SUCCESS_STEP_DEFS) == 4, f"count={len(FIRST_SUCCESS_STEP_DEFS)}")

    async with AsyncSessionLocal() as db:
        tenants: list[tuple[Tenant, TenantUser]] = []
        for i in range(2):
            tenant = Tenant(
                id=uuid4(),
                company_name=f"Onboarding Verify {stamp}-{i}",
                status="active",
                plan="trial",
            )
            user = TenantUser(
                id=uuid4(),
                tenant_id=tenant.id,
                email=f"onb-verify-{stamp}-{i}@example.com",
                password_hash=hash_password("test1234"),
                role="owner",
                status="active",
            )
            db.add(tenant)
            db.add(user)
            tenants.append((tenant, user))
        await db.commit()

        tenant_a, _ = tenants[0]
        tenant_b, _ = tenants[1]

        from app.models.client import Client

        client_a = Client(
            id=uuid4(),
            tenant_id=tenant_a.id,
            company_name=tenant_a.company_name,
            source_language="en",
            business_category="manufacturing",
            content_style="professional",
            status="active",
            brand_name=tenant_a.company_name,
        )
        db.add(client_a)
        await db.commit()

        auto_a = await OnboardingAutoConfigService.ensure_tenant_onboarding_defaults(db, tenant_a.id)
        await db.commit()
        record("auto_config_applied", auto_a.get("skipped") is False, str(auto_a))

        auto_a_repeat = await OnboardingAutoConfigService.ensure_tenant_onboarding_defaults(db, tenant_a.id)
        record("auto_config_idempotent", auto_a_repeat.get("skipped") is True, str(auto_a_repeat))

        from sqlalchemy import func, select
        from app.models.sales_crm import SalesDeal, SalesLead, SalesProposal

        lead_count_after = int(
            (await db.execute(
                select(func.count()).select_from(SalesLead).where(SalesLead.tenant_id == tenant_a.id),
            )).scalar() or 0,
        )
        deal_count_after = int(
            (await db.execute(
                select(func.count()).select_from(SalesDeal).where(SalesDeal.tenant_id == tenant_a.id),
            )).scalar() or 0,
        )
        proposal_count_after = int(
            (await db.execute(
                select(func.count()).select_from(SalesProposal).where(SalesProposal.tenant_id == tenant_a.id),
            )).scalar() or 0,
        )
        record(
            "auto_config_no_duplicates",
            lead_count_after == 1 and deal_count_after == 1 and proposal_count_after == 1,
            f"leads={lead_count_after} deals={deal_count_after} proposals={proposal_count_after}",
        )

        progress_a = (
            await db.execute(
                __import__("sqlalchemy").select(TenantOnboardingProgress).where(
                    TenantOnboardingProgress.tenant_id == tenant_a.id,
                ),
            )
        ).scalar_one_or_none()
        record("progress_persisted", progress_a is not None and progress_a.auto_config_applied)

        readiness_a = await TenantOnboardingService.readiness(db, tenant_a.id)
        record(
            "dual_metrics_present",
            readiness_a.platform_readiness_percent >= 0
            and readiness_a.business_readiness_percent >= 0
            and readiness_a.overall_percent >= 0,
            f"platform={readiness_a.platform_readiness_percent} "
            f"business={readiness_a.business_readiness_percent} "
            f"overall={readiness_a.overall_percent}",
        )
        record(
            "estimated_minutes",
            readiness_a.estimated_minutes_remaining >= 0,
            str(readiness_a.estimated_minutes_remaining),
        )
        record(
            "step_status_enum",
            all(
                s.status in ("completed", "missing", "recommended", "blocked")
                for s in readiness_a.platform_steps
            ),
            "platform step statuses valid",
        )
        record(
            "first_success_gated",
            readiness_a.first_success is None if not readiness_a.platform_ready else True,
            "first_success hidden until platform ready",
        )

        await TenantOnboardingService.save_company_profile(
            db,
            tenant_a.id,
            OnboardingCompanyProfile(
                company_name=f"Onboarding Verify {stamp}-0",
                industry="manufacturing",
                country="China",
            ),
        )
        await db.commit()
        readiness_after = await TenantOnboardingService.readiness(db, tenant_a.id)
        company_step = next(s for s in readiness_after.platform_steps if s.id == "company_info")
        industry_step = next(s for s in readiness_after.platform_steps if s.id == "industry_selection")
        record("company_step_completed", company_step.status == "completed")
        record("industry_step_completed", industry_step.status == "completed")
        record(
            "progress_increased",
            readiness_after.overall_percent >= readiness_a.overall_percent,
            f"{readiness_a.overall_percent} -> {readiness_after.overall_percent}",
        )

        await OnboardingReadinessService.record_walkthrough_panel(
            db,
            tenant_a.id,
            progress_a,
            "executive_dashboard",
        )
        await db.commit()
        walkthrough = await OnboardingReadinessService.record_walkthrough_panel(
            db,
            tenant_a.id,
            (
                await db.execute(
                    __import__("sqlalchemy").select(TenantOnboardingProgress).where(
                        TenantOnboardingProgress.tenant_id == tenant_a.id,
                    ),
                )
            ).scalar_one(),
            "crm_pipeline",
        )
        record(
            "walkthrough_persistence",
            walkthrough.executive_walkthrough.completed_panels >= 2,
            f"panels={walkthrough.executive_walkthrough.completed_panels}",
        )

        readiness_b = await TenantOnboardingService.readiness(db, tenant_b.id)
        record(
            "tenant_isolation",
            readiness_b.tenant_id == tenant_b.id and readiness_b.tenant_id != readiness_a.tenant_id,
            f"a={readiness_a.tenant_id} b={readiness_b.tenant_id}",
        )
        record(
            "tenant_b_no_auto_config",
            not readiness_b.auto_config_applied,
            f"auto_config_applied={readiness_b.auto_config_applied}",
        )

        # North Star goal must survive auto-configuration
        progress_a.north_star_goal = "brand_awareness"
        await db.commit()
        north_star_before = progress_a.north_star_goal
        auto_with_goal = await OnboardingAutoConfigService.ensure_tenant_onboarding_defaults(db, tenant_a.id)
        await db.commit()
        progress_after_goal = (
            await db.execute(
                select(TenantOnboardingProgress).where(TenantOnboardingProgress.tenant_id == tenant_a.id),
            )
        ).scalar_one()
        record(
            "north_star_preserved",
            progress_after_goal.north_star_goal == north_star_before == "brand_awareness",
            f"goal={progress_after_goal.north_star_goal}",
        )
        record("north_star_skip_when_applied", auto_with_goal.get("skipped") is True, str(auto_with_goal))

        # Completed onboarding must not be reset by auto-config on a fresh tenant
        tenant_completed = Tenant(
            id=uuid4(),
            company_name=f"Onboarding Completed {stamp}",
            status="active",
            plan="trial",
        )
        db.add(tenant_completed)
        await db.flush()
        client_completed = Client(
            id=uuid4(),
            tenant_id=tenant_completed.id,
            company_name=tenant_completed.company_name,
            source_language="en",
            business_category="manufacturing",
            content_style="professional",
            status="active",
            brand_name=tenant_completed.company_name,
        )
        db.add(client_completed)
        completed_at = datetime.now(timezone.utc)
        progress_completed = TenantOnboardingProgress(
            tenant_id=tenant_completed.id,
            status="completed",
            progress_percent=100,
            steps_completed={"company_info": completed_at.isoformat()},
            milestone_messages=[],
            started_at=completed_at,
            completed_at=completed_at,
            north_star_goal="export_leads",
            executive_walkthrough_progress={"completed_panels": ["executive_dashboard"]},
            first_success_state={"first_lead": completed_at.isoformat()},
        )
        db.add(progress_completed)
        await db.commit()

        auto_completed = await OnboardingAutoConfigService.ensure_tenant_onboarding_defaults(
            db, tenant_completed.id,
        )
        await db.commit()
        progress_completed = (
            await db.execute(
                select(TenantOnboardingProgress).where(
                    TenantOnboardingProgress.tenant_id == tenant_completed.id,
                ),
            )
        ).scalar_one()
        record(
            "completed_onboarding_not_reset",
            progress_completed.status == "completed"
            and progress_completed.north_star_goal == "export_leads"
            and progress_completed.executive_walkthrough_progress.get("completed_panels") == ["executive_dashboard"],
            f"status={progress_completed.status} goal={progress_completed.north_star_goal}",
        )
        record("completed_auto_config_applied", auto_completed.get("skipped") is False, str(auto_completed))

        # Partial configuration: existing lead should not be duplicated
        tenant_partial = Tenant(
            id=uuid4(),
            company_name=f"Onboarding Partial {stamp}",
            status="active",
            plan="trial",
        )
        db.add(tenant_partial)
        await db.flush()
        client_partial = Client(
            id=uuid4(),
            tenant_id=tenant_partial.id,
            company_name=tenant_partial.company_name,
            source_language="en",
            business_category="manufacturing",
            content_style="professional",
            status="active",
            brand_name=tenant_partial.company_name,
        )
        db.add(client_partial)
        db.add(SalesLead(
            id=uuid4(),
            tenant_id=tenant_partial.id,
            name="Existing Lead",
            company="Partial Co",
            email="partial@example.com",
            status="new",
            source="manual",
            notes="User-entered lead",
        ))
        await db.commit()

        auto_partial = await OnboardingAutoConfigService.ensure_tenant_onboarding_defaults(
            db, tenant_partial.id,
        )
        await db.commit()
        partial_leads = int(
            (await db.execute(
                select(func.count()).select_from(SalesLead).where(SalesLead.tenant_id == tenant_partial.id),
            )).scalar() or 0,
        )
        record(
            "partial_config_no_lead_duplicate",
            partial_leads == 1 and auto_partial.get("leads", 0) == 0,
            f"leads={partial_leads} auto={auto_partial}",
        )

        overview = await TenantOnboardingService.admin_readiness_overview(db)
        record("admin_visibility", overview.total_tenants >= 2, f"tenants={overview.total_tenants}")
        record(
            "admin_top_missing",
            isinstance(overview.top_missing_steps, dict),
            str(len(overview.top_missing_steps)),
        )

    artifact = {
        "script": "verify_customer_onboarding",
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "passed": len(failures) == 0,
        "failure_count": len(failures),
        "failures": failures,
        "checks": checks,
    }
    out = Path(__file__).resolve().parent / ".verify_customer_onboarding_last.json"
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")

    if failures:
        print(f"\nFAIL ({len(failures)} checks failed)")
        return 1
    print("\nOK all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
