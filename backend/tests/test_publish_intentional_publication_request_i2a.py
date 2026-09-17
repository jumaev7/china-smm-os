"""I2a — durable intentional publication-request schema/model tests only.

Covers migration upgrade/downgrade, request-key uniqueness (NULLS NOT DISTINCT),
intent uniqueness, domains, FKs, concurrent inserts, feature-flag default,
Compose pin, ORM/metadata match, and dormancy (no runtime activation).

No PublishService wiring, minting, API, or provider I/O.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_intentional_publication_request import (
    PUBLICATION_REQUEST_OPERATIONS,
    PUBLICATION_REQUEST_STATUSES,
    REQUEST_FINGERPRINT_LENGTH,
    PublishIntentionalPublicationRequest,
    build_request_fingerprint,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
COMPOSE = REPO_ROOT / "docker-compose.production.yml"

DEFAULT_ADMIN_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/postgres"
)
DEFAULT_DB_NAME = "pipr_i2a_test"
PREV_HEAD = "20260927_publish_write_coordination_registry"
I2A_REV = "20260928_publish_intentional_publication_requests"
FLAG_NAME = "PUBLISH_INTENTIONAL_PUBLICATION_REQUESTS_ENABLED"
FAIL_CLOSED = f"${{{FLAG_NAME}:-false}}"

HEX64 = "a" * 64
HEX64_B = "b" * 64


def _admin_url() -> str:
    return os.environ.get("PIPR_I2A_ADMIN_URL", DEFAULT_ADMIN_URL)


def _db_url() -> str:
    override = os.environ.get("PIPR_I2A_PG_URL")
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
        pytest.skip(f"PostgreSQL unavailable for I2a tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for I2a tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return target_url


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
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


async def _setup_minimal_pipr_schema(engine) -> None:
    """Parent stubs + PIPR DDL matching I2a constraints (no full migrate)."""
    async with engine.begin() as conn:
        await conn.execute(
            text("DROP TABLE IF EXISTS publish_intentional_publication_requests CASCADE")
        )
        await conn.execute(text("DROP TABLE IF EXISTS publishing_accounts CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS content_items CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS tenants CASCADE"))

        await conn.execute(text("CREATE TABLE tenants (id UUID PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE content_items (id UUID PRIMARY KEY)"))
        # account.tenant_id present for documentation of service-layer checks;
        # no composite FK from PIPR (matches production parent schema limits).
        await conn.execute(
            text(
                """
                CREATE TABLE publishing_accounts (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NULL REFERENCES tenants(id)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE publish_intentional_publication_requests (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
                    content_id UUID NOT NULL REFERENCES content_items(id) ON DELETE RESTRICT,
                    platform VARCHAR(20) NOT NULL,
                    account_id UUID NULL REFERENCES publishing_accounts(id) ON DELETE RESTRICT,
                    operation VARCHAR(40) NOT NULL,
                    client_idempotency_key VARCHAR(255) NOT NULL,
                    request_fingerprint VARCHAR(64) NOT NULL,
                    publication_intent_id UUID NOT NULL,
                    publish_version VARCHAR(64) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'accepted',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_pipr_publication_intent_id
                        UNIQUE (publication_intent_id),
                    CONSTRAINT ck_pipr_operation CHECK (
                        operation IN ('initial_publish', 'intentional_republish')
                    ),
                    CONSTRAINT ck_pipr_status CHECK (status IN ('accepted')),
                    CONSTRAINT ck_pipr_client_key_nonempty CHECK (
                        char_length(btrim(client_idempotency_key)) > 0
                    ),
                    CONSTRAINT ck_pipr_fingerprint_sha256_hex CHECK (
                        char_length(request_fingerprint) = 64
                        AND request_fingerprint ~ '^[0-9a-f]{64}$'
                    )
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX uq_pipr_request_identity
                ON publish_intentional_publication_requests
                (tenant_id, content_id, platform, account_id,
                 operation, client_idempotency_key)
                NULLS NOT DISTINCT
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX ix_pipr_tenant_content
                ON publish_intentional_publication_requests (tenant_id, content_id)
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX ix_pipr_client_idempotency_key
                ON publish_intentional_publication_requests (client_idempotency_key)
                """
            )
        )


async def _with_minimal_pg(coro_factory):
    url = await _recreate_database(DEFAULT_DB_NAME + "_min")
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_minimal_pipr_schema(engine)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await coro_factory(factory)
    except OSError as exc:
        pytest.skip(f"PostgreSQL I2a minimal schema unavailable: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL I2a minimal schema unavailable: {exc}")
        raise
    finally:
        await engine.dispose()


def _run_min(coro_factory):
    asyncio.run(_with_minimal_pg(coro_factory))


async def _seed_parents(
    session: AsyncSession,
    *,
    tenant: uuid.UUID,
    content: uuid.UUID,
    account: uuid.UUID | None = None,
    account_tenant: uuid.UUID | None = None,
) -> None:
    await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
    await session.execute(
        text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
    )
    if account is not None:
        await session.execute(
            text(
                "INSERT INTO publishing_accounts (id, tenant_id) "
                "VALUES (:id, :tenant)"
            ),
            {"id": account, "tenant": account_tenant},
        )
    await session.commit()


async def _insert_request(
    session: AsyncSession,
    *,
    tenant: uuid.UUID,
    content: uuid.UUID,
    platform: str = "telegram",
    account: uuid.UUID | None = None,
    operation: str = "initial_publish",
    client_key: str = "client-key-1",
    fingerprint: str = HEX64,
    intent: uuid.UUID | None = None,
    publish_version: str = "pv1",
    status: str = "accepted",
    row_id: uuid.UUID | None = None,
) -> uuid.UUID:
    rid = row_id or uuid.uuid4()
    intent_id = intent or uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO publish_intentional_publication_requests (
                id, tenant_id, content_id, platform, account_id, operation,
                client_idempotency_key, request_fingerprint, publication_intent_id,
                publish_version, status
            ) VALUES (
                :id, :tenant, :content, :platform, :account, :operation,
                :client_key, :fp, :intent, :pv, :status
            )
            """
        ),
        {
            "id": rid,
            "tenant": tenant,
            "content": content,
            "platform": platform,
            "account": account,
            "operation": operation,
            "client_key": client_key,
            "fp": fingerprint,
            "intent": intent_id,
            "pv": publish_version,
            "status": status,
        },
    )
    return rid


