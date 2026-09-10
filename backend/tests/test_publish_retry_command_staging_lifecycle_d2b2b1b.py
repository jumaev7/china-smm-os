"""Phase 3C.1C-D2-B2b1-B — graceful SIGTERM/SIGINT lifecycle.

LOCAL/CI disposable PostgreSQL only (china_smm_os_staging).

Proves:
- should_stop_before_barrier → stopped_before_barrier (no barrier/provider)
- post-barrier drain (no cancel / no replay)
- no new claim after stop
- drain timeout → hard process exit semantics (no asyncio cancellation)
- signal after final pre-barrier check stays in drain territory
- marker-hook coordination (DI only)
- FAKE_SINK_PATH cannot enable fake execution alone
"""
from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import PublishRetryCommand
from app.services import publish_retry_command_metrics as cmd_metrics
from app.services.publish_retry_command_barrier_service import (
    PublishRetryCommandBarrierService,
)
from app.services.publish_retry_command_claim_service import (
    PublishRetryCommandClaimService,
)
from app.services.publish_retry_command_executor import (
    ExecutorHooks,
    PublishRetryCommandExecutor,
)
from app.services.publish_retry_command_provider_port import (
    FakeProviderMode,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.services.publish_retry_command_staging_fixture import (
    PublishRetryCommandStagingFixtureBuilder,
)
from app.services.publish_retry_command_staging_worker_bootstrap import (
    bootstrap_staging_fake_worker_execution,
)
from app.workers import publish_retry_command_worker as worker_mod
from app.workers.publish_retry_command_worker import (
    EXIT_DRAIN_TIMEOUT,
    EXIT_OK,
    PublishRetryCommandWorker,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_STAGING = REPO_ROOT / "docker-compose.staging.yml"
ENV_STAGING_EXAMPLE = REPO_ROOT / ".env.staging.example"
WORKER_PATH = REPO_ROOT / "backend" / "app" / "workers" / "publish_retry_command_worker.py"
EXECUTOR_PATH = (
    REPO_ROOT / "backend" / "app" / "services" / "publish_retry_command_executor.py"
)

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/china_smm_os_staging"
)
WORKER_A = "staging-b2b1b:1:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _pg_url() -> str:
    return os.environ.get("PUBLISH_RETRY_STAGING_PG_URL", DEFAULT_PG_URL)


@contextmanager
def _flags(**kwargs):
    keys = {
        "APP_ENV": "staging",
        "DATABASE_URL": _pg_url(),
        "PUBLISH_RETRY_COMMANDS_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": True,
        "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND": "fake",
        "PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED": True,
        "PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE": "success",
        "PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE": 1,
        "PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS": 0.2,
        "PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS": 60.0,
        "TELEGRAM_BOT_TOKEN": "",
        "META_APP_SECRET": "",
    }
    keys.update(kwargs)
    with patch.multiple(settings, **keys):
        yield


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


async def _ensure_database(db_name: str | None = None) -> str:
    url = _pg_url()
    if db_name is not None:
        url = url.rsplit("/", 1)[0] + f"/{db_name}"
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    name = url.rsplit("/", 1)[-1]
    engine = create_async_engine(admin_url, echo=False, isolation_level="AUTOCOMMIT")
    try:
        await _wait_ready(engine)
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            )
            if exists.first() is None:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable for B2b1-B tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for B2b1-B tests: {exc}")
        raise
    finally:
        await engine.dispose()
    return url


async def _setup_schema(engine) -> None:
    from tests.test_publish_retry_command_staging_worker_bootstrap_d2b2b1a import (
        _setup_schema as _b2b1a_schema,
    )

    await _b2b1a_schema(engine)


async def _with_staging_pg(coro_factory):
    url = await _ensure_database()
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_schema(engine)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await coro_factory(factory, engine)
    except OSError as exc:
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    finally:
        await engine.dispose()


def _tmp_sink_path() -> Path:
    return Path(tempfile.mkdtemp(prefix="b2b1b-sink-")) / "invocations.jsonl"


def _tmp_marker_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="b2b1b-markers-"))


