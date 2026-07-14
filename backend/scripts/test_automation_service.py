"""Unit-style checks for Automation Center service layer."""
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
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.core.events import build_tenant_event
    from app.models.automation import TenantAutomationExecution, TenantAutomationFlow
    from app.models.client import Client
    from app.models.tenant import Tenant
    from app.services.auth_service import hash_password
    from app.services.automation_execution_service import AutomationExecutionService
    from app.services.automation_service import AutomationService
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration

    await ensure_platform_event_bus_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Auto Svc A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Auto Svc B {stamp}", status="active", plan="trial")
        db.add(tenant_a)
        db.add(tenant_b)
        await db.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id

        created_a = await AutomationService.ensure_system_flows(db, tenant_a_id)
        created_repeat = await AutomationService.ensure_system_flows(db, tenant_a_id)
        await db.commit()
        record("seed_system_flows", created_a >= 3, f"created={created_a}")
        record("seed_idempotent", created_repeat == 0, f"repeat_created={created_repeat}")

        listed = await AutomationService.list_flows(db, tenant_a_id)
        record("list_flows", listed.total >= 3, f"total={listed.total}")

        publish_flow = next((f for f in listed.items if f.key == "system_publish_failed_notify"), None)
        record("publish_flow_present", publish_flow is not None)

        if publish_flow:
            paused = await AutomationService.pause_flow(db, tenant_a_id, publish_flow.id)
            await db.commit()
            record("pause_persists", paused.status == "paused", paused.status)
            enabled = await AutomationService.enable_flow(db, tenant_a_id, publish_flow.id)
            await db.commit()
            record("enable_persists", enabled.status == "enabled", enabled.status)

        try:
            await AutomationService.get_flow(db, tenant_a_id, uuid4())
            record("wrong_tenant_404", False, "expected 404")
        except HTTPException as exc:
            record("wrong_tenant_404", exc.status_code == 404, f"status={exc.status_code}")

        listed_b = await AutomationService.list_flows(db, tenant_b_id)
        record("tenant_b_isolated", listed_b.total >= 3 and all("Svc A" not in (f.name or "") for f in listed_b.items))

        if publish_flow:
            event = build_tenant_event(
                "tenant.content.publish_failed",
                tenant_a_id,
                payload={"resource_name": "Test widget"},
                title="Publish failed",
            )
            executions = await AutomationExecutionService.process_event(db, event)
            await db.commit()
            record("enabled_flow_executes", len(executions) >= 1, f"count={len(executions)}")
            if executions:
                record("execution_success", executions[0].status == "success", executions[0].status)

            await AutomationService.pause_flow(db, tenant_a_id, publish_flow.id)
            await db.commit()
            event2 = build_tenant_event(
                "tenant.content.publish_failed",
                tenant_a_id,
                payload={"resource_name": "Paused test"},
            )
            paused_execs = await AutomationExecutionService.process_event(db, event2)
            await db.commit()
            record("paused_flow_skips", len(paused_execs) == 0, f"count={len(paused_execs)}")

            await AutomationService.enable_flow(db, tenant_a_id, publish_flow.id)
            await db.commit()

        unrelated = build_tenant_event("tenant.user.login", tenant_a_id, payload={})
        unrelated_execs = await AutomationExecutionService.process_event(db, unrelated)
        record("unrelated_event_skips", len(unrelated_execs) == 0, f"count={len(unrelated_execs)}")

        origin_event = build_tenant_event(
            "tenant.content.publish_failed",
            tenant_a_id,
            payload={"resource_name": "Loop test"},
            metadata={"automation_origin": True},
        )
        loop_execs = await AutomationExecutionService.process_event(db, origin_event)
        record("recursion_prevented", len(loop_execs) == 0, f"count={len(loop_execs)}")

        if publish_flow:
            manual = await AutomationService.manual_run(db, tenant_a_id, publish_flow.id)
            await db.commit()
            record("manual_run", manual.execution_id is not None, manual.status)

        kpis = await AutomationService.get_kpis(db, tenant_a_id)
        record("kpi_response", kpis.total_flows >= 3, f"flows={kpis.total_flows}")

        exec_page = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=5)
        record("executions_pagination", exec_page.page == 1 and exec_page.page_size == 5)

    total = 15
    passed = total - len(failures)
    print(f"\n{passed}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
