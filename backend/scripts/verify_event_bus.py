"""Verify platform event bus — tenant isolation and integration handlers."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import asyncio

    return asyncio.run(_run())


async def _run() -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.core.events import event_registry
    from app.models.platform_event import (
        TenantActivityEvent,
        TenantAutomationTrigger,
        TenantEventNotification,
    )
    from app.models.platform_ops import PlatformAuditLog
    from app.models.tenant import Tenant, TenantUser
    from app.models.tenant_onboarding import TenantOnboardingProgress
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration
    from app.services.platform_event_service import PlatformEventService

    await ensure_platform_event_bus_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

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

    record("registry_count", len(event_registry.list_all()) >= 10, f"count={len(event_registry.list_all())}")

    deal_def = event_registry.get("tenant.crm.deal_stage_changed")
    record(
        "registry_integrations",
        deal_def is not None and deal_def.integrations.audit and deal_def.integrations.automation,
        "deal_stage_changed flags",
    )

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(
            id=uuid4(),
            company_name=f"EventBus Verify A {stamp}",
            status="active",
            plan="trial",
        )
        tenant_b = Tenant(
            id=uuid4(),
            company_name=f"EventBus Verify B {stamp}",
            status="active",
            plan="trial",
        )
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"eventbus-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        db.add(tenant_a)
        db.add(tenant_b)
        db.add(user_a)
        db.add(TenantOnboardingProgress(tenant_id=tenant_a.id, status="in_progress", progress_percent=10))
        await db.commit()

        result = await PlatformEventService.emit(
            db,
            "tenant.crm.deal_stage_changed",
            tenant_a.id,
            payload={"deal_id": str(uuid4()), "from_stage": "lead", "to_stage": "qualified"},
            actor_type="tenant_user",
            actor_id=user_a.id,
            resource_type="deal",
            resource_id=str(uuid4()),
            title="Deal moved to Qualified",
            description="Pipeline stage transition",
            commit=True,
        )
        handled = result.handled_count
        record("publish_handled", handled >= 3, f"handled={handled}, subscribers={len(result.subscriber_results)}")

        counts_a = await PlatformEventService.count_tenant_records(db, tenant_a.id)
        record("activity_written", counts_a["activity"] >= 1, f"count={counts_a['activity']}")
        record("notification_written", counts_a["notifications"] >= 1, f"count={counts_a['notifications']}")
        record("automation_written", counts_a["automation_triggers"] >= 1, f"count={counts_a['automation_triggers']}")

        audit_count = (
            await db.execute(
                select(func.count())
                .select_from(PlatformAuditLog)
                .where(PlatformAuditLog.tenant_id == tenant_a.id),
            )
        ).scalar_one()
        record("audit_written", int(audit_count) >= 1, f"count={audit_count}")

        progress = (
            await db.execute(
                select(TenantOnboardingProgress).where(TenantOnboardingProgress.tenant_id == tenant_a.id),
            )
        ).scalar_one()
        record("customer_success_activity", progress.last_activity_at is not None, "last_activity_at set")

        await PlatformEventService.emit(
            db,
            "tenant.content.created",
            tenant_b.id,
            payload={"content_id": str(uuid4())},
            title="Content created",
            commit=True,
        )
        counts_b = await PlatformEventService.count_tenant_records(db, tenant_b.id)
        record("tenant_b_isolated", counts_b["activity"] >= 1, f"activity={counts_b['activity']}")

        cross_a = (
            await db.execute(
                select(func.count())
                .select_from(TenantActivityEvent)
                .where(
                    TenantActivityEvent.tenant_id == tenant_a.id,
                    TenantActivityEvent.event_type == "tenant.content.created",
                ),
            )
        ).scalar_one()
        record("tenant_a_no_cross_leak", int(cross_a) == 0, f"leaked={cross_a}")

        notifications_b = (
            await db.execute(
                select(func.count())
                .select_from(TenantEventNotification)
                .where(TenantEventNotification.tenant_id == tenant_b.id),
            )
        ).scalar_one()
        record("tenant_b_no_deal_notification", int(notifications_b) == 0, f"notifications={notifications_b}")

        triggers_a = (
            await db.execute(
                select(TenantAutomationTrigger)
                .where(TenantAutomationTrigger.tenant_id == tenant_a.id)
                .order_by(TenantAutomationTrigger.created_at.desc())
                .limit(1),
            )
        ).scalar_one_or_none()
        record(
            "automation_workflow_hint",
            triggers_a is not None and triggers_a.workflow_hint == "proposal_workflow",
            f"hint={getattr(triggers_a, 'workflow_hint', None)}",
        )

    print(f"\n{len(checks) - len(failures)}/{len(checks)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
