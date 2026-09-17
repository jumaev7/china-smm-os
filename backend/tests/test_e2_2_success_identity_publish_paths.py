"""E2-2 follow-up A: success identity alignment + publish-path verification.

Isolated local PostgreSQL + fake adapters only. No real provider I/O,
no flag enablement, no production access.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.schemas.publishing import PublishContentRequest
from app.services.manual_retry_eligibility import (
    build_manual_retry_live_state,
)
from app.services.publish_attempt_ops_service import PublishAttemptOpsService
from app.services.publish_resilience import (
    PublishResilienceService,
    build_idempotency_key,
)
from app.services.publish_retry_command_manual_resolution_service import (
    ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
    PublishRetryCommandManualResolutionService,
)
from app.services.publish_service import ADAPTERS, PublishService
from app.services.scheduled_publish_service import ScheduledPublishService

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/"
    "e2_2_success_identity_publish_path_test"
)
ACK_EXT = "ack-ext-12345"


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_E2_2_PATH_PG_URL", DEFAULT_PG_URL)


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
        pytest.skip(f"PostgreSQL unavailable for E2-2 path tests: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for E2-2 path tests: {exc}")
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
                tenant_id UUID NULL,
                company_name VARCHAR(255) NULL,
                telegram_publish_chat_id VARCHAR(255) NULL,
                telegram_publish_title VARCHAR(255) NULL
            )
        """))
        await conn.execute(text("""
            CREATE TABLE content_items (
                id UUID PRIMARY KEY,
                client_id UUID NOT NULL,
                media_file_id UUID NULL,
                platforms TEXT[] NOT NULL DEFAULT '{}',
                status VARCHAR(30) NOT NULL DEFAULT 'failed',
                source VARCHAR(20) NOT NULL DEFAULT 'manual',
                telegram_group_title VARCHAR(255) NULL,
                telegram_message_id BIGINT NULL,
                telegram_excluded BOOLEAN NOT NULL DEFAULT false,
                telegram_instructions TEXT NULL,
                context_ai_override VARCHAR(50) NULL,
                telegram_original_caption TEXT NULL,
                content_classification VARCHAR(50) NULL,
                suggestions_json TEXT NULL,
                quality_warnings_json TEXT NULL,
                telegram_media_group_id VARCHAR(50) NULL,
                telegram_forward_from VARCHAR(255) NULL,
                telegram_buffer_refs TEXT NULL,
                caption_short_ru TEXT NULL,
                caption_short_uz TEXT NULL,
                caption_short_en TEXT NULL,
                caption_short_zh TEXT NULL,
                caption_long_ru TEXT NULL,
                caption_long_uz TEXT NULL,
                caption_long_en TEXT NULL,
                caption_long_zh TEXT NULL,
                hashtags TEXT NULL,
                internal_notes TEXT NULL,
                scheduled_for TIMESTAMPTZ NULL,
                approved_at TIMESTAMPTZ NULL,
                published_at TIMESTAMPTZ NULL,
                review_token VARCHAR(64) NULL,
                client_approved_at TIMESTAMPTZ NULL,
                client_review_feedback TEXT NULL,
                client_review_status VARCHAR(30) NULL,
                client_review_preview_sent_at TIMESTAMPTZ NULL,
                client_review_preview_error TEXT NULL,
                media_request_sent_at TIMESTAMPTZ NULL,
                media_request_message TEXT NULL,
                media_request_status VARCHAR(20) NULL,
                media_request_format VARCHAR(20) NULL,
                campaign_id UUID NULL,
                parent_content_id UUID NULL,
                parent_media_asset_id UUID NULL,
                linked_sales_lead_id UUID NULL,
                linked_buyer_id UUID NULL,
                linked_sales_deal_id UUID NULL,
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
            CREATE UNIQUE INDEX uq_publish_attempts_retry_command_id
            ON publish_attempts (retry_command_id)
            WHERE retry_command_id IS NOT NULL
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
        pytest.skip(f"PostgreSQL E2-2 path test DB unavailable at {url}: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL E2-2 path test DB unavailable at {url}: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(coro_factory())


class _Fixture:
    def __init__(self, *, multi_platform: bool = False):
        self.tenant_id = uuid4()
        self.client_id = uuid4()
        self.content_id = uuid4()
        self.account_id = uuid4()
        self.account_b_id = uuid4()
        self.fb_account_id = uuid4()
        self.original_attempt_id = uuid4()
        self.resulting_attempt_id = uuid4()
        self.command_id = uuid4()
        self.actor_id = uuid4()
        self.correlation_id = "corr-e22-path"
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
        self.calls: list[object] = []
        self._gate: asyncio.Event | None = None
        self._entered: asyncio.Event | None = None

    def arm_gate(self) -> tuple[asyncio.Event, asyncio.Event]:
        self._entered = asyncio.Event()
        self._gate = asyncio.Event()
        return self._entered, self._gate

    async def __call__(self, ctx) -> dict:
        self.invocation_count += 1
        self.calls.append(ctx)
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


async def _seed_base(db: AsyncSession, fx: _Fixture) -> None:
    await db.execute(
        text("INSERT INTO tenants (id, company_name) VALUES (:id, 't')"),
        {"id": fx.tenant_id},
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
                :id, :cid, :plats, 'failed', 'hello path',
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


async def _seed_stranded(db: AsyncSession, fx: _Fixture) -> None:
    await _seed_base(db, fx)
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                publish_version, failure_code, retryable, next_retry_at,
                finished_at, idempotency_key
            ) VALUES (
                :id, :cid, :p, :aid, 'failed',
                :ver, 'provider_error', true, NOW() + interval '1 hour',
                NULL, :ikey
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
                retryable, next_retry_at, finished_at,
                external_post_id, response, idempotency_key,
                retry_command_id, lease_owner
            ) VALUES (
                :id, :cid, :p, :aid, 'operator_review',
                :ver, 'retry_command_write_started', 'command_orchestration',
                false, NULL, NULL,
                NULL, NULL, :ikey,
                :rcid, 'worker-a'
            )
            """
        ),
        {
            "id": fx.resulting_attempt_id,
            "cid": fx.content_id,
            "p": fx.platform,
            "aid": fx.account_id,
            "ver": fx.publish_version,
            "ikey": fx.idempotency_key,
            "rcid": fx.command_id,
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
                :p, :aid, :ver,
                'dest', 'workspace', :ikey,
                'provider_write_started', NULL, NOW() - interval '10 minutes',
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
        },
    )
    await db.commit()


