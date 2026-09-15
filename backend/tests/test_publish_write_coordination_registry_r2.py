"""R2 — Publish Write Coordination Registry repository + state-machine tests.

Dormant service only. No PublishService / executor / scheduler wiring.
"""
from __future__ import annotations

import asyncio
import ast
import inspect
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.publish_write_coordination_registry import (
    PUBLISH_WRITE_COORDINATION_STATES,
    build_logical_write_key,
)
from app.repositories.publish_write_coordination_registry_repository import (
    PublishWriteCoordinationRegistryRepository as RegistryRepo,
)
from app.services.publish_write_coordination import (
    DestinationIdentity,
    normalize_destination,
)
from app.services.publish_write_coordination_registry_errors import (
    AlreadySucceeded,
    IntentSuperseded,
    InvalidStateTransition,
    LeaseStillActive,
    OwnerMismatch,
    StaleGeneration,
    StaleVersion,
    UnresolvedWriteConflict,
)
from app.services.publish_write_coordination_registry_service import (
    INITIAL_GENERATION,
    PublishWriteCoordinationRegistryService as RegistryService,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADMIN_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/postgres"
)
DEFAULT_DB_NAME = "pwr_registry_r2_test"

SERVICE_MOD = "publish_write_coordination_registry_service"
REPO_MOD = "publish_write_coordination_registry_repository"
REGISTRY_TABLE = "publish_write_coordination_registry"

LIVE_SERVICE_FILES = [
    BACKEND_ROOT / "app" / "services" / "publish_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_resilience.py",
    BACKEND_ROOT / "app" / "services" / "publish_write_coordination.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_executor.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_claim_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_barrier_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_manual_resolution_service.py",
    BACKEND_ROOT / "app" / "services" / "publish_retry_command_service.py",
    BACKEND_ROOT / "app" / "services" / "scheduled_publish_service.py",
]


def _admin_url() -> str:
    return os.environ.get("PWR_REGISTRY_R2_ADMIN_URL", DEFAULT_ADMIN_URL)


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
        pytest.skip(f"PostgreSQL unavailable for R2 registry tests: {exc}")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for R2 registry tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return target_url


async def _setup_minimal_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS publish_write_coordination_registry CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS publishing_accounts CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS content_items CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS tenants CASCADE"))
        await conn.execute(text("CREATE TABLE tenants (id UUID PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE content_items (id UUID PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE publishing_accounts (id UUID PRIMARY KEY)"))
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


async def _seed_parents(
    session: AsyncSession,
    *,
    tenant: uuid.UUID,
    content: uuid.UUID,
    account: uuid.UUID | None = None,
) -> None:
    await session.execute(text("INSERT INTO tenants (id) VALUES (:id)"), {"id": tenant})
    await session.execute(
        text("INSERT INTO content_items (id) VALUES (:id)"), {"id": content}
    )
    if account is not None:
        await session.execute(
            text("INSERT INTO publishing_accounts (id) VALUES (:id)"),
            {"id": account},
        )
    await session.commit()


def _dest(
    tenant: uuid.UUID,
    content: uuid.UUID,
    account: uuid.UUID | None = None,
    platform: str = "telegram",
) -> DestinationIdentity:
    return normalize_destination(
        tenant_id=tenant,
        content_id=content,
        platform=platform,
        account_id=account,
    )


def _run(coro_factory):
    async def _main():
        url = await _recreate_database(DEFAULT_DB_NAME)
        engine = create_async_engine(url, echo=False)
        try:
            await _wait_ready(engine)
            await _setup_minimal_schema(engine)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            await coro_factory(factory)
        finally:
            await engine.dispose()

    asyncio.run(_main())


# ---------------------------------------------------------------------------
# Pure key helper
# ---------------------------------------------------------------------------


