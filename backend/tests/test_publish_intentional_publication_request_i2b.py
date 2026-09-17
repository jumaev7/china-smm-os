"""I2b — idempotent intent-only publication-request acceptance tests.

Real PostgreSQL (two independent sessions for concurrency). No provider I/O,
no registry mutation, no attempt/retry creation from acceptance.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.models.content import ContentItem
from app.models.publish_intentional_publication_request import (
    build_request_fingerprint,
)
from app.services.publish_intentional_publication_request_service import (
    FAILURE_FINGERPRINT_CONFLICT,
    FAILURE_UNAUTHORIZED_OPERATION,
    INTENT_MODE,
    PublishIntentionalPublicationRequestService as Svc,
)
from app.services.publish_resilience import compute_publish_version
from app.services.tenant_auth_service import CurrentTenantUser

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/postgres"
)
DEFAULT_DB_NAME = "pipr_i2b_test"
FLAG = "PUBLISH_INTENTIONAL_PUBLICATION_REQUESTS_ENABLED"


def _admin_url() -> str:
    return os.environ.get("PIPR_I2B_ADMIN_URL", DEFAULT_ADMIN_URL)


async def _wait_ready(engine, attempts: int = 40) -> None:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"PostgreSQL not ready: {last}")


async def _recreate_database(db_name: str) -> str:
    admin_url = _admin_url()
    target = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
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
        pytest.skip(f"PostgreSQL unavailable for I2b tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for I2b tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return target


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        for tbl in (
            "publish_intentional_publication_requests",
            "publish_write_coordination_registry",
            "publish_retry_commands",
            "publish_attempts",
            "publishing_accounts",
            "content_items",
            "clients",
            "tenants",
        ):
            await conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))

        await conn.execute(text("CREATE TABLE tenants (id UUID PRIMARY KEY)"))
        await conn.execute(
            text(
                """
                CREATE TABLE clients (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL REFERENCES tenants(id)
                )
                """
            )
        )
        # Columns required by ContentItem load_only + compute_publish_version.
        await conn.execute(
            text(
                """
                CREATE TABLE content_items (
                    id UUID PRIMARY KEY,
                    client_id UUID NOT NULL REFERENCES clients(id),
                    media_file_id UUID NULL,
                    platforms TEXT[] DEFAULT '{}',
                    caption_long_ru TEXT NULL,
                    caption_long_en TEXT NULL,
                    caption_short_ru TEXT NULL,
                    hashtags TEXT NULL,
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
                    tenant_id UUID NOT NULL REFERENCES tenants(id),
                    platform VARCHAR(20) NOT NULL,
                    account_name VARCHAR(255) NOT NULL DEFAULT 'acct',
                    account_id VARCHAR(255) NOT NULL DEFAULT '',
                    access_token_encrypted TEXT NULL,
                    refresh_token_encrypted TEXT NULL,
                    expires_at TIMESTAMPTZ NULL,
                    facebook_page_id VARCHAR(255) NULL,
                    instagram_business_account_id VARCHAR(255) NULL,
                    permissions_json TEXT NULL,
                    account_metadata_json TEXT NULL,
                    status VARCHAR(40) NOT NULL DEFAULT 'mock',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        # Enough columns for PublishAttempt ORM SELECT used by I1 reader.
        await conn.execute(
            text(
                """
                CREATE TABLE publish_attempts (
                    id UUID PRIMARY KEY,
                    content_id UUID NOT NULL REFERENCES content_items(id),
                    platform VARCHAR(20) NOT NULL,
                    account_id UUID NULL,
                    status VARCHAR(40) NOT NULL,
                    response TEXT NULL,
                    error TEXT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    idempotency_key VARCHAR(255) NULL,
                    publish_version VARCHAR(64) NULL,
                    attempt_number INT NULL,
                    failure_code VARCHAR(80) NULL,
                    failure_category VARCHAR(40) NULL,
                    retryable BOOLEAN NULL,
                    next_retry_at TIMESTAMPTZ NULL,
                    started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    external_post_id VARCHAR(255) NULL,
                    external_post_url TEXT NULL,
                    lease_owner VARCHAR(255) NULL,
                    lease_expires_at TIMESTAMPTZ NULL,
                    retry_after_seconds INT NULL,
                    retry_command_id UUID NULL,
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
                    tenant_id UUID NOT NULL,
                    client_id UUID NULL,
                    content_id UUID NOT NULL,
                    original_attempt_id UUID NULL,
                    resulting_attempt_id UUID NULL,
                    platform VARCHAR(20) NOT NULL,
                    publishing_account_id UUID NULL,
                    publish_version VARCHAR(64) NULL,
                    destination_key VARCHAR(255) NULL,
                    requested_by UUID NULL,
                    requested_source VARCHAR(40) NULL,
                    idempotency_key VARCHAR(255) NULL,
                    status VARCHAR(40) NOT NULL,
                    reason_code VARCHAR(80) NULL,
                    provider_outcome VARCHAR(40) NULL,
                    lease_owner VARCHAR(255) NULL,
                    lease_expires_at TIMESTAMPTZ NULL,
                    claimed_at TIMESTAMPTZ NULL,
                    started_at TIMESTAMPTZ NULL,
                    provider_write_started_at TIMESTAMPTZ NULL,
                    finished_at TIMESTAMPTZ NULL,
                    correlation_id VARCHAR(64) NULL,
                    publication_intent_id UUID NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE publish_write_coordination_registry (
                    id UUID PRIMARY KEY,
                    marker TEXT NOT NULL DEFAULT 'x'
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
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT uq_pipr_publication_intent_id UNIQUE (publication_intent_id),
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
                ON publish_intentional_publication_requests (
                    tenant_id, content_id, platform, account_id,
                    operation, client_idempotency_key
                ) NULLS NOT DISTINCT
                """
            )
        )


def _user(tenant_id: uuid.UUID, role: str = "owner") -> CurrentTenantUser:
    return CurrentTenantUser(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email=f"{role}@example.com",
        role=role,
        status="active",
        permissions=[],
    )


async def _load_content(session: AsyncSession, content_id: uuid.UUID) -> ContentItem:
    result = await session.execute(
        select(ContentItem)
        .options(
            load_only(
                ContentItem.id,
                ContentItem.client_id,
                ContentItem.caption_long_ru,
                ContentItem.caption_long_en,
                ContentItem.caption_short_ru,
                ContentItem.hashtags,
                ContentItem.media_file_id,
                ContentItem.platforms,
                ContentItem.updated_at,
            )
        )
        .where(ContentItem.id == content_id)
    )
    item = result.scalar_one()
    return item


async def _seed_base(session: AsyncSession) -> dict:
    tenant = uuid.uuid4()
    other_tenant = uuid.uuid4()
    client = uuid.uuid4()
    other_client = uuid.uuid4()
    content = uuid.uuid4()
    other_content = uuid.uuid4()
    account = uuid.uuid4()
    alias = uuid.uuid4()
    other_account = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
    await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": other_tenant})
    await session.execute(
        text("INSERT INTO clients (id, tenant_id) VALUES (:id, :t)"),
        {"id": client, "t": tenant},
    )
    await session.execute(
        text("INSERT INTO clients (id, tenant_id) VALUES (:id, :t)"),
        {"id": other_client, "t": other_tenant},
    )
    await session.execute(
        text(
            """
            INSERT INTO content_items (
                id, client_id, platforms, caption_long_ru, updated_at
            ) VALUES (:id, :c, ARRAY['telegram'], :cap, :u)
            """
        ),
        {"id": content, "c": client, "cap": "hello", "u": now},
    )
    await session.execute(
        text(
            """
            INSERT INTO content_items (
                id, client_id, platforms, caption_long_ru, updated_at
            ) VALUES (:id, :c, ARRAY['telegram'], 'other', :u)
            """
        ),
        {"id": other_content, "c": other_client, "u": now},
    )
    for aid, tid, chat in (
        (account, tenant, "@channel_a"),
        (alias, tenant, "@channel_a"),  # same external destination
        (other_account, other_tenant, "@other"),
    ):
        await session.execute(
            text(
                """
                INSERT INTO publishing_accounts (
                    id, tenant_id, platform, account_name, account_id, status
                ) VALUES (:id, :t, 'telegram', 'tg', :chat, 'mock')
                """
            ),
            {"id": aid, "t": tid, "chat": chat},
        )
    await session.commit()

    item = await _load_content(session, content)
    version = compute_publish_version(item)
    return {
        "tenant": tenant,
        "other_tenant": other_tenant,
        "client": client,
        "content": content,
        "other_content": other_content,
        "account": account,
        "alias": alias,
        "other_account": other_account,
        "version": version,
        "now": now,
    }


def _run(coro_factory):
    async def _main():
        url = await _recreate_database(DEFAULT_DB_NAME)
        engine = create_async_engine(url, echo=False)
        try:
            await _wait_ready(engine)
            await _setup_schema(engine)
            factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            await coro_factory(factory)
        finally:
            await engine.dispose()

    asyncio.run(_main())


# ---------------------------------------------------------------------------
# Static / flag / isolation (no DB required for some)
# ---------------------------------------------------------------------------


def test_flag_default_false():
    assert getattr(settings, FLAG) is False


def test_source_has_no_execution_coupling():
    src = inspect.getsource(Svc)
    forbidden = [
        "acquire_write_authority",
        "mark_write_started",
        "supersede_intent",
        "publish_content(",
        "TelegramPublisher",
        "FacebookPublisher",
        "InstagramPublisher",
        "RetryExecutor",
        "schedule_publish",
    ]
    for token in forbidden:
        assert token not in src, token

    import app.api.v1.publishing as pub_api

    api_src = inspect.getsource(pub_api.accept_intentional_publication_request)
    assert "PublishService" not in api_src
    assert "acquire_write_authority" not in api_src
    assert "publish_content" not in api_src


def test_disabled_feature_creates_zero_rows_and_404():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, False):
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="k1",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 404
                count = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM "
                            "publish_intentional_publication_requests"
                        )
                    )
                ).scalar()
                assert count == 0

    _run(body)


