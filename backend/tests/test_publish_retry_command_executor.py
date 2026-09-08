"""Phase 3C.1C-D2-A — unwired fake executor + command finalization.

PostgreSQL-backed where locking / concurrency matter.
Zero real provider adapters. Worker remains claim-only / unwired.
"""
from __future__ import annotations

import asyncio
import ast
import inspect
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import PublishRetryCommand
from app.services import publish_retry_command_metrics as cmd_metrics
from app.services.manual_retry_eligibility import ManualRetryEligibility
from app.services.publish_attempt_ops_service import PublishAttemptOpsService
from app.services.publish_resilience import (
    STATUS_FAILED,
    STATUS_OPERATOR_REVIEW,
    STATUS_SUCCESS,
    PublishResilienceService,
)
from app.services.publish_retry_command_barrier_service import (
    WRITE_STARTED_FAILURE_CODE,
    PublishRetryCommandBarrierService,
)
from app.services.publish_retry_command_executor import (
    PublishRetryCommandExecutor,
)
from app.services.publish_retry_command_finalization_service import (
    DEFINITIVE_ATTEMPT_STATUS,
    PublishRetryCommandFinalizationService,
)
from app.services.publish_retry_command_outcome_classifier import (
    ClassifiedProviderOutcome,
    classify_provider_result,
)
from app.services.publish_retry_command_preparation_service import (
    PREPARED_FAILURE_CODE,
    PublishRetryCommandPreparationService,
)
from app.services.publish_retry_command_provider_port import (
    FakeProviderExecutor,
    FakeProviderMode,
    ProviderExecutionResult,
)
from app.workers.publish_retry_command_worker import PublishRetryCommandWorker

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/retry_command_executor_test"
)

WORKER_A = "worker-a:1:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WORKER_B = "worker-b:2:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

