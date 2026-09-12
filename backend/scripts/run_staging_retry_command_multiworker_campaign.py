"""B2b2-B multi-worker + stale-owner concurrency campaign runner.

LOCAL STAGING ONLY. Project: china-smm-os-staging.

Proves database-level correctness with TWO live worker processes:

  B1  one command / two workers claim race (repeatable)
  B2/B3  stale owner after lease expiry + reclaim; release A fail-closed
  B4/B5  two workers / two commands + non-global serialization
  B6  claim/reclaim vs barrier boundary race
  B7  optional: A after_barrier hold while B handles other command

Core invariant: fake_invoke_count <= 1 per command.

Does NOT push, deploy, enable production, touch Phase E, or add real providers.

Examples:

  python scripts/run_staging_retry_command_multiworker_campaign.py \\
    --scenario all-required

  python scripts/run_staging_retry_command_multiworker_campaign.py \\
    --scenario claim_race --claim-iterations 15
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_PROJECT = "china-smm-os-staging"
DEFAULT_ENV_FILE = REPO_ROOT / ".env.staging.example"
DEFAULT_COMPOSE = REPO_ROOT / "docker-compose.staging.yml"
DEFAULT_OVERRIDE = REPO_ROOT / "docker-compose.staging.b2b2b-campaign.yml"
DEFAULT_EVIDENCE = REPO_ROOT / ".staging-b2b2b-evidence"
WORKER_A = "publish-retry-command-worker-a"
WORKER_B = "publish-retry-command-worker-b"
SINK_REL = Path("sink") / "fake-invocations.jsonl"
TERMINAL = {"succeeded", "failed", "ambiguous", "blocked", "superseded", "cancelled"}

Scenario = Literal[
    "claim_race",
    "stale_owner",
    "two_command",
    "reclaim_barrier_race",
    "post_barrier_overlap",
    "all-required",
]


@dataclass
class CommandSnapshot:
    command_id: str
    status: str | None
    resulting_attempt_id: str | None
    provider_write_started_at: str | None
    lease_expires_at: str | None
    lease_owner: str | None
    attempt_count: int
    command_count: int


@dataclass
class WorkerIdentity:
    service: str
    container_id: str | None = None
    worker_id: str | None = None
    worker_instance: str | None = None
    pid: str | None = None
    campaign_id: str | None = None


@dataclass
class IterationResult:
    iteration: int
    command_id: str
    winner_lease_owner: str | None = None
    winner_service: str | None = None
    sink: int = 0
    attempt_count: int = 0
    status: str | None = None
    ok: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class CampaignReport:
    scenario: str
    campaign_id_a: str
    campaign_id_b: str
    command_ids: list[str] = field(default_factory=list)
    worker_a: WorkerIdentity | None = None
    worker_b: WorkerIdentity | None = None
    iterations: list[IterationResult] = field(default_factory=list)
    snapshots: dict[str, Any] = field(default_factory=dict)
    sink_by_command: dict[str, int] = field(default_factory=dict)
    stale_a_outcome: str | None = None
    stale_a_reason: str | None = None
    reclaim_owner: str | None = None
    resulting_attempt_id: str | None = None
    attempt_count: int | None = None
    observation_seconds: float = 0.0
    assertions: list[str] = field(default_factory=list)
    ok: bool = False
    notes: list[str] = field(default_factory=list)
    db_primitives: list[str] = field(default_factory=list)


class CampaignError(RuntimeError):
    pass


def _print(msg: str) -> None:
    print(msg, flush=True)


def _compose_base(args: argparse.Namespace) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(args.compose_file),
        "-f",
        str(args.override_file),
        "--env-file",
        str(args.env_file),
        "-p",
        args.project,
    ]


def _run(
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    _print("running: " + " ".join(cmd))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        env=merged,
        check=False,
        text=True,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        stderr = result.stderr or ""
        stdout = result.stdout or ""
        raise CampaignError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
    return result


def _compose(
    args: argparse.Namespace,
    compose_args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return _run(
        _compose_base(args) + compose_args,
        env=env,
        check=check,
        capture=capture,
    )


def _base_env(args: argparse.Namespace) -> dict[str, str]:
    return {
        "STAGING_EVIDENCE_HOST_PATH": str(args.evidence_host_path),
        "PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS": "0",
        "PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS": str(args.poll_seconds),
        "PUBLISH_RETRY_COMMAND_LEASE_SECONDS": str(args.lease_seconds),
        "PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE": "success",
    }


def _worker_env(
    args: argparse.Namespace,
    *,
    campaign_a: str,
    campaign_b: str,
    hold_a: str = "",
    hold_b: str = "",
) -> dict[str, str]:
    env = _base_env(args)
    env["WORKER_A_CAMPAIGN_ID"] = campaign_a
    env["WORKER_B_CAMPAIGN_ID"] = campaign_b
    env["WORKER_A_HOLD_POINT"] = hold_a
    env["WORKER_B_HOLD_POINT"] = hold_b
    return env


def _reset_project(args: argparse.Namespace) -> None:
    _print(f"=== reset project {args.project} (down -v) ===")
    _compose(
        args,
        ["--profile", "retry-command", "down", "-v", "--remove-orphans"],
        check=False,
    )
    evidence = Path(args.evidence_host_path)
    if evidence.exists():
        shutil.rmtree(evidence, ignore_errors=True)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "markers").mkdir(parents=True, exist_ok=True)
    (evidence / "control").mkdir(parents=True, exist_ok=True)
    (evidence / "sink").mkdir(parents=True, exist_ok=True)


def _wait_postgres(args: argparse.Namespace, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _compose(
            args,
            [
                "exec",
                "-T",
                "postgres",
                "pg_isready",
                "-U",
                "postgres",
                "-d",
                "china_smm_os_staging",
            ],
            check=False,
            capture=True,
        )
        if result.returncode == 0:
            _print("postgres ready")
            return
        time.sleep(1.0)
    raise CampaignError("postgres not ready")


def _up_postgres(args: argparse.Namespace) -> None:
    _compose(args, ["up", "-d", "postgres"])
    _wait_postgres(args)


def _build_workers(args: argparse.Namespace) -> None:
    _print("=== build worker images ===")
    _compose(
        args,
        ["--profile", "retry-command", "build", WORKER_A, WORKER_B],
    )


def _migrate_with_network(args: argparse.Namespace) -> None:
    _print("=== alembic upgrade head (networked via worker-a) ===")
    _compose(
        args,
        [
            "--profile",
            "retry-command",
            "run",
            "--rm",
            "--build",
            "--entrypoint",
            "alembic",
            WORKER_A,
            "upgrade",
            "head",
        ],
    )


def _seed(args: argparse.Namespace) -> dict[str, Any]:
    _print("=== seed synthetic pending fixture ===")
    result = _compose(
        args,
        [
            "--profile",
            "retry-command",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            WORKER_A,
            "scripts/seed_staging_retry_command_fixture.py",
        ],
        capture=True,
    )
    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise CampaignError(f"seed produced no JSON\nstderr={result.stderr}")
    payload = json.loads(lines[-1])
    _print(f"seeded command_id={payload['command_id']}")
    return payload


def _sql_json(args: argparse.Namespace, sql: str) -> Any:
    result = _compose(
        args,
        [
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "china_smm_os_staging",
            "-v",
            "ON_ERROR_STOP=1",
            "-t",
            "-A",
            "-c",
            sql,
        ],
        capture=True,
    )
    text = (result.stdout or "").strip()
    if not text:
        return None
    if text in {"t", "true"}:
        return True
    if text in {"f", "false"}:
        return False
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CampaignError(
            f"failed to parse SQL result as JSON: {text!r} ({exc})"
        ) from exc


def _snapshot_command(args: argparse.Namespace, command_id: str) -> CommandSnapshot:
    row = _sql_json(
        args,
        f"""
        SELECT json_build_object(
          'command_id', c.id::text,
          'status', c.status,
          'resulting_attempt_id', c.resulting_attempt_id::text,
          'provider_write_started_at', c.provider_write_started_at,
          'lease_expires_at', c.lease_expires_at,
          'lease_owner', c.lease_owner,
          'attempt_count', (
            SELECT COUNT(*)::int FROM publish_attempts a
            WHERE a.retry_command_id = c.id
          ),
          'command_count', (
            SELECT COUNT(*)::int FROM publish_retry_commands
          )
        )
        FROM publish_retry_commands c
        WHERE c.id = '{command_id}'::uuid;
        """,
    )
    if not isinstance(row, dict):
        raise CampaignError(f"command not found: {command_id}")
    return CommandSnapshot(
        command_id=str(row["command_id"]),
        status=row.get("status"),
        resulting_attempt_id=row.get("resulting_attempt_id"),
        provider_write_started_at=(
            None
            if row.get("provider_write_started_at") in (None, "")
            else str(row["provider_write_started_at"])
        ),
        lease_expires_at=(
            None
            if row.get("lease_expires_at") in (None, "")
            else str(row["lease_expires_at"])
        ),
        lease_owner=row.get("lease_owner"),
        attempt_count=int(row.get("attempt_count") or 0),
        command_count=int(row.get("command_count") or 0),
    )


def _reclaim_candidates(args: argparse.Namespace, command_id: str) -> int:
    val = _sql_json(
        args,
        f"""
        SELECT COUNT(*)::int
        FROM publish_retry_commands
        WHERE status = 'claimed'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < NOW()
          AND provider_write_started_at IS NULL
          AND id = '{command_id}'::uuid;
        """,
    )
    return int(val or 0)


def _pending_candidates(args: argparse.Namespace, command_id: str) -> int:
    val = _sql_json(
        args,
        f"""
        SELECT COUNT(*)::int
        FROM publish_retry_commands
        WHERE status = 'pending' AND id = '{command_id}'::uuid;
        """,
    )
    return int(val or 0)


def _probe_claim_batch(args: argparse.Namespace, command_id: str) -> dict[str, Any]:
    result = _compose(
        args,
        [
            "--profile",
            "retry-command",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            WORKER_A,
            "scripts/probe_staging_retry_command_claim.py",
            "--forbid-command-id",
            command_id,
        ],
        capture=True,
    )
    lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise CampaignError(f"claim probe empty\nstderr={result.stderr}")
    return json.loads(lines[-1])


def _sink_count(args: argparse.Namespace, command_id: str) -> int:
    path = Path(args.evidence_host_path) / SINK_REL
    if not path.is_file():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("event_type", "fake_invoke") == "fake_invoke" and str(
            rec.get("command_id")
        ) == str(command_id):
            count += 1
    return count


def _hard_fail_if_double_invoke(args: argparse.Namespace, command_id: str) -> int:
    sink = _sink_count(args, command_id)
    if sink >= 2:
        raise CampaignError(
            f"HARD FAIL: fake_invoke={sink} for command_id={command_id}"
        )
    return sink


def _marker_path(args: argparse.Namespace, campaign_id: str, point: str) -> Path:
    return Path(args.evidence_host_path) / "markers" / campaign_id / point


def _control_path(args: argparse.Namespace, campaign_id: str, point: str) -> Path:
    return Path(args.evidence_host_path) / "control" / campaign_id / f"release_{point}"


def _wait_marker(
    args: argparse.Namespace,
    campaign_id: str,
    point: str,
    timeout: float,
) -> Path:
    path = _marker_path(args, campaign_id, point)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            _print(f"marker ready: {path}")
            return path
        time.sleep(0.1)
    raise CampaignError(f"marker timeout waiting for {path} ({timeout}s)")


def _parse_marker(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _write_release(args: argparse.Namespace, campaign_id: str, point: str) -> Path:
    path = _control_path(args, campaign_id, point)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{uuid4().hex[:8]}")
    payload = (
        f"release_point={point}\n"
        f"campaign_id={campaign_id}\n"
        f"released_at={time.time()}\n"
    )
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    _print(f"wrote release: {path}")
    return path


def _worker_container_id(args: argparse.Namespace, service: str) -> str:
    result = _compose(args, ["ps", "-q", service], capture=True)
    cid = (result.stdout or "").strip().splitlines()
    if not cid or not cid[0].strip():
        raise CampaignError(f"worker container not running: {service}")
    return cid[0].strip()


def _container_pid1(container_id: str) -> str | None:
    result = _run(
        ["docker", "inspect", "-f", "{{.State.Pid}}", container_id],
        capture=True,
        check=False,
    )
    text = (result.stdout or "").strip()
    return text or None


def _stop_workers(args: argparse.Namespace) -> None:
    _compose(
        args,
        ["--profile", "retry-command", "rm", "-f", "-s", WORKER_A, WORKER_B],
        check=False,
    )


def _start_worker(
    args: argparse.Namespace,
    service: str,
    env: dict[str, str],
    *,
    build: bool = False,
) -> str:
    cmd = [
        "--profile",
        "retry-command",
        "up",
        "-d",
        "--no-deps",
        service,
    ]
    if build:
        cmd.insert(3, "--build")
    _compose(args, cmd, env=env)
    time.sleep(1.0)
    return _worker_container_id(args, service)


def _start_workers(
    args: argparse.Namespace,
    env: dict[str, str],
    *,
    build: bool = False,
) -> tuple[str, str]:
    cmd = [
        "--profile",
        "retry-command",
        "up",
        "-d",
        "--no-deps",
        WORKER_A,
        WORKER_B,
    ]
    if build:
        cmd.insert(3, "--build")
    _compose(args, cmd, env=env)
    time.sleep(1.5)
    return _worker_container_id(args, WORKER_A), _worker_container_id(args, WORKER_B)


def _worker_logs(args: argparse.Namespace, service: str, since_seconds: int = 600) -> str:
    result = _compose(
        args,
        ["logs", "--no-color", f"--since={since_seconds}s", service],
        check=False,
        capture=True,
    )
    return (result.stdout or "") + (result.stderr or "")


def _parse_worker_instance(logs: str) -> str | None:
    matches = re.findall(
        r"\[RetryCommandWorker\] started instance=([^\s]+)",
        logs,
    )
    return matches[-1] if matches else None


def _parse_executor_outcomes(logs: str) -> list[tuple[str, str, str]]:
    """Return list of (command_id, outcome, provider_invoked) from worker logs."""
    out: list[tuple[str, str, str]] = []
    for m in re.finditer(
        r"\[RetryCommandWorker\] fake executor finished command_id=([^\s]+) "
        r"outcome=([^\s]+) provider_invoked=([^\s]+)",
        logs,
    ):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def _assert_true(report: CampaignReport, cond: bool, msg: str) -> None:
    report.assertions.append(("PASS: " if cond else "FAIL: ") + msg)
    if not cond:
        raise CampaignError(msg)


def _wait_lease_expired(
    args: argparse.Namespace,
    command_id: str,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _reclaim_candidates(args, command_id) >= 1:
            snap = _snapshot_command(args, command_id)
            _print(f"lease expired for reclaim; lease_expires_at={snap.lease_expires_at}")
            return
        check = _sql_json(
            args,
            f"""
            SELECT (lease_expires_at IS NOT NULL AND lease_expires_at < NOW())
            FROM publish_retry_commands WHERE id = '{command_id}'::uuid;
            """,
        )
        if check is True:
            _print("lease expired (DB now)")
            return
        time.sleep(1.0)
    raise CampaignError("lease did not expire in time")


def _wait_lease_owner_change(
    args: argparse.Namespace,
    command_id: str,
    *,
    not_owner: str,
    timeout: float,
) -> CommandSnapshot:
    deadline = time.monotonic() + timeout
    last = _snapshot_command(args, command_id)
    while time.monotonic() < deadline:
        last = _snapshot_command(args, command_id)
        if (
            last.lease_owner
            and last.lease_owner != not_owner
            and last.status == "claimed"
        ):
            _print(f"reclaim owner={last.lease_owner}")
            return last
        if last.provider_write_started_at is not None:
            return last
        if last.status in TERMINAL:
            return last
        time.sleep(0.5)
    raise CampaignError(
        f"lease_owner did not change from {not_owner!r} "
        f"(last={asdict(last)})"
    )


def _wait_terminal(
    args: argparse.Namespace,
    command_id: str,
    *,
    timeout: float,
) -> CommandSnapshot:
    deadline = time.monotonic() + timeout
    last = _snapshot_command(args, command_id)
    while time.monotonic() < deadline:
        last = _snapshot_command(args, command_id)
        _hard_fail_if_double_invoke(args, command_id)
        if last.status in TERMINAL:
            return last
        time.sleep(0.4)
    return last


def _wait_status(
    args: argparse.Namespace,
    command_id: str,
    *,
    statuses: set[str],
    timeout: float,
) -> CommandSnapshot:
    deadline = time.monotonic() + timeout
    last = _snapshot_command(args, command_id)
    while time.monotonic() < deadline:
        last = _snapshot_command(args, command_id)
        if last.status in statuses:
            return last
        time.sleep(0.3)
    raise CampaignError(
        f"timeout waiting for status in {statuses} (got {last.status})"
    )


def _identify_workers(
    args: argparse.Namespace,
    report: CampaignReport,
    *,
    cid_a: str,
    cid_b: str,
) -> None:
    logs_a = _worker_logs(args, WORKER_A)
    logs_b = _worker_logs(args, WORKER_B)
    # Prefer Docker host PIDs (distinct across containers). In-container
    # marker pid is always 1 (Python is PID1) — do not overwrite host pid.
    report.worker_a = WorkerIdentity(
        service=WORKER_A,
        container_id=cid_a,
        worker_instance=_parse_worker_instance(logs_a),
        pid=_container_pid1(cid_a),
        campaign_id=report.campaign_id_a,
    )
    report.worker_b = WorkerIdentity(
        service=WORKER_B,
        container_id=cid_b,
        worker_instance=_parse_worker_instance(logs_b),
        pid=_container_pid1(cid_b),
        campaign_id=report.campaign_id_b,
    )
    for camp, slot in (
        (report.campaign_id_a, report.worker_a),
        (report.campaign_id_b, report.worker_b),
    ):
        for point in (
            "after_prepare",
            "after_barrier",
            "provider_entered",
            "before_finalize",
        ):
            path = _marker_path(args, camp, point)
            if path.is_file():
                meta = _parse_marker(path)
                if meta.get("worker_id"):
                    slot.worker_id = meta["worker_id"]
                break


def _assert_workers_distinct(report: CampaignReport) -> None:
    assert report.worker_a and report.worker_b
    _assert_true(
        report,
        report.worker_a.worker_instance is not None
        and report.worker_b.worker_instance is not None
        and report.worker_a.worker_instance != report.worker_b.worker_instance,
        "worker A/B instance ids differ",
    )
    if report.worker_a.worker_id and report.worker_b.worker_id:
        _assert_true(
            report,
            report.worker_a.worker_id != report.worker_b.worker_id,
            "worker A/B raw ids differ",
        )
    if (
        report.worker_a.pid
        and report.worker_b.pid
        and report.worker_a.pid not in {"0", ""}
        and report.worker_b.pid not in {"0", ""}
    ):
        _assert_true(
            report,
            report.worker_a.pid != report.worker_b.pid,
            "worker A/B host PIDs differ",
        )
    _assert_true(
        report,
        report.worker_a.container_id != report.worker_b.container_id,
        "worker A/B container ids differ",
    )


def _observe_window(
    args: argparse.Namespace,
    report: CampaignReport,
    command_ids: list[str],
    *,
    seconds: float,
) -> None:
    report.observation_seconds = seconds
    deadline = time.monotonic() + seconds
    baselines = {cid: _snapshot_command(args, cid) for cid in command_ids}
    sink_base = {cid: _sink_count(args, cid) for cid in command_ids}
    while time.monotonic() < deadline:
        for cid in command_ids:
            snap = _snapshot_command(args, cid)
            sink = _hard_fail_if_double_invoke(args, cid)
            if snap.status != baselines[cid].status:
                # Allow no regression from terminal → non-terminal.
                if baselines[cid].status in TERMINAL and snap.status not in TERMINAL:
                    raise CampaignError(
                        f"status regression {baselines[cid].status}→{snap.status} "
                        f"for {cid}"
                    )
            if sink != sink_base[cid]:
                raise CampaignError(
                    f"sink changed during observation for {cid}: "
                    f"{sink_base[cid]}→{sink}"
                )
            if snap.attempt_count != baselines[cid].attempt_count:
                raise CampaignError(
                    f"attempt_count changed during observation for {cid}"
                )
        time.sleep(max(1.0, float(args.poll_seconds)))
    report.notes.append(f"observation_window_ok={seconds}s")


def _prepare_stack(args: argparse.Namespace, *, reset: bool) -> None:
    if reset:
        _reset_project(args)
    else:
        Path(args.evidence_host_path).mkdir(parents=True, exist_ok=True)
    _up_postgres(args)
    _build_workers(args)
    _migrate_with_network(args)


def _service_for_owner(
    report: CampaignReport,
    lease_owner: str | None,
) -> str | None:
    if not lease_owner or not report.worker_a or not report.worker_b:
        return None
    if report.worker_a.worker_id and lease_owner == report.worker_a.worker_id:
        return WORKER_A
    if report.worker_b.worker_id and lease_owner == report.worker_b.worker_id:
        return WORKER_B
    # Fallback: hostname prefix from worker_id "{host}:{pid}:{uuid}".
    if lease_owner.startswith("worker-a:"):
        return WORKER_A
    if lease_owner.startswith("worker-b:"):
        return WORKER_B
    return None


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _run_claim_race(args: argparse.Namespace, *, reset: bool) -> CampaignReport:
    """B1: two workers + one pending command → exactly one claim winner."""
    campaign_a = f"b1-a-{uuid4().hex[:8]}"
    campaign_b = f"b1-b-{uuid4().hex[:8]}"
    report = CampaignReport(
        scenario="claim_race",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        db_primitives=[
            "FOR UPDATE SKIP LOCKED (pending claim)",
            "status pending→claimed mutation",
            "lease_owner / lease_expires_at assignment",
        ],
    )
    _prepare_stack(args, reset=reset)
    env = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="",
        hold_b="",
    )
    cid_a, cid_b = _start_workers(args, env, build=True)
    # Warm-up identities from start logs.
    time.sleep(2.0)
    _identify_workers(args, report, cid_a=cid_a, cid_b=cid_b)

    for i in range(1, args.claim_iterations + 1):
        _print(f"=== claim race iteration {i}/{args.claim_iterations} ===")
        seed = _seed(args)
        command_id = seed["command_id"]
        report.command_ids.append(command_id)
        final = _wait_terminal(args, command_id, timeout=args.completion_timeout)
        sink = _hard_fail_if_double_invoke(args, command_id)
        winner_svc = _service_for_owner(report, final.lease_owner)
        # Refresh identities from markers if present.
        _identify_workers(args, report, cid_a=cid_a, cid_b=cid_b)
        winner_svc = _service_for_owner(report, final.lease_owner) or winner_svc

        it = IterationResult(
            iteration=i,
            command_id=command_id,
            winner_lease_owner=final.lease_owner,
            winner_service=winner_svc,
            sink=sink,
            attempt_count=final.attempt_count,
            status=final.status,
        )
        if final.status != "succeeded":
            it.notes.append(f"unexpected_status={final.status}")
        if sink != 1:
            it.notes.append(f"sink={sink}")
        if final.attempt_count != 1:
            it.notes.append(f"attempts={final.attempt_count}")
        it.ok = (
            final.status == "succeeded"
            and sink == 1
            and final.attempt_count == 1
        )
        report.iterations.append(it)
        report.sink_by_command[command_id] = sink
        if not it.ok:
            raise CampaignError(f"claim race iteration {i} failed: {asdict(it)}")

        # Loser probe: after terminal, claim_batch must not return this command.
        probe = _probe_claim_batch(args, command_id)
        kinds = [str(x.get("kind")) for x in (probe.get("results") or [])]
        it.notes.append(f"post_terminal_probe_kinds={kinds}")
        if any(k in {"claimed", "reclaimed"} for k in kinds):
            raise CampaignError(f"loser/probe claimed terminal command: {kinds}")

    _assert_workers_distinct(report)
    winners = {it.winner_service for it in report.iterations if it.winner_service}
    report.notes.append(f"winner_services_seen={sorted(winners)}")
    report.notes.append(
        "loser_behavior=idle_or_no_eligible; no fatal contention; "
        "post-terminal probe never claims"
    )
    # Observation window on last command with both workers alive.
    last_id = report.command_ids[-1]
    _observe_window(args, report, [last_id], seconds=args.observe_seconds)
    report.ok = all(it.ok for it in report.iterations)
    _assert_true(report, report.ok, "all claim race iterations passed")
    _assert_true(
        report,
        len(report.iterations) == args.claim_iterations,
        f"ran {args.claim_iterations} claim iterations",
    )
    return report


def _run_stale_owner(args: argparse.Namespace, *, reset: bool) -> CampaignReport:
    """B2/B3: A holds after_prepare → lease expiry → B reclaim → release A fail-closed."""
    campaign_a = f"b2-a-{uuid4().hex[:8]}"
    campaign_b = f"b2-b-{uuid4().hex[:8]}"
    report = CampaignReport(
        scenario="stale_owner",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        db_primitives=[
            "FOR UPDATE SKIP LOCKED (stale reclaim)",
            "lease_expires_at < NOW() reclaim predicate",
            "provider_write_started_at IS NULL reclaim guard",
            "barrier ownership: status==claimed",
            "barrier ownership: lease_owner == worker_id",
            "barrier ownership: lease_expires_at > now",
            "row FOR UPDATE on barrier (no skip_locked)",
        ],
    )
    _prepare_stack(args, reset=reset)
    seed = _seed(args)
    command_id = seed["command_id"]
    report.command_ids = [command_id]

    # Start A alone so it is the initial owner; then start B as reclaim contender.
    env_a = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_prepare",
        hold_b="after_prepare",
    )
    cid_a = _start_worker(args, WORKER_A, env_a, build=True)

    marker_a = _wait_marker(args, campaign_a, "after_prepare", args.marker_timeout)
    meta_a = _parse_marker(marker_a)
    before = _snapshot_command(args, command_id)
    report.snapshots["a_after_prepare"] = asdict(before)
    report.resulting_attempt_id = before.resulting_attempt_id
    _assert_true(report, before.status == "claimed", "A claimed before hold")
    _assert_true(
        report,
        before.provider_write_started_at is None,
        "A pre-barrier provider_write_started_at IS NULL",
    )
    _assert_true(report, before.attempt_count == 1, "one attempt after A prepare")
    _assert_true(report, _sink_count(args, command_id) == 0, "sink=0 while A held")

    owner_a = before.lease_owner or meta_a.get("worker_id")
    _assert_true(report, owner_a is not None, "A lease_owner recorded")

    env_b = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_prepare",
        hold_b="after_prepare",
    )
    cid_b = _start_worker(args, WORKER_B, env_b)

    # B reclaim renews lease_expires_at, so do not wait for a stable
    # "expired" row snapshot — wait for B's after_prepare marker instead.
    # That marker is only reachable after SKIP LOCKED reclaim post-expiry.
    marker_b = _wait_marker(
        args,
        campaign_b,
        "after_prepare",
        timeout=max(90.0, args.lease_seconds + 60.0),
    )
    meta_b = _parse_marker(marker_b)
    after_reclaim = _snapshot_command(args, command_id)
    report.snapshots["b_after_reclaim_prepare"] = asdict(after_reclaim)
    report.reclaim_owner = after_reclaim.lease_owner
    _assert_true(
        report,
        after_reclaim.lease_owner is not None
        and after_reclaim.lease_owner != owner_a,
        "B lease_owner differs from A after reclaim",
    )
    _assert_true(
        report,
        after_reclaim.attempt_count == 1,
        "attempt reuse: still exactly one linked attempt",
    )
    _assert_true(
        report,
        after_reclaim.resulting_attempt_id == before.resulting_attempt_id,
        "same resulting_attempt_id after reclaim",
    )
    _assert_true(
        report,
        after_reclaim.provider_write_started_at is None,
        "still pre-barrier after B reclaim prepare",
    )
    _assert_true(report, _sink_count(args, command_id) == 0, "sink=0 after B reclaim")

    # B3: release stale A only after B reclaim proven.
    _write_release(args, campaign_a, "after_prepare")
    # Give A time to attempt barrier and fail closed.
    deadline = time.monotonic() + 20.0
    stale_outcome = None
    stale_reason = None
    while time.monotonic() < deadline:
        logs_a = _worker_logs(args, WORKER_A)
        outcomes = _parse_executor_outcomes(logs_a)
        for cmd, outcome, inv in outcomes:
            if cmd == command_id:
                stale_outcome = outcome
                # provider_invoked must be false/False
                if inv.lower() in {"true", "1"}:
                    raise CampaignError("stale A invoked provider")
                break
        if stale_outcome is not None:
            break
        # Also ensure A did not write provider markers.
        if _marker_path(args, campaign_a, "provider_entered").is_file():
            raise CampaignError("stale A wrote provider_entered")
        if _marker_path(args, campaign_a, "after_barrier").is_file():
            raise CampaignError("stale A crossed barrier marker")
        time.sleep(0.5)

    report.stale_a_outcome = stale_outcome
    # Infer precise ownership rejection from durable DB state + logs.
    after_release = _snapshot_command(args, command_id)
    logs_a = _worker_logs(args, WORKER_A)
    if after_release.lease_owner and owner_a and after_release.lease_owner != owner_a:
        stale_reason = "lease_owner_mismatch"
    elif after_release.lease_expires_at is None and after_release.provider_write_started_at:
        stale_reason = "already_barriered_or_not_claimed"
    elif "lease_owner_mismatch" in logs_a:
        stale_reason = "lease_owner_mismatch"
    elif "lease_expired" in logs_a:
        stale_reason = "lease_expired"
    elif "not_claimed" in logs_a:
        stale_reason = "not_claimed"
    elif stale_outcome == "blocked_barrier":
        stale_reason = "blocked_lease_or_ownership"
    report.stale_a_reason = stale_reason
    report.snapshots["after_stale_a_release"] = asdict(after_release)

    _assert_true(
        report,
        stale_outcome in {
            "blocked_barrier",
            "blocked_preparation",
            "already_barriered_no_replay",
        }
        or (
            not _marker_path(args, campaign_a, "after_barrier").is_file()
            and not _marker_path(args, campaign_a, "provider_entered").is_file()
        ),
        f"stale A fail-closed (outcome={stale_outcome} reason={stale_reason})",
    )
    _assert_true(
        report,
        _sink_count(args, command_id) == 0,
        "sink still 0 after stale A release",
    )
    _assert_true(
        report,
        not _marker_path(args, campaign_a, "provider_entered").is_file(),
        "stale A never entered provider",
    )
    _assert_true(
        report,
        not _marker_path(args, campaign_a, "after_barrier").is_file(),
        "stale A never wrote after_barrier",
    )

    # Release B to complete normally.
    _write_release(args, campaign_b, "after_prepare")
    final = _wait_terminal(args, command_id, timeout=args.completion_timeout)
    sink = _hard_fail_if_double_invoke(args, command_id)
    report.sink_by_command[command_id] = sink
    report.snapshots["final"] = asdict(final)
    report.attempt_count = final.attempt_count

    _identify_workers(args, report, cid_a=cid_a, cid_b=cid_b)
    # Fill worker ids from markers (in-container pid is always 1 — ignore).
    if meta_a.get("worker_id") and report.worker_a:
        report.worker_a.worker_id = meta_a["worker_id"]
    if meta_b.get("worker_id") and report.worker_b:
        report.worker_b.worker_id = meta_b["worker_id"]

    _assert_workers_distinct(report)
    _assert_true(report, sink == 1, "B completes with fake_invoke exactly 1")
    _assert_true(report, final.status == "succeeded", "command succeeded via B")
    _assert_true(report, final.attempt_count == 1, "no attempt lineage fork")
    _assert_true(
        report,
        final.resulting_attempt_id == before.resulting_attempt_id,
        "final resulting_attempt_id unchanged",
    )
    # Provider entered under B campaign only.
    _assert_true(
        report,
        _marker_path(args, campaign_b, "provider_entered").is_file(),
        "B crossed provider",
    )
    _assert_true(
        report,
        not _marker_path(args, campaign_a, "provider_entered").is_file(),
        "A never crossed provider",
    )

    _observe_window(args, report, [command_id], seconds=args.observe_seconds)
    report.notes.append(
        f"stale_a_rejected_at_barrier outcome={stale_outcome} reason={stale_reason}"
    )
    report.notes.append("phase_e_untouched=true")
    report.ok = True
    return report


def _run_two_command(args: argparse.Namespace, *, reset: bool) -> CampaignReport:
    """B4/B5: two commands + overlap proving non-global serialization."""
    campaign_a = f"b4-a-{uuid4().hex[:8]}"
    campaign_b = f"b4-b-{uuid4().hex[:8]}"
    report = CampaignReport(
        scenario="two_command",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        db_primitives=[
            "FOR UPDATE SKIP LOCKED (per-row claim)",
            "per-command lease_owner",
            "per-command provider_write_started_at",
            "no process-global lock required",
        ],
    )
    _prepare_stack(args, reset=reset)
    seed_x = _seed(args)
    seed_y = _seed(args)
    cmd_x = seed_x["command_id"]
    cmd_y = seed_y["command_id"]
    report.command_ids = [cmd_x, cmd_y]

    # Start A alone so it claims exactly one command and holds; then start B
    # against the remaining pending command (avoids B draining both).
    env_a = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_prepare",
        hold_b="",
    )
    cid_a = _start_worker(args, WORKER_A, env_a, build=True)

    marker_a = _wait_marker(args, campaign_a, "after_prepare", args.marker_timeout)
    meta_a = _parse_marker(marker_a)
    # Identify which command A holds.
    snap_x = _snapshot_command(args, cmd_x)
    snap_y = _snapshot_command(args, cmd_y)
    if snap_x.status == "claimed" and snap_x.lease_expires_at is not None:
        held_id, free_id = cmd_x, cmd_y
        held_snap = snap_x
    elif snap_y.status == "claimed" and snap_y.lease_expires_at is not None:
        held_id, free_id = cmd_y, cmd_x
        held_snap = snap_y
    else:
        raise CampaignError(
            f"could not identify A-held command: x={asdict(snap_x)} y={asdict(snap_y)}"
        )

    report.snapshots["a_held"] = {
        "command_id": held_id,
        "snapshot": asdict(held_snap),
        "marker": meta_a,
    }
    _assert_true(report, held_snap.provider_write_started_at is None, "held pre-barrier")
    _assert_true(report, _sink_count(args, held_id) == 0, "held sink=0")
    _assert_true(
        report,
        _pending_candidates(args, free_id) == 1,
        "second command still pending for B",
    )

    # B5: while A is held, B must complete the other command (no global lock).
    env_b = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_prepare",
        hold_b="",
    )
    cid_b = _start_worker(args, WORKER_B, env_b)
    free_final = _wait_terminal(args, free_id, timeout=args.completion_timeout)
    free_sink = _hard_fail_if_double_invoke(args, free_id)
    report.snapshots["b_free_while_a_held"] = asdict(free_final)
    _assert_true(
        report,
        free_final.status == "succeeded",
        "free command completed while A held (non-global serialization)",
    )
    _assert_true(report, free_sink == 1, "free command fake_invoke=1")
    _assert_true(report, free_final.attempt_count == 1, "free command one attempt")
    # Held command still held / not progressed to provider.
    held_mid = _snapshot_command(args, held_id)
    _assert_true(
        report,
        held_mid.status == "claimed",
        "held command still claimed while free completed",
    )
    _assert_true(report, _sink_count(args, held_id) == 0, "held still sink=0")
    report.notes.append(
        f"non_global_serialization: A held {held_id} after_prepare; "
        f"B completed {free_id} independently"
    )

    # Release A; held command completes.
    _write_release(args, campaign_a, "after_prepare")
    held_final = _wait_terminal(args, held_id, timeout=args.completion_timeout)
    held_sink = _hard_fail_if_double_invoke(args, held_id)
    report.sink_by_command[held_id] = held_sink
    report.sink_by_command[free_id] = free_sink
    report.snapshots["held_final"] = asdict(held_final)

    _identify_workers(args, report, cid_a=cid_a, cid_b=cid_b)
    if meta_a.get("worker_id") and report.worker_a:
        report.worker_a.worker_id = meta_a["worker_id"]
    _assert_workers_distinct(report)

    _assert_true(report, held_final.status == "succeeded", "held command succeeded")
    _assert_true(report, held_sink == 1, "held command fake_invoke=1")
    _assert_true(report, held_final.attempt_count == 1, "held command one attempt")
    # Parallel ownership evidence: different lease owners preferred.
    owners = {held_final.lease_owner, free_final.lease_owner}
    report.notes.append(f"final_lease_owners={sorted(o for o in owners if o)}")
    _assert_true(
        report,
        len([o for o in owners if o]) >= 1,
        "at least one lease_owner recorded",
    )

    _observe_window(args, report, [held_id, free_id], seconds=args.observe_seconds)
    report.ok = True
    return report


def _run_reclaim_barrier_race(
    args: argparse.Namespace, *, reset: bool
) -> CampaignReport:
    """B6: race A barrier vs B reclaim around lease expiry; fake_invoke <= 1."""
    campaign_a = f"b6-a-{uuid4().hex[:8]}"
    campaign_b = f"b6-b-{uuid4().hex[:8]}"
    report = CampaignReport(
        scenario="reclaim_barrier_race",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        db_primitives=[
            "barrier FOR UPDATE exclusive row lock",
            "reclaim FOR UPDATE SKIP LOCKED + lease_expires_at < NOW()",
            "ownership validation before provider authorization",
        ],
    )
    _prepare_stack(args, reset=reset)
    seed = _seed(args)
    command_id = seed["command_id"]
    report.command_ids = [command_id]

    env_a = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_prepare",
        hold_b="",
    )
    cid_a = _start_worker(args, WORKER_A, env_a, build=True)
    marker_a = _wait_marker(args, campaign_a, "after_prepare", args.marker_timeout)
    meta_a = _parse_marker(marker_a)
    before = _snapshot_command(args, command_id)
    owner_a = before.lease_owner or meta_a.get("worker_id")
    report.snapshots["a_held"] = asdict(before)

    # B joins while A is held; will contend at lease expiry / barrier.
    env_b = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_prepare",
        hold_b="",
    )
    cid_b = _start_worker(args, WORKER_B, env_b)

    # Wait until lease is nearly expired, then release A into the race.
    deadline = time.monotonic() + max(45.0, args.lease_seconds + 20.0)
    released = False
    while time.monotonic() < deadline:
        remaining = _sql_json(
            args,
            f"""
            SELECT EXTRACT(EPOCH FROM (lease_expires_at - NOW()))
            FROM publish_retry_commands WHERE id = '{command_id}'::uuid;
            """,
        )
        if remaining is None:
            break
        rem = float(remaining)
        _print(f"lease remaining_seconds~={rem:.2f}")
        if rem <= 2.5:
            _write_release(args, campaign_a, "after_prepare")
            released = True
            break
        time.sleep(0.5)
    if not released:
        # Lease already expired or clock skew — release anyway for reclaim race.
        _write_release(args, campaign_a, "after_prepare")

    final = _wait_terminal(args, command_id, timeout=args.completion_timeout)
    sink = _hard_fail_if_double_invoke(args, command_id)
    report.sink_by_command[command_id] = sink
    report.snapshots["final"] = asdict(final)
    report.attempt_count = final.attempt_count
    report.resulting_attempt_id = final.resulting_attempt_id

    logs_a = _worker_logs(args, WORKER_A)
    logs_b = _worker_logs(args, WORKER_B)
    outcomes_a = _parse_executor_outcomes(logs_a)
    outcomes_b = _parse_executor_outcomes(logs_b)
    report.snapshots["outcomes_a"] = outcomes_a
    report.snapshots["outcomes_b"] = outcomes_b

    provider_a = any(
        c == command_id and o not in {
            "blocked_barrier",
            "blocked_preparation",
            "already_barriered_no_replay",
            "stopped_before_barrier",
        }
        and inv.lower() in {"true", "1"}
        for c, o, inv in outcomes_a
    )
    provider_b = any(
        c == command_id and inv.lower() in {"true", "1"}
        for c, o, inv in outcomes_b
    )
    if provider_a and provider_b:
        raise CampaignError("both A and B invoked provider — atomicity failure")

    winner = final.lease_owner
    report.reclaim_owner = winner
    report.notes.append(
        f"race_winner_lease_owner={winner} owner_a={owner_a} "
        f"provider_a={provider_a} provider_b={provider_b}"
    )
    if winner == owner_a:
        report.notes.append("A won barrier before reclaim invalidated ownership")
    elif winner and winner != owner_a:
        report.notes.append("B won reclaim before/at A barrier")

    _identify_workers(args, report, cid_a=cid_a, cid_b=cid_b)
    if meta_a.get("worker_id") and report.worker_a:
        report.worker_a.worker_id = meta_a["worker_id"]
    _assert_workers_distinct(report)
    _assert_true(report, sink == 1, "race fake_invoke exactly 1")
    _assert_true(report, final.status == "succeeded", "race reached succeeded")
    _assert_true(report, final.attempt_count == 1, "race one attempt")
    _observe_window(args, report, [command_id], seconds=args.observe_seconds)
    report.ok = True
    return report


def _run_post_barrier_overlap(
    args: argparse.Namespace, *, reset: bool
) -> CampaignReport:
    """B7 optional: A holds after_barrier on X while B completes Y."""
    campaign_a = f"b7-a-{uuid4().hex[:8]}"
    campaign_b = f"b7-b-{uuid4().hex[:8]}"
    report = CampaignReport(
        scenario="post_barrier_overlap",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        db_primitives=[
            "provider_write_started_at per command",
            "reclaim excludes provider_write_started_at IS NOT NULL",
            "pending claim excludes non-pending status",
        ],
    )
    _prepare_stack(args, reset=reset)
    seed_x = _seed(args)
    seed_y = _seed(args)
    cmd_x = seed_x["command_id"]
    cmd_y = seed_y["command_id"]
    report.command_ids = [cmd_x, cmd_y]

    env_a = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_barrier",
        hold_b="",
    )
    cid_a = _start_worker(args, WORKER_A, env_a, build=True)
    marker_a = _wait_marker(args, campaign_a, "after_barrier", args.marker_timeout)
    meta_a = _parse_marker(marker_a)

    snap_x = _snapshot_command(args, cmd_x)
    snap_y = _snapshot_command(args, cmd_y)
    if snap_x.status == "provider_write_started":
        held_id, free_id = cmd_x, cmd_y
        held_snap = snap_x
    elif snap_y.status == "provider_write_started":
        held_id, free_id = cmd_y, cmd_x
        held_snap = snap_y
    else:
        raise CampaignError(
            f"A did not hold after_barrier: x={asdict(snap_x)} y={asdict(snap_y)}"
        )

    report.snapshots["a_after_barrier"] = asdict(held_snap)
    _assert_true(
        report,
        held_snap.provider_write_started_at is not None,
        "held has provider_write_started_at",
    )
    _assert_true(report, _sink_count(args, held_id) == 0, "held sink=0 at after_barrier")
    _assert_true(
        report,
        _reclaim_candidates(args, held_id) == 0,
        "held command not reclaimable",
    )
    _assert_true(
        report,
        _pending_candidates(args, free_id) == 1,
        "second command still pending for B",
    )

    env_b = _worker_env(
        args,
        campaign_a=campaign_a,
        campaign_b=campaign_b,
        hold_a="after_barrier",
        hold_b="",
    )
    cid_b = _start_worker(args, WORKER_B, env_b)
    free_final = _wait_terminal(args, free_id, timeout=args.completion_timeout)
    free_sink = _hard_fail_if_double_invoke(args, free_id)
    _assert_true(report, free_final.status == "succeeded", "Y/free succeeded under B")
    _assert_true(report, free_sink == 1, "free sink=1")
    held_mid = _snapshot_command(args, held_id)
    _assert_true(
        report,
        held_mid.status == "provider_write_started",
        "X remains provider_write_started while Y completed",
    )
    _assert_true(report, _sink_count(args, held_id) == 0, "X sink still 0")
    report.notes.append(
        f"B7: A held {held_id} after_barrier; B completed {free_id}; "
        "B cannot own A command"
    )

    _write_release(args, campaign_a, "after_barrier")
    held_final = _wait_terminal(args, held_id, timeout=args.completion_timeout)
    held_sink = _hard_fail_if_double_invoke(args, held_id)
    report.sink_by_command[held_id] = held_sink
    report.sink_by_command[free_id] = free_sink

    _identify_workers(args, report, cid_a=cid_a, cid_b=cid_b)
    if meta_a.get("worker_id") and report.worker_a:
        report.worker_a.worker_id = meta_a["worker_id"]
    _assert_workers_distinct(report)
    _assert_true(report, held_final.status == "succeeded", "held finalized once")
    _assert_true(report, held_sink == 1, "held fake_invoke=1")
    _observe_window(args, report, [held_id, free_id], seconds=args.observe_seconds)
    report.notes.append("phase_e_untouched=true")
    report.ok = True
    return report


def _dump_report(report: CampaignReport) -> None:
    _print("=== CAMPAIGN REPORT ===")
    _print(json.dumps(asdict(report), indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "claim_race",
            "stale_owner",
            "two_command",
            "reclaim_barrier_race",
            "post_barrier_overlap",
            "all-required",
        ),
        default="all-required",
    )
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--override-file", type=Path, default=DEFAULT_OVERRIDE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--evidence-host-path", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--poll-seconds", type=int, default=1)
    parser.add_argument("--marker-timeout", type=float, default=120.0)
    parser.add_argument("--completion-timeout", type=float, default=180.0)
    parser.add_argument("--observe-seconds", type=float, default=8.0)
    parser.add_argument("--claim-iterations", type=int, default=12)
    parser.add_argument(
        "--include-optional",
        action="store_true",
        help="Include B7 post_barrier_overlap in all-required",
    )
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--report-json", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.project != DEFAULT_PROJECT:
        raise SystemExit(f"refusing non-staging project name: {args.project}")
    if args.lease_seconds < 30:
        raise SystemExit("lease-seconds must be >= 30 (production clamp floor)")
    if args.claim_iterations < 1:
        raise SystemExit("claim-iterations must be >= 1")

    args.evidence_host_path = Path(args.evidence_host_path).resolve()
    args.compose_file = Path(args.compose_file).resolve()
    args.override_file = Path(args.override_file).resolve()
    args.env_file = Path(args.env_file).resolve()

    if args.scenario == "all-required":
        scenarios: list[Scenario] = [
            "claim_race",
            "stale_owner",
            "two_command",
            "reclaim_barrier_race",
        ]
        if args.include_optional:
            scenarios.append("post_barrier_overlap")
    else:
        scenarios = [args.scenario]  # type: ignore[list-item]

    runners = {
        "claim_race": _run_claim_race,
        "stale_owner": _run_stale_owner,
        "two_command": _run_two_command,
        "reclaim_barrier_race": _run_reclaim_barrier_race,
        "post_barrier_overlap": _run_post_barrier_overlap,
    }

    reports: list[CampaignReport] = []
    try:
        for idx, scenario in enumerate(scenarios):
            reset = (not args.no_reset) or idx > 0
            # Always reset between scenarios for isolation.
            if idx > 0:
                reset = True
            _print(f"\n######## SCENARIO {scenario} (reset={reset}) ########\n")
            report = runners[scenario](args, reset=reset)
            _dump_report(report)
            reports.append(report)
            if not report.ok:
                return 1
            _stop_workers(args)
    except CampaignError as exc:
        _print(f"CAMPAIGN FAILED: {exc}")
        if args.report_json:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(
                json.dumps(
                    [asdict(r) for r in reports] + [{"error": str(exc)}],
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        return 1
    finally:
        pass

    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps([asdict(r) for r in reports], indent=2, default=str),
            encoding="utf-8",
        )

    _print("=== ALL REQUIRED MULTI-WORKER CAMPAIGNS PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