class _BlockingProvider:
    """Staging-test-only provider that blocks after entry (post-barrier)."""

    def __init__(
        self,
        *,
        entered: asyncio.Event,
        release: asyncio.Event,
        block_seconds: float = 30.0,
        result: ProviderExecutionResult | None = None,
    ) -> None:
        self.entered = entered
        self.release = release
        self.block_seconds = block_seconds
        self.result = result or ProviderExecutionResult(
            outcome="success",
            external_post_id="fake:retry-command:blocked:1",
            safe_message="blocking fake success",
            provider_metadata={"fake": True, "staging": True},
        )
        self.invocation_count = 0
        self.requests: list[ProviderExecutionRequest] = []

    async def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.invocation_count += 1
        self.requests.append(request)
        self.entered.set()
        try:
            await asyncio.wait_for(self.release.wait(), timeout=self.block_seconds)
        except asyncio.TimeoutError:
            pass
        return self.result


def test_executor_stopped_before_barrier_no_provider():
    async def body(factory, engine):
        cmd_metrics.reset_for_tests()
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )

            stop_calls = {"n": 0}

            def should_stop() -> bool:
                stop_calls["n"] += 1
                return True

            result = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                provider=execution.provider,
                correlation_id=fx.correlation_id,
                eligibility_evaluator=execution.eligibility_evaluator,
                should_stop_before_barrier=should_stop,
            )
        assert result.ok is True
        assert result.outcome == "stopped_before_barrier"
        assert result.provider_invoked is False
        assert result.provider_invocation_count == 0
        assert result.barrier_outcome is None
        assert stop_calls["n"] == 1
        assert execution.provider.invocation_count == 0
        assert execution.sink is not None
        assert execution.sink.count_for_command(fx.command_id) == 0
        assert cmd_metrics.snapshot()["retry_command_stopped_before_barrier_total"] >= 1

        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            assert cmd.status == "claimed"
            assert cmd.provider_write_started_at is None
            assert cmd.resulting_attempt_id is not None
            attempt = (
                await db.execute(
                    select(PublishAttempt).where(
                        PublishAttempt.id == cmd.resulting_attempt_id,
                    ),
                )
            ).scalar_one()
            assert attempt.status == "operator_review"
            assert attempt.failure_code == "retry_command_prepared"

    asyncio.run(_with_staging_pg(body))


def test_executor_no_stop_check_after_barrier():
    """Post-barrier: should_stop flipping true must not abort provider/finalize."""

    async def body(factory, engine):
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )

            stop = {"v": False}

            def should_stop() -> bool:
                return stop["v"]

            def after_barrier():
                stop["v"] = True

            result = await PublishRetryCommandExecutor.execute(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                provider=execution.provider,
                correlation_id=fx.correlation_id,
                eligibility_evaluator=execution.eligibility_evaluator,
                hooks=ExecutorHooks(after_barrier=after_barrier),
                should_stop_before_barrier=should_stop,
            )
        assert result.outcome == "succeeded"
        assert execution.provider.invocation_count == 1
        assert result.provider_invocation_count == 1

    asyncio.run(_with_staging_pg(body))


def test_signal_before_claim_zero_claim():
    async def body(factory, engine):
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )
            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
            )
            worker.request_stop()
            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                results = await worker.run_once()
            assert results == []
            assert execution.provider.invocation_count == 0
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "pending"
                assert cmd.lease_owner is None

    asyncio.run(_with_staging_pg(body))


def test_signal_after_claim_before_executor():
    async def body(factory, engine):
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )
            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
            )
            orch = AsyncMock()
            real_claim = PublishRetryCommandClaimService.claim_batch

            async def claim_then_stop(*args, **kwargs):
                real = await real_claim(*args, **kwargs)
                worker.request_stop()
                return real

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                with patch.object(
                    PublishRetryCommandClaimService,
                    "claim_batch",
                    side_effect=claim_then_stop,
                ):
                    with patch.object(
                        PublishRetryCommandClaimService,
                        "record_claim_audits",
                        AsyncMock(return_value=None),
                    ):
                        with patch.object(worker, "_orchestrate_after_claim", orch):
                            results = await worker.run_once()
            assert any(r.kind == "claimed" for r in results)
            assert orch.await_count == 0
            assert execution.provider.invocation_count == 0
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "claimed"
                assert cmd.provider_write_started_at is None

    asyncio.run(_with_staging_pg(body))