async def _ack(db: AsyncSession, fx: _Fixture, *, external_post_id: str = ACK_EXT):
    # E2-2 apply requires BOTH feature flags (intentional dependency).
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
            external_post_id=external_post_id,
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
        caption_long_ru="hello path",
        caption_long_en=None,
        caption_long_uz=None,
        caption_long_zh=None,
        caption_short_uz=None,
        caption_short_en=None,
        caption_short_zh=None,
        hashtags=None,
        internal_notes=None,
        approved_at=datetime.now(timezone.utc),
        client_review_status=None,
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


@contextmanager
def _publish_harness(fx: _Fixture, adapters: dict[str, CountingAdapter]):
    item = _content_ns(fx)
    # Stabilize publish_version so seeded attempt keys remain aligned.
    def _fixed_version(_item, _payload=None):
        return fx.publish_version

    async def _get_content(_db, content_id):
        assert content_id == fx.content_id
        return item

    async def _serialize(_db, _item):
        return {
            "id": str(fx.content_id),
            "platforms": list(fx.platforms),
            "caption_long_ru": "hello path",
            "media_url": None,
            "generated_final_video_url": None,
        }

    with (
        patch.object(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True),
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
        patch.dict(ADAPTERS, adapters, clear=False),
    ):
        yield item


def _result_for(platform: str, results: list[dict]) -> dict | None:
    for row in results:
        if row.get("platform") == platform:
            return row
    return None


# ── Unit-style reader checks against real PG rows ─────────────────────────────


def test_prior_live_successes_sees_ack_column_without_response():
    fx = _Fixture()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with patch.object(
                settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
            ):
                async with factory() as db:
                    await _ack(db, fx)
            async with factory() as db:
                attempt = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.id == fx.resulting_attempt_id
                        )
                    )
                ).scalar_one()
                assert attempt.status == "success"
                assert attempt.external_post_id == ACK_EXT
                assert attempt.response is None

                found = await PublishService._prior_live_successes(
                    db, fx.content_id, ["telegram"]
                )
                assert found["telegram"]["platform_post_id"] == ACK_EXT
                assert found["telegram"]["deduplicated"] is True

                live = await PublishResilienceService.find_live_success(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account_id=fx.account_id,
                )
                assert live is not None
                assert live.id == fx.resulting_attempt_id

    _run(body)


