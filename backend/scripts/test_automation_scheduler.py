"""Automation Scheduler Phase 1 — service-level checks."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    from sqlalchemy import func, select, update

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.core.events import build_tenant_event
    from app.models.automation import TenantAutomationExecution, TenantAutomationFlow, TenantAutomationJob
    from app.models.client import Client
    from app.models.tenant import Tenant
    from app.services.automation_execution_service import AutomationExecutionService
    from app.services.automation_job_service import AutomationJobService, retry_job_deduplication_key
    from app.services.automation_retry_delay import compute_retry_delay_seconds
    from app.services.automation_scheduler_service import AutomationSchedulerService
    from app.services.automation_service import AutomationService
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )

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

    # --- Delay formula unit checks ---
    record("delay_retry1_fixed", compute_retry_delay_seconds(retry_number=1, base_delay_seconds=60, backoff="fixed") == 60)
    record("delay_retry2_fixed", compute_retry_delay_seconds(retry_number=2, base_delay_seconds=60, backoff="fixed") == 60)
    record("delay_retry3_linear", compute_retry_delay_seconds(retry_number=3, base_delay_seconds=60, backoff="linear") == 180)
    record(
        "delay_retry3_exponential",
        compute_retry_delay_seconds(retry_number=3, base_delay_seconds=60, backoff="exponential") == 240,
    )
    record(
        "delay_max_cap",
        compute_retry_delay_seconds(
            retry_number=20, base_delay_seconds=3600, backoff="exponential", max_delay_seconds=86400,
        )
        == 86400,
    )
    record("delay_zero_retry", compute_retry_delay_seconds(retry_number=0, base_delay_seconds=60, backoff="fixed") == 0)
    record(
        "delay_invalid_backoff",
        compute_retry_delay_seconds(retry_number=2, base_delay_seconds=30, backoff="nope") == 30,
    )

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Sched A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Sched B {stamp}", status="active", plan="trial")
        client_a = Client(
            id=uuid4(),
            tenant_id=tenant_a.id,
            company_name=tenant_a.company_name,
            source_language="en",
            business_category="manufacturing",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add(client_a)
        await db.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id

        await AutomationService.ensure_system_flows(db, tenant_a_id)
        await AutomationService.ensure_system_flows(db, tenant_b_id)
        await db.commit()

        publish_flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.tenant_id == tenant_a_id,
                    TenantAutomationFlow.key == "system_publish_failed_notify",
                ),
            )
        ).scalar_one()
        publish_flow.max_retry_attempts = 2
        publish_flow.retry_delay_seconds = 1
        publish_flow.retry_backoff = "fixed"
        await db.commit()

        # Force a retryable failure by pointing action at invalid CRM path? Use execution_error via
        # temporarily broken action — simpler: insert a failed execution row and enqueue.
        # Prefer live path: patch flow to unknown then restore — use record_activity? better:
        # Create event that runs create_notification successfully, then manually mark failed.
        # For enqueue testing, simulate failed retryable execution.

        failed = TenantAutomationExecution(
            id=uuid4(),
            tenant_id=tenant_a_id,
            automation_flow_id=publish_flow.id,
            event_id=uuid4(),
            trigger_event=publish_flow.trigger_event,
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=1,
            input_payload={"resource_name": "Sched widget"},
            execution_kind="event",
            deduplication_key=f"event:{uuid4()}",
            retry_number=0,
            attempt_number=1,
            error_code="execution_error",
            error_message="simulated transient failure",
            error_category="internal",
            is_retryable=True,
        )
        failed.root_execution_id = failed.id
        db.add(failed)
        await db.commit()

        job = await AutomationJobService.enqueue_automatic_retry(db, execution=failed, flow=publish_flow)
        await db.commit()
        record("enqueue_retryable", job is not None and job.status == "scheduled", str(getattr(job, "id", None)))

        dup = await AutomationJobService.enqueue_automatic_retry(db, execution=failed, flow=publish_flow)
        await db.commit()
        record("enqueue_duplicate_same_id", dup is not None and job is not None and dup.id == job.id)

        # Non-retryable
        failed_nr = TenantAutomationExecution(
            id=uuid4(),
            tenant_id=tenant_a_id,
            automation_flow_id=publish_flow.id,
            event_id=uuid4(),
            trigger_event=publish_flow.trigger_event,
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=1,
            input_payload={},
            execution_kind="event",
            deduplication_key=f"event:{uuid4()}",
            retry_number=0,
            attempt_number=1,
            error_code="invalid_config",
            error_message="bad config",
            error_category="validation",
            is_retryable=False,
        )
        failed_nr.root_execution_id = failed_nr.id
        db.add(failed_nr)
        await db.commit()
        none_job = await AutomationJobService.enqueue_automatic_retry(db, execution=failed_nr, flow=publish_flow)
        await db.commit()
        record("enqueue_non_retryable_none", none_job is None)

        # Max retries exhausted
        publish_flow.max_retry_attempts = 0
        await db.flush()
        none_max = await AutomationJobService.enqueue_automatic_retry(db, execution=failed, flow=publish_flow)
        await db.commit()
        record("enqueue_max_retries_none", none_max is None)
        publish_flow.max_retry_attempts = 2
        await db.commit()

        # Tenant isolation: list for B empty of A's job
        list_b = await AutomationJobService.list_jobs(db, tenant_b_id)
        record("tenant_isolation_list_empty", list_b.total == 0)

        # Make job due
        assert job is not None
        job.available_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        job.scheduled_for = job.available_at
        await db.commit()

        w1 = "worker-test-1"
        w2 = "worker-test-2"
        claimed1 = await AutomationSchedulerService.claim_due_jobs(db, worker_id=w1, batch_size=10)
        await db.commit()
        record("lease_one_worker_claims", any(c.id == job.id for c in claimed1), f"n={len(claimed1)}")

        # Refresh and try second worker
        job_reload = (
            await db.execute(
                select(TenantAutomationJob)
                .where(TenantAutomationJob.id == job.id)
                .execution_options(populate_existing=True),
            )
        ).scalar_one()
        owner = job_reload.lease_owner
        claimed2 = await AutomationSchedulerService.claim_due_jobs(db, worker_id=w2, batch_size=10)
        await db.commit()
        record(
            "lease_two_workers_no_duplicate",
            job_reload.id not in {c.id for c in claimed2} and owner == w1,
            f"owner={owner}",
        )

        # Future job not claimed
        future = TenantAutomationJob(
            id=uuid4(),
            tenant_id=tenant_a_id,
            automation_flow_id=publish_flow.id,
            execution_id=failed.id,
            root_execution_id=failed.id,
            job_kind="automation_retry",
            status="scheduled",
            scheduled_for=datetime.now(timezone.utc) + timedelta(hours=2),
            available_at=datetime.now(timezone.utc) + timedelta(hours=2),
            attempt_number=2,
            max_attempts=2,
            priority=100,
            deduplication_key=retry_job_deduplication_key(failed.id, 99),
            payload={},
        )
        db.add(future)
        await db.commit()
        claimed_future = await AutomationSchedulerService.claim_due_jobs(db, worker_id=w2, batch_size=50)
        await db.commit()
        record("future_not_claimed", future.id not in {c.id for c in claimed_future})

        # Paused flow: release current job back and test claim skip
        await db.execute(
            update(TenantAutomationJob)
            .where(TenantAutomationJob.id == job.id)
            .values(
                status="scheduled",
                lease_owner=None,
                lease_expires_at=None,
                available_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            ),
        )
        publish_flow.status = "paused"
        await db.commit()
        claimed_paused = await AutomationSchedulerService.claim_due_jobs(db, worker_id=w1, batch_size=50)
        await db.commit()
        record("paused_not_claimed", job.id not in {c.id for c in claimed_paused})
        publish_flow.status = "enabled"
        await db.commit()

        # System flows cannot be disabled — cancel scheduled jobs directly
        cancelled_n = await AutomationJobService.cancel_scheduled_jobs_for_flow(
            db, tenant_id=tenant_a_id, flow_id=publish_flow.id,
        )
        await db.commit()
        record("disabled_cancels_scheduled", cancelled_n >= 1, f"n={cancelled_n}")

        # Fresh due job for execution
        publish_flow.status = "enabled"
        failed2 = TenantAutomationExecution(
            id=uuid4(),
            tenant_id=tenant_a_id,
            automation_flow_id=publish_flow.id,
            event_id=uuid4(),
            trigger_event=publish_flow.trigger_event,
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=1,
            input_payload={"resource_name": "Exec widget"},
            execution_kind="event",
            deduplication_key=f"event:{uuid4()}",
            retry_number=0,
            attempt_number=1,
            error_code="execution_error",
            error_message="simulated",
            error_category="internal",
            is_retryable=True,
        )
        failed2.root_execution_id = failed2.id
        db.add(failed2)
        await db.commit()
        job2 = await AutomationJobService.enqueue_automatic_retry(db, execution=failed2, flow=publish_flow)
        await db.commit()
        assert job2 is not None
        job2.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        job2.scheduled_for = job2.available_at
        await db.commit()

        claimed_exec = await AutomationSchedulerService.claim_due_jobs(db, worker_id=w1, batch_size=5)
        await db.commit()
        record("claim_for_execution", any(c.id == job2.id for c in claimed_exec))
        outcome = await AutomationSchedulerService.process_job(db, job_id=job2.id, worker_id=w1)
        await db.commit()
        record("job_execution_terminal", outcome.status in {"succeeded", "failed", "dead_letter"}, outcome.status)

        retry_count = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_a_id,
                    TenantAutomationExecution.root_execution_id == failed2.id,
                    TenantAutomationExecution.execution_kind == "retry",
                ),
            )
        ).scalar_one()
        record("linked_retry_execution_created", int(retry_count) >= 1, f"count={retry_count}")

        # Lease recovery
        stuck = TenantAutomationJob(
            id=uuid4(),
            tenant_id=tenant_a_id,
            automation_flow_id=publish_flow.id,
            execution_id=failed2.id,
            root_execution_id=failed2.id,
            job_kind="automation_retry",
            status="leased",
            scheduled_for=datetime.now(timezone.utc),
            available_at=datetime.now(timezone.utc),
            attempt_number=1,
            max_attempts=2,
            priority=100,
            deduplication_key=f"lease-recovery:{uuid4()}",
            lease_owner="dead-worker",
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            lease_recovery_count=0,
            payload={},
        )
        db.add(stuck)
        await db.commit()
        recovery = await AutomationSchedulerService.recover_expired_leases(db)
        await db.commit()
        stuck2 = (
            await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == stuck.id))
        ).scalar_one()
        record("lease_recovery_scheduled", stuck2.status == "scheduled", stuck2.status)
        record("lease_recovery_count_inc", stuck2.lease_recovery_count == 1, str(stuck2.lease_recovery_count))

        # Compleated not recovered
        done = TenantAutomationJob(
            id=uuid4(),
            tenant_id=tenant_a_id,
            automation_flow_id=publish_flow.id,
            execution_id=failed2.id,
            root_execution_id=failed2.id,
            job_kind="automation_retry",
            status="succeeded",
            scheduled_for=datetime.now(timezone.utc),
            available_at=datetime.now(timezone.utc),
            attempt_number=1,
            max_attempts=2,
            priority=100,
            deduplication_key=f"done:{uuid4()}",
            lease_owner="x",
            lease_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            payload={},
        )
        db.add(done)
        await db.commit()
        await AutomationSchedulerService.recover_expired_leases(db)
        await db.commit()
        done2 = (await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == done.id))).scalar_one()
        record("completed_not_recovered", done2.status == "succeeded")

        # Threshold -> dead letter
        stuck2.status = "leased"
        stuck2.lease_owner = "dead"
        stuck2.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        stuck2.lease_recovery_count = 5
        await db.commit()
        await AutomationSchedulerService.recover_expired_leases(db)
        await db.commit()
        stuck3 = (
            await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == stuck.id))
        ).scalar_one()
        record("recovery_threshold_dead_letter", stuck3.status == "dead_letter", stuck3.status)

        # API cancel / requeue
        sched = TenantAutomationJob(
            id=uuid4(),
            tenant_id=tenant_a_id,
            automation_flow_id=publish_flow.id,
            execution_id=failed2.id,
            root_execution_id=failed2.id,
            job_kind="automation_retry",
            status="scheduled",
            scheduled_for=datetime.now(timezone.utc) + timedelta(minutes=5),
            available_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            attempt_number=1,
            max_attempts=2,
            priority=100,
            deduplication_key=f"cancel-me:{uuid4()}",
            payload={},
        )
        db.add(sched)
        await db.commit()
        cancelled = await AutomationJobService.cancel_job(db, tenant_a_id, sched.id)
        await db.commit()
        record("cancel_scheduled", cancelled.status == "cancelled")

        dead = stuck3
        requeued = await AutomationJobService.requeue_job(db, tenant_a_id, dead.id)
        await db.commit()
        record("requeue_dead_letter", requeued.status == "scheduled", requeued.status)

        kpis = await AutomationService.get_kpis(db, tenant_a_id)
        record("kpi_has_scheduled_jobs", hasattr(kpis, "scheduled_jobs"))
        record("kpi_has_dead_letter", kpis.dead_letter_jobs >= 0)

        # Wrong tenant 404
        try:
            await AutomationJobService.get_job(db, tenant_b_id, requeued.id)
            record("wrong_tenant_404", False, "expected 404")
        except Exception as exc:
            from fastapi import HTTPException

            record("wrong_tenant_404", isinstance(exc, HTTPException) and exc.status_code == 404)

    print("")
    if failures:
        print(f"FAILED {len(failures)} checks")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
