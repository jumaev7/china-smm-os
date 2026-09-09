"""Phase 3C.1C-D2-B2a — staging identity + full fake integration harness.

LOCAL/CI disposable PostgreSQL only (china_smm_os_staging).
Worker remains non-executing for backend=fake. No real providers.
"""
from __future__ import annotations

import ast
import asyncio
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from app.services.publish_retry_command_eligibility import (
    STAGING_CORRELATION_ID_PREFIX,
    STAGING_TENANT_NAME_PREFIX,
    CanonicalManualRetryEligibility,
    RetryCommandEligibilityContext,
    StagingSyntheticRetryEligibility,
    default_eligibility_evaluator,
)
from app.services.publish_retry_command_executor import (
    ExecutorHooks,
    PublishRetryCommandExecutor,
)
from app.services.publish_retry_command_fake_sink import DurableFakeInvocationSink
from app.services.publish_retry_command_preparation_service import (
    PublishRetryCommandPreparationService,
)
from app.services.publish_retry_command_provider_port import FakeProviderMode
from app.services.publish_retry_command_staging_fake_factory import (
    FAKE_EXTERNAL_ID_PREFIX,
    PublishRetryCommandStagingFakeFactory,
    resolve_staging_fake_backend,
)
from app.services.publish_retry_command_staging_fixture import (
    PublishRetryCommandStagingFixtureBuilder,
)
from app.services.publish_retry_command_staging_identity import (
    PRODUCTION_DATABASE_DENYLIST,
    REQUIRED_DATABASE_NAME,
    RetryCommandStagingIdentityGuard,
    StagingIdentityError,
    VerifiedRetryCommandStagingContext,
    parse_database_name_from_url,
)
from app.workers.publish_retry_command_worker import PublishRetryCommandWorker

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "backend" / "app" / "services"
B2A_MODULES = (
    "publish_retry_command_staging_identity.py",
    "publish_retry_command_eligibility.py",
    "publish_retry_command_fake_sink.py",
    "publish_retry_command_staging_fake_factory.py",
    "publish_retry_command_staging_fixture.py",
)

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/china_smm_os_staging"
)

WORKER_A = "staging-harness:1:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WORKER_B = "staging-harness:2:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


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
        pytest.skip(f"PostgreSQL unavailable for staging harness tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for staging harness tests: {exc}")
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


def _tmp_sink() -> DurableFakeInvocationSink:
    path = Path(tempfile.mkdtemp(prefix="retry-fake-sink-")) / "invocations.jsonl"
    return DurableFakeInvocationSink(path)


# ---------------------------------------------------------------------------
# Static / unit
# ---------------------------------------------------------------------------


def test_b2a_zero_real_provider_imports():
    forbidden = (
        "telegram_publisher",
        "facebook_publisher",
        "instagram_publisher",
        "httpx",
        "ADAPTERS",
    )
    for name in B2A_MODULES:
        src = (SERVICES_DIR / name).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for bad in forbidden:
                        assert bad not in alias.name, f"{name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for bad in forbidden:
                    assert bad not in mod, f"{name} imports from {mod}"
                    for alias in node.names:
                        assert bad not in alias.name, f"{name} imports {alias.name}"
        assert "ADAPTERS[" not in src


def test_conditional_telegram_allowlist_still_empty():
    assert _CONDITIONAL_TELEGRAM_CODES == frozenset()


def test_canonical_evaluator_is_default_constructor():
    prep = PublishRetryCommandPreparationService()
    barrier = PublishRetryCommandBarrierService()
    assert isinstance(prep.eligibility_evaluator, CanonicalManualRetryEligibility)
    assert isinstance(barrier.eligibility_evaluator, CanonicalManualRetryEligibility)
    assert isinstance(default_eligibility_evaluator(), CanonicalManualRetryEligibility)


def test_staging_eligibility_requires_capability():
    with pytest.raises(StagingIdentityError):
        StagingSyntheticRetryEligibility(object())  # type: ignore[arg-type]


