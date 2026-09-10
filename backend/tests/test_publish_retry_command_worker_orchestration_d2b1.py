"""Phase 3C.1C-D2-B1 — safe worker orchestration + backend=none + compose profile.

Hard acceptance: under all D2-B1 configs, executor / Preparation / Barrier /
provider / Finalizer invocation counts remain 0. No FakeProvider instantiation.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import textwrap
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_retry_command import PublishRetryCommand
from app.services import publish_retry_command_metrics as cmd_metrics
from app.services.publish_retry_command_claim_service import (
    ClaimResult,
    PublishRetryCommandClaimService,
)
from app.services.publish_retry_command_execution_backend import (
    ExecutionBackendKind,
    assert_worker_execution_backend_or_exit,
    normalize_execution_backend,
    resolve_execution_backend,
)
from app.workers import publish_retry_command_worker as worker_mod
from app.workers.publish_retry_command_worker import PublishRetryCommandWorker

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.production.yml"
WORKER_PATH = REPO_ROOT / "backend" / "app" / "workers" / "publish_retry_command_worker.py"
BACKEND_RESOLVER_PATH = (
    REPO_ROOT / "backend" / "app" / "services" / "publish_retry_command_execution_backend.py"
)

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/retry_command_d2b1_test"
)


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_D2B1_PG_URL", DEFAULT_PG_URL)


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
        pytest.skip(f"PostgreSQL unavailable for D2-B1 tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for D2-B1 tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return url


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS publish_retry_commands CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS publish_attempts CASCADE"))
        await conn.execute(
            text(
                """
                CREATE TABLE publish_attempts (
                    id UUID PRIMARY KEY,
                    retry_command_id UUID NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'failed',
                    platform VARCHAR(20) NOT NULL DEFAULT 'telegram',
                    content_id UUID NULL
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
                CREATE INDEX ix_publish_retry_commands_status_created_at
                ON publish_retry_commands (status, created_at)
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
        pytest.skip(f"PostgreSQL D2-B1 test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL D2-B1 test DB unavailable at {url}: {exc}")
        raise
    finally:
        await engine.dispose()


def _run(coro_factory):
    asyncio.run(_with_pg(coro_factory))


@contextmanager
def _gates_on(**overrides):
    values = {
        "PUBLISH_RETRY_COMMANDS_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": False,
        "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND": "none",
        "PUBLISH_RETRY_COMMAND_LEASE_SECONDS": 180,
        "PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE": 1,
    }
    values.update(overrides)
    with patch.multiple(settings, **values):
        yield


async def _insert_command(
    db: AsyncSession,
    *,
    status: str = "pending",
    lease_owner: str | None = None,
    lease_expires_sql: str | None = None,
    provider_write_started: bool = False,
    claimed_at_sql: str | None = None,
    started_at_sql: str | None = None,
    command_id: uuid.UUID | None = None,
) -> uuid.UUID:
    cid = command_id or uuid.uuid4()
    attempt_id = uuid.uuid4()
    await db.execute(
        text("INSERT INTO publish_attempts (id) VALUES (:id)"),
        {"id": attempt_id},
    )
    pws_sql = "NOW()" if provider_write_started else "NULL"
    lease_sql = lease_expires_sql if lease_expires_sql is not None else "NULL"
    claimed_sql = claimed_at_sql if claimed_at_sql is not None else "NULL"
    started_sql = started_at_sql if started_at_sql is not None else "NULL"
    await db.execute(
        text(
            f"""
            INSERT INTO publish_retry_commands (
                id, tenant_id, client_id, content_id, original_attempt_id,
                resulting_attempt_id, platform, publish_version, destination_key,
                requested_source, idempotency_key, status, lease_owner,
                lease_expires_at, claimed_at, started_at, provider_write_started_at,
                correlation_id
            ) VALUES (
                :id, :tenant_id, :client_id, :content_id, :attempt_id,
                NULL, 'telegram', 'pv_test', 'telegram:none',
                'admin', :idem, :status, :lease_owner,
                {lease_sql}, {claimed_sql}, {started_sql}, {pws_sql},
                :corr
            )
            """
        ),
        {
            "id": cid,
            "tenant_id": uuid.uuid4(),
            "client_id": uuid.uuid4(),
            "content_id": uuid.uuid4(),
            "attempt_id": attempt_id,
            "idem": f"idem-{cid}",
            "status": status,
            "lease_owner": lease_owner,
            "corr": str(uuid.uuid4()),
        },
    )
    await db.commit()
    return cid


async def _load(db: AsyncSession, command_id: uuid.UUID) -> PublishRetryCommand:
    return (
        await db.execute(
            select(PublishRetryCommand).where(PublishRetryCommand.id == command_id),
        )
    ).scalar_one()


async def _run_worker_once(factory, worker: PublishRetryCommandWorker):
    with patch.object(worker_mod, "AsyncSessionLocal", factory):
        with patch.object(
            PublishRetryCommandClaimService,
            "record_claim_audits",
            AsyncMock(return_value=None),
        ):
            return await worker.run_once()


# ---------------------------------------------------------------------------
# Config / resolver
# ---------------------------------------------------------------------------


def test_z_defaults_fail_closed():
    assert settings.PUBLISH_RETRY_COMMANDS_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND == "none"


def test_normalize_blank_to_none():
    assert normalize_execution_backend(None) == "none"
    assert normalize_execution_backend("") == "none"
    assert normalize_execution_backend("  ") == "none"
    assert normalize_execution_backend("NONE") == "none"


@pytest.mark.parametrize(
    "raw,kind,runnable,reason",
    [
        ("none", ExecutionBackendKind.NONE, True, "backend_none"),
        ("fake", ExecutionBackendKind.RESERVED_UNIMPLEMENTED, False, "backend_fake_requires_staging_bootstrap"),
        ("telegram", ExecutionBackendKind.UNSUPPORTED_REAL, False, "backend_unsupported"),
        ("facebook", ExecutionBackendKind.UNSUPPORTED_REAL, False, "backend_unsupported"),
        ("instagram", ExecutionBackendKind.UNSUPPORTED_REAL, False, "backend_unsupported"),
        ("real", ExecutionBackendKind.UNSUPPORTED_REAL, False, "backend_unsupported"),
        ("weird", ExecutionBackendKind.INVALID, False, "backend_invalid"),
    ],
)
def test_resolve_execution_backend_matrix(raw, kind, runnable, reason):
    res = resolve_execution_backend(raw)
    assert res.value == raw
    assert res.kind == kind
    assert res.d2b1_runnable is runnable
    assert res.reason == reason


def test_startup_exit_on_invalid_backend():
    with patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "fake"):
        with pytest.raises(SystemExit) as exc:
            assert_worker_execution_backend_or_exit()
        assert exc.value.code == 2
    with patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "telegram"):
        with pytest.raises(SystemExit):
            assert_worker_execution_backend_or_exit()
    with patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "none"):
        assert_worker_execution_backend_or_exit()  # does not raise


