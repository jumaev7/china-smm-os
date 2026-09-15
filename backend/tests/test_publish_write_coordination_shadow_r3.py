"""R3 — Publish write coordination shadow-only observation tests.

Proves:
  - shadow flag default false / compose pin
  - pure decision classifications
  - read-only registry access only
  - fail-open error isolation
  - no registry writes from live publish paths
  - shadow OFF vs ON live-behavior equivalence
  - synthetic registry classification vs unchanged live execution
  - source audit: no mutation-method runtime calls from live paths
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_write_coordination_registry import (
    build_logical_write_key,
)
from app.schemas.publishing import PublishContentRequest
from app.services.publish_resilience import PublishResilienceService
from app.services.publish_service import ADAPTERS, PublishService
from app.services.publish_write_coordination import (
    write_coordination_enabled,
    write_coordination_shadow_enabled,
)
from app.services.publish_write_coordination_registry_service import (
    PublishWriteCoordinationRegistryService as RegistryService,
)
from app.services.publish_write_coordination_shadow import (
    ALLOW_IF_AUTHORITY_WERE_REQUESTED,
    BLOCK_INTENT_SUPERSEDED,
    BLOCK_SAME_INTENT_SUCCESS,
    BLOCK_UNRESOLVED_DESTINATION,
    FORBIDDEN_MUTATION_METHODS,
    INSUFFICIENT_INTENT_CONTEXT,
    NO_REGISTRY_EVIDENCE,
    classify_shadow_decision,
    disagreement_kind,
    observe_publish_pre_provider,
)
from app.services import publish_write_coordination_shadow_metrics as shadow_metrics

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_ADMIN_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/postgres"
)
DEFAULT_DB_NAME = "pwr_registry_r3_shadow_test"
REGISTRY_TABLE = "publish_write_coordination_registry"

LIVE_RUNTIME_FILES = [
    BACKEND_ROOT / "app" / "services" / "publish_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_resilience.py",
    BACKEND_ROOT / "app" / "services" / "scheduled_publish_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_executor.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_claim_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_barrier_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_manual_resolution_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_preparation_service.py",
]


# ---------------------------------------------------------------------------
# Pure decision unit tests
# ---------------------------------------------------------------------------


def test_shadow_flag_defaults_false():
    assert type(settings).model_fields["PUBLISH_WRITE_COORDINATION_SHADOW"].default is False
    assert settings.PUBLISH_WRITE_COORDINATION_SHADOW is False
    assert write_coordination_shadow_enabled() is False
    assert write_coordination_enabled() is False


def test_compose_production_pins_shadow_false():
    compose = (REPO_ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "PUBLISH_WRITE_COORDINATION_SHADOW: ${PUBLISH_WRITE_COORDINATION_SHADOW:-false}" in compose
    assert "PUBLISH_WRITE_COORDINATION_SHADOW:-true" not in compose
    assert "PUBLISH_WRITE_COORDINATION_ENABLED: ${PUBLISH_WRITE_COORDINATION_ENABLED:-false}" in compose


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (
            {"publication_intent_id": None, "has_unresolved": True},
            BLOCK_UNRESOLVED_DESTINATION,
        ),
        (
            {"publication_intent_id": None, "has_unresolved": False},
            INSUFFICIENT_INTENT_CONTEXT,
        ),
        (
            {
                "publication_intent_id": uuid4(),
                "has_unresolved": False,
                "has_same_intent_success": True,
            },
            BLOCK_SAME_INTENT_SUCCESS,
        ),
        (
            {
                "publication_intent_id": uuid4(),
                "has_unresolved": False,
                "intent_row_state": "SUPERSEDED",
            },
            BLOCK_INTENT_SUPERSEDED,
        ),
        (
            {
                "publication_intent_id": uuid4(),
                "has_unresolved": False,
                "intent_row_state": None,
            },
            NO_REGISTRY_EVIDENCE,
        ),
        (
            {
                "publication_intent_id": uuid4(),
                "has_unresolved": False,
                "intent_row_state": "FAILED_SAFE",
            },
            ALLOW_IF_AUTHORITY_WERE_REQUESTED,
        ),
        (
            {
                "publication_intent_id": uuid4(),
                "has_unresolved": False,
                "intent_row_state": "RESERVED",
            },
            ALLOW_IF_AUTHORITY_WERE_REQUESTED,
        ),
    ],
)
def test_classify_shadow_decision_matrix(kwargs, expected):
    decision = classify_shadow_decision(**kwargs)
    assert decision.classification == expected


def test_disagreement_kind_dimensions():
    block = classify_shadow_decision(
        publication_intent_id=uuid4(),
        has_unresolved=True,
    )
    allow = classify_shadow_decision(
        publication_intent_id=uuid4(),
        has_unresolved=False,
        intent_row_state=None,
    )
    insufficient = classify_shadow_decision(
        publication_intent_id=None,
        has_unresolved=False,
    )
    assert disagreement_kind("allow", block) == "live_allow_shadow_block"
    assert disagreement_kind("block", allow) == "live_block_shadow_allow"
    assert disagreement_kind("allow", allow) is None
    assert disagreement_kind("block", block) is None
    assert disagreement_kind("allow", insufficient) is None


def test_shadow_disabled_performs_zero_registry_queries():
    shadow_metrics.reset_for_tests()
    db = MagicMock()

    async def _body():
        with patch.object(settings, "PUBLISH_WRITE_COORDINATION_SHADOW", False):
            with patch.object(
                RegistryService,
                "destination_has_unresolved_write",
                new=AsyncMock(side_effect=AssertionError("must not query")),
            ):
                result = await observe_publish_pre_provider(
                    db,
                    tenant_id=uuid4(),
                    content_id=uuid4(),
                    platform="telegram",
                    account_id=None,
                    publication_intent_id=None,
                    live_decision="allow",
                )
        assert result.skipped is True
        assert result.evaluated is False
        snap = shadow_metrics.snapshot()
        assert snap["shadow_evaluations_total"] == 0
        assert snap["shadow_error_total"] == 0

    asyncio.run(_body())


# ---------------------------------------------------------------------------
# Source / mutation audit
# ---------------------------------------------------------------------------


def test_shadow_module_never_calls_forbidden_mutation_methods():
    path = (
        BACKEND_ROOT
        / "app"
        / "services"
        / "publish_write_coordination_shadow.py"
    )
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)
    assert FORBIDDEN_MUTATION_METHODS.isdisjoint(called)
    # No attribute access of mutation APIs (e.g. RegistryService.acquire_...).
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_MUTATION_METHODS:
            raise AssertionError(f"shadow references mutation attribute {node.attr}")


def test_live_runtime_paths_have_no_registry_mutation_calls():
    """R3 must not introduce registry mutation calls into live runtime modules."""
    import re

    for path in LIVE_RUNTIME_FILES:
        assert path.is_file(), f"missing {path}"
        src = path.read_text(encoding="utf-8")
        assert "PublishWriteCoordinationRegistryService" not in src
        assert "publish_write_coordination_registry_repository" not in src
        for method in FORBIDDEN_MUTATION_METHODS:
            # Match attribute/call form, not unrelated helpers like _record_ambiguous_audit.
            pattern = rf"(?<![A-Za-z0-9_]){re.escape(method)}\s*\("
            assert re.search(pattern, src) is None, (
                f"{path.name} appears to call {method}()"
            )


def test_publish_service_only_imports_shadow_not_registry_service():
    src = (BACKEND_ROOT / "app" / "services" / "publish_service.py").read_text(
        encoding="utf-8"
    )
    assert "publish_write_coordination_shadow" in src
    assert "observe_publish_pre_provider" in src
    assert "publish_write_coordination_registry_service" not in src
    assert "acquire_write_authority" not in src


def test_retry_executor_and_manual_resolution_remain_unwired_to_shadow():
    """Deferred: retry path not shadowed in R3."""
    for name in (
        "publish_retry_command_executor.py",
        "publish_retry_command_preparation_service.py",
        "publish_retry_command_barrier_service.py",
        "publish_retry_command_manual_resolution_service.py",
    ):
        src = (BACKEND_ROOT / "app" / "services" / name).read_text(encoding="utf-8")
        assert "publish_write_coordination_shadow" not in src
        assert "observe_publish_pre_provider" not in src


def test_shadow_module_doc_documents_deferred_retry_integration():
    src = (
        BACKEND_ROOT
        / "app"
        / "services"
        / "publish_write_coordination_shadow.py"
    ).read_text(encoding="utf-8")
    assert "Deferred" in src
    assert "retry" in src.lower()


# ---------------------------------------------------------------------------
# Isolated PostgreSQL helpers
# ---------------------------------------------------------------------------


def _admin_url() -> str:
    return os.environ.get("PWR_REGISTRY_R3_ADMIN_URL", DEFAULT_ADMIN_URL)


async def _wait_ready(engine, attempts: int = 40) -> None:
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(0.25)
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
        pytest.skip(f"PostgreSQL unavailable for R3 shadow tests: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for R3 shadow tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return target_url


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        for table in (
            "platform_audit_logs",
            REGISTRY_TABLE,
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
                    company_name VARCHAR(255) NULL,
                    telegram_publish_chat_id VARCHAR(255) NULL,
                    telegram_publish_title VARCHAR(255) NULL
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
                    status VARCHAR(30) NOT NULL DEFAULT 'mock',
                    access_token_encrypted TEXT NULL,
                    refresh_token_encrypted TEXT NULL,
                    facebook_page_id VARCHAR(64) NULL,
                    instagram_business_account_id VARCHAR(64) NULL,
                    permissions_json TEXT NULL,
                    account_metadata_json TEXT NULL,
                    expires_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
                CREATE UNIQUE INDEX uq_publish_attempts_active_claim
                ON publish_attempts (idempotency_key)
                WHERE status = 'in_progress' AND idempotency_key IS NOT NULL
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
                    UNIQUE (logical_write_key)
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE platform_audit_logs (
                    id UUID PRIMARY KEY,
                    actor_type VARCHAR(40) NOT NULL,
                    actor_id UUID NULL,
                    tenant_id UUID NULL,
                    event_type VARCHAR(120) NOT NULL,
                    resource_type VARCHAR(80) NULL,
                    resource_id VARCHAR(120) NULL,
                    details JSONB NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )


def _run(coro):
    asyncio.run(coro)


class _Fixture:
    def __init__(self):
        self.tenant_id = uuid4()
        self.client_id = uuid4()
        self.content_id = uuid4()
        self.account_id = uuid4()
        self.platform = "telegram"
        self.platforms = ["telegram"]
        self.publish_version = "v-r3-shadow"


class CountingAdapter:
    def __init__(self, platform: str, *, success: bool = True, post_id: str = "tg-1"):
        self.platform = platform
        self.success = success
        self.post_id = post_id
        self.invocation_count = 0

    async def __call__(self, ctx) -> dict:
        self.invocation_count += 1
        if self.success:
            return {
                "platform": self.platform,
                "success": True,
                "platform_post_id": self.post_id,
                "post_url": None,
                "mock": False,
            }
        return {
            "platform": self.platform,
            "success": False,
            "error": "fake failure",
            "platform_post_id": None,
            "mock": False,
            "failure_code": "provider_error",
            "retryable": False,
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
                :id, :cid, :plats, 'failed', 'hello shadow',
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


async def _insert_registry_row(
    db: AsyncSession,
    *,
    tenant_id,
    content_id,
    account_id,
    platform: str,
    intent_id,
    state: str,
    generation: int = 1,
    version: int = 1,
    external_post_id: str | None = None,
) -> None:
    key = build_logical_write_key(
        tenant_id, content_id, platform, account_id, intent_id
    )
    await db.execute(
        text(
            f"""
            INSERT INTO {REGISTRY_TABLE} (
                id, logical_write_key, tenant_id, content_id, platform,
                account_id, publication_intent_id, root_intent_id, state,
                generation, version, external_post_id
            ) VALUES (
                :id, :key, :tid, :cid, :plat, :aid, :intent, :intent, :state,
                :gen, :ver, :epid
            )
            """
        ),
        {
            "id": uuid4(),
            "key": key,
            "tid": tenant_id,
            "cid": content_id,
            "plat": platform,
            "aid": account_id,
            "intent": intent_id,
            "state": state,
            "gen": generation,
            "ver": version,
            "epid": external_post_id,
        },
    )


async def _registry_snapshot(db: AsyncSession) -> list[tuple]:
    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, state, generation, version, publication_intent_id,
                       logical_write_key, external_post_id
                FROM {REGISTRY_TABLE}
                ORDER BY logical_write_key
                """
            )
        )
    ).all()
    return [tuple(r) for r in rows]


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
        caption_long_ru="hello shadow",
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
def _publish_harness(fx: _Fixture, adapters: dict, *, shadow: bool):
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
            "caption_long_ru": "hello shadow",
            "media_url": None,
            "generated_final_video_url": None,
        }

    async def _resolve(_db, _tenant_id, platform, account_id=None, **_kwargs):
        return SimpleNamespace(
            id=fx.account_id,
            account_name="TG A",
            account_id="tg-a",
            status="mock",
            platform="telegram",
            tenant_id=fx.tenant_id,
            expires_at=None,
            access_token_encrypted=None,
            facebook_page_id=None,
            instagram_business_account_id=None,
        )

    with (
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_ENABLED", False),
        patch.object(settings, "PUBLISH_WRITE_COORDINATION_SHADOW", shadow),
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
        patch.object(
            PublishResilienceService,
            "_notify_alert",
            new=staticmethod(AsyncMock(return_value=None)),
        ),
        patch(
            "app.services.measurement.publication_registry.register_from_publish_attempt",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.publish_write_coordination_shadow._emit_shadow_audit",
            new=AsyncMock(return_value=None),
        ),
        patch.dict(ADAPTERS, adapters, clear=False),
    ):
        yield