def test_build_logical_write_key_deterministic_account_none_and_prefix():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    intent = uuid.uuid4()
    account = uuid.uuid4()
    k1 = build_logical_write_key(tenant, content, "Telegram", None, intent)
    k2 = build_logical_write_key(tenant, content, "telegram", None, intent)
    k3 = build_logical_write_key(tenant, content, "telegram", account, intent)
    k4 = build_logical_write_key(tenant, content, "telegram", None, uuid.uuid4())
    assert k1 == k2
    assert k1 != k3
    assert k1 != k4
    assert len(k1) == 64
    # Prefix retained in preimage (hash changes if prefix omitted).
    from hashlib import sha256

    payload = "|".join(
        [
            "pwr_v1",
            str(tenant),
            str(content),
            "telegram",
            "none",
            str(intent),
        ]
    )
    assert k1 == sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Happy-path + crash/race suite
# ---------------------------------------------------------------------------


def test_first_acquire_generation_one_and_same_owner_idempotent():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="owner-a",
                lease_seconds=60,
            )
            assert auth.state == "RESERVED"
            assert auth.generation == INITIAL_GENERATION == 1
            assert auth.version == 0
            assert auth.owner_id == "owner-a"
        async with factory() as db:
            again = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="owner-a",
                lease_seconds=60,
            )
            assert again.registry_id == auth.registry_id
            assert again.generation == 1
            assert again.version == 0

    _run(body)


def test_duplicate_acquire_different_owners_blocked_by_live_lease():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="owner-a",
                lease_seconds=120,
            )
        async with factory() as db:
            with pytest.raises(LeaseStillActive):
                await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="owner-b",
                    lease_seconds=120,
                )

    _run(body)


def test_expired_reserved_reclaim_bumps_generation_and_rejects_stale():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    past = datetime.now(timezone.utc) - timedelta(seconds=30)

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="owner-a",
                lease_expires_at=past,
                now=past - timedelta(seconds=1),
            )
            assert auth.generation == 1
        async with factory() as db:
            reclaimed = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="owner-b",
                lease_seconds=60,
            )
            assert reclaimed.generation == 2
            assert reclaimed.owner_id == "owner-b"
            assert reclaimed.version == 1
        async with factory() as db:
            with pytest.raises(StaleGeneration):
                await RegistryService.mark_write_started(
                    db,
                    registry_id=reclaimed.registry_id,
                    owner_type="attempt",
                    owner_id="owner-a",
                    generation=1,
                    expected_version=reclaimed.version,
                )
            with pytest.raises(OwnerMismatch):
                await RegistryService.mark_write_started(
                    db,
                    registry_id=reclaimed.registry_id,
                    owner_type="attempt",
                    owner_id="owner-a",
                    generation=2,
                    expected_version=reclaimed.version,
                )

    _run(body)


def test_mark_write_started_success_and_stale_version():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="owner-a",
                lease_seconds=60,
            )
        async with factory() as db:
            with pytest.raises(StaleVersion):
                await RegistryService.mark_write_started(
                    db,
                    registry_id=auth.registry_id,
                    owner_type="attempt",
                    owner_id="owner-a",
                    generation=auth.generation,
                    expected_version=auth.version + 5,
                )
        async with factory() as db:
            started = await RegistryService.mark_write_started(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="owner-a",
                generation=auth.generation,
                expected_version=auth.version,
            )
            assert started.state == "WRITE_STARTED"
            assert started.version == auth.version + 1

    _run(body)


def test_write_started_cannot_reclaim_or_safe_fail():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="owner-a",
                lease_seconds=1,
            )
            started = await RegistryService.mark_write_started(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="owner-a",
                generation=auth.generation,
                expected_version=auth.version,
            )
        # Even with ancient "now", WRITE_STARTED blocks acquire.
        async with factory() as db:
            with pytest.raises(UnresolvedWriteConflict):
                await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="owner-b",
                    lease_seconds=60,
                    now=datetime.now(timezone.utc) + timedelta(days=1),
                )
        async with factory() as db:
            with pytest.raises(InvalidStateTransition) as exc:
                await RegistryService.record_safe_failure(
                    db,
                    registry_id=auth.registry_id,
                    owner_type="attempt",
                    owner_id="owner-a",
                    generation=auth.generation,
                    expected_version=started.version,
                )
            assert exc.value.from_state == "WRITE_STARTED"
            assert exc.value.to_state == "FAILED_SAFE"

    _run(body)


