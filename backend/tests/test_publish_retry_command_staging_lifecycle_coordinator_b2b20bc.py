"""Phase 3C.1C-D2-B2b2-0B+0C — staging lifecycle coordinator.

LOCAL/CI disposable PostgreSQL only (china_smm_os_staging).

Proves:
- durable marker write (flush/fsync/rename)
- hold/release at after_prepare / after_barrier / provider_entered / before_finalize
- fake outcome independent of hold point
- stale release isolation via campaign id
- production/backend=none cannot construct coordinator
- canonical services do not import coordinator
"""
from __future__ import annotations

import ast
import asyncio
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_retry_command import PublishRetryCommand
from app.services.publish_retry_command_staging_fixture import (
    PublishRetryCommandStagingFixtureBuilder,
)
from app.services.publish_retry_command_staging_identity import (
    REQUIRED_DATABASE_NAME,
)
from app.services.publish_retry_command_staging_lifecycle_coordinator import (
    ALLOWED_LIFECYCLE_POINTS,
    StagingLifecycleCoordinationError,
    StagingLifecycleCoordinator,
    StagingLifecycleHoldTimeoutError,
    durable_write_marker,
    validate_staging_evidence_path,
)
from app.services.publish_retry_command_staging_worker_bootstrap import (
    bootstrap_staging_fake_worker_execution,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "backend" / "app" / "services"
COMPOSE_STAGING = REPO_ROOT / "docker-compose.staging.yml"
ENV_STAGING_EXAMPLE = REPO_ROOT / ".env.staging.example"
COORD_PATH = SERVICES_DIR / "publish_retry_command_staging_lifecycle_coordinator.py"

DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/china_smm_os_staging"
)
WORKER_A = "staging-b2b20bc:1:cccccccc-cccc-cccc-cccc-cccccccccccc"


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
        "TELEGRAM_BOT_TOKEN": "",
        "META_APP_SECRET": "",
        "PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT": "",
        "PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID": "",
        "PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS": 0.0,
        "PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT": "",
        "PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR": "",
        "PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR": "",
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


async def _ensure_database() -> str:
    url = _pg_url()
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
        pytest.skip(f"PostgreSQL unavailable for B2b2-0B+0C tests: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL unavailable for B2b2-0B+0C tests: {exc}")
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


def _evidence_tree() -> tuple[Path, Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="b2b20bc-ev-"))
    markers = root / "markers"
    control = root / "control"
    markers.mkdir(parents=True, exist_ok=True)
    control.mkdir(parents=True, exist_ok=True)
    return root, markers, control


def _tmp_sink_path(evidence: Path) -> Path:
    path = evidence / "sink" / "invocations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _fake_staging_context():
    """Build a verified context via the identity module's private token.

    Unit-only path tests that do not need live DB still require the capability.
    """
    from app.services import publish_retry_command_staging_identity as ident

    return ident.VerifiedRetryCommandStagingContext(
        app_env="staging",
        execution_backend="fake",
        fake_execution_allowed=True,
        current_database=REQUIRED_DATABASE_NAME,
        _capability_token=ident._CAPABILITY_TOKEN,
    )


# ---------------------------------------------------------------------------
# Unit: durability / paths / release
# ---------------------------------------------------------------------------


def test_durable_write_marker_fsync_visible_to_external_reader():
    root = Path(tempfile.mkdtemp(prefix="b2b20bc-dur-"))
    path = root / "marker"
    seen = threading.Event()
    payload_holder: list[str] = []

    def reader() -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if path.is_file():
                payload_holder.append(path.read_text(encoding="utf-8"))
                seen.set()
                return
            time.sleep(0.01)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    durable_write_marker(path, "point=after_prepare\ncommand_id=abc\n")
    assert seen.wait(5.0)
    t.join(timeout=1.0)
    assert payload_holder
    assert "point=after_prepare" in payload_holder[0]
    assert "command_id=abc" in payload_holder[0]
    # Implementation must fsync (not write_text alone).
    src = COORD_PATH.read_text(encoding="utf-8")
    assert "os.fsync" in src
    assert "os.replace" in src