# ---------------------------------------------------------------------------
# Unit / config / dormancy (no DB)
# ---------------------------------------------------------------------------


def test_operation_and_status_domains():
    assert PUBLICATION_REQUEST_OPERATIONS == {
        "initial_publish",
        "intentional_republish",
    }
    assert PUBLICATION_REQUEST_STATUSES == {"accepted"}


def test_build_request_fingerprint_contract():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    account = uuid.uuid4()
    fp1 = build_request_fingerprint(
        tenant_id=tenant,
        content_id=content,
        platform="Telegram",
        account_id=None,
        operation="initial_publish",
        publish_version="v1",
        intent_mode="mint_new",
    )
    fp2 = build_request_fingerprint(
        tenant_id=tenant,
        content_id=content,
        platform="telegram",
        account_id=None,
        operation="initial_publish",
        publish_version="v1",
        intent_mode="mint_new",
    )
    fp3 = build_request_fingerprint(
        tenant_id=tenant,
        content_id=content,
        platform="telegram",
        account_id=account,
        operation="initial_publish",
        publish_version="v1",
        intent_mode="mint_new",
    )
    assert fp1 == fp2
    assert len(fp1) == REQUEST_FINGERPRINT_LENGTH == 64
    assert re.fullmatch(r"[0-9a-f]{64}", fp1)
    assert fp1 != fp3