def test_success_and_ambiguous_paths():
    tenant, content = uuid.uuid4(), uuid.uuid4()
    intent_ok, intent_amb = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)

        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent_ok,
                owner_type="attempt",
                owner_id="o1",
                lease_seconds=60,
            )
            started = await RegistryService.mark_write_started(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="o1",
                generation=auth.generation,
                expected_version=auth.version,
            )
            ok = await RegistryService.record_success(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="o1",
                generation=auth.generation,
                expected_version=started.version,
                external_post_id="post-1",
            )
            assert ok.state == "SUCCEEDED"
            assert await RegistryService.same_intent_has_durable_success(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent_ok,
            )

        async with factory() as db:
            auth2 = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent_amb,
                owner_type="attempt",
                owner_id="o2",
                lease_seconds=60,
            )
            started2 = await RegistryService.mark_write_started(
                db,
                registry_id=auth2.registry_id,
                owner_type="attempt",
                owner_id="o2",
                generation=auth2.generation,
                expected_version=auth2.version,
            )
            amb = await RegistryService.record_ambiguous(
                db,
                registry_id=auth2.registry_id,
                owner_type="attempt",
                owner_id="o2",
                generation=auth2.generation,
                expected_version=started2.version,
            )
            assert amb.state == "AMBIGUOUS"
            with pytest.raises(UnresolvedWriteConflict):
                await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent_amb,
                    owner_type="attempt",
                    owner_id="o3",
                    lease_seconds=60,
                )

    _run(body)


def test_resolve_ambiguous_failed_then_reacquire_and_succeeded_blocks():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="o1",
                lease_seconds=60,
            )
            started = await RegistryService.mark_write_started(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="o1",
                generation=auth.generation,
                expected_version=auth.version,
            )
            amb = await RegistryService.record_ambiguous(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="o1",
                generation=auth.generation,
                expected_version=started.version,
            )
            resolved = await RegistryService.resolve_ambiguous(
                db,
                registry_id=auth.registry_id,
                expected_version=amb.version,
                target="RESOLVED_FAILED",
                resolution_evidence="recon:no-effect",
                resolver_id="ops-1",
            )
            assert resolved.state == "RESOLVED_FAILED"
        async with factory() as db:
            again = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="o2",
                lease_seconds=60,
            )
            assert again.generation == 2
            started2 = await RegistryService.mark_write_started(
                db,
                registry_id=again.registry_id,
                owner_type="attempt",
                owner_id="o2",
                generation=again.generation,
                expected_version=again.version,
            )
            amb2 = await RegistryService.record_ambiguous(
                db,
                registry_id=again.registry_id,
                owner_type="attempt",
                owner_id="o2",
                generation=again.generation,
                expected_version=started2.version,
            )
            ok = await RegistryService.resolve_ambiguous(
                db,
                registry_id=again.registry_id,
                expected_version=amb2.version,
                target="RESOLVED_SUCCEEDED",
                resolution_evidence="recon:found-post",
                resolver_id="ops-2",
                external_post_id="ext-9",
            )
            assert ok.state == "RESOLVED_SUCCEEDED"
            with pytest.raises(AlreadySucceeded):
                await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="o3",
                    lease_seconds=60,
                )

    _run(body)