# ---------------------------------------------------------------------------
# Happy path + idempotency
# ---------------------------------------------------------------------------


def test_new_accept_mints_one_intent():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                result = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="key-new",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
                assert result.idempotent_replay is False
                assert result.request.publication_intent_id is not None
                assert result.request.status == "accepted"
                payload = Svc.serialize(result)
                assert payload["accepted"] is True
                assert payload["write_authorized"] is False
                assert payload["idempotent_replay"] is False

    _run(body)


def test_b_duplicate_after_restart_same_ids():
    """B/D — replay after simulated restart / response loss."""

    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                first = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="key-replay",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
                rid, intent = first.request.id, first.request.publication_intent_id

            # New session ≈ process restart / lost response.
            async with factory() as session:
                second = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="key-replay",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
                assert second.idempotent_replay is True
                assert second.request.id == rid
                assert second.request.publication_intent_id == intent
                count = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM "
                            "publish_intentional_publication_requests"
                        )
                    )
                ).scalar()
                assert count == 1

    _run(body)


def test_c_same_key_different_fingerprint_409():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="key-fp",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()

            # Wrong expected version before content edit → version mismatch
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="key-fp",
                        expected_publish_version="pv_deadbeefdeadbeef",
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 409

            # Same key after content edit with new version → fingerprint conflict
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE content_items SET caption_long_ru = 'edited' "
                        "WHERE id = :id"
                    ),
                    {"id": ids["content"]},
                )
                await session.commit()
                item = await _load_content(session, ids["content"])
                new_ver = compute_publish_version(item)
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="key-fp",
                        expected_publish_version=new_ver,
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 409
                detail = ei.value.detail
                assert detail["failure_code"] == FAILURE_FINGERPRINT_CONFLICT
                count = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM "
                            "publish_intentional_publication_requests"
                        )
                    )
                ).scalar()
                assert count == 1

    _run(body)


