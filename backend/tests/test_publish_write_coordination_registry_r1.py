"""R1 — Publish Write Coordination Registry schema/model tests only.

Covers migration upgrade/downgrade, constraints, nullable-account uniqueness,
soft attempt/command refs (no cascade erase), and publication_intent_id storage.

No service wiring, acquire, or publish-path behavior.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import PublishRetryCommand
from app.models.publish_write_coordination_registry import (
    PUBLISH_WRITE_COORDINATION_STATES,
    PublishWriteCoordinationRegistry,
    build_logical_write_key,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/postgres"
)
DEFAULT_DB_NAME = "pwr_registry_r1_test"
PREV_HEAD = "20260926_publish_retry_command_lineage"
R1_REV = "20260927_publish_write_coordination_registry"

FORBIDDEN_PERSISTED_STATES = frozenset({
    "AVAILABLE",
    "CLAIMED",
    "PENDING",
    "RETRYABLE",
    "EXECUTING",
})


def _admin_url() -> str:
    return os.environ.get("PWR_REGISTRY_R1_ADMIN_URL", DEFAULT_ADMIN_URL)


def _db_url() -> str:
    override = os.environ.get("PWR_REGISTRY_R1_PG_URL")
    if override:
        return override
    return _admin_url().rsplit("/", 1)[0] + f"/{DEFAULT_DB_NAME}"


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
    admin_url = _admin_url()
    target_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    engine = create_async_engine(admin_url, echo=False, isolation_level="AUTOCOMMIT")
    try:
        await _wait_ready(engine)
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable for R1 registry tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for R1 registry tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return target_url


def _alembic_config(database_url: str) -> Config:
    from app.core.config import settings

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    # env.py reads settings.DATABASE_URL
    patcher = patch.object(settings, "DATABASE_URL", database_url)
    patcher.start()
    cfg.attributes["settings_patcher"] = patcher
    return cfg


def _alembic_upgrade(database_url: str, revision: str) -> None:
    cfg = _alembic_config(database_url)
    try:
        command.upgrade(cfg, revision)
    finally:
        cfg.attributes["settings_patcher"].stop()


def _alembic_downgrade(database_url: str, revision: str) -> None:
    cfg = _alembic_config(database_url)
    try:
        command.downgrade(cfg, revision)
    finally:
        cfg.attributes["settings_patcher"].stop()


async def _setup_minimal_registry_schema(engine) -> None:
    """Minimal parent stubs + registry DDL matching R1 constraints (no full migrate)."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS publish_write_coordination_registry CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS publish_retry_commands CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS publish_attempts CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS publishing_accounts CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS content_items CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS tenants CASCADE"))

        await conn.execute(text("CREATE TABLE tenants (id UUID PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE content_items (id UUID PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE publishing_accounts (id UUID PRIMARY KEY)"))
        await conn.execute(
            text(
                """
                CREATE TABLE publish_attempts (
                    id UUID PRIMARY KEY,
                    publication_intent_id UUID NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE publish_retry_commands (
                    id UUID PRIMARY KEY,
                    publication_intent_id UUID NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE publish_write_coordination_registry (
                    id UUID PRIMARY KEY,
                    logical_write_key VARCHAR(64) NOT NULL,
                    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
                    content_id UUID NOT NULL REFERENCES content_items(id) ON DELETE RESTRICT,
                    platform VARCHAR(20) NOT NULL,
                    account_id UUID NULL REFERENCES publishing_accounts(id) ON DELETE RESTRICT,
                    publication_intent_id UUID NOT NULL,
                    root_intent_id UUID NOT NULL,
                    state VARCHAR(32) NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 0,
                    owner_type VARCHAR(40) NULL,
                    owner_id VARCHAR(120) NULL,
                    lease_acquired_at TIMESTAMPTZ NULL,
                    lease_expires_at TIMESTAMPTZ NULL,
                    provider_write_started_at TIMESTAMPTZ NULL,
                    resolved_at TIMESTAMPTZ NULL,
                    current_attempt_id UUID NULL,
                    current_command_id UUID NULL,
                    external_post_id VARCHAR(255) NULL,
                    supersedes_id UUID NULL
                        REFERENCES publish_write_coordination_registry(id)
                        ON DELETE RESTRICT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_publish_write_coordination_registry_logical_write_key
                        UNIQUE (logical_write_key),
                    CONSTRAINT ck_publish_write_coordination_registry_state CHECK (
                        state IN (
                            'RESERVED', 'WRITE_STARTED', 'SUCCEEDED', 'FAILED_SAFE',
                            'AMBIGUOUS', 'RESOLVED_SUCCEEDED', 'RESOLVED_FAILED',
                            'SUPERSEDED'
                        )
                    ),
                    CONSTRAINT ck_publish_write_coordination_registry_generation_nonneg
                        CHECK (generation >= 0),
                    CONSTRAINT ck_publish_write_coordination_registry_version_nonneg
                        CHECK (version >= 0),
                    CONSTRAINT ck_publish_write_coordination_registry_write_started_ts
                        CHECK (
                            state <> 'WRITE_STARTED'
                            OR provider_write_started_at IS NOT NULL
                        )
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX
                uq_publish_write_coordination_registry_destination_intent
                ON publish_write_coordination_registry
                (tenant_id, content_id, platform, account_id, publication_intent_id)
                NULLS NOT DISTINCT
                """
            )
        )