SERVICES_DIR = Path(__file__).resolve().parents[1] / "app" / "services"
D2A_MODULES = (
    "publish_retry_command_executor.py",
    "publish_retry_command_finalization_service.py",
    "publish_retry_command_provider_port.py",
    "publish_retry_command_outcome_classifier.py",
)


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_EXECUTOR_PG_URL", DEFAULT_PG_URL)


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
        pytest.skip(f"PostgreSQL unavailable for executor tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for executor tests: {exc}")
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
        pytest.skip(f"PostgreSQL executor test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL executor test DB unavailable at {url}: {exc}")
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
    live = MagicMock(
        has_live_success=False,
        content_status="failed",
        current_publish_version="pv_test",
        account_status="connected",
        now=datetime.now(timezone.utc),
    )
    with patch(
        "app.services.publish_retry_command_preparation_service."
        "evaluate_manual_retry_eligibility",
        return_value=elig,
    ), patch(
        "app.services.publish_retry_command_preparation_service."
        "build_manual_retry_live_state",
        new_callable=AsyncMock,
        return_value=live,
    ), patch(
        "app.services.publish_retry_command_barrier_service."
        "evaluate_manual_retry_eligibility",
        return_value=elig,
    ), patch(
        "app.services.publish_retry_command_barrier_service."
        "build_manual_retry_live_state",
        new_callable=AsyncMock,
        return_value=live,
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
        self.prepared_attempt_id = uuid.uuid4()
        self.command_id = uuid.uuid4()
        self.publish_version = "pv_test"
        self.platform = "telegram"
        self.idempotency_key = (
            f"{self.content_id}:{self.platform}:{self.account_id}:{self.publish_version}"
        )


async def _seed_claimed(
    db: AsyncSession,
    fx: _Fixture,
    *,
    command_status: str = "claimed",
    lease_owner: str = WORKER_A,
    lease_expires_sql: str = "NOW() + interval '3 minutes'",
    provider_write_started: bool = False,
    link_attempt: bool = False,
    reverse_link: bool = True,
    attempt_status: str = "operator_review",
    attempt_failure_code: str = PREPARED_FAILURE_CODE,
    attempt_retryable: bool = False,
    attempt_finished_sql: str | None = None,
    attempt_external_post_id: str | None = None,
    command_finished: bool = False,
    provider_outcome: str | None = None,
    account_tenant: uuid.UUID | None = None,
    content_tenant_via_client: bool = True,
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
        {
            "id": fx.client_id,
            "tid": fx.tenant_id if content_tenant_via_client else fx.other_tenant_id,
        },
    )
    await db.execute(
        text(
            """
            INSERT INTO content_items
                (id, client_id, status, platforms, updated_at)
            VALUES
                (:id, :cid, 'failed', ARRAY['telegram']::varchar[], NOW())
            """
        ),
        {"id": fx.content_id, "cid": fx.client_id},
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
                :id, :content_id, :platform, :account_id, 'failed', 'rate_limited',
                :pv, 1, :ikey, true
            )
            """
        ),
        {
            "id": fx.original_attempt_id,
            "content_id": fx.content_id,
            "platform": fx.platform,
            "account_id": fx.account_id,
            "pv": fx.publish_version,
            "ikey": fx.idempotency_key,
        },
    )

    resulting_id = fx.prepared_attempt_id if link_attempt else None
    if link_attempt:
        finished = attempt_finished_sql or "NULL"
        await db.execute(
            text(
                f"""
                INSERT INTO publish_attempts (
                    id, content_id, platform, account_id, status, failure_code,
                    failure_category, publish_version, attempt_number,
                    idempotency_key, retryable, next_retry_at, finished_at,
                    external_post_id, retry_command_id, started_at, error
                ) VALUES (
                    :id, :content_id, :platform, :account_id, :status, :fc,
                    'command_orchestration', :pv, 2,
                    :ikey, :retryable, NULL, {finished},
                    :epid, :rcid, NOW(), 'Prepared for durable retry-command execution'
                )
                """
            ),
            {
                "id": fx.prepared_attempt_id,
                "content_id": fx.content_id,
                "platform": fx.platform,
                "account_id": fx.account_id,
                "status": attempt_status,
                "fc": attempt_failure_code,
                "pv": fx.publish_version,
                "ikey": fx.idempotency_key + ":prep",
                "retryable": attempt_retryable,
                "epid": attempt_external_post_id,
                "rcid": fx.command_id if reverse_link else None,
            },
        )

    finished_sql = "NOW()" if command_finished else "NULL"
    await db.execute(
        text(
            f"""
            INSERT INTO publish_retry_commands (
                id, tenant_id, client_id, content_id, original_attempt_id,
                resulting_attempt_id, platform, publishing_account_id,
                publish_version, destination_key, requested_source,
                idempotency_key, status, provider_outcome, lease_owner,
                lease_expires_at, claimed_at, started_at,
                provider_write_started_at, finished_at, correlation_id
            ) VALUES (
                :id, :tid, :cid, :content_id, :orig,
                :resulting, :platform, :acct,
                :pv, :dest, 'admin',
                :ikey, :status, :pout, :owner, {lease_expires_sql},
                NOW(), NOW(),
                {"NOW()" if provider_write_started else "NULL"},
                {finished_sql},
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
            "resulting": resulting_id,
            "platform": fx.platform,
            "acct": fx.account_id,
            "pv": fx.publish_version,
            "dest": f"telegram:{fx.account_id}",
            "ikey": f"cmd:{fx.command_id}",
            "status": command_status,
            "pout": provider_outcome,
            "owner": lease_owner,
            "corr": str(uuid.uuid4()),
        },
    )
    await db.commit()


async def _reload_command(db: AsyncSession, command_id: uuid.UUID) -> PublishRetryCommand:
    return (
        await db.execute(
            select(PublishRetryCommand).where(PublishRetryCommand.id == command_id),
        )
    ).scalar_one()


async def _reload_attempt(db: AsyncSession, attempt_id: uuid.UUID) -> PublishAttempt:
    return (
        await db.execute(
            select(PublishAttempt).where(PublishAttempt.id == attempt_id),
        )
    ).scalar_one()


async def _linked_attempt_id(db: AsyncSession, command_id: uuid.UUID) -> uuid.UUID:
    cmd = await _reload_command(db, command_id)
    assert cmd.resulting_attempt_id is not None
    return cmd.resulting_attempt_id


# ---------------------------------------------------------------------------
# Architecture / static unit tests (no PG)
# ---------------------------------------------------------------------------


def test_ad_zero_real_provider_imports_in_d2a_modules():
    forbidden_imports = (
        "telegram_publisher",
        "facebook_publisher",
        "instagram_publisher",
        "httpx",
        "publish_service",
    )
    for name in D2A_MODULES:
        src = (SERVICES_DIR / name).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    for bad in forbidden_imports:
                        assert bad not in mod, f"{name} imports {mod}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for bad in forbidden_imports:
                    assert bad not in mod, f"{name} imports from {mod}"
                for alias in node.names:
                    assert alias.name != "ADAPTERS", f"{name} imports ADAPTERS"
        assert ".begin_attempt(" not in src, f"{name} calls begin_attempt"
        assert ".finalize_attempt(" not in src, f"{name} calls finalize_attempt"
        assert "ADAPTERS[" not in src
        assert ".publish_content(" not in src