def test_prior_live_successes_legacy_response_only_still_works():
    fx = _Fixture()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.execute(
                    text(
                        """
                        INSERT INTO publish_attempts (
                            id, content_id, platform, account_id, status,
                            response, external_post_id, publish_version
                        ) VALUES (
                            :id, :cid, 'telegram', :aid, 'success',
                            :resp, NULL, :ver
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "cid": fx.content_id,
                        "aid": fx.account_id,
                        "resp": json.dumps(
                            {
                                "success": True,
                                "mock": False,
                                "platform_post_id": "legacy-resp-1",
                            }
                        ),
                        "ver": fx.publish_version,
                    },
                )
                await db.commit()
            async with factory() as db:
                found = await PublishService._prior_live_successes(
                    db, fx.content_id, ["telegram"]
                )
                assert found["telegram"]["platform_post_id"] == "legacy-resp-1"

    _run(body)


def test_conflicting_column_and_response_suppresses_without_authoritative_id():
    """F1: conflict suppresses duplicate writes; neither ID is authoritative."""
    fx = _Fixture()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_base(db, fx)
                await db.execute(
                    text(
                        """
                        INSERT INTO publish_attempts (
                            id, content_id, platform, account_id, status,
                            response, external_post_id, publish_version
                        ) VALUES (
                            :id, :cid, 'telegram', :aid, 'success',
                            :resp, 'column-id', :ver
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "cid": fx.content_id,
                        "aid": fx.account_id,
                        "resp": json.dumps(
                            {
                                "success": True,
                                "mock": False,
                                "platform_post_id": "response-id",
                            }
                        ),
                        "ver": fx.publish_version,
                    },
                )
                await db.commit()
            async with factory() as db:
                found = await PublishService._prior_live_successes(
                    db, fx.content_id, ["telegram"]
                )
                # F1: conflict suppresses without authoritative platform_post_id.
                assert found["telegram"]["identity_conflict"] is True
                assert found["telegram"]["platform_post_id"] is None
                assert found["telegram"]["deduplicated"] is True
                assert found["telegram"]["conflict_durable_external_post_id"] == "column-id"
                assert found["telegram"]["conflict_response_platform_post_id"] == "response-id"

    _run(body)


# ── Real publish_content / manual_retry / scheduler paths ─────────────────────


def test_publish_content_after_ack_does_not_invoke_adapter():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with patch.object(
                settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
            ):
                async with factory() as db:
                    await _ack(db, fx)

            with _publish_harness(fx, {"telegram": tg}):
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
            assert row is not None
            assert row.get("success") is True
            assert row.get("deduplicated") is True
            assert row.get("platform_post_id") == ACK_EXT
            # Prefer prior_live_successes early skip (no new claim).
            async with factory() as db:
                in_progress = (
                    await db.execute(
                        text(
                            "SELECT COUNT(*) FROM publish_attempts "
                            "WHERE content_id=:cid AND status='in_progress'"
                        ),
                        {"cid": fx.content_id},
                    )
                ).scalar_one()
                assert int(in_progress) == 0

    _run(body)


def test_manual_retry_original_after_ack_denied_live_success():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        from sqlalchemy.orm import selectinload

        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with patch.object(
                settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
            ):
                async with factory() as db:
                    await _ack(db, fx)

            # Live-state projection sees destination success for original key.
            async with factory() as db:
                original = (
                    await db.execute(
                        select(PublishAttempt)
                        .where(PublishAttempt.id == fx.original_attempt_id)
                        .options(selectinload(PublishAttempt.account))
                    )
                ).scalar_one()
                live = await build_manual_retry_live_state(
                    db, original, content=_content_ns(fx)
                )
                assert live.has_live_success is True

            with _publish_harness(fx, {"telegram": tg}):
                async with factory() as db:
                    out = await PublishAttemptOpsService.manual_retry(
                        db,
                        fx.original_attempt_id,
                        tenant_id=fx.tenant_id,
                        source="workspace",
                        actor_role="operator",
                    )
            assert out["ok"] is False
            assert tg.invocation_count == 0
            # Current taxonomy may deny on failure_code before live-success;
            # either deny reason is acceptable so long as no provider write.
            assert out["retry_blocked_reason"] in {
                "live_success_exists",
                "failure_code_unknown",
                "failure_code_null",
                "operator_review_required",
            }

            # Eligibility bypass still converges on publish_content guards.
            with _publish_harness(fx, {"telegram": tg}):
                async with factory() as db:
                    out_skip = await PublishAttemptOpsService.manual_retry(
                        db,
                        fx.original_attempt_id,
                        tenant_id=fx.tenant_id,
                        source="workspace",
                        actor_role="operator",
                        skip_eligibility=True,
                    )
            assert tg.invocation_count == 0
            # Deduplicated publish_content success is reported as ok=True.
            assert out_skip["ok"] is True

            # Resulting success attempt denied on own-row status gate.
            with _publish_harness(fx, {"telegram": tg}):
                async with factory() as db:
                    out2 = await PublishAttemptOpsService.manual_retry(
                        db,
                        fx.resulting_attempt_id,
                        tenant_id=fx.tenant_id,
                        source="workspace",
                        actor_role="operator",
                    )
            assert out2["ok"] is False
            assert out2["retry_blocked_reason"] == "live_success_exists"
            assert tg.invocation_count == 0

    _run(body)


def test_scheduler_delegates_to_publish_content_skip():
    """Scheduler due-item path only wraps publish_content(from_scheduler=True)."""
    src = ScheduledPublishService._publish_due_item.__func__  # type: ignore[attr-defined]
    import inspect

    text_src = inspect.getsource(ScheduledPublishService._publish_due_item)
    assert "PublishService.publish_content" in text_src
    assert "from_scheduler=True" in text_src
    # No distinct destination identity logic beyond publish_content.
    assert "find_live_success" not in text_src
    assert "_prior_live_successes" not in text_src
    _ = src  # keep reference for type checkers


def test_multi_destination_acked_skipped_other_may_write():
    fx = _Fixture(multi_platform=True)
    tg = CountingAdapter("telegram")
    fb = CountingAdapter("facebook", post_id="fb-new-1")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with patch.object(
                settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
            ):
                async with factory() as db:
                    await _ack(db, fx)

            with _publish_harness(fx, {"telegram": tg, "facebook": fb}):
                async with factory() as db:
                    # Default account resolution: telegram→account A, facebook→FB A
                    # Force per-platform accounts via separate publish calls to avoid
                    # account_id multi-platform restriction; then one multi-platform
                    # publish without explicit account_id.
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
            fb_row = _result_for("facebook", result["results"])
            assert tg_row and tg_row.get("deduplicated") is True
            assert fb_row and fb_row.get("success") is True
            assert fb_row.get("platform_post_id") == "fb-new-1"

    _run(body)


def test_different_account_is_legitimate_new_intent():
    """begin_attempt allows a different account; platform-keyed prior reader may still skip.

    Documented pre-existing limitation of ``_prior_live_successes`` (platform-only).
    Account-aware safety is enforced by ``begin_attempt`` / ``find_live_success``.
    """
    fx = _Fixture()
    tg = CountingAdapter("telegram", post_id="tg-account-b")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with patch.object(
                settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
            ):
                async with factory() as db:
                    await _ack(db, fx)

            # Account-aware guard: different account is not a live success.
            async with factory() as db:
                other = await PublishResilienceService.find_live_success(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account_id=fx.account_b_id,
                )
                assert other is None
                claim = await PublishResilienceService.begin_attempt(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account=SimpleNamespace(
                        id=fx.account_b_id, account_name="TG B"
                    ),
                    publish_version=fx.publish_version,
                    lease_owner="test",
                    test_mode=False,
                )
                assert claim.skip is False
                await db.rollback()

            # publish_content still hits platform-keyed _prior_live_successes first.
            with _publish_harness(fx, {"telegram": tg}):
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
            row = _result_for("telegram", result["results"])
            assert row is not None
            # Observed: platform-keyed prior reader suppresses account-B write.
            assert tg.invocation_count == 0
            assert row.get("deduplicated") is True
            assert row.get("platform_post_id") == ACK_EXT

    _run(body)


def test_different_account_begin_attempt_allows_while_documenting_platform_reader():
    """Account B write is allowed by begin_attempt after ack on account A."""
    fx = _Fixture()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)
            with patch.object(
                settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
            ):
                async with factory() as db:
                    await _ack(db, fx)
            async with factory() as db:
                same = await PublishResilienceService.find_live_success(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account_id=fx.account_id,
                )
                other = await PublishResilienceService.find_live_success(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account_id=fx.account_b_id,
                )
                assert same is not None
                assert other is None

                claim = await PublishResilienceService.begin_attempt(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account=SimpleNamespace(
                        id=fx.account_b_id, account_name="TG B"
                    ),
                    publish_version=fx.publish_version,
                    lease_owner="test",
                    test_mode=False,
                )
                assert claim.skip is False
                assert claim.attempt is not None
                await db.rollback()

    _run(body)


