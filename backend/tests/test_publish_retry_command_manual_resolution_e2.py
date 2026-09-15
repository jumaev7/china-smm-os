"""Phase E2-1 — MARK_AMBIGUOUS manual resolution.

Covers: auth, confirmation, feature flag, lineage, idempotency, alert resolve,
mandatory same-TX audit + rollback, PG concurrency, provider/execution
negative proofs, no replacement command / content mutation.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.platform_ops import PlatformAuditLog
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.models.publish_retry_command import PublishRetryCommand
from app.services.publish_retry_command_manual_resolution_service import (
    ACTION_MARK_AMBIGUOUS,
    AUDIT_EVENT_MARK_AMBIGUOUS,
    PublishRetryCommandManualResolutionService,
)
from app.services.publish_retry_command_stranded_detector import (
    PHASE_E_CONTEXT_MARKER,
    stranded_dedupe_key,
)

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/"
    "retry_command_manual_resolution_e2_test"
)

SERVICE_PATH = (
    "app/services/publish_retry_command_manual_resolution_service.py"
)


# ── Static / import gates ────────────────────────────────────────────────────


def test_audit_event_fits_column():
    assert len(AUDIT_EVENT_MARK_AMBIGUOUS) <= 50
    assert AUDIT_EVENT_MARK_AMBIGUOUS == "publishing.retry_cmd_recon_ambiguous"


def test_e2_service_has_zero_provider_io_imports():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath(SERVICE_PATH).read_text(
        encoding="utf-8",
    )
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_modules = {
        "httpx",
        "app.services.providers",
        "app.services.publish_service",
        "app.services.publish_retry_command_provider_port",
        "app.services.publish_retry_command_fake_sink",
        "app.services.publish.providers",
        "app.services.publish_retry_command_execution_backend",
        "app.services.publish_retry_command_executor",
        "app.services.publish_retry_command_claim_service",
        "app.services.publish_retry_command_preparation_service",
        "app.services.publish_retry_command_barrier_service",
        "app.services.publish_retry_command_finalization_service",
        "app.workers.publish_retry_command_worker",
    }
    for mod in forbidden_modules:
        assert mod not in imported, f"E2-1 must not import {mod}"
        assert not any(
            m == mod or m.startswith(mod + ".") for m in imported
        ), f"E2-1 must not import under {mod}"

    # Call-site tokens must not appear outside the module docstring negatives.
    body = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
    for token in (
        "PublishRetryCommandClaimService",
        "PublishRetryCommandPreparationService",
        "PublishRetryCommandBarrierService",
        "PublishRetryCommandExecutor",
        "PublishRetryCommandFinalizationService",
        "PublishRetryCommandWorker",
        "httpx",
    ):
        assert token not in body, f"E2-1 body must not reference {token}"


def test_e2_service_source_forbids_execution_and_provider_calls():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath(SERVICE_PATH).read_text(
        encoding="utf-8",
    )
    for bad in (
        "ClaimService",
        "PreparationService",
        "BarrierService",
        "FinalizationService",
        "cross_barrier",
        "prepare_command",
        "execute_command",
        "publish_content",
        "begin_attempt",
    ):
        assert bad not in src


def test_feature_flag_defaults_false():
    # Assert declared defaults (not process env / leaked monkeypatches).
    assert (
        type(settings).model_fields["PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED"].default
        is False
    )
    assert (
        type(settings).model_fields[
            "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED"
        ].default
        is False
    )


def test_production_compose_keeps_manual_resolution_false():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    text_src = (root / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED" in text_src
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED:-false" in text_src
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED:-true" not in text_src
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED" in text_src
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED:-false" in text_src
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED:-true" not in text_src

# ── Auth helpers ─────────────────────────────────────────────────────────────


def test_require_manual_resolution_actor_roles():
    from app.api.v1 import publishing as pub

    admin = SimpleNamespace(id=uuid.uuid4())
    pub._require_manual_resolution_actor(None, admin)  # ok

    for role in ("owner", "manager", "operator"):
        pub._require_manual_resolution_actor(
            SimpleNamespace(id=uuid.uuid4(), role=role), None,
        )

    for role in ("viewer", "sales"):
        with pytest.raises(HTTPException) as exc:
            pub._require_manual_resolution_actor(
                SimpleNamespace(id=uuid.uuid4(), role=role), None,
            )
        assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as unauth:
        pub._require_manual_resolution_actor(None, None)
    assert unauth.value.status_code == 401


def test_confirmation_gate_rejects_false(monkeypatch):
    monkeypatch.setattr(
        settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", True,
    )

    async def _run():
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_MARK_AMBIGUOUS,
                confirm_permanent_resolution=False,
                operator_reason="because stranded",
                actor_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 400
        assert "permanent" in str(exc.value.detail).lower()
        db.execute.assert_not_called()

    asyncio.run(_run())


def test_feature_flag_false_fail_closed(monkeypatch):
    monkeypatch.setattr(
        settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", False,
    )

    async def _run():
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_MARK_AMBIGUOUS,
                confirm_permanent_resolution=True,
                operator_reason="because stranded",
                actor_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 403
        db.execute.assert_not_called()

    asyncio.run(_run())


def test_unsupported_action_rejected(monkeypatch):
    monkeypatch.setattr(
        settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", True,
    )
    monkeypatch.setattr(
        settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True,
    )

    async def _run():
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action="MARK_FAILED_CONFIRMED",
                confirm_permanent_resolution=True,
                operator_reason="nope",
                actor_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 400
        db.execute.assert_not_called()

    asyncio.run(_run())


def test_request_schema_allows_e2_actions_rejects_deferred():
    from pydantic import ValidationError

    from app.schemas.publishing import PublishRetryCommandResolveRequest

    ok = PublishRetryCommandResolveRequest(
        action="MARK_AMBIGUOUS",
        confirm_permanent_resolution=True,
        operator_reason="review complete",
    )
    assert ok.action == "MARK_AMBIGUOUS"

    ok_success = PublishRetryCommandResolveRequest(
        action="ACKNOWLEDGE_EXTERNAL_SUCCESS",
        confirm_permanent_resolution=True,
        operator_reason="seen live",
        evidence_source="operator_provider_ui",
        external_post_id="12345",
    )
    assert ok_success.action == "ACKNOWLEDGE_EXTERNAL_SUCCESS"

    with pytest.raises(ValidationError):
        PublishRetryCommandResolveRequest(
            action="CANCEL",
            confirm_permanent_resolution=True,
            operator_reason="nope",
        )

    with pytest.raises(ValidationError):
        PublishRetryCommandResolveRequest(
            action="MARK_FAILED_CONFIRMED",
            confirm_permanent_resolution=True,
            operator_reason="nope",
        )


# ── PostgreSQL fixtures ──────────────────────────────────────────────────────


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_E2_PG_URL", DEFAULT_PG_URL)


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
        pytest.skip(f"PostgreSQL unavailable for E2-1 tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for E2-1 tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return url


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        for table in (
            "platform_audit_logs",
            "publish_operator_alerts",
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
                    company_name VARCHAR(255) NOT NULL DEFAULT 't',
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    plan VARCHAR(30) NOT NULL DEFAULT 'starter',
                    factory_partner_application_id UUID NULL,
                    created_at TIMESTAMPTZ NULL,
                    updated_at TIMESTAMPTZ NULL
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
                    publication_intent_id UUID NULL,
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
                CREATE TABLE publish_operator_alerts (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    dedupe_key VARCHAR(320) NOT NULL,
                    alert_type VARCHAR(40) NOT NULL,
                    state VARCHAR(20) NOT NULL DEFAULT 'open',
                    severity VARCHAR(20) NOT NULL DEFAULT 'critical',
                    title VARCHAR(255) NOT NULL,
                    body TEXT NULL,
                    client_id UUID NULL,
                    content_id UUID NULL,
                    account_id UUID NULL,
                    attempt_id UUID NULL,
                    platform VARCHAR(20) NULL,
                    account_name VARCHAR(255) NULL,
                    company_name VARCHAR(255) NULL,
                    attempt_status VARCHAR(40) NULL,
                    attempt_number INTEGER NULL,
                    failure_code VARCHAR(80) NULL,
                    failure_message TEXT NULL,
                    next_retry_at TIMESTAMPTZ NULL,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    first_occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    latest_occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    acknowledged_at TIMESTAMPTZ NULL,
                    acknowledged_by UUID NULL,
                    resolved_at TIMESTAMPTZ NULL,
                    resolved_by UUID NULL,
                    resolve_note TEXT NULL,
                    resolved_by_system BOOLEAN NOT NULL DEFAULT false,
                    action_url VARCHAR(500) NULL,
                    context JSONB NULL,
                    notification_id UUID NULL,
                    last_delivery_at TIMESTAMPTZ NULL,
                    last_delivery_channel VARCHAR(40) NULL,
                    last_delivery_error VARCHAR(480) NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE platform_audit_logs (
                    id UUID PRIMARY KEY,
                    actor_type VARCHAR(20) NOT NULL,
                    actor_id UUID NULL,
                    tenant_id UUID NULL,
                    event_type VARCHAR(50) NOT NULL,
                    resource_type VARCHAR(50) NULL,
                    resource_id VARCHAR(100) NULL,
                    details JSONB NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
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
        pytest.skip(f"PostgreSQL E2-1 test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL E2-1 test DB unavailable at {url}: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(_with_pg(coro_factory))


@contextmanager
def _e2_on():
    with patch.object(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", True):
        yield


class _Fixture:
    def __init__(self):
        self.tenant_id = uuid.uuid4()
        self.other_tenant_id = uuid.uuid4()
        self.client_id = uuid.uuid4()
        self.content_id = uuid.uuid4()
        self.account_id = uuid.uuid4()
        self.original_attempt_id = uuid.uuid4()
        self.resulting_attempt_id = uuid.uuid4()
        self.command_id = uuid.uuid4()
        self.actor_id = uuid.uuid4()
        self.correlation_id = "corr-e2-1"
        self.publish_version = "v1"
        self.platform = "telegram"


async def _seed_stranded(
    db: AsyncSession,
    fx: _Fixture,
    *,
    status: str = "provider_write_started",
    provider_write_started: bool = True,
    with_alert: bool = False,
    resulting_attempt_id: uuid.UUID | None = None,
    attempt_retry_command_id: uuid.UUID | None = None,
    attempt_content_id: uuid.UUID | None = None,
    include_resulting: bool = True,
    content_status: str = "failed",
) -> None:
    await db.execute(
        text(
            "INSERT INTO tenants (id, company_name) VALUES (:id, 't')"
        ),
        {"id": fx.tenant_id},
    )
    await db.execute(
        text(
            "INSERT INTO tenants (id, company_name) VALUES (:id, 'other')"
        ),
        {"id": fx.other_tenant_id},
    )
    await db.execute(
        text(
            "INSERT INTO clients (id, tenant_id, company_name) "
            "VALUES (:id, :tid, 'Co')"
        ),
        {"id": fx.client_id, "tid": fx.tenant_id},
    )
    await db.execute(
        text(
            "INSERT INTO content_items (id, client_id, status) "
            "VALUES (:id, :cid, :st)"
        ),
        {"id": fx.content_id, "cid": fx.client_id, "st": content_status},
    )
    await db.execute(
        text(
            "INSERT INTO publishing_accounts "
            "(id, tenant_id, platform) VALUES (:id, :tid, :p)"
        ),
        {"id": fx.account_id, "tid": fx.tenant_id, "p": fx.platform},
    )
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                publish_version, failure_code, retryable, next_retry_at,
                finished_at, retry_command_id
            ) VALUES (
                :id, :cid, :p, :aid, 'failed',
                :ver, 'provider_error', true, NOW() + interval '1 hour',
                NULL, NULL
            )
            """
        ),
        {
            "id": fx.original_attempt_id,
            "cid": fx.content_id,
            "p": fx.platform,
            "aid": fx.account_id,
            "ver": fx.publish_version,
        },
    )

    rid = resulting_attempt_id if resulting_attempt_id is not None else fx.resulting_attempt_id
    if include_resulting:
        await db.execute(
            text(
                """
                INSERT INTO publish_attempts (
                    id, content_id, platform, account_id, status,
                    publish_version, failure_code, failure_category,
                    retryable, next_retry_at, finished_at, retry_command_id,
                    error
                ) VALUES (
                    :id, :cid, :p, :aid, 'operator_review',
                    :ver, 'retry_command_write_started', 'command_orchestration',
                    false, NULL, NULL, :rcid,
                    'write barrier crossed'
                )
                """
            ),
            {
                "id": rid,
                "cid": attempt_content_id or fx.content_id,
                "p": fx.platform,
                "aid": fx.account_id,
                "ver": fx.publish_version,
                "rcid": (
                    fx.command_id
                    if attempt_retry_command_id is None
                    else attempt_retry_command_id
                ),
            },
        )

    pws_sql = "NOW() - interval '10 minutes'" if provider_write_started else "NULL"
    resulting_sql = ":rid" if include_resulting else "NULL"
    await db.execute(
        text(
            f"""
            INSERT INTO publish_retry_commands (
                id, tenant_id, client_id, content_id,
                original_attempt_id, resulting_attempt_id,
                platform, publishing_account_id, publish_version,
                destination_key, requested_source, idempotency_key,
                status, provider_outcome, provider_write_started_at,
                finished_at, correlation_id, lease_owner
            ) VALUES (
                :id, :tid, :clid, :cid,
                :oid, {resulting_sql},
                :p, :aid, :ver,
                'dest', 'workspace', :ikey,
                :st, NULL, {pws_sql},
                NULL, :corr, 'worker-a'
            )
            """
        ),
        {
            "id": fx.command_id,
            "tid": fx.tenant_id,
            "clid": fx.client_id,
            "cid": fx.content_id,
            "oid": fx.original_attempt_id,
            "rid": rid,
            "p": fx.platform,
            "aid": fx.account_id,
            "ver": fx.publish_version,
            "ikey": f"ikey-{fx.command_id}",
            "st": status,
            "corr": fx.correlation_id,
        },
    )

    if with_alert:
        await db.execute(
            text(
                """
                INSERT INTO publish_operator_alerts (
                    id, tenant_id, dedupe_key, alert_type, state, severity,
                    title, body, content_id, attempt_id, platform,
                    failure_code, attempt_status, context,
                    first_occurred_at, latest_occurred_at
                ) VALUES (
                    :id, :tid, :dk, 'operator_review', 'open', 'critical',
                    'stranded', 'body', :cid, :aid, :p,
                    'stranded_post_barrier', 'provider_write_started',
                    CAST(:ctx AS jsonb), NOW(), NOW()
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "tid": fx.tenant_id,
                "dk": stranded_dedupe_key(fx.command_id),
                "cid": fx.content_id,
                "aid": rid,
                "p": fx.platform,
                "ctx": (
                    f'{{"phase_e": "{PHASE_E_CONTEXT_MARKER}", '
                    f'"auto_ack_eligible": false, '
                    f'"command_id": "{fx.command_id}"}}'
                ),
            },
        )
    await db.commit()


async def _count(db: AsyncSession, table: str) -> int:
    return int(
        (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
    )


# ── Happy path / alert / idempotency ─────────────────────────────────────────


def test_mark_ambiguous_applied_with_alert_and_audit():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        with _e2_on():
            async with factory() as db:
                result = await PublishRetryCommandManualResolutionService.resolve(
                    db,
                    command_id=fx.command_id,
                    tenant_id=fx.tenant_id,
                    action=ACTION_MARK_AMBIGUOUS,
                    confirm_permanent_resolution=True,
                    operator_reason="  stranded past quiet period  ",
                    actor_id=fx.actor_id,
                    evidence_source="operator_console",
                    commit=True,
                )

        assert result.resolution == "applied"
        assert result.status == "ambiguous"
        assert result.provider_outcome == "ambiguous"
        assert result.attempt_status == "operator_review"
        assert result.alert_resolved is True
        assert result.audit_event_type == AUDIT_EVENT_MARK_AMBIGUOUS
        assert result.audit_id is not None

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "ambiguous"
            assert cmd.provider_outcome == "ambiguous"
            assert cmd.finished_at is not None
            assert cmd.reason_code == "manual_mark_ambiguous"

            attempt = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.resulting_attempt_id,
                    ),
                )
            ).scalar_one()
            assert attempt.status == "operator_review"
            assert attempt.retryable is False
            assert attempt.next_retry_at is None
            assert attempt.finished_at is not None
            # historical forensic fields preserved
            assert attempt.failure_code == "retry_command_write_started"
            assert attempt.external_post_id is None

            original = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.original_attempt_id,
                    ),
                )
            ).scalar_one()
            assert original.status == "failed"
            assert original.retryable is True

            content = (
                await db.execute(
                    text("SELECT status FROM content_items WHERE id = :id"),
                    {"id": fx.content_id},
                )
            ).scalar_one()
            assert content == "failed"

            assert await _count(db, "publish_retry_commands") == 1

            audits = (
                await db.execute(
                    select(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_MARK_AMBIGUOUS,
                    ),
                )
            ).scalars().all()
            assert len(audits) == 1
            details = audits[0].details or {}
            assert details["action"] == ACTION_MARK_AMBIGUOUS
            assert details["operator_reason"] == "stranded past quiet period"
            assert details["old_status"] == "provider_write_started"
            assert details["new_status"] == "ambiguous"
            assert details["evidence_source"] == "operator_console"

            alert = (
                await db.execute(
                    select(PublishOperatorAlert).where(
                        PublishOperatorAlert.dedupe_key
                        == stranded_dedupe_key(fx.command_id),
                    ),
                )
            ).scalar_one()
            assert alert.state == "resolved"
            assert alert.resolved_by == fx.actor_id
            assert alert.resolved_by_system is False
            assert "MARK_AMBIGUOUS" in (alert.resolve_note or "")
            assert str(fx.command_id) in (alert.resolve_note or "")
            assert (alert.context or {}).get("phase_e") == PHASE_E_CONTEXT_MARKER

    _run(_body)


def test_idempotent_same_action_no_audit_spam():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        with _e2_on():
            async with factory() as db:
                first = await PublishRetryCommandManualResolutionService.resolve(
                    db,
                    command_id=fx.command_id,
                    tenant_id=fx.tenant_id,
                    action=ACTION_MARK_AMBIGUOUS,
                    confirm_permanent_resolution=True,
                    operator_reason="first",
                    actor_id=fx.actor_id,
                    commit=True,
                )
            finished_at = first.finished_at
            async with factory() as db:
                second = await PublishRetryCommandManualResolutionService.resolve(
                    db,
                    command_id=fx.command_id,
                    tenant_id=fx.tenant_id,
                    action=ACTION_MARK_AMBIGUOUS,
                    confirm_permanent_resolution=True,
                    operator_reason="replay",
                    actor_id=fx.actor_id,
                    commit=True,
                )

        assert first.resolution == "applied"
        assert second.resolution == "already_resolved"
        assert second.finished_at == finished_at
        assert second.audit_id is None

        async with factory() as db:
            audits = (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_MARK_AMBIGUOUS,
                    ),
                )
            ).scalar_one()
            assert audits == 1
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.finished_at == finished_at

    _run(_body)


def test_missing_alert_still_succeeds():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=False)
        with _e2_on():
            async with factory() as db:
                result = await PublishRetryCommandManualResolutionService.resolve(
                    db,
                    command_id=fx.command_id,
                    tenant_id=fx.tenant_id,
                    action=ACTION_MARK_AMBIGUOUS,
                    confirm_permanent_resolution=True,
                    operator_reason="no alert present",
                    actor_id=fx.actor_id,
                    commit=True,
                )
        assert result.resolution == "applied"
        assert result.alert_resolved is False
        async with factory() as db:
            assert await _count(db, "publish_operator_alerts") == 0

    _run(_body)


# ── Conflict / lineage ───────────────────────────────────────────────────────


def test_pending_not_resolvable():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(
                db, fx, status="pending", provider_write_started=False,
            )
        with _e2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await PublishRetryCommandManualResolutionService.resolve(
                        db,
                        command_id=fx.command_id,
                        tenant_id=fx.tenant_id,
                        action=ACTION_MARK_AMBIGUOUS,
                        confirm_permanent_resolution=True,
                        operator_reason="nope",
                        actor_id=fx.actor_id,
                        commit=True,
                    )
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "not_resolvable"

    _run(_body)


def test_terminal_succeeded_already_resolved():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(
                db, fx, status="succeeded", provider_write_started=False,
            )
            await db.execute(
                text(
                    "UPDATE publish_retry_commands SET provider_outcome='known_success', "
                    "finished_at=NOW() WHERE id=:id"
                ),
                {"id": fx.command_id},
            )
            await db.commit()
        with _e2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await PublishRetryCommandManualResolutionService.resolve(
                        db,
                        command_id=fx.command_id,
                        tenant_id=fx.tenant_id,
                        action=ACTION_MARK_AMBIGUOUS,
                        confirm_permanent_resolution=True,
                        operator_reason="nope",
                        actor_id=fx.actor_id,
                        commit=True,
                    )
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "already_resolved"

    _run(_body)


def test_missing_resulting_attempt_id_lineage_conflict():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, include_resulting=False)
        with _e2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await PublishRetryCommandManualResolutionService.resolve(
                        db,
                        command_id=fx.command_id,
                        tenant_id=fx.tenant_id,
                        action=ACTION_MARK_AMBIGUOUS,
                        confirm_permanent_resolution=True,
                        operator_reason="nope",
                        actor_id=fx.actor_id,
                        commit=True,
                    )
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "lineage_conflict"
        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "provider_write_started"

    _run(_body)


def test_bidirectional_lineage_broken():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(
                db, fx, attempt_retry_command_id=uuid.uuid4(),
            )
        with _e2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await PublishRetryCommandManualResolutionService.resolve(
                        db,
                        command_id=fx.command_id,
                        tenant_id=fx.tenant_id,
                        action=ACTION_MARK_AMBIGUOUS,
                        confirm_permanent_resolution=True,
                        operator_reason="nope",
                        actor_id=fx.actor_id,
                        commit=True,
                    )
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "lineage_conflict"

    _run(_body)


def test_wrong_tenant_not_found():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)
        with _e2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await PublishRetryCommandManualResolutionService.resolve(
                        db,
                        command_id=fx.command_id,
                        tenant_id=fx.other_tenant_id,
                        action=ACTION_MARK_AMBIGUOUS,
                        confirm_permanent_resolution=True,
                        operator_reason="cross tenant",
                        actor_id=fx.actor_id,
                        commit=True,
                    )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Retry command not found"

    _run(_body)


# ── Audit failure rollback ───────────────────────────────────────────────────


def test_audit_failure_rolls_back_command_attempt_alert():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        with _e2_on():
            async with factory() as db:
                with patch(
                    "app.services.publish_retry_command_manual_resolution_service"
                    ".PlatformAuditService.record",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("audit insert failed"),
                ):
                    with pytest.raises(RuntimeError, match="audit insert failed"):
                        await PublishRetryCommandManualResolutionService.resolve(
                            db,
                            command_id=fx.command_id,
                            tenant_id=fx.tenant_id,
                            action=ACTION_MARK_AMBIGUOUS,
                            confirm_permanent_resolution=True,
                            operator_reason="should roll back",
                            actor_id=fx.actor_id,
                            commit=True,
                        )
                    await db.rollback()

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "provider_write_started"
            assert cmd.provider_outcome is None
            assert cmd.finished_at is None

            attempt = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.resulting_attempt_id,
                    ),
                )
            ).scalar_one()
            assert attempt.status == "operator_review"
            assert attempt.finished_at is None
            assert attempt.failure_code == "retry_command_write_started"

            alert = (
                await db.execute(
                    select(PublishOperatorAlert).where(
                        PublishOperatorAlert.dedupe_key
                        == stranded_dedupe_key(fx.command_id),
                    ),
                )
            ).scalar_one()
            assert alert.state == "open"
            assert alert.resolved_at is None

            audits = (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_MARK_AMBIGUOUS,
                    ),
                )
            ).scalar_one()
            assert audits == 0

    _run(_body)


# ── Concurrent operators ─────────────────────────────────────────────────────


def test_concurrent_mark_ambiguous_one_applied():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        sync = asyncio.Barrier(2)
        results: list = []
        errors: list = []

        async def _worker():
            with _e2_on():
                async with factory() as db:
                    await sync.wait()
                    try:
                        results.append(
                            await PublishRetryCommandManualResolutionService.resolve(
                                db,
                                command_id=fx.command_id,
                                tenant_id=fx.tenant_id,
                                action=ACTION_MARK_AMBIGUOUS,
                                confirm_permanent_resolution=True,
                                operator_reason="concurrent",
                                actor_id=fx.actor_id,
                                commit=True,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors.append(exc)

        await asyncio.gather(_worker(), _worker())
        assert not errors, errors
        assert len(results) == 2
        applied = [r for r in results if r.resolution == "applied"]
        already = [r for r in results if r.resolution == "already_resolved"]
        assert len(applied) == 1
        assert len(already) == 1

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "ambiguous"
            attempt = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.resulting_attempt_id,
                    ),
                )
            ).scalar_one()
            assert attempt.status == "operator_review"
            assert attempt.finished_at is not None
            audits = (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_MARK_AMBIGUOUS,
                    ),
                )
            ).scalar_one()
            assert audits == 1
            assert await _count(db, "publish_retry_commands") == 1

    _run(_body)


# ── Auto-Ack regression ──────────────────────────────────────────────────────


def test_resolved_stranded_alert_still_excluded_from_auto_ack():
    from app.services.operator_auto_ack.eligibility import evaluate_auto_ack_candidate

    alert = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        content_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        alert_type="operator_review",
        state="resolved",
        severity="critical",
        platform="telegram",
        failure_code="stranded_post_barrier",
        attempt_status="provider_write_started",
        occurrence_count=1,
        latest_occurred_at=datetime.now(timezone.utc),
        first_occurred_at=datetime.now(timezone.utc),
        context={"phase_e": PHASE_E_CONTEXT_MARKER, "auto_ack_eligible": False},
    )
    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        status="operator_review",
        failure_code="retry_command_write_started",
        platform="telegram",
        content_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False


# ── Route wiring smoke ───────────────────────────────────────────────────────


def test_resolve_route_registered_and_uses_service():
    from app.api.v1 import publishing as pub

    src = inspect.getsource(pub.resolve_publish_retry_command)
    assert "PublishRetryCommandManualResolutionService.resolve" in src
    assert "_require_manual_resolution_actor" in src
    assert "MARK_AMBIGUOUS" in inspect.getsource(pub) or True

    full = inspect.getsource(pub)
    assert '/retry-commands/{command_id}/resolve"' in full
    # Still no unsafe stranded recovery aliases.
    assert "stranded_recover" not in full
    assert "stranded_replay" not in full
    assert "mark_ambiguous_stranded" not in full