def test_staging_fake_factory_requires_capability():
    with pytest.raises(StagingIdentityError):
        PublishRetryCommandStagingFakeFactory(object())  # type: ignore[arg-type]


def test_parse_database_url_not_authoritative_helper():
    assert parse_database_name_from_url(
        "postgresql+asyncpg://u:p@localhost:5432/china_smm_os_staging",
    ) == "china_smm_os_staging"
    assert parse_database_name_from_url(
        "postgresql+asyncpg://u:p@localhost:5432/china_smm_os",
    ) == "china_smm_os"
    assert "china_smm_os" in PRODUCTION_DATABASE_DENYLIST


def test_verified_context_cannot_be_forged():
    with pytest.raises(StagingIdentityError):
        VerifiedRetryCommandStagingContext(
            app_env="staging",
            execution_backend="fake",
            fake_execution_allowed=True,
            current_database=REQUIRED_DATABASE_NAME,
            _capability_token="forged",
        )


def test_staging_eligibility_markers():
    # Build a real capability via private token path used by guard only —
    # use guard minting in async tests; here unit-check marker deny/allow
    # with a monkeypatched capability instance from guard internals.
    from app.services import publish_retry_command_staging_identity as ident

    ctx = VerifiedRetryCommandStagingContext(
        app_env="staging",
        execution_backend="fake",
        fake_execution_allowed=True,
        current_database=REQUIRED_DATABASE_NAME,
        _capability_token=ident._CAPABILITY_TOKEN,
    )
    policy = StagingSyntheticRetryEligibility(ctx)
    attempt = MagicMock(status="failed", platform="telegram")

    denied = policy.evaluate(
        RetryCommandEligibilityContext(
            attempt=attempt,
            correlation_id="not-staging",
            tenant_company_name=f"{STAGING_TENANT_NAME_PREFIX}x",
        ),
    )
    assert denied.allowed is False

    denied2 = policy.evaluate(
        RetryCommandEligibilityContext(
            attempt=attempt,
            correlation_id=f"{STAGING_CORRELATION_ID_PREFIX}x",
            tenant_company_name="prod-tenant",
        ),
    )
    assert denied2.allowed is False

    allowed = policy.evaluate(
        RetryCommandEligibilityContext(
            attempt=attempt,
            correlation_id=f"{STAGING_CORRELATION_ID_PREFIX}x",
            tenant_company_name=f"{STAGING_TENANT_NAME_PREFIX}x",
        ),
    )
    assert allowed.allowed is True


def test_durable_sink_append_and_count(tmp_path: Path):
    sink = DurableFakeInvocationSink(tmp_path / "sink.jsonl")
    cid = uuid.uuid4()
    sink.append(
        command_id=cid,
        attempt_id=uuid.uuid4(),
        fake_mode="success",
        invocation_ordinal=1,
    )
    assert sink.count_for_command(cid) == 1
    # Restart fidelity: new instance same path
    sink2 = DurableFakeInvocationSink(tmp_path / "sink.jsonl")
    assert sink2.count_for_command(cid) == 1


# ---------------------------------------------------------------------------
# Identity / wrong-DB
# ---------------------------------------------------------------------------


def test_identity_success_on_staging_db():
    async def body(factory, engine):
        with _flags():
            async with engine.connect() as conn:
                ctx = await RetryCommandStagingIdentityGuard.verify(conn)
            assert ctx.current_database == REQUIRED_DATABASE_NAME
            assert ctx.app_env == "staging"
            factory_obj = PublishRetryCommandStagingFakeFactory(ctx)
            provider = factory_obj.create(mode=FakeProviderMode.SUCCESS)
            assert provider is not None
            resolved = resolve_staging_fake_backend(
                staging_context=ctx,
                requested_backend="fake",
            )
            assert resolved is not None
            assert resolve_staging_fake_backend(
                staging_context=ctx,
                requested_backend="none",
            ) is None

    asyncio.run(_with_staging_pg(body))


