"""Phase E2-2 ACKNOWLEDGE_EXTERNAL_SUCCESS tests (local/dormant)."""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.platform_ops import PlatformAuditLog
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.models.publish_retry_command import PublishRetryCommand
from app.services.publish_resilience import PublishResilienceService
from app.services.publish_retry_command_manual_resolution_service import (
    ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
    ACTION_MARK_AMBIGUOUS,
    AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
    AUDIT_EVENT_MARK_AMBIGUOUS,
    REASON_CODE_ACK_EXTERNAL_SUCCESS,
    REASON_CODE_PROVIDER_SUCCESS,
    PublishRetryCommandManualResolutionService,
)
from app.services.publish_retry_command_stranded_detector import (
    PHASE_E_CONTEXT_MARKER,
    stranded_dedupe_key,
)

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/"
    "retry_command_manual_resolution_e2_2_test"
)
SERVICE_PATH = "app/services/publish_retry_command_manual_resolution_service.py"


def test_audit_event_fits_column():
    assert len(AUDIT_EVENT_ACK_EXTERNAL_SUCCESS) <= 50
    assert AUDIT_EVENT_ACK_EXTERNAL_SUCCESS == "publishing.retry_cmd_recon_success"


def test_e2_2_service_has_zero_provider_io_or_registry_imports():
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
        "urllib.request",
        "requests",
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
        "app.services.measurement.publication_registry",
    }
    for mod in forbidden_modules:
        assert mod not in imported, f"E2-2 must not import {mod}"
        assert not any(
            m == mod or m.startswith(mod + ".") for m in imported
        ), f"E2-2 must not import under {mod}"

    body = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
    for token in (
        "PublishRetryCommandClaimService",
        "PublishRetryCommandPreparationService",
        "PublishRetryCommandBarrierService",
        "PublishRetryCommandExecutor",
        "PublishRetryCommandFinalizationService",
        "PublishRetryCommandWorker",
        "register_publication",
        "upsert_publication",
        "httpx",
        "urlopen",
    ):
        assert token not in body, f"E2-2 body must not reference {token}"


