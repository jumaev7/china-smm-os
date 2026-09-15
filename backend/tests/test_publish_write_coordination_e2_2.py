"""E2-2 Follow-up B: dormant write-coordination path/concurrency proofs.

Isolated local PostgreSQL + fake adapters only. No real provider I/O,
no production enablement, no commit/push.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.schemas.publishing import PublishContentRequest
from app.services.publish_attempt_ops_service import PublishAttemptOpsService
from app.services.publish_resilience import (
    PublishResilienceService,
    build_idempotency_key,
)
from app.services.publish_retry_command_manual_resolution_service import (
    ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
    ACTION_MARK_AMBIGUOUS,
    PublishRetryCommandManualResolutionService,
)
from app.services.publish_service import ADAPTERS, PublishService
from app.services.publish_write_coordination import (
    PUBLICATION_IN_PROGRESS_ERROR,
    UNRESOLVED_PRIOR_WRITE_FAILURE_CODE,
    advisory_lock_keys,
    normalize_destination,
    write_coordination_enabled,
)

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/"
    "e2_2_write_coordination_test"
)
ACK_EXT = "ack-ext-coord"


def _pg_url() -> str:
    return os.environ.get("PUBLISH_WRITE_COORD_PG_URL", DEFAULT_PG_URL)


async def _wait_ready(engine, attempts: int = 40) -> None:
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(0.2)
    raise RuntimeError(f"PostgreSQL not ready: {last_exc}")


async def _ensure_database() -> str:
    url = _pg_url()
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    db_name = url.rsplit("/", 1)[1]
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
        pytest.skip(f"PostgreSQL unavailable for write-coord tests: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for write-coord tests: {exc}")
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
                company_name VARCHAR(255) NULL,
                telegram_publish_chat_id VARCHAR(255) NULL,
                telegram_publish_title VARCHAR(255) NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE content_items (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                platforms TEXT[] NOT NULL DEFAULT '{}',
                status VARCHAR(30) NOT NULL DEFAULT 'failed',
                caption_long_ru TEXT NULL,
                caption_long_en TEXT NULL,
                caption_short_ru TEXT NULL,
                hashtags TEXT NULL,
                media_file_id UUID NULL,
                approved_at TIMESTAMPTZ NULL,
                updated_at TIMESTAMPTZ NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE publishing_accounts (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                platform VARCHAR(20) NOT NULL,
                account_name VARCHAR(255) NOT NULL DEFAULT 'Bot',
                account_id VARCHAR(255) NOT NULL DEFAULT 'acct',
                status VARCHAR(30) NOT NULL DEFAULT 'mock',
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
            CREATE UNIQUE INDEX uq_publish_attempts_active_claim
            ON publish_attempts (idempotency_key)
            WHERE status = 'in_progress' AND idempotency_key IS NOT NULL
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
                destination_key VARCHAR(100) NOT NULL,
                requested_by UUID NULL,
                requested_source VARCHAR(20) NOT NULL DEFAULT 'workspace',
                idempotency_key VARCHAR(220) NOT NULL,
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
            CREATE TABLE tenant_external_publications (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                provider_publication_id VARCHAR(255) NOT NULL
            )
        """))