def test_orm_model_columns_and_constraints():
    assert (
        PublishIntentionalPublicationRequest.__tablename__
        == "publish_intentional_publication_requests"
    )
    cols = {c.name for c in PublishIntentionalPublicationRequest.__table__.columns}
    required = {
        "id",
        "tenant_id",
        "content_id",
        "platform",
        "account_id",
        "operation",
        "client_idempotency_key",
        "request_fingerprint",
        "publication_intent_id",
        "publish_version",
        "status",
        "created_at",
        "updated_at",
    }
    assert required.issubset(cols)
    assert PublishIntentionalPublicationRequest.__table__.c.account_id.nullable is True
    assert PublishIntentionalPublicationRequest.__table__.c.tenant_id.nullable is False
    assert (
        PublishIntentionalPublicationRequest.__table__.c.request_fingerprint.nullable
        is False
    )


def test_feature_flag_defaults_false():
    assert getattr(settings, FLAG_NAME) is False
    assert type(settings).model_fields[FLAG_NAME].default is False


def test_production_compose_pins_flag_false():
    text_body = COMPOSE.read_text(encoding="utf-8")
    assert FLAG_NAME in text_body
    assert FAIL_CLOSED in text_body
    # Effective default when unset is false (Compose substitution pin).
    assert f"{FLAG_NAME}: {FAIL_CLOSED}" in text_body or (
        f"{FLAG_NAME}: ${{{FLAG_NAME}:-false}}" in text_body
    )


def test_model_import_creates_no_request_rows_side_effect():
    """Importing the model module must not insert rows (no startup backfill)."""
    import app.models.publish_intentional_publication_request as mod

    assert mod.PublishIntentionalPublicationRequest.__tablename__ == (
        "publish_intentional_publication_requests"
    )
    assert not hasattr(mod, "_STARTUP_BACKFILL")
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "session.add" not in source
    assert "INSERT INTO" not in source.upper()
    # Class body registers metadata only; no engine / create_all / seed calls.
    assert "create_engine" not in source
    assert "create_async_engine" not in source
    assert "create_all" not in source


def test_dormancy_no_publish_service_wiring():
    """I2a→I2b: PublishService / retry / workers must not wire PIPR execution.

    I2b may reference the model only from the dedicated intent-acceptance
    service and the intentional-publication-requests API route. Provider
    execution paths remain unwired.
    """
    repo = REPO_ROOT
    forbidden_hits: list[str] = []
    # I2b allowlist — intent acceptance only (no provider execution).
    allowed_relpaths = {
        Path("backend/app/services/publish_intentional_publication_request_service.py"),
        Path("backend/app/api/v1/publishing.py"),
    }
    scan_roots = [
        repo / "backend" / "app" / "services",
        repo / "backend" / "app" / "api",
        repo / "backend" / "app" / "workers",
        repo / "backend" / "app" / "main.py",
    ]
    needles = (
        "PublishIntentionalPublicationRequest",
        "publish_intentional_publication_requests",
        "build_request_fingerprint",
    )
    for root in scan_roots:
        if root.is_file():
            paths = [root]
        elif root.is_dir():
            paths = list(root.rglob("*.py"))
        else:
            continue
        for path in paths:
            rel = path.relative_to(repo)
            if rel in allowed_relpaths:
                continue
            body = path.read_text(encoding="utf-8")
            for needle in needles:
                if needle in body:
                    forbidden_hits.append(f"{rel}:{needle}")
    assert forbidden_hits == []

    # Explicit: PublishService still must not mint or reference PIPR.
    publish_svc = (
        repo / "backend" / "app" / "services" / "publish_service.py"
    ).read_text(encoding="utf-8")
    for needle in needles:
        assert needle not in publish_svc, needle


# ---------------------------------------------------------------------------
# Migration upgrade / downgrade + R1 intact
# ---------------------------------------------------------------------------


