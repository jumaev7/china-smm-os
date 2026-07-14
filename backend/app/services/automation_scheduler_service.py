"""PostgreSQL-backed automation job leasing, recovery, and execution."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import (
    DEFAULT_SCHEDULER_BATCH_SIZE,
    DEFAULT_SCHEDULER_LEASE_SECONDS,
    MAX_LEASE_RECOVERIES,
    MAX_SCHEDULER_LEASE_SECONDS,
    TenantAutomationExecution,
    TenantAutomationFlow,
    TenantAutomationJob,
)
from app.services.automation_errors import (
    action_type_allowed,
    safe_error_message,
)
from app.services.automation_execution_service import (
    AutomationExecutionService,
    retry_deduplication_key,
)
from app.services.automation_job_service import AutomationJobService

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutomationSchedulerService:
    """
    Claim due jobs with FOR UPDATE SKIP LOCKED, execute under lease ownership,
    and recover expired leases without holding row locks during action work.
    """

    @staticmethod
    async def claim_due_jobs(
        db: AsyncSession,
        *,
        worker_id: str,
        batch_size: int = DEFAULT_SCHEDULER_BATCH_SIZE,
        lease_seconds: int = DEFAULT_SCHEDULER_LEASE_SECONDS,
    ) -> list[TenantAutomationJob]:
        now = _utcnow()
        lease_seconds = max(30, min(int(lease_seconds), MAX_SCHEDULER_LEASE_SECONDS))
        batch_size = max(1, min(int(batch_size), 50))
        lease_until = now + timedelta(seconds=lease_seconds)

        # Short transaction pattern: lock + update, then return rows (no long work here).
        result = await db.execute(
            text(
                """
                WITH due AS (
                    SELECT j.id
                    FROM tenant_automation_jobs j
                    INNER JOIN tenant_automation_flows f
                        ON f.id = j.automation_flow_id
                       AND f.tenant_id = j.tenant_id
                    WHERE j.status = 'scheduled'
                      AND j.available_at <= :now
                      AND f.status = 'enabled'
                    ORDER BY j.priority DESC, j.available_at ASC
                    FOR UPDATE OF j SKIP LOCKED
                    LIMIT :batch_size
                )
                UPDATE tenant_automation_jobs AS jobs
                SET status = 'leased',
                    lease_owner = :worker_id,
                    lease_expires_at = :lease_until,
                    last_heartbeat_at = :now,
                    updated_at = :now
                FROM due
                WHERE jobs.id = due.id
                RETURNING jobs.id
                """
            ),
            {
                "now": now,
                "batch_size": batch_size,
                "worker_id": worker_id,
                "lease_until": lease_until,
            },
        )
        claimed_ids = [row[0] for row in result.fetchall()]
        await db.flush()
        if not claimed_ids:
            return []

        rows = (
            await db.execute(
                select(TenantAutomationJob)
                .where(TenantAutomationJob.id.in_(claimed_ids))
                .execution_options(populate_existing=True),
            )
        ).scalars().all()
        # Preserve claim order.
        by_id = {r.id: r for r in rows}
        return [by_id[i] for i in claimed_ids if i in by_id]

    @staticmethod
    async def recover_expired_leases(
        db: AsyncSession,
        *,
        limit: int = 50,
    ) -> dict[str, int]:
        """Return expired leased/running jobs to scheduled or dead_letter."""
        now = _utcnow()
        result = await db.execute(
            text(
                """
                SELECT id
                FROM tenant_automation_jobs
                WHERE status IN ('leased', 'running')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < :now
                ORDER BY lease_expires_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT :limit
                """
            ),
            {"now": now, "limit": max(1, min(int(limit), 200))},
        )
        ids = [row[0] for row in result.fetchall()]
        await db.flush()
        recovered = 0
        dead_lettered = 0
        for job_id in ids:
            job = (
                await db.execute(
                    select(TenantAutomationJob)
                    .where(TenantAutomationJob.id == job_id)
                    .execution_options(populate_existing=True),
                )
            ).scalar_one_or_none()
            if job is None:
                continue
            if job.status in {"succeeded", "failed", "dead_letter", "cancelled"}:
                continue
            next_count = int(job.lease_recovery_count or 0) + 1
            job.lease_recovery_count = next_count
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_heartbeat_at = now
            job.updated_at = now
            if next_count > MAX_LEASE_RECOVERIES:
                await AutomationJobService.mark_dead_letter(
                    db,
                    job,
                    error_code="lease_recovery_exceeded",
                    error_message=f"Lease recovery exceeded ({MAX_LEASE_RECOVERIES})",
                )
                dead_lettered += 1
            else:
                job.status = "scheduled"
                job.available_at = now
                job.started_at = None
                recovered += 1
                await db.flush()
        return {"recovered": recovered, "dead_lettered": dead_lettered, "inspected": len(ids)}

    @staticmethod
    async def heartbeat(
        db: AsyncSession,
        *,
        job_id: UUID,
        worker_id: str,
        lease_seconds: int = DEFAULT_SCHEDULER_LEASE_SECONDS,
    ) -> bool:
        now = _utcnow()
        lease_seconds = max(30, min(int(lease_seconds), MAX_SCHEDULER_LEASE_SECONDS))
        result = await db.execute(
            update(TenantAutomationJob)
            .where(
                TenantAutomationJob.id == job_id,
                TenantAutomationJob.lease_owner == worker_id,
                TenantAutomationJob.status.in_(("leased", "running")),
            )
            .values(
                last_heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
        )
        await db.flush()
        return int(result.rowcount or 0) > 0

    @staticmethod
    async def process_job(
        db: AsyncSession,
        *,
        job_id: UUID,
        worker_id: str,
    ) -> TenantAutomationJob:
        """Execute a leased job under explicit lease ownership."""
        job = (
            await db.execute(
                select(TenantAutomationJob)
                .where(TenantAutomationJob.id == job_id)
                .execution_options(populate_existing=True),
            )
        ).scalar_one_or_none()
        if job is None:
            raise ValueError("Job not found")
        if job.lease_owner != worker_id or job.status not in {"leased", "running"}:
            raise ValueError("Lease ownership required")

        now = _utcnow()
        job.status = "running"
        job.started_at = job.started_at or now
        job.last_heartbeat_at = now
        job.updated_at = now
        await db.flush()

        try:
            outcome = await AutomationSchedulerService._execute_automation_retry(db, job)
        except Exception as exc:
            logger.exception("[AutomationScheduler] job %s failed", job.id)
            job.status = "failed"
            job.finished_at = _utcnow()
            job.updated_at = job.finished_at
            job.error_code = "scheduler_error"
            job.error_category = "internal"
            job.error_message = safe_error_message(str(exc))
            job.lease_owner = None
            job.lease_expires_at = None
            await db.flush()
            return job

        return outcome

    @staticmethod
    async def _execute_automation_retry(
        db: AsyncSession,
        job: TenantAutomationJob,
    ) -> TenantAutomationJob:
        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.id == job.automation_flow_id,
                    TenantAutomationFlow.tenant_id == job.tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if flow is None:
            return await AutomationJobService.mark_dead_letter(
                db,
                job,
                error_code="flow_missing",
                error_message="Automation flow no longer exists",
            )
        if flow.status == "disabled":
            now = _utcnow()
            job.status = "cancelled"
            job.finished_at = now
            job.updated_at = now
            job.error_code = "flow_disabled"
            job.error_category = "configuration"
            job.error_message = "Flow disabled"
            job.lease_owner = None
            job.lease_expires_at = None
            await db.flush()
            return job
        if flow.status == "paused":
            # Return to scheduled without consuming attempts.
            now = _utcnow()
            job.status = "scheduled"
            job.lease_owner = None
            job.lease_expires_at = None
            job.started_at = None
            job.updated_at = now
            # Keep available_at as-is so it becomes due again once enabled.
            await db.flush()
            return job
        if not action_type_allowed(flow.action_type):
            return await AutomationJobService.mark_dead_letter(
                db,
                job,
                error_code="unknown_action",
                error_message="Action type is not allowlisted",
            )

        source_execution_id = job.execution_id
        if source_execution_id is None:
            return await AutomationJobService.mark_dead_letter(
                db,
                job,
                error_code="execution_missing",
                error_message="Source execution missing",
            )
        failed = (
            await db.execute(
                select(TenantAutomationExecution).where(
                    TenantAutomationExecution.id == source_execution_id,
                    TenantAutomationExecution.tenant_id == job.tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if failed is None:
            return await AutomationJobService.mark_dead_letter(
                db,
                job,
                error_code="execution_missing",
                error_message="Source execution no longer exists",
            )

        # If a requeued job points at a non-failed leaf, try to find the latest failed
        # under the same root that is still eligible.
        if failed.status != "failed":
            root_id = job.root_execution_id or failed.root_execution_id or failed.id
            latest_failed = (
                await db.execute(
                    select(TenantAutomationExecution)
                    .where(
                        TenantAutomationExecution.tenant_id == job.tenant_id,
                        TenantAutomationExecution.root_execution_id == root_id,
                        TenantAutomationExecution.status == "failed",
                    )
                    .order_by(TenantAutomationExecution.created_at.desc())
                    .limit(1),
                )
            ).scalar_one_or_none()
            if latest_failed is None:
                return await AutomationJobService.mark_dead_letter(
                    db,
                    job,
                    error_code="execution_not_failed",
                    error_message="No failed execution available for retry",
                )
            failed = latest_failed

        eligibility = await AutomationExecutionService.evaluate_retry_eligibility(
            db,
            tenant_id=job.tenant_id,
            execution=failed,
            flow=flow,
        )
        # Prefer the execution this job was scheduled for (idempotent delivery).
        root_id = job.root_execution_id or failed.root_execution_id or failed.id
        expected_key = retry_deduplication_key(root_id, int(job.attempt_number))
        existing_retry = await AutomationExecutionService._existing_by_dedup(
            db,
            tenant_id=job.tenant_id,
            flow_id=flow.id,
            deduplication_key=expected_key,
        )
        if existing_retry is not None:
            retry_row = existing_retry
        else:
            if not eligibility["eligible"]:
                reason = eligibility["reason"] or "Retry not eligible"
                if "limit" in reason.lower() or "not retryable" in reason.lower():
                    return await AutomationJobService.mark_dead_letter(
                        db,
                        job,
                        error_code="retry_limit" if "limit" in reason.lower() else "non_retryable",
                        error_message=reason,
                    )
                now = _utcnow()
                job.status = "failed"
                job.finished_at = now
                job.updated_at = now
                job.error_code = "not_eligible"
                job.error_category = "conflict"
                job.error_message = safe_error_message(reason)
                job.lease_owner = None
                job.lease_expires_at = None
                await db.flush()
                return job

            try:
                retry_row = await AutomationExecutionService.retry_execution(
                    db,
                    job.tenant_id,
                    failed,
                    flow,
                )
            except ValueError as exc:
                return await AutomationJobService.mark_dead_letter(
                    db,
                    job,
                    error_code="retry_rejected",
                    error_message=str(exc),
                )

        now = _utcnow()
        job.result_payload = {
            "execution_id": str(retry_row.id),
            "execution_status": retry_row.status,
            "retry_number": retry_row.retry_number,
        }
        job.lease_owner = None
        job.lease_expires_at = None
        job.finished_at = now
        job.updated_at = now

        if retry_row.status == "success":
            job.status = "succeeded"
            job.error_code = None
            job.error_category = None
            job.error_message = None
            await db.flush()
            return job

        # Retry execution itself failed — mark job failed; next automatic job may enqueue.
        job.status = "failed"
        job.error_code = retry_row.error_code or "execution_error"
        job.error_category = retry_row.error_category
        job.error_message = safe_error_message(retry_row.error_message)
        await db.flush()

        # Next durable retry is enqueued from execution finalize when retryable.
        # If non-retryable and no further schedule, dead-letter this job.
        if retry_row.status == "failed" and not retry_row.is_retryable:
            await AutomationJobService.mark_dead_letter(
                db,
                job,
                error_code=retry_row.error_code or "retry_exhausted",
                error_message=retry_row.error_message or "Retry failed permanently",
            )
        return job

    @staticmethod
    async def claim_batch(
        db: AsyncSession,
        *,
        worker_id: str,
        batch_size: int = DEFAULT_SCHEDULER_BATCH_SIZE,
        lease_seconds: int = DEFAULT_SCHEDULER_LEASE_SECONDS,
    ) -> tuple[list[UUID], dict[str, int]]:
        """Recover expired leases and claim due jobs. Caller must commit promptly."""
        recovery = await AutomationSchedulerService.recover_expired_leases(db)
        claimed = await AutomationSchedulerService.claim_due_jobs(
            db,
            worker_id=worker_id,
            batch_size=batch_size,
            lease_seconds=lease_seconds,
        )
        return [row.id for row in claimed], recovery
