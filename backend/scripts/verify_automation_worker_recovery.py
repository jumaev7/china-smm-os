"""Prove durable retry survives restarts and multi-worker lease exclusivity."""
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
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.models.automation import TenantAutomationExecution, TenantAutomationFlow, TenantAutomationJob
    from app.models.client import Client
    from app.models.tenant import Tenant
    from app.services.automation_job_service import AutomationJobService
    from app.services.automation_scheduler_service import AutomationSchedulerService
    from app.services.automation_service import AutomationService
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.workers.automation_scheduler_worker import AutomationSchedulerWorker

    await ensure_platform_event_bus_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    stamp = int(datetime.now(timezone.utc).timestamp())
    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"Worker Rec {stamp}", status="active", plan="trial")
        client = Client(
            id=uuid4(),
            tenant_id=tenant.id,
            company_name=tenant.company_name,
            source_language="en",
            business_category="manufacturing",
        )
        db.add(tenant)
        await db.commit()
        db.add(client)
        await db.commit()
        tenant_id = tenant.id

        await AutomationService.ensure_system_flows(db, tenant_id)
        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.tenant_id == tenant_id,
                    TenantAutomationFlow.key == "system_publish_failed_notify",
                ),
            )
        ).scalar_one()
        flow.max_retry_attempts = 2
        flow.retry_delay_seconds = 1
        flow.retry_backoff = "fixed"
        await db.commit()

        failed = TenantAutomationExecution(
            id=uuid4(),
            tenant_id=tenant_id,
            automation_flow_id=flow.id,
            event_id=uuid4(),
            trigger_event=flow.trigger_event,
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=1,
            input_payload={"resource_name": "Durable widget"},
            execution_kind="event",
            deduplication_key=f"event:{uuid4()}",
            retry_number=0,
            attempt_number=1,
            error_code="execution_error",
            error_message="simulated",
            error_category="internal",
            is_retryable=True,
        )
        failed.root_execution_id = failed.id
        db.add(failed)
        await db.commit()

        job = await AutomationJobService.enqueue_automatic_retry(db, execution=failed, flow=flow)
        await db.commit()
        record("job_scheduled_before_restart", job is not None and job.status == "scheduled")
        job_id = job.id
        failed_id = failed.id
        flow_id = flow.id

    # Simulate API/worker process restart: new sessions only; job must persist.
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == job_id))
        ).scalar_one_or_none()
        record("job_survives_restart", row is not None and row.status == "scheduled", str(getattr(row, "status", None)))
        if row:
            row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            row.scheduled_for = row.available_at
            await db.commit()

    worker = AutomationSchedulerWorker(worker_id="recovery-worker-a", poll_seconds=0.1, batch_size=5)
    summary = await worker.run_once()
    record("worker_processed_after_restart", summary.get("processed", 0) >= 1, str(summary))

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == job_id))
        ).scalar_one()
        record(
            "job_terminal_after_worker",
            row.status in {"succeeded", "failed", "dead_letter"},
            row.status,
        )
        retries = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.root_execution_id == failed_id,
                    TenantAutomationExecution.execution_kind == "retry",
                ),
            )
        ).scalar_one()
        record("one_retry_execution", int(retries) == 1, f"count={retries}")

        flow = (
            await db.execute(select(TenantAutomationFlow).where(TenantAutomationFlow.id == flow_id))
        ).scalar_one()

        # Crash after lease: claim then abandon (no process), recover, second worker executes once.
        failed2 = TenantAutomationExecution(
            id=uuid4(),
            tenant_id=tenant_id,
            automation_flow_id=flow.id,
            event_id=uuid4(),
            trigger_event=flow.trigger_event,
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=1,
            input_payload={"resource_name": "Crash widget"},
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
        job2 = await AutomationJobService.enqueue_automatic_retry(db, execution=failed2, flow=flow)
        await db.commit()
        assert job2 is not None
        job2.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

        claimed = await AutomationSchedulerService.claim_due_jobs(
            db, worker_id="crashed-worker", batch_size=5, lease_seconds=30,
        )
        await db.commit()
        record("crash_claim", any(c.id == job2.id for c in claimed))
        # Expire lease
        row2 = (
            await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == job2.id))
        ).scalar_one()
        row2.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        await db.commit()

    recovery_worker = AutomationSchedulerWorker(worker_id="recovery-worker-b", poll_seconds=0.1)
    summary2 = await recovery_worker.run_once()
    record("recovered_and_processed", summary2.get("processed", 0) >= 1 or summary2.get("recovery", {}).get("recovered", 0) >= 1, str(summary2))
    # May need second tick if recovery returned to scheduled without processing same tick after claim in same run_once — claim_batch recovers then claims.
    async with AsyncSessionLocal() as db:
        row2 = (
            await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == job2.id))
        ).scalar_one()
        if row2.status == "scheduled":
            row2.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
    if row2.status not in {"succeeded", "failed", "dead_letter"}:
        await recovery_worker.run_once()
    async with AsyncSessionLocal() as db:
        row2 = (
            await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == job2.id))
        ).scalar_one()
        record("crash_recovered_terminal", row2.status in {"succeeded", "failed", "dead_letter"}, row2.status)
        retries2 = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.root_execution_id == failed2.id,
                    TenantAutomationExecution.execution_kind == "retry",
                ),
            )
        ).scalar_one()
        record("crash_no_duplicate_retry", int(retries2) == 1, f"count={retries2}")

        # Multi-worker concurrency: two due jobs, two workers
        jobs = []
        roots = []
        for i in range(4):
            f = TenantAutomationExecution(
                id=uuid4(),
                tenant_id=tenant_id,
                automation_flow_id=flow.id,
                event_id=uuid4(),
                trigger_event=flow.trigger_event,
                status="failed",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=1,
                input_payload={"resource_name": f"Conc {i}"},
                execution_kind="event",
                deduplication_key=f"event:{uuid4()}",
                retry_number=0,
                attempt_number=1,
                error_code="execution_error",
                error_message="simulated",
                error_category="internal",
                is_retryable=True,
            )
            f.root_execution_id = f.id
            db.add(f)
            await db.flush()
            roots.append(f.id)
            j = await AutomationJobService.enqueue_automatic_retry(db, execution=f, flow=flow)
            assert j is not None
            j.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            jobs.append(j.id)
        await db.commit()

    async def worker_tick(wid: str) -> dict:
        w = AutomationSchedulerWorker(worker_id=wid, batch_size=2)
        return await w.run_once()

    results = await asyncio.gather(worker_tick("mw-1"), worker_tick("mw-2"))
    total_processed = sum(int(r.get("processed") or 0) for r in results)
    record("multi_worker_processed", total_processed >= 2, f"processed={total_processed} results={results}")

    # Drain remaining
    await AutomationSchedulerWorker(worker_id="mw-drain", batch_size=10).run_once()

    async with AsyncSessionLocal() as db:
        owners = []
        for jid in jobs:
            j = (await db.execute(select(TenantAutomationJob).where(TenantAutomationJob.id == jid))).scalar_one()
            record(f"job_{jid}_not_stuck", j.status not in {"leased", "running"}, j.status)
            retries = (
                await db.execute(
                    select(func.count())
                    .select_from(TenantAutomationExecution)
                    .where(
                        TenantAutomationExecution.root_execution_id == j.root_execution_id,
                        TenantAutomationExecution.execution_kind == "retry",
                    ),
                )
            ).scalar_one()
            record(f"job_{jid}_single_retry", int(retries) <= 1, f"count={retries}")
            owners.append(j.lease_owner)

        # No active lease leftover
        leased = (
            await db.execute(
                select(func.count())
                .select_from(TenantAutomationJob)
                .where(
                    TenantAutomationJob.tenant_id == tenant_id,
                    TenantAutomationJob.status.in_(("leased", "running")),
                ),
            )
        ).scalar_one()
        record("no_stuck_leases", int(leased) == 0, f"leased={leased}")

    print("")
    if failures:
        print(f"FAILED {len(failures)} checks")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