async def _with_minimal_pg(coro_factory):
    url = await _recreate_database(DEFAULT_DB_NAME + "_min")
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_minimal_registry_schema(engine)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await coro_factory(session)
    except OSError as exc:
        pytest.skip(f"PostgreSQL R1 minimal schema unavailable: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL R1 minimal schema unavailable: {exc}")
        raise
    finally:
        await engine.dispose()


def _run_min(coro_factory):
    asyncio.run(_with_minimal_pg(coro_factory))


# ---------------------------------------------------------------------------
# Model / enum unit tests (no DB)
# ---------------------------------------------------------------------------


def test_registry_states_exact_set():
    expected = {
        "RESERVED",
        "WRITE_STARTED",
        "SUCCEEDED",
        "FAILED_SAFE",
        "AMBIGUOUS",
        "RESOLVED_SUCCEEDED",
        "RESOLVED_FAILED",
        "SUPERSEDED",
    }
    assert PUBLISH_WRITE_COORDINATION_STATES == expected
    assert FORBIDDEN_PERSISTED_STATES.isdisjoint(PUBLISH_WRITE_COORDINATION_STATES)


def test_build_logical_write_key_deterministic_and_account_sensitive():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent = uuid.uuid4()
    account = uuid.uuid4()

    k1 = build_logical_write_key(tenant, content, "Telegram", None, intent)
    k2 = build_logical_write_key(tenant, content, "telegram", None, intent)
    k3 = build_logical_write_key(tenant, content, "telegram", account, intent)
    k4 = build_logical_write_key(tenant, content, "telegram", None, uuid.uuid4())

    assert k1 == k2
    assert len(k1) == 64
    assert k1 != k3
    assert k1 != k4


def test_orm_models_expose_publication_intent_id_and_registry_columns():
    assert hasattr(PublishAttempt, "publication_intent_id")
    assert hasattr(PublishRetryCommand, "publication_intent_id")
    assert PublishWriteCoordinationRegistry.__tablename__ == (
        "publish_write_coordination_registry"
    )
    cols = {c.name for c in PublishWriteCoordinationRegistry.__table__.columns}
    required = {
        "id",
        "logical_write_key",
        "tenant_id",
        "content_id",
        "platform",
        "account_id",
        "publication_intent_id",
        "root_intent_id",
        "state",
        "generation",
        "version",
        "owner_type",
        "owner_id",
        "lease_acquired_at",
        "lease_expires_at",
        "provider_write_started_at",
        "resolved_at",
        "current_attempt_id",
        "current_command_id",
        "external_post_id",
        "supersedes_id",
        "created_at",
        "updated_at",
    }
    assert required.issubset(cols)


