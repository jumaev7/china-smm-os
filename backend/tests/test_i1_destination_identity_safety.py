"""I1 — account-aware publication destination safety.

Isolated PostgreSQL + counting mocked adapters. No real provider I/O,
no flag enablement, no registry authority, no intent minting.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.schemas.publishing import PublishContentRequest
from app.services.publish_destination_identity import (
    PROVEN_DISTINCT_DESTINATION,
    SAME_DESTINATION,
    UNRESOLVED_DESTINATION,
    compare_publication_destinations,
    extract_external_destination,
)
from app.services.publish_resilience import PublishResilienceService
from app.services.publish_service import ADAPTERS, PublishService

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/"
    "i1_destination_identity_safety_test"
)


def _pg_url() -> str:
    return os.environ.get("I1_DESTINATION_PG_URL", DEFAULT_PG_URL)


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
        pytest.skip(f"PostgreSQL unavailable for I1 tests: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for I1 tests: {exc}")
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
                company_name VARCHAR(255) NOT NULL DEFAULT 't'
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
                platforms TEXT[] NOT NULL DEFAULT '{}',
                status VARCHAR(30) NOT NULL DEFAULT 'failed',
                caption_long_ru TEXT NULL,
                approved_at TIMESTAMPTZ NULL,
                published_at TIMESTAMPTZ NULL,
                internal_notes TEXT NULL,
                client_review_status VARCHAR(30) NULL,
                updated_at TIMESTAMPTZ NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NULL DEFAULT NOW(),
                media_file_id UUID NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'manual'
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
            CREATE TABLE publish_write_coordination_registry (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                content_id UUID NOT NULL,
                platform VARCHAR(20) NOT NULL,
                account_id UUID NULL,
                logical_write_key VARCHAR(220) NOT NULL,
                generation INTEGER NOT NULL DEFAULT 1,
                version INTEGER NOT NULL DEFAULT 1,
                state VARCHAR(40) NOT NULL DEFAULT 'open',
                publication_intent_id UUID NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE TABLE platform_audit_logs (
                id UUID PRIMARY KEY,
                actor_type VARCHAR(20) NOT NULL DEFAULT 'system',
                event_type VARCHAR(80) NOT NULL,
                details JSONB NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
        pytest.skip(f"PostgreSQL I1 test DB unavailable: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL I1 test DB unavailable: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(coro_factory())


class _Fx:
    def __init__(self) -> None:
        self.tenant_id = uuid4()
        self.other_tenant_id = uuid4()
        self.client_id = uuid4()
        self.content_id = uuid4()
        self.other_content_id = uuid4()
        self.account_a = uuid4()
        self.account_b = uuid4()
        self.account_alias = uuid4()
        self.account_unknown = uuid4()
        self.fb_a = uuid4()
        self.fb_b = uuid4()
        self.publish_version = "pv_i1_v1"
        self.platforms = ["telegram"]


class CountingAdapter:
    def __init__(self, platform: str, post_id: str = "i1-post"):
        self.platform = platform
        self.post_id = post_id
        self.invocation_count = 0

    async def __call__(self, ctx) -> dict:
        self.invocation_count += 1
        return {
            "platform": self.platform,
            "success": True,
            "platform_post_id": self.post_id,
            "post_url": None,
            "mock": False,
        }


async def _seed(db: AsyncSession, fx: _Fx, *, with_fb: bool = False) -> None:
    plats = ["telegram", "facebook"] if with_fb else ["telegram"]
    fx.platforms = plats
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
            INSERT INTO content_items
                (id, client_id, platforms, status, caption_long_ru, approved_at)
            VALUES (:id, :cid, :p, 'failed', 'i1 hello', NOW())
            """
        ),
        {"id": fx.content_id, "cid": fx.client_id, "p": plats},
    )
    await db.execute(
        text(
            """
            INSERT INTO content_items
                (id, client_id, platforms, status, caption_long_ru, approved_at)
            VALUES (:id, :cid, :p, 'failed', 'other', NOW())
            """
        ),
        {"id": fx.other_content_id, "cid": fx.client_id, "p": plats},
    )
    rows = [
        (fx.account_a, "telegram", "TG A", "tg-a", None, None),
        (fx.account_b, "telegram", "TG B", "tg-b", None, None),
        # Alias of A — same telegram chat under a different UUID.
        (fx.account_alias, "telegram", "TG A alias", "tg-a", None, None),
        # Facebook pages without facebook_page_id → external identity unknown.
        (fx.account_unknown, "facebook", "FB unknown", "fb-handle", None, None),
        (fx.fb_a, "facebook", "FB A", "fb-a", "page-a", None),
        (fx.fb_b, "facebook", "FB B", "fb-b", "page-b", None),
    ]
    for aid, plat, name, ext, page, ig in rows:
        await db.execute(
            text(
                """
                INSERT INTO publishing_accounts
                    (id, tenant_id, platform, account_name, account_id, status,
                     facebook_page_id, instagram_business_account_id)
                VALUES (:id, :tid, :p, :n, :ext, 'mock', :page, :ig)
                """
            ),
            {
                "id": aid,
                "tid": fx.tenant_id,
                "p": plat,
                "n": name,
                "ext": ext,
                "page": page,
                "ig": ig,
            },
        )
    await db.commit()