def test_e2_2_feature_flag_defaults_false_and_compose_pin():
    assert (
        type(settings).model_fields[
            "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED"
        ].default
        is False
    )
    assert (
        type(settings).model_fields[
            "PUBLISH_WRITE_COORDINATION_ENABLED"
        ].default
        is False
    )
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    text_src = (root / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED:-false" in text_src
    assert "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED:-true" not in text_src
    assert "PUBLISH_WRITE_COORDINATION_ENABLED:-false" in text_src
    assert "PUBLISH_WRITE_COORDINATION_ENABLED:-true" not in text_src


def test_e2_2_flag_off_rejects_success_even_when_e2_1_on(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", False)

    async def _run():
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
                confirm_permanent_resolution=True,
                operator_reason="seen",
                evidence_source="ui",
                external_post_id="1",
                actor_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 403
        assert "E2_2" in str(exc.value.detail)
        db.execute.assert_not_called()

    asyncio.run(_run())


def test_e2_2_on_but_coordination_off_rejects_success(monkeypatch):
    """E2-2 acknowledgment intentionally requires write coordination."""
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False)

    async def _run():
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
                confirm_permanent_resolution=True,
                operator_reason="seen",
                evidence_source="ui",
                external_post_id="1",
                actor_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 403
        assert "PUBLISH_WRITE_COORDINATION_ENABLED=false" in str(exc.value.detail)
        db.execute.assert_not_called()

    asyncio.run(_run())


def test_e2_1_flag_off_rejects_ambiguous_even_when_e2_2_on(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", True)

    async def _run():
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_MARK_AMBIGUOUS,
                confirm_permanent_resolution=True,
                operator_reason="ambiguous",
                actor_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 403
        assert "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED=false" in str(exc.value.detail)
        db.execute.assert_not_called()

    asyncio.run(_run())


def test_both_flags_off_reject_both_actions(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", False)
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", False)

    async def _run():
        db = AsyncMock()
        with pytest.raises(HTTPException) as e1:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_MARK_AMBIGUOUS,
                confirm_permanent_resolution=True,
                operator_reason="x",
                actor_id=uuid.uuid4(),
            )
        assert e1.value.status_code == 403
        with pytest.raises(HTTPException) as e2:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
                confirm_permanent_resolution=True,
                operator_reason="x",
                evidence_source="ui",
                external_post_id="1",
                actor_id=uuid.uuid4(),
            )
        assert e2.value.status_code == 403

    asyncio.run(_run())


def test_success_evidence_validation_matrix(monkeypatch):
    monkeypatch.setattr(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", True)

    async def _expect_400(**kwargs):
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandManualResolutionService.resolve(
                db,
                command_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
                actor_id=uuid.uuid4(),
                **kwargs,
            )
        assert exc.value.status_code == 400
        db.execute.assert_not_called()

    async def _run():
        await _expect_400(
            confirm_permanent_resolution=False,
            operator_reason="ok",
            evidence_source="ui",
            external_post_id="1",
        )
        await _expect_400(
            confirm_permanent_resolution=True,
            operator_reason="   ",
            evidence_source="ui",
            external_post_id="1",
        )
        await _expect_400(
            confirm_permanent_resolution=True,
            operator_reason="ok",
            evidence_source=None,
            external_post_id="1",
        )
        await _expect_400(
            confirm_permanent_resolution=True,
            operator_reason="ok",
            evidence_source="ui",
            external_post_id=None,
        )
        await _expect_400(
            confirm_permanent_resolution=True,
            operator_reason="ok",
            evidence_source="ui",
            external_post_id="1",
            external_post_url="ftp://bad.example/x",
        )
        await _expect_400(
            confirm_permanent_resolution=True,
            operator_reason="ok",
            evidence_source="ui",
            external_post_id="x" * 256,
        )

    asyncio.run(_run())


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_E2_2_PG_URL", DEFAULT_PG_URL)


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
        pytest.skip(f"PostgreSQL unavailable for E2-2 tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for E2-2 tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return url

async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        for table in (
            "platform_audit_logs",
            "publish_operator_alerts",
            "tenant_external_publications",
            "publish_retry_commands",
            "publish_attempts",
            "publishing_accounts",
            "content_items",
            "clients",
            "tenants",
        ):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))

        await conn.execute(text("""
            CREATE TABLE tenants (
                id UUID PRIMARY KEY,
                company_name VARCHAR(255) NOT NULL DEFAULT 't',
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                plan VARCHAR(30) NOT NULL DEFAULT 'starter',
                factory_partner_application_id UUID NULL,
                created_at TIMESTAMPTZ NULL,
                updated_at TIMESTAMPTZ NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE clients (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                company_name VARCHAR(255) NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE content_items (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'failed',
                caption_long_ru TEXT NULL,
                updated_at TIMESTAMPTZ NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE publishing_accounts (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                platform VARCHAR(20) NOT NULL,
                account_name VARCHAR(255) NOT NULL DEFAULT 'Bot',
                account_id VARCHAR(255) NOT NULL DEFAULT 'acct',
                status VARCHAR(30) NOT NULL DEFAULT 'connected',
                access_token_encrypted TEXT NULL,
                refresh_token_encrypted TEXT NULL,
                facebook_page_id VARCHAR(64) NULL,
                instagram_business_account_id VARCHAR(64) NULL,
                permissions_json TEXT NULL,
                account_metadata_json TEXT NULL,
                expires_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
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
        """))
        await conn.execute(text("""
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
        """))
        await conn.execute(text("""
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
        """))
        await conn.execute(text("""
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
        """))
        await conn.execute(text("""
            CREATE TABLE tenant_external_publications (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                provider_publication_id VARCHAR(255) NOT NULL
            )
        """))


async def _with_pg(coro_factory):
    url = await _ensure_database()
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_schema(engine)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await coro_factory(factory)
    except OSError as exc:
        pytest.skip(f"PostgreSQL E2-2 test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL E2-2 test DB unavailable at {url}: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(_with_pg(coro_factory))


@contextmanager
def _e2_2_on():
    """E2-2 apply requires E2_2 + write-coordination flags."""
    with (
        patch.object(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True),
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", True),
    ):
        yield


@contextmanager
def _both_on():
    with (
        patch.object(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", True),
        patch.object(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True),
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", True),
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
        self.resulting_attempt_id = uuid.uuid4()
        self.command_id = uuid.uuid4()
        self.actor_id = uuid.uuid4()
        self.correlation_id = "corr-e2-2"
        self.publish_version = "v1"
        self.platform = "telegram"
        self.idempotency_key = f"ikey-{uuid.uuid4()}"


_SUCCESS_KW = dict(
    action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
    confirm_permanent_resolution=True,
    operator_reason="Verified live Telegram message in channel UI",
    evidence_source="operator_provider_ui",
    external_post_id="12345",
    external_post_url="https://t.me/c/111/12345",
)


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
    attempt_external_post_id: str | None = None,
    attempt_status: str = "operator_review",
    attempt_failure_code: str | None = "retry_command_write_started",
    attempt_retryable: bool = False,
    attempt_finished: bool = False,
    claim_lease: bool = True,
) -> None:
    await db.execute(
        text("INSERT INTO tenants (id, company_name) VALUES (:id, 't')"),
        {"id": fx.tenant_id},
    )
    await db.execute(
        text("INSERT INTO tenants (id, company_name) VALUES (:id, 'other')"),
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
                finished_at, retry_command_id, response
            ) VALUES (
                :id, :cid, :p, :aid, 'failed',
                :ver, 'provider_error', true, NOW() + interval '1 hour',
                NULL, NULL, NULL
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
        finished_sql = "NOW()" if attempt_finished else "NULL"
        next_retry_sql = "NULL" if not attempt_retryable else "NOW() + interval '1 hour'"
        await db.execute(
            text(
                f"""
                INSERT INTO publish_attempts (
                    id, content_id, platform, account_id, status,
                    publish_version, failure_code, failure_category,
                    retryable, next_retry_at, finished_at, retry_command_id,
                    error, external_post_id, response, idempotency_key,
                    lease_owner
                ) VALUES (
                    :id, :cid, :p, :aid, :st,
                    :ver, :fc, 'command_orchestration',
                    :retr, {next_retry_sql}, {finished_sql}, :rcid,
                    'write barrier crossed', :epid, NULL, :ikey,
                    'worker-a'
                )
                """
            ),
            {
                "id": rid,
                "cid": attempt_content_id or fx.content_id,
                "p": fx.platform,
                "aid": fx.account_id,
                "ver": fx.publish_version,
                "st": attempt_status,
                "fc": attempt_failure_code,
                "retr": attempt_retryable,
                "rcid": (
                    fx.command_id
                    if attempt_retry_command_id is None
                    else attempt_retry_command_id
                ),
                "epid": attempt_external_post_id,
                "ikey": fx.idempotency_key,
            },
        )

    pws_sql = "NOW() - interval '10 minutes'" if provider_write_started else "NULL"
    resulting_sql = ":rid" if include_resulting else "NULL"
    lease_sql = "'worker-a'" if claim_lease else "NULL"
    claimed_sql = "NOW() - interval '15 minutes'" if claim_lease else "NULL"
    await db.execute(
        text(
            f"""
            INSERT INTO publish_retry_commands (
                id, tenant_id, client_id, content_id,
                original_attempt_id, resulting_attempt_id,
                platform, publishing_account_id, publish_version,
                destination_key, requested_source, idempotency_key,
                status, provider_outcome, provider_write_started_at,
                finished_at, correlation_id, lease_owner, claimed_at
            ) VALUES (
                :id, :tid, :clid, :cid,
                :oid, {resulting_sql},
                :p, :aid, :ver,
                'dest', 'workspace', :ikey,
                :st, NULL, {pws_sql},
                NULL, :corr, {lease_sql}, {claimed_sql}
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
            "ikey": fx.idempotency_key,
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


async def _ack(db, fx: _Fixture, **overrides):
    kwargs = {
        "command_id": fx.command_id,
        "tenant_id": fx.tenant_id,
        "actor_id": fx.actor_id,
        "commit": True,
        **_SUCCESS_KW,
        **overrides,
    }
    return await PublishRetryCommandManualResolutionService.resolve(db, **kwargs)


def test_ack_external_success_applied_exact_fields():
    fx = _Fixture()
    observed = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        with _e2_2_on():
            async with factory() as db:
                result = await _ack(db, fx, observed_at=observed)

        assert result.resolution == "applied"
        assert result.status == "succeeded"
        assert result.provider_outcome == "known_success"
        assert result.attempt_status == "success"
        assert result.external_post_id == "12345"
        assert result.alert_resolved is True
        assert result.audit_event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS
        assert result.audit_id is not None

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "succeeded"
            assert cmd.provider_outcome == "known_success"
            assert cmd.reason_code == REASON_CODE_ACK_EXTERNAL_SUCCESS
            assert cmd.finished_at is not None
            assert cmd.lease_owner == "worker-a"
            assert cmd.claimed_at is not None
            assert cmd.provider_write_started_at is not None

            attempt = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.resulting_attempt_id,
                    ),
                )
            ).scalar_one()
            assert attempt.status == "success"
            assert attempt.external_post_id == "12345"
            assert attempt.external_post_url == "https://t.me/c/111/12345"
            assert attempt.failure_code is None
            assert attempt.failure_category is None
            assert attempt.error is None
            assert attempt.retryable is False
            assert attempt.next_retry_at is None
            assert attempt.finished_at is not None
            assert attempt.response is None

            original = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.original_attempt_id,
                    ),
                )
            ).scalar_one()
            assert original.status == "failed"
            assert original.retryable is True
            assert original.external_post_id is None

            content = (
                await db.execute(
                    text("SELECT status FROM content_items WHERE id = :id"),
                    {"id": fx.content_id},
                )
            ).scalar_one()
            assert content == "failed"
            assert await _count(db, "tenant_external_publications") == 0
            assert await _count(db, "publish_retry_commands") == 1

            audits = (
                await db.execute(
                    select(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                    ),
                )
            ).scalars().all()
            assert len(audits) == 1
            details = audits[0].details or {}
            assert details["action"] == ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS
            assert details["operator_reason"] == _SUCCESS_KW["operator_reason"]
            assert details["evidence_source"] == "operator_provider_ui"
            assert details["external_post_id"] == "12345"
            assert details["provenance"] == "manual_resolution_e2_2"
            assert details["content_repair"] == "skipped_unsafe_aggregate"
            assert details["publication_repair"] == "deferred_minimal_e2_2"
            assert details["evidence_attestation"] == "operator_attested_unverified"
            assert details["old_status"] == "provider_write_started"
            assert details["new_status"] == "succeeded"
            assert details["new_reason_code"] == REASON_CODE_ACK_EXTERNAL_SUCCESS

            alert = (
                await db.execute(
                    select(PublishOperatorAlert).where(
                        PublishOperatorAlert.dedupe_key
                        == stranded_dedupe_key(fx.command_id),
                    ),
                )
            ).scalar_one()
            assert alert.state == "resolved"
            assert alert.resolved_by_system is False
            assert ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS in (alert.resolve_note or "")
            assert (alert.context or {}).get("phase_e") == PHASE_E_CONTEXT_MARKER

            live = await PublishResilienceService.find_live_success(
                db,
                content_id=fx.content_id,
                platform=fx.platform,
                account_id=fx.account_id,
            )
            assert live is not None
            assert live.id == fx.resulting_attempt_id
            assert live.external_post_id == "12345"

    _run(_body)


def test_compatible_replay_returns_prior_audit_no_mutation():
    fx = _Fixture()
    observed = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        with _e2_2_on():
            async with factory() as db:
                first = await _ack(db, fx, observed_at=observed)
            finished_at = first.finished_at
            async with factory() as db:
                second = await _ack(db, fx, observed_at=observed)

        assert first.resolution == "applied"
        assert second.resolution == "already_resolved"
        assert second.audit_id == first.audit_id
        assert second.audit_event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS
        assert second.alert_resolved is False
        assert second.finished_at == finished_at
        assert second.external_post_id == "12345"

        async with factory() as db:
            audits = (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
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


def test_replay_evidence_mismatches_conflict():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)

        with _e2_2_on():
            async with factory() as db:
                await _ack(db, fx)

            cases = [
                {"external_post_id": "99999"},
                {"operator_reason": "different reason"},
                {"evidence_source": "other_source"},
                {"external_post_url": "https://t.me/c/111/99999"},
                {
                    "observed_at": datetime(
                        2026, 9, 14, 1, 0, 0, tzinfo=timezone.utc,
                    ),
                },
            ]
            for override in cases:
                async with factory() as db:
                    with pytest.raises(HTTPException) as exc:
                        await _ack(db, fx, **override)
                    assert exc.value.status_code == 409
                    assert exc.value.detail["error"] == "evidence_conflict"

        async with factory() as db:
            assert (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                    ),
                )
            ).scalar_one() == 1

    _run(_body)


def test_executor_success_not_manual_replay():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)
            await db.execute(
                text(
                    """
                    UPDATE publish_retry_commands
                    SET status='succeeded',
                        provider_outcome='known_success',
                        reason_code=:rc,
                        finished_at=NOW()
                    WHERE id=:id
                    """
                ),
                {"id": fx.command_id, "rc": REASON_CODE_PROVIDER_SUCCESS},
            )
            await db.execute(
                text(
                    """
                    UPDATE publish_attempts
                    SET status='success',
                        external_post_id='12345',
                        failure_code=NULL,
                        finished_at=NOW()
                    WHERE id=:id
                    """
                ),
                {"id": fx.resulting_attempt_id},
            )
            await db.commit()

        with _e2_2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "already_resolved"

        async with factory() as db:
            audits = (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                    ),
                )
            ).scalar_one()
            assert audits == 0

    _run(_body)


def test_missing_manual_audit_with_manual_reason_code_fails_closed():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)
            await db.execute(
                text(
                    """
                    UPDATE publish_retry_commands
                    SET status='succeeded',
                        provider_outcome='known_success',
                        reason_code=:rc,
                        finished_at=NOW()
                    WHERE id=:id
                    """
                ),
                {"id": fx.command_id, "rc": REASON_CODE_ACK_EXTERNAL_SUCCESS},
            )
            await db.execute(
                text(
                    """
                    UPDATE publish_attempts
                    SET status='success',
                        external_post_id='12345',
                        failure_code=NULL,
                        finished_at=NOW()
                    WHERE id=:id
                    """
                ),
                {"id": fx.resulting_attempt_id},
            )
            await db.commit()

        with _e2_2_on():
            async with factory() as db:
                before_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "evidence_conflict"
                after_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                assert after_audits == before_audits
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "succeeded"
                assert cmd.reason_code == REASON_CODE_ACK_EXTERNAL_SUCCESS

    _run(_body)


def test_duplicate_manual_audit_provenance_fails_closed():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)

        with _e2_2_on():
            async with factory() as db:
                first = await _ack(db, fx)

            async with factory() as db:
                details = (
                    await db.execute(
                        select(PlatformAuditLog).where(
                            PlatformAuditLog.id == first.audit_id,
                        ),
                    )
                ).scalar_one().details
                await db.execute(
                    text(
                        """
                        INSERT INTO platform_audit_logs (
                            id, actor_type, actor_id, tenant_id, event_type,
                            resource_type, resource_id, details
                        ) VALUES (
                            :id, 'tenant_user', :aid, :tid, :et,
                            'publish_retry_command', :rid, CAST(:details AS jsonb)
                        )
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "aid": fx.actor_id,
                        "tid": fx.tenant_id,
                        "et": AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                        "rid": str(fx.command_id),
                        "details": json.dumps(details),
                    },
                )
                await db.commit()

            async with factory() as db:
                before_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                before_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "evidence_conflict"
                after_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                after_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert after_audits == before_audits
                assert after_updated == before_updated

    _run(_body)


def test_wrong_tenant_audit_not_used_for_replay():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)

        with _e2_2_on():
            async with factory() as db:
                first = await _ack(db, fx)

            async with factory() as db:
                await db.execute(
                    text(
                        "UPDATE platform_audit_logs SET tenant_id=:tid WHERE id=:id"
                    ),
                    {"tid": fx.other_tenant_id, "id": first.audit_id},
                )
                await db.commit()

            async with factory() as db:
                before_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                before_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "evidence_conflict"
                after_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                after_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert after_audits == before_audits
                assert after_updated == before_updated

    _run(_body)



def test_valid_plus_contradictory_audit_candidate_fails_closed():
    """One valid + one malformed/contradictory sibling must not authorize replay."""
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)

        with _e2_2_on():
            async with factory() as db:
                first = await _ack(db, fx)

            async with factory() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO platform_audit_logs (
                            id, actor_type, actor_id, tenant_id, event_type,
                            resource_type, resource_id, details
                        ) VALUES (
                            :id, 'tenant_user', :aid, :tid, :et,
                            'publish_retry_command', :rid, CAST(:details AS jsonb)
                        )
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "aid": fx.actor_id,
                        "tid": fx.tenant_id,
                        "et": AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                        "rid": str(fx.command_id),
                        "details": json.dumps(
                            {
                                "action": "NOT_THE_SUCCESS_ACTION",
                                "provenance": "tampered",
                                "tenant_id": str(fx.tenant_id),
                                "command_id": str(fx.command_id),
                                "note": "contradictory sibling must fail closed",
                            }
                        ),
                    },
                )
                await db.commit()

            async with factory() as db:
                before_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                before_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "evidence_conflict"
                after_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                after_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert after_audits == before_audits
                assert after_updated == before_updated
                assert first.audit_id is not None

    _run(_body)


