"""Phase 3C.1C-D2-B2b2-0A — staging fixture builder repair (full Alembic).

LOCAL/CI disposable PostgreSQL only. Hard gate: alembic upgrade head, then
PublishRetryCommandStagingFixtureBuilder against china_smm_os_staging.

No claim / prepare / barrier / provider / finalizer. No production mutation.
"""
from __future__ import annotations

import asyncio
import os
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.publish_retry_command_eligibility import (
    STAGING_CORRELATION_ID_PREFIX,
    STAGING_TENANT_NAME_PREFIX,
    CanonicalManualRetryEligibility,
    RetryCommandEligibilityContext,
    StagingSyntheticRetryEligibility,
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
    query_current_database,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/postgres"
)
ALLOWED_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ALLOWED_TEST_PORTS = frozenset({54329})
ALEMBIC_HEAD = "20260926_publish_retry_command_lineage"


def _base_url() -> str:
    return os.environ.get(
        "PUBLISH_RETRY_STAGING_FIXTURE_PG_URL",
        DEFAULT_ADMIN_URL,
    )


def _url_for_db(db_name: str) -> str:
    return f"{_base_url().rsplit('/', 1)[0]}/{db_name}"


def _parse_pg_url(url: str) -> tuple[str, int, str, str, str]:
    normalized = (
        str(url)
        .replace("postgresql+asyncpg://", "postgresql://", 1)
        .replace("postgres+asyncpg://", "postgresql://", 1)
    )
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").strip().lower()
    port = int(parsed.port or 5432)
    user = parsed.username or ""
    password = parsed.password or ""
    db = (parsed.path or "").lstrip("/").split("?", 1)[0]
    return host, port, user, password, db


def assert_disposable_test_postgres_isolation(url: str) -> None:
    host, port, user, password, _db = _parse_pg_url(url)
    if host not in ALLOWED_TEST_HOSTS:
        pytest.fail(f"B2b2-0A isolation STOP: host {host!r} not disposable")
    if port not in ALLOWED_TEST_PORTS:
        pytest.fail(f"B2b2-0A isolation STOP: port {port} not disposable")
    if user != "postgres" or password != "password":
        pytest.fail("B2b2-0A isolation STOP: credentials not disposable test pair")


@contextmanager
def _staging_flags(*, database_url: str):
    with patch.multiple(
        settings,
        APP_ENV="staging",
        DATABASE_URL=database_url,
        PUBLISH_RETRY_COMMANDS_ENABLED=True,
        PUBLISH_RETRY_COMMAND_WORKER_ENABLED=True,
        PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=True,
        PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True,
        PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="fake",
        PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=True,
        TELEGRAM_BOT_TOKEN="",
        META_APP_SECRET="",
    ):
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