def test_migration_upgrade_downgrade_preserves_r1():
    url = asyncio.run(_recreate_database(DEFAULT_DB_NAME + "_mig"))
    _alembic_upgrade(url, "head")

    engine = create_async_engine(url, echo=False)

    async def _assert_upgraded():
        await _wait_ready(engine)
        async with engine.connect() as conn:
            ver = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
            assert ver == I2A_REV

            for table in (
                "publish_intentional_publication_requests",
                "publish_write_coordination_registry",
                "publish_attempts",
                "publish_retry_commands",
            ):
                exists = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_name = :t"
                        ),
                        {"t": table},
                    )
                ).first()
                assert exists is not None, table

            for col_table in ("publish_attempts", "publish_retry_commands"):
                col = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name = :t "
                            "AND column_name = 'publication_intent_id'"
                        ),
                        {"t": col_table},
                    )
                ).first()
                assert col is not None, col_table

            idx = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = 'uq_pipr_request_identity'"
                    )
                )
            ).scalar()
            assert idx is not None
            assert "nulls not distinct" in idx.lower()

            pg_ver = (await conn.execute(text("SHOW server_version"))).scalar()
            major = int(str(pg_ver).split(".")[0])
            assert major >= 15

    asyncio.run(_assert_upgraded())
    asyncio.run(engine.dispose())

    # Capture R1 table row counts before downgrade (empty is fine; proves
    # I2a downgrade does not drop R1 tables or rewrite historical counts).
    engine_seed = create_async_engine(url, echo=False)

    async def _count_r1_rows():
        await _wait_ready(engine_seed)
        async with engine_seed.connect() as conn:
            attempt_count_before = (
                await conn.execute(text("SELECT COUNT(*) FROM publish_attempts"))
            ).scalar()
            registry_count_before = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM publish_write_coordination_registry")
                )
            ).scalar()
            return attempt_count_before, registry_count_before

    attempt_before, registry_before = asyncio.run(_count_r1_rows())
    asyncio.run(engine_seed.dispose())

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
                        "WHERE table_name = "
                        "'publish_intentional_publication_requests'"
                    )
                )
            ).first()
            assert gone is None

            registry = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'publish_write_coordination_registry'"
                    )
                )
            ).first()
            assert registry is not None

            for col_table in ("publish_attempts", "publish_retry_commands"):
                col = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name = :t "
                            "AND column_name = 'publication_intent_id'"
                        ),
                        {"t": col_table},
                    )
                ).first()
                assert col is not None, col_table

            attempt_after = (
                await conn.execute(text("SELECT COUNT(*) FROM publish_attempts"))
            ).scalar()
            registry_after = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM publish_write_coordination_registry")
                )
            ).scalar()
            assert attempt_after == attempt_before
            assert registry_after == registry_before

    asyncio.run(_assert_downgraded())
    asyncio.run(engine2.dispose())

    _alembic_upgrade(url, "head")
    engine3 = create_async_engine(url, echo=False)

    async def _assert_reupgraded():
        await _wait_ready(engine3)
        async with engine3.connect() as conn:
            ver = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
            assert ver == I2A_REV

    asyncio.run(_assert_reupgraded())
    asyncio.run(engine3.dispose())


def test_orm_metadata_matches_migrated_schema():
    url = asyncio.run(_recreate_database(DEFAULT_DB_NAME + "_meta"))
    _alembic_upgrade(url, "head")
    engine = create_async_engine(url, echo=False)

    async def _body():
        await _wait_ready(engine)
        async with engine.connect() as conn:

            def _reflect(sync_conn):
                insp = inspect(sync_conn)
                cols = {
                    c["name"]
                    for c in insp.get_columns(
                        "publish_intentional_publication_requests"
                    )
                }
                indexes = {
                    i["name"]
                    for i in insp.get_indexes(
                        "publish_intentional_publication_requests"
                    )
                }
                uniques = insp.get_unique_constraints(
                    "publish_intentional_publication_requests"
                )
                return cols, indexes, uniques

            db_cols, idx_names, uniques = await conn.run_sync(_reflect)
            orm_cols = {
                c.name for c in PublishIntentionalPublicationRequest.__table__.columns
            }
            assert orm_cols == db_cols
            assert "uq_pipr_request_identity" in idx_names
            assert "ix_pipr_tenant_content" in idx_names
            assert "ix_pipr_client_idempotency_key" in idx_names

            unique_names = {u["name"] for u in uniques}
            assert "uq_pipr_publication_intent_id" in unique_names or any(
                u.get("column_names") == ["publication_intent_id"] for u in uniques
            )

            idxdef = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = 'uq_pipr_request_identity'"
                    )
                )
            ).scalar()
            assert "nulls not distinct" in idxdef.lower()

    asyncio.run(_body())
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Constraint tests (minimal real PostgreSQL)
# ---------------------------------------------------------------------------