def test_single_inconsistent_outcome_provenance_fails_closed():
    """Exactly one candidate with inconsistent outcome/provenance → conflict."""
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)

        with _e2_2_on():
            async with factory() as db:
                first = await _ack(db, fx)

            async with factory() as db:
                await db.execute(
                    text(
                        """
                        UPDATE platform_audit_logs
                        SET details = jsonb_set(
                            jsonb_set(details, '{provenance}', '"tampered_provenance"'),
                            '{new_status}', '"ambiguous"'
                        )
                        WHERE id = :id
                        """
                    ),
                    {"id": first.audit_id},
                )
                await db.commit()

            async with factory() as db:
                before_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                before_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "evidence_conflict"
                mismatched = exc.value.detail.get("mismatched_fields") or []
                assert "provenance" in mismatched or "new_status" in mismatched
                after_audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog),
                    )
                ).scalar_one()
                after_updated = (
                    await db.execute(
                        select(PublishRetryCommand.updated_at).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert after_audits == before_audits
                assert after_updated == before_updated

    _run(_body)


def test_pending_and_claimed_not_resolvable():
    for status in ("pending", "claimed"):
        fx = _Fixture()

        async def _body(factory, st=status):
            async with factory() as db:
                await _seed_stranded(
                    db, fx, status=st, provider_write_started=False,
                )
            with _e2_2_on():
                async with factory() as db:
                    with pytest.raises(HTTPException) as exc:
                        await _ack(db, fx)
                    assert exc.value.status_code == 409
                    assert exc.value.detail["error"] == "not_resolvable"

        _run(_body)


def test_ambiguous_already_resolved_for_success_action():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)
            await db.execute(
                text(
                    """
                    UPDATE publish_retry_commands
                    SET status='ambiguous',
                        provider_outcome='ambiguous',
                        reason_code='manual_mark_ambiguous',
                        finished_at=NOW()
                    WHERE id=:id
                    """
                ),
                {"id": fx.command_id},
            )
            await db.commit()
        with _e2_2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "already_resolved"

    _run(_body)


def test_lineage_and_lifecycle_conflicts():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, attempt_retry_command_id=uuid.uuid4())
        with _e2_2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "lineage_conflict"

    _run(_body)

    fx2 = _Fixture()

    async def _body2(factory):
        async with factory() as db:
            await _seed_stranded(
                db,
                fx2,
                attempt_status="success",
                attempt_failure_code=None,
                attempt_finished=True,
                attempt_external_post_id="already",
            )
        with _e2_2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx2)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "lineage_conflict"

    _run(_body2)

    fx3 = _Fixture()

    async def _body3(factory):
        async with factory() as db:
            await _seed_stranded(
                db, fx3, attempt_external_post_id="different-id",
            )
        with _e2_2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx3)
                assert exc.value.status_code == 409
                assert exc.value.detail["error"] == "evidence_conflict"

    _run(_body3)


