"""Staging lifecycle campaign helper (B2b1-B) — LOCAL ONLY.

Coordinates marker wait → SIGTERM against a running staging worker process/container.

Does NOT deploy. Does NOT touch production. Does NOT implement B2b2 restart proof.

Examples (Linux/compose):

  # Wait for after_prepare marker then SIGTERM (pre-barrier campaign)
  python scripts/run_staging_retry_command_lifecycle_campaign.py \\
    --marker-dir /tmp/china-smm-os-staging-markers \\
    --wait after_prepare \\
    --pid 12345

  # Wait for after_barrier then SIGTERM (post-barrier drain campaign)
  python scripts/run_staging_retry_command_lifecycle_campaign.py \\
    --marker-dir /tmp/china-smm-os-staging-markers \\
    --wait after_barrier \\
    --compose-service publish-retry-command-worker
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _wait_marker(marker_dir: Path, name: str, timeout: float) -> Path:
    path = marker_dir / name
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
        help="Directory with DI marker files (after_prepare / after_barrier / ...)",
    )
    parser.add_argument(
        "--wait",
        required=True,
        choices=("after_prepare", "after_barrier", "before_provider", "idle"),
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
        path = _wait_marker(Path(args.marker_dir), args.wait, args.timeout)
        print(f"marker ready: {path}", flush=True)

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
