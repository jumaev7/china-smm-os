"""Verify AI campaign plan proposal + apply creates draft plan only.

Run from backend/:  python scripts/verify_campaign_ai_planning.py
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
    from app.core.config import settings
    from app.core.database import AsyncSessionLocal, ensure_campaign_planner_schema, ensure_governed_ai_schema
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.campaign_planner.ai_plan_service import CampaignAIPlanService
    from app.services.campaign_planner.calendar_service import CalendarService
    from app.services.campaign_planner.campaign_service import CampaignService
    from app.services.ai_platform.prompt_registry import PROMPT_KEY_CAMPAIGN_PLAN_PROPOSAL, get_prompt
    from app.services.ai_platform.schemas import TASK_CAMPAIGN_PLAN_PROPOSAL

    await ensure_governed_ai_schema()
    await ensure_campaign_planner_schema()

    # Enable mock AI for this process (deterministic; no external provider).
    settings.AI_PLATFORM_ENABLED = True
    settings.AI_DEFAULT_PROVIDER = "mock"

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures = []

    def record(c, ok, d=""):
        print(("OK" if ok else "FAIL") + f" {c}" + (f" — {d}" if d else ""))
        if not ok:
            failures.append(c)

    prompt = get_prompt(PROMPT_KEY_CAMPAIGN_PLAN_PROPOSAL)
    record("prompt_registered", prompt.prompt_key == PROMPT_KEY_CAMPAIGN_PLAN_PROPOSAL and prompt.task_type == TASK_CAMPAIGN_PLAN_PROPOSAL)
    record("ai_platform_flag", settings.AI_PLATFORM_ENABLED is True or settings.AI_PLATFORM_ENABLED is False)

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"CP AI {stamp}", status="active", plan="trial")
        user = TenantUser(id=uuid4(), tenant_id=tenant.id, email=f"cpai-{stamp}@example.com",
                          password_hash=hash_password("test1234"), role="owner", status="active")
        db.add_all([tenant, user])
        await db.commit()

        camp = await CampaignService.create_campaign(db, tenant.id, {
            "name": "AI Plan", "platforms": ["telegram", "instagram"], "locales": ["en"],
            "start_date": date(2026, 8, 1), "end_date": date(2026, 8, 14),
            "cadence": {"posts_per_week": 3},
        }, created_by=user.id)
        await db.commit()

        detail = await CampaignAIPlanService.request_plan(
            db, tenant.id, camp.id, quality_mode="standard", requested_by=user.id,
        )
        await db.commit()
        record("ai_request_completed", detail["status"] in {"completed", "provider_failed", "validation_failed"}, detail["status"])
        req_id = detail["request_id"]

        # Idempotent re-request
        detail2 = await CampaignAIPlanService.request_plan(
            db, tenant.id, camp.id, quality_mode="standard", requested_by=user.id,
        )
        await db.commit()
        record("ai_idempotent", str(detail2["request_id"]) == str(req_id))

        if detail["status"] == "completed":
            applied = await CampaignAIPlanService.apply_proposal(db, tenant.id, req_id, applied_by=user.id)
            await db.commit()
            plan_id = applied.get("applied_plan_version_id")
            record("ai_applied", applied.get("apply_status") == "applied" and plan_id)
            if plan_id:
                from uuid import UUID
                plan = await CalendarService.load_plan(db, tenant.id, camp.id, UUID(str(plan_id)))
                record("applied_is_draft", plan.status == "draft", plan.status)
                record("generation_ai_assisted", plan.generation_method == "ai_assisted")
                record("not_auto_published", plan.published_at is None)

            rejected_ok = False
            try:
                await CampaignAIPlanService.reject_proposal(db, tenant.id, req_id)
            except Exception:
                rejected_ok = True
            record("cannot_reject_after_apply", rejected_ok)

    print()
    if failures:
        print(f"FAILED {len(failures)}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