def test_wrong_tenant_not_found():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)
        with _e2_2_on():
            async with factory() as db:
                with pytest.raises(HTTPException) as exc:
                    await _ack(db, fx, tenant_id=fx.other_tenant_id)
                assert exc.value.status_code == 404

    _run(_body)


def test_audit_failure_rolls_back_all_mutations():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        with _e2_2_on():
            async with factory() as db:
                with patch(
                    "app.services.publish_retry_command_manual_resolution_service"
                    ".PlatformAuditService.record",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("audit insert failed"),
                ):
                    with pytest.raises(RuntimeError, match="audit insert failed"):
                        await _ack(db, fx)
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
            assert cmd.reason_code is None

            attempt = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.resulting_attempt_id,
                    ),
                )
            ).scalar_one()
            assert attempt.status == "operator_review"
            assert attempt.external_post_id is None
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

            assert (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog),
                )
            ).scalar_one() == 0

    _run(_body)


def test_concurrent_identical_ack_one_applied():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)

        sync = asyncio.Barrier(2)
        results: list = []
        errors: list = []

        async def _worker():
            async with factory() as db:
                await sync.wait()
                try:
                    results.append(await _ack(db, fx))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        with _e2_2_on():
            await asyncio.gather(_worker(), _worker())
        assert not errors, errors
        applied = [r for r in results if r.resolution == "applied"]
        already = [r for r in results if r.resolution == "already_resolved"]
        assert len(applied) == 1
        assert len(already) == 1
        assert already[0].audit_id == applied[0].audit_id

        async with factory() as db:
            assert (
                await db.execute(
                    select(func.count()).select_from(PlatformAuditLog).where(
                        PlatformAuditLog.event_type == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                    ),
                )
            ).scalar_one() == 1

    _run(_body)