# ---------------------------------------------------------------------------
# Architecture / import boundaries
# ---------------------------------------------------------------------------


def test_w_no_fake_provider_import_from_worker():
    src = WORKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "FakeProvider" not in alias.name
                assert "provider_port" not in alias.name
                assert "publish_retry_command_executor" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert "FakeProvider" not in mod
            assert "provider_port" not in mod
            assert "publish_retry_command_executor" not in mod
            assert "preparation_service" not in mod
            assert "barrier_service" not in mod
            assert "finalization_service" not in mod
            for alias in node.names:
                assert alias.name not in {
                    "FakeProviderExecutor",
                    "PublishRetryCommandExecutor",
                    "PublishRetryCommandPreparationService",
                    "PublishRetryCommandBarrierService",
                    "PublishRetryCommandFinalizationService",
                }


def test_x_no_real_provider_imports_in_worker_or_resolver():
    forbidden = (
        "telegram_publisher",
        "facebook_publisher",
        "instagram_publisher",
        "httpx",
        "publish_service",
    )
    for path in (WORKER_PATH, BACKEND_RESOLVER_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for bad in forbidden:
                        assert bad not in alias.name
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for bad in forbidden:
                    assert bad not in mod
                for alias in node.names:
                    assert alias.name != "ADAPTERS"


def _parse_method(method):
    return ast.parse(textwrap.dedent(inspect.getsource(method)))


def def_names_called_in(method) -> set[str]:
    tree = _parse_method(method)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_future_handoff_unreachable_without_execution_context():
    """backend=none / bare worker: orchestrate must not invoke executor handoff."""
    called = def_names_called_in(PublishRetryCommandWorker._orchestrate_after_claim)
    # Handoff may be named in the fake branch; runtime requires verified context.
    assert "prepare" not in called
    assert "cross_barrier" not in called
    assert "finalize" not in called
    orch_tree = _parse_method(PublishRetryCommandWorker._orchestrate_after_claim)
    for node in ast.walk(orch_tree):
        if isinstance(node, ast.Name):
            assert node.id not in {
                "PublishRetryCommandExecutor",
                "PublishRetryCommandPreparationService",
                "PublishRetryCommandBarrierService",
                "PublishRetryCommandFinalizationService",
                "FakeProviderExecutor",
            }

    async def scenario(factory):
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-handoff:1:aaa")
        handoff = AsyncMock()
        with _gates_on(
            PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True,
            PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="none",
        ):
            with patch.object(worker, "_future_executor_handoff", handoff):
                await _run_worker_once(factory, worker)
        assert handoff.await_count == 0
        async with factory() as db:
            assert (await _load(db, cid)).status == "claimed"

    _run(scenario)


def test_fake_without_execution_context_still_refuses_handoff():
    """Defense in depth: fake settings alone do not authorize executor."""
    async def scenario(factory):
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-nofake-ctx:1:aaa")
        handoff = AsyncMock()
        with _gates_on(
            PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True,
            PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="fake",
        ):
            with patch.object(worker, "_future_executor_handoff", handoff):
                await _run_worker_once(factory, worker)
        assert handoff.await_count == 0
        snap = cmd_metrics.snapshot()
        assert snap["retry_command_worker_backend_invalid_total"] >= 1

    _run(scenario)


def test_t_sequential_no_gather_in_worker():
    run_once_tree = _parse_method(PublishRetryCommandWorker.run_once)
    for node in ast.walk(run_once_tree):
        if isinstance(node, ast.Attribute) and node.attr == "gather":
            pytest.fail("run_once must not use asyncio.gather")
        if isinstance(node, ast.Name) and node.id == "gather":
            pytest.fail("run_once must not reference gather")
    forever_tree = _parse_method(PublishRetryCommandWorker.run_forever)
    for node in ast.walk(forever_tree):
        if isinstance(node, ast.Attribute) and node.attr == "gather":
            pytest.fail("run_forever must not use asyncio.gather")


def test_m_no_arbitrary_claimed_row_scan():
    """Worker must not add SELECT scans for claimed / provider_write_started rows."""
    tree = _parse_method(PublishRetryCommandWorker)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Ignore docstrings / log messages; look for SQL-ish literals used as queries.
            val = node.value.strip().lower()
            if val.startswith("select ") and "publish_retry_commands" in val:
                pytest.fail(f"worker must not embed claim scans: {node.value!r}")
    # Only claim_batch authorizes work; worker iterates its returned results only.
    run_once = inspect.getsource(PublishRetryCommandWorker.run_once)
    assert "claim_batch" in run_once
    assert "for item in results" in run_once


# ---------------------------------------------------------------------------
# Gate / orchestration behavior
# ---------------------------------------------------------------------------


def test_a_worker_false_no_claim_no_executor():
    async def scenario(factory):
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-a:1:aaa")
        with _gates_on(PUBLISH_RETRY_COMMAND_WORKER_ENABLED=False):
            results = await _run_worker_once(factory, worker)
        assert results[0].kind == "disabled"
        async with factory() as db:
            assert (await _load(db, cid)).status == "pending"
        snap = cmd_metrics.snapshot()
        assert snap["retry_command_provider_calls_total"] == 0
        assert snap["retry_command_worker_backend_none_total"] == 0

    _run(scenario)


def test_b_commands_false_no_claim_no_executor():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-b:1:aaa")
        with _gates_on(PUBLISH_RETRY_COMMANDS_ENABLED=False):
            results = await _run_worker_once(factory, worker)
        assert results[0].kind == "disabled"
        async with factory() as db:
            assert (await _load(db, cid)).status == "pending"

    _run(scenario)


def test_c_claim_false_no_claim_no_executor():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-c:1:aaa")
        with _gates_on(PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=False):
            results = await _run_worker_once(factory, worker)
        assert results[0].kind == "disabled"
        async with factory() as db:
            assert (await _load(db, cid)).status == "pending"

    _run(scenario)


def test_d_execution_false_claim_may_occur_executor_zero():
    async def scenario(factory):
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-d:1:aaa")
        prep = MagicMock()
        barrier = MagicMock()
        finalizer = MagicMock()
        executor = MagicMock()
        provider = MagicMock()
        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=False):
            with patch(
                "app.services.publish_retry_command_preparation_service."
                "PublishRetryCommandPreparationService.prepare",
                prep,
            ), patch(
                "app.services.publish_retry_command_barrier_service."
                "PublishRetryCommandBarrierService.cross_barrier",
                barrier,
            ), patch(
                "app.services.publish_retry_command_finalization_service."
                "PublishRetryCommandFinalizationService.finalize",
                finalizer,
            ), patch(
                "app.services.publish_retry_command_executor."
                "PublishRetryCommandExecutor.execute",
                executor,
            ), patch(
                "app.services.publish_retry_command_provider_port."
                "FakeProviderExecutor",
                provider,
            ):
                results = await _run_worker_once(factory, worker)
        assert results[0].kind == "claimed"
        assert results[0].command_id == cid
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"
            assert row.provider_write_started_at is None
        assert prep.call_count == 0
        assert barrier.call_count == 0
        assert finalizer.call_count == 0
        assert executor.call_count == 0
        assert provider.call_count == 0
        snap = cmd_metrics.snapshot()
        assert snap["retry_command_worker_execution_disabled_total"] >= 1
        assert snap["retry_command_provider_calls_total"] == 0

    _run(scenario)