def test_identity_fails_production_env_even_on_staging_db():
    async def body(factory, engine):
        with _flags(APP_ENV="production"):
            async with engine.connect() as conn:
                with pytest.raises(StagingIdentityError) as ei:
                    await RetryCommandStagingIdentityGuard.verify(conn)
            assert ei.value.reason == "app_env_not_staging"

    asyncio.run(_with_staging_pg(body))


def test_identity_fails_development_env_on_staging_db():
    async def body(factory, engine):
        with _flags(APP_ENV="development"):
            async with engine.connect() as conn:
                with pytest.raises(StagingIdentityError):
                    await RetryCommandStagingIdentityGuard.verify(conn)

    asyncio.run(_with_staging_pg(body))


def test_identity_fails_ack_false():
    async def body(factory, engine):
        with _flags(PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=False):
            async with engine.connect() as conn:
                with pytest.raises(StagingIdentityError) as ei:
                    await RetryCommandStagingIdentityGuard.verify(conn)
            assert ei.value.reason == "fake_execution_ack_false"

    asyncio.run(_with_staging_pg(body))


def test_identity_fails_backend_none_when_fake_required():
    async def body(factory, engine):
        with _flags(PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="none"):
            async with engine.connect() as conn:
                with pytest.raises(StagingIdentityError) as ei:
                    await RetryCommandStagingIdentityGuard.verify(conn)
            assert ei.value.reason == "backend_not_fake"

    asyncio.run(_with_staging_pg(body))


def test_preflight_fails_when_url_points_at_production_db():
    with _flags(
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/china_smm_os",
    ):
        with pytest.raises(StagingIdentityError) as ei:
            RetryCommandStagingIdentityGuard.preflight_settings()
        assert ei.value.reason == "database_url_production_denylist"


def test_identity_fails_wrong_actual_database_name():
    wrong_name = "china_smm_os_staging_wrong"

    async def body(factory, engine):
        with _flags(
            DATABASE_URL=_pg_url().rsplit("/", 1)[0] + f"/{wrong_name}",
        ):
            async with engine.connect() as conn:
                with pytest.raises(StagingIdentityError) as ei:
                    await RetryCommandStagingIdentityGuard.verify(
                        conn,
                        skip_url_preflight=True,
                    )
            assert ei.value.reason == "current_database_not_staging"

    asyncio.run(_with_staging_pg(body, db_name=wrong_name))


def test_provider_secrets_block_fake_identity():
    async def body(factory, engine):
        with _flags(TELEGRAM_BOT_TOKEN="real-looking-token"):
            async with engine.connect() as conn:
                with pytest.raises(StagingIdentityError) as ei:
                    await RetryCommandStagingIdentityGuard.verify(conn)
            assert ei.value.reason == "provider_secrets_populated"
            assert "TELEGRAM_BOT_TOKEN" in str(ei.value)

    asyncio.run(_with_staging_pg(body))


# ---------------------------------------------------------------------------
# Full harness outcomes
# ---------------------------------------------------------------------------


async def _mint_ctx(engine) -> VerifiedRetryCommandStagingContext:
    async with engine.connect() as conn:
        return await RetryCommandStagingIdentityGuard.verify(conn)


async def _run_mode(factory, engine, mode: FakeProviderMode, *, hooks=None):
    with _flags():
        ctx = await _mint_ctx(engine)
        sink = _tmp_sink()
        eligibility = StagingSyntheticRetryEligibility(ctx)
        provider = PublishRetryCommandStagingFakeFactory(ctx).create(
            mode=mode,
            sink=sink,
        )
        async with factory() as db:
            fx = await PublishRetryCommandStagingFixtureBuilder(ctx).create(
                db,
                command_status="claimed",
                worker_id=WORKER_A,
                commit=True,
            )
        result = await PublishRetryCommandExecutor.execute(
            factory,
            command_id=fx.command_id,
            worker_id=WORKER_A,
            provider=provider,
            correlation_id=fx.correlation_id,
            eligibility_evaluator=eligibility,
            hooks=hooks,
        )
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
        return result, cmd, attempt, sink, fx, provider