def test_failed_safe_reacquire_and_supersede_rules():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="o1",
                lease_seconds=60,
            )
            failed = await RegistryService.record_safe_failure(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="o1",
                generation=auth.generation,
                expected_version=auth.version,
            )
            assert failed.state == "FAILED_SAFE"
        async with factory() as db:
            again = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent,
                owner_type="attempt",
                owner_id="o2",
                lease_seconds=60,
            )
            assert again.generation == 2
            # SUPERSEDE rejected while RESERVED (unresolved/active)
            with pytest.raises(InvalidStateTransition):
                await RegistryService.supersede_intent(
                    db,
                    registry_id=again.registry_id,
                    expected_version=again.version,
                )
            failed2 = await RegistryService.record_safe_failure(
                db,
                registry_id=again.registry_id,
                owner_type="attempt",
                owner_id="o2",
                generation=again.generation,
                expected_version=again.version,
            )
            sup = await RegistryService.supersede_intent(
                db,
                registry_id=again.registry_id,
                expected_version=failed2.version,
            )
            assert sup.state == "SUPERSEDED"
            with pytest.raises(IntentSuperseded):
                await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="o3",
                    lease_seconds=60,
                )

    _run(body)


def test_surface_stranded_and_destination_unresolved_guard():
    tenant, content = uuid.uuid4(), uuid.uuid4()
    intent_a, intent_b = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)
        async with factory() as db:
            auth = await RegistryService.acquire_write_authority(
                db,
                destination=_dest(tenant, content),
                publication_intent_id=intent_a,
                owner_type="attempt",
                owner_id="o1",
                lease_seconds=60,
            )
            started = await RegistryService.mark_write_started(
                db,
                registry_id=auth.registry_id,
                owner_type="attempt",
                owner_id="o1",
                generation=auth.generation,
                expected_version=auth.version,
            )
            assert await RegistryService.destination_has_unresolved_write(
                db, _dest(tenant, content)
            )
            with pytest.raises(InvalidStateTransition):
                await RegistryService.surface_stranded_write(
                    db,
                    registry_id=auth.registry_id,
                    expected_version=started.version,
                    owner_liveness_valid=True,
                )
            surfaced = await RegistryService.surface_stranded_write(
                db,
                registry_id=auth.registry_id,
                expected_version=started.version,
                owner_liveness_valid=False,
            )
            assert surfaced.state == "AMBIGUOUS"
            # Cross-intent: still unresolved on destination.
            assert await RegistryService.destination_has_unresolved_write(
                db, _dest(tenant, content)
            )
            # Different intent still blocked at destination query level.
            rows = await RegistryRepo.find_unresolved_for_destination(
                db, _dest(tenant, content)
            )
            assert any(r.publication_intent_id == intent_a for r in rows)
            _ = intent_b  # destination guard is cross-intent by design

    _run(body)


def test_two_session_concurrent_first_acquire_one_winner():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)

        from app.services.publish_write_coordination_registry_errors import (
            PublishWriteCoordinationError as PWCE,
        )

        results: list = []
        errors: list = []

        async def worker(owner: str):
            async with factory() as db:
                try:
                    auth = await RegistryService.acquire_write_authority(
                        db,
                        destination=_dest(tenant, content),
                        publication_intent_id=intent,
                        owner_type="attempt",
                        owner_id=owner,
                        lease_seconds=60,
                    )
                    results.append(auth)
                except PWCE as exc:
                    errors.append(exc)

        await asyncio.gather(worker("owner-a"), worker("owner-b"))
        assert len(results) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], LeaseStillActive)
        assert results[0].generation == 1

        async with factory() as db:
            count = (
                await db.execute(
                    text("SELECT COUNT(*) FROM publish_write_coordination_registry")
                )
            ).scalar()
            assert count == 1

    _run(body)


def test_null_account_two_session_uniqueness_concurrency():
    tenant, content, intent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)

        from app.services.publish_write_coordination_registry_errors import (
            PublishWriteCoordinationError as PWCE,
        )

        results: list = []
        errors: list = []

        async def worker(owner: str):
            async with factory() as db:
                try:
                    auth = await RegistryService.acquire_write_authority(
                        db,
                        destination=_dest(tenant, content, account=None),
                        publication_intent_id=intent,
                        owner_type="attempt",
                        owner_id=owner,
                        lease_seconds=60,
                    )
                    results.append(auth)
                except PWCE as exc:
                    errors.append(exc)

        await asyncio.gather(worker("a"), worker("b"))
        assert len(results) == 1
        assert len(errors) == 1
        async with factory() as db:
            count = (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM publish_write_coordination_registry "
                        "WHERE account_id IS NULL"
                    )
                )
            ).scalar()
            assert count == 1

    _run(body)