def test_pre_barrier_sigterm_via_after_prepare_hook():
    async def body(factory, engine):
        marker_dir = _tmp_marker_dir()
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )

            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
            )

            def after_prepare():
                (marker_dir / "after_prepare").write_text("1\n", encoding="utf-8")
                worker.request_stop()

            real_execute = PublishRetryCommandExecutor.execute

            async def execute_with_stop_hook(*args, **kwargs):
                kwargs = dict(kwargs)
                kwargs["hooks"] = ExecutorHooks(after_prepare=after_prepare)
                kwargs["should_stop_before_barrier"] = worker._should_stop_before_barrier
                return await real_execute(*args, **kwargs)

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                with patch.object(
                    PublishRetryCommandClaimService,
                    "record_claim_audits",
                    AsyncMock(return_value=None),
                ):
                    with patch.object(
                        PublishRetryCommandExecutor,
                        "execute",
                        side_effect=execute_with_stop_hook,
                    ):
                        results = await worker.run_once()

            assert any(r.kind == "claimed" for r in results)
            assert execution.provider.invocation_count == 0
            assert (marker_dir / "after_prepare").is_file()
            assert worker.exit_code == EXIT_OK
            assert worker.in_drain_territory is False
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "claimed"
                assert cmd.provider_write_started_at is None
                assert cmd.resulting_attempt_id is not None

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                again = await worker.run_once()
            assert again == []

    asyncio.run(_with_staging_pg(body))


def test_post_barrier_sigterm_drains_provider_and_finalizer():
    async def body(factory, engine):
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )

            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
                drain_seconds=5.0,
            )

            real_execute = PublishRetryCommandExecutor.execute

            async def execute_stop_after_barrier(*args, **kwargs):
                kwargs = dict(kwargs)
                kwargs["hooks"] = ExecutorHooks(
                    after_barrier=lambda: worker.request_stop(),
                )
                kwargs["should_stop_before_barrier"] = worker._should_stop_before_barrier
                return await real_execute(*args, **kwargs)

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                with patch.object(
                    PublishRetryCommandClaimService,
                    "record_claim_audits",
                    AsyncMock(return_value=None),
                ):
                    with patch.object(
                        PublishRetryCommandExecutor,
                        "execute",
                        side_effect=execute_stop_after_barrier,
                    ):
                        await worker.run_once()

            assert execution.provider.invocation_count == 1
            assert execution.sink is not None
            assert execution.sink.count_for_command(fx.command_id) == 1
            assert worker.exit_code == EXIT_OK
            assert worker.in_drain_territory is True
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "succeeded"

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                assert await worker.run_once() == []
            assert execution.provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


def test_success_then_graceful_idle_stop():
    async def body(factory, engine):
        with _flags(PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE="success"):
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )
            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
            )
            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                with patch.object(
                    PublishRetryCommandClaimService,
                    "record_claim_audits",
                    AsyncMock(return_value=None),
                ):
                    await worker.run_once()
            assert execution.provider.invocation_count == 1
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "succeeded"

            worker.request_stop()
            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                assert await worker.run_once() == []
            assert worker.exit_code == EXIT_OK
            assert execution.provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


@pytest.mark.parametrize(
    "mode,expected_status",
    [
        (FakeProviderMode.DEFINITIVE_FAILURE, "failed"),
        (FakeProviderMode.AMBIGUOUS, "ambiguous"),
        (FakeProviderMode.TIMEOUT, "ambiguous"),
        (FakeProviderMode.EXCEPTION, "ambiguous"),
    ],
)
def test_post_barrier_stop_with_provider_outcomes(mode, expected_status):
    async def body(factory, engine):
        with _flags(PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE=mode.value):
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )
            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
            )
            real_execute = PublishRetryCommandExecutor.execute

            async def execute_stop_after_barrier(*args, **kwargs):
                kwargs = dict(kwargs)
                kwargs["hooks"] = ExecutorHooks(
                    after_barrier=lambda: worker.request_stop(),
                )
                kwargs["should_stop_before_barrier"] = worker._should_stop_before_barrier
                return await real_execute(*args, **kwargs)

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                with patch.object(
                    PublishRetryCommandClaimService,
                    "record_claim_audits",
                    AsyncMock(return_value=None),
                ):
                    with patch.object(
                        PublishRetryCommandExecutor,
                        "execute",
                        side_effect=execute_stop_after_barrier,
                    ):
                        await worker.run_once()
            assert execution.provider.invocation_count == 1
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == expected_status
            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                assert await worker.run_once() == []
            assert execution.provider.invocation_count == 1

    asyncio.run(_with_staging_pg(body))