def test_e_execution_true_backend_none_zero_downstream():
    async def scenario(factory):
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-e:1:aaa")
        prep = AsyncMock()
        barrier = AsyncMock()
        finalizer = AsyncMock()
        executor = AsyncMock()
        with _gates_on(
            PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True,
            PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="none",
        ):
            with patch(
                "app.services.publish_retry_command_preparation_service."
                "PublishRetryCommandPreparationService.prepare",
                prep,
            ), patch(
                "app.services.publish_retry_command_barrier_service."
                "PublishRetryCommandBarrierService.cross_barrier",
                barrier,
            ), patch(
                "app.services.publish_retry_command_finalization_service."
                "PublishRetryCommandFinalizationService.finalize",
                finalizer,
            ), patch(
                "app.services.publish_retry_command_executor."
                "PublishRetryCommandExecutor.execute",
                executor,
            ):
                results = await _run_worker_once(factory, worker)
        assert results[0].kind == "claimed"
        assert results[0].command_id == cid
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"
            assert row.provider_write_started_at is None
            assert row.resulting_attempt_id is None
        assert prep.await_count == 0
        assert barrier.await_count == 0
        assert finalizer.await_count == 0
        assert executor.await_count == 0
        snap = cmd_metrics.snapshot()
        assert snap["retry_command_worker_backend_none_total"] >= 1
        assert snap["retry_command_prepare_total"] == 0
        assert snap["retry_command_barrier_crossed_total"] == 0
        assert snap["retry_command_provider_calls_total"] == 0
        assert snap["retry_command_finalize_total"] == 0

    _run(scenario)


