"""Phase 3C.1C-C — pre-I/O preparation + deterministic attempt linkage.

PostgreSQL-backed: lock/reuse/concurrency/lineage. Zero provider I/O.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import PublishRetryCommand
from app.services import publish_retry_command_metrics as prep_metrics
from app.services.manual_retry_eligibility import ManualRetryEligibility
from app.services.publish_attempt_ops_service import PublishAttemptOpsService
from app.services.publish_resilience import (
    STATUS_OPERATOR_REVIEW,
    PublishResilienceService,
)
from app.services.publish_retry_command_claim_service import (
    PublishRetryCommandClaimService,
)
from app.services.publish_retry_command_preparation_service import (
    PREPARED_ATTEMPT_STATUS,
    PREPARED_FAILURE_CODE,
    PublishRetryCommandPreparationService,
    prepare_gates_open,
)
from app.workers.publish_retry_command_worker import PublishRetryCommandWorker

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/retry_command_prepare_test"
)

WORKER_A = "worker-a:1:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WORKER_B = "worker-b:2:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_PREPARE_PG_URL", DEFAULT_PG_URL)


def _allow(**kwargs):
    defaults = dict(
        allowed=True,
        reason_code="allowed",
        safety_class="CONDITIONAL_MANUAL_RETRY",
        confirmation_tier="medium",
        external_side_effect=True,
        operator_message="Allowed",
        mobile_eligible=False,
    )
    defaults.update(kwargs)
    return ManualRetryEligibility(**defaults)


def _deny(**kwargs):
    defaults = dict(
        allowed=False,
        reason_code="not_on_allowlist",
        safety_class="OPERATOR_REVIEW",
        confirmation_tier="high",
        external_side_effect=True,
        operator_message="Manual retry unavailable",
        mobile_eligible=False,
    )
    defaults.update(kwargs)
    return ManualRetryEligibility(**defaults)


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
        pytest.skip(f"PostgreSQL unavailable for prepare tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for prepare tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return url


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        for table in (
            "publish_retry_commands",
            "publish_attempts",
            "publishing_accounts",
            "content_items",
            "clients",
            "tenants",
        ):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))

        await conn.execute(
            text(
                """
                CREATE TABLE tenants (
                    id UUID PRIMARY KEY,
                    name VARCHAR(255) NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE clients (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    company_name VARCHAR(255) NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE content_items (
                    id UUID PRIMARY KEY,
                    client_id UUID NOT NULL,
                    status VARCHAR(30) NOT NULL DEFAULT 'failed',
                    caption_long_ru TEXT NULL,
                    caption_long_en TEXT NULL,
                    caption_short_ru TEXT NULL,
                    hashtags TEXT NULL,
                    media_file_id UUID NULL,
                    platforms VARCHAR[] NULL,
                    updated_at TIMESTAMPTZ NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE publishing_accounts (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    platform VARCHAR(20) NOT NULL,
                    account_name VARCHAR(255) NOT NULL DEFAULT 'Bot',
                    account_id VARCHAR(255) NOT NULL DEFAULT 'acct',
                    status VARCHAR(30) NOT NULL DEFAULT 'connected'
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE publish_attempts (
                    id UUID PRIMARY KEY,
                    content_id UUID NOT NULL,
                    platform VARCHAR(20) NOT NULL,
                    account_id UUID NULL,
                    status VARCHAR(20) NOT NULL,
                    response TEXT NULL,
                    error TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    idempotency_key VARCHAR(220) NULL,
                    publish_version VARCHAR(64) NULL,
                    attempt_number INTEGER NOT NULL DEFAULT 1,
                    failure_code VARCHAR(80) NULL,
                    failure_category VARCHAR(40) NULL,
                    retryable BOOLEAN NULL,
                    next_retry_at TIMESTAMPTZ NULL,
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    external_post_id VARCHAR(255) NULL,
                    external_post_url TEXT NULL,
                    lease_owner VARCHAR(120) NULL,
                    lease_expires_at TIMESTAMPTZ NULL,
                    retry_after_seconds INTEGER NULL,
                    retry_command_id UUID NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX uq_publish_attempts_retry_command_id
                ON publish_attempts (retry_command_id)
                WHERE retry_command_id IS NOT NULL
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX uq_publish_attempts_active_claim
                ON publish_attempts (idempotency_key)
                WHERE status = 'in_progress' AND idempotency_key IS NOT NULL
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
                CREATE UNIQUE INDEX uq_publish_retry_commands_resulting_attempt_id
                ON publish_retry_commands (resulting_attempt_id)
                WHERE resulting_attempt_id IS NOT NULL
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
        pytest.skip(f"PostgreSQL prepare test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL prepare test DB unavailable at {url}: {exc}")
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
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_LEASE_SECONDS": 180,
        "PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE": 1,
    }
    values.update(overrides)
    with patch.multiple(settings, **values):
        yield


@contextmanager
def _eligible(elig=None):
    elig = elig or _allow()
    with patch(
        "app.services.publish_retry_command_preparation_service."
        "evaluate_manual_retry_eligibility",
        return_value=elig,
    ), patch(
        "app.services.publish_retry_command_preparation_service."
        "build_manual_retry_live_state",
        new_callable=AsyncMock,
        return_value=MagicMock(
            has_live_success=False,
            content_status="failed",
            current_publish_version="pv_test",
            account_status="connected",
            now=datetime.now(timezone.utc),
        ),
    ):
        yield


class _Fixture:
    def __init__(self):
        self.tenant_id = uuid.uuid4()
        self.other_tenant_id = uuid.uuid4()
        self.client_id = uuid.uuid4()
        self.content_id = uuid.uuid4()
        self.account_id = uuid.uuid4()
        self.original_attempt_id = uuid.uuid4()
        self.command_id = uuid.uuid4()
        self.publish_version = "pv_test"
        self.platform = "telegram"
        self.idempotency_key = (
            f"{self.content_id}:{self.platform}:{self.account_id}:{self.publish_version}"
        )


async def _seed(
    db: AsyncSession,
    fx: _Fixture,
    *,
    command_status: str = "claimed",
    lease_owner: str = WORKER_A,
    lease_expires_sql: str = "NOW() + interval '3 minutes'",
    provider_write_started: bool = False,
    resulting_attempt_id: uuid.UUID | None = None,
    original_status: str = "failed",
    original_failure_code: str = "rate_limited",
    content_status: str = "failed",
    account_tenant: uuid.UUID | None = None,
    original_platform: str | None = None,
    original_account: uuid.UUID | None = None,
    original_content: uuid.UUID | None = None,
    original_version: str | None = None,
) -> None:
    await db.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, 't')"),
        {"id": fx.tenant_id},
    )
    await db.execute(
        text("INSERT INTO tenants (id, name) VALUES (:id, 'other')"),
        {"id": fx.other_tenant_id},
    )
    await db.execute(
        text(
            "INSERT INTO clients (id, tenant_id, company_name) "
            "VALUES (:id, :tid, 'Acme')"
        ),
        {"id": fx.client_id, "tid": fx.tenant_id},
    )
    await db.execute(
        text(
            """
            INSERT INTO content_items
                (id, client_id, status, platforms, updated_at)
            VALUES
                (:id, :cid, :status, ARRAY['telegram']::varchar[], NOW())
            """
        ),
        {"id": fx.content_id, "cid": fx.client_id, "status": content_status},
    )
    await db.execute(
        text(
            """
            INSERT INTO publishing_accounts
                (id, tenant_id, platform, account_name, account_id, status)
            VALUES
                (:id, :tid, 'telegram', 'Bot', 'bot1', 'connected')
            """
        ),
        {"id": fx.account_id, "tid": account_tenant or fx.tenant_id},
    )
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status, failure_code,
                publish_version, attempt_number, idempotency_key, retryable
            ) VALUES (
                :id, :content_id, :platform, :account_id, :status, :fc,
                :pv, 1, :ikey, true
            )
            """
        ),
        {
            "id": fx.original_attempt_id,
            "content_id": original_content or fx.content_id,
            "platform": original_platform or fx.platform,
            "account_id": fx.account_id if original_account is None else original_account,
            "status": original_status,
            "fc": original_failure_code,
            "pv": original_version or fx.publish_version,
            "ikey": fx.idempotency_key,
        },
    )
    await db.execute(
        text(
            f"""
            INSERT INTO publish_retry_commands (
                id, tenant_id, client_id, content_id, original_attempt_id,
                resulting_attempt_id, platform, publishing_account_id,
                publish_version, destination_key, requested_source,
                idempotency_key, status, lease_owner, lease_expires_at,
                claimed_at, started_at, provider_write_started_at, correlation_id
            ) VALUES (
                :id, :tid, :cid, :content_id, :orig,
                :resulting, :platform, :acct,
                :pv, :dest, 'admin',
                :ikey, :status, :owner, {lease_expires_sql},
                NOW(), NOW(),
                {"NOW()" if provider_write_started else "NULL"},
                :corr
            )
            """
        ),
        {
            "id": fx.command_id,
            "tid": fx.tenant_id,
            "cid": fx.client_id,
            "content_id": fx.content_id,
            "orig": fx.original_attempt_id,
            "resulting": resulting_attempt_id,
            "platform": fx.platform,
            "acct": fx.account_id,
            "pv": fx.publish_version,
            "dest": f"telegram:{fx.account_id}",
            "ikey": f"cmd:{fx.command_id}",
            "status": command_status,
            "owner": lease_owner,
            "corr": str(uuid.uuid4()),
        },
    )
    await db.commit()


async def _count_attempts(db: AsyncSession) -> int:
    return int(
        (await db.execute(text("SELECT COUNT(*) FROM publish_attempts"))).scalar_one()
    )


async def _reload_command(db: AsyncSession, command_id: uuid.UUID) -> PublishRetryCommand:
    return (
        await db.execute(
            select(PublishRetryCommand).where(PublishRetryCommand.id == command_id),
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Architecture / gate unit tests (no PG required)
# ---------------------------------------------------------------------------


def test_prepared_status_is_operator_review_not_auto_executable():
    assert PREPARED_ATTEMPT_STATUS == STATUS_OPERATOR_REVIEW
    assert PREPARED_ATTEMPT_STATUS not in ("in_progress", "retrying")
    src = inspect.getsource(PublishAttemptOpsService.due_retry_content_ids)
    assert "STATUS_RETRYING" in src or "retrying" in src
    assert "operator_review" not in src
    claim_src = inspect.getsource(PublishResilienceService.claim_due_retries)
    assert "STATUS_RETRYING" in claim_src or "retrying" in claim_src
    assert "operator_review" not in claim_src
    worker_src = inspect.getsource(PublishRetryCommandWorker.run_once)
    assert "PreparationService" not in worker_src
    assert "prepare(" not in worker_src


def test_prepare_gates_require_execution_flag():
    with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=False):
        ok, reason = prepare_gates_open()
        assert ok is False
        assert reason == "execution_disabled"
    with _gates_on():
        ok, reason = prepare_gates_open()
        assert ok is True


def test_begin_attempt_not_used_by_preparation_service():
    locked = inspect.getsource(PublishRetryCommandPreparationService._prepare_locked)
    create = inspect.getsource(PublishRetryCommandPreparationService._create_prepared_attempt)
    assert ".begin_attempt(" not in locked
    assert ".begin_attempt(" not in create
    assert "publish_content" not in locked
    assert "publish_content" not in create
    assert "finalize_attempt" not in locked
    assert "finalize_attempt" not in create
    assert "provider_write_started_at =" not in locked
    assert 'status = "provider_write_started"' not in locked
    assert 'status = "provider_write_started"' not in create


# ---------------------------------------------------------------------------
# PG matrix
# ---------------------------------------------------------------------------


def test_a_create_exactly_one_linked_attempt():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is True
        assert result.outcome == "prepared"
        assert result.resulting_attempt_id is not None
        assert result.reused_existing_attempt is False
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.status == "claimed"
            assert cmd.provider_write_started_at is None
            assert cmd.resulting_attempt_id == result.resulting_attempt_id
            attempt = await db.get(PublishAttempt, result.resulting_attempt_id)
            assert attempt is not None
            assert attempt.retry_command_id == fx.command_id
            assert attempt.status == PREPARED_ATTEMPT_STATUS
            assert attempt.failure_code == PREPARED_FAILURE_CODE
            assert attempt.retryable is False
            assert attempt.next_retry_at is None
            assert await _count_attempts(db) == 2  # original + prepared

    _run(_body)


def test_b_repeat_prepare_reuses_same_attempt():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        with _gates_on(), _eligible():
            async with factory() as db:
                first = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
            async with factory() as db:
                second = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert first.ok and second.ok
        assert second.reused_existing_attempt is True
        assert second.resulting_attempt_id == first.resulting_attempt_id
        async with factory() as db:
            assert await _count_attempts(db) == 2

    _run(_body)


def test_c_concurrent_prepare_one_attempt():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)

        barrier = asyncio.Barrier(2)
        results = []

        async def _worker():
            with _gates_on(), _eligible():
                async with factory() as db:
                    await barrier.wait()
                    results.append(
                        await PublishRetryCommandPreparationService.prepare(
                            db, command_id=fx.command_id, worker_id=WORKER_A,
                        )
                    )

        with _gates_on(), _eligible():
            await asyncio.gather(_worker(), _worker())

        assert len(results) == 2
        assert all(r.ok for r in results)
        ids = {r.resulting_attempt_id for r in results}
        assert len(ids) == 1
        async with factory() as db:
            assert await _count_attempts(db) == 2

    _run(_body)


def test_d_attempt_side_orphan_repaired():
    fx = _Fixture()
    orphan_id = uuid.uuid4()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx, resulting_attempt_id=None)
            await db.execute(
                text(
                    """
                    INSERT INTO publish_attempts (
                        id, content_id, platform, account_id, status,
                        publish_version, attempt_number, idempotency_key,
                        retry_command_id, retryable, failure_code
                    ) VALUES (
                        :id, :content_id, :platform, :account_id, 'operator_review',
                        :pv, 2, :ikey, :cmd, false, 'retry_command_prepared'
                    )
                    """
                ),
                {
                    "id": orphan_id,
                    "content_id": fx.content_id,
                    "platform": fx.platform,
                    "account_id": fx.account_id,
                    "pv": fx.publish_version,
                    "ikey": fx.idempotency_key + ":prep",
                    "cmd": fx.command_id,
                },
            )
            await db.commit()

        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is True
        assert result.outcome == "repaired_attempt_side_link"
        assert result.resulting_attempt_id == orphan_id
        assert result.reused_existing_attempt is True
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.resulting_attempt_id == orphan_id
            assert await _count_attempts(db) == 2

    _run(_body)


def test_e_command_side_inconsistent_link_fail_closed():
    fx = _Fixture()
    bad_attempt = uuid.uuid4()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx, resulting_attempt_id=None)
            await db.execute(
                text(
                    """
                    INSERT INTO publish_attempts (
                        id, content_id, platform, account_id, status,
                        publish_version, attempt_number, retry_command_id
                    ) VALUES (
                        :id, :content_id, :platform, :account_id, 'operator_review',
                        :pv, 2, NULL
                    )
                    """
                ),
                {
                    "id": bad_attempt,
                    "content_id": fx.content_id,
                    "platform": fx.platform,
                    "account_id": fx.account_id,
                    "pv": fx.publish_version,
                },
            )
            await db.execute(
                text(
                    "UPDATE publish_retry_commands "
                    "SET resulting_attempt_id = :aid WHERE id = :cid"
                ),
                {"aid": bad_attempt, "cid": fx.command_id},
            )
            await db.commit()

        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.outcome == "invariant_violation"
        assert result.reason_code == "bidirectional_lineage_broken"
        async with factory() as db:
            assert await _count_attempts(db) == 2

    _run(_body)


def test_f_expired_lease_blocks_preparation():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(
                db, fx,
                lease_expires_sql="NOW() - interval '1 minute'",
            )
        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.outcome == "blocked_lease_or_ownership"
        assert result.reason_code == "lease_expired"
        async with factory() as db:
            assert await _count_attempts(db) == 1

    _run(_body)


def test_g_valid_lease_allows_preparation():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is True
        assert result.outcome == "prepared"

    _run(_body)


def test_h_newer_success_prevents_attempt_creation():
    fx = _Fixture()
    success_id = uuid.uuid4()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
            await db.execute(
                text(
                    """
                    INSERT INTO publish_attempts (
                        id, content_id, platform, account_id, status,
                        publish_version, attempt_number, idempotency_key,
                        external_post_id
                    ) VALUES (
                        :id, :content_id, :platform, :account_id, 'success',
                        :pv, 2, :ikey, 'post-123'
                    )
                    """
                ),
                {
                    "id": success_id,
                    "content_id": fx.content_id,
                    "platform": fx.platform,
                    "account_id": fx.account_id,
                    "pv": fx.publish_version,
                    "ikey": fx.idempotency_key,
                },
            )
            await db.commit()

        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.outcome == "blocked_newer_success"
        assert result.newer_success_attempt_id == success_id
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.resulting_attempt_id is None
            assert await _count_attempts(db) == 2

    _run(_body)


def test_i_eligibility_failure_prevents_attempt_creation():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        with _gates_on(), _eligible(_deny()):
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.outcome == "blocked_ineligible"
        async with factory() as db:
            assert await _count_attempts(db) == 1
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.resulting_attempt_id is None

    _run(_body)


def test_j_wrong_tenant_on_account_fails_closed():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx, account_tenant=fx.other_tenant_id)
        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.outcome == "invariant_violation"
        assert result.reason_code == "account_tenant_mismatch"

    _run(_body)


def test_k_wrong_content_on_linked_attempt_fails_closed():
    fx = _Fixture()
    other_content = uuid.uuid4()
    linked = uuid.uuid4()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
            await db.execute(
                text(
                    "INSERT INTO content_items (id, client_id, status) "
                    "VALUES (:id, :cid, 'failed')"
                ),
                {"id": other_content, "cid": fx.client_id},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO publish_attempts (
                        id, content_id, platform, account_id, status,
                        publish_version, attempt_number, retry_command_id
                    ) VALUES (
                        :id, :content_id, :platform, :account_id, 'operator_review',
                        :pv, 2, :cmd
                    )
                    """
                ),
                {
                    "id": linked,
                    "content_id": other_content,
                    "platform": fx.platform,
                    "account_id": fx.account_id,
                    "pv": fx.publish_version,
                    "cmd": fx.command_id,
                },
            )
            await db.execute(
                text(
                    "UPDATE publish_retry_commands "
                    "SET resulting_attempt_id = :aid WHERE id = :cid"
                ),
                {"aid": linked, "cid": fx.command_id},
            )
            await db.commit()

        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.reason_code == "linked_attempt_content_mismatch"

    _run(_body)


