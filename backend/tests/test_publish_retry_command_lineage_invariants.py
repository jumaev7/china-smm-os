"""Phase 3C.1C-A — DB-level 1:1 lineage invariants for publish retry commands.

Proves PostgreSQL rejects duplicate command↔attempt linkage and enforces
provider_write_started timestamp CHECK. No worker / executor behavior.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Disposable local Postgres (same host as uuid regression suite).
DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/lineage_invariant_test"
)


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_LINEAGE_PG_URL", DEFAULT_PG_URL)


async def _wait_ready(engine, attempts: int = 40) -> None:
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 — readiness probe
            last_exc = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"PostgreSQL not ready: {last_exc}")


async def _ensure_database() -> str:
    """Create lineage_invariant_test DB on the uuid-test Postgres if missing."""
    url = _pg_url()
    # Connect to default postgres DB to CREATE DATABASE if needed.
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
        pytest.skip(f"PostgreSQL unavailable for lineage tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for lineage tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return url


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS publish_attempts CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS publish_retry_commands CASCADE"))
        # Minimal tables carrying only the Phase 3C.1C-A invariants under test.
        await conn.execute(
            text(
                """
                CREATE TABLE publish_attempts (
                    id UUID PRIMARY KEY,
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
                CREATE TABLE publish_retry_commands (
                    id UUID PRIMARY KEY,
                    resulting_attempt_id UUID NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    provider_write_started_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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
        async with factory() as session:
            await coro_factory(session)
    except OSError as exc:
        pytest.skip(f"PostgreSQL lineage test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL lineage test DB unavailable at {url}: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(_with_pg(coro_factory))


def test_a_command_attempt_linkage_succeeds():
    """A. command X + attempt A linkage succeeds."""
    command_id = uuid.uuid4()
    attempt_id = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(
            text("INSERT INTO publish_retry_commands (id) VALUES (:id)"),
            {"id": command_id},
        )
        await session.execute(
            text(
                "INSERT INTO publish_attempts (id, retry_command_id) "
                "VALUES (:id, :cmd)"
            ),
            {"id": attempt_id, "cmd": command_id},
        )
        await session.commit()
        row = (
            await session.execute(
                text(
                    "SELECT retry_command_id FROM publish_attempts WHERE id = :id"
                ),
                {"id": attempt_id},
            )
        ).one()
        assert row[0] == command_id

    _run(_body)


def test_b_duplicate_attempt_same_command_rejected():
    """B. attempt B using same command X fails DB uniqueness."""
    command_id = uuid.uuid4()
    attempt_a = uuid.uuid4()
    attempt_b = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(
            text("INSERT INTO publish_retry_commands (id) VALUES (:id)"),
            {"id": command_id},
        )
        await session.execute(
            text(
                "INSERT INTO publish_attempts (id, retry_command_id) "
                "VALUES (:id, :cmd)"
            ),
            {"id": attempt_a, "cmd": command_id},
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO publish_attempts (id, retry_command_id) "
                    "VALUES (:id, :cmd)"
                ),
                {"id": attempt_b, "cmd": command_id},
            )
            await session.commit()
        await session.rollback()

    _run(_body)


def test_c_command_resulting_attempt_succeeds():
    """C. command A → attempt X succeeds."""
    command_id = uuid.uuid4()
    attempt_id = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(
            text("INSERT INTO publish_attempts (id) VALUES (:id)"),
            {"id": attempt_id},
        )
        await session.execute(
            text(
                "INSERT INTO publish_retry_commands (id, resulting_attempt_id) "
                "VALUES (:id, :att)"
            ),
            {"id": command_id, "att": attempt_id},
        )
        await session.commit()
        row = (
            await session.execute(
                text(
                    "SELECT resulting_attempt_id FROM publish_retry_commands "
                    "WHERE id = :id"
                ),
                {"id": command_id},
            )
        ).one()
        assert row[0] == attempt_id

    _run(_body)


def test_d_duplicate_command_same_resulting_attempt_rejected():
    """D. command B → same attempt X fails DB uniqueness."""
    command_a = uuid.uuid4()
    command_b = uuid.uuid4()
    attempt_id = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(
            text("INSERT INTO publish_attempts (id) VALUES (:id)"),
            {"id": attempt_id},
        )
        await session.execute(
            text(
                "INSERT INTO publish_retry_commands (id, resulting_attempt_id) "
                "VALUES (:id, :att)"
            ),
            {"id": command_a, "att": attempt_id},
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO publish_retry_commands (id, resulting_attempt_id) "
                    "VALUES (:id, :att)"
                ),
                {"id": command_b, "att": attempt_id},
            )
            await session.commit()
        await session.rollback()

    _run(_body)


def test_e_multiple_null_retry_command_id_allowed():
    """E. multiple NULL retry_command_id values remain allowed."""

    async def _body(session: AsyncSession):
        for _ in range(3):
            await session.execute(
                text(
                    "INSERT INTO publish_attempts (id, retry_command_id) "
                    "VALUES (:id, NULL)"
                ),
                {"id": uuid.uuid4()},
            )
        await session.commit()
        cnt = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM publish_attempts "
                    "WHERE retry_command_id IS NULL"
                )
            )
        ).scalar_one()
        assert cnt == 3

    _run(_body)