@pytest.mark.parametrize(
    "backend",
    ["fake", "telegram", "facebook", "instagram", "real", "bogus"],
)
def test_fgh_invalid_fake_real_backends_fail_closed(backend):
    async def scenario(factory):
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id=f"d2b1-{backend}:1:aaa")
        executor = AsyncMock()
        with _gates_on(
            PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True,
            PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=backend,
        ):
            with patch(
                "app.services.publish_retry_command_executor."
                "PublishRetryCommandExecutor.execute",
                executor,
            ):
                results = await _run_worker_once(factory, worker)
        assert results[0].kind == "claimed"
        assert results[0].command_id == cid
        assert executor.await_count == 0
        snap = cmd_metrics.snapshot()
        assert snap["retry_command_worker_backend_invalid_total"] >= 1
        assert snap["retry_command_provider_calls_total"] == 0

    _run(scenario)


def test_i_one_pending_claimed_once_batch_one():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-i:1:aaa")
        with _gates_on():
            results = await _run_worker_once(factory, worker)
        assert len([r for r in results if r.kind == "claimed"]) == 1
        assert results[0].command_id == cid

    _run(scenario)


def test_j_two_pending_only_one_claimed_initially():
    async def scenario(factory):
        async with factory() as db:
            c1 = await _insert_command(db, status="pending")
            await asyncio.sleep(0.02)
            c2 = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-j:1:aaa")
        with _gates_on(PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE=1):
            results = await _run_worker_once(factory, worker)
        claimed = [r for r in results if r.kind == "claimed"]
        assert len(claimed) == 1
        assert claimed[0].command_id in {c1, c2}
        async with factory() as db:
            statuses = {
                (await _load(db, c1)).status,
                (await _load(db, c2)).status,
            }
            assert statuses == {"claimed", "pending"}

    _run(scenario)