# ---------------------------------------------------------------------------
# Migration upgrade / downgrade
# ---------------------------------------------------------------------------


def test_migration_upgrade_and_downgrade():
    url = asyncio.run(_recreate_database(DEFAULT_DB_NAME + "_mig"))
    _alembic_upgrade(url, "head")

    engine = create_async_engine(url, echo=False)

    async def _assert_upgraded():
        await _wait_ready(engine)
        async with engine.connect() as conn:
            ver = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
            assert ver == R1_REV
            exists = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'publish_write_coordination_registry'"
                    )
                )
            ).first()
            assert exists is not None
            attempt_col = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'publish_attempts' "
                        "AND column_name = 'publication_intent_id'"
                    )
                )
            ).first()
            command_col = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'publish_retry_commands' "
                        "AND column_name = 'publication_intent_id'"
                    )
                )
            ).first()
            assert attempt_col is not None
            assert command_col is not None
            # NULLS NOT DISTINCT unique index present
            idx = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = "
                        "'uq_publish_write_coordination_registry_destination_intent'"
                    )
                )
            ).scalar()
            assert idx is not None
            assert "NULLS NOT DISTINCT" in idx.upper().replace("  ", " ") or (
                "nulls not distinct" in idx.lower()
            )

    asyncio.run(_assert_upgraded())
    asyncio.run(engine.dispose())

    _alembic_downgrade(url, PREV_HEAD)

    engine2 = create_async_engine(url, echo=False)

    async def _assert_downgraded():
        await _wait_ready(engine2)
        async with engine2.connect() as conn:
            ver = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
            assert ver == PREV_HEAD
            gone = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'publish_write_coordination_registry'"
                    )
                )
            ).first()
            assert gone is None
            attempt_col = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'publish_attempts' "
                        "AND column_name = 'publication_intent_id'"
                    )
                )
            ).first()
            command_col = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'publish_retry_commands' "
                        "AND column_name = 'publication_intent_id'"
                    )
                )
            ).first()
            assert attempt_col is None
            assert command_col is None

    asyncio.run(_assert_downgraded())
    asyncio.run(engine2.dispose())

    # Re-upgrade proves forward migration is repeatable after downgrade.
    _alembic_upgrade(url, "head")
    engine3 = create_async_engine(url, echo=False)

    async def _assert_reupgraded():
        await _wait_ready(engine3)
        async with engine3.connect() as conn:
            ver = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
            assert ver == R1_REV

    asyncio.run(_assert_reupgraded())
    asyncio.run(engine3.dispose())


# ---------------------------------------------------------------------------
# Constraint / uniqueness tests on minimal schema
# ---------------------------------------------------------------------------


def test_logical_write_key_uniqueness():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent = uuid.uuid4()
    key = build_logical_write_key(tenant, content, "telegram", None, intent)

    async def _body(session: AsyncSession):
        await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
        await session.execute(
            text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
        )
        row_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    NULL, :intent, :intent, 'RESERVED'
                )
                """
            ),
            {
                "id": row_id,
                "key": key,
                "tenant": tenant,
                "content": content,
                "intent": intent,
            },
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    """
                    INSERT INTO publish_write_coordination_registry (
                        id, logical_write_key, tenant_id, content_id, platform,
                        account_id, publication_intent_id, root_intent_id, state
                    ) VALUES (
                        :id, :key, :tenant, :content, 'telegram',
                        NULL, :intent2, :intent2, 'RESERVED'
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "key": key,
                    "tenant": tenant,
                    "content": content,
                    "intent2": uuid.uuid4(),
                },
            )
            await session.commit()
        await session.rollback()

    _run_min(_body)