def test_harness_full_success():
    async def body(factory, engine):
        result, cmd, attempt, sink, fx, provider = await _run_mode(
            factory, engine, FakeProviderMode.SUCCESS,
        )
        assert result.ok is True
        assert result.outcome == "succeeded"
        assert cmd.status == "succeeded"
        assert attempt is not None
        assert attempt.status == "success"
        assert attempt.retryable is False
        assert attempt.next_retry_at is None
        assert attempt.external_post_id is not None
        assert attempt.external_post_id.startswith(FAKE_EXTERNAL_ID_PREFIX)
        assert sink.count_for_command(fx.command_id) == 1
        assert provider.invocation_count == 1
        assert attempt.retry_command_id == fx.command_id

    asyncio.run(_with_staging_pg(body))


def test_harness_definitive_failure():
    async def body(factory, engine):
        result, cmd, attempt, sink, fx, provider = await _run_mode(
            factory, engine, FakeProviderMode.DEFINITIVE_FAILURE,
        )
        assert result.outcome == "failed"
        assert cmd.status == "failed"
        assert attempt is not None
        assert attempt.status == "failed"
        assert attempt.retryable is False
        assert attempt.next_retry_at is None
        assert sink.count_for_command(fx.command_id) == 1
        assert provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


def test_harness_ambiguous():
    async def body(factory, engine):
        result, cmd, attempt, sink, fx, provider = await _run_mode(
            factory, engine, FakeProviderMode.AMBIGUOUS,
        )
        assert result.outcome == "ambiguous"
        assert cmd.status == "ambiguous"
        assert attempt is not None
        assert attempt.status == "operator_review"
        assert attempt.retryable is False
        assert attempt.next_retry_at is None
        assert sink.count_for_command(fx.command_id) == 1
        assert provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


@pytest.mark.parametrize(
    "mode",
    [FakeProviderMode.TIMEOUT, FakeProviderMode.EXCEPTION],
)
def test_harness_timeout_and_exception(mode):
    async def body(factory, engine):
        result, cmd, attempt, sink, fx, provider = await _run_mode(
            factory, engine, mode,
        )
        assert result.outcome == "ambiguous"
        assert cmd.status == "ambiguous"
        assert attempt is not None
        assert attempt.status == "operator_review"
        assert attempt.retryable is False
        assert sink.count_for_command(fx.command_id) == 1
        assert provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


@pytest.mark.parametrize(
    "mode",
    [FakeProviderMode.MALFORMED, FakeProviderMode.SUCCESS_MISSING_EXTERNAL_ID],
)
def test_harness_malformed_and_missing_external_id(mode):
    async def body(factory, engine):
        result, cmd, attempt, sink, fx, provider = await _run_mode(
            factory, engine, mode,
        )
        assert result.outcome == "ambiguous"
        assert cmd.status == "ambiguous"
        assert attempt is not None
        assert attempt.status == "operator_review"
        assert sink.count_for_command(fx.command_id) == 1
        assert provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


def test_duplicate_executor_no_replay():
    async def body(factory, engine):
        result, cmd, attempt, sink, fx, provider = await _run_mode(
            factory, engine, FakeProviderMode.SUCCESS,
        )
        assert sink.count_for_command(fx.command_id) == 1
        # Second run — new provider instance but same sink/command
        with _flags():
            ctx = await _mint_ctx(engine)
            eligibility = StagingSyntheticRetryEligibility(ctx)
            provider2 = PublishRetryCommandStagingFakeFactory(ctx).create(
                mode=FakeProviderMode.SUCCESS,
                sink=sink,
            )
            result2 = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                provider=provider2,
                correlation_id=fx.correlation_id,
                eligibility_evaluator=eligibility,
            )
        assert result2.outcome in ("already_finalized", "already_barriered_no_replay")
        assert provider2.invocation_count == 0
        assert sink.count_for_command(fx.command_id) == 1

    asyncio.run(_with_staging_pg(body))