def test_concurrent_success_vs_ambiguous_one_winner():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)

        sync = asyncio.Barrier(2)
        results: list = []
        errors: list = []

        async def _success():
            async with factory() as db:
                await sync.wait()
                try:
                    results.append(("success", await _ack(db, fx)))
                except Exception as exc:  # noqa: BLE001
                    errors.append(("success", exc))

        async def _ambiguous():
            async with factory() as db:
                await sync.wait()
                try:
                    results.append(
                        (
                            "ambiguous",
                            await PublishRetryCommandManualResolutionService.resolve(
                                db,
                                command_id=fx.command_id,
                                tenant_id=fx.tenant_id,
                                action=ACTION_MARK_AMBIGUOUS,
                                confirm_permanent_resolution=True,
                                operator_reason="mark ambiguous",
                                actor_id=fx.actor_id,
                                commit=True,
                            ),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(("ambiguous", exc))

        with _both_on():
            await asyncio.gather(_success(), _ambiguous())
        assert len(results) == 1
        assert len(errors) == 1
        winner_action, winner = results[0]
        assert winner.resolution == "applied"
        loser_action, loser = errors[0]
        assert isinstance(loser, HTTPException)
        assert loser.status_code == 409
        assert loser.detail["error"] == "already_resolved"
        assert {winner_action, loser_action} == {"success", "ambiguous"}

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            if winner_action == "success":
                assert cmd.status == "succeeded"
            else:
                assert cmd.status == "ambiguous"

    _run(_body)


def test_operator_versus_finalizer_race():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx)

        sync = asyncio.Barrier(2)
        outcomes: list = []

        async def _operator():
            async with factory() as db:
                await sync.wait()
                try:
                    outcomes.append(("op", await _ack(db, fx)))
                except Exception as exc:  # noqa: BLE001
                    outcomes.append(("op_err", exc))

        async def _finalizer():
            async with factory() as db:
                await sync.wait()
                try:
                    cmd = (
                        await db.execute(
                            select(PublishRetryCommand)
                            .where(PublishRetryCommand.id == fx.command_id)
                            .with_for_update(),
                        )
                    ).scalar_one()
                    if cmd.status != "provider_write_started":
                        outcomes.append(("fin", "already_finalized"))
                        await db.rollback()
                        return
                    attempt = (
                        await db.execute(
                            select(PublishAttempt)
                            .where(PublishAttempt.id == fx.resulting_attempt_id)
                            .with_for_update(),
                        )
                    ).scalar_one()
                    attempt.status = "success"
                    attempt.external_post_id = "prov-999"
                    attempt.failure_code = None
                    attempt.failure_category = None
                    attempt.error = None
                    attempt.finished_at = func.now()
                    cmd.status = "succeeded"
                    cmd.provider_outcome = "known_success"
                    cmd.reason_code = REASON_CODE_PROVIDER_SUCCESS
                    cmd.finished_at = func.now()
                    await db.commit()
                    outcomes.append(("fin", "applied"))
                except Exception as exc:  # noqa: BLE001
                    outcomes.append(("fin_err", exc))

        with _e2_2_on():
            await asyncio.gather(_operator(), _finalizer())
        kinds = {k for k, _ in outcomes}
        assert "op" in kinds or "op_err" in kinds
        assert "fin" in kinds or "fin_err" in kinds

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "succeeded"
            assert cmd.reason_code in {
                REASON_CODE_ACK_EXTERNAL_SUCCESS,
                REASON_CODE_PROVIDER_SUCCESS,
            }
            attempt = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == fx.resulting_attempt_id,
                    ),
                )
            ).scalar_one()
            assert attempt.status == "success"
            assert attempt.external_post_id in {"12345", "prov-999"}

            if cmd.reason_code == REASON_CODE_ACK_EXTERNAL_SUCCESS:
                assert any(k == "op" for k, _ in outcomes)
                audits = (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog).where(
                            PlatformAuditLog.event_type
                            == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                        ),
                    )
                ).scalar_one()
                assert audits == 1
            else:
                op_errs = [v for k, v in outcomes if k == "op_err"]
                assert op_errs
                assert isinstance(op_errs[0], HTTPException)
                assert op_errs[0].detail["error"] == "already_resolved"
                assert (
                    await db.execute(
                        select(func.count()).select_from(PlatformAuditLog).where(
                            PlatformAuditLog.event_type
                            == AUDIT_EVENT_ACK_EXTERNAL_SUCCESS,
                        ),
                    )
                ).scalar_one() == 0

    _run(_body)