def test_destination_intent_uniqueness_with_account():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    account = uuid.uuid4()
    intent = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
        await session.execute(
            text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
        )
        await session.execute(
            text("INSERT INTO publishing_accounts (id) VALUES (:id)"), {"id": account}
        )
        params = {
            "tenant": tenant,
            "content": content,
            "account": account,
            "intent": intent,
        }
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    :account, :intent, :intent, 'RESERVED'
                )
                """
            ),
            {
                **params,
                "id": uuid.uuid4(),
                "key": build_logical_write_key(
                    tenant, content, "telegram", account, intent
                ),
            },
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    """
                    INSERT INTO publish_write_coordination_registry (
                        id, logical_write_key, tenant_id, content_id, platform,
                        account_id, publication_intent_id, root_intent_id, state
                    ) VALUES (
                        :id, :key, :tenant, :content, 'telegram',
                        :account, :intent, :intent, 'RESERVED'
                    )
                    """
                ),
                {
                    **params,
                    "id": uuid.uuid4(),
                    "key": build_logical_write_key(
                        tenant, content, "telegram", account, uuid.uuid4()
                    ),
                },
            )
            await session.commit()
        await session.rollback()

    _run_min(_body)


def test_destination_intent_uniqueness_with_null_account():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
        await session.execute(
            text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
        )
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    NULL, :intent, :intent, 'RESERVED'
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "key": build_logical_write_key(
                    tenant, content, "telegram", None, intent
                ),
                "tenant": tenant,
                "content": content,
                "intent": intent,
            },
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    """
                    INSERT INTO publish_write_coordination_registry (
                        id, logical_write_key, tenant_id, content_id, platform,
                        account_id, publication_intent_id, root_intent_id, state
                    ) VALUES (
                        :id, :key, :tenant, :content, 'telegram',
                        NULL, :intent, :intent, 'RESERVED'
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "key": "different" + "0" * 55,
                    "tenant": tenant,
                    "content": content,
                    "intent": intent,
                },
            )
            await session.commit()
        await session.rollback()

    _run_min(_body)


def test_nullable_lease_owner_and_write_started_fields():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
        await session.execute(
            text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
        )
        row_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state,
                    owner_type, owner_id, lease_acquired_at, lease_expires_at,
                    provider_write_started_at
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    NULL, :intent, :intent, 'SUCCEEDED',
                    NULL, NULL, NULL, NULL, NULL
                )
                """
            ),
            {
                "id": row_id,
                "key": build_logical_write_key(
                    tenant, content, "telegram", None, intent
                ),
                "tenant": tenant,
                "content": content,
                "intent": intent,
            },
        )
        await session.commit()
        row = (
            await session.execute(
                text(
                    "SELECT owner_type, owner_id, lease_acquired_at, "
                    "lease_expires_at, provider_write_started_at "
                    "FROM publish_write_coordination_registry WHERE id = :id"
                ),
                {"id": row_id},
            )
        ).one()
        assert row == (None, None, None, None, None)

    _run_min(_body)


def test_supersedes_self_reference_and_restrict_delete():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent_a = uuid.uuid4()
    intent_b = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
        await session.execute(
            text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
        )
        prior_id = uuid.uuid4()
        newer_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    NULL, :intent, :intent, 'SUCCEEDED'
                )
                """
            ),
            {
                "id": prior_id,
                "key": build_logical_write_key(
                    tenant, content, "telegram", None, intent_a
                ),
                "tenant": tenant,
                "content": content,
                "intent": intent_a,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state,
                    supersedes_id
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    NULL, :intent, :intent, 'RESERVED', :prior
                )
                """
            ),
            {
                "id": newer_id,
                "key": build_logical_write_key(
                    tenant, content, "telegram", None, intent_b
                ),
                "tenant": tenant,
                "content": content,
                "intent": intent_b,
                "prior": prior_id,
            },
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "DELETE FROM publish_write_coordination_registry WHERE id = :id"
                ),
                {"id": prior_id},
            )
            await session.commit()
        await session.rollback()

    _run_min(_body)


def test_no_cascade_delete_from_attempt_or_command():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent = uuid.uuid4()
    attempt_id = uuid.uuid4()
    command_id = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
        await session.execute(
            text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
        )
        await session.execute(
            text(
                "INSERT INTO publish_attempts (id, publication_intent_id) "
                "VALUES (:id, :intent)"
            ),
            {"id": attempt_id, "intent": intent},
        )
        await session.execute(
            text(
                "INSERT INTO publish_retry_commands (id, publication_intent_id) "
                "VALUES (:id, :intent)"
            ),
            {"id": command_id, "intent": intent},
        )
        reg_id = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state,
                    current_attempt_id, current_command_id
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    NULL, :intent, :intent, 'RESERVED',
                    :attempt, :command
                )
                """
            ),
            {
                "id": reg_id,
                "key": build_logical_write_key(
                    tenant, content, "telegram", None, intent
                ),
                "tenant": tenant,
                "content": content,
                "intent": intent,
                "attempt": attempt_id,
                "command": command_id,
            },
        )
        await session.commit()

        await session.execute(
            text("DELETE FROM publish_attempts WHERE id = :id"),
            {"id": attempt_id},
        )
        await session.execute(
            text("DELETE FROM publish_retry_commands WHERE id = :id"),
            {"id": command_id},
        )
        await session.commit()

        still = (
            await session.execute(
                text(
                    "SELECT current_attempt_id, current_command_id "
                    "FROM publish_write_coordination_registry WHERE id = :id"
                ),
                {"id": reg_id},
            )
        ).one()
        # Soft refs retain historical pointers; row itself survives.
        assert still[0] == attempt_id
        assert still[1] == command_id

        with pytest.raises(IntegrityError):
            await session.execute(
                text("DELETE FROM tenants WHERE id = :id"), {"id": tenant}
            )
            await session.commit()
        await session.rollback()

    _run_min(_body)