def test_e_two_distinct_keys_two_rows_zero_provider_writes():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
            attempts_before = (
                await session.execute(text("SELECT COUNT(*) FROM publish_attempts"))
            ).scalar()
            registry_before = (
                await session.execute(
                    text("SELECT COUNT(*) FROM publish_write_coordination_registry")
                )
            ).scalar()
            cmds_before = (
                await session.execute(text("SELECT COUNT(*) FROM publish_retry_commands"))
            ).scalar()

        provider = MagicMock()
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                a = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="key-a",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                b = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="key-b",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
                assert a.request.id != b.request.id
                assert (
                    a.request.publication_intent_id
                    != b.request.publication_intent_id
                )
                count = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM "
                            "publish_intentional_publication_requests"
                        )
                    )
                ).scalar()
                assert count == 2
                assert (
                    await session.execute(text("SELECT COUNT(*) FROM publish_attempts"))
                ).scalar() == attempts_before
                assert (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM publish_write_coordination_registry"
                        )
                    )
                ).scalar() == registry_before
                assert (
                    await session.execute(
                        text("SELECT COUNT(*) FROM publish_retry_commands")
                    )
                ).scalar() == cmds_before
                provider.assert_not_called()

    _run(body)


def test_f_duplicate_null_account_one_row():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                first = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=None,
                    operation="initial_publish",
                    client_idempotency_key="null-key",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
            async with factory() as session:
                second = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=None,
                    operation="initial_publish",
                    client_idempotency_key="null-key",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
                assert second.idempotent_replay is True
                assert second.request.id == first.request.id
                count = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM "
                            "publish_intentional_publication_requests "
                            "WHERE account_id IS NULL"
                        )
                    )
                ).scalar()
                assert count == 1

    _run(body)