def test_e2_1_mark_ambiguous_still_works_with_both_flags_on():
    fx = _Fixture()

    async def _body(factory):
        async with factory() as db:
            await _seed_stranded(db, fx, with_alert=True)
        with _both_on():
            async with factory() as db:
                result = await PublishRetryCommandManualResolutionService.resolve(
                    db,
                    command_id=fx.command_id,
                    tenant_id=fx.tenant_id,
                    action=ACTION_MARK_AMBIGUOUS,
                    confirm_permanent_resolution=True,
                    operator_reason="still ambiguous",
                    actor_id=fx.actor_id,
                    commit=True,
                )
        assert result.resolution == "applied"
        assert result.status == "ambiguous"
        assert result.audit_event_type == AUDIT_EVENT_MARK_AMBIGUOUS

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "ambiguous"
            assert cmd.reason_code == "manual_mark_ambiguous"

    _run(_body)


def test_role_gate_unchanged():
    from app.api.v1 import publishing as pub

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


def test_resolve_route_passes_e2_2_fields():
    from app.api.v1 import publishing as pub

    src = inspect.getsource(pub.resolve_publish_retry_command)
    assert "external_post_id=body.external_post_id" in src
    assert "external_post_url=body.external_post_url" in src
    assert "observed_at=body.observed_at" in src
    assert "PublishRetryCommandManualResolutionService.resolve" in src