def test_ab_ac_executor_source_avoids_begin_finalize_and_adapters():
    src = inspect.getsource(PublishRetryCommandExecutor)
    assert ".begin_attempt(" not in src
    assert ".finalize_attempt(" not in src
    assert "ADAPTERS" not in src
    assert "publish_content" not in src
    assert "telegram_publisher" not in src


def test_worker_does_not_call_executor_or_finalizer():
    worker_src = inspect.getsource(PublishRetryCommandWorker)
    assert "PublishRetryCommandExecutor" not in worker_src
    assert "FinalizationService" not in worker_src
    assert "FakeProvider" not in worker_src
    run_once = inspect.getsource(PublishRetryCommandWorker.run_once)
    assert "PreparationService" not in run_once
    assert "BarrierService" not in run_once
    assert "execute(" not in run_once or "claim" in run_once.lower()


def test_selector_safety_statuses_chosen_by_finalizer():
    assert DEFINITIVE_ATTEMPT_STATUS == STATUS_FAILED
    due_src = inspect.getsource(PublishAttemptOpsService.due_retry_content_ids)
    assert "STATUS_RETRYING" in due_src or "retrying" in due_src
    assert "operator_review" not in due_src
    assert "STATUS_FAILED" not in due_src or "retrying" in due_src
    claim_src = inspect.getsource(PublishResilienceService.claim_due_retries)
    assert "STATUS_RETRYING" in claim_src or "retrying" in claim_src
    recover_src = inspect.getsource(PublishResilienceService.recover_stale_attempts)
    assert "STATUS_IN_PROGRESS" in recover_src or "in_progress" in recover_src


def test_classifier_success_requires_external_id():
    ok = classify_provider_result(
        ProviderExecutionResult(outcome="success", external_post_id="p1"),
    )
    assert ok.outcome == "SUCCESS"
    missing = classify_provider_result(
        ProviderExecutionResult(outcome="success", external_post_id=None),
    )
    assert missing.outcome == "AMBIGUOUS"
    malformed = classify_provider_result({"outcome": "success"})
    assert malformed.outcome == "AMBIGUOUS"


def test_fake_provider_invocation_counter():
    async def _inner():
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        assert fake.invocation_count == 0
        await fake.execute(
            __import__(
                "app.services.publish_retry_command_provider_port",
                fromlist=["ProviderExecutionRequest"],
            ).ProviderExecutionRequest(
                command_id=uuid.uuid4(),
                resulting_attempt_id=uuid.uuid4(),
                platform="telegram",
            ),
        )
        assert fake.invocation_count == 1

    asyncio.run(_inner())


def test_production_flags_default_false():
    config_src = (SERVICES_DIR.parent / "core" / "config.py").read_text(encoding="utf-8")
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED: bool = False" in config_src
    assert "PUBLISH_RETRY_COMMANDS_ENABLED: bool = False" in config_src
    assert "PUBLISH_RETRY_COMMAND_WORKER_ENABLED: bool = False" in config_src
    assert "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED: bool = False" in config_src


# ---------------------------------------------------------------------------
# Happy / outcome path tests
# ---------------------------------------------------------------------------


def test_a_success_exactly_one_invocation():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                provider=fake,
            )
        assert result.ok is True
        assert result.outcome == "succeeded"
        assert fake.invocation_count == 1
        assert result.provider_invocation_count == 1
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            att = await _reload_attempt(db, cmd.resulting_attempt_id)
            assert cmd.status == "succeeded"
            assert cmd.provider_outcome == "known_success"
            assert cmd.finished_at is not None
            assert cmd.lease_expires_at is None
            assert att.status == STATUS_SUCCESS
            assert att.retryable is False
            assert att.next_retry_at is None
            assert att.external_post_id == "fake-post-1"
            assert att.finished_at is not None
            assert att.retry_command_id == cmd.id
        assert cmd_metrics.snapshot()["retry_command_provider_calls_total"] == 1
        assert cmd_metrics.snapshot()["retry_command_provider_success_total"] == 1
        assert cmd_metrics.snapshot()["retry_command_finalize_total"] == 1

    _run(body)