def test_publication_intent_id_storage_on_attempt_and_command():
    intent = uuid.uuid4()

    async def _body(session: AsyncSession):
        attempt_id = uuid.uuid4()
        command_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO publish_attempts (id, publication_intent_id) "
                "VALUES (:id, :intent)"
            ),
            {"id": attempt_id, "intent": intent},
        )
        await session.execute(
            text(
                "INSERT INTO publish_retry_commands (id, publication_intent_id) "
                "VALUES (:id, :intent)"
            ),
            {"id": command_id, "intent": intent},
        )
        await session.commit()
        a = (
            await session.execute(
                text(
                    "SELECT publication_intent_id FROM publish_attempts WHERE id = :id"
                ),
                {"id": attempt_id},
            )
        ).scalar()
        c = (
            await session.execute(
                text(
                    "SELECT publication_intent_id FROM publish_retry_commands "
                    "WHERE id = :id"
                ),
                {"id": command_id},
            )
        ).scalar()
        assert a == intent
        assert c == intent

        # Historical-null safety
        await session.execute(
            text("INSERT INTO publish_attempts (id) VALUES (:id)"),
            {"id": uuid.uuid4()},
        )
        await session.commit()

    _run_min(_body)


def test_tenant_restrict_preserves_registry_history():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent = uuid.uuid4()

    async def _body(session: AsyncSession):
        await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
        await session.execute(
            text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
        )
        await session.execute(
            text(
                """
                INSERT INTO publish_write_coordination_registry (
                    id, logical_write_key, tenant_id, content_id, platform,
                    account_id, publication_intent_id, root_intent_id, state
                ) VALUES (
                    :id, :key, :tenant, :content, 'telegram',
                    NULL, :intent, :intent, 'RESERVED'
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "key": build_logical_write_key(
                    tenant, content, "telegram", None, intent
                ),
                "tenant": tenant,
                "content": content,
                "intent": intent,
            },
        )
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(
                text("DELETE FROM content_items WHERE id = :id"), {"id": content}
            )
            await session.commit()
        await session.rollback()

    _run_min(_body)