# ---------------------------------------------------------------------------
# Real dual-session concurrency (A)
# ---------------------------------------------------------------------------


def test_a_concurrent_same_key_one_row_one_intent():
    """Independent PostgreSQL sessions — not an in-memory dict simulation."""

    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)

        barrier = asyncio.Barrier(2)
        results: list = []
        errors: list = []

        async def worker(key_suffix: str = ""):
            try:
                async with factory() as session:
                    with patch.object(settings, FLAG, True):
                        await barrier.wait()
                        result = await Svc.accept(
                            session,
                            tenant_id=ids["tenant"],
                            content_id=ids["content"],
                            platform="telegram",
                            account_id=ids["account"],
                            operation="initial_publish",
                            client_idempotency_key="concurrent-key",
                            expected_publish_version=ids["version"],
                            user=_user(ids["tenant"]),
                        )
                        await session.commit()
                        results.append(result)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with patch.object(settings, FLAG, True):
            await asyncio.gather(worker(), worker())

        assert not errors, errors
        assert len(results) == 2
        ids_set = {r.request.id for r in results}
        intents = {r.request.publication_intent_id for r in results}
        assert len(ids_set) == 1
        assert len(intents) == 1
        assert sum(1 for r in results if r.idempotent_replay) == 1
        assert sum(1 for r in results if not r.idempotent_replay) == 1

        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM "
                        "publish_intentional_publication_requests"
                    )
                )
            ).scalar()
            assert count == 1

    _run(body)


# ---------------------------------------------------------------------------
# Tenant / auth / destination safety
# ---------------------------------------------------------------------------


def test_i_cross_tenant_cannot_replay():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="tenant-key",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()

            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["other_tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="tenant-key",
                        expected_publish_version=ids["version"],
                        user=_user(ids["other_tenant"]),
                    )
                assert ei.value.status_code == 403

    _run(body)


