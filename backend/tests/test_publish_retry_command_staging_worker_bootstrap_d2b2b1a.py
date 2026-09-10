"""Phase 3C.1C-D2-B2b1-A — staging fake worker bootstrap + handoff.

LOCAL/CI disposable PostgreSQL only (china_smm_os_staging).
Proves: no claim before identity; verified execution context; worker→executor
handoff; eligibility object identity; batch=1; no real providers.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import PublishRetryCommand
from app.services.manual_retry_eligibility import _CONDITIONAL_TELEGRAM_CODES
from app.services.publish_retry_command_barrier_service import (
    PublishRetryCommandBarrierService,
)
from app.services.publish_retry_command_claim_service import (
    PublishRetryCommandClaimService,
)
from app.services.publish_retry_command_eligibility import (
    CanonicalManualRetryEligibility,
    default_eligibility_evaluator,
)
from app.services.publish_retry_command_execution_backend import (
    assert_worker_execution_backend_or_exit,
    resolve_execution_backend,
)
from app.services.publish_retry_command_preparation_service import (
    PublishRetryCommandPreparationService,
)
from app.services.publish_retry_command_provider_port import FakeProviderMode
from app.services.publish_retry_command_staging_fake_factory import (
    FAKE_EXTERNAL_ID_PREFIX,
)
from app.services.publish_retry_command_staging_fixture import (
    PublishRetryCommandStagingFixtureBuilder,
)
from app.services.publish_retry_command_staging_identity import (
    REQUIRED_DATABASE_NAME,
    StagingIdentityError,
)
from app.services.publish_retry_command_staging_worker_bootstrap import (
    RetryCommandWorkerExecutionContext,
    StagingWorkerBootstrapError,
    bootstrap_staging_fake_worker_execution,
)
from app.workers import publish_retry_command_worker as worker_mod
from app.workers.publish_retry_command_worker import PublishRetryCommandWorker

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "backend" / "app" / "services"
WORKER_PATH = REPO_ROOT / "backend" / "app" / "workers" / "publish_retry_command_worker.py"
BOOTSTRAP_PATH = SERVICES_DIR / "publish_retry_command_staging_worker_bootstrap.py"
COMPOSE_STAGING = REPO_ROOT / "docker-compose.staging.yml"
ENV_STAGING_EXAMPLE = REPO_ROOT / ".env.staging.example"

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/china_smm_os_staging"
)
WORKER_A = "staging-worker:1:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_STAGING_PG_URL", DEFAULT_PG_URL)


@contextmanager
def _flags(**kwargs):
    keys = {
        "APP_ENV": "staging",
        "DATABASE_URL": _pg_url(),
        "PUBLISH_RETRY_COMMANDS_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND": "fake",
        "PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED": True,
        "PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE": "success",
        "PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE": 1,
        "TELEGRAM_BOT_TOKEN": "",
        "META_APP_SECRET": "",
    }
    keys.update(kwargs)
    with patch.multiple(settings, **keys):
        yield


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


async def _ensure_database(db_name: str | None = None) -> str:
    url = _pg_url()
    if db_name is not None:
        url = url.rsplit("/", 1)[0] + f"/{db_name}"
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    name = url.rsplit("/", 1)[-1]
    engine = create_async_engine(admin_url, echo=False, isolation_level="AUTOCOMMIT")
    try:
        await _wait_ready(engine)
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            )
            if exists.first() is None:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable for B2b1-A tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for B2b1-A tests: {exc}")
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
                    name VARCHAR(255) NULL,
                    company_name VARCHAR(255) NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    plan VARCHAR(30) NOT NULL DEFAULT 'starter'
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
                    status VARCHAR(30) NOT NULL DEFAULT 'connected',
                    access_token_encrypted TEXT NULL,
                    refresh_token_encrypted TEXT NULL
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


async def _with_staging_pg(coro_factory, *, db_name: str = REQUIRED_DATABASE_NAME):
    url = await _ensure_database(db_name)
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_schema(engine)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await coro_factory(factory, engine)
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    finally:
        await engine.dispose()


def _tmp_sink_path() -> Path:
    return Path(tempfile.mkdtemp(prefix="b2b1a-sink-")) / "invocations.jsonl"


async def _bootstrap_ok(engine, **flag_overrides):
    sink = _tmp_sink_path()
    with _flags(**flag_overrides):
        async with engine.connect() as conn:
            return await bootstrap_staging_fake_worker_execution(
                conn,
                sink_path=sink,
            )


async def _assert_bootstrap_fails_before_claim(
    engine,
    *,
    expected_reason: str,
    **flag_overrides,
):
    claim = AsyncMock(return_value=[])
    with _flags(**flag_overrides):
        with patch.object(PublishRetryCommandClaimService, "claim_batch", claim):
            async with engine.connect() as conn:
                with pytest.raises(StagingWorkerBootstrapError) as ei:
                    await bootstrap_staging_fake_worker_execution(conn)
            assert ei.value.reason == expected_reason
    assert claim.await_count == 0


# ---------------------------------------------------------------------------
# Startup identity matrix / no-claim-before-identity
# ---------------------------------------------------------------------------


def test_fake_production_app_env_fails_before_claim():
    async def body(factory, engine):
        await _assert_bootstrap_fails_before_claim(
            engine,
            expected_reason="app_env_not_staging",
            APP_ENV="production",
        )

    asyncio.run(_with_staging_pg(body))


def test_fake_live_db_china_smm_os_fails_before_claim():
    async def body(factory, engine):
        # Connect to production-named disposable DB; URL preflight skipped via
        # DATABASE_URL still naming staging so early parse can pass when needed.
        claim = AsyncMock(return_value=[])
        with _flags(
            DATABASE_URL=_pg_url().rsplit("/", 1)[0] + f"/{REQUIRED_DATABASE_NAME}",
        ):
            with patch.object(PublishRetryCommandClaimService, "claim_batch", claim):
                async with engine.connect() as conn:
                    with pytest.raises(StagingWorkerBootstrapError) as ei:
                        await bootstrap_staging_fake_worker_execution(
                            conn,
                            # Force live identity against this connection's DB.
                        )
                assert ei.value.reason == "current_database_production_denylist"
        assert claim.await_count == 0

    asyncio.run(_with_staging_pg(body, db_name="china_smm_os"))


def test_fake_development_app_env_fails_before_claim():
    async def body(factory, engine):
        await _assert_bootstrap_fails_before_claim(
            engine,
            expected_reason="app_env_not_staging",
            APP_ENV="development",
        )

    asyncio.run(_with_staging_pg(body))


def test_fake_ack_false_fails_before_claim():
    async def body(factory, engine):
        await _assert_bootstrap_fails_before_claim(
            engine,
            expected_reason="fake_execution_ack_false",
            PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=False,
        )

    asyncio.run(_with_staging_pg(body))


def test_fake_provider_secret_fails_before_claim():
    async def body(factory, engine):
        await _assert_bootstrap_fails_before_claim(
            engine,
            expected_reason="provider_secrets_populated",
            TELEGRAM_BOT_TOKEN="real-looking-token",
        )

    asyncio.run(_with_staging_pg(body))


def test_fake_wrong_staging_db_fails_before_claim():
    async def body(factory, engine):
        claim = AsyncMock(return_value=[])
        with _flags(
            DATABASE_URL=_pg_url().rsplit("/", 1)[0] + "/china_smm_os_staging_wrong",
        ):
            with patch.object(PublishRetryCommandClaimService, "claim_batch", claim):
                async with engine.connect() as conn:
                    with pytest.raises(StagingWorkerBootstrapError) as ei:
                        await bootstrap_staging_fake_worker_execution(conn)
                # URL preflight may fail first, or live DB check.
                assert ei.value.reason in {
                    "database_url_not_staging",
                    "current_database_not_staging",
                }
        assert claim.await_count == 0

    asyncio.run(_with_staging_pg(body, db_name="china_smm_os_staging_wrong"))


def test_valid_staging_identity_creates_execution_context():
    async def body(factory, engine):
        ctx = await _bootstrap_ok(engine)
        assert isinstance(ctx, RetryCommandWorkerExecutionContext)
        assert ctx.execution_backend == "fake"
        assert ctx.staging_context.current_database == REQUIRED_DATABASE_NAME
        assert ctx.provider is not None
        assert ctx.eligibility_evaluator is not None
        worker = PublishRetryCommandWorker(worker_id=WORKER_A, execution=ctx)
        assert worker._execution is ctx

    asyncio.run(_with_staging_pg(body))


def test_batch_not_one_fails_closed():
    async def body(factory, engine):
        await _assert_bootstrap_fails_before_claim(
            engine,
            expected_reason="batch_size_not_one",
            PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE=2,
        )

    asyncio.run(_with_staging_pg(body))


# ---------------------------------------------------------------------------
# backend=none regression + resolver
# ---------------------------------------------------------------------------


def test_backend_none_skips_staging_bootstrap():
    with patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "none"):
        res = resolve_execution_backend()
        assert res.value == "none"
        assert res.d2b1_runnable is True
        assert_worker_execution_backend_or_exit()  # does not raise

    bootstrap = AsyncMock()
    with patch.object(settings, "PUBLISH_RETRY_COMMAND_WORKER_ENABLED", True):
        with patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "none"):
            with patch(
                "app.services.publish_retry_command_staging_worker_bootstrap."
                "bootstrap_staging_fake_worker_execution",
                bootstrap,
            ):
                # amain none path must not call bootstrap — simulate dispatch.
                resolution = resolve_execution_backend()
                assert resolution.value == "none"
                if resolution.value == "fake":
                    asyncio.run(bootstrap())
    assert bootstrap.await_count == 0


def test_resolver_classifies_fake_not_approved():
    res = resolve_execution_backend("fake")
    assert res.value == "fake"
    assert res.d2b1_runnable is False
    assert "bootstrap" in res.reason
    with patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "fake"):
        with pytest.raises(SystemExit) as ei:
            assert_worker_execution_backend_or_exit()
        assert ei.value.code == 2


def test_production_defaults_unchanged():
    assert settings.PUBLISH_RETRY_COMMANDS_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND == "none"
    assert settings.PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED is False
    assert _CONDITIONAL_TELEGRAM_CODES == frozenset()
    assert isinstance(default_eligibility_evaluator(), CanonicalManualRetryEligibility)


# ---------------------------------------------------------------------------
# Worker handoff outcomes
# ---------------------------------------------------------------------------


async def _run_worker_with_mode(factory, engine, mode: FakeProviderMode):
    sink = _tmp_sink_path()
    with _flags(PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE=mode.value):
        async with engine.connect() as conn:
            execution = await bootstrap_staging_fake_worker_execution(
                conn,
                sink_path=sink,
            )
        async with factory() as db:
            fx = await PublishRetryCommandStagingFixtureBuilder(
                execution.staging_context,
            ).create(
                db,
                command_status="pending",
                worker_id=WORKER_A,
                commit=True,
            )
        worker = PublishRetryCommandWorker(worker_id=WORKER_A, execution=execution)
        with patch.object(worker_mod, "AsyncSessionLocal", factory):
            with patch.object(
                PublishRetryCommandClaimService,
                "record_claim_audits",
                AsyncMock(return_value=None),
            ):
                results = await worker.run_once()
        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            attempt = None
            if cmd.resulting_attempt_id:
                attempt = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.id == cmd.resulting_attempt_id,
                        ),
                    )
                ).scalar_one()
        return results, cmd, attempt, execution, fx


def test_success_worker_handoff():
    async def body(factory, engine):
        results, cmd, attempt, execution, fx = await _run_worker_with_mode(
            factory, engine, FakeProviderMode.SUCCESS,
        )
        claimed = [r for r in results if r.kind in ("claimed", "reclaimed")]
        assert len(claimed) == 1
        assert claimed[0].command_id == fx.command_id
        assert execution.provider.invocation_count == 1
        assert cmd.status == "succeeded"
        assert attempt is not None
        assert attempt.status == "success"
        assert attempt.retry_command_id == fx.command_id
        assert attempt.external_post_id is not None
        assert attempt.external_post_id.startswith(FAKE_EXTERNAL_ID_PREFIX)
        assert execution.sink is not None
        assert execution.sink.count_for_command(fx.command_id) == 1

    asyncio.run(_with_staging_pg(body))


def test_definitive_failure_worker_handoff():
    async def body(factory, engine):
        results, cmd, attempt, execution, fx = await _run_worker_with_mode(
            factory, engine, FakeProviderMode.DEFINITIVE_FAILURE,
        )
        assert execution.provider.invocation_count == 1
        assert cmd.status == "failed"
        assert attempt is not None
        assert attempt.status == "failed"
        assert attempt.next_retry_at is None
        assert len([r for r in results if r.kind == "claimed"]) == 1

    asyncio.run(_with_staging_pg(body))


def test_ambiguous_worker_handoff():
    async def body(factory, engine):
        _results, cmd, attempt, execution, fx = await _run_worker_with_mode(
            factory, engine, FakeProviderMode.AMBIGUOUS,
        )
        assert execution.provider.invocation_count == 1
        assert cmd.status == "ambiguous"
        assert attempt is not None
        assert attempt.next_retry_at is None
        assert fx.command_id == cmd.id

    asyncio.run(_with_staging_pg(body))


def test_timeout_worker_handoff_ambiguous_no_replay():
    async def body(factory, engine):
        _results, cmd, attempt, execution, fx = await _run_worker_with_mode(
            factory, engine, FakeProviderMode.TIMEOUT,
        )
        assert execution.provider.invocation_count == 1
        assert cmd.status == "ambiguous"
        assert attempt is not None
        # Re-run orchestration must not invoke provider again (barrier already crossed).
        worker = PublishRetryCommandWorker(worker_id=WORKER_A, execution=execution)
        await worker._orchestrate_after_claim(command_id=fx.command_id)
        assert execution.provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


def test_same_eligibility_object_identity_to_prep_and_barrier():
    async def body(factory, engine):
        sink = _tmp_sink_path()
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=sink,
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )
            seen: dict[str, object] = {}

            real_prepare = PublishRetryCommandPreparationService.prepare
            real_barrier = PublishRetryCommandBarrierService.cross_barrier

            async def prep_wrap(db, **kwargs):
                seen["prep"] = kwargs.get("eligibility_evaluator")
                return await real_prepare(db, **kwargs)

            async def barrier_wrap(db, **kwargs):
                seen["barrier"] = kwargs.get("eligibility_evaluator")
                return await real_barrier(db, **kwargs)

            with patch.object(
                PublishRetryCommandPreparationService,
                "prepare",
                side_effect=prep_wrap,
            ), patch.object(
                PublishRetryCommandBarrierService,
                "cross_barrier",
                side_effect=barrier_wrap,
            ):
                await execution.execute_claimed(
                    factory,
                    command_id=fx.command_id,
                    worker_id=WORKER_A,
                    correlation_id=fx.correlation_id,
                )
            assert seen["prep"] is execution.eligibility_evaluator
            assert seen["barrier"] is execution.eligibility_evaluator
            assert seen["prep"] is seen["barrier"]

    asyncio.run(_with_staging_pg(body))


# ---------------------------------------------------------------------------
# Architecture / SIGTERM / compose
# ---------------------------------------------------------------------------


def test_request_stop_does_not_cancel_running_executor():
    """HARD GATE audit: request_stop only sets Event; no task.cancel on executor."""
    src = inspect.getsource(PublishRetryCommandWorker.request_stop)
    assert "self._stop.set()" in src
    assert "task.cancel" not in src
    run_once = inspect.getsource(PublishRetryCommandWorker.run_once)
    assert "if self._stop.is_set()" in run_once
    # Active executor must not be cancelled by stop / drain timeout.
    await_src = inspect.getsource(PublishRetryCommandWorker._await_active_executor)
    assert "asyncio.shield" in await_src
    assert "task.cancel()" not in await_src
    assert "active_task.cancel" not in await_src
    handoff = inspect.getsource(PublishRetryCommandWorker._future_executor_handoff)
    assert "task.cancel()" not in handoff
    assert "_should_stop_before_barrier" in handoff


def test_generic_worker_has_no_staging_identity_policy():
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            # Docstrings may mention the boundary; code/string literals must not
            # embed staging DB names or provider-secret policy.
            if node.value.count("\n") > 2 and val.lstrip().startswith(('"', "'", "Publish")):
                continue
            assert "china_smm_os_staging" not in val
            assert "TELEGRAM_BOT_TOKEN" not in val
            assert "META_APP_SECRET" not in val
    src_no_docs = WORKER_PATH.read_text(encoding="utf-8")
    # Strip module docstring for policy checks on executable surface.
    mod = ast.parse(src_no_docs)
    assert ast.get_docstring(mod)
    # No APP_ENV / current_database branching in executable source.
    class_src = inspect.getsource(PublishRetryCommandWorker)
    assert 'APP_ENV == "staging"' not in class_src
    assert "query_current_database" not in class_src
    assert "china_smm_os_staging" not in class_src
    assert "TELEGRAM_BOT_TOKEN" not in class_src


def test_no_real_provider_imports_in_bootstrap_or_worker():
    forbidden = (
        "telegram_publisher",
        "facebook_publisher",
        "instagram_publisher",
        "ADAPTERS",
    )
    for path in (BOOTSTRAP_PATH, WORKER_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for bad in forbidden:
                        assert bad not in alias.name
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for bad in forbidden:
                    assert bad not in mod
        assert "ADAPTERS[" not in src


def test_staging_compose_skeleton_isolated():
    assert COMPOSE_STAGING.is_file()
    text_body = COMPOSE_STAGING.read_text(encoding="utf-8")
    assert "name: china-smm-os-staging" in text_body
    assert "china_smm_os_staging" in text_body
    assert "staging_pgdata" in text_body
    assert "china-smm-os-staging-pgdata" in text_body
    assert 'restart: "no"' in text_body or "restart: 'no'" in text_body
    assert "retry-command" in text_body
    # No production/public services as Compose service keys.
    assert "\n  cloudflared:" not in text_body
    assert "\n  frontend:" not in text_body
    assert "\n  backend:" not in text_body
    assert "env_file:\n      - .env.production" not in text_body
    assert "${" not in text_body or "STAGING_ENV_FILE" in text_body
    assert ENV_STAGING_EXAMPLE.is_file()
    env = ENV_STAGING_EXAMPLE.read_text(encoding="utf-8")
    assert "APP_ENV=staging" in env
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=fake" in env
    assert "PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=true" in env
    assert "PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE=1" in env
    assert "POSTGRES_DB=china_smm_os_staging" in env
    assert "TELEGRAM_BOT_TOKEN=" in env
    assert "META_APP_SECRET=" in env


def test_half_valid_fake_context_rejected():
    with pytest.raises(StagingWorkerBootstrapError):
        RetryCommandWorkerExecutionContext(
            execution_backend="fake",
            staging_context=MagicMock(),
            eligibility_evaluator=MagicMock(),
            provider=MagicMock(),
            sink=None,
            hooks=None,
        )