def test_b_definitive_failure():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.DEFINITIVE_FAILURE)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "failed"
        assert fake.invocation_count == 1
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            att = await _reload_attempt(db, cmd.resulting_attempt_id)
            assert cmd.status == "failed"
            assert cmd.provider_outcome == "known_failure"
            assert att.status == STATUS_FAILED
            assert att.retryable is False
            assert att.next_retry_at is None

    _run(body)


def test_c_ambiguous_result():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.AMBIGUOUS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "ambiguous"
        assert fake.invocation_count == 1
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            att = await _reload_attempt(db, cmd.resulting_attempt_id)
            assert cmd.status == "ambiguous"
            assert att.status == STATUS_OPERATOR_REVIEW
            assert att.retryable is False
            assert att.next_retry_at is None

    _run(body)


def test_d_timeout_exception_ambiguous():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.TIMEOUT)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "ambiguous"
        assert fake.invocation_count == 1

    _run(body)


def test_e_unknown_exception_ambiguous():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.EXCEPTION)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "ambiguous"
        assert fake.invocation_count == 1

    _run(body)


def test_f_malformed_result_ambiguous():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.MALFORMED, malformed_payload={"bad": True})
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "ambiguous"
        assert fake.invocation_count == 1

    _run(body)


def test_g_success_missing_external_id_ambiguous():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS_MISSING_EXTERNAL_ID)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "ambiguous"
        assert fake.invocation_count == 1
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.status == "ambiguous"

    _run(body)


# ---------------------------------------------------------------------------
# Duplicate / no-replay
# ---------------------------------------------------------------------------


def test_h_duplicate_after_success_zero_calls():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            r1 = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
            r2 = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert r1.outcome == "succeeded"
        assert r2.outcome == "already_finalized"
        assert fake.invocation_count == 1

    _run(body)


def test_i_duplicate_after_failure_zero_calls():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.DEFINITIVE_FAILURE)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
            r2 = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert r2.outcome == "already_finalized"
        assert fake.invocation_count == 1

    _run(body)


def test_j_duplicate_after_ambiguous_zero_calls():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.AMBIGUOUS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
            r2 = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert r2.outcome == "already_finalized"
        assert fake.invocation_count == 1

    _run(body)


def test_k_duplicate_while_provider_write_started_zero_calls():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(
                db,
                fx,
                command_status="provider_write_started",
                provider_write_started=True,
                link_attempt=True,
                attempt_failure_code=WRITE_STARTED_FAILURE_CODE,
                lease_expires_sql="NULL",
            )
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "already_barriered_no_replay"
        assert fake.invocation_count == 0

    _run(body)


def test_l_concurrent_executors_provider_at_most_one():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)

        async def run_one():
            return await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )

        with _gates_on(), _eligible():
            results = await asyncio.gather(run_one(), run_one())

        assert fake.invocation_count <= 1
        terminals = [r for r in results if r.outcome == "succeeded"]
        no_replay = [
            r for r in results
            if r.outcome in ("already_barriered_no_replay", "already_finalized", "blocked_barrier")
        ]
        assert len(terminals) == 1
        assert len(no_replay) == 1
        assert sum(1 for r in results if r.provider_invoked) == 1
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.status == "succeeded"
            attempts = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.retry_command_id == fx.command_id,
                    ),
                )
            ).scalars().all()
            assert len(attempts) == 1
            assert attempts[0].next_retry_at is None
            assert attempts[0].retryable is False

    _run(body)


# ---------------------------------------------------------------------------
# Pre-barrier blocks
# ---------------------------------------------------------------------------


def test_m_preparation_blocked_zero_provider():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible(_deny()):
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "blocked_preparation"
        assert fake.invocation_count == 0

    _run(body)


def test_n_barrier_denied_zero_provider():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx, link_attempt=True)

        # Prep eligible, barrier denied via live success injected only for barrier.
        allow = _allow()
        live_ok = MagicMock(
            has_live_success=False,
            content_status="failed",
            current_publish_version="pv_test",
            account_status="connected",
            now=datetime.now(timezone.utc),
        )
        with _gates_on(), patch(
            "app.services.publish_retry_command_preparation_service."
            "evaluate_manual_retry_eligibility",
            return_value=allow,
        ), patch(
            "app.services.publish_retry_command_preparation_service."
            "build_manual_retry_live_state",
            new_callable=AsyncMock,
            return_value=live_ok,
        ), patch(
            "app.services.publish_retry_command_barrier_service."
            "evaluate_manual_retry_eligibility",
            return_value=_deny(reason_code="not_on_allowlist"),
        ), patch(
            "app.services.publish_retry_command_barrier_service."
            "build_manual_retry_live_state",
            new_callable=AsyncMock,
            return_value=live_ok,
        ):
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "blocked_barrier"
        assert fake.invocation_count == 0

    _run(body)