def test_drain_timeout_no_replay_nonzero_exit():
    """In-process soft path: exit code 3 + no replay (hard exit disabled).

    Process-level proof that ``os._exit`` avoids ``CancelledError`` lives in
    ``test_drain_timeout_process_hard_exit_no_cancellederror``.
    """

    async def body(factory, engine):
        cmd_metrics.reset_for_tests()
        entered = asyncio.Event()
        release = asyncio.Event()
        blocker = _BlockingProvider(entered=entered, release=release, block_seconds=60.0)

        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                    create_sink=False,
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )

            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
                drain_seconds=0.3,
                hard_exit_on_drain_timeout=False,
            )

            real_execute = PublishRetryCommandExecutor.execute

            async def execute_blocking(*args, **kwargs):
                kwargs = dict(kwargs)
                kwargs["provider"] = blocker
                kwargs["hooks"] = ExecutorHooks(
                    after_barrier=lambda: worker.request_stop(),
                )
                kwargs["should_stop_before_barrier"] = worker._should_stop_before_barrier
                return await real_execute(*args, **kwargs)

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                with patch.object(
                    PublishRetryCommandClaimService,
                    "record_claim_audits",
                    AsyncMock(return_value=None),
                ):
                    with patch.object(
                        PublishRetryCommandExecutor,
                        "execute",
                        side_effect=execute_blocking,
                    ):
                        await worker.run_once()

            assert await asyncio.wait_for(entered.wait(), timeout=5.0)
            deadline = time.monotonic() + 2.0
            while worker.exit_code == EXIT_OK and time.monotonic() < deadline:
                await asyncio.sleep(0.05)

            assert worker.exit_code == EXIT_DRAIN_TIMEOUT
            assert worker.in_drain_territory is True
            assert blocker.invocation_count == 1
            snap = cmd_metrics.snapshot()
            assert snap["retry_command_worker_drain_timeout_total"] >= 1

            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "provider_write_started"
                assert cmd.provider_write_started_at is not None

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                assert await worker.run_once() == []
            assert blocker.invocation_count == 1

            release.set()
            # Soft path left the executor task pending; do not cancel it here.
            # Keep a reference via all_tasks and await completion after release.
            pending = [
                t
                for t in asyncio.all_tasks()
                if t.get_name().startswith("retry-command-executor:")
            ]
            for t in pending:
                try:
                    await asyncio.wait_for(asyncio.shield(t), timeout=2.0)
                except Exception:  # noqa: BLE001
                    pass

    asyncio.run(_with_staging_pg(body))


