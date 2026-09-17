"""Isolated PostgreSQL fixtures for schema modes A / B / C.

Schema shape mirrors the proven E2-2 path fixture so ORM loads during
publish_content succeed without touching production.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .isolation import prove_isolation, resolve_pg_url


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


async def ensure_database(url: str | None = None) -> str:
    url = url or resolve_pg_url()
    proof = prove_isolation(url)
    if not proof.ok:
        raise RuntimeError(f"F4 isolation proof failed: {proof.failures}")

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
        pytest.skip(f"PostgreSQL unavailable for F4 harness: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for F4 harness: {exc}")
        raise
    finally:
        await engine.dispose()
    return url


def _publish_attempts_ddl(*, with_intent: bool) -> str:
    intent_col = "publication_intent_id UUID NULL," if with_intent else ""
    return f"""
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
            {intent_col}
            CONSTRAINT chk_placeholder CHECK (true)
        )
    """


async def setup_schema(engine, *, mode: str) -> None:
    """Schema modes:

    A_historical — pre-R1 (no publication_intent_id, no registry table)
    B_old_on_r1 / C_new_on_r1 — R1-compatible (nullable intent + empty registry)
    """
    with_intent = mode != "A_historical"
    with_registry = mode != "A_historical"

    async with engine.begin() as conn:
        for table in (
            "platform_audit_logs",
            "publish_operator_alerts",
            "tenant_external_publications",
            "publish_write_coordination_registry",
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
                company_name VARCHAR(255) NULL,
                source_language VARCHAR(10) NULL,
                business_category VARCHAR(100) NULL,
                content_style VARCHAR(100) NULL,
                status VARCHAR(20) NULL DEFAULT 'active',
                notes TEXT NULL,
                brand_name VARCHAR(255) NULL,
                business_description TEXT NULL,
                products_services TEXT NULL,
                target_audience TEXT NULL,
                tone_of_voice VARCHAR(100) NULL,
                preferred_languages TEXT NULL,
                cta_phone VARCHAR(50) NULL,
                cta_telegram VARCHAR(100) NULL,
                cta_website VARCHAR(255) NULL,
                cta_address TEXT NULL,
                words_to_avoid TEXT NULL,
                hashtag_preferences TEXT NULL,
                logo_url TEXT NULL,
                telegram_id VARCHAR(100) NULL,
                telegram_group_id VARCHAR(100) NULL,
                telegram_group_title VARCHAR(255) NULL,
                telegram_publish_chat_id VARCHAR(255) NULL,
                telegram_publish_title VARCHAR(255) NULL,
                telegram_publish_type VARCHAR(50) NULL,
                telegram_workflow_mode VARCHAR(50) NULL,
                operator_auto_draft_enabled BOOLEAN NULL DEFAULT false,
                auto_publish_after_client_approval BOOLEAN NULL DEFAULT false,
                telegram_active_content_id UUID NULL,
                plan_name VARCHAR(50) NULL,
                monthly_fee NUMERIC NULL,
                monthly_post_limit INTEGER NULL,
                billing_status VARCHAR(30) NULL,
                billing_cycle_start TIMESTAMPTZ NULL,
                billing_cycle_end TIMESTAMPTZ NULL,
                tenant_id UUID NULL,
                created_at TIMESTAMPTZ NULL,
                updated_at TIMESTAMPTZ NULL
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
        await conn.execute(text(_publish_attempts_ddl(with_intent=with_intent)))
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
                idempotency_key VARCHAR(220) NOT NULL DEFAULT '',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                reason_code VARCHAR(80) NULL,
                provider_outcome VARCHAR(40) NULL,
                lease_owner VARCHAR(120) NULL,
                lease_expires_at TIMESTAMPTZ NULL,
                claimed_at TIMESTAMPTZ NULL,
                started_at TIMESTAMPTZ NULL,
                provider_write_started_at TIMESTAMPTZ NULL,
                finished_at TIMESTAMPTZ NULL,
                correlation_id VARCHAR(64) NOT NULL DEFAULT 'f4',
                publication_intent_id UUID NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE platform_audit_logs (
                id UUID PRIMARY KEY,
                actor_type VARCHAR(20) NOT NULL DEFAULT 'system',
                actor_id UUID NULL,
                tenant_id UUID NULL,
                event_type VARCHAR(80) NOT NULL,
                resource_type VARCHAR(50) NULL,
                resource_id VARCHAR(100) NULL,
                details JSONB NULL,
                payload_json TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE publish_operator_alerts (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                dedupe_key VARCHAR(320) NOT NULL DEFAULT 'f4',
                alert_type VARCHAR(80) NOT NULL,
                state VARCHAR(20) NOT NULL DEFAULT 'open',
                severity VARCHAR(20) NOT NULL DEFAULT 'critical',
                title VARCHAR(255) NOT NULL DEFAULT 'f4',
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
                context_json TEXT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'open',
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
                content_id UUID NULL,
                platform VARCHAR(20) NULL,
                external_post_id VARCHAR(255) NULL,
                provider_publication_id VARCHAR(255) NULL
            )
        """))
        if with_registry:
            await conn.execute(text("""
                CREATE TABLE publish_write_coordination_registry (
                    id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL,
                    content_id UUID NOT NULL,
                    platform VARCHAR(20) NOT NULL,
                    account_id UUID NULL,
                    publication_intent_id UUID NULL,
                    logical_write_key VARCHAR(128) NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    state VARCHAR(40) NOT NULL DEFAULT 'IDLE',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))


@dataclass
class FixtureIds:
    tenant_id: Any
    other_tenant_id: Any
    client_id: Any
    content_id: Any
    account_id: Any
    account_b_id: Any
    account_alias_id: Any
    fb_account_id: Any
    fb_unknown_id: Any
    fb_unknown_b_id: Any
    publish_version: str = "pv_f4_v1"
    platform: str = "telegram"
    platforms: list[str] | None = None

    def __post_init__(self) -> None:
        if self.platforms is None:
            self.platforms = [self.platform]


def new_fixture_ids() -> FixtureIds:
    return FixtureIds(
        tenant_id=uuid4(),
        other_tenant_id=uuid4(),
        client_id=uuid4(),
        content_id=uuid4(),
        account_id=uuid4(),
        account_b_id=uuid4(),
        account_alias_id=uuid4(),
        fb_account_id=uuid4(),
        fb_unknown_id=uuid4(),
        fb_unknown_b_id=uuid4(),
    )


async def seed_base(
    db: AsyncSession, fx: FixtureIds, *, platforms: list[str] | None = None
) -> None:
    plats = platforms or fx.platforms or [fx.platform]
    fx.platforms = list(plats)
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
                id, client_id, platforms, status, caption_long_ru, approved_at
            ) VALUES (
                :id, :cid, :plats, 'failed', 'f4 hello', :ts
            )
            """
        ),
        {
            "id": fx.content_id,
            "cid": fx.client_id,
            "plats": plats,
            "ts": datetime.now(timezone.utc),
        },
    )
    # Alias shares telegram chat id with A (same external destination, new UUID).
    # FB unknown rows omit facebook_page_id so external identity is unresolved.
    for aid, plat, name, ext, page in (
        (fx.account_id, "telegram", "TG A", "tg-a", None),
        (fx.account_b_id, "telegram", "TG B", "tg-b", None),
        (fx.account_alias_id, "telegram", "TG A alias", "tg-a", None),
        (fx.fb_account_id, "facebook", "FB A", "fb-a", "page-a"),
        (fx.fb_unknown_id, "facebook", "FB unknown", "fb-handle", None),
        (fx.fb_unknown_b_id, "facebook", "FB unknown B", "fb-handle-b", None),
    ):
        await db.execute(
            text(
                """
                INSERT INTO publishing_accounts
                    (id, tenant_id, platform, account_name, account_id, status,
                     facebook_page_id)
                VALUES (:id, :tid, :p, :n, :ext, 'mock', :page)
                """
            ),
            {
                "id": aid,
                "tid": fx.tenant_id,
                "p": plat,
                "n": name,
                "ext": ext,
                "page": page,
            },
        )
    await db.commit()