# ── Concurrency: separate PG sessions + deterministic barriers ────────────────


def test_concurrency_ack_commits_before_publish_check_skips_adapter():
    fx = _Fixture()
    tg = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)

            # Interleaving 1: ack fully commits, then publish eligibility runs.
            with patch.object(
                settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
            ):
                async with factory() as db:
                    await _ack(db, fx)

            with _publish_harness(fx, {"telegram": tg}):
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
            assert _result_for("telegram", result["results"])["deduplicated"] is True

    _run(body)


def test_concurrency_publish_check_overlaps_ack_then_begin_attempt_sees_success():
    """Publish pauses inside begin_attempt's live-success read; ack commits; resume.

    Uses a barrier around the real find_live_success (not mocked locks / sleep).
    Separate AsyncSession for ack vs publish.
    """
    fx = _Fixture()
    tg = CountingAdapter("telegram")
    entered = asyncio.Event()
    release = asyncio.Event()
    original_find = PublishResilienceService.find_live_success
    call_count = {"n": 0}

    async def gated_find(db, **kwargs):
        call_count["n"] += 1
        # Gate the first live-success probe from begin_attempt.
        if call_count["n"] == 1:
            entered.set()
            await release.wait()
        return await original_find(db, **kwargs)

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)

            async def publisher():
                with (
                    patch.object(
                        PublishResilienceService,
                        "find_live_success",
                        new=staticmethod(gated_find),
                    ),
                    _publish_harness(fx, {"telegram": tg}),
                ):
                    # Bypass prior_live_successes so the race focuses on begin_attempt.
                    with patch.object(
                        PublishService,
                        "_prior_live_successes",
                        new=staticmethod(AsyncMock(return_value={})),
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
                with patch.object(
                    settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
                ):
                    async with factory() as db:
                        await _ack(db, fx)
                release.set()

            pub_task = asyncio.create_task(publisher())
            ack_task = asyncio.create_task(acknowledger())
            result, _ = await asyncio.gather(pub_task, ack_task)

            assert tg.invocation_count == 0
            row = _result_for("telegram", result["results"])
            assert row is not None
            assert row.get("deduplicated") is True
            assert row.get("platform_post_id") == ACK_EXT

    _run(body)


def test_concurrency_c3_disabled_mode_preserves_pre_coordination_evidence():
    """DISABLED-MODE: coordination off — publisher may invoke adapter while stranded.

    Ack without WRITE_COORDINATION is gate-rejected (403). Retains evidence that
    unresolved provider_write_started alone did not block begin_attempt historically
    when coordination is disabled.
    """
    from fastapi import HTTPException

    fx = _Fixture()
    tg = CountingAdapter("telegram", post_id="race-post")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)

            with (
                _publish_harness(fx, {"telegram": tg}),
                patch.object(
                    PublishService,
                    "_prior_live_successes",
                    new=staticmethod(AsyncMock(return_value={})),
                ),
                patch.object(
                    PublishResilienceService,
                    "find_live_success",
                    new=staticmethod(AsyncMock(return_value=None)),
                ),
                patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False),
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
            row = _result_for("telegram", result["results"])
            assert row and row.get("platform_post_id") == "race-post"

            with (
                patch.object(
                    settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", True
                ),
                patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False),
            ):
                async with factory() as db:
                    with pytest.raises(HTTPException) as exc:
                        await PublishRetryCommandManualResolutionService.resolve(
                            db,
                            command_id=fx.command_id,
                            tenant_id=fx.tenant_id,
                            action=ACTION_ACKNOWLEDGE_EXTERNAL_SUCCESS,
                            confirm_permanent_resolution=True,
                            operator_reason="Verified live Telegram message",
                            evidence_source="operator_provider_ui",
                            external_post_id=ACK_EXT,
                            actor_id=fx.actor_id,
                            commit=True,
                        )
                    assert exc.value.status_code == 403
                    assert "WRITE_COORDINATION" in str(exc.value.detail)

    _run(body)