def test_path_validation_rejects_root_and_outside():
    evidence = Path(tempfile.mkdtemp(prefix="b2b20bc-path-"))
    with pytest.raises(StagingLifecycleCoordinationError) as exc:
        validate_staging_evidence_path("/", evidence_root=evidence, what="marker")
    assert exc.value.reason in {
        "path_is_filesystem_root",
        "path_outside_evidence_root",
    }
    with pytest.raises(StagingLifecycleCoordinationError) as exc2:
        validate_staging_evidence_path(
            tempfile.mkdtemp(prefix="outside-"),
            evidence_root=evidence,
            what="marker",
        )
    assert exc2.value.reason == "path_outside_evidence_root"
    # Explicit drive-root style rejection when evidence itself is not root.
    drive_root = Path(evidence.anchor)
    with pytest.raises(StagingLifecycleCoordinationError) as exc3:
        validate_staging_evidence_path(
            drive_root,
            evidence_root=evidence,
            what="marker",
        )
    assert exc3.value.reason in {
        "path_is_filesystem_root",
        "path_outside_evidence_root",
    }


def test_coordinator_requires_verified_staging_context():
    evidence, markers, control = _evidence_tree()
    with pytest.raises(StagingLifecycleCoordinationError):
        StagingLifecycleCoordinator(
            staging_context=MagicMock(),  # type: ignore[arg-type]
            evidence_root=evidence,
            marker_dir=markers,
            control_dir=control,
        )


def test_stale_release_isolated_by_campaign_id():
    async def body() -> None:
        ctx = _fake_staging_context()
        evidence, markers, control = _evidence_tree()
        stale = StagingLifecycleCoordinator(
            staging_context=ctx,
            evidence_root=evidence,
            marker_dir=markers,
            control_dir=control,
            campaign_id="campaign-old",
            hold_point="after_prepare",
            hold_timeout_seconds=0.3,
            poll_seconds=0.05,
        )
        fresh = StagingLifecycleCoordinator(
            staging_context=ctx,
            evidence_root=evidence,
            marker_dir=markers,
            control_dir=control,
            campaign_id="campaign-new",
            hold_point="after_prepare",
            hold_timeout_seconds=0.3,
            poll_seconds=0.05,
        )
        stale.write_release("after_prepare")
        with pytest.raises(StagingLifecycleHoldTimeoutError):
            await fresh.mark_and_maybe_hold("after_prepare", command_id="cmd-1")
        # Stale release still present; fresh campaign did not consume it.
        assert stale.release_path("after_prepare").is_file()
        assert not fresh.release_path("after_prepare").is_file()

    asyncio.run(body())


def test_release_consumed_exactly_once():
    async def body() -> None:
        ctx = _fake_staging_context()
        evidence, markers, control = _evidence_tree()
        coord = StagingLifecycleCoordinator(
            staging_context=ctx,
            evidence_root=evidence,
            marker_dir=markers,
            control_dir=control,
            campaign_id="once",
            hold_point="after_barrier",
            hold_timeout_seconds=2.0,
            poll_seconds=0.05,
        )

        async def releaser() -> None:
            while not coord.marker_path("after_barrier").is_file():
                await asyncio.sleep(0.02)
            coord.write_release("after_barrier")

        task = asyncio.create_task(releaser())
        await coord.mark_and_maybe_hold("after_barrier", command_id="c1")
        await task
        assert not coord.release_path("after_barrier").is_file()
        assert coord.marker_path("after_barrier").is_file()

    asyncio.run(body())


def test_unsupported_hold_point_rejected():
    with pytest.raises(StagingLifecycleCoordinationError) as exc:
        StagingLifecycleCoordinator.from_verified_settings(
            _fake_staging_context(),
            MagicMock(
                PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT=str(
                    Path(tempfile.mkdtemp(prefix="b2b20bc-bad-")),
                ),
                PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR="",
                PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR="",
                PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT="before_claim",
                PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID="",
                PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS=0,
            ),
        )
    assert exc.value.reason == "unsupported_hold_point"


def test_from_settings_disabled_when_unset():
    coord = StagingLifecycleCoordinator.from_verified_settings(
        _fake_staging_context(),
        MagicMock(
            PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT="",
            PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR="",
            PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR="",
            PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT="",
            PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID="",
            PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS=0,
        ),
    )
    assert coord is None


def test_canonical_services_do_not_import_coordinator():
    banned = (
        "publish_retry_command_claim_service.py",
        "publish_retry_command_preparation_service.py",
        "publish_retry_command_barrier_service.py",
        "publish_retry_command_finalization_service.py",
        "publish_retry_command_executor.py",
    )
    for name in banned:
        path = SERVICES_DIR / name
        src = path.read_text(encoding="utf-8")
        assert "staging_lifecycle_coordinator" not in src
        assert "StagingLifecycleCoordinator" not in src
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                text = ast.get_source_segment(src, node) or ""
                assert "lifecycle_coordinator" not in text


