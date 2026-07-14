"""Durable automation job enqueue, listing, cancel, and requeue."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import (
    AUTOMATION_JOB_STATUSES,
    TenantAutomationExecution,
    TenantAutomationFlow,
    TenantAutomationJob,
)
from app.schemas.automation import (
    AutomationJobDetail,
    AutomationJobListResponse,
    AutomationJobSummary,
)
from app.services.automation_errors import (
    classify_automation_error,
    clamp_max_retry_attempts,
    safe_error_message,
    sanitize_payload_summary,
)
from app.services.automation_execution_service import AutomationExecutionService
from app.services.automation_retry_delay import compute_retry_schedule

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def retry_job_deduplication_key(root_execution_id: UUID, retry_number: int) -> str:
    return f"retry-job:{root_execution_id}:{retry_number}"


def requeue_job_deduplication_key(source_job_id: UUID, generation: int) -> str:
    return f"requeue-job:{source_job_id}:{generation}"


class AutomationJobService:
    """Tenant-scoped automation job persistence and mutations."""

    @staticmethod
    async def enqueue_automatic_retry(
        db: AsyncSession,
        *,
        execution: TenantAutomationExecution,
        flow: TenantAutomationFlow,
    ) -> TenantAutomationJob | None:
        """
        Enqueue one durable retry job after a failed retryable execution.

        Does nothing when ineligible. Duplicate keys return the existing job.
        """
        if execution.status != "failed":
            return None
        if flow.tenant_id != execution.tenant_id:
            return None
        if flow.status == "disabled":
            return None

        eligibility = await AutomationExecutionService.evaluate_retry_eligibility(
            db,
            tenant_id=execution.tenant_id,
            execution=execution,
            flow=flow,
        )
        if not eligibility["eligible"]:
            return None

        retry_number = int(eligibility["next_retry_number"])
        root_id = eligibility["root_execution_id"] or execution.root_execution_id or execution.id
        max_attempts = clamp_max_retry_attempts(flow.max_retry_attempts)
        scheduled_for, available_at, delay_seconds = compute_retry_schedule(
            retry_number=retry_number,
            base_delay_seconds=getattr(flow, "retry_delay_seconds", None),
            backoff=getattr(flow, "retry_backoff", None),
        )
        dedup = retry_job_deduplication_key(root_id, retry_number)

        existing = await AutomationJobService._existing_by_dedup(
            db, tenant_id=execution.tenant_id, deduplication_key=dedup,
        )
        if existing is not None:
            return existing

        row = TenantAutomationJob(
            id=uuid4(),
            tenant_id=execution.tenant_id,
            automation_flow_id=flow.id,
            execution_id=execution.id,
            root_execution_id=root_id,
            job_kind="automation_retry",
            status="scheduled",
            scheduled_for=scheduled_for,
            available_at=available_at,
            attempt_number=retry_number,
            max_attempts=max_attempts,
            priority=100,
            deduplication_key=dedup,
            payload={
                "retry_number": retry_number,
                "delay_seconds": delay_seconds,
                "source_execution_id": str(execution.id),
                "root_execution_id": str(root_id),
                "retry_backoff": getattr(flow, "retry_backoff", "fixed"),
                "retry_delay_seconds": getattr(flow, "retry_delay_seconds", 60),
            },
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            existing = await AutomationJobService._existing_by_dedup(
                db, tenant_id=execution.tenant_id, deduplication_key=dedup,
            )
            if existing is not None:
                return existing
            raise
        logger.info(
            "[AutomationJob] enqueued retry job=%s flow=%s root=%s attempt=%s delay=%ss",
            row.id,
            flow.key,
            root_id,
            retry_number,
            delay_seconds,
        )
        return row

    @staticmethod
    async def cancel_scheduled_jobs_for_flow(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        flow_id: UUID,
    ) -> int:
        """Cancel non-terminal scheduled jobs when a flow is disabled."""
        now = _utcnow()
        result = await db.execute(
            update(TenantAutomationJob)
            .where(
                TenantAutomationJob.tenant_id == tenant_id,
                TenantAutomationJob.automation_flow_id == flow_id,
                TenantAutomationJob.status == "scheduled",
            )
            .values(
                status="cancelled",
                finished_at=now,
                updated_at=now,
                error_code="flow_disabled",
                error_category="configuration",
                error_message="Flow disabled — scheduled retry cancelled",
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        await db.flush()
        return int(result.rowcount or 0)

    @staticmethod
    async def list_jobs(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        flow_id: UUID | None = None,
        status: str | None = None,
        root_execution_id: UUID | None = None,
    ) -> AutomationJobListResponse:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        offset = (page - 1) * page_size
        filters = [TenantAutomationJob.tenant_id == tenant_id]
        if flow_id is not None:
            filters.append(TenantAutomationJob.automation_flow_id == flow_id)
        if status:
            if status not in AUTOMATION_JOB_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid job status filter")
            filters.append(TenantAutomationJob.status == status)
        if root_execution_id is not None:
            filters.append(TenantAutomationJob.root_execution_id == root_execution_id)

        total = (
            await db.execute(
                select(func.count()).select_from(TenantAutomationJob).where(*filters),
            )
        ).scalar_one()
        rows = (
            await db.execute(
                select(TenantAutomationJob)
                .where(*filters)
                .order_by(TenantAutomationJob.created_at.desc(), TenantAutomationJob.id.desc())
                .offset(offset)
                .limit(page_size),
            )
        ).scalars().all()

        flow_ids = {r.automation_flow_id for r in rows}
        flow_names: dict[UUID, str] = {}
        if flow_ids:
            flows = (
                await db.execute(
                    select(TenantAutomationFlow.id, TenantAutomationFlow.name).where(
                        TenantAutomationFlow.tenant_id == tenant_id,
                        TenantAutomationFlow.id.in_(flow_ids),
                    ),
                )
            ).all()
            flow_names = {fid: name for fid, name in flows}

        items = [
            AutomationJobService._to_summary(row, flow_names.get(row.automation_flow_id))
            for row in rows
        ]
        pages = max(1, (int(total) + page_size - 1) // page_size) if int(total) else 1
        return AutomationJobListResponse(
            items=items,
            total=int(total),
            page=page,
            page_size=page_size,
            pages=pages,
        )

    @staticmethod
    async def get_job(
        db: AsyncSession,
        tenant_id: UUID,
        job_id: UUID,
    ) -> AutomationJobDetail:
        row = await AutomationJobService._load_job(db, tenant_id, job_id)
        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.id == row.automation_flow_id,
                    TenantAutomationFlow.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        summary = AutomationJobService._to_summary(row, flow.name if flow else None)
        return AutomationJobDetail(
            **summary.model_dump(),
            payload_summary=sanitize_payload_summary(row.payload),
            result_summary=sanitize_payload_summary(row.result_payload),
            lease_owner=None,  # never expose lease owner internals as secret; omit worker id
            lease_expires_at=row.lease_expires_at,
            lease_recovery_count=row.lease_recovery_count,
        )

    @staticmethod
    async def cancel_job(
        db: AsyncSession,
        tenant_id: UUID,
        job_id: UUID,
    ) -> AutomationJobDetail:
        row = await AutomationJobService._load_job(db, tenant_id, job_id)
        if row.status != "scheduled":
            raise HTTPException(
                status_code=409,
                detail="Only scheduled jobs can be cancelled",
            )
        now = _utcnow()
        row.status = "cancelled"
        row.finished_at = now
        row.updated_at = now
        row.error_code = "cancelled"
        row.error_category = "conflict"
        row.error_message = "Cancelled by operator"
        row.lease_owner = None
        row.lease_expires_at = None
        await db.flush()
        return await AutomationJobService.get_job(db, tenant_id, job_id)

    @staticmethod
    async def requeue_job(
        db: AsyncSession,
        tenant_id: UUID,
        job_id: UUID,
    ) -> AutomationJobDetail:
        """Requeue a failed/dead_letter job with a new server-generated dedup key."""
        source = await AutomationJobService._load_job(db, tenant_id, job_id)
        if source.status not in {"failed", "dead_letter"}:
            raise HTTPException(
                status_code=409,
                detail="Only failed or dead-letter jobs can be requeued",
            )

        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.id == source.automation_flow_id,
                    TenantAutomationFlow.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if flow is None:
            raise HTTPException(status_code=409, detail="Automation flow not found")
        if flow.status == "disabled":
            raise HTTPException(status_code=409, detail="Flow is disabled")
        if flow.status == "paused":
            raise HTTPException(status_code=409, detail="Flow is paused")

        generation = int((source.payload or {}).get("requeue_generation", 0) or 0) + 1
        dedup = requeue_job_deduplication_key(source.id, generation)
        now = _utcnow()
        # Operator requeue becomes due immediately; delay policy already applied originally.
        scheduled_for = now
        available_at = now
        row = TenantAutomationJob(
            id=uuid4(),
            tenant_id=tenant_id,
            automation_flow_id=source.automation_flow_id,
            execution_id=source.execution_id,
            root_execution_id=source.root_execution_id,
            job_kind="automation_retry",
            status="scheduled",
            scheduled_for=scheduled_for,
            available_at=available_at,
            attempt_number=source.attempt_number,
            max_attempts=source.max_attempts,
            priority=source.priority,
            deduplication_key=dedup,
            payload={
                **(source.payload or {}),
                "requeued_from_job_id": str(source.id),
                "requeue_generation": generation,
            },
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            existing = await AutomationJobService._existing_by_dedup(
                db, tenant_id=tenant_id, deduplication_key=dedup,
            )
            if existing is not None:
                return await AutomationJobService.get_job(db, tenant_id, existing.id)
            raise
        return await AutomationJobService.get_job(db, tenant_id, row.id)

    @staticmethod
    async def mark_dead_letter(
        db: AsyncSession,
        job: TenantAutomationJob,
        *,
        error_code: str,
        error_message: str,
        notify: bool = True,
    ) -> TenantAutomationJob:
        category, _ = classify_automation_error(error_code, error_message)
        now = _utcnow()
        job.status = "dead_letter"
        job.finished_at = now
        job.updated_at = now
        job.error_code = error_code
        job.error_category = category
        job.error_message = safe_error_message(error_message)
        job.lease_owner = None
        job.lease_expires_at = None
        await db.flush()
        if notify:
            await AutomationJobService._notify_dead_letter_once(db, job)
        return job

    @staticmethod
    async def _notify_dead_letter_once(db: AsyncSession, job: TenantAutomationJob) -> None:
        """Insert one tenant notification per dead-letter job without emitting events."""
        from app.models.platform_event import TenantEventNotification

        existing = (
            await db.execute(
                select(TenantEventNotification.id).where(
                    TenantEventNotification.tenant_id == job.tenant_id,
                    TenantEventNotification.resource_type == "automation_job",
                    TenantEventNotification.resource_id == str(job.id),
                    TenantEventNotification.event_type == "tenant.automation.job_dead_letter",
                ).limit(1),
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        row = TenantEventNotification(
            id=uuid4(),
            tenant_id=job.tenant_id,
            event_id=job.id,
            event_type="tenant.automation.job_dead_letter",
            category="automation",
            title="Automation retry exhausted",
            body=safe_error_message(
                job.error_message or "A scheduled automation retry entered dead-letter.",
            ),
            severity="warning",
            action_url="/automation",
            resource_type="automation_job",
            resource_id=str(job.id),
            payload={
                "job_id": str(job.id),
                "flow_id": str(job.automation_flow_id),
                "error_code": job.error_code,
            },
            status="unread",
        )
        db.add(row)
        await db.flush()

    @staticmethod
    async def _existing_by_dedup(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        deduplication_key: str,
    ) -> TenantAutomationJob | None:
        return (
            await db.execute(
                select(TenantAutomationJob).where(
                    TenantAutomationJob.tenant_id == tenant_id,
                    TenantAutomationJob.deduplication_key == deduplication_key,
                ),
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _load_job(
        db: AsyncSession,
        tenant_id: UUID,
        job_id: UUID,
    ) -> TenantAutomationJob:
        row = (
            await db.execute(
                select(TenantAutomationJob).where(
                    TenantAutomationJob.id == job_id,
                    TenantAutomationJob.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Automation job not found")
        return row

    @staticmethod
    def _to_summary(row: TenantAutomationJob, flow_name: str | None) -> AutomationJobSummary:
        return AutomationJobSummary(
            id=row.id,
            automation_flow_id=row.automation_flow_id,
            automation_name=flow_name,
            execution_id=row.execution_id,
            root_execution_id=row.root_execution_id,
            job_kind=row.job_kind,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            scheduled_for=row.scheduled_for,
            available_at=row.available_at,
            attempt_number=row.attempt_number,
            max_attempts=row.max_attempts,
            priority=row.priority,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error_code=row.error_code,
            error_category=row.error_category,  # type: ignore[arg-type]
            error_message=safe_error_message(row.error_message),
            created_at=row.created_at,
            updated_at=row.updated_at,
            can_cancel=row.status == "scheduled",
            can_requeue=row.status in {"failed", "dead_letter"},
        )