async def _insert_success(
    db: AsyncSession,
    fx: _Fx,
    *,
    account_id=...,
    content_id=None,
    platform: str = "telegram",
    external_post_id: str = "ext-1",
    response: dict | None = None,
    publication_intent_id=None,
) -> None:
    if account_id is ...:
        account_id = fx.account_a
    resp = response
    if resp is None:
        resp = {"success": True, "mock": False, "platform_post_id": external_post_id}
    await db.execute(
        text(
            """
            INSERT INTO publish_attempts (
                id, content_id, platform, account_id, status,
                response, external_post_id, publish_version, publication_intent_id
            ) VALUES (
                :id, :cid, :p, :aid, 'success',
                :resp, :ext, :ver, :intent
            )
            """
        ),
        {
            "id": uuid4(),
            "cid": content_id or fx.content_id,
            "p": platform,
            "aid": account_id,
            "resp": json.dumps(resp) if resp is not None else None,
            "ext": external_post_id,
            "ver": fx.publish_version,
            "intent": publication_intent_id,
        },
    )
    await db.commit()


def _content_ns(fx: _Fx):
    return SimpleNamespace(
        id=fx.content_id,
        client_id=fx.client_id,
        media_file_id=None,
        media_file=None,
        platforms=list(fx.platforms),
        status="failed",
        source="manual",
        caption_short_ru=None,
        caption_long_ru="i1 hello",
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
def _publish_harness(fx: _Fx, adapters: dict[str, CountingAdapter]):
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
            "caption_long_ru": "i1 hello",
            "media_url": None,
            "generated_final_video_url": None,
        }

    with (
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
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False),
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_SHADOW", False),
        patch.object(settings, "SCHEDULED_PUBLISH_ENABLED", False),
        patch.dict(ADAPTERS, adapters, clear=False),
    ):
        yield item


def _row(platform: str, results: list[dict]) -> dict | None:
    for r in results:
        if r.get("platform") == platform:
            return r
    return None


# ── Pure identity unit checks ─────────────────────────────────────────────────