# ---------------------------------------------------------------------------
# Table-driven transition matrix
# ---------------------------------------------------------------------------


def test_state_transition_matrix():
    """For each persisted state, verify legal/illegal operations."""
    tenant, content = uuid.uuid4(), uuid.uuid4()

    async def body(factory):
        async with factory() as db:
            await _seed_parents(db, tenant=tenant, content=content)

        async def make_state(state: str):
            intent = uuid.uuid4()
            async with factory() as db:
                auth = await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="owner",
                    lease_seconds=120,
                )
                rid = auth.registry_id
                gen = auth.generation
                ver = auth.version
                if state == "RESERVED":
                    return rid, gen, ver, intent
                if state == "FAILED_SAFE":
                    r = await RegistryService.record_safe_failure(
                        db,
                        registry_id=rid,
                        owner_type="attempt",
                        owner_id="owner",
                        generation=gen,
                        expected_version=ver,
                    )
                    return rid, gen, r.version, intent
                started = await RegistryService.mark_write_started(
                    db,
                    registry_id=rid,
                    owner_type="attempt",
                    owner_id="owner",
                    generation=gen,
                    expected_version=ver,
                )
                ver = started.version
                if state == "WRITE_STARTED":
                    return rid, gen, ver, intent
                if state == "SUCCEEDED":
                    r = await RegistryService.record_success(
                        db,
                        registry_id=rid,
                        owner_type="attempt",
                        owner_id="owner",
                        generation=gen,
                        expected_version=ver,
                        external_post_id="p",
                    )
                    return rid, gen, r.version, intent
                if state == "AMBIGUOUS":
                    r = await RegistryService.record_ambiguous(
                        db,
                        registry_id=rid,
                        owner_type="attempt",
                        owner_id="owner",
                        generation=gen,
                        expected_version=ver,
                    )
                    return rid, gen, r.version, intent
                if state == "RESOLVED_SUCCEEDED":
                    amb = await RegistryService.record_ambiguous(
                        db,
                        registry_id=rid,
                        owner_type="attempt",
                        owner_id="owner",
                        generation=gen,
                        expected_version=ver,
                    )
                    r = await RegistryService.resolve_ambiguous(
                        db,
                        registry_id=rid,
                        expected_version=amb.version,
                        target="RESOLVED_SUCCEEDED",
                        resolution_evidence="e",
                        resolver_id="r",
                        external_post_id="x",
                    )
                    return rid, gen, r.version, intent
                if state == "RESOLVED_FAILED":
                    amb = await RegistryService.record_ambiguous(
                        db,
                        registry_id=rid,
                        owner_type="attempt",
                        owner_id="owner",
                        generation=gen,
                        expected_version=ver,
                    )
                    r = await RegistryService.resolve_ambiguous(
                        db,
                        registry_id=rid,
                        expected_version=amb.version,
                        target="RESOLVED_FAILED",
                        resolution_evidence="e",
                        resolver_id="r",
                    )
                    return rid, gen, r.version, intent
                raise AssertionError(state)

        async def make_superseded():
            intent = uuid.uuid4()
            async with factory() as db:
                auth = await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="owner",
                    lease_seconds=60,
                )
                fail = await RegistryService.record_safe_failure(
                    db,
                    registry_id=auth.registry_id,
                    owner_type="attempt",
                    owner_id="owner",
                    generation=auth.generation,
                    expected_version=auth.version,
                )
                sup = await RegistryService.supersede_intent(
                    db,
                    registry_id=auth.registry_id,
                    expected_version=fail.version,
                )
                return auth.registry_id, auth.generation, sup.version, intent

        # Explicit impossible transitions.
        rid, gen, ver, intent = await make_state("WRITE_STARTED")
        async with factory() as db:
            with pytest.raises(InvalidStateTransition):
                await RegistryService.record_safe_failure(
                    db,
                    registry_id=rid,
                    owner_type="attempt",
                    owner_id="owner",
                    generation=gen,
                    expected_version=ver,
                )
            with pytest.raises(UnresolvedWriteConflict):
                await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="other",
                    lease_seconds=60,
                )

        for state, exc_type in (
            ("AMBIGUOUS", UnresolvedWriteConflict),
            ("SUCCEEDED", AlreadySucceeded),
            ("RESOLVED_SUCCEEDED", AlreadySucceeded),
            ("SUPERSEDED", IntentSuperseded),
        ):
            if state == "SUPERSEDED":
                rid, gen, ver, intent = await make_superseded()
            else:
                rid, gen, ver, intent = await make_state(state)
            async with factory() as db:
                with pytest.raises(exc_type):
                    await RegistryService.acquire_write_authority(
                        db,
                        destination=_dest(tenant, content),
                        publication_intent_id=intent,
                        owner_type="attempt",
                        owner_id="other",
                        lease_seconds=60,
                    )

        # Legal re-acquire sources.
        for state in ("FAILED_SAFE", "RESOLVED_FAILED"):
            rid, gen, ver, intent = await make_state(state)
            async with factory() as db:
                again = await RegistryService.acquire_write_authority(
                    db,
                    destination=_dest(tenant, content),
                    publication_intent_id=intent,
                    owner_type="attempt",
                    owner_id="reclaimer",
                    lease_seconds=60,
                )
                assert again.state == "RESERVED"
                assert again.generation == gen + 1

        assert PUBLISH_WRITE_COORDINATION_STATES == frozenset(
            {
                "RESERVED",
                "WRITE_STARTED",
                "SUCCEEDED",
                "FAILED_SAFE",
                "AMBIGUOUS",
                "RESOLVED_SUCCEEDED",
                "RESOLVED_FAILED",
                "SUPERSEDED",
            }
        )

    _run(body)


