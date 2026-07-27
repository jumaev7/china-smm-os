"""Live source sync orchestration — locks, credentials, checkpoints.

Provider calls happen only from this path (scheduled or manual sync).
Mention/analytics/review/Executive Copilot paths must not import or call this
for request-time provider fetches.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listening import (
    LIVE_SOURCE_TYPES,
    SOURCE_HEALTH_STATUSES,
    TenantListeningProject,
    TenantListeningSource,
)
from app.services.listening.errors import (
    ProjectArchivedError,
    ProjectNotFoundError,
    ProjectPausedError,
    SourceAlreadyRunningError,
    SourceNotFoundError,
    SourceUnsupportedError,
)
from app.services.listening.ingestion_service import ingest_observations
from app.services.listening.live_credentials import resolve_facebook_page_credentials
from app.services.listening.providers import get_adapter, is_live_source_type
from app.services.listening.providers.meta_errors import (
    MetaListeningError,
    public_failure_summary,
)
from app.services.listening.providers.meta_graph_read import PROVIDER_CAPABILITY_VERSION

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 900
MIN_POLL_INTERVAL_SECONDS = 300
MAX_POLL_INTERVAL_SECONDS = 86400
LOCK_LEASE_SECONDS = 180

_TOKEN_CONFIG_KEYS = frozenset({
    "_runtime_page_access_token",
    "access_token",
    "page_access_token",
    "user_access_token",
    "token",
})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clamp_poll_interval(seconds: int | None) -> int:
    value = int(seconds) if seconds is not None else DEFAULT_POLL_INTERVAL_SECONDS
    return max(MIN_POLL_INTERVAL_SECONDS, min(MAX_POLL_INTERVAL_SECONDS, value))


def scrub_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Persistable config only — never tokens."""
    return {
        k: v
        for k, v in (config or {}).items()
        if k not in _TOKEN_CONFIG_KEYS and not str(k).startswith("_runtime")
    }