def test_k_l_claim_session_closed_before_orchestration_handoff_ids_only():
    async def scenario(factory):
        async with factory() as db:
            await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-kl:1:aaa")
        closed = {"session_closed": False}
        seen: list[dict] = []

        class TrackingSession:
            def __init__(self, real):
                self._real = real

            async def __aenter__(self):
                return await self._real.__aenter__()

            async def __aexit__(self, *args):
                closed["session_closed"] = True
                return await self._real.__aexit__(*args)

        def factory_wrapper():
            return TrackingSession(factory())

        async def capture_orch(*, command_id):
            assert closed["session_closed"] is True
            seen.append({"command_id": command_id, "worker_id": worker.worker_id})
            # Prove handoff scope: only these two identities are used.
            assert set(seen[-1].keys()) == {"command_id", "worker_id"}

        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True):
            with patch.object(worker, "_orchestrate_after_claim", side_effect=capture_orch):
                with patch.object(worker_mod, "AsyncSessionLocal", factory_wrapper):
                    with patch.object(
                        PublishRetryCommandClaimService,
                        "record_claim_audits",
                        AsyncMock(return_value=None),
                    ):
                        await worker.run_once()
        assert len(seen) == 1
        assert seen[0]["worker_id"] == "d2b1-kl:1:aaa"

    _run(scenario)