@asynccontextmanager
async def _session_factory():
    url = await _ensure_database()
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_schema(engine)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        yield factory
    except OSError as exc:
        pytest.skip(f"PostgreSQL write-coord DB unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL write-coord DB unavailable: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(coro_factory())


class _Fixture:
    def __init__(self, *, multi_platform: bool = False):
        self.tenant_id = uuid4()
        self.other_tenant_id = uuid4()
        self.client_id = uuid4()
        self.content_id = uuid4()
        self.other_content_id = uuid4()
        self.account_id = uuid4()
        self.account_b_id = uuid4()
        self.fb_account_id = uuid4()
        self.original_attempt_id = uuid4()
        self.resulting_attempt_id = uuid4()
        self.command_id = uuid4()
        self.fb_command_id = uuid4()
        self.fb_original_attempt_id = uuid4()
        self.fb_resulting_attempt_id = uuid4()
        self.actor_id = uuid4()
        self.correlation_id = "corr-write-coord"
        self.publish_version = "pv_fixture_v1"
        self.platform = "telegram"
        self.platforms = ["telegram", "facebook"] if multi_platform else ["telegram"]
        self.idempotency_key = build_idempotency_key(
            content_id=self.content_id,
            platform=self.platform,
            account_id=self.account_id,
            publish_version=self.publish_version,
        )


class CountingAdapter:
    def __init__(self, platform: str, post_id: str = "fake-new-post"):
        self.platform = platform
        self.post_id = post_id
        self.invocation_count = 0
        self.lock_held_during_call: bool | None = None
        self._gate: asyncio.Event | None = None
        self._entered: asyncio.Event | None = None
        self._probe_db_factory = None
        self._probe_identity = None
        self._probe_callback = None

    def arm_gate(self):
        self._entered = asyncio.Event()
        self._gate = asyncio.Event()
        return self._entered, self._gate

    def arm_lock_probe(self, factory, identity):
        self._probe_db_factory = factory
        self._probe_identity = identity

    def arm_probe_callback(self, callback):
        """Async callback(ctx) invoked inside the fake provider call."""
        self._probe_callback = callback

    async def __call__(self, ctx) -> dict:
        self.invocation_count += 1
        if self._probe_db_factory is not None and self._probe_identity is not None:
            # Prove advisory xact lock is NOT held on another session during I/O.
            k1, k2 = advisory_lock_keys(self._probe_identity)
            async with self._probe_db_factory() as probe:
                row = (
                    await probe.execute(
                        text(
                            "SELECT pg_try_advisory_xact_lock(:k1, :k2) AS got"
                        ),
                        {"k1": k1, "k2": k2},
                    )
                ).first()
                self.lock_held_during_call = not bool(row.got)
                await probe.rollback()
        if self._probe_callback is not None:
            await self._probe_callback(ctx)
        if self._entered is not None:
            self._entered.set()
        if self._gate is not None:
            await self._gate.wait()
        return {
            "platform": self.platform,
            "success": True,
            "platform_post_id": self.post_id,
            "post_url": None,
            "mock": False,
        }


class FailingAdapter:
    """Fake provider that raises after entry (caught by publish_content)."""

    def __init__(self, platform: str, message: str = "fake provider boom"):
        self.platform = platform
        self.message = message
        self.invocation_count = 0
        self._probe_callback = None

    def arm_probe_callback(self, callback):
        self._probe_callback = callback

    async def __call__(self, ctx) -> dict:
        self.invocation_count += 1
        if self._probe_callback is not None:
            await self._probe_callback(ctx)
        raise RuntimeError(self.message)


async def _seed_base(db: AsyncSession, fx: _Fixture) -> None:
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
            """
            INSERT INTO content_items (
                id, client_id, platforms, status, caption_long_ru,
                approved_at, updated_at
            ) VALUES (
                :id, :cid, :plats, 'failed', 'hello coord',
                NOW(), NOW()
            )
            """
        ),
        {"id": fx.content_id, "cid": fx.client_id, "plats": fx.platforms},
    )
    await db.execute(
        text(
            """
            INSERT INTO publishing_accounts
                (id, tenant_id, platform, account_name, account_id, status)
            VALUES (:id, :tid, 'telegram', 'TG A', 'tg-a', 'mock')
            """
        ),
        {"id": fx.account_id, "tid": fx.tenant_id},
    )
    await db.execute(
        text(
            """
            INSERT INTO publishing_accounts
                (id, tenant_id, platform, account_name, account_id, status)
            VALUES (:id, :tid, 'telegram', 'TG B', 'tg-b', 'mock')
            """
        ),
        {"id": fx.account_b_id, "tid": fx.tenant_id},
    )
    if "facebook" in fx.platforms:
        await db.execute(
            text(
                """
                INSERT INTO publishing_accounts
                    (id, tenant_id, platform, account_name, account_id, status)
                VALUES (:id, :tid, 'facebook', 'FB A', 'fb-a', 'mock')
                """
            ),
            {"id": fx.fb_account_id, "tid": fx.tenant_id},
        )