async def _publish_once(db: AsyncSession, fx: _Fixture, adapter: CountingAdapter):
    return await PublishService.publish_content(
        db,
        fx.content_id,
        request=PublishContentRequest(
            platforms=["telegram"],
            account_id=fx.account_id,
            mode="manual_publish",
        ),
    )


# ---------------------------------------------------------------------------
# DB-backed shadow tests
# ---------------------------------------------------------------------------


def test_shadow_observation_and_equivalence_and_no_writes():
    async def body():
        url = await _recreate_database(DEFAULT_DB_NAME)
        engine = create_async_engine(url, echo=False)
        try:
            await _setup_schema(engine)
            Session = async_sessionmaker(engine, expire_on_commit=False)

            # --- synthetic classification via observe ---
            fx = _Fixture()
            intent = uuid4()
            other_intent = uuid4()
            async with Session() as db:
                await _seed_base(db, fx)
                await db.commit()

            cases = [
                ("WRITE_STARTED", BLOCK_UNRESOLVED_DESTINATION, "allow"),
                ("AMBIGUOUS", BLOCK_UNRESOLVED_DESTINATION, "allow"),
                ("SUCCEEDED", BLOCK_SAME_INTENT_SUCCESS, "allow"),
                ("RESOLVED_SUCCEEDED", BLOCK_SAME_INTENT_SUCCESS, "allow"),
                ("SUPERSEDED", BLOCK_INTENT_SUPERSEDED, "allow"),
                ("FAILED_SAFE", ALLOW_IF_AUTHORITY_WERE_REQUESTED, "allow"),
            ]
            for state, expected_class, live in cases:
                shadow_metrics.reset_for_tests()
                async with Session() as db:
                    await db.execute(text(f"DELETE FROM {REGISTRY_TABLE}"))
                    await _insert_registry_row(
                        db,
                        tenant_id=fx.tenant_id,
                        content_id=fx.content_id,
                        account_id=fx.account_id,
                        platform="telegram",
                        intent_id=intent,
                        state=state,
                        external_post_id="ext-1"
                        if state in ("SUCCEEDED", "RESOLVED_SUCCEEDED")
                        else None,
                    )
                    await db.commit()
                    with patch.object(
                        settings, "PUBLISH_WRITE_COORDINATION_SHADOW", True
                    ):
                        with patch(
                            "app.services.publish_write_coordination_shadow._emit_shadow_audit",
                            new=AsyncMock(return_value=None),
                        ):
                            result = await observe_publish_pre_provider(
                                db,
                                tenant_id=fx.tenant_id,
                                content_id=fx.content_id,
                                platform="telegram",
                                account_id=fx.account_id,
                                publication_intent_id=intent,
                                live_decision=live,  # type: ignore[arg-type]
                            )
                    assert result.evaluated is True
                    assert result.classification == expected_class
                    if expected_class in (
                        BLOCK_UNRESOLVED_DESTINATION,
                        BLOCK_SAME_INTENT_SUCCESS,
                        BLOCK_INTENT_SUPERSEDED,
                    ):
                        assert result.disagreement is True

            # Unrelated destination / different intent must not false-block
            # via same-intent success when observing a fresh intent.
            async with Session() as db:
                await db.execute(text(f"DELETE FROM {REGISTRY_TABLE}"))
                await _insert_registry_row(
                    db,
                    tenant_id=fx.tenant_id,
                    content_id=fx.content_id,
                    account_id=fx.account_id,
                    platform="telegram",
                    intent_id=other_intent,
                    state="SUCCEEDED",
                    external_post_id="other-ext",
                )
                await db.commit()
                with patch.object(settings, "PUBLISH_WRITE_COORDINATION_SHADOW", True):
                    with patch(
                        "app.services.publish_write_coordination_shadow._emit_shadow_audit",
                        new=AsyncMock(return_value=None),
                    ):
                        result = await observe_publish_pre_provider(
                            db,
                            tenant_id=fx.tenant_id,
                            content_id=fx.content_id,
                            platform="telegram",
                            account_id=fx.account_id,
                            publication_intent_id=intent,
                            live_decision="allow",
                        )
                assert result.classification == NO_REGISTRY_EVIDENCE

            # Missing intent → INSUFFICIENT (empty registry)
            async with Session() as db:
                await db.execute(text(f"DELETE FROM {REGISTRY_TABLE}"))
                await db.commit()
                with patch.object(settings, "PUBLISH_WRITE_COORDINATION_SHADOW", True):
                    with patch(
                        "app.services.publish_write_coordination_shadow._emit_shadow_audit",
                        new=AsyncMock(return_value=None),
                    ):
                        result = await observe_publish_pre_provider(
                            db,
                            tenant_id=fx.tenant_id,
                            content_id=fx.content_id,
                            platform="telegram",
                            account_id=fx.account_id,
                            publication_intent_id=None,
                            live_decision="allow",
                        )
                assert result.classification == INSUFFICIENT_INTENT_CONTEXT
                assert shadow_metrics.snapshot()["shadow_no_intent_context_total"] >= 1

            # --- publish equivalence OFF vs ON + no registry writes ---
            async def _run_publish(*, shadow: bool, success: bool):
                local_fx = _Fixture()
                adapter = CountingAdapter("telegram", success=success, post_id="p-1")
                async with Session() as db:
                    await _seed_base(db, local_fx)
                    await db.commit()
                    before = await _registry_snapshot(db)
                with _publish_harness(
                    local_fx, {"telegram": adapter}, shadow=shadow
                ):
                    async with Session() as db:
                        out = await _publish_once(db, local_fx, adapter)
                        await db.commit()
                        after = await _registry_snapshot(db)
                        attempts = (
                            await db.execute(
                                text(
                                    "SELECT status, external_post_id, "
                                    "publication_intent_id FROM publish_attempts "
                                    "WHERE content_id = :cid ORDER BY created_at"
                                ),
                                {"cid": local_fx.content_id},
                            )
                        ).all()
                return {
                    "out": {
                        "all_success": out.get("all_success"),
                        "status": out.get("status"),
                        "results": [
                            {
                                "platform": r.get("platform"),
                                "success": r.get("success"),
                                "platform_post_id": r.get("platform_post_id"),
                                "deduplicated": r.get("deduplicated"),
                                "failure_code": r.get("failure_code"),
                            }
                            for r in out.get("results", [])
                        ],
                    },
                    "calls": adapter.invocation_count,
                    "before": before,
                    "after": after,
                    "attempts": [tuple(a) for a in attempts],
                }

            for success in (True, False):
                off = await _run_publish(shadow=False, success=success)
                on = await _run_publish(shadow=True, success=success)
                assert off["out"] == on["out"]
                assert off["calls"] == on["calls"] == 1
                assert off["attempts"] == on["attempts"]
                assert off["before"] == off["after"] == []
                assert on["before"] == on["after"] == []

            # Prior live success suppression equivalence + no registry mutation
            async def _run_prior_success(*, shadow: bool):
                local_fx = _Fixture()
                adapter = CountingAdapter("telegram", success=True, post_id="new")
                async with Session() as db:
                    await _seed_base(db, local_fx)
                    await db.execute(
                        text(
                            """
                            INSERT INTO publish_attempts (
                                id, content_id, platform, account_id, status,
                                external_post_id, response, publish_version
                            ) VALUES (
                                :id, :cid, 'telegram', :aid, 'success',
                                'prior-ext', NULL, :ver
                            )
                            """
                        ),
                        {
                            "id": uuid4(),
                            "cid": local_fx.content_id,
                            "aid": local_fx.account_id,
                            "ver": local_fx.publish_version,
                        },
                    )
                    await db.commit()
                    before = await _registry_snapshot(db)
                with _publish_harness(
                    local_fx, {"telegram": adapter}, shadow=shadow
                ):
                    async with Session() as db:
                        out = await _publish_once(db, local_fx, adapter)
                        await db.commit()
                        after = await _registry_snapshot(db)
                return out, adapter.invocation_count, before, after

            off_ps = await _run_prior_success(shadow=False)
            on_ps = await _run_prior_success(shadow=True)
            assert off_ps[0].get("all_success") is True
            assert on_ps[0].get("all_success") is True
            assert off_ps[1] == on_ps[1] == 0
            assert off_ps[2] == off_ps[3] == []
            assert on_ps[2] == on_ps[3] == []

            # Synthetic WRITE_STARTED present: live still proceeds; registry unchanged
            local_fx = _Fixture()
            adapter = CountingAdapter("telegram", success=True, post_id="live-ok")
            intent = uuid4()
            async with Session() as db:
                await _seed_base(db, local_fx)
                await _insert_registry_row(
                    db,
                    tenant_id=local_fx.tenant_id,
                    content_id=local_fx.content_id,
                    account_id=local_fx.account_id,
                    platform="telegram",
                    intent_id=intent,
                    state="WRITE_STARTED",
                    generation=3,
                    version=5,
                )
                await db.commit()
                before = await _registry_snapshot(db)
            shadow_metrics.reset_for_tests()
            with _publish_harness(local_fx, {"telegram": adapter}, shadow=True):
                async with Session() as db:
                    out = await _publish_once(db, local_fx, adapter)
                    await db.commit()
                    after = await _registry_snapshot(db)
            assert out.get("all_success") is True
            assert adapter.invocation_count == 1
            assert before == after
            assert before[0][1] == "WRITE_STARTED"
            assert before[0][2] == 3
            assert before[0][3] == 5
            snap = shadow_metrics.snapshot()
            assert snap["shadow_evaluations_total"] >= 1
            assert snap["shadow_unresolved_detected_total"] >= 1
            assert snap["shadow_disagreement_total"] >= 1

            # Repository exception fail-open: live unchanged
            local_fx = _Fixture()
            adapter = CountingAdapter("telegram", success=True, post_id="err-ok")
            async with Session() as db:
                await db.execute(text(f"DELETE FROM {REGISTRY_TABLE}"))
                await _seed_base(db, local_fx)
                await db.commit()
                before = await _registry_snapshot(db)
            shadow_metrics.reset_for_tests()
            with _publish_harness(local_fx, {"telegram": adapter}, shadow=True):
                with patch.object(
                    RegistryService,
                    "destination_has_unresolved_write",
                    new=AsyncMock(side_effect=RuntimeError("boom-shadow-db")),
                ):
                    async with Session() as db:
                        out = await _publish_once(db, local_fx, adapter)
                        await db.commit()
                        after = await _registry_snapshot(db)
            assert out.get("all_success") is True
            assert adapter.invocation_count == 1
            assert before == after == []
            assert shadow_metrics.snapshot()["shadow_error_total"] >= 1

            # Forbidden mutation methods never invoked during shadowed publish
            local_fx = _Fixture()
            adapter = CountingAdapter("telegram", success=True, post_id="mut-ok")
            async with Session() as db:
                await db.execute(text(f"DELETE FROM {REGISTRY_TABLE}"))
                await _seed_base(db, local_fx)
                await db.commit()
            spies = {
                name: AsyncMock(side_effect=AssertionError(f"{name} called"))
                for name in FORBIDDEN_MUTATION_METHODS
            }
            with _publish_harness(local_fx, {"telegram": adapter}, shadow=True):
                with (
                    patch.object(RegistryService, "acquire_write_authority", spies["acquire_write_authority"]),
                    patch.object(RegistryService, "mark_write_started", spies["mark_write_started"]),
                    patch.object(RegistryService, "record_safe_failure", spies["record_safe_failure"]),
                    patch.object(RegistryService, "record_success", spies["record_success"]),
                    patch.object(RegistryService, "record_ambiguous", spies["record_ambiguous"]),
                    patch.object(RegistryService, "surface_stranded_write", spies["surface_stranded_write"]),
                    patch.object(RegistryService, "resolve_ambiguous", spies["resolve_ambiguous"]),
                    patch.object(RegistryService, "supersede_intent", spies["supersede_intent"]),
                ):
                    async with Session() as db:
                        out = await _publish_once(db, local_fx, adapter)
                        await db.commit()
            assert out.get("all_success") is True
            for spy in spies.values():
                spy.assert_not_called()

            # Scheduled path shares PublishService hook (from_scheduler=True)
            local_fx = _Fixture()
            adapter = CountingAdapter("telegram", success=True, post_id="sched")
            async with Session() as db:
                await db.execute(text(f"DELETE FROM {REGISTRY_TABLE}"))
                await _seed_base(db, local_fx)
                await db.commit()
                before = await _registry_snapshot(db)
            with _publish_harness(local_fx, {"telegram": adapter}, shadow=True):
                async with Session() as db:
                    out = await PublishService.publish_content(
                        db,
                        local_fx.content_id,
                        request=PublishContentRequest(
                            platforms=["telegram"],
                            account_id=local_fx.account_id,
                            mode="scheduled_publish",
                        ),
                        from_scheduler=True,
                    )
                    await db.commit()
                    after = await _registry_snapshot(db)
            assert adapter.invocation_count == 1
            assert before == after == []
            assert out.get("all_success") is True

        finally:
            await engine.dispose()

    _run(body())


def test_get_destination_intent_row_is_readonly_public_api():
    assert hasattr(RegistryService, "get_destination_intent_row")
    assert callable(RegistryService.get_destination_intent_row)
    # Ensure signature does not expose for_update to callers.
    sig = inspect.signature(RegistryService.get_destination_intent_row)
    assert "for_update" not in sig.parameters
