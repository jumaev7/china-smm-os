"""Verify Automation Center — persistence, execution, tenant isolation, recursion."""
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
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.core.events import build_tenant_event
    from app.models.automation import TenantAutomationFlow
    from app.models.platform_event import TenantAutomationTrigger
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.automation_execution_service import AutomationExecutionService
    from app.services.automation_service import AutomationService
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

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(
            id=uuid4(),
            company_name=f"Automation Verify A {stamp}",
            status="active",
            plan="trial",
        )
        tenant_b = Tenant(
            id=uuid4(),
            company_name=f"Automation Verify B {stamp}",
            status="active",
            plan="trial",
        )
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"auto-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        db.add(tenant_a)
        db.add(tenant_b)
        db.add(user_a)
        await db.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id

        first_seed = await AutomationService.ensure_system_flows(db, tenant_a_id)
        second_seed = await AutomationService.ensure_system_flows(db, tenant_a_id)
        await db.commit()
        record("system_flows_seed", first_seed >= 3, f"created={first_seed}")
        record("system_flows_idempotent", second_seed == 0)

        flow_rows = (
            await db.execute(
                select(TenantAutomationFlow).where(TenantAutomationFlow.tenant_id == tenant_a_id),
            )
        ).scalars().all()
        record("unique_tenant_keys", len({r.key for r in flow_rows}) == len(flow_rows))

        listed_a = await AutomationService.list_flows(db, tenant_a_id)
        listed_b = await AutomationService.list_flows(db, tenant_b_id)
        record("list_tenant_a", listed_a.total >= 3, f"total={listed_a.total}")
        record("list_tenant_b", listed_b.total >= 3, f"total={listed_b.total}")

        flow_a = listed_a.items[0]
        try:
            await AutomationService.get_flow(db, tenant_b_id, flow_a.id)
            record("tenant_isolation_get", False, "tenant B read tenant A flow")
        except HTTPException as exc:
            record("tenant_isolation_get", exc.status_code == 404, f"status={exc.status_code}")

        publish_flow = next((f for f in listed_a.items if f.key == "system_publish_failed_notify"), None)
        if publish_flow:
            await AutomationService.pause_flow(db, tenant_a_id, publish_flow.id)
            await db.commit()
            refreshed = await AutomationService.get_flow(db, tenant_a_id, publish_flow.id)
            record("status_pause_persists", refreshed.status == "paused")
            await AutomationService.enable_flow(db, tenant_a_id, publish_flow.id)
            await db.commit()

        result = await PlatformEventService.emit(
            db,
            "tenant.content.publish_failed",
            tenant_a_id,
            payload={"resource_name": f"Verify post {stamp}"},
            title="Publish failed",
            commit=True,
        )
        record("event_bus_emit", result.handled_count >= 1, f"handled={result.handled_count}")

        triggers = (
            await db.execute(
                select(TenantAutomationTrigger).where(TenantAutomationTrigger.tenant_id == tenant_a_id),
            )
        ).scalars().all()
        record("trigger_inbox_written", len(triggers) >= 1, f"triggers={len(triggers)}")

        execs = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=20)
        record("execution_history", execs.total >= 1, f"total={execs.total}")

        kpis = await AutomationService.get_kpis(db, tenant_a_id)
        record("kpi_metrics", kpis.health_score >= 0 and kpis.total_flows >= 3)

        if publish_flow:
            dup_event = build_tenant_event(
                "tenant.content.publish_failed",
                tenant_a_id,
                payload={"resource_name": "dup"},
            )
            first = await AutomationExecutionService.process_event(db, dup_event)
            second = await AutomationExecutionService.process_event(db, dup_event)
            await db.commit()
            record(
                "duplicate_event_controlled",
                len(first) >= 1 and len(second) >= 1 and first[0].id == second[0].id,
                "idempotent per event_id",
            )

        loop_event = build_tenant_event(
            "tenant.content.publish_failed",
            tenant_a_id,
            payload={"resource_name": "loop"},
            metadata={"automation_origin": True},
        )
        loop_execs = await AutomationExecutionService.process_event(db, loop_event)
        record("recursion_guard", len(loop_execs) == 0)

        if publish_flow:
            manual = await AutomationService.manual_run(db, tenant_a_id, publish_flow.id)
            await db.commit()
            record("manual_test_run", manual.is_manual_test and manual.execution_id is not None)

    artifact = Path(__file__).resolve().parent / ".verify_automation_center_last.json"
    artifact.write_text(
        json.dumps(
            {
                "stamp": stamp,
                "checks": checks,
                "passed": len(checks) - len(failures),
                "total": len(checks),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n{len(checks) - len(failures)}/{len(checks)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
