"""Phase 3C.1C-B — claim / lease / reclaim foundation for publish retry commands.

PostgreSQL SKIP LOCKED concurrency + fail-closed flags. Zero provider execution.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_retry_command import (
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)
from app.services import publish_retry_command_metrics as claim_metrics
from app.services.publish_retry_command_claim_service import (
    PublishRetryCommandClaimService,
    claim_gates_open,
    scrubbed_worker_instance,
)
from app.workers.publish_retry_command_worker import (
    PublishRetryCommandWorker,
    build_worker_identity,
)

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/retry_command_claim_test"
)

TERMINAL_STATUSES = tuple(sorted(RETRY_COMMAND_TERMINAL_STATUSES))


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_CLAIM_PG_URL", DEFAULT_PG_URL)


async def _wait_ready(engine, attempts: int = 40) -> None:
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"PostgreSQL not ready: {last_exc}")


async def _ensure_database() -> str:
    url = _pg_url()
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    db_name = url.rsplit("/", 1)[-1]
    engine = create_async_engine(admin_url, echo=False, isolation_level="AUTOCOMMIT")
    try:
        await _wait_ready(engine)
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if exists.first() is None:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable for claim tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for claim tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return url


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS publish_retry_commands CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS publish_attempts CASCADE"))
        await conn.execute(
            text(
                """
                CREATE TABLE publish_attempts (
                    id UUID PRIMARY KEY,
                    retry_command_id UUID NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'failed',
                    platform VARCHAR(20) NOT NULL DEFAULT 'telegram',
                    content_id UUID NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE publish_retry_commands (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    client_id UUID NOT NULL,
                    content_id UUID NOT NULL,
                    original_attempt_id UUID NOT NULL,
                    resulting_attempt_id UUID NULL,
                    platform VARCHAR(20) NOT NULL,
                    publishing_account_id UUID NULL,
                    publish_version VARCHAR(64) NOT NULL,
                    destination_key VARCHAR(120) NOT NULL,
                    requested_by UUID NULL,
                    requested_source VARCHAR(20) NOT NULL,
                    idempotency_key VARCHAR(420) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    reason_code VARCHAR(80) NULL,
                    provider_outcome VARCHAR(40) NULL,
                    lease_owner VARCHAR(120) NULL,
                    lease_expires_at TIMESTAMPTZ NULL,
                    claimed_at TIMESTAMPTZ NULL,
                    started_at TIMESTAMPTZ NULL,
                    provider_write_started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    correlation_id VARCHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT ck_publish_retry_commands_provider_write_ts CHECK (
                        status <> 'provider_write_started'
                        OR provider_write_started_at IS NOT NULL
                    )
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX ix_publish_retry_commands_status_created_at
                ON publish_retry_commands (status, created_at)
                """
            )
        )


async def _with_pg(coro_factory):
    url = await _ensure_database()
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_schema(engine)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await coro_factory(factory)
    except OSError as exc:
        pytest.skip(f"PostgreSQL claim test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL claim test DB unavailable at {url}: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(_with_pg(coro_factory))


@contextmanager
def _gates_on(**overrides):
    values = {
        "PUBLISH_RETRY_COMMANDS_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": False,
        "PUBLISH_RETRY_COMMAND_LEASE_SECONDS": 180,
        "PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE": 1,
    }
    values.update(overrides)
    with patch.multiple(settings, **values):
        yield


async def _insert_command(
    db: AsyncSession,
    *,
    status: str = "pending",
    lease_owner: str | None = None,
    lease_expires_sql: str | None = None,
    provider_write_started: bool = False,
    claimed_at_sql: str | None = None,
    started_at_sql: str | None = None,
    command_id: uuid.UUID | None = None,
) -> uuid.UUID:
    cid = command_id or uuid.uuid4()
    attempt_id = uuid.uuid4()
    await db.execute(
        text("INSERT INTO publish_attempts (id) VALUES (:id)"),
        {"id": attempt_id},
    )
    pws_sql = "NOW()" if provider_write_started else "NULL"
    lease_sql = lease_expires_sql if lease_expires_sql is not None else "NULL"
    claimed_sql = claimed_at_sql if claimed_at_sql is not None else "NULL"
    started_sql = started_at_sql if started_at_sql is not None else "NULL"
    await db.execute(
        text(
            f"""
            INSERT INTO publish_retry_commands (
                id, tenant_id, client_id, content_id, original_attempt_id,
                resulting_attempt_id, platform, publish_version, destination_key,
                requested_source, idempotency_key, status, lease_owner,
                lease_expires_at, claimed_at, started_at, provider_write_started_at,
                correlation_id
            ) VALUES (
                :id, :tenant_id, :client_id, :content_id, :attempt_id,
                NULL, 'telegram', 'pv_test', 'telegram:none',
                'admin', :idem, :status, :lease_owner,
                {lease_sql}, {claimed_sql}, {started_sql}, {pws_sql},
                :corr
            )
            """
        ),
        {
            "id": cid,
            "tenant_id": uuid.uuid4(),
            "client_id": uuid.uuid4(),
            "content_id": uuid.uuid4(),
            "attempt_id": attempt_id,
            "idem": f"idem-{cid}",
            "status": status,
            "lease_owner": lease_owner,
            "corr": str(uuid.uuid4()),
        },
    )
    await db.commit()
    return cid


async def _load(db: AsyncSession, command_id: uuid.UUID) -> PublishRetryCommand:
    return (
        await db.execute(
            select(PublishRetryCommand).where(PublishRetryCommand.id == command_id),
        )
    ).scalar_one()


async def _attempt_count(db: AsyncSession) -> int:
    return int(
        (await db.execute(text("SELECT COUNT(*) FROM publish_attempts"))).scalar_one()
    )


async def _command_count(db: AsyncSession) -> int:
    return int(
        (await db.execute(text("SELECT COUNT(*) FROM publish_retry_commands"))).scalar_one()
    )


def test_claim_gates_default_closed():
    assert settings.PUBLISH_RETRY_COMMANDS_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED is False
    allowed, reason = claim_gates_open()
    assert allowed is False
    assert reason == "commands_disabled"


def test_claim_gate_precedence():
    with _gates_on(PUBLISH_RETRY_COMMANDS_ENABLED=False):
        assert claim_gates_open() == (False, "commands_disabled")
    with _gates_on(PUBLISH_RETRY_COMMAND_WORKER_ENABLED=False):
        assert claim_gates_open() == (False, "worker_disabled")
    with _gates_on(PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=False):
        assert claim_gates_open() == (False, "claim_disabled")
    with _gates_on():
        assert claim_gates_open() == (True, "ok")


def test_worker_identity_stable_per_process_shape():
    a = build_worker_identity()
    b = build_worker_identity()
    assert a != b
    assert a.count(":") >= 2
    scrubbed = scrubbed_worker_instance(a)
    assert scrubbed.startswith("winst_")
    assert ":" not in scrubbed


def test_graceful_shutdown_sets_stop_without_release():
    worker = PublishRetryCommandWorker(worker_id="host:1:test")
    assert not worker._stop.is_set()
    worker.request_stop()
    assert worker._stop.is_set()


def test_flag_off_no_mutation():
    async def scenario(factory):
        claim_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
            expired_id = await _insert_command(
                db,
                status="claimed",
                lease_owner="old-worker",
                lease_expires_sql="NOW() - INTERVAL '1 hour'",
                claimed_at_sql="NOW() - INTERVAL '2 hours'",
                started_at_sql="NOW() - INTERVAL '2 hours'",
            )

        with patch.multiple(
            settings,
            PUBLISH_RETRY_COMMANDS_ENABLED=False,
            PUBLISH_RETRY_COMMAND_WORKER_ENABLED=True,
            PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=True,
        ):
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="w-flag-off",
                )
        assert results[0].kind == "disabled"
        async with factory() as db:
            pending = await _load(db, cid)
            stale = await _load(db, expired_id)
            assert pending.status == "pending"
            assert pending.lease_owner is None
            assert stale.status == "claimed"
            assert stale.lease_owner == "old-worker"

    _run(scenario)


def test_claim_requires_all_three_gates():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")

        for kwargs in (
            {"PUBLISH_RETRY_COMMANDS_ENABLED": False},
            {"PUBLISH_RETRY_COMMAND_WORKER_ENABLED": False},
            {"PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": False},
        ):
            with _gates_on(**kwargs):
                async with factory() as db:
                    results = await PublishRetryCommandClaimService.claim_batch(
                        db, worker_id="w-gate",
                    )
                assert results[0].kind == "disabled"
                async with factory() as db:
                    row = await _load(db, cid)
                    assert row.status == "pending"

    _run(scenario)


def test_pending_claim_basic():
    async def scenario(factory):
        claim_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
            attempts_before = await _attempt_count(db)

        with _gates_on():
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="worker-a:1:aaa",
                )

        assert len(results) == 1
        assert results[0].kind == "claimed"
        assert results[0].command_id == cid
        assert results[0].is_reclaim is False
        assert results[0].status == "claimed"

        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"
            assert row.lease_owner == "worker-a:1:aaa"
            assert row.lease_expires_at is not None
            assert row.claimed_at is not None
            assert row.started_at is not None
            assert row.provider_write_started_at is None
            assert row.resulting_attempt_id is None
            assert await _attempt_count(db) == attempts_before
            assert await _command_count(db) == 1
            future = (
                await db.execute(
                    text(
                        "SELECT lease_expires_at > NOW() FROM publish_retry_commands "
                        "WHERE id = :id"
                    ),
                    {"id": cid},
                )
            ).scalar_one()
            assert future is True

        snap = claim_metrics.snapshot()
        assert snap["retry_command_claim_total"] >= 1

    _run(scenario)


def test_concurrent_claim_single_winner():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")

        async def claim(wid: str):
            async with factory() as db:
                return await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id=wid,
                )

        with _gates_on():
            r1, r2 = await asyncio.gather(
                claim("worker-1:1:aaa"),
                claim("worker-2:2:bbb"),
            )

        winners = [r for r in (r1, r2) if r[0].kind == "claimed"]
        losers = [r for r in (r1, r2) if r[0].kind == "none"]
        assert len(winners) == 1
        assert winners[0][0].command_id == cid
        assert len(losers) == 1

        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"
            assert row.lease_owner in ("worker-1:1:aaa", "worker-2:2:bbb")
            assert await _command_count(db) == 1

    _run(scenario)


def test_two_pending_distributed_across_workers():
    async def scenario(factory):
        async with factory() as db:
            c1 = await _insert_command(db, status="pending")
            await asyncio.sleep(0.02)
            c2 = await _insert_command(db, status="pending")

        async def claim(wid: str):
            async with factory() as db:
                return await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id=wid, batch=1,
                )

        with _gates_on():
            r1, r2 = await asyncio.gather(
                claim("dist-1:1:aaa"),
                claim("dist-2:2:bbb"),
            )

        claimed_ids = {
            r[0].command_id
            for r in (r1, r2)
            if r[0].kind == "claimed"
        }
        assert claimed_ids == {c1, c2}

        async with factory() as db:
            row1 = await _load(db, c1)
            row2 = await _load(db, c2)
            assert row1.status == "claimed"
            assert row2.status == "claimed"
            assert row1.lease_owner != row2.lease_owner

    _run(scenario)


def test_stale_claimed_reclaim_preserves_timestamps():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(
                db,
                status="claimed",
                lease_owner="dead-worker:9:zzz",
                lease_expires_sql="NOW() - INTERVAL '10 minutes'",
                claimed_at_sql="NOW() - INTERVAL '1 hour'",
                started_at_sql="NOW() - INTERVAL '1 hour'",
            )
            before = await _load(db, cid)
            claimed_at = before.claimed_at
            started_at = before.started_at
            attempts_before = await _attempt_count(db)

        with _gates_on():
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="reclaimer:1:abc",
                )

        assert results[0].kind == "reclaimed"
        assert results[0].command_id == cid
        assert results[0].is_reclaim is True

        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"
            assert row.lease_owner == "reclaimer:1:abc"
            assert row.claimed_at == claimed_at
            assert row.started_at == started_at
            assert row.provider_write_started_at is None
            assert row.resulting_attempt_id is None
            assert await _attempt_count(db) == attempts_before
            assert await _command_count(db) == 1
            advanced = (
                await db.execute(
                    text(
                        "SELECT lease_expires_at > NOW() FROM publish_retry_commands "
                        "WHERE id = :id"
                    ),
                    {"id": cid},
                )
            ).scalar_one()
            assert advanced is True

    _run(scenario)


def test_valid_lease_not_reclaimed():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(
                db,
                status="claimed",
                lease_owner="holder:1:aaa",
                lease_expires_sql="NOW() + INTERVAL '30 minutes'",
                claimed_at_sql="NOW() - INTERVAL '1 minute'",
                started_at_sql="NOW() - INTERVAL '1 minute'",
            )

        with _gates_on():
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="intruder:2:bbb",
                )

        assert results[0].kind == "none"
        async with factory() as db:
            row = await _load(db, cid)
            assert row.lease_owner == "holder:1:aaa"
            assert row.status == "claimed"

    _run(scenario)


def test_provider_write_started_never_reclaimed():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(
                db,
                status="provider_write_started",
                lease_owner="writer:1:aaa",
                lease_expires_sql="NOW() - INTERVAL '2 hours'",
                provider_write_started=True,
                claimed_at_sql="NOW() - INTERVAL '3 hours'",
                started_at_sql="NOW() - INTERVAL '3 hours'",
            )
            before = await _load(db, cid)
            before_owner = before.lease_owner
            before_expires = before.lease_expires_at
            before_updated = before.updated_at

        with _gates_on():
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="must-skip:9:zzz",
                )

        assert results[0].kind == "none"
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "provider_write_started"
            assert row.lease_owner == before_owner
            assert row.lease_expires_at == before_expires
            assert row.provider_write_started_at is not None
            assert row.updated_at == before_updated

    _run(scenario)


@pytest.mark.parametrize("terminal", TERMINAL_STATUSES)
def test_terminal_status_never_claimed(terminal):
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(
                db,
                status=terminal,
                lease_owner="ghost:1:aaa",
                lease_expires_sql="NOW() - INTERVAL '1 day'",
                claimed_at_sql="NOW() - INTERVAL '2 days'",
                started_at_sql="NOW() - INTERVAL '2 days'",
            )

        with _gates_on():
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="terminal-skip:1:aaa",
                )

        assert results[0].kind == "none"
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == terminal
            assert row.lease_owner == "ghost:1:aaa"

    _run(scenario)


def test_db_now_not_app_clock():
    """Lease eligibility follows DB now(); claim service does not use app clock."""
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(
                db,
                status="claimed",
                lease_owner="old:1:aaa",
                lease_expires_sql="NOW() - INTERVAL '5 minutes'",
                claimed_at_sql="NOW() - INTERVAL '30 minutes'",
                started_at_sql="NOW() - INTERVAL '30 minutes'",
            )

        import app.services.publish_retry_command_claim_service as claim_mod
        import inspect

        source = inspect.getsource(claim_mod.PublishRetryCommandClaimService)
        assert "datetime.now" not in source
        assert "datetime.utcnow" not in source
        assert "func.now()" in source

        with _gates_on():
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="dbclock:1:aaa",
                )

        assert results[0].kind == "reclaimed"
        async with factory() as db:
            row = await _load(db, cid)
            assert row.lease_owner == "dbclock:1:aaa"
            future = (
                await db.execute(
                    text(
                        "SELECT lease_expires_at > NOW() FROM publish_retry_commands "
                        "WHERE id = :id"
                    ),
                    {"id": cid},
                )
            ).scalar_one()
            assert future is True

    _run(scenario)


def test_zero_execution_during_claim_and_reclaim():
    async def scenario(factory):
        async with factory() as db:
            pending_id = await _insert_command(db, status="pending")
            stale_id = await _insert_command(
                db,
                status="claimed",
                lease_owner="dead:1:aaa",
                lease_expires_sql="NOW() - INTERVAL '1 hour'",
                claimed_at_sql="NOW() - INTERVAL '2 hours'",
                started_at_sql="NOW() - INTERVAL '2 hours'",
            )
            content_before = (
                await db.execute(
                    text(
                        "SELECT content_id, original_attempt_id, resulting_attempt_id "
                        "FROM publish_retry_commands WHERE id = :id"
                    ),
                    {"id": pending_id},
                )
            ).one()

        boom = AsyncMock(side_effect=AssertionError("must not execute"))
        patches = [
            patch(
                "app.services.publish_service.PublishService.publish_content",
                boom,
            ),
            patch(
                "app.services.publish_resilience.PublishResilienceService.begin_attempt",
                boom,
            ),
            patch(
                "app.services.publish_resilience.PublishResilienceService.finalize_attempt",
                boom,
            ),
            patch(
                "app.services.publish_service.ADAPTERS",
                new_callable=dict,
            ),
            patch(
                "app.services.operator_workspace_actions.OperatorWorkspaceActionService",
            ),
        ]
        with _gates_on(PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE=5):
            for p in patches:
                p.start()
            try:
                async with factory() as db:
                    results = await PublishRetryCommandClaimService.claim_batch(
                        db, worker_id="safe:1:aaa", batch=5,
                    )
            finally:
                for p in patches:
                    p.stop()

        kinds = {r.kind for r in results}
        assert "claimed" in kinds
        assert "reclaimed" in kinds
        assert boom.await_count == 0

        async with factory() as db:
            pending = await _load(db, pending_id)
            stale = await _load(db, stale_id)
            assert pending.status == "claimed"
            assert stale.status == "claimed"
            assert pending.provider_write_started_at is None
            assert stale.provider_write_started_at is None
            assert pending.resulting_attempt_id is None
            assert stale.resulting_attempt_id is None
            after = (
                await db.execute(
                    text(
                        "SELECT content_id, original_attempt_id, resulting_attempt_id "
                        "FROM publish_retry_commands WHERE id = :id"
                    ),
                    {"id": pending_id},
                )
            ).one()
            assert after == content_before
            assert await _attempt_count(db) == 2

    _run(scenario)


def test_claim_audit_after_commit_best_effort():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")

        recorded: list[dict] = []

        async def fake_record(db, **kwargs):
            recorded.append(kwargs)
            return None

        from app.services.platform_audit_service import PlatformAuditService

        with _gates_on():
            async with factory() as db:
                results = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id="audit-w:1:aaa",
                )
            with patch.object(
                PlatformAuditService,
                "record",
                AsyncMock(side_effect=fake_record),
            ):
                await PublishRetryCommandClaimService.record_claim_audits(
                    factory,
                    results,
                    worker_id="audit-w:1:aaa",
                )

        assert results[0].kind == "claimed"
        assert len(recorded) == 1
        assert recorded[0]["event_type"] == "publishing.retry_command_claimed"
        details = recorded[0]["details"]
        assert details["command_id"] == str(cid)
        assert details["worker_instance"].startswith("winst_")
        assert "lease_owner" not in details

        with patch.object(
            PlatformAuditService,
            "record",
            AsyncMock(side_effect=RuntimeError("audit down")),
        ):
            await PublishRetryCommandClaimService.record_claim_audits(
                factory,
                results,
                worker_id="audit-w:1:aaa",
            )
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"

    _run(scenario)


def test_serialize_excludes_lease_owner():
    from app.services.publish_retry_command_service import serialize_retry_command

    cmd = PublishRetryCommand(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        content_id=uuid.uuid4(),
        original_attempt_id=uuid.uuid4(),
        platform="telegram",
        publish_version="pv",
        destination_key="telegram:none",
        requested_source="admin",
        idempotency_key="k",
        status="claimed",
        correlation_id=str(uuid.uuid4()),
        lease_owner="secret-host:1:uuid",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    payload = serialize_retry_command(cmd)
    assert "lease_owner" not in payload
    assert "lease_expires_at" not in payload


def test_worker_run_once_observation_only():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")

        worker = PublishRetryCommandWorker(worker_id="obs:1:aaa")

        with _gates_on():
            with patch(
                "app.workers.publish_retry_command_worker.AsyncSessionLocal",
                factory,
            ):
                # Avoid real audit tenant FK lookups against minimal schema.
                with patch.object(
                    PublishRetryCommandClaimService,
                    "record_claim_audits",
                    AsyncMock(return_value=None),
                ):
                    results = await worker.run_once()

        assert results[0].kind == "claimed"
        assert results[0].command_id == cid
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"
            assert row.provider_write_started_at is None

    _run(scenario)