def test_l_wrong_platform_account_fails_closed():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx, original_platform="facebook")
        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.reason_code == "platform_lineage_mismatch"

    _run(_body)


def test_m_prepared_command_reclaimed_then_reused():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        with _gates_on(), _eligible():
            async with factory() as db:
                first = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
            assert first.ok
            async with factory() as db:
                await db.execute(
                    text(
                        "UPDATE publish_retry_commands "
                        "SET lease_expires_at = NOW() - interval '1 minute' "
                        "WHERE id = :id"
                    ),
                    {"id": fx.command_id},
                )
                await db.commit()
            async with factory() as db:
                reclaimed = await PublishRetryCommandClaimService.claim_batch(
                    db, worker_id=WORKER_B, batch=1, commit=True,
                )
            assert reclaimed and reclaimed[0].kind == "reclaimed"
            async with factory() as db:
                second = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_B,
                )
        assert second.ok is True
        assert second.reused_existing_attempt is True
        assert second.resulting_attempt_id == first.resulting_attempt_id
        async with factory() as db:
            assert await _count_attempts(db) == 2

    _run(_body)


def test_n_terminal_and_post_write_cannot_prepare():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx, command_status="failed")
        with _gates_on(), _eligible():
            async with factory() as db:
                terminal = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert terminal.ok is False
        assert terminal.outcome == "blocked_terminal_or_post_write"

        fx2 = _Fixture()
        async with factory() as db:
            for table in (
                "publish_retry_commands",
                "publish_attempts",
                "publishing_accounts",
                "content_items",
                "clients",
                "tenants",
            ):
                await db.execute(text(f"DELETE FROM {table}"))
            await db.commit()
            await _seed(
                db,
                fx2,
                command_status="provider_write_started",
                provider_write_started=True,
            )
        with _gates_on(), _eligible():
            async with factory() as db:
                post = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx2.command_id, worker_id=WORKER_A,
                )
        assert post.ok is False
        assert post.outcome == "blocked_terminal_or_post_write"
        assert post.reason_code == "provider_write_started"

    _run(_body)