async def _load_source(
    db: AsyncSession,
    tenant_id: UUID,
    source_id: UUID,
) -> TenantListeningSource:
    source = (
        await db.execute(
            select(TenantListeningSource).where(
                TenantListeningSource.id == source_id,
                TenantListeningSource.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise SourceNotFoundError("listening source not found")
    return source


async def try_acquire_source_lock(
    db: AsyncSession,
    source: TenantListeningSource,
    *,
    owner: str,
    now: datetime | None = None,
    commit: bool = False,
) -> bool:
    """Multi-worker-safe source lock via atomic conditional UPDATE.

    In-memory Python locks are insufficient across workers. This uses a
    database row lease comparable to the automation scheduler pattern.

    Lifecycle (must commit the lease before long provider work):
    1. Acquisition: UPDATE succeeds only when lock is free, expired/stale,
       or already owned by the same ``owner``.
    2. Owner / run identity: ``lock_owner`` (e.g. ``manual:<user>``,
       ``<worker>:<source_id>``, ``sync:<hex>``).
    3. Lease expiry: ``lock_expires_at`` = now + LOCK_LEASE_SECONDS.
    4. Worker crash after commit: lease remains until expiry; another worker
       may reclaim once ``lock_expires_at < now``.
    5. Stale-lock recovery: the WHERE clause treats expired leases as free.
    6. Release: UPDATE clears lock only when ``lock_owner`` matches the
       releasing run — one run cannot release another run's lock.
    7. Concurrent manual + scheduled: both call this path; exactly one wins
       the committed lease; the other gets already_running.
    8. Transaction boundaries: RETURNING alone is not enough — callers must
       ``commit=True`` (or commit promptly) so the persisted lease blocks
       other sessions after this transaction ends.
    """
    reference = now or utcnow()
    expires = reference + timedelta(seconds=LOCK_LEASE_SECONDS)
    result = await db.execute(
        text(
            """
            UPDATE tenant_listening_sources
            SET lock_owner = :owner,
                lock_expires_at = :expires,
                updated_at = :now
            WHERE id = :id
              AND tenant_id = :tenant_id
              AND (
                lock_owner IS NULL
                OR lock_expires_at IS NULL
                OR lock_expires_at < :now
                OR lock_owner = :owner
              )
            RETURNING id
            """
        ),
        {
            "owner": owner,
            "expires": expires,
            "now": reference,
            "id": source.id,
            "tenant_id": source.tenant_id,
        },
    )
    claimed = result.fetchone() is not None
    if not claimed:
        logger.info(
            "listening_source_lock_contention",
            extra={
                "tenant_id": str(source.tenant_id),
                "source_id": str(source.id),
                "source_type": source.source_type,
            },
        )
        return False
    source.lock_owner = owner
    source.lock_expires_at = expires
    await db.flush()
    if commit:
        # Persist lease before provider I/O so other workers observe it.
        await db.commit()
        try:
            await db.refresh(source)
        except Exception:  # noqa: BLE001
            pass
    return True


async def release_source_lock(
    db: AsyncSession,
    source: TenantListeningSource,
    *,
    owner: str,
    commit: bool = False,
) -> bool:
    """Release only if this owner still holds the lease. Returns True if released."""
    result = await db.execute(
        text(
            """
            UPDATE tenant_listening_sources
            SET lock_owner = NULL,
                lock_expires_at = NULL,
                updated_at = :now
            WHERE id = :id
              AND tenant_id = :tenant_id
              AND lock_owner = :owner
            """
        ),
        {
            "now": utcnow(),
            "id": source.id,
            "tenant_id": source.tenant_id,
            "owner": owner,
        },
    )
    released = int(result.rowcount or 0) > 0
    if released:
        source.lock_owner = None
        source.lock_expires_at = None
        await db.flush()
    if commit:
        await db.commit()
    return released


def _set_failure(
    source: TenantListeningSource,
    *,
    code: str,
    summary: str | None = None,
) -> None:
    # Normalize legacy alias.
    if code == "revoked_authorization":
        code = "token_expired_or_revoked"
    safe_code = code if code in SOURCE_HEALTH_STATUSES else "internal_processing_failure"
    source.health_status = safe_code
    source.last_failure_at = utcnow()
    source.last_failure_code = safe_code[:80]
    source.last_failure_summary = (summary or public_failure_summary(safe_code))[:500]
    if safe_code in {
        "token_expired_or_revoked",
        "revoked_authorization",
        "missing_scope",
        "missing_credentials",
        "insufficient_app_access",
        "page_not_authorized",
        "provider_unavailable",
        "unsupported_capability",
    }:
        source.freshness_status = "unavailable"


def _set_success(
    source: TenantListeningSource,
    *,
    fetched_count: int,
    checkpoint: str | None,
) -> None:
    source.health_status = "healthy_zero" if fetched_count == 0 else "healthy"
    source.last_failure_at = None
    source.last_failure_code = None
    source.last_failure_summary = None
    if checkpoint is not None:
        source.last_checkpoint = checkpoint[:1000]
    source.provider_capability_version = PROVIDER_CAPABILITY_VERSION


async def build_runtime_config(
    db: AsyncSession,
    source: TenantListeningSource,
) -> dict[str, Any]:
    """Build ephemeral runtime config including Page token.

    The token is in-memory only. Callers must never assign this dict to
    ``source.config_json``, checkpoints, runs, or provenance.
    """
    base = scrub_config(source.config_json)
    integration_id = source.integration_id
    if integration_id is None:
        raw = base.get("publishing_account_id") or base.get("integration_id")
        if raw:
            integration_id = UUID(str(raw))
    if integration_id is None:
        raise MetaListeningError(
            "invalid_configuration",
            public_failure_summary("invalid_configuration"),
            retryable=False,
        )

    expected_page = source.provider_resource_ref or base.get("provider_resource_ref")
    bundle = await resolve_facebook_page_credentials(
        db,
        tenant_id=source.tenant_id,
        publishing_account_id=integration_id,
        expected_page_id=str(expected_page) if expected_page else None,
    )
    runtime = {**base, **bundle.public_config_overlay()}
    runtime["_runtime_page_access_token"] = bundle.page_access_token
    # Keep model fields aligned without storing the token.
    source.integration_id = bundle.publishing_account_id
    source.provider_resource_ref = bundle.page_id
    source.config_json = scrub_config(runtime)
    return runtime


async def sync_live_source(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    source_id: UUID,
    trigger_type: str = "sync",
    created_by_user_id: UUID | None = None,
    lock_owner: str | None = None,
    allow_paused_project: bool = False,
) -> Any:
    """Run a read-only live sync for one source under an exclusive lease."""
    source = await _load_source(db, tenant_id, source_id)
    if not is_live_source_type(source.source_type):
        raise SourceUnsupportedError(
            f"source '{source.source_type}' is not a live provider adapter",
            details={"source_type": source.source_type},
        )
    if not source.is_enabled:
        _set_failure(source, code="disabled", summary="source is paused/disabled")
        await db.flush()
        raise SourceUnsupportedError("listening source is disabled")

    project = (
        await db.execute(
            select(TenantListeningProject).where(
                TenantListeningProject.id == source.project_id,
                TenantListeningProject.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise ProjectNotFoundError("listening project not found")
    if project.status == "archived":
        raise ProjectArchivedError("archived listening projects cannot sync")
    if project.status == "paused" and not allow_paused_project:
        raise ProjectPausedError("paused listening projects are not scheduled for sync")

    owner = lock_owner or f"sync:{uuid4().hex[:12]}"
    # Commit the lease immediately so concurrent sessions see the persisted lock
    # after this transaction ends (UPDATE RETURNING alone is not sufficient).
    if not await try_acquire_source_lock(db, source, owner=owner, commit=True):
        raise SourceAlreadyRunningError(
            "source sync already in progress",
            details={"error_code": "already_running", "source_id": str(source_id)},
        )

    try:
        adapter = get_adapter(source.source_type)
        try:
            runtime = await build_runtime_config(db, source)
        except MetaListeningError as exc:
            _set_failure(source, code=exc.code, summary=public_failure_summary(exc.code))
            await db.flush()
            raise SourceUnsupportedError(
                public_failure_summary(exc.code),
                details={"error_code": exc.code},
            ) from exc

        validation_errors = await adapter.validate_configuration(runtime)
        if validation_errors:
            code = (
                "missing_scope"
                if any("missing_scope" in e for e in validation_errors)
                else "invalid_configuration"
            )
            if any("integration_status:" in e for e in validation_errors):
                code = "token_expired_or_revoked"
            _set_failure(
                source,
                code=code,
                summary=public_failure_summary(code),
            )
            await db.flush()
            raise SourceUnsupportedError(
                public_failure_summary(code),
                details={"error_code": code, "validation_errors": validation_errors},
            )

        cursor = source.last_checkpoint
        # Token stays in runtime_config only — never written to source.config_json.
        run = await ingest_observations(
            db,
            tenant_id=tenant_id,
            project_id=source.project_id,
            source_type=source.source_type,
            trigger_type=trigger_type,
            source_id=source.id,
            cursor=cursor,
            created_by_user_id=created_by_user_id,
            allow_paused=allow_paused_project,
            runtime_config=runtime,
        )

        if run.status == "failed":
            code = (run.error_summary or "provider_unavailable").split(";")[0].strip()[:80]
            if code == "revoked_authorization":
                code = "token_expired_or_revoked"
            _set_failure(
                source,
                code=code if code in SOURCE_HEALTH_STATUSES else "provider_unavailable",
                summary=public_failure_summary(
                    code if code in SOURCE_HEALTH_STATUSES else "provider_unavailable"
                ),
            )
        else:
            advanced = bool((run.checkpoint_json or {}).get("advanced"))
            checkpoint = run.cursor_after if advanced else source.last_checkpoint
            _set_success(
                source,
                fetched_count=int(run.fetched_count or 0),
                checkpoint=checkpoint,
            )
            if advanced and run.cursor_after:
                source.last_checkpoint = run.cursor_after[:1000]
        await db.flush()
        return run
    finally:
        # Owner-matched release + commit so the lease does not outlive the run
        # unless the process crashed after acquire commit (then stale recovery).
        await release_source_lock(db, source, owner=owner, commit=True)


async def list_due_live_sources(
    db: AsyncSession,
    *,
    limit: int = 20,
    now: datetime | None = None,
) -> list[TenantListeningSource]:
    """Active projects + enabled live sources whose poll interval has elapsed."""
    reference = now or utcnow()
    rows = list(
        (
            await db.execute(
                select(TenantListeningSource)
                .join(
                    TenantListeningProject,
                    and_(
                        TenantListeningProject.id == TenantListeningSource.project_id,
                        TenantListeningProject.tenant_id == TenantListeningSource.tenant_id,
                    ),
                )
                .where(
                    TenantListeningSource.is_enabled.is_(True),
                    TenantListeningSource.source_type.in_(tuple(LIVE_SOURCE_TYPES)),
                    TenantListeningProject.status == "active",
                    or_(
                        TenantListeningSource.lock_expires_at.is_(None),
                        TenantListeningSource.lock_expires_at < reference,
                    ),
                )
                .order_by(TenantListeningSource.last_success_at.asc().nullsfirst())
                .limit(limit)
            )
        ).scalars().all()
    )
    due: list[TenantListeningSource] = []
    for source in rows:
        interval = clamp_poll_interval(source.poll_interval_seconds)
        last = source.last_success_at
        if last is None or (reference - last).total_seconds() >= interval:
            # Skip continuously polling revoked sources — wait longer.
            if source.health_status in {
                "token_expired_or_revoked",
                "revoked_authorization",
                "missing_scope",
                "insufficient_app_access",
                "page_not_authorized",
                "unsupported_capability",
            }:
                fail_at = source.last_failure_at
                if fail_at and (reference - fail_at).total_seconds() < max(interval, 3600):
                    continue
            due.append(source)
    return due


async def run_scheduled_live_sync_batch(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    sources = await list_due_live_sources(db, limit=limit)
    for source in sources:
        try:
            run = await sync_live_source(
                db,
                tenant_id=source.tenant_id,
                source_id=source.id,
                trigger_type="scheduled",
                lock_owner=f"{worker_id}:{source.id}",
            )
            results.append({
                "source_id": str(source.id),
                "tenant_id": str(source.tenant_id),
                "status": run.status,
                "fetched": run.fetched_count,
            })
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.warning(
                "listening_scheduled_sync_failed",
                extra={
                    "source_id": str(source.id),
                    "tenant_id": str(source.tenant_id),
                    "error": type(exc).__name__,
                },
            )
            results.append({
                "source_id": str(source.id),
                "tenant_id": str(source.tenant_id),
                "status": "failed",
                "error": type(exc).__name__,
            })
    return results


__all__ = [
    "clamp_poll_interval",
    "scrub_config",
    "sync_live_source",
    "list_due_live_sources",
    "run_scheduled_live_sync_batch",
    "try_acquire_source_lock",
    "release_source_lock",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "MIN_POLL_INTERVAL_SECONDS",
    "MAX_POLL_INTERVAL_SECONDS",
]