def test_j_forged_relationships_rejected():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            # Wrong tenant claiming other tenant content
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["other_content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="forge-content",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 403

            # Foreign account id
            async with factory() as session:
                item = await _load_content(session, ids["content"])
                ver = compute_publish_version(item)
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["other_account"],
                        operation="initial_publish",
                        client_idempotency_key="forge-acct",
                        expected_publish_version=ver,
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 403

    _run(body)


def test_k_operator_cannot_intentional_republish():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="intentional_republish",
                        client_idempotency_key="repub",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"], role="operator"),
                    )
                assert ei.value.status_code == 403
                assert ei.value.detail["failure_code"] == FAILURE_UNAUTHORIZED_OPERATION

            async with factory() as session:
                # viewer blocked even for initial
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="viewer",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"], role="viewer"),
                    )
                assert ei.value.status_code == 403

    _run(body)


def test_t_wrong_platform_account_rejected():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
            fb = uuid.uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO publishing_accounts (
                        id, tenant_id, platform, account_name, account_id,
                        status, facebook_page_id
                    ) VALUES (
                        :id, :t, 'facebook', 'fb', 'page', 'mock', 'page-1'
                    )
                    """
                ),
                {"id": fb, "t": ids["tenant"]},
            )
            await session.commit()
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=fb,
                        operation="initial_publish",
                        client_idempotency_key="plat-mismatch",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 400

    _run(body)


def test_h_historical_null_destination_fail_closed():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
            await session.execute(
                text(
                    """
                    INSERT INTO publish_attempts (
                        id, content_id, platform, account_id, status,
                        response, external_post_id
                    ) VALUES (
                        :id, :c, 'telegram', NULL, 'success',
                        :resp, 'ext-1'
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "c": ids["content"],
                    "resp": '{"platform_post_id":"ext-1","success":true}',
                },
            )
            await session.commit()
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="null-hist",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 422
                assert "destination" in str(ei.value.detail).lower() or (
                    isinstance(ei.value.detail, dict)
                    and "unresolved" in ei.value.detail.get("failure_code", "")
                )

    _run(body)