def test_compare_same_uuid_and_alias_and_distinct():
    a = SimpleNamespace(
        id=uuid4(),
        platform="telegram",
        account_id="tg-a",
        facebook_page_id=None,
        instagram_business_account_id=None,
    )
    b = SimpleNamespace(
        id=uuid4(),
        platform="telegram",
        account_id="tg-b",
        facebook_page_id=None,
        instagram_business_account_id=None,
    )
    alias = SimpleNamespace(
        id=uuid4(),
        platform="telegram",
        account_id="tg-a",
        facebook_page_id=None,
        instagram_business_account_id=None,
    )
    assert (
        compare_publication_destinations(
            platform="telegram",
            intended_account_id=a.id,
            intended_account=a,
            prior_account_id=a.id,
            prior_account=a,
        )
        == SAME_DESTINATION
    )
    assert (
        compare_publication_destinations(
            platform="telegram",
            intended_account_id=b.id,
            intended_account=b,
            prior_account_id=a.id,
            prior_account=a,
        )
        == PROVEN_DISTINCT_DESTINATION
    )
    assert (
        compare_publication_destinations(
            platform="telegram",
            intended_account_id=alias.id,
            intended_account=alias,
            prior_account_id=a.id,
            prior_account=a,
        )
        == SAME_DESTINATION
    )
    assert (
        compare_publication_destinations(
            platform="telegram",
            intended_account_id=a.id,
            intended_account=a,
            prior_account_id=None,
            prior_account=None,
        )
        == UNRESOLVED_DESTINATION
    )
    fb = SimpleNamespace(
        id=uuid4(),
        platform="facebook",
        account_id="handle",
        facebook_page_id=None,
        instagram_business_account_id=None,
    )
    assert extract_external_destination(fb) is None
    assert (
        compare_publication_destinations(
            platform="facebook",
            intended_account_id=fb.id,
            intended_account=fb,
            prior_account_id=uuid4(),
            prior_account=fb,
        )
        == UNRESOLVED_DESTINATION
    )


# ── A–S behavioral scenarios ──────────────────────────────────────────────────


def test_a_proven_distinct_cross_account_allows_one_write():
    fx = _Fx()
    adapter = CountingAdapter("telegram", post_id="b-post")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=fx.account_a, external_post_id="a-post")
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_b,
                        ),
                    )
            row = _row("telegram", result["results"])
            assert adapter.invocation_count == 1
            assert row and row.get("success") is True
            assert row.get("platform_post_id") == "b-post"
            assert row.get("deduplicated") is not True

    _run(body)


def test_b_same_destination_repeated_zero_writes():
    fx = _Fx()
    adapter = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=fx.account_a)
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
            row = _row("telegram", result["results"])
            assert adapter.invocation_count == 0
            assert row and row.get("deduplicated") is True

    _run(body)


def test_c_alias_same_external_destination_zero_writes():
    fx = _Fx()
    adapter = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=fx.account_a)
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_alias,
                        ),
                    )
            row = _row("telegram", result["results"])
            assert adapter.invocation_count == 0
            assert row and (
                row.get("deduplicated") is True
                or row.get("failure_code") == "destination_identity_unresolved"
            )
            # Alias is proven SAME via telegram chat id.
            assert row.get("deduplicated") is True

    _run(body)


def test_d_unknown_external_identity_zero_writes():
    fx = _Fx()
    adapter = CountingAdapter("facebook", post_id="should-not")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx, with_fb=True)
                other = uuid4()
                await db.execute(
                    text(
                        """
                        INSERT INTO publishing_accounts
                            (id, tenant_id, platform, account_name, account_id,
                             status, facebook_page_id)
                        VALUES (:id, :tid, 'facebook', 'FB X', 'x', 'mock', NULL)
                        """
                    ),
                    {"id": other, "tid": fx.tenant_id},
                )
                await db.commit()
                await _insert_success(
                    db,
                    fx,
                    account_id=fx.account_unknown,
                    platform="facebook",
                    external_post_id="fb-unk",
                )
            with _publish_harness(fx, {"facebook": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["facebook"],
                            account_id=other,
                        ),
                    )
            row = _row("facebook", result["results"])
            assert adapter.invocation_count == 0
            assert row and row.get("failure_code") == "destination_identity_unresolved"

    _run(body)


def test_e_null_historical_plus_concrete_unresolved_zero_writes():
    fx = _Fx()
    adapter = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=None, external_post_id="null-hist")
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
            row = _row("telegram", result["results"])
            assert adapter.invocation_count == 0
            assert row and row.get("failure_code") == "destination_identity_unresolved"
            assert row.get("success") is False

    _run(body)


def test_f_historical_null_exact_destination_suppresses():
    fx = _Fx()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=None, external_post_id="null-exact")
                found = await PublishService._prior_live_successes(
                    db, fx.content_id, ["telegram"], account=None
                )
                assert "telegram" in found
                assert found["telegram"]["platform_post_id"] == "null-exact"
                assert found["telegram"]["deduplicated"] is True

    _run(body)