# ---------------------------------------------------------------------------
# No-runtime-wiring proof
# ---------------------------------------------------------------------------


def test_r2_service_not_imported_by_live_paths():
    tokens = (
        SERVICE_MOD,
        REPO_MOD,
        "PublishWriteCoordinationRegistryService",
        "acquire_write_authority",
    )
    for path in LIVE_SERVICE_FILES:
        assert path.is_file(), f"missing {path}"
        src = path.read_text(encoding="utf-8")
        for token in tokens:
            assert token not in src, f"{path.name} references {token}"


def test_publish_service_ast_has_no_registry_service_import():
    src = (BACKEND_ROOT / "app" / "services" / "publish_service.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert SERVICE_MOD not in alias.name
                assert REPO_MOD not in alias.name
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert SERVICE_MOD not in mod
            assert REPO_MOD not in mod
            for alias in node.names:
                assert alias.name != "PublishWriteCoordinationRegistryService"


def test_registry_service_has_no_provider_or_enqueue_side_effects():
    path = (
        BACKEND_ROOT
        / "app"
        / "services"
        / "publish_write_coordination_registry_service.py"
    )
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported.add(mod.split(".")[0] if mod else "")
            for alias in node.names:
                imported.add(alias.name)
    forbidden_imports = {
        "httpx",
        "ADAPTERS",
        "PublishService",
        "TelegramService",
        "publish_retry_command_executor",
        "publish_retry_command_service",
    }
    assert forbidden_imports.isdisjoint(imported)
    # Must require caller-supplied intent (no mint helper).
    assert "publication_intent_id" in src
    assert "mint" not in src.lower() or "Does NOT" in src

def test_service_public_api_surface():
    expected = {
        "acquire_write_authority",
        "mark_write_started",
        "record_safe_failure",
        "record_success",
        "record_ambiguous",
        "surface_stranded_write",
        "resolve_ambiguous",
        "supersede_intent",
        "destination_has_unresolved_write",
        "same_intent_has_durable_success",
    }
    members = {
        name
        for name, _ in inspect.getmembers(RegistryService)
        if not name.startswith("_") and callable(getattr(RegistryService, name))
    }
    assert expected <= members