def test_o_zero_provider_calls():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        publish_mock = AsyncMock(
            side_effect=AssertionError("publish_content must not be called"),
        )
        finalize_mock = AsyncMock(
            side_effect=AssertionError("finalize_attempt must not be called"),
        )
        with _gates_on(), _eligible(), patch(
            "app.services.publish_service.PublishService.publish_content",
            publish_mock,
        ), patch(
            "app.services.publish_resilience.PublishResilienceService.finalize_attempt",
            finalize_mock,
        ):
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is True
        publish_mock.assert_not_called()
        finalize_mock.assert_not_called()

    _run(_body)


def test_p_q_r_atomic_lineage_and_claimed_pre_write():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        prep_metrics.reset_for_tests()
        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            attempt = await db.get(PublishAttempt, result.resulting_attempt_id)
            assert cmd.resulting_attempt_id == attempt.id
            assert attempt.retry_command_id == cmd.id
            assert cmd.provider_write_started_at is None
            assert result.provider_write_started_at_is_null is True
            assert cmd.status == "claimed"
            assert result.command_status == "claimed"
        snap = prep_metrics.snapshot()
        assert snap["retry_command_prepare_total"] >= 1

    _run(_body)


def test_wrong_owner_blocks_preparation():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx, lease_owner=WORKER_A)
        with _gates_on(), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_B,
                )
        assert result.ok is False
        assert result.reason_code == "lease_owner_mismatch"

    _run(_body)


def test_empty_allowlist_blocks_without_eligibility_seam():
    """Production policy: empty allowlist → no attempt created."""
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        with _gates_on():
            # Real evaluator — no patch. Empty allowlist denies.
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.outcome == "blocked_ineligible"
        async with factory() as db:
            assert await _count_attempts(db) == 1

    _run(_body)


def test_execution_gate_blocks_even_when_claim_gates_open():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed(db, fx)
        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=False), _eligible():
            async with factory() as db:
                result = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A,
                )
        assert result.ok is False
        assert result.outcome == "disabled"
        assert result.reason_code == "execution_disabled"

    _run(_body)
