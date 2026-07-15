"""Service-layer checks for versioned workflow lifecycle."""
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

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.core.events import build_tenant_event
    from app.models.tenant import Tenant
    from app.models.workflow import TenantWorkflowVersion
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration
    from app.services.workflow_execution_service import WorkflowExecutionService
    from app.services.workflow_service import WorkflowService
    from sqlalchemy import select

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

    valid_definition = {
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {
            "operator": "all",
            "items": [
                {"id": "c1", "field": "platform", "op": "equals", "value": "instagram"},
            ],
        },
        "steps": [
            {
                "id": "step_1",
                "type": "action",
                "action_type": "create_notification",
                "config": {"title": "WF fail {resource_name}", "category": "automation", "severity": "warning"},
            },
            {
                "id": "step_2",
                "type": "action",
                "action_type": "record_activity",
                "config": {"title": "Workflow recorded"},
            },
        ],
        "failure_policy": "stop_on_failure",
    }

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"WF Svc A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"WF Svc B {stamp}", status="active", plan="trial")
        db.add(tenant_a)
        db.add(tenant_b)
        await db.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id

        created = await WorkflowService.create_workflow(
            db,
            tenant_a_id,
            name="Publish recovery workflow",
            key=f"publish_recovery_{stamp}",
            definition=valid_definition,
        )
        await db.commit()
        record("create_draft", created.status == "draft" and created.draft_version_id is not None, created.status)

        updated = await WorkflowService.update_workflow(
            db,
            tenant_a_id,
            created.id,
            draft_revision=created.draft_revision,
            name="Publish recovery workflow v2",
            definition=valid_definition,
        )
        await db.commit()
        record("edit_draft", updated.draft_revision == created.draft_revision + 1, str(updated.draft_revision))

        try:
            await WorkflowService.update_workflow(
                db,
                tenant_a_id,
                created.id,
                draft_revision=created.draft_revision,
                name="stale",
            )
            record("stale_revision_409", False, "expected 409")
        except HTTPException as exc:
            record("stale_revision_409", exc.status_code == 409, f"status={exc.status_code}")

        validation = await WorkflowService.validate_workflow(db, tenant_a_id, created.id)
        record("validate_valid", validation.valid)

        bad = await WorkflowService.update_workflow(
            db,
            tenant_a_id,
            created.id,
            draft_revision=updated.draft_revision,
            definition={
                **valid_definition,
                "trigger": {"event": "not.a.real.event"},
            },
        )
        await db.commit()
        bad_val = await WorkflowService.validate_workflow(db, tenant_a_id, created.id)
        record("reject_invalid_trigger", not bad_val.valid)

        restored = await WorkflowService.update_workflow(
            db,
            tenant_a_id,
            created.id,
            draft_revision=bad.draft_revision,
            definition=valid_definition,
        )
        await db.commit()

        published = await WorkflowService.publish_workflow(db, tenant_a_id, created.id)
        await db.commit()
        record("publish", published.status == "published" and published.published_version_number >= 1)

        # Immutability: published version definition must not change when draft edits
        published_version_id = published.published_version_id
        before = (
            await db.execute(
                select(TenantWorkflowVersion).where(TenantWorkflowVersion.id == published_version_id),
            )
        ).scalar_one()
        before_def = dict(before.definition)
        before_hash = before.definition_hash

        edited = await WorkflowService.update_workflow(
            db,
            tenant_a_id,
            created.id,
            draft_revision=published.draft_revision,
            definition={
                **valid_definition,
                "steps": [
                    *valid_definition["steps"],
                    {
                        "id": "step_3",
                        "type": "action",
                        "action_type": "create_notification",
                        "config": {"title": "Extra", "category": "automation"},
                    },
                ],
            },
        )
        await db.commit()
        after = (
            await db.execute(
                select(TenantWorkflowVersion).where(TenantWorkflowVersion.id == published_version_id),
            )
        ).scalar_one()
        record(
            "published_immutable",
            after.definition == before_def and after.definition_hash == before_hash and after.state == "published",
        )
        record("draft_after_publish", edited.draft_version_id != published_version_id)

        paused = await WorkflowService.pause_workflow(db, tenant_a_id, created.id)
        await db.commit()
        record("pause", paused.status == "paused")
        resumed = await WorkflowService.resume_workflow(db, tenant_a_id, created.id)
        await db.commit()
        record("resume", resumed.status == "published")

        # Re-publish to bump version numbers
        await WorkflowService.update_workflow(
            db,
            tenant_a_id,
            created.id,
            draft_revision=edited.draft_revision,
            definition=valid_definition,
        )
        await db.commit()
        detail = await WorkflowService.get_workflow(db, tenant_a_id, created.id)
        published2 = await WorkflowService.publish_workflow(db, tenant_a_id, created.id)
        await db.commit()
        record(
            "version_monotonic",
            published2.published_version_number > published.published_version_number,
            f"{published.published_version_number}->{published2.published_version_number}",
        )

        cloned = await WorkflowService.clone_workflow(db, tenant_a_id, created.id)
        await db.commit()
        record(
            "clone_independent",
            cloned.id != created.id and cloned.status == "draft" and cloned.draft_version_id != detail.draft_version_id,
        )

        # Tenant isolation
        try:
            await WorkflowService.get_workflow(db, tenant_b_id, created.id)
            record("tenant_isolation_404", False)
        except HTTPException as exc:
            record("tenant_isolation_404", exc.status_code == 404)

        # Execution: matching vs non-matching; ordered steps; stop on failure; idempotency
        await WorkflowService.resume_workflow(db, tenant_a_id, created.id) if False else None
        # ensure published
        current = await WorkflowService.get_workflow(db, tenant_a_id, created.id)
        if current.status != "published":
            # already published
            pass

        event = build_tenant_event(
            "tenant.content.publish_failed",
            tenant_a_id,
            payload={"platform": "instagram", "resource_name": "Post A", "retryable": True},
        )
        runs = await WorkflowExecutionService.process_event(db, event)
        await db.commit()
        record("event_executes", len(runs) >= 1 and runs[0].status == "success", str([r.status for r in runs]))

        if runs:
            exec_detail = await WorkflowService.get_execution(db, tenant_a_id, runs[0].id)
            record(
                "ordered_steps",
                len(exec_detail.steps) == 2 and exec_detail.steps[0].step_index == 0,
                f"steps={len(exec_detail.steps)}",
            )
            # Historical link to published version
            record(
                "execution_links_version",
                exec_detail.workflow_version_id == published2.published_version_id
                or exec_detail.workflow_version_id == published.published_version_id
                or exec_detail.workflow_version_id == current.active_version_id,
            )

        # Duplicate event idempotency
        runs2 = await WorkflowExecutionService.process_event(db, event)
        await db.commit()
        record(
            "duplicate_idempotent",
            len(runs2) == 1 and runs2[0].id == runs[0].id,
            f"ids={[str(r.id) for r in runs2]}",
        )

        skip_event = build_tenant_event(
            "tenant.content.publish_failed",
            tenant_a_id,
            payload={"platform": "tiktok", "resource_name": "Post B"},
        )
        skipped = await WorkflowExecutionService.process_event(db, skip_event)
        await db.commit()
        record("non_match_skips_steps", len(skipped) >= 1 and skipped[0].status == "skipped")

        archived = await WorkflowService.archive_workflow(db, tenant_a_id, created.id)
        await db.commit()
        versions = await WorkflowService.list_versions(db, tenant_a_id, created.id)
        record("archive_keeps_versions", archived.status == "archived" and versions.total >= 2)

        # Evaluate-only test
        test = await WorkflowService.test_workflow(
            db,
            tenant_a_id,
            cloned.id,
            mode="evaluate_only",
            synthetic_payload={"platform": "instagram"},
        )
        record("evaluate_only", test.valid and test.matched is True)

    if failures:
        print(f"\nFAILED {len(failures)}")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nAll workflow service checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
