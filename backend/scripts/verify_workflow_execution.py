"""Verify Workflow Execution — event-driven runs, ordering, idempotency, coexistence with simple flows."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _workflow_definition_match() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {
            "operator": "all",
            "items": [{"id": "c1", "field": "platform", "op": "equals", "value": "instagram"}],
        },
        "steps": [
            {
                "id": "step_1",
                "type": "action",
                "action_type": "create_notification",
                "config": {"title": "Hi", "category": "automation"},
            },
            {
                "id": "step_2",
                "type": "action",
                "action_type": "record_activity",
                "config": {"title": "Logged"},
            },
        ],
        "failure_policy": "stop_on_failure",
    }


def _workflow_definition_always_fails() -> dict[str, Any]:
    """Unconditional match, second step deliberately fails (no CRM client exists for tenant)."""
    return {
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {"operator": "all", "items": []},
        "steps": [
            {
                "id": "step_1",
                "type": "action",
                "action_type": "record_activity",
                "config": {"title": "Runs first"},
            },
            {
                "id": "step_2",
                "type": "action",
                "action_type": "create_crm_lead",
                "config": {},
            },
        ],
        "failure_policy": "stop_on_failure",
    }


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.core.events import build_tenant_event, event_bus
    from app.models.automation import TenantAutomationExecution
    from app.models.tenant import Tenant
    from app.models.workflow import TenantWorkflowExecution, TenantWorkflowStepExecution
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.workflow_service import WorkflowService

    await ensure_platform_event_bus_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "PASS" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" -> {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant = Tenant(
            id=uuid4(),
            company_name=f"Workflow Exec Verify {stamp}",
            status="active",
            plan="trial",
        )
        db.add(tenant)
        await db.flush()

        workflow_a = await WorkflowService.create_workflow(
            db,
            tenant.id,
            name="Match Workflow",
            key=f"match_wf_{stamp}",
            definition=_workflow_definition_match(),
        )
        await WorkflowService.publish_workflow(db, tenant.id, workflow_a.id)

        workflow_b = await WorkflowService.create_workflow(
            db,
            tenant.id,
            name="Always Fails Workflow",
            key=f"fail_wf_{stamp}",
            definition=_workflow_definition_always_fails(),
        )
        await WorkflowService.publish_workflow(db, tenant.id, workflow_b.id)
        await db.commit()
        record("setup_workflows_published", True, f"a={workflow_a.id} b={workflow_b.id}")

        # ── matching event: workflow A matches + runs both steps in order;
        #    workflow B always matches and deliberately fails at step 2 ──────
        event = build_tenant_event(
            "tenant.content.publish_failed",
            tenant.id,
            payload={
                "content_id": str(uuid4()),
                "platform": "instagram",
                "failure_code": "network_timeout",
                "resource_name": "Test Post",
            },
            title="Publish failed",
        )
        result = await event_bus.publish(db, event)
        await db.commit()
        record("event_handled", result.handled_count >= 1, f"handled={result.handled_count}")

        exec_a = (
            await db.execute(
                select(TenantWorkflowExecution).where(
                    TenantWorkflowExecution.tenant_id == tenant.id,
                    TenantWorkflowExecution.workflow_id == workflow_a.id,
                    TenantWorkflowExecution.platform_event_id == event.event_id,
                ),
            )
        ).scalar_one_or_none()
        record(
            "workflow_a_matched_and_ran",
            exec_a is not None and exec_a.status == "success",
            f"status={getattr(exec_a, 'status', None)}",
        )

        steps_a = (
            (
                await db.execute(
                    select(TenantWorkflowStepExecution)
                    .where(TenantWorkflowStepExecution.workflow_execution_id == exec_a.id)
                    .order_by(TenantWorkflowStepExecution.step_index.asc()),
                )
            ).scalars().all()
            if exec_a is not None
            else []
        )
        record(
            "workflow_a_steps_run_in_order",
            len(steps_a) == 2
            and steps_a[0].step_id == "step_1"
            and steps_a[0].action_type == "create_notification"
            and steps_a[0].status == "success"
            and steps_a[1].step_id == "step_2"
            and steps_a[1].action_type == "record_activity"
            and steps_a[1].status == "success",
            f"steps={[(s.step_id, s.action_type, s.status) for s in steps_a]}",
        )

        exec_b = (
            await db.execute(
                select(TenantWorkflowExecution).where(
                    TenantWorkflowExecution.tenant_id == tenant.id,
                    TenantWorkflowExecution.workflow_id == workflow_b.id,
                    TenantWorkflowExecution.platform_event_id == event.event_id,
                ),
            )
        ).scalar_one_or_none()
        record(
            "workflow_b_fails_at_step_2",
            exec_b is not None and exec_b.status == "failed" and exec_b.error_code == "no_client",
            f"status={getattr(exec_b, 'status', None)} error={getattr(exec_b, 'error_code', None)}",
        )

        steps_b = (
            (
                await db.execute(
                    select(TenantWorkflowStepExecution)
                    .where(TenantWorkflowStepExecution.workflow_execution_id == exec_b.id)
                    .order_by(TenantWorkflowStepExecution.step_index.asc()),
                )
            ).scalars().all()
            if exec_b is not None
            else []
        )
        record(
            "workflow_b_step_1_ran_before_failure",
            len(steps_b) == 2 and steps_b[0].status == "success" and steps_b[1].status == "failed",
            f"steps={[(s.step_id, s.status) for s in steps_b]}",
        )

        simple_exec_count_1 = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant.id,
                    TenantAutomationExecution.trigger_event == "tenant.content.publish_failed",
                    TenantAutomationExecution.status == "success",
                ),
            )
        ).scalar_one()
        record(
            "simple_flow_unaffected_by_workflow_failure",
            int(simple_exec_count_1) >= 1,
            f"count={simple_exec_count_1}",
        )

        # ── duplicate delivery of the same event is idempotent ──────────────
        workflow_exec_count_before = (
            await db.execute(
                select(func.count())
                .select_from(TenantWorkflowExecution)
                .where(TenantWorkflowExecution.tenant_id == tenant.id),
            )
        ).scalar_one()
        automation_exec_count_before = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(TenantAutomationExecution.tenant_id == tenant.id),
            )
        ).scalar_one()

        await event_bus.publish(db, event)
        await db.commit()

        workflow_exec_count_after = (
            await db.execute(
                select(func.count())
                .select_from(TenantWorkflowExecution)
                .where(TenantWorkflowExecution.tenant_id == tenant.id),
            )
        ).scalar_one()
        automation_exec_count_after = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(TenantAutomationExecution.tenant_id == tenant.id),
            )
        ).scalar_one()
        record(
            "duplicate_event_idempotent",
            workflow_exec_count_after == workflow_exec_count_before
            and automation_exec_count_after == automation_exec_count_before,
            f"workflow {workflow_exec_count_before}->{workflow_exec_count_after} "
            f"automation {automation_exec_count_before}->{automation_exec_count_after}",
        )

        # ── non-matching event: workflow A (condition-gated) must skip ──────
        event2 = build_tenant_event(
            "tenant.content.publish_failed",
            tenant.id,
            payload={
                "content_id": str(uuid4()),
                "platform": "facebook",
                "failure_code": "network_timeout",
                "resource_name": "Test Post 2",
            },
            title="Publish failed",
        )
        await event_bus.publish(db, event2)
        await db.commit()

        exec_a_2 = (
            await db.execute(
                select(TenantWorkflowExecution).where(
                    TenantWorkflowExecution.tenant_id == tenant.id,
                    TenantWorkflowExecution.workflow_id == workflow_a.id,
                    TenantWorkflowExecution.platform_event_id == event2.event_id,
                ),
            )
        ).scalar_one_or_none()
        record(
            "workflow_a_skips_non_matching_event",
            exec_a_2 is not None and exec_a_2.status == "skipped",
            f"status={getattr(exec_a_2, 'status', None)}",
        )

        skipped_steps = (
            (
                await db.execute(
                    select(func.count())
                    .select_from(TenantWorkflowStepExecution)
                    .where(TenantWorkflowStepExecution.workflow_execution_id == exec_a_2.id),
                )
            ).scalar_one()
            if exec_a_2 is not None
            else -1
        )
        record("workflow_a_skip_has_no_steps", skipped_steps == 0, f"steps={skipped_steps}")

        # ── simple flow keeps executing on subsequent events too ────────────
        simple_exec_count_2 = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant.id,
                    TenantAutomationExecution.trigger_event == "tenant.content.publish_failed",
                    TenantAutomationExecution.status == "success",
                ),
            )
        ).scalar_one()
        record(
            "simple_flow_still_executes",
            int(simple_exec_count_2) > int(simple_exec_count_1),
            f"count={simple_exec_count_2}",
        )

    print(f"\n{len(failures)} FAILED" if failures else "\nAll Workflow Execution checks PASSED")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