def test_g_alias_does_not_bypass_unresolved_prior_write():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
            await session.execute(
                text(
                    """
                    INSERT INTO publish_retry_commands (
                        id, tenant_id, content_id, platform,
                        publishing_account_id, status, provider_write_started_at
                    ) VALUES (
                        :id, :t, :c, 'telegram', :acct, 'ambiguous', NULL
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "t": ids["tenant"],
                    "c": ids["content"],
                    "acct": ids["account"],
                },
            )
            await session.commit()
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["alias"],  # SAME external destination
                        operation="initial_publish",
                        client_idempotency_key="alias-bypass",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 422

    _run(body)


def test_m_n_content_edit_no_silent_substitution_or_second_intent():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                first = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="edit-key",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
                intent = first.request.publication_intent_id

            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE content_items SET caption_long_ru = 'changed-caption' "
                        "WHERE id = :id"
                    ),
                    {"id": ids["content"]},
                )
                await session.commit()
                item = await _load_content(session, ids["content"])
                new_ver = compute_publish_version(item)
                assert new_ver != ids["version"]

                # Replay original fingerprint (old expected version) fails version check
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="edit-key",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 409

                # New version + same key → fingerprint conflict, no second intent
                with pytest.raises(HTTPException) as ei2:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="edit-key",
                        expected_publish_version=new_ver,
                        user=_user(ids["tenant"]),
                    )
                assert ei2.value.status_code == 409
                assert ei2.value.detail["failure_code"] == FAILURE_FINGERPRINT_CONFLICT

                count = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM "
                            "publish_intentional_publication_requests"
                        )
                    )
                ).scalar()
                assert count == 1
                row_intent = (
                    await session.execute(
                        text(
                            "SELECT publication_intent_id FROM "
                            "publish_intentional_publication_requests"
                        )
                    )
                ).scalar()
                assert row_intent == intent

    _run(body)


def test_o_p_q_r_s_no_side_effects():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
            # seed one registry marker to prove unchanged
            await session.execute(
                text(
                    "INSERT INTO publish_write_coordination_registry (id, marker) "
                    "VALUES (:id, 'pre')"
                ),
                {"id": uuid.uuid4()},
            )
            await session.commit()

        publish_mock = AsyncMock()
        with (
            patch.object(settings, FLAG, True),
            patch(
                "app.services.publish_service.PublishService.publish_content",
                publish_mock,
            ),
        ):
            async with factory() as session:
                await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="initial_publish",
                    client_idempotency_key="side-fx",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"]),
                )
                await session.commit()
                assert (
                    await session.execute(text("SELECT COUNT(*) FROM publish_attempts"))
                ).scalar() == 0
                assert (
                    await session.execute(
                        text("SELECT COUNT(*) FROM publish_retry_commands")
                    )
                ).scalar() == 0
                assert (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM publish_write_coordination_registry"
                        )
                    )
                ).scalar() == 1
                publish_mock.assert_not_called()

                # S — no historical intent backfill on attempts
                null_intents = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM publish_attempts "
                            "WHERE 1=0"  # table has no publication_intent_id in fixture
                        )
                    )
                ).scalar()
                assert null_intents == 0

    _run(body)


def test_missing_key_400():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                with pytest.raises(HTTPException) as ei:
                    await Svc.accept(
                        session,
                        tenant_id=ids["tenant"],
                        content_id=ids["content"],
                        platform="telegram",
                        account_id=ids["account"],
                        operation="initial_publish",
                        client_idempotency_key="   ",
                        expected_publish_version=ids["version"],
                        user=_user(ids["tenant"]),
                    )
                assert ei.value.status_code == 400

    _run(body)


def test_prior_live_success_accepts_but_not_write_authorized():
    async def body(factory):
        async with factory() as session:
            ids = await _seed_base(session)
            await session.execute(
                text(
                    """
                    INSERT INTO publish_attempts (
                        id, content_id, platform, account_id, status,
                        response, external_post_id
                    ) VALUES (
                        :id, :c, 'telegram', :a, 'success',
                        :resp, 'ext-ok'
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "c": ids["content"],
                    "a": ids["account"],
                    "resp": '{"platform_post_id":"ext-ok","success":true}',
                },
            )
            await session.commit()
        with patch.object(settings, FLAG, True):
            async with factory() as session:
                result = await Svc.accept(
                    session,
                    tenant_id=ids["tenant"],
                    content_id=ids["content"],
                    platform="telegram",
                    account_id=ids["account"],
                    operation="intentional_republish",
                    client_idempotency_key="after-success",
                    expected_publish_version=ids["version"],
                    user=_user(ids["tenant"], role="owner"),
                )
                await session.commit()
                assert result.prior_live_success is True
                payload = Svc.serialize(result)
                assert payload["write_authorized"] is False
                assert "does not authorize" in payload["acceptance_note"].lower()

    _run(body)


def test_fingerprint_helper_matches_service_inputs():
    tenant, content, account = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fp = build_request_fingerprint(
        tenant_id=tenant,
        content_id=content,
        platform="telegram",
        account_id=account,
        operation="initial_publish",
        publish_version="pv_abc",
        intent_mode=INTENT_MODE,
    )
    assert len(fp) == 64
    assert fp == build_request_fingerprint(
        tenant_id=tenant,
        content_id=content,
        platform="Telegram",
        account_id=account,
        operation="initial_publish",
        publish_version="pv_abc",
        intent_mode=INTENT_MODE,
    )


def test_ordinary_publish_unaffected_when_flag_false():
    """Regression: existing publish path must not require I2b headers."""
    import app.api.v1.content as content_api

    src = inspect.getsource(content_api.publish_content)
    assert "intentional_publication" not in src
    assert "client_idempotency_key" not in src
    assert getattr(settings, FLAG) is False