async def insert_success_attempt(
    db: AsyncSession,
    fx: FixtureIds,
    *,
    platform: str | None = None,
    account_id: Any = ...,
    external_post_id: str | None = None,
    response: dict | None = None,
    publication_intent_id=None,
    with_intent_column: bool = True,
    publish_version: str | None = None,
) -> Any:
    """Insert a success attempt.

    ``account_id=...`` (default) uses ``fx.account_id``.
    Pass ``account_id=None`` explicitly for historical NULL identity rows.
    """
    attempt_id = uuid4()
    plat = platform or fx.platform
    cols = [
        "id",
        "content_id",
        "platform",
        "account_id",
        "status",
        "response",
        "external_post_id",
        "publish_version",
    ]
    vals = [
        ":id",
        ":cid",
        ":p",
        ":aid",
        "'success'",
        ":resp",
        ":ext",
        ":ver",
    ]
    params: dict[str, Any] = {
        "id": attempt_id,
        "cid": fx.content_id,
        "p": plat,
        "aid": fx.account_id if account_id is ... else account_id,
        "resp": json.dumps(response) if response is not None else None,
        "ext": external_post_id,
        "ver": publish_version or fx.publish_version,
    }
    if with_intent_column:
        cols.append("publication_intent_id")
        vals.append(":intent")
        # Historical NULL must remain NULL — never fabricate.
        params["intent"] = publication_intent_id
    await db.execute(
        text(
            f"INSERT INTO publish_attempts ({', '.join(cols)}) "
            f"VALUES ({', '.join(vals)})"
        ),
        params,
    )
    await db.commit()
    return attempt_id


async def registry_count(db: AsyncSession) -> int:
    try:
        return int(
            (
                await db.execute(
                    text("SELECT COUNT(*) FROM publish_write_coordination_registry")
                )
            ).scalar_one()
        )
    except Exception:  # noqa: BLE001
        return 0


async def null_intent_count(db: AsyncSession) -> int | None:
    try:
        return int(
            (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM publish_attempts "
                        "WHERE publication_intent_id IS NULL"
                    )
                )
            ).scalar_one()
        )
    except Exception:  # noqa: BLE001
        return None


@asynccontextmanager
async def session_factory(mode: str = "C_new_on_r1") -> AsyncIterator[async_sessionmaker]:
    url = await ensure_database()
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await setup_schema(engine, mode=mode)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        yield factory
    except OSError as exc:
        pytest.skip(f"PostgreSQL F4 DB unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL F4 DB unavailable: {exc}")
        raise
    finally:
        await engine.dispose()


def run_async(coro_factory) -> None:
    asyncio.run(coro_factory())