def test_insert_valid_request_row():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            await _insert_request(session, tenant=tenant, content=content)
            await session.commit()
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM "
                        "publish_intentional_publication_requests"
                    )
                )
            ).scalar()
            assert count == 1

    _run_min(body)


def test_duplicate_full_request_key_rejected():
    tenant, content, account = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(
                session,
                tenant=tenant,
                content=content,
                account=account,
                account_tenant=tenant,
            )
            await _insert_request(
                session,
                tenant=tenant,
                content=content,
                account=account,
                client_key="same-key",
                intent=uuid.uuid4(),
            )
            await session.commit()
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    account=account,
                    client_key="same-key",
                    fingerprint=HEX64_B,
                    intent=uuid.uuid4(),
                )
                await session.commit()
            await session.rollback()

    _run_min(body)


def test_duplicate_null_account_request_key_rejected():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            await _insert_request(
                session,
                tenant=tenant,
                content=content,
                account=None,
                client_key="null-acct-key",
            )
            await session.commit()
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    account=None,
                    client_key="null-acct-key",
                    fingerprint=HEX64_B,
                    intent=uuid.uuid4(),
                )
                await session.commit()
            await session.rollback()

    _run_min(body)


def test_same_client_key_different_scope_allowed():
    """Same client key under different operation / destination is allowed."""
    tenant, content = uuid.uuid4(), uuid.uuid4()
    account = uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(
                session,
                tenant=tenant,
                content=content,
                account=account,
                account_tenant=tenant,
            )
            await _insert_request(
                session,
                tenant=tenant,
                content=content,
                account=None,
                operation="initial_publish",
                client_key="reuse-key",
                intent=uuid.uuid4(),
            )
            # Different operation — allowed
            await _insert_request(
                session,
                tenant=tenant,
                content=content,
                account=None,
                operation="intentional_republish",
                client_key="reuse-key",
                fingerprint=HEX64_B,
                intent=uuid.uuid4(),
            )
            # Different account destination — allowed
            await _insert_request(
                session,
                tenant=tenant,
                content=content,
                account=account,
                operation="initial_publish",
                client_key="reuse-key",
                fingerprint="c" * 64,
                intent=uuid.uuid4(),
            )
            await session.commit()
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM "
                        "publish_intentional_publication_requests "
                        "WHERE client_idempotency_key = 'reuse-key'"
                    )
                )
            ).scalar()
            assert count == 3

    _run_min(body)


def test_duplicate_publication_intent_id_rejected():
    tenant, content = uuid.uuid4(), uuid.uuid4()
    intent = uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            await _insert_request(
                session,
                tenant=tenant,
                content=content,
                client_key="k1",
                intent=intent,
            )
            await session.commit()
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    client_key="k2",
                    fingerprint=HEX64_B,
                    intent=intent,
                )
                await session.commit()
            await session.rollback()

    _run_min(body)


def test_invalid_operation_rejected():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    operation="technical_retry",
                )
                await session.commit()
            await session.rollback()

    _run_min(body)


def test_invalid_status_rejected():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    status="write_authorized",
                )
                await session.commit()
            await session.rollback()

    _run_min(body)


def test_empty_client_key_rejected():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    client_key="   ",
                )
                await session.commit()
            await session.rollback()
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    client_key="",
                )
                await session.commit()
            await session.rollback()

    _run_min(body)