def test_g_default_account_matches_prior_zero_writes():
    fx = _Fx()
    adapter = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                # Default resolver picks earliest created active account (A).
                await _insert_success(db, fx, account_id=fx.account_a)
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            # no explicit account_id → default resolve
                        ),
                    )
            row = _row("telegram", result["results"])
            assert adapter.invocation_count == 0
            assert row and row.get("deduplicated") is True

    _run(body)


def test_h_different_tenants_isolated():
    fx = _Fx()
    adapter = CountingAdapter("telegram", post_id="tenant-b")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=fx.account_a)
                # Other tenant content + account sharing platform name must not
                # be visible via content-scoped reader.
                other_client = uuid4()
                other_content = uuid4()
                other_account = uuid4()
                await db.execute(
                    text(
                        "INSERT INTO clients (id, tenant_id, company_name) "
                        "VALUES (:id, :tid, 'Other')"
                    ),
                    {"id": other_client, "tid": fx.other_tenant_id},
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO content_items
                            (id, client_id, platforms, status, approved_at)
                        VALUES (:id, :cid, '{telegram}', 'failed', NOW())
                        """
                    ),
                    {"id": other_content, "cid": other_client},
                )
                await db.execute(
                    text(
                        """
                        INSERT INTO publishing_accounts
                            (id, tenant_id, platform, account_name, account_id, status)
                        VALUES (:id, :tid, 'telegram', 'Other', 'tg-other', 'mock')
                        """
                    ),
                    {"id": other_account, "tid": fx.other_tenant_id},
                )
                await db.commit()
                found = await PublishService._prior_live_successes(
                    db, other_content, ["telegram"], account_id=other_account
                )
                assert found == {}

            # Publishing our content to B still works (distinct) and does not
            # leak other-tenant state.
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_b,
                        ),
                    )
            assert adapter.invocation_count == 1
            assert _row("telegram", result["results"])["success"] is True

    _run(body)


def test_i_same_platform_different_content_preserves_scoping():
    fx = _Fx()
    adapter = CountingAdapter("telegram", post_id="other-content")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(
                    db,
                    fx,
                    content_id=fx.other_content_id,
                    account_id=fx.account_a,
                    external_post_id="other-c",
                )
            # Harness is bound to fx.content_id — prior on other content must
            # not suppress.
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
            assert adapter.invocation_count == 1
            assert _row("telegram", result["results"])["platform_post_id"] == "other-content"

    _run(body)


def test_j_mock_prior_success_preserves_f1_eligibility():
    fx = _Fx()
    adapter = CountingAdapter("telegram", post_id="real-after-mock")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(
                    db,
                    fx,
                    account_id=fx.account_a,
                    external_post_id="mock-durable",
                    response={
                        "success": True,
                        "mock": True,
                        "platform_post_id": "mock-durable",
                    },
                )
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
            assert adapter.invocation_count == 1
            assert _row("telegram", result["results"])["platform_post_id"] == "real-after-mock"

    _run(body)


def test_k_durable_only_success_suppresses():
    fx = _Fx()
    adapter = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await db.execute(
                    text(
                        """
                        INSERT INTO publish_attempts (
                            id, content_id, platform, account_id, status,
                            response, external_post_id, publish_version
                        ) VALUES (
                            :id, :cid, 'telegram', :aid, 'success',
                            NULL, 'durable-only', :ver
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "cid": fx.content_id,
                        "aid": fx.account_a,
                        "ver": fx.publish_version,
                    },
                )
                await db.commit()
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
            row = _row("telegram", result["results"])
            assert adapter.invocation_count == 0
            assert row and row.get("platform_post_id") == "durable-only"
            assert row.get("deduplicated") is True

    _run(body)


def test_l_conflicting_provider_ids_suppress_with_conflict():
    fx = _Fx()
    adapter = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(
                    db,
                    fx,
                    account_id=fx.account_a,
                    external_post_id="column-id",
                    response={
                        "success": True,
                        "mock": False,
                        "platform_post_id": "response-id",
                    },
                )
            with (
                _publish_harness(fx, {"telegram": adapter}),
                patch(
                    "app.services.publish_service.notify_provider_identity_conflict",
                    new=AsyncMock(),
                ),
            ):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
            row = _row("telegram", result["results"])
            assert adapter.invocation_count == 0
            assert row and row.get("identity_conflict") is True
            assert row.get("platform_post_id") is None
            assert row.get("deduplicated") is True

    _run(body)