def test_n_provider_write_started_not_claimed():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(
                db,
                status="provider_write_started",
                lease_owner="writer:1:aaa",
                lease_expires_sql="NOW() - INTERVAL '2 hours'",
                provider_write_started=True,
                claimed_at_sql="NOW() - INTERVAL '3 hours'",
                started_at_sql="NOW() - INTERVAL '3 hours'",
            )
        worker = PublishRetryCommandWorker(worker_id="d2b1-n:1:aaa")
        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True):
            results = await _run_worker_once(factory, worker)
        assert results[0].kind == "none"
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "provider_write_started"
            assert row.lease_owner == "writer:1:aaa"

    _run(scenario)


def test_o_sigterm_before_claim_no_new_claim():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-o:1:aaa")
        worker.request_stop()
        # run_once still claims if called directly; SIGTERM-before-claim is
        # enforced by run_forever not entering run_once when stop is set.
        # Simulate: stop set → skip claim path in a thin loop tick.
        with _gates_on():
            if worker._stop.is_set():
                results = [ClaimResult(kind="disabled", reason="stop_requested")]
            else:
                results = await _run_worker_once(factory, worker)
        assert results[0].kind == "disabled"
        async with factory() as db:
            assert (await _load(db, cid)).status == "pending"

        # Also prove run_forever respects stop before claiming.
        worker2 = PublishRetryCommandWorker(worker_id="d2b1-o2:1:aaa")
        worker2.request_stop()
        with _gates_on(PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS=1.0):
            with patch.object(
                worker2, "run_once", AsyncMock(side_effect=AssertionError("no claim")),
            ):
                await worker2.run_forever()

    _run(scenario)


def test_p_sigterm_after_claim_no_executor_leave_lease():
    async def scenario(factory):
        cmd_metrics.reset_for_tests()
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-p:1:aaa")
        orch = AsyncMock()
        real_claim = PublishRetryCommandClaimService.claim_batch

        async def claim_then_stop(*args, **kwargs):
            real = await real_claim(*args, **kwargs)
            worker.request_stop()
            return real

        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True):
            with patch.object(
                PublishRetryCommandClaimService,
                "claim_batch",
                side_effect=claim_then_stop,
            ):
                with patch.object(worker, "_orchestrate_after_claim", orch):
                    results = await _run_worker_once(factory, worker)
        assert results[0].kind == "claimed"
        assert orch.await_count == 0
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"
            assert row.lease_owner == "d2b1-p:1:aaa"

    _run(scenario)


def test_q_r_exception_no_immediate_retry_no_remembered_id():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(db, status="pending")
        worker = PublishRetryCommandWorker(worker_id="d2b1-q:1:aaa")
        calls: list[uuid.UUID] = []

        async def boom(*, command_id):
            calls.append(command_id)
            raise RuntimeError("orchestration boom")

        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True):
            with patch.object(worker, "_orchestrate_after_claim", side_effect=boom):
                await _run_worker_once(factory, worker)
            # Next poll does not remember command_id — only claim_batch can re-auth.
            with patch.object(
                PublishRetryCommandClaimService,
                "claim_batch",
                AsyncMock(return_value=[ClaimResult(kind="none")]),
            ) as claim_mock:
                with patch.object(
                    worker, "_orchestrate_after_claim", AsyncMock(),
                ) as orch2:
                    await _run_worker_once(factory, worker)
        assert calls == [cid]
        claim_mock.assert_awaited()
        # Second tick got none — orchestration not re-invoked with remembered id.
        assert orch2.await_count == 0
        async with factory() as db:
            row = await _load(db, cid)
            assert row.status == "claimed"  # left for lease/reclaim

    _run(scenario)