async def _recreate_database(db_name: str) -> str:
    admin_url = _url_for_db("postgres")
    target_url = _url_for_db(db_name)
    assert_disposable_test_postgres_isolation(admin_url)
    assert_disposable_test_postgres_isolation(target_url)

    engine = create_async_engine(admin_url, echo=False, isolation_level="AUTOCOMMIT")
    try:
        await _wait_ready(engine)
        async with engine.connect() as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"),
                    {"n": db_name},
                )
            ).first()
            if exists is not None:
                await conn.execute(text(f'DROP DATABASE "{db_name}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable for B2b2-0A: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for B2b2-0A: {exc}")
        raise
    finally:
        await engine.dispose()
    return target_url


def _alembic_upgrade_head(database_url: str) -> None:
    """Sync alembic upgrade against disposable URL (full current schema)."""
    assert_disposable_test_postgres_isolation(database_url)
    with patch.object(settings, "DATABASE_URL", database_url):
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        command.upgrade(cfg, "head")


async def _count_rows(conn, table: str, where: str = "TRUE", params: dict | None = None) -> int:
    row = (
        await conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {where}"),
            params or {},
        )
    ).scalar()
    return int(row or 0)


async def _fixture_marker_counts(conn) -> dict[str, int]:
    return {
        "tenants": await _count_rows(
            conn,
            "tenants",
            "company_name LIKE :p",
            {"p": f"{STAGING_TENANT_NAME_PREFIX}%"},
        ),
        "clients": await _count_rows(
            conn,
            "clients",
            "company_name LIKE :p",
            {"p": f"{STAGING_TENANT_NAME_PREFIX}%"},
        ),
        "content_items": await _count_rows(
            conn,
            "content_items",
            "source = :s",
            {"s": "staging_synthetic"},
        ),
        "commands": await _count_rows(
            conn,
            "publish_retry_commands",
            "correlation_id LIKE :p",
            {"p": f"{STAGING_CORRELATION_ID_PREFIX}%"},
        ),
    }


def test_invalid_context_refuses_builder_construction():
    with pytest.raises(StagingIdentityError):
        PublishRetryCommandStagingFixtureBuilder(object())  # type: ignore[arg-type]

    with pytest.raises(StagingIdentityError):
        VerifiedRetryCommandStagingContext(
            app_env="staging",
            execution_backend="fake",
            fake_execution_allowed=True,
            current_database=REQUIRED_DATABASE_NAME,
            _capability_token="forged",
        )


def test_full_alembic_schema_fixture_builder_success():
    """Hard gate: alembic upgrade head → builder → one pending synthetic command."""

    async def _prepare() -> str:
        return await _recreate_database(REQUIRED_DATABASE_NAME)

    url = asyncio.run(_prepare())
    _alembic_upgrade_head(url)

    async def body() -> None:
        with _staging_flags(database_url=url):
            engine = create_async_engine(url, echo=False)
            try:
                async with engine.connect() as conn:
                    db_name = (await conn.execute(text("SELECT current_database()"))).scalar()
                    assert db_name == REQUIRED_DATABASE_NAME
                    ver = (
                        await conn.execute(text("SELECT version_num FROM alembic_version"))
                    ).scalar()
                    assert ver == ALEMBIC_HEAD
                    # Prove full-schema NOT NULL columns exist (not stripped harness).
                    cols = {
                        r[0]
                        for r in (
                            await conn.execute(
                                text(
                                    """
                                    SELECT column_name
                                    FROM information_schema.columns
                                    WHERE table_schema = 'public'
                                      AND table_name = 'clients'
                                      AND column_name IN (
                                        'source_language', 'business_category',
                                        'content_style', 'status'
                                      )
                                    """
                                )
                            )
                        ).all()
                    }
                    assert cols == {
                        "source_language",
                        "business_category",
                        "content_style",
                        "status",
                    }
                    src_col = (
                        await conn.execute(
                            text(
                                """
                                SELECT 1 FROM information_schema.columns
                                WHERE table_schema = 'public'
                                  AND table_name = 'content_items'
                                  AND column_name = 'source'
                                """
                            )
                        )
                    ).first()
                    assert src_col is not None

                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                claim_mock = MagicMock()
                prepare_mock = MagicMock()
                barrier_mock = MagicMock()
                executor_mock = MagicMock()
                finalizer_mock = MagicMock()
                sink_mock = MagicMock()

                with (
                    patch(
                        "app.services.publish_retry_command_claim_service."
                        "PublishRetryCommandClaimService",
                        claim_mock,
                    ),
                    patch(
                        "app.services.publish_retry_command_preparation_service."
                        "PublishRetryCommandPreparationService",
                        prepare_mock,
                    ),
                    patch(
                        "app.services.publish_retry_command_barrier_service."
                        "PublishRetryCommandBarrierService",
                        barrier_mock,
                    ),
                    patch(
                        "app.services.publish_retry_command_executor."
                        "PublishRetryCommandExecutor",
                        executor_mock,
                    ),
                    patch(
                        "app.services.publish_retry_command_finalization_service."
                        "PublishRetryCommandFinalizationService",
                        finalizer_mock,
                    ),
                    patch(
                        "app.services.publish_retry_command_fake_sink."
                        "DurableFakeInvocationSink",
                        sink_mock,
                    ),
                ):
                    async with factory() as db:
                        ctx = await RetryCommandStagingIdentityGuard.verify(
                            db, execution_backend="fake"
                        )
                        assert ctx.current_database == REQUIRED_DATABASE_NAME
                        eligibility = StagingSyntheticRetryEligibility(ctx)
                        builder = PublishRetryCommandStagingFixtureBuilder(ctx)
                        fx = await builder.create(db, command_status="pending")

                    claim_mock.assert_not_called()
                    prepare_mock.assert_not_called()
                    barrier_mock.assert_not_called()
                    executor_mock.assert_not_called()
                    finalizer_mock.assert_not_called()
                    sink_mock.assert_not_called()

                    async with engine.connect() as conn:
                        assert (
                            await query_current_database(conn)
                        ) == REQUIRED_DATABASE_NAME
                        counts = await _fixture_marker_counts(conn)
                        assert counts["tenants"] == 1
                        assert counts["clients"] == 1
                        assert counts["content_items"] == 1
                        assert counts["commands"] == 1

                        client = (
                            await conn.execute(
                                text(
                                    """
                                    SELECT source_language, business_category,
                                           content_style, status, company_name
                                    FROM clients WHERE id = :id
                                    """
                                ),
                                {"id": fx.client_id},
                            )
                        ).mappings().one()
                        assert client["source_language"] == "zh"
                        assert client["business_category"] == "general"
                        assert client["content_style"] == "professional"
                        assert client["status"] == "active"
                        assert str(client["company_name"]).startswith(
                            STAGING_TENANT_NAME_PREFIX
                        )

                        content = (
                            await conn.execute(
                                text(
                                    """
                                    SELECT source, status, platforms
                                    FROM content_items WHERE id = :id
                                    """
                                ),
                                {"id": fx.content_id},
                            )
                        ).mappings().one()
                        assert content["source"] == "staging_synthetic"
                        assert content["status"] == "failed"
                        assert "telegram" in (content["platforms"] or [])

                        account = (
                            await conn.execute(
                                text(
                                    """
                                    SELECT platform, status, account_name,
                                           access_token_encrypted
                                    FROM publishing_accounts WHERE id = :id
                                    """
                                ),
                                {"id": fx.account_id},
                            )
                        ).mappings().one()
                        assert account["platform"] == "telegram"
                        assert account["status"] == "mock"
                        assert account["access_token_encrypted"] is None
                        assert str(account["account_name"]).startswith(
                            STAGING_TENANT_NAME_PREFIX
                        )

                        attempt = (
                            await conn.execute(
                                text(
                                    """
                                    SELECT status, failure_code, retryable
                                    FROM publish_attempts WHERE id = :id
                                    """
                                ),
                                {"id": fx.original_attempt_id},
                            )
                        ).mappings().one()
                        assert attempt["status"] == "failed"
                        assert attempt["failure_code"] == "provider_unavailable"
                        assert attempt["retryable"] is True

                        cmd = (
                            await conn.execute(
                                text(
                                    """
                                    SELECT status, provider_write_started_at,
                                           provider_outcome, finished_at,
                                           correlation_id, resulting_attempt_id
                                    FROM publish_retry_commands WHERE id = :id
                                    """
                                ),
                                {"id": fx.command_id},
                            )
                        ).mappings().one()
                        assert cmd["status"] == "pending"
                        assert cmd["provider_write_started_at"] is None
                        assert cmd["provider_outcome"] is None
                        assert cmd["finished_at"] is None
                        assert cmd["resulting_attempt_id"] is None
                        assert str(cmd["correlation_id"]).startswith(
                            STAGING_CORRELATION_ID_PREFIX
                        )

                    fake_attempt = types.SimpleNamespace(
                        id=fx.original_attempt_id,
                        status="failed",
                        platform="telegram",
                        failure_code="provider_unavailable",
                        retryable=True,
                        content_id=fx.content_id,
                    )
                    elig_ctx = RetryCommandEligibilityContext(
                        attempt=fake_attempt,
                        source="admin",
                        correlation_id=fx.correlation_id,
                        tenant_company_name=fx.tenant_name,
                        command_id=fx.command_id,
                        tenant_id=fx.tenant_id,
                    )
                    staging_result = eligibility.evaluate(elig_ctx)
                    assert staging_result.allowed is True
                    assert staging_result.reason_code == "staging_synthetic_fixture_allowed"

                    canonical = CanonicalManualRetryEligibility().evaluate(elig_ctx)
                    assert canonical.allowed is False

                    # Repeat build → new uniquely named fixture (behavior A).
                    async with factory() as db:
                        ctx2 = await RetryCommandStagingIdentityGuard.verify(
                            db, execution_backend="fake"
                        )
                        fx2 = await PublishRetryCommandStagingFixtureBuilder(ctx2).create(
                            db, command_status="pending"
                        )
                    assert fx2.command_id != fx.command_id
                    assert fx2.tenant_id != fx.tenant_id
                    assert fx2.tenant_name.startswith(STAGING_TENANT_NAME_PREFIX)
                    assert fx2.tenant_name != fx.tenant_name

                    async with engine.connect() as conn:
                        counts2 = await _fixture_marker_counts(conn)
                        assert counts2["tenants"] == 2
                        assert counts2["clients"] == 2
                        assert counts2["commands"] == 2
                        pending = await _count_rows(
                            conn,
                            "publish_retry_commands",
                            "status = 'pending' AND provider_write_started_at IS NULL "
                            "AND correlation_id LIKE :p",
                            {"p": f"{STAGING_CORRELATION_ID_PREFIX}%"},
                        )
                        assert pending == 2
            finally:
                await engine.dispose()

    asyncio.run(body())


def test_transaction_rollback_on_late_insert_failure():
    url = _url_for_db(REQUIRED_DATABASE_NAME)
    assert_disposable_test_postgres_isolation(url)

    async def _schema_ready() -> bool:
        engine = create_async_engine(url, echo=False)
        try:
            await _wait_ready(engine)
            async with engine.connect() as conn:
                has_source = (
                    await conn.execute(
                        text(
                            """
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema='public'
                              AND table_name='content_items'
                              AND column_name='source'
                            """
                        )
                    )
                ).first()
                has_client_fields = (
                    await conn.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM information_schema.columns
                            WHERE table_schema='public'
                              AND table_name='clients'
                              AND column_name IN (
                                'source_language', 'business_category',
                                'content_style', 'status'
                              )
                            """
                        )
                    )
                ).scalar()
            return has_source is not None and int(has_client_fields or 0) == 4
        finally:
            await engine.dispose()

    try:
        ready = asyncio.run(_schema_ready())
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "does not exist" in msg:
            ready = False
        else:
            raise

    if not ready:
        url = asyncio.run(_recreate_database(REQUIRED_DATABASE_NAME))
        _alembic_upgrade_head(url)

    async def body() -> None:
        with _staging_flags(database_url=url):
            engine = create_async_engine(url, echo=False)
            try:
                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with engine.connect() as conn:
                    before = await _fixture_marker_counts(conn)

                async with factory() as db:
                    ctx = await RetryCommandStagingIdentityGuard.verify(
                        db, execution_backend="fake"
                    )
                    builder = PublishRetryCommandStagingFixtureBuilder(ctx)
                    real_execute = db.execute

                    async def failing_execute(*args, **kwargs):
                        sql = str(args[0]) if args else ""
                        if "INSERT INTO publish_retry_commands" in sql:
                            raise RuntimeError("forced late fixture failure")
                        return await real_execute(*args, **kwargs)

                    with patch.object(db, "execute", side_effect=failing_execute):
                        with pytest.raises(
                            RuntimeError, match="forced late fixture failure"
                        ):
                            await builder.create(db, command_status="pending")

                async with engine.connect() as conn:
                    after = await _fixture_marker_counts(conn)
                    assert after == before
            finally:
                await engine.dispose()

    asyncio.run(body())


def test_production_dbname_refuses_before_insert():
    """china_smm_os + staging-like env → hard fail; counts unchanged."""

    async def _prepare() -> str:
        return await _recreate_database("china_smm_os")

    prod_url = asyncio.run(_prepare())
    # Minimal tables so counts are meaningful; identity must fail before insert.
    async def _minimal() -> None:
        engine = create_async_engine(prod_url, echo=False)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        CREATE TABLE tenants (
                            id UUID PRIMARY KEY,
                            company_name VARCHAR(255) NOT NULL
                        )
                        """
                    )
                )
                await conn.execute(
                    text(
                        """
                        CREATE TABLE clients (
                            id UUID PRIMARY KEY,
                            tenant_id UUID,
                            company_name VARCHAR(255),
                            source_language VARCHAR(10) NOT NULL,
                            business_category VARCHAR(100) NOT NULL,
                            content_style VARCHAR(100) NOT NULL,
                            status VARCHAR(20) NOT NULL
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
                            status VARCHAR(30) NOT NULL,
                            source VARCHAR(20) NOT NULL,
                            platforms VARCHAR[] NULL,
                            updated_at TIMESTAMPTZ NULL
                        )
                        """
                    )
                )
                await conn.execute(
                    text(
                        "CREATE TABLE publishing_accounts (id UUID PRIMARY KEY)"
                    )
                )
                await conn.execute(
                    text("CREATE TABLE publish_attempts (id UUID PRIMARY KEY)")
                )
                await conn.execute(
                    text(
                        """
                        CREATE TABLE publish_retry_commands (
                            id UUID PRIMARY KEY,
                            correlation_id VARCHAR(64)
                        )
                        """
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(_minimal())

    async def body() -> None:
        staging_looking = _url_for_db(REQUIRED_DATABASE_NAME)
        assert "china_smm_os" in PRODUCTION_DATABASE_DENYLIST
        with patch.multiple(
            settings,
            APP_ENV="staging",
            DATABASE_URL=staging_looking,
            PUBLISH_RETRY_COMMANDS_ENABLED=True,
            PUBLISH_RETRY_COMMAND_WORKER_ENABLED=True,
            PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=True,
            PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True,
            PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="fake",
            PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=True,
            TELEGRAM_BOT_TOKEN="",
            META_APP_SECRET="",
        ):
            engine = create_async_engine(prod_url, echo=False)
            try:
                async with engine.connect() as conn:
                    before = {
                        "tenants": await _count_rows(conn, "tenants"),
                        "commands": await _count_rows(conn, "publish_retry_commands"),
                    }
                    live = await query_current_database(conn)
                    assert live == "china_smm_os"

                factory = async_sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
                async with factory() as db:
                    # Guard refuses minting on production denylist name.
                    with pytest.raises(StagingIdentityError) as guard_exc:
                        await RetryCommandStagingIdentityGuard.verify(
                            db, execution_backend="fake"
                        )
                    assert "production" in str(guard_exc.value).lower() or (
                        "denylist" in str(guard_exc.value).lower()
                    )

                    # Even a forged context must fail live DB check in builder.
                    forged = MagicMock(spec=VerifiedRetryCommandStagingContext)
                    forged.current_database = REQUIRED_DATABASE_NAME
                    with patch(
                        "app.services.publish_retry_command_staging_fixture."
                        "assert_verified_staging_context",
                        return_value=forged,
                    ):
                        builder = PublishRetryCommandStagingFixtureBuilder(forged)
                        with pytest.raises(StagingIdentityError) as build_exc:
                            await builder.create(db, command_status="pending")
                        assert build_exc.value.reason == "current_database_not_staging"

                async with engine.connect() as conn:
                    after = {
                        "tenants": await _count_rows(conn, "tenants"),
                        "commands": await _count_rows(conn, "publish_retry_commands"),
                    }
                    assert after == before
            finally:
                await engine.dispose()

    asyncio.run(body())


def test_builder_source_mentions_no_execution_side_effects():
    src = (
        BACKEND_ROOT
        / "app"
        / "services"
        / "publish_retry_command_staging_fixture.py"
    ).read_text(encoding="utf-8")
    assert "PublishRetryCommandClaimService" not in src
    assert "PublishRetryCommandBarrierService" not in src
    assert "PublishRetryCommandExecutor" not in src
    assert "PublishRetryCommandFinalizationService" not in src
    assert "DurableFakeInvocationSink" not in src
    assert "source_language" in src
    assert "business_category" in src
    assert "content_style" in src
    assert "staging_synthetic" in src
    assert "REQUIRED_DATABASE_NAME" in src