def test_o_wrong_owner_zero_provider():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx, lease_owner=WORKER_A)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_B, provider=fake,
            )
        assert result.outcome == "blocked_preparation"
        assert fake.invocation_count == 0

    _run(body)


def test_p_expired_lease_zero_provider():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(
                db, fx, lease_expires_sql="NOW() - interval '1 minute'",
            )
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "blocked_preparation"
        assert fake.invocation_count == 0

    _run(body)


def test_q_execution_flag_false_pre_barrier_zero_provider():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=False), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "disabled"
        assert fake.invocation_count == 0

    _run(body)


def test_r_flag_flips_false_after_barrier_still_one_call():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)

        original = PublishRetryCommandBarrierService.cross_barrier
        disable_patcher = None

        async def cross_then_disable(*args, **kwargs):
            nonlocal disable_patcher
            result = await original(*args, **kwargs)
            if result.outcome == "barrier_crossed" and disable_patcher is None:
                disable_patcher = patch.object(
                    settings, "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED", False,
                )
                disable_patcher.start()
            return result

        with _gates_on(), _eligible(), patch.object(
            PublishRetryCommandBarrierService,
            "cross_barrier",
            side_effect=cross_then_disable,
        ):
            try:
                result = await PublishRetryCommandExecutor.execute(
                    factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
                )
            finally:
                if disable_patcher is not None:
                    disable_patcher.stop()
        assert result.outcome == "succeeded"
        assert fake.invocation_count == 1

    _run(body)


# ---------------------------------------------------------------------------
# Crash boundaries
# ---------------------------------------------------------------------------


def test_s_crash_after_preparation_future_safe():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            async with factory() as db:
                prep = await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A, commit=True,
                )
            assert prep.ok is True
            # Crash before barrier — re-run full executor
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "succeeded"
        assert fake.invocation_count == 1
        async with factory() as db:
            attempts = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.retry_command_id == fx.command_id,
                    ),
                )
            ).scalars().all()
            assert len(attempts) == 1

    _run(body)


def test_t_crash_after_barrier_before_provider_no_replay():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            async with factory() as db:
                await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A, commit=True,
                )
            async with factory() as db:
                barrier = await PublishRetryCommandBarrierService.cross_barrier(
                    db, command_id=fx.command_id, worker_id=WORKER_A, commit=True,
                )
            assert barrier.outcome == "barrier_crossed"
            # Crash before provider — future executor must NOT call provider
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "already_barriered_no_replay"
        assert fake.invocation_count == 0
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.status == "provider_write_started"

    _run(body)


def test_u_crash_after_provider_success_before_finalize_no_replay():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            async with factory() as db:
                await PublishRetryCommandPreparationService.prepare(
                    db, command_id=fx.command_id, worker_id=WORKER_A, commit=True,
                )
            async with factory() as db:
                await PublishRetryCommandBarrierService.cross_barrier(
                    db, command_id=fx.command_id, worker_id=WORKER_A, commit=True,
                )
            # Simulate provider already called (invocation counted) then crash
            fake.invocation_count = 1
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "already_barriered_no_replay"
        # No additional call beyond the simulated prior invocation
        assert fake.invocation_count == 1
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.status == "provider_write_started"

    _run(body)


def test_v_finalization_db_failure_no_replay():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)

        with _gates_on(), _eligible(), patch.object(
            PublishRetryCommandFinalizationService,
            "finalize",
            side_effect=RuntimeError("finalize boom"),
        ):
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "post_provider_finalize_failed"
        assert fake.invocation_count == 1

        # Retry must not call provider again
        with _gates_on(), _eligible():
            r2 = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert r2.outcome == "already_barriered_no_replay"
        assert fake.invocation_count == 1
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            assert cmd.status == "provider_write_started"

    _run(body)