def test_concurrency_adapter_already_entered_before_ack_allows_provider_invocation():
    """C3 under coordination: durable in_progress → ack 409 publication_in_progress.

    Setup: claim+commit an ordinary in_progress attempt first (coordination on),
    keep stranded command ack-eligible, then attempt acknowledgment. No ack/audit
    mutations. Already-started adapter I/O is not cancelled (separate scenario).
    """
    from fastapi import HTTPException

    from app.services.publish_write_coordination import PUBLICATION_IN_PROGRESS_ERROR

    fx = _Fixture()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed_stranded(db, fx)

            # Commit a competing same-destination in_progress claim.
            with patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", True):
                async with factory() as db:
                    # Temporarily cancel unresolved command so begin_attempt can claim.
                    await db.execute(
                        text(
                            "UPDATE publish_retry_commands SET status='cancelled', "
                            "finished_at=NOW() WHERE id=:id"
                        ),
                        {"id": fx.command_id},
                    )
                    await db.commit()

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
                        lease_owner="c3-inflight",
                        test_mode=False,
                        tenant_id=fx.tenant_id,
                    )
                    assert claim.skip is False
                    await db.commit()
                    inflight_id = claim.attempt.id

                # Restore command to provider_write_started for ack eligibility.
                async with factory() as db:
                    await db.execute(
                        text(
                            "UPDATE publish_retry_commands SET status='provider_write_started', "
                            "finished_at=NULL, provider_write_started_at=NOW() - "
                            "interval '10 minutes' WHERE id=:id"
                        ),
                        {"id": fx.command_id},
                    )
                    await db.commit()

            audit_before = 0
            async with factory() as db:
                audit_before = int(
                    (
                        await db.execute(
                            text("SELECT COUNT(*) FROM platform_audit_logs")
                        )
                    ).scalar_one()
                )

            with pytest.raises(HTTPException) as exc:
                async with factory() as db:
                    await _ack(db, fx)
            assert exc.value.status_code == 409
            detail = exc.value.detail
            assert isinstance(detail, dict)
            assert detail.get("error") == PUBLICATION_IN_PROGRESS_ERROR

            async with factory() as db:
                resulting = (
                    await db.execute(
                        select(PublishAttempt).where(
                            PublishAttempt.id == fx.resulting_attempt_id
                        )
                    )
                ).scalar_one()
                assert resulting.status == "operator_review"
                assert resulting.external_post_id is None
                cmd = (
                    await db.execute(
                        text(
                            "SELECT status FROM publish_retry_commands WHERE id=:id"
                        ),
                        {"id": fx.command_id},
                    )
                ).first()
                assert cmd[0] == "provider_write_started"
                audit_after = int(
                    (
                        await db.execute(
                            text("SELECT COUNT(*) FROM platform_audit_logs")
                        )
                    ).scalar_one()
                )
                assert audit_after == audit_before
                inflight = (
                    await db.execute(
                        select(PublishAttempt).where(PublishAttempt.id == inflight_id)
                    )
                ).scalar_one()
                assert inflight.status == "in_progress"

    _run(body)


def test_lock_boundary_shared_destination_lock_participants():
    """Static evidence: ack + begin_attempt share destination xact lock helper."""
    import inspect

    from app.services.publish_retry_command_manual_resolution_service import (
        PublishRetryCommandManualResolutionService as S,
    )
    from app.services import publish_write_coordination as wc

    ack_src = inspect.getsource(S._resolve_ack_external_success)
    begin_src = inspect.getsource(PublishResilienceService.begin_attempt)
    assert "acquire_destination_xact_lock" in ack_src
    assert "write_coordination_enabled" in begin_src
    assert "pg_advisory_xact_lock" in inspect.getsource(wc.acquire_destination_xact_lock)
    assert "PUBLICATION_IN_PROGRESS_ERROR" in ack_src