def test_e2_2_confirm_requires_explicit_json_true_at_schema_boundary():
    """Coercible truthy values must not bypass E2-2 confirmation (API schema)."""
    from pydantic import ValidationError

    from app.schemas.publishing import PublishRetryCommandResolveRequest

    base = {
        "action": "ACKNOWLEDGE_EXTERNAL_SUCCESS",
        "operator_reason": "seen live",
        "evidence_source": "operator_provider_ui",
        "external_post_id": "12345",
    }

    ok = PublishRetryCommandResolveRequest.model_validate(
        {**base, "confirm_permanent_resolution": True},
    )
    assert ok.confirm_permanent_resolution is True

    for bad in ("true", "True", 1, 1.0, False, None, "1", "yes"):
        with pytest.raises(ValidationError) as exc:
            PublishRetryCommandResolveRequest.model_validate(
                {**base, "confirm_permanent_resolution": bad},
            )
        msgs = str(exc.value).lower()
        assert (
            "confirm_permanent_resolution" in msgs
            or "json boolean true" in msgs
        )

    with pytest.raises(ValidationError):
        PublishRetryCommandResolveRequest.model_validate(base)


def test_e2_1_confirm_coercion_semantics_preserved():
    """MARK_AMBIGUOUS keeps established coercible-bool schema behavior."""
    from app.schemas.publishing import PublishRetryCommandResolveRequest

    coerced = PublishRetryCommandResolveRequest.model_validate(
        {
            "action": "MARK_AMBIGUOUS",
            "confirm_permanent_resolution": "true",
            "operator_reason": "review complete",
        },
    )
    assert coerced.confirm_permanent_resolution is True

    coerced_one = PublishRetryCommandResolveRequest.model_validate(
        {
            "action": "MARK_AMBIGUOUS",
            "confirm_permanent_resolution": 1,
            "operator_reason": "review complete",
        },
    )
    assert coerced_one.confirm_permanent_resolution is True


