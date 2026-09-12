"""Update B2b1-B lifecycle campaign helper for campaign-scoped durable markers.

Still supports SIGTERM coordination for B2b1. For B2b2-A SIGKILL + restart
no-replay proofs use:

  python scripts/run_staging_retry_command_sigkill_restart_campaign.py --help

Prefer hold/release runner for 0B+0C proofs:

  python scripts/run_staging_retry_command_hold_release_campaign.py --help
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ALLOWED_WAIT = (
    "after_prepare",
    "after_barrier",
    "before_provider",
    "provider_entered",
    "after_provider",
    "before_finalize",
    "idle",
)


def _wait_marker(path: Path, timeout: float) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return path
        time.sleep(0.05)
    raise SystemExit(f"marker timeout waiting for {path} ({timeout}s)")


def _send_sigterm_pid(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
    print(f"sent SIGTERM to pid={pid}", flush=True)


def _send_sigterm_compose(service: str, compose_file: str, project: str) -> None:
    cmd = [
        "docker",
        "compose",
        "-f",
        compose_file,
        "-p",
        project,
        "kill",
        "-s",
        "SIGTERM",
        service,
    ]
    print("running:", " ".join(cmd), flush=True)
    subprocess.check_call(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--marker-dir",
        required=True,
        help="Markers root (…/markers). Campaign id nests underneath.",
    )
    parser.add_argument(
        "--campaign-id",
        default="default",
        help="Staging campaign id (observability/coordination only)",
    )
    parser.add_argument(
        "--wait",
        required=True,
        choices=ALLOWED_WAIT,
        help="Marker to wait for before signaling (idle = signal immediately)",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--pid", type=int, default=None, help="Worker OS pid")
    parser.add_argument(
        "--compose-service",
        default=None,
        help="Compose service name (e.g. publish-retry-command-worker)",
    )
    parser.add_argument(
        "--compose-file",
        default="docker-compose.staging.yml",
    )
    parser.add_argument(
        "--compose-project",
        default="china-smm-os-staging",
    )
    args = parser.parse_args(argv)

    if args.wait != "idle":
        path = Path(args.marker_dir) / args.campaign_id / args.wait
        ready = _wait_marker(path, args.timeout)
        print(f"marker ready: {ready}", flush=True)

    if args.pid is not None:
        _send_sigterm_pid(args.pid)
        return 0
    if args.compose_service:
        _send_sigterm_compose(
            args.compose_service,
            args.compose_file,
            args.compose_project,
        )
        return 0

    raise SystemExit("provide --pid or --compose-service")


if __name__ == "__main__":
    raise SystemExit(main())