async def _seed_stranded(
    db: AsyncSession,
    fx: _Fixture,
    *,
    status: str = "provider_write_started",
    provider_write_started: bool = True,
) -> None:
    await _seed_base(db, fx)
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                publish_version, failure_code, retryable, next_retry_at,
                finished_at, retry_command_id, response, idempotency_key
            ) VALUES (
                :id, :cid, :p, :aid, 'failed',
                :ver, 'provider_error', true, NOW() + interval '1 hour',
                NULL, NULL, NULL, :ikey
            )
            """
        ),
        {
            "id": fx.original_attempt_id,
            "cid": fx.content_id,
            "p": fx.platform,
            "aid": fx.account_id,
            "ver": fx.publish_version,
            "ikey": fx.idempotency_key,
        },
    )
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                publish_version, failure_code, failure_category,
                retryable, next_retry_at, finished_at, retry_command_id,
                error, external_post_id, response, idempotency_key, lease_owner
            ) VALUES (
                :id, :cid, :p, :aid, 'operator_review',
                :ver, 'retry_command_write_started', 'command_orchestration',
                false, NULL, NULL, :crid,
                'write barrier crossed', NULL, NULL, :ikey, 'worker-a'
            )
            """
        ),
        {
            "id": fx.resulting_attempt_id,
            "cid": fx.content_id,
            "p": fx.platform,
            "aid": fx.account_id,
            "ver": fx.publish_version,
            "crid": fx.command_id,
            "ikey": fx.idempotency_key,
        },
    )
    pws_sql = "NOW() - interval '10 minutes'" if provider_write_started else "NULL"
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
                :oid, :rid,
                :p, :aid, :ver,
                'dest', 'workspace', :ikey,
                :st, NULL, {pws_sql},
                NULL, :corr, 'worker-a', NOW() - interval '15 minutes'
            )
            """
        ),
        {
            "id": fx.command_id,
            "tid": fx.tenant_id,
            "clid": fx.client_id,
            "cid": fx.content_id,
            "oid": fx.original_attempt_id,
            "rid": fx.resulting_attempt_id,
            "p": fx.platform,
            "aid": fx.account_id,
            "ver": fx.publish_version,
            "ikey": f"cmd-{fx.command_id}",
            "corr": fx.correlation_id,
            "st": status,
        },
    )
    await db.commit()


async def _ack(db: AsyncSession, fx: _Fixture):
    with (
        patch.object(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True),
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", True),
    ):
        return await PublishRetryCommandManualResolutionService.resolve(
            db,
            command_id=fx.command_id,
            tenant_id=fx.tenant_id,
            action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
            confirm_permanent_resolution=True,
            operator_reason="Verified live Telegram message in channel UI",
            evidence_source="operator_provider_ui",
            external_post_id=ACK_EXT,
            external_post_url="https://t.me/c/1/12345",
            actor_id=fx.actor_id,
            commit=True,
        )


def _content_ns(fx: _Fixture) -> SimpleNamespace:
    return SimpleNamespace(
        id=fx.content_id,
        client_id=fx.client_id,
        media_file_id=None,
        media_file=None,
        platforms=list(fx.platforms),
        status="failed",
        source="manual",
        caption_short_ru=None,
        caption_long_ru="hello coord",
        caption_long_en=None,
        caption_long_uz=None,
        caption_long_zh=None,
        caption_short_uz=None,
        caption_short_en=None,
        caption_short_zh=None,
        hashtags=None,
        internal_notes=None,
        approved_at=datetime.now(timezone.utc),
        published_at=None,
        client_review_status=None,
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


@contextmanager
def _publish_harness(fx: _Fixture, adapters: dict[str, CountingAdapter], *, coord: bool):
    item = _content_ns(fx)

    def _fixed_version(_item, _payload=None):
        return fx.publish_version

    async def _get_content(_db, content_id):
        assert content_id == fx.content_id
        return item

    async def _serialize(_db, _item):
        return {
            "id": str(fx.content_id),
            "platforms": list(fx.platforms),
            "caption_long_ru": "hello coord",
            "media_url": None,
            "generated_final_video_url": None,
        }

    async def _resolve(_db, _tenant_id, platform, account_id=None, **_kwargs):
        plat = (platform or "").strip().lower()
        if account_id is not None:
            aid = account_id
        elif plat == "facebook":
            aid = fx.fb_account_id
        else:
            aid = fx.account_id
        if aid == fx.fb_account_id:
            name, external = "FB A", "fb-a"
        elif aid == fx.account_b_id:
            name, external = "TG B", "tg-b"
        else:
            name, external = "TG A", "tg-a"
        return SimpleNamespace(
            id=aid,
            account_name=name,
            account_id=external,
            status="mock",
            platform=plat or platform,
            tenant_id=fx.tenant_id,
            expires_at=None,
            access_token_encrypted=None,
            facebook_page_id="page-1" if plat == "facebook" else None,
            instagram_business_account_id=None,
        )

    with (
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", coord),
        patch.object(PublishService, "_get_content", staticmethod(_get_content)),
        patch.object(
            PublishService,
            "recover_stale_publishing",
            new=staticmethod(AsyncMock(return_value=0)),
        ),
        patch(
            "app.services.content_service.ContentService.serialize_detail",
            new=AsyncMock(side_effect=_serialize),
        ),
        patch(
            "app.services.publish_safety_service.PublishSafetyService.enforce_or_block",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.publish_service.compute_publish_version",
            side_effect=_fixed_version,
        ),
        patch(
            "app.services.publish_service.tenant_id_for_content",
            new=AsyncMock(return_value=fx.tenant_id),
        ),
        patch(
            "app.services.publishing_account_service.PublishingAccountService.resolve_for_platform",
            new=AsyncMock(side_effect=_resolve),
        ),
        patch.object(
            PublishService,
            "_client_publish_context",
            new=staticmethod(
                AsyncMock(
                    return_value={
                        "chat_id": None,
                        "company_name": "Co",
                        "publish_title": None,
                    }
                )
            ),
        ),
        # Minimal schema cannot load full ContentItem/Client ORM graphs used by
        # alert + measurement helpers; keep them out of the publish TX under test.
        patch.object(
            PublishResilienceService,
            "_notify_alert",
            new=staticmethod(AsyncMock(return_value=None)),
        ),
        patch(
            "app.services.measurement.publication_registry.register_from_publish_attempt",
            new=AsyncMock(return_value=None),
        ),
        patch.dict(ADAPTERS, adapters, clear=False),
    ):
        yield


def _result_for(platform: str, results: list) -> dict | None:
    for row in results:
        if row.get("platform") == platform:
            return row
    return None


def test_flag_defaults_false():
    assert write_coordination_enabled() is False
    assert type(settings).model_fields["PUBLISH_WRITE_COORDINATION_ENABLED"].default is False


def test_advisory_key_stable_and_not_python_hash():
    a = normalize_destination(
        tenant_id=uuid4(),
        content_id=uuid4(),
        platform="Telegram",
        account_id=None,
    )
    b = normalize_destination(
        tenant_id=a.tenant_id,
        content_id=a.content_id,
        platform="telegram",
        account_id=None,
    )
    assert advisory_lock_keys(a) == advisory_lock_keys(b)
    # Different account → different key
    c = normalize_destination(
        tenant_id=a.tenant_id,
        content_id=a.content_id,
        platform="telegram",
        account_id=uuid4(),
    )
    assert advisory_lock_keys(a) != advisory_lock_keys(c)
    src = inspect.getsource(advisory_lock_keys)
    assert "hashlib.sha256" in src
    assert "Python hash()" not in src.replace("Python ``hash()``.", "")
    # Ensure we do not call builtin hash() for key derivation.
    assert "hash(material" not in src
    assert "hash(str" not in src
    assert "hash(identity" not in src


def test_coordination_disabled_preserves_begin_attempt_past_unresolved():
    """With coordination off, stranded provider_write_started does not block claim."""
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with (
                _publish_harness(fx, {"telegram": tg}, coord=False),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 1
            assert _result_for("telegram", result["results"])["success"] is True

    _run(body)


def test_unresolved_provider_write_started_blocks_provider_invocation():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 0
            row = _result_for("telegram", result["results"])
            assert row["failure_code"] == UNRESOLVED_PRIOR_WRITE_FAILURE_CODE
            assert row["retryable"] is False
            # No automatic retry attempt created solely for coordination denial.
            async with factory() as db:
                inflight = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id,
                            PublishAttempt.status == "in_progress",
                        )
                    )
                ).scalars().all()
                assert inflight == []

    _run(body)


def test_ambiguous_blocks_without_automatic_retry():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(
                    db, fx, status="ambiguous", provider_write_started=False
                )
                await db.execute(
                    text(
                        "UPDATE publish_retry_commands SET provider_outcome='ambiguous', "
                        "reason_code='manual_mark_ambiguous', finished_at=NOW() "
                        "WHERE id=:id"
                    ),
                    {"id": fx.command_id},
                )
                await db.commit()
            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 0
            row = _result_for("telegram", result["results"])
            assert row["failure_code"] == UNRESOLVED_PRIOR_WRITE_FAILURE_CODE
            assert row["retryable"] is False

    _run(body)


def test_cross_version_unresolved_blocks_new_version():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
                patch(
                    "app.services.publish_service.compute_publish_version",
                    return_value="pv_new_version_xyz",
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 0
            assert (
                _result_for("telegram", result["results"])["failure_code"]
                == UNRESOLVED_PRIOR_WRITE_FAILURE_CODE
            )

    _run(body)


def test_different_account_not_blocked_by_unresolved():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_b_id,
                        ),
                    )
            assert tg.invocation_count == 1
            assert _result_for("telegram", result["results"])["success"] is True

    _run(body)


def test_ack_before_publish_prevents_invocation():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            async with factory() as db:
                await _ack(db, fx)
            with _publish_harness(fx, {"telegram": tg}, coord=True):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 0
            row = _result_for("telegram", result["results"])
            assert row.get("deduplicated") is True
            assert row.get("platform_post_id") == ACK_EXT

    _run(body)


def test_no_lock_held_during_fake_provider_invocation():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.commit()
            identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )
            tg.arm_lock_probe(factory, identity)
            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 1
            assert tg.lock_held_during_call is False

    _run(body)


def test_two_ordinary_same_intent_publishes_serialize():
    fx = _Fixture()
    tg_a = CountingAdapter("telegram", post_id="post-a")
    entered, gate = tg_a.arm_gate()
    tg_b = CountingAdapter("telegram", post_id="post-b")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.commit()

            async def first():
                with (
                    _publish_harness(fx, {"telegram": tg_a}, coord=True),
                    patch.object(
                        PublishService,
                        "_prior_live_successes",
                        new=staticmethod(AsyncMock(return_value={})),
                    ),
                ):
                    async with factory() as db:
                        return await PublishService.publish_content(
                            db,
                            fx.content_id,
                            request=PublishContentRequest(
                                mode="manual_publish",
                                platforms=["telegram"],
                                account_id=fx.account_id,
                            ),
                        )

            async def second():
                await entered.wait()
                with (
                    _publish_harness(fx, {"telegram": tg_b}, coord=True),
                    patch.object(
                        PublishService,
                        "_prior_live_successes",
                        new=staticmethod(AsyncMock(return_value={})),
                    ),
                ):
                    async with factory() as db:
                        out = await PublishService.publish_content(
                            db,
                            fx.content_id,
                            request=PublishContentRequest(
                                mode="manual_publish",
                                platforms=["telegram"],
                                account_id=fx.account_id,
                            ),
                        )
                gate.set()
                return out

            t1 = asyncio.create_task(first())
            t2 = asyncio.create_task(second())
            r1, r2 = await asyncio.gather(t1, t2)
            # First claimed+committed before adapter; second must not invoke.
            assert tg_a.invocation_count == 1
            assert tg_b.invocation_count == 0
            row2 = _result_for("telegram", r2["results"])
            assert row2.get("failure_code") == "concurrent_claim" or row2.get(
                "deduplicated"
            )
            assert r1 is not None

    _run(body)


def test_overlapping_guard_ack_then_publish_sees_success():
    """Publish waits before begin_attempt; ack commits first; publish resumes → 0 invokes."""
    fx = _Fixture()
    tg = CountingAdapter("telegram")
    entered = asyncio.Event()
    release = asyncio.Event()
    original_begin = PublishResilienceService.begin_attempt

    async def gated_begin(db, **kwargs):
        entered.set()
        await release.wait()
        return await original_begin(db, **kwargs)

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)

            async def publisher():
                with (
                    _publish_harness(fx, {"telegram": tg}, coord=True),
                    patch.object(
                        PublishResilienceService,
                        "begin_attempt",
                        new=staticmethod(gated_begin),
                    ),
                    patch.object(
                        PublishService,
                        "_prior_live_successes",
                        new=staticmethod(AsyncMock(return_value={})),
                    ),
                ):
                    async with factory() as db:
                        return await PublishService.publish_content(
                            db,
                            fx.content_id,
                            request=PublishContentRequest(
                                mode="manual_publish",
                                platforms=["telegram"],
                                account_id=fx.account_id,
                            ),
                        )

            async def acknowledger():
                await entered.wait()
                async with factory() as db:
                    await _ack(db, fx)
                release.set()

            pub_task = asyncio.create_task(publisher())
            ack_task = asyncio.create_task(acknowledger())
            result, _ = await asyncio.gather(pub_task, ack_task)
            assert tg.invocation_count == 0
            row = _result_for("telegram", result["results"])
            assert row.get("deduplicated") is True or row.get("platform_post_id") == ACK_EXT

    _run(body)


def test_rollback_releases_advisory_lock():
    fx = _Fixture()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.commit()
            identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )
            k1, k2 = advisory_lock_keys(identity)
            with patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", True):
                async with factory() as db:
                    account = SimpleNamespace(
                        id=fx.account_id, account_name="TG A", status="mock"
                    )
                    claim = await PublishResilienceService.begin_attempt(
                        db,
                        content_id=fx.content_id,
                        platform="telegram",
                        account=account,
                        publish_version=fx.publish_version,
                        lease_owner="roll",
                        tenant_id=fx.tenant_id,
                    )
                    assert claim.skip is False
                    await db.rollback()
            async with factory() as db:
                got = (
                    await db.execute(
                        text("SELECT pg_try_advisory_xact_lock(:k1, :k2) AS got"),
                        {"k1": k1, "k2": k2},
                    )
                ).first()
                assert got.got is True
                await db.rollback()
                # Claim must not be durable after rollback.
                rows = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id,
                            PublishAttempt.status == "in_progress",
                        )
                    )
                ).scalars().all()
                assert rows == []

    _run(body)


def test_e2_1_mark_ambiguous_independent_of_coordination():
    fx = _Fixture()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with (
                patch.object(
                    settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", True
                ),
                patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False),
            ):
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

    _run(body)


def test_prebarrier_claimed_excluded_while_execution_disabled():
    """claimed (pre-barrier) must not block ordinary publish while execution off."""
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(
                    db, fx, status="claimed", provider_write_started=False
                )
            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 1
            assert _result_for("telegram", result["results"])["success"] is True

    _run(body)


def test_legitimate_new_intent_different_content():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
                other_client = uuid4()
                await db.execute(
                    text(
                        "INSERT INTO clients (id, tenant_id) VALUES (:id, :tid)"
                    ),
                    {"id": other_client, "tid": fx.tenant_id},
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO content_items
                            (id, client_id, platforms, status, caption_long_ru)
                        VALUES (:id, :cid, '{telegram}', 'failed', 'other')
                        """
                    ),
                    {"id": fx.other_content_id, "cid": other_client},
                )
                await db.commit()

            other_fx = _Fixture()
            other_fx.tenant_id = fx.tenant_id
            other_fx.client_id = other_client
            other_fx.content_id = fx.other_content_id
            other_fx.account_id = fx.account_id
            other_fx.publish_version = "pv_other"
            other_fx.platforms = ["telegram"]

            with (
                _publish_harness(other_fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        other_fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert tg.invocation_count == 1
            assert _result_for("telegram", result["results"])["success"] is True

    _run(body)


# ── Follow-up B — pre-commit transaction boundary verification ────────────────


async def _seed_retrying_original(db: AsyncSession, fx: _Fixture) -> None:
    """Real manual-retry predecessor: retrying row with a future next_retry_at."""
    await _seed_base(db, fx)
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                publish_version, failure_code, failure_category,
                retryable, next_retry_at, finished_at, response,
                idempotency_key, attempt_number, error
            ) VALUES (
                :id, :cid, :p, :aid, 'retrying',
                :ver, 'provider_error', 'provider',
                true, NOW() + interval '2 hours', NULL, NULL,
                :ikey, 1, 'prior provider error'
            )
            """
        ),
        {
            "id": fx.original_attempt_id,
            "cid": fx.content_id,
            "p": fx.platform,
            "aid": fx.account_id,
            "ver": fx.publish_version,
            "ikey": fx.idempotency_key,
        },
    )
    await db.commit()


async def _seed_fb_stranded(db: AsyncSession, fx: _Fixture) -> None:
    """Unresolved facebook destination command (same content, different identity)."""
    fb_key = build_idempotency_key(
        content_id=fx.content_id,
        platform="facebook",
        account_id=fx.fb_account_id,
        publish_version=fx.publish_version,
    )
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                publish_version, failure_code, retryable, next_retry_at,
                finished_at, retry_command_id, response, idempotency_key
            ) VALUES (
                :id, :cid, 'facebook', :aid, 'failed',
                :ver, 'provider_error', true, NOW() + interval '1 hour',
                NULL, NULL, NULL, :ikey
            )
            """
        ),
        {
            "id": fx.fb_original_attempt_id,
            "cid": fx.content_id,
            "aid": fx.fb_account_id,
            "ver": fx.publish_version,
            "ikey": fb_key,
        },
    )
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                publish_version, failure_code, failure_category,
                retryable, next_retry_at, finished_at, retry_command_id,
                error, external_post_id, response, idempotency_key, lease_owner
            ) VALUES (
                :id, :cid, 'facebook', :aid, 'operator_review',
                :ver, 'retry_command_write_started', 'command_orchestration',
                false, NULL, NULL, :crid,
                'write barrier crossed', NULL, NULL, :ikey, 'worker-fb'
            )
            """
        ),
        {
            "id": fx.fb_resulting_attempt_id,
            "cid": fx.content_id,
            "aid": fx.fb_account_id,
            "ver": fx.publish_version,
            "crid": fx.fb_command_id,
            "ikey": fb_key,
        },
    )
    await db.execute(
        text(
            """
            INSERT INTO publish_retry_commands (
                id, tenant_id, client_id, content_id,
                original_attempt_id, resulting_attempt_id,
                platform, publishing_account_id, publish_version,
                destination_key, requested_source, idempotency_key,
                status, provider_outcome, provider_write_started_at,
                finished_at, correlation_id, lease_owner, claimed_at
            ) VALUES (
                :id, :tid, :clid, :cid,
                :oid, :rid,
                'facebook', :aid, :ver,
                'dest-fb', 'workspace', :ikey,
                'provider_write_started', NULL, NOW() - interval '10 minutes',
                NULL, :corr, 'worker-fb', NOW() - interval '15 minutes'
            )
            """
        ),
        {
            "id": fx.fb_command_id,
            "tid": fx.tenant_id,
            "clid": fx.client_id,
            "cid": fx.content_id,
            "oid": fx.fb_original_attempt_id,
            "rid": fx.fb_resulting_attempt_id,
            "aid": fx.fb_account_id,
            "ver": fx.publish_version,
            "ikey": f"cmd-fb-{fx.fb_command_id}",
            "corr": f"{fx.correlation_id}-fb",
        },
    )
    await db.commit()


async def _try_destination_lock(factory, identity) -> bool:
    k1, k2 = advisory_lock_keys(identity)
    async with factory() as probe:
        row = (
            await probe.execute(
                text("SELECT pg_try_advisory_xact_lock(:k1, :k2) AS got"),
                {"k1": k1, "k2": k2},
            )
        ).first()
        got = bool(row.got)
        await probe.rollback()
    return got


def test_manual_retry_pending_mutations_durable_at_non_meta_early_commit():
    """Real caller (manual_retry): next_retry_at clear becomes durable before Telegram I/O.

    Matches the established Meta early-commit contract, extended to non-Meta when
    write coordination is enabled. Evidence uses the caller's own pending row —
    not artificial unrelated dirty data.
    """
    fx = _Fixture()
    tg = CountingAdapter("telegram")
    midflight: dict = {}

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_retrying_original(db, fx)

            identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )

            async def probe_during_io(_ctx):
                async with factory() as peer:
                    row = (
                        await peer.execute(
                            text(
                                "SELECT status, next_retry_at IS NULL AS cleared "
                                "FROM publish_attempts WHERE id = :id"
                            ),
                            {"id": fx.original_attempt_id},
                        )
                    ).first()
                    midflight["original_status"] = row.status
                    midflight["original_retry_cleared"] = bool(row.cleared)
                    inflight = (
                        await peer.execute(
                            text(
                                "SELECT count(*) FROM publish_attempts "
                                "WHERE content_id = :cid AND status = 'in_progress'"
                            ),
                            {"cid": fx.content_id},
                        )
                    ).scalar_one()
                    midflight["inflight_count"] = int(inflight)
                midflight["lock_free"] = await _try_destination_lock(factory, identity)

            tg.arm_probe_callback(probe_during_io)

            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    out = await PublishAttemptOpsService.manual_retry(
                        db,
                        fx.original_attempt_id,
                        tenant_id=fx.tenant_id,
                        source="workspace",
                        actor_role="operator",
                        skip_eligibility=True,
                    )

            assert out["ok"] is True
            assert tg.invocation_count == 1
            assert midflight["original_status"] == "failed"
            assert midflight["original_retry_cleared"] is True
            assert midflight["inflight_count"] == 1
            assert midflight["lock_free"] is True

            async with factory() as db:
                original = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.id == fx.original_attempt_id
                        )
                    )
                ).scalar_one()
                assert original.status == "failed"
                assert original.next_retry_at is None
                successes = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id,
                            PublishAttempt.status == "success",
                        )
                    )
                ).scalars().all()
                assert len(successes) == 1

    _run(body)


def test_provider_exception_after_durable_claim_finalizes_and_releases_lock():
    fx = _Fixture()
    tg = FailingAdapter("telegram", message="simulated telegram outage")
    midflight: dict = {}

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.commit()

            identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )

            async def probe_during_io(_ctx):
                async with factory() as peer:
                    inflight = (
                        await peer.execute(
                            text(
                                "SELECT count(*) FROM publish_attempts "
                                "WHERE content_id = :cid AND status = 'in_progress'"
                            ),
                            {"cid": fx.content_id},
                        )
                    ).scalar_one()
                    midflight["inflight_during_io"] = int(inflight)
                midflight["lock_free_during_io"] = await _try_destination_lock(
                    factory, identity
                )

            tg.arm_probe_callback(probe_during_io)

            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )

            assert tg.invocation_count == 1
            assert midflight["inflight_during_io"] == 1
            assert midflight["lock_free_during_io"] is True
            row = _result_for("telegram", result["results"])
            assert row is not None
            assert row["success"] is False
            assert result["all_success"] is False

            async with factory() as db:
                attempts = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id
                        )
                    )
                ).scalars().all()
                assert attempts
                assert all(a.status != "in_progress" for a in attempts)
                terminal = {a.status for a in attempts}
                assert "in_progress" not in terminal
                assert terminal & {"retrying", "failed", "operator_review", "exhausted"}
            assert await _try_destination_lock(factory, identity) is True

    _run(body)


def test_second_destination_fails_after_first_success_durable_partial():
    fx = _Fixture(multi_platform=True)
    tg = CountingAdapter("telegram", post_id="tg-ok-1")
    fb = FailingAdapter("facebook", message="simulated facebook outage")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.commit()

            with (
                _publish_harness(fx, {"telegram": tg, "facebook": fb}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram", "facebook"],
                        ),
                    )

            assert tg.invocation_count == 1
            assert fb.invocation_count == 1
            assert _result_for("telegram", result["results"])["success"] is True
            assert _result_for("facebook", result["results"])["success"] is False
            assert result["all_success"] is False

            async with factory() as db:
                rows = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id
                        )
                    )
                ).scalars().all()
                by_plat = {a.platform: a for a in rows}
                assert by_plat["telegram"].status == "success"
                assert by_plat["telegram"].external_post_id == "tg-ok-1"
                assert by_plat["facebook"].status != "in_progress"
                assert by_plat["facebook"].status in {
                    "retrying",
                    "failed",
                    "operator_review",
                    "exhausted",
                }
                assert not any(a.status == "in_progress" for a in rows)

            tg_id = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )
            fb_id = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="facebook",
                account_id=fx.fb_account_id,
            )
            assert await _try_destination_lock(factory, tg_id) is True
            assert await _try_destination_lock(factory, fb_id) is True

    _run(body)


def test_coordination_denied_then_eligible_does_not_hold_lock_across_provider_io():
    """Telegram denied (unresolved); Facebook eligible. Telegram lock free during FB I/O."""
    fx = _Fixture(multi_platform=True)
    tg = CountingAdapter("telegram")
    fb = CountingAdapter("facebook", post_id="fb-ok-1")
    midflight: dict = {}

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)

            tg_identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )
            fb_identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="facebook",
                account_id=fx.fb_account_id,
            )

            async def probe_during_fb(_ctx):
                midflight["tg_lock_free"] = await _try_destination_lock(
                    factory, tg_identity
                )
                midflight["fb_lock_free"] = await _try_destination_lock(
                    factory, fb_identity
                )

            fb.arm_probe_callback(probe_during_fb)
            fb.arm_lock_probe(factory, fb_identity)

            with (
                _publish_harness(fx, {"telegram": tg, "facebook": fb}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram", "facebook"],
                        ),
                    )

            assert tg.invocation_count == 0
            assert fb.invocation_count == 1
            tg_row = _result_for("telegram", result["results"])
            assert tg_row["failure_code"] == UNRESOLVED_PRIOR_WRITE_FAILURE_CODE
            assert _result_for("facebook", result["results"])["success"] is True
            # Denied branch must not retain its destination lock across the
            # subsequent provider invocation (released by FB early-commit).
            assert midflight["tg_lock_free"] is True
            assert midflight["fb_lock_free"] is True
            assert fb.lock_held_during_call is False
            assert await _try_destination_lock(factory, tg_identity) is True
            assert await _try_destination_lock(factory, fb_identity) is True

    _run(body)


def test_all_destinations_skipped_or_denied_no_inflight_locks_released():
    fx = _Fixture(multi_platform=True)
    tg = CountingAdapter("telegram")
    fb = CountingAdapter("facebook")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
                await _seed_fb_stranded(db, fx)

            tg_identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )
            fb_identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="facebook",
                account_id=fx.fb_account_id,
            )

            with (
                _publish_harness(fx, {"telegram": tg, "facebook": fb}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram", "facebook"],
                        ),
                    )

            assert tg.invocation_count == 0
            assert fb.invocation_count == 0
            assert (
                _result_for("telegram", result["results"])["failure_code"]
                == UNRESOLVED_PRIOR_WRITE_FAILURE_CODE
            )
            assert (
                _result_for("facebook", result["results"])["failure_code"]
                == UNRESOLVED_PRIOR_WRITE_FAILURE_CODE
            )
            async with factory() as db:
                inflight = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id,
                            PublishAttempt.status == "in_progress",
                        )
                    )
                ).scalars().all()
                assert inflight == []
            assert await _try_destination_lock(factory, tg_identity) is True
            assert await _try_destination_lock(factory, fb_identity) is True

    _run(body)


def test_caller_rollback_after_failure_cannot_undo_early_committed_claim():
    """After coordination early-commit, session rollback cannot erase the claim.

    Mirrors Meta's long-standing early-commit durability: post-commit rollback
    only affects the new transaction opened after commit.
    """
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.commit()

            identity = normalize_destination(
                tenant_id=fx.tenant_id,
                content_id=fx.content_id,
                platform="telegram",
                account_id=fx.account_id,
            )

            with (
                _publish_harness(fx, {"telegram": tg}, coord=True),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
                patch.object(
                    PublishService,
                    "_record_attempt",
                    new=staticmethod(
                        AsyncMock(side_effect=RuntimeError("finalize boom"))
                    ),
                ),
            ):
                async with factory() as db:
                    with pytest.raises(HTTPException) as exc_info:
                        await PublishService.publish_content(
                            db,
                            fx.content_id,
                            request=PublishContentRequest(
                                mode="manual_publish",
                                platforms=["telegram"],
                                account_id=fx.account_id,
                            ),
                        )
                    assert exc_info.value.status_code == 500
                    # Caller-style cleanup after publish_content failure.
                    await db.rollback()

            assert tg.invocation_count == 1
            async with factory() as db:
                inflight = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id,
                            PublishAttempt.status == "in_progress",
                        )
                    )
                ).scalars().all()
                # Early commit made the claim durable; rollback did not erase it.
                assert len(inflight) == 1
                assert inflight[0].platform == "telegram"
            assert await _try_destination_lock(factory, identity) is True

    _run(body)


def test_coordination_disabled_non_meta_keeps_claim_in_open_transaction():
    """With coordination off, Telegram claim is not durable mid-provider I/O.

    Preserves pre-coordination transaction behavior (Meta still early-commits).
    """
    fx = _Fixture()
    tg = CountingAdapter("telegram")
    midflight: dict = {}

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_retrying_original(db, fx)

            async def probe_during_io(_ctx):
                async with factory() as peer:
                    row = (
                        await peer.execute(
                            text(
                                "SELECT status, next_retry_at IS NULL AS cleared "
                                "FROM publish_attempts WHERE id = :id"
                            ),
                            {"id": fx.original_attempt_id},
                        )
                    ).first()
                    midflight["original_status"] = row.status
                    midflight["original_retry_cleared"] = bool(row.cleared)
                    inflight = (
                        await peer.execute(
                            text(
                                "SELECT count(*) FROM publish_attempts "
                                "WHERE content_id = :cid AND status = 'in_progress'"
                            ),
                            {"cid": fx.content_id},
                        )
                    ).scalar_one()
                    midflight["inflight_count"] = int(inflight)

            tg.arm_probe_callback(probe_during_io)

            with (
                _publish_harness(fx, {"telegram": tg}, coord=False),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
                patch.object(
                    PublishService,
                    "_record_attempt",
                    new=staticmethod(
                        AsyncMock(side_effect=RuntimeError("finalize boom"))
                    ),
                ),
            ):
                async with factory() as db:
                    with pytest.raises(HTTPException):
                        await PublishAttemptOpsService.manual_retry(
                            db,
                            fx.original_attempt_id,
                            tenant_id=fx.tenant_id,
                            source="workspace",
                            actor_role="operator",
                            skip_eligibility=True,
                        )
                    await db.rollback()

            assert tg.invocation_count == 1
            # Mid-I/O: caller pending mutations + claim still uncommitted.
            assert midflight["original_status"] == "retrying"
            assert midflight["original_retry_cleared"] is False
            assert midflight["inflight_count"] == 0

            async with factory() as db:
                original = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.id == fx.original_attempt_id
                        )
                    )
                ).scalar_one()
                assert original.status == "retrying"
                assert original.next_retry_at is not None
                inflight = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.content_id == fx.content_id,
                            PublishAttempt.status == "in_progress",
                        )
                    )
                ).scalars().all()
                assert inflight == []

    _run(body)