def test_m_n_ambiguous_and_duplicate_api_no_extra_write():
    """Duplicate API delivery → 0 provider writes on both requests."""
    fx = _Fx()
    adapter = CountingAdapter("telegram")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=fx.account_a)
            with _publish_harness(fx, {"telegram": adapter}) as item:
                async with factory() as db:
                    r1 = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
                # Harness content ns is mutated to published; reset for replay.
                item.status = "failed"
                async with factory() as db:
                    r2 = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
            assert adapter.invocation_count == 0
            assert _row("telegram", r1["results"]).get("deduplicated") is True
            assert _row("telegram", r2["results"]).get("deduplicated") is True

    _run(body)


def test_o_meta_early_commit_semantics_unchanged_source():
    src = open(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "app",
            "services",
            "publish_service.py",
        ),
        encoding="utf-8",
    ).read()
    assert "is_meta_publish_platform(platform)" in src
    assert "must_commit_claim" in src
    assert "await db.commit()" in src


def test_find_live_success_null_means_is_null_not_wildcard():
    fx = _Fx()

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
                await _insert_success(db, fx, account_id=fx.account_a, external_post_id="a")
                # Proven-distinct B is not suppressed by A's success alone.
                other = await PublishResilienceService.find_live_success(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account_id=fx.account_b,
                )
                assert other is None

                # NULL intended vs concrete prior → unresolved fail-closed hit.
                null_req = await PublishResilienceService.find_live_success(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account_id=None,
                )
                assert null_req is not None

                await _insert_success(
                    db, fx, account_id=None, external_post_id="null-row"
                )
                # Concrete B vs historical NULL → unresolved block.
                blocked = await PublishResilienceService.find_live_success(
                    db,
                    content_id=fx.content_id,
                    platform="telegram",
                    account_id=fx.account_b,
                )
                assert blocked is not None

    _run(body)


def test_p_scheduled_path_remains_disabled_wrapper():
    src_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "app",
        "services",
        "scheduled_publish_service.py",
    )
    src = open(src_path, encoding="utf-8").read()
    assert "from_scheduler=True" in src
    # Production/runtime enablement remains NO-GO; local .env may differ.
    # I1 must not introduce a new scheduled publish path.
    assert "publish_content" in src


def test_q_r_s_registry_shadow_intent_neutrality():
    assert settings.PUBLISH_WRITE_COORDINATION_SHADOW is False
    assert getattr(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False) is False

    fx = _Fx()
    adapter = CountingAdapter("telegram", post_id="neutral")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx)
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_a,
                        ),
                    )
                    reg = (
                        await db.execute(
                            text(
                                "SELECT count(*) FROM publish_write_coordination_registry"
                            )
                        )
                    ).scalar_one()
                    intents = (
                        await db.execute(
                            text(
                                "SELECT count(*) FROM publish_attempts "
                                "WHERE publication_intent_id IS NOT NULL"
                            )
                        )
                    ).scalar_one()
            assert adapter.invocation_count == 1
            assert int(reg) == 0
            assert int(intents) == 0

    _run(body)


def test_proven_distinct_facebook_pages_allow():
    fx = _Fx()
    adapter = CountingAdapter("facebook", post_id="page-b-post")

    async def body():
        async with _session_factory() as factory:
            async with factory() as db:
                await _seed(db, fx, with_fb=True)
                await _insert_success(
                    db,
                    fx,
                    account_id=fx.fb_a,
                    platform="facebook",
                    external_post_id="page-a-post",
                )
            with _publish_harness(fx, {"facebook": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["facebook"],
                            account_id=fx.fb_b,
                        ),
                    )
            assert adapter.invocation_count == 1
            assert _row("facebook", result["results"])["platform_post_id"] == "page-b-post"

    _run(body)