def test_production_settings_defaults_ignore_coordination():
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND == "none"
    assert settings.PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT == ""
    assert settings.PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR == ""
    assert settings.PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR == ""
    assert settings.PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT == ""
    assert settings.PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID == ""


def test_backend_none_worker_source_ignores_hold_env():
    worker_src = (
        REPO_ROOT
        / "backend"
        / "app"
        / "workers"
        / "publish_retry_command_worker.py"
    ).read_text(encoding="utf-8")
    assert "STAGING_HOLD_POINT" not in worker_src
    assert "StagingLifecycleCoordinator" not in worker_src


# ---------------------------------------------------------------------------
# Integration: hold/release campaigns
# ---------------------------------------------------------------------------


async def _hold_release_campaign(
    factory,
    engine,
    *,
    hold_point: str,
    campaign_id: str,
    assert_during_hold,
) -> None:
    evidence, markers, control = _evidence_tree()
    sink = _tmp_sink_path(evidence)
    with _flags(
        PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT=str(evidence),
        PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR=str(markers),
        PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR=str(control),
        PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT=hold_point,
        PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID=campaign_id,
        PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS=8.0,
        PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH=str(sink),
    ):
        async with engine.connect() as conn:
            execution = await bootstrap_staging_fake_worker_execution(
                conn,
                sink_path=sink,
            )
        assert execution.lifecycle_coordinator is not None
        coord = execution.lifecycle_coordinator
        coord.clear_campaign_artifacts()

        async with factory() as db:
            fx = await PublishRetryCommandStagingFixtureBuilder(
                execution.staging_context,
            ).create(
                db,
                command_status="claimed",
                worker_id=WORKER_A,
                commit=True,
            )

        async def releaser() -> None:
            path = coord.marker_path(hold_point)
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                if path.is_file():
                    await assert_during_hold(factory, execution, fx, coord, path)
                    coord.write_release(hold_point)
                    return
                await asyncio.sleep(0.05)
            raise AssertionError(f"marker not observed for {hold_point}: {path}")

        task = asyncio.create_task(releaser())
        result = await execution.execute_claimed(
            factory,
            command_id=fx.command_id,
            worker_id=WORKER_A,
            correlation_id=fx.correlation_id,
        )
        await task
        assert result.ok is True
        assert result.outcome == "succeeded"
        assert result.provider_invocation_count == 1
        # All executor points + provider_entered should have markers.
        for point in (
            "after_prepare",
            "after_barrier",
            "before_provider",
            "provider_entered",
            "after_provider",
            "before_finalize",
        ):
            assert coord.marker_path(point).is_file(), point


def test_hold_release_after_prepare():
    async def during(factory, execution, fx, coord, path):
        text_body = path.read_text(encoding="utf-8")
        assert "point=after_prepare" in text_body
        assert f"command_id={fx.command_id}" in text_body
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
        assert execution.sink is not None
        assert execution.sink.count_for_command(fx.command_id) == 0

    async def body(factory, engine):
        await _hold_release_campaign(
            factory,
            engine,
            hold_point="after_prepare",
            campaign_id="hr-after-prepare",
            assert_during_hold=during,
        )

    asyncio.run(_with_staging_pg(body))


def test_hold_release_after_barrier_db_state_and_provider_zero():
    async def during(factory, execution, fx, coord, path):
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
            assert cmd.lease_expires_at is None
        assert execution.sink is not None
        assert execution.sink.count_for_command(fx.command_id) == 0
        assert getattr(execution.provider, "invocation_count", 0) == 0

    async def body(factory, engine):
        await _hold_release_campaign(
            factory,
            engine,
            hold_point="after_barrier",
            campaign_id="hr-after-barrier",
            assert_during_hold=during,
        )

    asyncio.run(_with_staging_pg(body))


def test_hold_release_provider_entered_sink_started():
    async def during(factory, execution, fx, coord, path):
        assert execution.sink is not None
        assert execution.sink.count_for_command(fx.command_id) == 1
        assert "point=provider_entered" in path.read_text(encoding="utf-8")

    async def body(factory, engine):
        await _hold_release_campaign(
            factory,
            engine,
            hold_point="provider_entered",
            campaign_id="hr-provider-entered",
            assert_during_hold=during,
        )

    asyncio.run(_with_staging_pg(body))