def test_empty_or_invalid_fingerprint_rejected():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            for bad in ("", "short", "G" * 64, "A" * 64):
                with pytest.raises(IntegrityError):
                    await _insert_request(
                        session,
                        tenant=tenant,
                        content=content,
                        fingerprint=bad,
                        client_key=f"k-{bad[:8] or 'empty'}-{uuid.uuid4()}",
                        intent=uuid.uuid4(),
                    )
                    await session.commit()
                await session.rollback()

    _run_min(body)


def test_foreign_key_violations_rejected():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=uuid.uuid4(),
                    content=content,
                )
                await session.commit()
            await session.rollback()
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=uuid.uuid4(),
                )
                await session.commit()
            await session.rollback()
            with pytest.raises(IntegrityError):
                await _insert_request(
                    session,
                    tenant=tenant,
                    content=content,
                    account=uuid.uuid4(),
                )
                await session.commit()
            await session.rollback()

    _run_min(body)


def test_tenant_consistency_not_db_enforced():
    """Documented: ordinary FKs do not reject cross-tenant account linkage."""
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    content, account = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await session.execute(
                text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant_a}
            )
            await session.execute(
                text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant_b}
            )
            await session.execute(
                text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
            )
            # Account belongs to tenant_b; request claims tenant_a — allowed by DB.
            await session.execute(
                text(
                    "INSERT INTO publishing_accounts (id, tenant_id) "
                    "VALUES (:id, :tenant)"
                ),
                {"id": account, "tenant": tenant_b},
            )
            await session.commit()
            await _insert_request(
                session,
                tenant=tenant_a,
                content=content,
                account=account,
            )
            await session.commit()
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM "
                        "publish_intentional_publication_requests"
                    )
                )
            ).scalar()
            assert count == 1

    _run_min(body)


def test_concurrent_duplicate_request_identity_one_winner():
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)

        successes: list[uuid.UUID] = []
        errors: list[BaseException] = []

        async def worker(intent: uuid.UUID):
            async with factory() as session:
                try:
                    await _insert_request(
                        session,
                        tenant=tenant,
                        content=content,
                        account=None,
                        client_key="concurrent-key",
                        intent=intent,
                        fingerprint=HEX64 if intent.int % 2 == 0 else HEX64_B,
                    )
                    await session.commit()
                    successes.append(intent)
                except IntegrityError as exc:
                    await session.rollback()
                    errors.append(exc)

        await asyncio.gather(worker(uuid.uuid4()), worker(uuid.uuid4()))
        assert len(successes) == 1
        assert len(errors) == 1
        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM "
                        "publish_intentional_publication_requests "
                        "WHERE client_idempotency_key = 'concurrent-key'"
                    )
                )
            ).scalar()
            assert count == 1

    _run_min(body)


def test_concurrent_duplicate_intent_identity_one_winner():
    tenant, content = uuid.uuid4(), uuid.uuid4()
    shared_intent = uuid.uuid4()

    async def body(factory):
        async with factory() as session:
            await _seed_parents(session, tenant=tenant, content=content)

        successes: list[str] = []
        errors: list[BaseException] = []

        async def worker(client_key: str, fingerprint: str):
            async with factory() as session:
                try:
                    await _insert_request(
                        session,
                        tenant=tenant,
                        content=content,
                        client_key=client_key,
                        fingerprint=fingerprint,
                        intent=shared_intent,
                    )
                    await session.commit()
                    successes.append(client_key)
                except IntegrityError as exc:
                    await session.rollback()
                    errors.append(exc)

        await asyncio.gather(
            worker("ck-a", HEX64),
            worker("ck-b", HEX64_B),
        )
        assert len(successes) == 1
        assert len(errors) == 1
        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM "
                        "publish_intentional_publication_requests "
                        "WHERE publication_intent_id = :intent"
                    ),
                    {"intent": shared_intent},
                )
            ).scalar()
            assert count == 1

    _run_min(body)