def test_f_multiple_null_resulting_attempt_id_allowed():
    """F. multiple NULL resulting_attempt_id values remain allowed."""

    async def _body(session: AsyncSession):
        for _ in range(3):
            await session.execute(
                text(
                    "INSERT INTO publish_retry_commands "
                    "(id, resulting_attempt_id) VALUES (:id, NULL)"
                ),
                {"id": uuid.uuid4()},
            )
        await session.commit()
        cnt = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM publish_retry_commands "
                    "WHERE resulting_attempt_id IS NULL"
                )
            )
        ).scalar_one()
        assert cnt == 3

    _run(_body)


def test_g_distinct_command_attempt_pairs_succeed():
    """G. different command ↔ attempt pairs succeed."""
    cmd1, cmd2 = uuid.uuid4(), uuid.uuid4()
    att1, att2 = uuid.uuid4(), uuid.uuid4()

    async def _body(session: AsyncSession):
        for cmd in (cmd1, cmd2):
            await session.execute(
                text("INSERT INTO publish_retry_commands (id) VALUES (:id)"),
                {"id": cmd},
            )
        await session.execute(
            text(
                "INSERT INTO publish_attempts (id, retry_command_id) "
                "VALUES (:id, :cmd)"
            ),
            {"id": att1, "cmd": cmd1},
        )
        await session.execute(
            text(
                "INSERT INTO publish_attempts (id, retry_command_id) "
                "VALUES (:id, :cmd)"
            ),
            {"id": att2, "cmd": cmd2},
        )
        await session.execute(
            text(
                "UPDATE publish_retry_commands "
                "SET resulting_attempt_id = :att WHERE id = :cmd"
            ),
            {"att": att1, "cmd": cmd1},
        )
        await session.execute(
            text(
                "UPDATE publish_retry_commands "
                "SET resulting_attempt_id = :att WHERE id = :cmd"
            ),
            {"att": att2, "cmd": cmd2},
        )
        await session.commit()
        cnt = (
            await session.execute(text("SELECT COUNT(*) FROM publish_attempts"))
        ).scalar_one()
        assert cnt == 2

    _run(_body)


def test_check_provider_write_started_with_timestamp_allowed():
    """status=provider_write_started + timestamp set → allowed."""
    now = datetime.now(timezone.utc)

    async def _body(session: AsyncSession):
        await session.execute(
            text(
                "INSERT INTO publish_retry_commands "
                "(id, status, provider_write_started_at) "
                "VALUES (:id, 'provider_write_started', :ts)"
            ),
            {"id": uuid.uuid4(), "ts": now},
        )
        await session.commit()

    _run(_body)


def test_check_provider_write_started_without_timestamp_rejected():
    """status=provider_write_started + timestamp NULL → rejected by DB."""

    async def _body(session: AsyncSession):
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO publish_retry_commands "
                    "(id, status, provider_write_started_at) "
                    "VALUES (:id, 'provider_write_started', NULL)"
                ),
                {"id": uuid.uuid4()},
            )
            await session.commit()
        await session.rollback()

    _run(_body)


def test_check_pending_null_timestamp_allowed():
    """pending + timestamp NULL → allowed."""

    async def _body(session: AsyncSession):
        await session.execute(
            text(
                "INSERT INTO publish_retry_commands "
                "(id, status, provider_write_started_at) "
                "VALUES (:id, 'pending', NULL)"
            ),
            {"id": uuid.uuid4()},
        )
        await session.commit()

    _run(_body)


def test_check_claimed_null_timestamp_allowed():
    """claimed + timestamp NULL → allowed."""

    async def _body(session: AsyncSession):
        await session.execute(
            text(
                "INSERT INTO publish_retry_commands "
                "(id, status, provider_write_started_at) "
                "VALUES (:id, 'claimed', NULL)"
            ),
            {"id": uuid.uuid4()},
        )
        await session.commit()

    _run(_body)


# ---------------------------------------------------------------------------
# Read-only production preflight query (documentation / ops copy-paste).
# Do not execute against production from tests.
# ---------------------------------------------------------------------------
PREFLIGHT_DUPLICATE_LINEAGE_SQL = """
-- Phase 3C.1C-A pre-migration safety (read-only).
-- Expect zero rows on both queries before applying 20260926.

SELECT retry_command_id, COUNT(*) AS cnt
FROM publish_attempts
WHERE retry_command_id IS NOT NULL
GROUP BY retry_command_id
HAVING COUNT(*) > 1;

SELECT resulting_attempt_id, COUNT(*) AS cnt
FROM publish_retry_commands
WHERE resulting_attempt_id IS NOT NULL
GROUP BY resulting_attempt_id
HAVING COUNT(*) > 1;

SELECT COUNT(*) AS command_rows FROM publish_retry_commands;
SELECT COUNT(*) AS nonnull_attempt_links
FROM publish_attempts
WHERE retry_command_id IS NOT NULL;
"""


def test_preflight_sql_is_documented():
    assert "retry_command_id IS NOT NULL" in PREFLIGHT_DUPLICATE_LINEAGE_SQL
    assert "resulting_attempt_id IS NOT NULL" in PREFLIGHT_DUPLICATE_LINEAGE_SQL