def test_e2_2_confirm_coercion_rejected_at_fastapi_boundary_returns_422():
    """FastAPI request validation returns 422 when JSON true is not explicit."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.schemas.publishing import PublishRetryCommandResolveRequest

    app = FastAPI()

    def _probe(body: PublishRetryCommandResolveRequest):
        return {"ok": True, "confirm": body.confirm_permanent_resolution}

    # Concrete annotations: this module uses from __future__ import annotations.
    _probe.__annotations__ = {
        "body": PublishRetryCommandResolveRequest,
        "return": dict,
    }
    app.post("/resolve-probe")(_probe)

    client = TestClient(app)
    base = {
        "action": "ACKNOWLEDGE_EXTERNAL_SUCCESS",
        "operator_reason": "seen live",
        "evidence_source": "operator_provider_ui",
        "external_post_id": "12345",
    }

    ok = client.post(
        "/resolve-probe",
        json={**base, "confirm_permanent_resolution": True},
    )
    assert ok.status_code == 200
    assert ok.json()["confirm"] is True

    for bad in ("true", 1, False, None):
        resp = client.post(
            "/resolve-probe",
            json={**base, "confirm_permanent_resolution": bad},
        )
        assert resp.status_code == 422, (bad, resp.status_code, resp.text)

    missing = client.post("/resolve-probe", json=base)
    assert missing.status_code == 422

    # E2-1 still accepts coercible true at the HTTP/schema boundary
    e21 = client.post(
        "/resolve-probe",
        json={
            "action": "MARK_AMBIGUOUS",
            "confirm_permanent_resolution": "true",
            "operator_reason": "review complete",
        },
    )
    assert e21.status_code == 200