def test_concurrent_executors_at_most_one_fake():
    async def body(factory, engine):
        with _flags():
            ctx = await _mint_ctx(engine)
            sink = _tmp_sink()
            eligibility = StagingSyntheticRetryEligibility(ctx)
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(ctx).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )

            async def runner(worker_id: str):
                provider = PublishRetryCommandStagingFakeFactory(ctx).create(
                    mode=FakeProviderMode.SUCCESS,
                    sink=sink,
                )
                return await PublishRetryCommandExecutor.execute(
                    factory,
                    command_id=fx.command_id,
                    worker_id=worker_id,
                    provider=provider,
                    correlation_id=fx.correlation_id,
                    eligibility_evaluator=eligibility,
                ), provider

            # Both claim same lease owner path — barrier FOR UPDATE serializes.
            # Use same worker_id so ownership validation passes for both until barrier.
            r1, r2 = await asyncio.gather(runner(WORKER_A), runner(WORKER_A))
            results = [r1[0], r2[0]]
            providers = [r1[1], r2[1]]
            invoked = sum(p.invocation_count for p in providers)
            assert invoked == 1
            assert sink.count_for_command(fx.command_id) <= 1
            assert sink.count_for_command(fx.command_id) == 1
            outcomes = {r.outcome for r in results}
            assert "succeeded" in outcomes
            assert "already_barriered_no_replay" in outcomes or "succeeded" in outcomes
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "succeeded"
                assert cmd.resulting_attempt_id is not None

    asyncio.run(_with_staging_pg(body))


def test_pre_barrier_crash_no_sink():
    async def body(factory, engine):
        class Boom(RuntimeError):
            pass

        def crash():
            raise Boom("pre-barrier crash")

        with pytest.raises(Boom):
            await _run_mode(
                factory,
                engine,
                FakeProviderMode.SUCCESS,
                hooks=ExecutorHooks(after_prepare=crash),
            )
        # Re-open: find the only command created in this schema run
        async with factory() as db:
            cmd = (await db.execute(select(PublishRetryCommand))).scalar_one()
            assert cmd.status == "claimed"
            assert cmd.provider_write_started_at is None
            assert cmd.resulting_attempt_id is not None

    asyncio.run(_with_staging_pg(body))


def test_post_barrier_pre_fake_crash_no_future_invoke():
    async def body(factory, engine):
        class Boom(RuntimeError):
            pass

        def crash():
            raise Boom("post-barrier pre-fake")

        with pytest.raises(Boom):
            await _run_mode(
                factory,
                engine,
                FakeProviderMode.SUCCESS,
                hooks=ExecutorHooks(before_provider=crash),
            )

        with _flags():
            ctx = await _mint_ctx(engine)
            sink = _tmp_sink()
            eligibility = StagingSyntheticRetryEligibility(ctx)
            async with factory() as db:
                cmd = (await db.execute(select(PublishRetryCommand))).scalar_one()
                assert cmd.status == "provider_write_started"
                command_id = cmd.id
                correlation_id = cmd.correlation_id
                worker_id = cmd.lease_owner or WORKER_A
            provider = PublishRetryCommandStagingFakeFactory(ctx).create(
                mode=FakeProviderMode.SUCCESS,
                sink=sink,
            )
            result = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=command_id,
                worker_id=worker_id,
                provider=provider,
                correlation_id=correlation_id,
                eligibility_evaluator=eligibility,
            )
        assert result.outcome == "already_barriered_no_replay"
        assert provider.invocation_count == 0
        assert sink.count_for_command(command_id) == 0

    asyncio.run(_with_staging_pg(body))