def test_w_finalizer_duplicate_idempotent():
    async def body(factory):
        fx = _Fixture()
        async with factory() as db:
            await _seed_claimed(
                db,
                fx,
                command_status="provider_write_started",
                provider_write_started=True,
                link_attempt=True,
                attempt_failure_code=WRITE_STARTED_FAILURE_CODE,
                lease_expires_sql="NULL",
            )
        classified = ClassifiedProviderOutcome(
            outcome="SUCCESS",
            external_post_id="p-1",
            reason_code="provider_success",
        )
        with _gates_on():
            async with factory() as db:
                r1 = await PublishRetryCommandFinalizationService.finalize(
                    db,
                    command_id=fx.command_id,
                    classified=classified,
                    worker_id=WORKER_A,
                    commit=True,
                )
            async with factory() as db:
                cmd_after = await _reload_command(db, fx.command_id)
                finished_at = cmd_after.finished_at
                r2 = await PublishRetryCommandFinalizationService.finalize(
                    db,
                    command_id=fx.command_id,
                    classified=ClassifiedProviderOutcome(
                        outcome="DEFINITIVE_FAILURE",
                        failure_code="should_not_apply",
                    ),
                    worker_id=WORKER_A,
                    commit=True,
                )
                cmd2 = await _reload_command(db, fx.command_id)
        assert r1.outcome == "succeeded"
        assert r2.outcome == "already_finalized"
        assert cmd2.status == "succeeded"
        assert cmd2.provider_outcome == "known_success"
        assert cmd2.finished_at == finished_at

    _run(body)


# ---------------------------------------------------------------------------
# Terminal attempt selector safety / lineage
# ---------------------------------------------------------------------------


def test_xyz_aa_terminal_attempts_never_retryable():
    async def body(factory):
        for mode, expected_cmd in (
            (FakeProviderMode.SUCCESS, "succeeded"),
            (FakeProviderMode.DEFINITIVE_FAILURE, "failed"),
            (FakeProviderMode.AMBIGUOUS, "ambiguous"),
        ):
            fx = _Fixture()
            fake = FakeProviderExecutor(mode)
            async with factory() as db:
                await _seed_claimed(db, fx)
            with _gates_on(), _eligible():
                await PublishRetryCommandExecutor.execute(
                    factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
                )
            async with factory() as db:
                cmd = await _reload_command(db, fx.command_id)
                att = await _reload_attempt(db, cmd.resulting_attempt_id)
                assert cmd.status == expected_cmd
                assert att.retryable is False
                assert att.next_retry_at is None
                assert att.status != "retrying"
                assert att.retry_command_id == cmd.id

    _run(body)


def test_ag_lineage_preserved():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)
        with _gates_on(), _eligible():
            await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        async with factory() as db:
            cmd = await _reload_command(db, fx.command_id)
            att = await _reload_attempt(db, cmd.resulting_attempt_id)
            assert cmd.resulting_attempt_id == att.id
            assert att.retry_command_id == cmd.id
            assert att.content_id == cmd.content_id
            assert att.platform == cmd.platform
            assert att.account_id == cmd.publishing_account_id

    _run(body)


def test_ah_cross_tenant_mismatch_fails_closed():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx, account_tenant=fx.other_tenant_id)
        with _gates_on(), _eligible():
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome in ("blocked_preparation", "invariant_violation")
        assert fake.invocation_count == 0

    _run(body)


def test_ae_audit_failure_does_not_cause_second_provider_call():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)

        with _gates_on(), _eligible(), patch.object(
            PublishRetryCommandExecutor,
            "_audit_provider_call_started",
            side_effect=RuntimeError("audit boom"),
        ), patch.object(
            PublishRetryCommandFinalizationService,
            "record_finalization_audit",
            side_effect=RuntimeError("audit boom 2"),
        ):
            # _audit_provider_call_started catches internally; force raise before call path
            # by patching PlatformAuditService instead via side_effect on the method —
            # executor catches, so provider still called once.
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "succeeded"
        assert fake.invocation_count == 1

    _run(body)


def test_af_metrics_failure_does_not_cause_second_provider_call():
    async def body(factory):
        fx = _Fixture()
        fake = FakeProviderExecutor(FakeProviderMode.SUCCESS)
        async with factory() as db:
            await _seed_claimed(db, fx)

        from app.services import publish_retry_command_metrics as metrics_mod

        original = metrics_mod.inc

        def flaky_inc(name, amount=1):
            if name.startswith("retry_command_provider_"):
                raise RuntimeError(f"metrics boom:{name}")
            return original(name, amount)

        with _gates_on(), _eligible(), patch(
            "app.services.publish_retry_command_metrics.inc",
            side_effect=flaky_inc,
        ):
            result = await PublishRetryCommandExecutor.execute(
                factory, command_id=fx.command_id, worker_id=WORKER_A, provider=fake,
            )
        assert result.outcome == "succeeded"
        assert fake.invocation_count == 1

    _run(body)
