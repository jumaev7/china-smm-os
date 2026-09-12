"""Staging hold/release campaign runner (B2b2-0B+0C) — LOCAL ONLY.

Proves: fixture seed → worker → durable marker → hold → release → terminal
completion. Does NOT SIGKILL. Does NOT restart. Does NOT prove no-replay
(B2b2-A). Does NOT deploy. Does NOT touch production.

Uses PublishRetryCommandStagingFixtureBuilder only (no raw SQL seed).

Examples:

  # In-process hold/release proof (requires china_smm_os_staging PostgreSQL)
  python scripts/run_staging_retry_command_hold_release_campaign.py \\
    --hold-point after_barrier \\
    --campaign-id demo-after-barrier

  # External release mode: wait for marker, write release file, exit 0
  python scripts/run_staging_retry_command_hold_release_campaign.py \\
    --mode release-only \\
    --evidence-root /var/lib/retry-command-staging \\
    --hold-point after_prepare \\
    --campaign-id demo
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

# Allow `python scripts/...` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ALLOWED_POINTS = (
    "after_prepare",
    "after_barrier",
    "before_provider",
    "provider_entered",
    "after_provider",
    "before_finalize",
)


def _wait_marker(path: Path, timeout: float) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return path
        time.sleep(0.05)
    raise SystemExit(f"marker timeout waiting for {path} ({timeout}s)")


def _release_only(args: argparse.Namespace) -> int:
    from app.services.publish_retry_command_staging_lifecycle_coordinator import (
        durable_write_marker,
        release_filename,
    )

    evidence = Path(args.evidence_root)
    marker_dir = Path(args.marker_dir) if args.marker_dir else evidence / "markers"
    control_dir = Path(args.control_dir) if args.control_dir else evidence / "control"
    campaign = args.campaign_id or "default"
    marker_path = marker_dir / campaign / args.hold_point
    release_path = control_dir / campaign / release_filename(args.hold_point)

    print(f"waiting for marker: {marker_path}", flush=True)
    ready = _wait_marker(marker_path, args.timeout)
    print(f"marker ready: {ready}", flush=True)
    print(f"marker contents:\n{ready.read_text(encoding='utf-8')}", flush=True)
    durable_write_marker(release_path, f"release=1\npoint={args.hold_point}\n")
    print(f"wrote release: {release_path}", flush=True)
    return 0


async def _run_inprocess(args: argparse.Namespace) -> int:
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.models.publish_retry_command import PublishRetryCommand
    from app.services.publish_retry_command_staging_fixture import (
        PublishRetryCommandStagingFixtureBuilder,
    )
    from app.services.publish_retry_command_staging_lifecycle_coordinator import (
        StagingLifecycleCoordinator,
    )
    from app.services.publish_retry_command_staging_worker_bootstrap import (
        bootstrap_staging_fake_worker_execution,
    )

    db_url = args.database_url or os.environ.get(
        "PUBLISH_RETRY_STAGING_PG_URL",
        getattr(settings, "DATABASE_URL", ""),
    )
    if not db_url:
        raise SystemExit("DATABASE_URL / --database-url required")

    evidence = Path(args.evidence_root or tempfile.mkdtemp(prefix="retry-staging-ev-"))
    marker_dir = Path(args.marker_dir) if args.marker_dir else evidence / "markers"
    control_dir = Path(args.control_dir) if args.control_dir else evidence / "control"
    campaign = args.campaign_id or f"hold-{uuid4().hex[:8]}"
    sink_path = evidence / "sink" / "fake-invocations.jsonl"
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    marker_dir.mkdir(parents=True, exist_ok=True)
    control_dir.mkdir(parents=True, exist_ok=True)

    # Patch settings for verified staging bootstrap.
    settings.APP_ENV = "staging"
    settings.PUBLISH_RETRY_COMMANDS_ENABLED = True
    settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED = True
    settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED = True
    settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED = True
    settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND = "fake"
    settings.PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED = True
    settings.PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE = "success"
    settings.PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE = 1
    settings.PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH = str(sink_path)
    settings.PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT = str(evidence)
    settings.PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR = str(marker_dir)
    settings.PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR = str(control_dir)
    settings.PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT = args.hold_point
    settings.PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID = campaign
    settings.PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS = float(
        args.hold_timeout,
    )
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.META_APP_SECRET = ""
    settings.DATABASE_URL = db_url

    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    worker_id = f"staging-hold-campaign:1:{uuid4()}"

    try:
        async with engine.connect() as conn:
            db_name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
            if db_name != "china_smm_os_staging":
                raise SystemExit(f"refusing non-staging database: {db_name}")

        async with engine.connect() as conn:
            execution = await bootstrap_staging_fake_worker_execution(
                conn,
                sink_path=sink_path,
            )
        coordinator = execution.lifecycle_coordinator
        if coordinator is None:
            raise SystemExit("lifecycle coordinator not constructed")
        coordinator.clear_campaign_artifacts()

        async with factory() as db:
            fx = await PublishRetryCommandStagingFixtureBuilder(
                execution.staging_context,
            ).create(
                db,
                command_status="claimed",
                worker_id=worker_id,
                commit=True,
            )

        async def _releaser() -> None:
            path = coordinator.marker_path(args.hold_point)
            deadline = time.monotonic() + float(args.timeout)
            while time.monotonic() < deadline:
                if path.is_file():
                    # Optional DB assertion windows for key points.
                    if args.hold_point == "after_barrier":
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
                    if args.hold_point == "after_prepare":
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
                    if execution.sink is not None and args.hold_point in {
                        "after_prepare",
                        "after_barrier",
                        "before_provider",
                    }:
                        assert execution.sink.count_for_command(fx.command_id) == 0
                    if (
                        execution.sink is not None
                        and args.hold_point == "provider_entered"
                    ):
                        assert execution.sink.count_for_command(fx.command_id) == 1
                    coordinator.write_release(args.hold_point)
                    print(f"released hold at {args.hold_point}", flush=True)
                    return
                await asyncio.sleep(0.05)
            raise TimeoutError(f"marker not observed: {path}")

        releaser = asyncio.create_task(_releaser())
        result = await execution.execute_claimed(
            factory,
            command_id=fx.command_id,
            worker_id=worker_id,
            correlation_id=fx.correlation_id,
        )
        await releaser

        print(
            f"outcome={result.outcome} ok={result.ok} "
            f"provider_invoked={result.provider_invoked} "
            f"invocation_count={result.provider_invocation_count}",
            flush=True,
        )
        print(f"marker_dir={marker_dir / campaign}", flush=True)
        print(f"sink={sink_path}", flush=True)
        if not result.ok or result.outcome != "succeeded":
            return 1
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("inprocess", "release-only"),
        default="inprocess",
    )
    parser.add_argument("--hold-point", required=True, choices=ALLOWED_POINTS)
    parser.add_argument("--campaign-id", default=None)
    parser.add_argument("--evidence-root", default=None)
    parser.add_argument("--marker-dir", default=None)
    parser.add_argument("--control-dir", default=None)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--hold-timeout",
        type=float,
        default=30.0,
        help="Worker-side hold timeout seconds (0 = wait until release)",
    )
    args = parser.parse_args(argv)

    if args.mode == "release-only":
        if not args.evidence_root and not args.marker_dir:
            raise SystemExit("release-only requires --evidence-root or --marker-dir")
        return _release_only(args)
    return asyncio.run(_run_inprocess(args))


if __name__ == "__main__":
    raise SystemExit(main())
