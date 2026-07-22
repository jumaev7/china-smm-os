"""Durable measurement collection jobs — separate from automation_flow jobs.

Reuses lease/retry conventions conceptually without coupling to
``automation_flow_id``. Measurement worker failures never affect publishing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import TenantExternalPublication, TenantMeasurementJob
from app.models.publishing_account import PublishingAccount
from app.services.measurement.providers.base import DISCONNECTED_ACCOUNT_STATUSES

LEASE_SECONDS = 120
DEFAULT_MAX_ATTEMPTS = 5


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe_key(publication_id: UUID, cadence_key: str | None) -> str:
    return f"metrics_collect:{publication_id}:{cadence_key or 'default'}"


async def schedule_collection_job(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    publication: TenantExternalPublication,
    available_at: datetime | None = None,
    cadence_key: str | None = None,
    priority: int = 100,
) -> TenantMeasurementJob:
    """Idempotent schedule — upserts by (tenant_id, deduplication_key)."""
    key = _dedupe_key(publication.id, cadence_key)
    existing = (
        await db.execute(
            select(TenantMeasurementJob).where(
                TenantMeasurementJob.tenant_id == tenant_id,
                TenantMeasurementJob.deduplication_key == key,
            )
        )
    ).scalar_one_or_none()

    when = available_at or utcnow()
    if existing is not None:
        if existing.status in {"scheduled", "paused", "failed"}:
            existing.status = "scheduled"
            existing.available_at = when
            existing.cadence_key = cadence_key
            existing.priority = priority
            existing.last_error_code = None
            existing.last_error_metadata = None
            await db.flush()
        return existing

    job = TenantMeasurementJob(
        id=uuid4(),
        tenant_id=tenant_id,
        external_publication_id=publication.id,
        publishing_account_id=publication.publishing_account_id,
        platform=publication.platform,
        job_kind="metrics_collect",
        status="scheduled",
        priority=priority,
        available_at=when,
        attempt_number=0,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
        deduplication_key=key,
        cadence_key=cadence_key,
    )
    db.add(job)
    await db.flush()
    return job


async def pause_jobs_for_disconnected_account(
    db: AsyncSession,
    tenant_id: UUID,
    publishing_account_id: UUID,
) -> int:
    result = await db.execute(
        update(TenantMeasurementJob)
        .where(
            TenantMeasurementJob.tenant_id == tenant_id,
            TenantMeasurementJob.publishing_account_id == publishing_account_id,
            TenantMeasurementJob.status.in_(["scheduled", "failed"]),
        )
        .values(status="paused", last_error_code="account_disconnected")
    )
    await db.flush()
    return int(result.rowcount or 0)


async def claim_jobs(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int = 10,
    now: datetime | None = None,
) -> list[TenantMeasurementJob]:
    """Lease due jobs. Expired leases are reclaimable."""
    reference = now or utcnow()
    lease_until = reference + timedelta(seconds=LEASE_SECONDS)

    candidates = list(
        (
            await db.execute(
                select(TenantMeasurementJob)
                .where(
                    TenantMeasurementJob.status.in_(["scheduled", "failed", "leased"]),
                    TenantMeasurementJob.available_at <= reference,
                    or_(
                        TenantMeasurementJob.lease_expires_at.is_(None),
                        TenantMeasurementJob.lease_expires_at < reference,
                        and_(
                            TenantMeasurementJob.status == "scheduled",
                            TenantMeasurementJob.lease_owner.is_(None),
                        ),
                    ),
                )
                .order_by(TenantMeasurementJob.priority.asc(), TenantMeasurementJob.available_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
    )

    claimed: list[TenantMeasurementJob] = []
    for job in candidates:
        # Pause if account disconnected.
        if job.publishing_account_id is not None:
            account = (
                await db.execute(
                    select(PublishingAccount).where(
                        PublishingAccount.id == job.publishing_account_id,
                        PublishingAccount.tenant_id == job.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if account is not None and account.status in DISCONNECTED_ACCOUNT_STATUSES:
                job.status = "paused"
                job.last_error_code = "account_disconnected"
                continue

        job.status = "leased"
        job.lease_owner = worker_id
        job.lease_expires_at = lease_until
        job.attempt_number = int(job.attempt_number or 0) + 1
        claimed.append(job)

    await db.flush()
    return claimed


async def mark_job_succeeded(db: AsyncSession, job: TenantMeasurementJob) -> None:
    job.status = "succeeded"
    job.completed_at = utcnow()
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error_code = None
    job.last_error_metadata = None
    await db.flush()


async def mark_job_failed(
    db: AsyncSession,
    job: TenantMeasurementJob,
    *,
    error_code: str,
    metadata: dict | None = None,
    retry_in: timedelta | None = None,
) -> None:
    if int(job.attempt_number or 0) >= int(job.max_attempts or DEFAULT_MAX_ATTEMPTS):
        job.status = "dead_letter"
        job.completed_at = utcnow()
    else:
        job.status = "failed"
        job.available_at = utcnow() + (retry_in or timedelta(minutes=15))
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error_code = error_code
    job.last_error_metadata = metadata
    await db.flush()


__all__ = [
    "schedule_collection_job",
    "pause_jobs_for_disconnected_account",
    "claim_jobs",
    "mark_job_succeeded",
    "mark_job_failed",
]