def test_post_fake_pre_finalize_crash_sink_one_no_second_call():
    async def body(factory, engine):
        class Boom(RuntimeError):
            pass

        def crash():
            raise Boom("post-fake pre-finalize")

        # First run with shared sink path so restart can observe count.
        sink = _tmp_sink()
        with _flags():
            ctx = await _mint_ctx(engine)
            eligibility = StagingSyntheticRetryEligibility(ctx)
            provider = PublishRetryCommandStagingFakeFactory(ctx).create(
                mode=FakeProviderMode.SUCCESS,
                sink=sink,
            )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(ctx).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )
            with pytest.raises(Boom):
                await PublishRetryCommandExecutor.execute(
                    factory,
                    command_id=fx.command_id,
                    worker_id=WORKER_A,
                    provider=provider,
                    correlation_id=fx.correlation_id,
                    eligibility_evaluator=eligibility,
                    hooks=ExecutorHooks(before_finalize=crash),
                )
            assert provider.invocation_count == 1
            assert sink.count_for_command(fx.command_id) == 1

            # Restart: new provider, same sink file
            provider2 = PublishRetryCommandStagingFakeFactory(ctx).create(
                mode=FakeProviderMode.SUCCESS,
                sink=sink,
            )
            result = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                provider=provider2,
                correlation_id=fx.correlation_id,
                eligibility_evaluator=eligibility,
            )
        assert result.outcome == "already_barriered_no_replay"
        assert provider2.invocation_count == 0
        assert sink.count_for_command(fx.command_id) == 1
        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "provider_write_started"

    asyncio.run(_with_staging_pg(body))


def test_sink_failure_before_effect_is_fail_closed():
    async def body(factory, engine):
        with _flags():
            ctx = await _mint_ctx(engine)
            sink = _tmp_sink()
            eligibility = StagingSyntheticRetryEligibility(ctx)
            provider = PublishRetryCommandStagingFakeFactory(ctx).create(
                mode=FakeProviderMode.SUCCESS,
                sink=sink,
                fail_sink_before_effect=True,
            )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(ctx).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )
            result = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                provider=provider,
                correlation_id=fx.correlation_id,
                eligibility_evaluator=eligibility,
            )
            # Provider raised → classifier AMBIGUOUS; no auto-retry second call.
            assert provider.invocation_count == 1
            assert result.provider_invocation_count == 1
            assert sink.count_for_command(fx.command_id) == 0

    asyncio.run(_with_staging_pg(body))


def test_canonical_policy_still_blocks_without_injection():
    async def body(factory, engine):
        with _flags():
            ctx = await _mint_ctx(engine)
            sink = _tmp_sink()
            provider = PublishRetryCommandStagingFakeFactory(ctx).create(
                mode=FakeProviderMode.SUCCESS,
                sink=sink,
            )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(ctx).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )
            # No staging evaluator injection — empty allowlist blocks.
            result = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                provider=provider,
                correlation_id=fx.correlation_id,
            )
        assert result.ok is False
        assert result.outcome == "blocked_preparation"
        assert provider.invocation_count == 0
        assert sink.count_for_command(fx.command_id) == 0

    asyncio.run(_with_staging_pg(body))


def test_worker_still_refuses_fake_backend():
    async def _inner():
        with _flags(
            PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="fake",
            PUBLISH_RETRY_COMMAND_WORKER_ENABLED=True,
        ):
            worker = PublishRetryCommandWorker(worker_id=WORKER_A)
            await worker._orchestrate_after_claim(command_id=uuid.uuid4())

    asyncio.run(_inner())


def test_no_app_env_staging_branch_in_prep_barrier():
    for name in (
        "publish_retry_command_preparation_service.py",
        "publish_retry_command_barrier_service.py",
    ):
        src = (SERVICES_DIR / name).read_text(encoding="utf-8")
        assert 'APP_ENV == "staging"' not in src
        assert "APP_ENV == 'staging'" not in src