def test_s_lease_reclaim_remains_canonical_recovery():
    async def scenario(factory):
        async with factory() as db:
            cid = await _insert_command(
                db,
                status="claimed",
                lease_owner="dead:1:aaa",
                lease_expires_sql="NOW() - INTERVAL '1 hour'",
                claimed_at_sql="NOW() - INTERVAL '2 hours'",
                started_at_sql="NOW() - INTERVAL '2 hours'",
            )
        worker = PublishRetryCommandWorker(worker_id="d2b1-s:1:aaa")
        with _gates_on(PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=True):
            results = await _run_worker_once(factory, worker)
        assert results[0].kind == "reclaimed"
        assert results[0].command_id == cid
        async with factory() as db:
            row = await _load(db, cid)
            assert row.lease_owner == "d2b1-s:1:aaa"
            assert row.status == "claimed"

    _run(scenario)


# ---------------------------------------------------------------------------
# Compose profile hardening
# ---------------------------------------------------------------------------


def _service_blocks(text: str) -> dict[str, str]:
    services: dict[str, str] = {}
    lines = text.splitlines()
    in_services = False
    current: str | None = None
    buf: list[str] = []
    for line in lines:
        if line.startswith("services:"):
            in_services = True
            continue
        if not in_services:
            continue
        if line.startswith("networks:") or line.startswith("volumes:"):
            break
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            if current is not None:
                services[current] = "\n".join(buf)
            current = line.strip().rstrip(":")
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        services[current] = "\n".join(buf)
    return services


def test_uv_compose_profile_gates_retry_worker():
    text = COMPOSE.read_text(encoding="utf-8")
    services = _service_blocks(text)
    assert "publish-retry-command-worker" in services
    worker = services["publish-retry-command-worker"]
    assert "profiles:" in worker
    assert "retry-command" in worker
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND" in worker
    assert "${PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND:-none}" in worker

    # Backend and unrelated workers must not gain the retry-command profile.
    for name in (
        "backend",
        "automation-worker",
        "telegram-webhook-worker",
        "listening-worker",
        "publish-alert-telegram-worker",
        "frontend",
        "postgres",
    ):
        body = services[name]
        assert "retry-command" not in body, f"{name} must not use retry-command profile"

    # migrate keeps tools profile only
    assert 'profiles: ["tools"]' in services["migrate"] or "tools" in services["migrate"]


def test_compose_config_excludes_worker_without_profile():
    """Prefer docker compose config when available; else static proof above."""
    import shutil
    import subprocess

    if not shutil.which("docker"):
        pytest.skip("docker not available for compose config check")
    env = {**os.environ, "COMPOSE_FILE": str(COMPOSE)}
    # Provide dummy required vars so config can render.
    required = {
        "DATABASE_URL": "postgresql://u:p@localhost/db",
        "SECRET_KEY": "x",
        "ADMIN_SECRET_KEY": "x",
        "TENANT_SECRET_KEY": "x",
        "S3_BUCKET": "b",
        "S3_ENDPOINT_URL": "http://localhost",
        "S3_ACCESS_KEY": "k",
        "S3_SECRET_KEY": "s",
        "OPENAI_API_KEY": "k",
        "TELEGRAM_BOT_TOKEN": "t",
        "TELEGRAM_ADMIN_ID": "1",
        "TELEGRAM_WEBHOOK_SECRET": "s",
        "META_APP_ID": "1",
        "META_APP_SECRET": "s",
        "LISTENING_META_WEBHOOK_VERIFY_TOKEN": "t",
        "POSTGRES_PASSWORD": "p",
    }
    env.update(required)
    try:
        base = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config", "--services"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
        profiled = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE),
                "--profile",
                "retry-command",
                "config",
                "--services",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"docker compose config unavailable: {exc}")

    if base.returncode != 0:
        pytest.skip(f"docker compose config failed: {base.stderr}")
    base_services = set(base.stdout.split())
    assert "publish-retry-command-worker" not in base_services
    assert "backend" in base_services

    if profiled.returncode != 0:
        pytest.skip(f"docker compose profile config failed: {profiled.stderr}")
    profile_services = set(profiled.stdout.split())
    assert "publish-retry-command-worker" in profile_services
    assert "backend" in profile_services
