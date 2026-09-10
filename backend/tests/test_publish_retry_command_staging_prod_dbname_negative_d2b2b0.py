"""Phase 3C.1C-D2-B2b0 — exact production-DB-name negative integration test.

REAL PostgreSQL only, against a DISPOSABLE local/CI instance whose database
name is deliberately exactly ``china_smm_os``.

Does NOT connect to production infrastructure / Hetzner / .env.production.
Does NOT start the long-running retry worker.
Does NOT loosen RetryCommandStagingIdentityGuard.

Proves: staging + fake + ack-open + live current_database()==china_smm_os
→ fail closed (current_database_production_denylist) BEFORE any retry-command
mutation or staging capability mint.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.services.publish_retry_command_barrier_service import (
    PublishRetryCommandBarrierService,
)
from app.services.publish_retry_command_eligibility import (
    STAGING_TENANT_NAME_PREFIX,
    StagingSyntheticRetryEligibility,
)
from app.services.publish_retry_command_fake_sink import DurableFakeInvocationSink
from app.services.publish_retry_command_finalization_service import (
    PublishRetryCommandFinalizationService,
)
from app.services.publish_retry_command_preparation_service import (
    PublishRetryCommandPreparationService,
)
from app.services.publish_retry_command_staging_fake_factory import (
    PublishRetryCommandStagingFakeFactory,
    StagingFakeProviderExecutor,
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

# Disposable local/CI Postgres (same port family as other retry-command PG tests).
DEFAULT_ADMIN_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/postgres"
)
PRODUCTION_LIKE_DB_NAME = "china_smm_os"
ALLOWED_TEST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ALLOWED_TEST_PORTS = frozenset({54329})


def _base_url() -> str:
    """Admin/base URL for disposable PG; env override must still pass isolation."""
    return os.environ.get(
        "PUBLISH_RETRY_PROD_DBNAME_NEGATIVE_PG_URL",
        DEFAULT_ADMIN_URL,
    )


def _url_for_db(db_name: str) -> str:
    base = _base_url().rsplit("/", 1)[0]
    return f"{base}/{db_name}"


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
    """Refuse setup/destructive actions unless disposable test infra is proven.

    DB name alone is NOT sufficient — this test intentionally uses china_smm_os.
    """
    host, port, user, password, _db = _parse_pg_url(url)
    if host not in ALLOWED_TEST_HOSTS:
        pytest.fail(
            f"B2b0 isolation STOP: host {host!r} is not disposable test "
            f"localhost/container (allowed={sorted(ALLOWED_TEST_HOSTS)})",
        )
    if port not in ALLOWED_TEST_PORTS:
        pytest.fail(
            f"B2b0 isolation STOP: port {port} is not the disposable test "
            f"Postgres port (allowed={sorted(ALLOWED_TEST_PORTS)}). "
            "Refusing CREATE/DROP against unknown infrastructure.",
        )
    if user != "postgres" or password != "password":
        pytest.fail(
            "B2b0 isolation STOP: credentials are not the known disposable "
            "test postgres:password pair. Refusing to proceed.",
        )


def parse_database_name_safe(url: str) -> str:
    return _parse_pg_url(url)[4]


@contextmanager
def _staging_fake_open_flags(*, connected_db_url: str):
    """Every fake gate open EXCEPT authoritative DB identity.

    DATABASE_URL intentionally names the staging DB so URL preflight passes;
    the live connection targets china_smm_os (production denylist name).
    """
    staging_looking_url = _url_for_db(REQUIRED_DATABASE_NAME)
    assert parse_database_name_safe(staging_looking_url) == REQUIRED_DATABASE_NAME
    assert parse_database_name_safe(connected_db_url) == PRODUCTION_LIKE_DB_NAME
    with patch.multiple(
        settings,
        APP_ENV="staging",
        DATABASE_URL=staging_looking_url,
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


async def _ensure_named_database(db_name: str) -> str:
    """Create disposable DB ``db_name`` on the isolated test Postgres only."""
    admin_url = _url_for_db("postgres")
    target_url = _url_for_db(db_name)
    assert_disposable_test_postgres_isolation(admin_url)
    assert_disposable_test_postgres_isolation(target_url)

    engine = create_async_engine(admin_url, echo=False, isolation_level="AUTOCOMMIT")
    try:
        await _wait_ready(engine)
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            )
            if exists.first() is None:
                # Quoted identifier; name is a fixed constant in this test module.
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable for B2b0 prod-dbname negative: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for B2b0 prod-dbname negative: {exc}")
        raise
    finally:
        await engine.dispose()
    return target_url


async def _setup_minimal_schema(engine) -> None:
    """Table create/drop only inside proven disposable DB (never DROP DATABASE)."""
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
                    status VARCHAR(30) NOT NULL DEFAULT 'failed'
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
                    platform VARCHAR(20) NOT NULL
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
                    status VARCHAR(20) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    retry_command_id UUID NULL
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
                    platform VARCHAR(20) NOT NULL,
                    publish_version VARCHAR(64) NOT NULL,
                    destination_key VARCHAR(120) NOT NULL,
                    requested_source VARCHAR(20) NOT NULL,
                    idempotency_key VARCHAR(420) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    correlation_id VARCHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )


async def _count_rows(conn, table: str) -> int:
    result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
    return int(result.scalar_one())


async def _count_staging_fixture_markers(conn) -> int:
    result = await conn.execute(
        text(
            """
            SELECT COUNT(*) FROM tenants
            WHERE COALESCE(company_name, '') LIKE :pfx
               OR COALESCE(name, '') LIKE :pfx
            """
        ),
        {"pfx": f"{STAGING_TENANT_NAME_PREFIX}%"},
    )
    return int(result.scalar_one())


async def _run_live_prod_dbname_negative() -> dict:
    assert PRODUCTION_LIKE_DB_NAME in PRODUCTION_DATABASE_DENYLIST
    assert REQUIRED_DATABASE_NAME != PRODUCTION_LIKE_DB_NAME

    target_url = await _ensure_named_database(PRODUCTION_LIKE_DB_NAME)
    assert_disposable_test_postgres_isolation(target_url)

    engine = create_async_engine(target_url, echo=False)
    sink_dir = Path(tempfile.mkdtemp(prefix="b2b0-prod-dbname-sink-"))
    sink = DurableFakeInvocationSink(sink_dir / "invocations.jsonl")

    fixture_init = MagicMock(
        side_effect=AssertionError("fixture builder must not be constructed"),
    )
    fixture_create = AsyncMock(
        side_effect=AssertionError("fixture create must not run on B2b0 reject"),
    )
    eligibility_init = MagicMock(
        side_effect=AssertionError("StagingSyntheticRetryEligibility must not construct"),
    )
    fake_factory_init = MagicMock(
        side_effect=AssertionError("fake factory must not be constructed"),
    )
    fake_factory_create = MagicMock(
        side_effect=AssertionError("fake factory create must not run"),
    )
    prepare = AsyncMock(side_effect=AssertionError("prepare must not run"))
    cross_barrier = AsyncMock(side_effect=AssertionError("cross_barrier must not run"))
    fake_execute = AsyncMock(
        side_effect=AssertionError("StagingFakeProviderExecutor.execute must not run"),
    )
    finalize = AsyncMock(side_effect=AssertionError("finalization must not run"))

    verified_ctx: VerifiedRetryCommandStagingContext | None = None
    rejection_reason: str | None = None
    live_db_name: str | None = None
    before: dict[str, int] = {}
    after: dict[str, int] = {}
    settings_snapshot: dict[str, object] = {}

    try:
        await _wait_ready(engine)
        await _setup_minimal_schema(engine)

        with (
            _staging_fake_open_flags(connected_db_url=target_url),
            patch.object(
                PublishRetryCommandStagingFixtureBuilder,
                "__init__",
                fixture_init,
            ),
            patch.object(
                PublishRetryCommandStagingFixtureBuilder,
                "create",
                fixture_create,
            ),
            patch.object(
                StagingSyntheticRetryEligibility,
                "__init__",
                eligibility_init,
            ),
            patch.object(
                PublishRetryCommandStagingFakeFactory,
                "__init__",
                fake_factory_init,
            ),
            patch.object(
                PublishRetryCommandStagingFakeFactory,
                "create",
                fake_factory_create,
            ),
            patch.object(
                PublishRetryCommandPreparationService,
                "prepare",
                prepare,
            ),
            patch.object(
                PublishRetryCommandBarrierService,
                "cross_barrier",
                cross_barrier,
            ),
            patch.object(
                StagingFakeProviderExecutor,
                "execute",
                fake_execute,
            ),
            patch.object(
                PublishRetryCommandFinalizationService,
                "finalize",
                finalize,
            ),
        ):
            settings_snapshot = {
                "APP_ENV": settings.APP_ENV,
                "backend": settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND,
                "fake_ack": settings.PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED,
                "commands": settings.PUBLISH_RETRY_COMMANDS_ENABLED,
                "worker": settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED,
                "claim": settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED,
                "execution": settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED,
            }

            async with engine.connect() as conn:
                live_db_name = await query_current_database(conn)
                assert live_db_name == PRODUCTION_LIKE_DB_NAME, (
                    f"authoritative live proof required: expected "
                    f"{PRODUCTION_LIKE_DB_NAME!r}, got {live_db_name!r}"
                )

                before = {
                    "publish_retry_commands": await _count_rows(
                        conn, "publish_retry_commands",
                    ),
                    "publish_attempts": await _count_rows(conn, "publish_attempts"),
                    "tenants": await _count_rows(conn, "tenants"),
                    "clients": await _count_rows(conn, "clients"),
                    "content_items": await _count_rows(conn, "content_items"),
                    "staging_markers": await _count_staging_fixture_markers(conn),
                }

                with pytest.raises(StagingIdentityError) as ei:
                    verified_ctx = await RetryCommandStagingIdentityGuard.verify(conn)
                rejection_reason = ei.value.reason

                after = {
                    "publish_retry_commands": await _count_rows(
                        conn, "publish_retry_commands",
                    ),
                    "publish_attempts": await _count_rows(conn, "publish_attempts"),
                    "tenants": await _count_rows(conn, "tenants"),
                    "clients": await _count_rows(conn, "clients"),
                    "content_items": await _count_rows(conn, "content_items"),
                    "staging_markers": await _count_staging_fixture_markers(conn),
                }

            # Settings presented every fake gate as open during verify.
            assert settings_snapshot["APP_ENV"] == "staging"
            assert settings_snapshot["backend"] == "fake"
            assert settings_snapshot["fake_ack"] is True
            assert settings_snapshot["commands"] is True
            assert settings_snapshot["worker"] is True
            assert settings_snapshot["claim"] is True
            assert settings_snapshot["execution"] is True

        assert live_db_name == "china_smm_os"
        assert rejection_reason == "current_database_production_denylist"
        assert verified_ctx is None
        assert not isinstance(verified_ctx, VerifiedRetryCommandStagingContext)

        assert fixture_init.call_count == 0
        assert fixture_create.await_count == 0
        assert eligibility_init.call_count == 0
        assert fake_factory_init.call_count == 0
        assert fake_factory_create.call_count == 0
        assert prepare.await_count == 0
        assert cross_barrier.await_count == 0
        assert fake_execute.await_count == 0
        assert finalize.await_count == 0

        assert not sink.path.exists()
        assert after == before
        assert after["staging_markers"] == 0
        assert after["publish_retry_commands"] == 0
        assert after["publish_attempts"] == 0

        return {
            "live_db": live_db_name,
            "rejection": rejection_reason,
            "before": before,
            "after": after,
            "settings": settings_snapshot,
        }
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    finally:
        await engine.dispose()


def test_live_db_named_china_smm_os_rejects_staging_fake_before_any_mutation():
    """Real PG integration: production DB name denylist before any mutation."""
    result = asyncio.run(_run_live_prod_dbname_negative())
    assert result["live_db"] == "china_smm_os"
    assert result["rejection"] == "current_database_production_denylist"
    assert result["before"] == result["after"]


def test_b2b0_isolation_guard_rejects_non_local_urls():
    """Self-test: isolation helper refuses unknown hosts/ports before any DB work."""
    with pytest.raises(pytest.fail.Exception, match="isolation STOP"):
        assert_disposable_test_postgres_isolation(
            "postgresql+asyncpg://postgres:password@db.example.com:5432/china_smm_os",
        )
    with pytest.raises(pytest.fail.Exception, match="isolation STOP"):
        assert_disposable_test_postgres_isolation(
            "postgresql+asyncpg://postgres:password@127.0.0.1:5432/china_smm_os",
        )
    assert_disposable_test_postgres_isolation(DEFAULT_ADMIN_URL)