def test_drain_timeout_process_hard_exit_no_cancellederror():
    """Process-level: post-barrier drain timeout must not CancelledError provider.

    Reproduces top-level ``asyncio.run`` semantics. Hard exit via ``os._exit(3)``
    must happen before Runner.close cancels pending tasks.
    """
    marker_dir = Path(tempfile.mkdtemp(prefix="b2b1b-drain-proc-"))
    cancelled_marker = marker_dir / "provider_cancelled"
    started_marker = marker_dir / "provider_started"
    script = marker_dir / "drain_timeout_child.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import asyncio
            import logging
            import sys
            from pathlib import Path
            from types import SimpleNamespace

            # Ensure backend package importable when run as script.
            sys.path.insert(0, {str(REPO_ROOT / "backend")!r})

            from app.workers.publish_retry_command_worker import (
                EXIT_DRAIN_TIMEOUT,
                PublishRetryCommandWorker,
            )

            CANCELLED = Path({str(cancelled_marker)!r})
            STARTED = Path({str(started_marker)!r})

            async def provider_block():
                STARTED.write_text("1", encoding="utf-8")
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    CANCELLED.write_text("cancelled", encoding="utf-8")
                    raise

            async def amain():
                execution = SimpleNamespace(execution_backend="fake")
                worker = PublishRetryCommandWorker(
                    worker_id="proc-drain:1:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    execution=execution,
                    drain_seconds=0.25,
                    hard_exit_on_drain_timeout=True,
                )
                worker._enter_drain_territory()
                task = asyncio.create_task(
                    provider_block(),
                    name="retry-command-executor:proc-drain",
                )
                worker._active_task = task
                worker.request_stop()
                # Mirror post-barrier drain path used by run_forever/amain.
                await worker._await_active_executor(task)
                # Must not reach here under hard-exit path.
                sys.exit(99)

            def main():
                logging.basicConfig(level=logging.INFO)
                try:
                    asyncio.run(amain())
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else 1
                    raise SystemExit(code) from exc

            if __name__ == "__main__":
                main()
            """
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(REPO_ROOT / "backend"),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == EXIT_DRAIN_TIMEOUT, (
        f"expected exit {EXIT_DRAIN_TIMEOUT}, got {proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert started_marker.is_file(), "provider never entered"
    assert not cancelled_marker.is_file(), (
        "provider received CancelledError before process exit — "
        "asyncio.run cleanup still cancelled the post-barrier task"
    )


def test_signal_after_final_pre_barrier_check_no_cancellation():
    """SIGTERM after final stop check must not cancel; drain territory applies."""

    async def body(factory, engine):
        with _flags():
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="pending",
                    worker_id=WORKER_A,
                    commit=True,
                )

            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
                drain_seconds=5.0,
                hard_exit_on_drain_timeout=False,
            )
            cancelled = {"provider": False, "barrier": False}
            real_execute = PublishRetryCommandExecutor.execute
            real_cross = PublishRetryCommandBarrierService.cross_barrier
            check_passed = asyncio.Event()

            async def slow_cross(*args, **kwargs):
                assert worker.in_drain_territory is True
                # SIGTERM arrives after final check, while barrier TX in flight.
                worker.request_stop()
                try:
                    return await real_cross(*args, **kwargs)
                except asyncio.CancelledError:
                    cancelled["barrier"] = True
                    raise

            async def execute_with_race(*args, **kwargs):
                kwargs = dict(kwargs)
                orig_stop = worker._should_stop_before_barrier

                def stop_cb() -> bool:
                    result = orig_stop()
                    if not result:
                        check_passed.set()
                    return result

                kwargs["should_stop_before_barrier"] = stop_cb
                return await real_execute(*args, **kwargs)

            with patch.object(worker_mod, "AsyncSessionLocal", factory):
                with patch.object(
                    PublishRetryCommandClaimService,
                    "record_claim_audits",
                    AsyncMock(return_value=None),
                ):
                    with patch.object(
                        PublishRetryCommandBarrierService,
                        "cross_barrier",
                        side_effect=slow_cross,
                    ):
                        with patch.object(
                            PublishRetryCommandExecutor,
                            "execute",
                            side_effect=execute_with_race,
                        ):
                            await worker.run_once()

            assert check_passed.is_set()
            assert worker.in_drain_territory is True
            assert cancelled["barrier"] is False
            assert execution.provider.invocation_count == 1
            assert worker.exit_code == EXIT_OK
            async with factory() as db:
                cmd = (
                    await db.execute(
                        select(PublishRetryCommand).where(
                            PublishRetryCommand.id == fx.command_id,
                        ),
                    )
                ).scalar_one()
                assert cmd.status == "succeeded"

    asyncio.run(_with_staging_pg(body))


def test_hard_exit_guard_requires_fake_execution_and_territory():
    """os._exit path refuses backend=none / pre-barrier."""
    worker = PublishRetryCommandWorker(
        worker_id=WORKER_A,
        execution=None,
        hard_exit_on_drain_timeout=True,
    )
    worker._terminate_after_post_barrier_drain_timeout()
    assert worker.exit_code == EXIT_DRAIN_TIMEOUT

    fake = SimpleNamespace(execution_backend="fake")
    worker2 = PublishRetryCommandWorker(
        worker_id=WORKER_A,
        execution=fake,  # type: ignore[arg-type]
        hard_exit_on_drain_timeout=False,
    )
    # Outside territory — must not os._exit even with fake context.
    worker2._terminate_after_post_barrier_drain_timeout()
    assert worker2.exit_code == EXIT_DRAIN_TIMEOUT
    assert worker2.in_drain_territory is False

    src = inspect.getsource(
        PublishRetryCommandWorker._terminate_after_post_barrier_drain_timeout,
    )
    assert "os._exit" in src
    assert "execution_backend != \"fake\"" in src or "execution_backend != 'fake'" in src


def test_run_forever_exits_on_idle_stop_without_claim():
    async def body(factory, engine):
        with _flags(PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS=0.05):
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            worker = PublishRetryCommandWorker(
                worker_id=WORKER_A,
                execution=execution,
            )
            claim = AsyncMock(side_effect=AssertionError("must not claim after stop"))
            worker.request_stop()
            with patch.object(
                PublishRetryCommandClaimService,
                "claim_batch",
                claim,
            ):
                await worker.run_forever()
            assert claim.await_count == 0
            assert worker.exit_code == EXIT_OK

    asyncio.run(_with_staging_pg(body))


def test_marker_hooks_write_files_after_identity():
    async def body(factory, engine):
        marker_dir = _tmp_marker_dir()
        with _flags(PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR=str(marker_dir)):
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=_tmp_sink_path(),
                )
            assert execution.hooks is not None
            async with factory() as db:
                fx = await PublishRetryCommandStagingFixtureBuilder(
                    execution.staging_context,
                ).create(
                    db,
                    command_status="claimed",
                    worker_id=WORKER_A,
                    commit=True,
                )
            result = await execution.execute_claimed(
                factory,
                command_id=fx.command_id,
                worker_id=WORKER_A,
                correlation_id=fx.correlation_id,
            )
        assert result.outcome == "succeeded"
        for name in (
            "after_prepare",
            "after_barrier",
            "before_provider",
            "after_provider",
            "before_finalize",
        ):
            assert (marker_dir / name).is_file()

    asyncio.run(_with_staging_pg(body))


def test_fake_sink_path_alone_cannot_enable_fake_execution():
    """Setting FAKE_SINK_PATH without staging identity/bootstrap must not run fake."""
    with patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "none"):
        with patch.object(
            settings,
            "PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH",
            "/tmp/should-not-create-in-prod.jsonl",
        ):
            worker = PublishRetryCommandWorker(worker_id=WORKER_A, execution=None)
            assert worker._execution is None
            src = inspect.getsource(PublishRetryCommandWorker._orchestrate_after_claim)
            assert "FAKE_SINK_PATH" not in src
            assert "fake_sink" not in src.lower()


def test_no_failpoint_getenv_in_executor_prep_barrier():
    for path in (
        EXECUTOR_PATH,
        REPO_ROOT
        / "backend"
        / "app"
        / "services"
        / "publish_retry_command_preparation_service.py",
        REPO_ROOT
        / "backend"
        / "app"
        / "services"
        / "publish_retry_command_barrier_service.py",
        REPO_ROOT
        / "backend"
        / "app"
        / "services"
        / "publish_retry_command_finalization_service.py",
    ):
        src = path.read_text(encoding="utf-8")
        assert 'os.getenv("FAILPOINT' not in src
        assert "FAILPOINT" not in src


def test_worker_passes_should_stop_callback():
    handoff = inspect.getsource(PublishRetryCommandWorker._future_executor_handoff)
    assert "should_stop_before_barrier=self._should_stop_before_barrier" in handoff
    assert "stopped_before_barrier" in EXECUTOR_PATH.read_text(encoding="utf-8")


def test_compose_lifecycle_docs_and_drain_defaults():
    assert COMPOSE_STAGING.is_file()
    text_body = COMPOSE_STAGING.read_text(encoding="utf-8")
    assert 'restart: "no"' in text_body or "restart: 'no'" in text_body
    assert "retry-command" in text_body
    assert "china-smm-os-staging" in text_body
    env = ENV_STAGING_EXAMPLE.read_text(encoding="utf-8")
    assert "PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS" in env
    assert settings.PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS == 60.0
    assert settings.PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH == ""
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND == "none"
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED is False
    docs = (REPO_ROOT / "docs" / "STAGING_RETRY_COMMAND_WORKER.md").read_text(
        encoding="utf-8",
    )
    assert "os._exit(3)" in docs
    assert "asyncio.run" in docs


def test_batch_sequential_no_gather_in_worker():
    src = inspect.getsource(PublishRetryCommandWorker)
    assert "asyncio.gather" not in src
    assert "gather(" not in src