def test_hold_release_before_finalize_after_provider_effect():
    async def during(factory, execution, fx, coord, path):
        assert execution.sink is not None
        assert execution.sink.count_for_command(fx.command_id) == 1
        assert coord.marker_path("after_provider").is_file()
        assert coord.marker_path("before_finalize").is_file()
        async with factory() as db:
            cmd = (
                await db.execute(
                    select(PublishRetryCommand).where(
                        PublishRetryCommand.id == fx.command_id,
                    ),
                )
            ).scalar_one()
            # Finalizer not committed yet — still barrier state.
            assert cmd.status == "provider_write_started"

    async def body(factory, engine):
        await _hold_release_campaign(
            factory,
            engine,
            hold_point="before_finalize",
            campaign_id="hr-before-finalize",
            assert_during_hold=during,
        )

    asyncio.run(_with_staging_pg(body))


def test_hold_timeout_fails_before_provider_without_invocation():
    async def body(factory, engine):
        evidence, markers, control = _evidence_tree()
        sink = _tmp_sink_path(evidence)
        with _flags(
            PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT=str(evidence),
            PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR=str(markers),
            PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR=str(control),
            PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT="after_barrier",
            PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID="timeout-camp",
            PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS=0.4,
            PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH=str(sink),
        ):
            async with engine.connect() as conn:
                execution = await bootstrap_staging_fake_worker_execution(
                    conn,
                    sink_path=sink,
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
            with pytest.raises(StagingLifecycleHoldTimeoutError):
                await execution.execute_claimed(
                    factory,
                    command_id=fx.command_id,
                    worker_id=WORKER_A,
                    correlation_id=fx.correlation_id,
                )
            assert execution.sink is not None
            assert execution.sink.count_for_command(fx.command_id) == 0
            assert execution.lifecycle_coordinator is not None
            assert execution.lifecycle_coordinator.marker_path(
                "after_barrier",
            ).is_file()

    asyncio.run(_with_staging_pg(body))


def test_fake_outcome_independent_of_hold_point():
    """Hold point config must not overload FakeProviderMode names."""
    assert "block_before_provider" not in ALLOWED_LIFECYCLE_POINTS
    assert "after_barrier" in ALLOWED_LIFECYCLE_POINTS
    from app.services.publish_retry_command_provider_port import FakeProviderMode

    modes = {m.value for m in FakeProviderMode}
    assert modes.isdisjoint(ALLOWED_LIFECYCLE_POINTS)


def test_compose_and_env_wiring_staging_only():
    compose = COMPOSE_STAGING.read_text(encoding="utf-8")
    assert "/var/lib/retry-command-staging" in compose
    assert "STAGING_HOLD_POINT" in compose
    assert "STAGING_CONTROL_DIR" in compose
    assert "staging_evidence" in compose
    # No production compose defaults for these controls.
    prod_compose = REPO_ROOT / "docker-compose.yml"
    if prod_compose.is_file():
        prod = prod_compose.read_text(encoding="utf-8")
        assert "STAGING_HOLD_POINT" not in prod
        assert "retry-command-staging" not in prod
    env = ENV_STAGING_EXAMPLE.read_text(encoding="utf-8")
    assert "STAGING_HOLD_POINT" in env
    assert "STAGING_CONTROL_DIR" in env


def test_hold_release_campaign_script_committed():
    script = (
        REPO_ROOT
        / "backend"
        / "scripts"
        / "run_staging_retry_command_hold_release_campaign.py"
    )
    assert script.is_file()
    src = script.read_text(encoding="utf-8")
    assert "PublishRetryCommandStagingFixtureBuilder" in src
    assert "docker kill -s SIGKILL" not in src
    assert "os.kill" not in src
    assert "signal.SIGKILL" not in src


def test_fixture_builder_still_imported_for_campaigns():
    # Raw-SQL removal proof: campaign runner uses fixture builder symbol.
    script = (
        REPO_ROOT
        / "backend"
        / "scripts"
        / "run_staging_retry_command_hold_release_campaign.py"
    )
    src = script.read_text(encoding="utf-8")
    assert "PublishRetryCommandStagingFixtureBuilder" in src
    assert "INSERT INTO publish_retry_command" not in src.lower()
    assert "text(\"INSERT" not in src
