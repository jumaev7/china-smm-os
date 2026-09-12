"""B2b2-A single-worker SIGKILL + restart / no-replay campaign runner.

LOCAL STAGING ONLY. Project: china-smm-os-staging.

Proves crash/restart safety under REAL docker kill -s SIGKILL for:

  A1/A2  pre-barrier kill + reclaim after lease expiry
  A3/A4  post-barrier/pre-provider kill + restart no-replay
  A5/A6  post-provider/pre-finalizer kill + restart no-replay

Optional A7/A8 (finalizer-in-flight) is DEFERRED — no clean mid-finalizer-TX
DI hook without weakening production FinalizationService.

Does NOT push, deploy, enable production, touch Phase E, or add real providers.

Examples:

  python scripts/run_staging_retry_command_sigkill_restart_campaign.py \\
    --scenario all-required

  python scripts/run_staging_retry_command_sigkill_restart_campaign.py \\
    --scenario post_barrier --no-reset
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
DEFAULT_OVERRIDE = REPO_ROOT / "docker-compose.staging.b2b2a-campaign.yml"
DEFAULT_EVIDENCE = REPO_ROOT / ".staging-b2b2a-evidence"
WORKER_SERVICE = "publish-retry-command-worker"
SINK_REL = Path("sink") / "fake-invocations.jsonl"

Scenario = Literal[
    "pre_barrier",
    "post_barrier",
    "post_provider",
    "all-required",
]


@dataclass
class KillEvidence:
    container_id: str
    exit_code: int | None
    status: str | None
    oom_killed: bool | None
    restart_policy: str | None
    restart_count: int | None


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
class CampaignReport:
    scenario: str
    campaign_id_a: str
    campaign_id_b: str
    command_id: str
    hold_point: str
    worker_a_id: str | None = None
    worker_a_instance: str | None = None
    worker_b_id: str | None = None
    worker_b_instance: str | None = None
    kill: KillEvidence | None = None
    before_kill: CommandSnapshot | None = None
    after_kill: CommandSnapshot | None = None
    after_restart: CommandSnapshot | None = None
    sink_before_kill: int = 0
    sink_after_kill: int = 0
    sink_after_restart: int = 0
    provider_entered_before_kill: bool = False
    provider_entered_after_restart: bool = False
    claim_probe_kinds: list[str] = field(default_factory=list)
    reclaim_probe_count: int = 0
    observation_seconds: float = 0.0
    expected_min_claim_cycles: int = 0
    assertions: list[str] = field(default_factory=list)
    ok: bool = False
    notes: list[str] = field(default_factory=list)


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


def _campaign_env(
    args: argparse.Namespace,
    *,
    hold_point: str,
    campaign_id: str,
    lease_seconds: int,
) -> dict[str, str]:
    return {
        "STAGING_EVIDENCE_HOST_PATH": str(args.evidence_host_path),
        "PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT": hold_point,
        "PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID": campaign_id,
        "PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS": "0",
        "PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS": str(args.poll_seconds),
        "PUBLISH_RETRY_COMMAND_LEASE_SECONDS": str(lease_seconds),
        "PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE": "success",
    }


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
            ["exec", "-T", "postgres", "pg_isready", "-U", "postgres", "-d", "china_smm_os_staging"],
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


def _build_worker(args: argparse.Namespace) -> None:
    _print("=== build worker image ===")
    _compose(
        args,
        ["--profile", "retry-command", "build", WORKER_SERVICE],
    )


def _migrate_with_network(args: argparse.Namespace) -> None:
    """Migrate using a one-shot worker container on the staging network."""
    _print("=== alembic upgrade head (networked) ===")
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
            WORKER_SERVICE,
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
            "--build",
            "--entrypoint",
            "python",
            WORKER_SERVICE,
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
    """Run SQL via psql and parse JSON (or scalar JSON-compatible) result."""
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
    if not text or text == "":
        return None
    # psql booleans / ints when not wrapped in json_* helpers
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
        SELECT COALESCE(json_agg(id::text), '[]'::json)
        FROM publish_retry_commands
        WHERE status = 'claimed'
          AND lease_expires_at IS NOT NULL
          AND lease_expires_at < NOW()
          AND provider_write_started_at IS NULL
          AND id = '{command_id}'::uuid;
        """,
    )
    if val is None:
        return 0
    if isinstance(val, list):
        return len(val)
    return 0


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
    """One-shot claim_batch probe as a distinct worker id (must not win command)."""
    result = _compose(
        args,
        [
            "--profile",
            "retry-command",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            WORKER_SERVICE,
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


def _worker_container_id(args: argparse.Namespace) -> str:
    result = _compose(
        args,
        ["ps", "-q", WORKER_SERVICE],
        capture=True,
    )
    cid = (result.stdout or "").strip().splitlines()
    if not cid or not cid[0].strip():
        raise CampaignError("worker container not running")
    return cid[0].strip()


def _inspect_kill(container_id: str) -> KillEvidence:
    fmt = (
        "{{.State.ExitCode}}|{{.State.Status}}|{{.State.OOMKilled}}|"
        "{{.HostConfig.RestartPolicy.Name}}|{{.RestartCount}}"
    )
    result = _run(
        ["docker", "inspect", "-f", fmt, container_id],
        capture=True,
    )
    parts = (result.stdout or "").strip().split("|")
    while len(parts) < 5:
        parts.append("")
    exit_code = int(parts[0]) if parts[0] else None
    oom = None
    if parts[2] != "":
        oom = parts[2].lower() == "true"
    restart_count = int(parts[4]) if parts[4] else None
    return KillEvidence(
        container_id=container_id,
        exit_code=exit_code,
        status=parts[1] or None,
        oom_killed=oom,
        restart_policy=parts[3] or None,
        restart_count=restart_count,
    )


def _sigkill_worker(args: argparse.Namespace) -> KillEvidence:
    cid = _worker_container_id(args)
    _print(f"=== SIGKILL worker container {cid[:12]} ===")
    _run(["docker", "kill", "-s", "SIGKILL", cid])
    # Brief settle for inspect state.
    time.sleep(0.5)
    evidence = _inspect_kill(cid)
    _print(f"kill evidence: {asdict(evidence)}")
    if evidence.restart_policy not in (None, "no", ""):
        raise CampaignError(f"unexpected restart policy: {evidence.restart_policy}")
    if evidence.oom_killed:
        raise CampaignError("OOMKilled unexpectedly true")
    # 137 = 128+SIGKILL(9); some engines report 137 or Status=exited.
    if evidence.status not in ("exited", "dead"):
        # Retry inspect once.
        time.sleep(1.0)
        evidence = _inspect_kill(cid)
    if evidence.status not in ("exited", "dead"):
        raise CampaignError(f"worker not exited after SIGKILL: {evidence}")
    return evidence


def _remove_worker(args: argparse.Namespace) -> None:
    _compose(
        args,
        ["--profile", "retry-command", "rm", "-f", "-s", WORKER_SERVICE],
        check=False,
    )


def _start_worker(
    args: argparse.Namespace,
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
        WORKER_SERVICE,
    ]
    if build:
        cmd.insert(3, "--build")
    _compose(args, cmd, env=env)
    # Postgres already up on the project network; --no-deps skips recreate.
    time.sleep(1.0)
    return _worker_container_id(args)


def _worker_logs(args: argparse.Namespace, since_seconds: int = 300) -> str:
    result = _compose(
        args,
        ["logs", "--no-color", f"--since={since_seconds}s", WORKER_SERVICE],
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


def _assert_true(report: CampaignReport, cond: bool, msg: str) -> None:
    report.assertions.append(("PASS: " if cond else "FAIL: ") + msg)
    if not cond:
        raise CampaignError(msg)


def _assert_release_isolation(
    args: argparse.Namespace,
    report: CampaignReport,
    hold_point: str,
) -> None:
    """A's release file must not exist / influence B (campaign-scoped + consumed)."""
    a_release = _control_path(args, report.campaign_id_a, hold_point)
    b_release = _control_path(args, report.campaign_id_b, hold_point)
    _assert_true(
        report,
        not a_release.is_file(),
        f"no stale A release file at {a_release}",
    )
    _assert_true(
        report,
        not b_release.is_file(),
        f"no accidental B release file at {b_release}",
    )
    # Distinct campaign scopes.
    _assert_true(
        report,
        report.campaign_id_a != report.campaign_id_b,
        "worker A/B campaign ids differ",
    )


def _wait_lease_expired(
    args: argparse.Namespace,
    command_id: str,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = _snapshot_command(args, command_id)
        expired = _reclaim_candidates(args, command_id)
        if snap.lease_expires_at is not None and expired >= 1:
            _print(f"lease expired for reclaim; lease_expires_at={snap.lease_expires_at}")
            return
        # Also accept DB expression when lease_expires_at < NOW even if race.
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


def _wait_terminal_or_sink(
    args: argparse.Namespace,
    command_id: str,
    *,
    timeout: float,
    want_sink: int | None = None,
) -> CommandSnapshot:
    deadline = time.monotonic() + timeout
    terminal = {"succeeded", "failed", "ambiguous", "blocked", "superseded", "cancelled"}
    last = _snapshot_command(args, command_id)
    while time.monotonic() < deadline:
        last = _snapshot_command(args, command_id)
        sink = _sink_count(args, command_id)
        if last.status in terminal:
            return last
        if want_sink is not None and sink >= want_sink and last.status in terminal:
            return last
        time.sleep(0.5)
    return last


def _prepare_stack(args: argparse.Namespace, *, reset: bool) -> dict[str, Any]:
    if reset:
        _reset_project(args)
    else:
        Path(args.evidence_host_path).mkdir(parents=True, exist_ok=True)
    _up_postgres(args)
    _build_worker(args)
    _migrate_with_network(args)
    return _seed(args)


def _run_pre_barrier(args: argparse.Namespace, *, reset: bool) -> CampaignReport:
    hold_point = "after_prepare"
    campaign_a = f"a1a2-{uuid4().hex[:8]}"
    campaign_b = f"a1a2-b-{uuid4().hex[:8]}"
    seed = _prepare_stack(args, reset=reset)
    command_id = seed["command_id"]
    report = CampaignReport(
        scenario="pre_barrier",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        command_id=command_id,
        hold_point=hold_point,
    )
    env_a = _campaign_env(
        args,
        hold_point=hold_point,
        campaign_id=campaign_a,
        lease_seconds=args.lease_seconds,
    )
    _start_worker(args, env_a, build=True)
    marker = _wait_marker(args, campaign_a, hold_point, args.marker_timeout)
    meta = _parse_marker(marker)
    report.worker_a_id = meta.get("worker_id")
    logs_a = _worker_logs(args)
    report.worker_a_instance = _parse_worker_instance(logs_a)

    report.before_kill = _snapshot_command(args, command_id)
    report.sink_before_kill = _sink_count(args, command_id)
    _assert_true(report, report.before_kill.status == "claimed", "A1 before kill status=claimed")
    _assert_true(
        report,
        report.before_kill.provider_write_started_at is None,
        "A1 before kill provider_write_started_at IS NULL",
    )
    _assert_true(
        report,
        report.before_kill.lease_expires_at is not None,
        "A1 before kill lease_expires_at non-null",
    )
    _assert_true(report, report.sink_before_kill == 0, "A1 before kill sink=0")
    _assert_true(
        report,
        report.before_kill.resulting_attempt_id is not None,
        "A1 resulting_attempt_id present after prepare",
    )

    report.kill = _sigkill_worker(args)
    report.after_kill = _snapshot_command(args, command_id)
    report.sink_after_kill = _sink_count(args, command_id)
    _assert_true(report, report.after_kill.status == "claimed", "A1 after kill still claimed")
    _assert_true(
        report,
        report.after_kill.provider_write_started_at is None,
        "A1 after kill provider_write_started_at still NULL",
    )
    _assert_true(report, report.sink_after_kill == 0, "A1 after kill sink=0")
    _assert_true(
        report,
        _marker_path(args, campaign_a, hold_point).is_file(),
        "A1 marker persists after SIGKILL",
    )

    # A2: wait lease expiry, start worker B (no hold), expect reclaim + invoke once.
    _wait_lease_expired(args, command_id, timeout=max(45.0, args.lease_seconds + 20.0))
    _assert_release_isolation(args, report, hold_point)
    _remove_worker(args)
    env_b = _campaign_env(
        args,
        hold_point="",
        campaign_id=campaign_b,
        lease_seconds=args.lease_seconds,
    )
    _start_worker(args, env_b)
    final = _wait_terminal_or_sink(
        args,
        command_id,
        timeout=args.restart_timeout,
        want_sink=1,
    )
    report.after_restart = final
    report.sink_after_restart = _sink_count(args, command_id)
    logs_b = _worker_logs(args)
    report.worker_b_instance = _parse_worker_instance(logs_b)
    # Prefer lease_owner after reclaim as worker B id.
    report.worker_b_id = final.lease_owner or report.worker_b_id

    _assert_true(report, report.sink_after_restart == 1, "A2 fake_invoke exactly 1")
    _assert_true(
        report,
        final.status == "succeeded",
        f"A2 command terminal succeeded (got {final.status})",
    )
    _assert_true(
        report,
        final.attempt_count == 1,
        f"A2 exactly one linked attempt (got {final.attempt_count})",
    )
    _assert_true(
        report,
        final.command_count == 1,
        f"A2 exactly one retry command (got {final.command_count})",
    )
    _assert_true(
        report,
        report.before_kill.resulting_attempt_id == final.resulting_attempt_id,
        "A2 same resulting_attempt_id reused after reclaim",
    )
    _assert_true(
        report,
        report.worker_a_instance is not None
        and report.worker_b_instance is not None
        and report.worker_a_instance != report.worker_b_instance,
        "A2 worker A/B instance ids differ",
    )
    if report.worker_a_id and report.worker_b_id:
        _assert_true(
            report,
            report.worker_a_id != report.worker_b_id,
            "A2 worker A/B raw ids differ",
        )
    report.notes.append("attempt_reuse=same_resulting_attempt_id")
    report.ok = True
    return report


def _run_post_barrier(args: argparse.Namespace, *, reset: bool) -> CampaignReport:
    hold_point = "after_barrier"
    campaign_a = f"a3a4-{uuid4().hex[:8]}"
    campaign_b = f"a3a4-b-{uuid4().hex[:8]}"
    seed = _prepare_stack(args, reset=reset)
    command_id = seed["command_id"]
    report = CampaignReport(
        scenario="post_barrier",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        command_id=command_id,
        hold_point=hold_point,
    )
    env_a = _campaign_env(
        args,
        hold_point=hold_point,
        campaign_id=campaign_a,
        lease_seconds=args.lease_seconds,
    )
    _start_worker(args, env_a, build=True)
    marker = _wait_marker(args, campaign_a, hold_point, args.marker_timeout)
    meta = _parse_marker(marker)
    report.worker_a_id = meta.get("worker_id")
    report.worker_a_instance = _parse_worker_instance(_worker_logs(args))

    report.before_kill = _snapshot_command(args, command_id)
    report.sink_before_kill = _sink_count(args, command_id)
    report.provider_entered_before_kill = _marker_path(
        args, campaign_a, "provider_entered"
    ).is_file()
    _assert_true(
        report,
        report.before_kill.status == "provider_write_started",
        "A3 before kill status=provider_write_started",
    )
    _assert_true(
        report,
        report.before_kill.provider_write_started_at is not None,
        "A3 before kill provider_write_started_at set",
    )
    _assert_true(
        report,
        report.before_kill.lease_expires_at is None,
        "A3 before kill lease_expires_at IS NULL",
    )
    _assert_true(report, report.sink_before_kill == 0, "A3 before kill sink=0")
    _assert_true(
        report,
        not report.provider_entered_before_kill,
        "A3 provider_entered absent before kill",
    )

    report.kill = _sigkill_worker(args)
    report.after_kill = _snapshot_command(args, command_id)
    report.sink_after_kill = _sink_count(args, command_id)
    _assert_true(
        report,
        report.after_kill.status == "provider_write_started",
        "A3 after kill still provider_write_started",
    )
    _assert_true(
        report,
        report.after_kill.provider_write_started_at is not None,
        "A3 after kill provider_write_started_at remains set",
    )
    _assert_true(report, report.sink_after_kill == 0, "A3 after kill sink=0")
    _assert_true(
        report,
        report.after_kill.status not in {"succeeded", "failed", "ambiguous"},
        "A3 after kill not terminal",
    )

    _assert_release_isolation(args, report, hold_point)
    _remove_worker(args)
    env_b = _campaign_env(
        args,
        hold_point="",
        campaign_id=campaign_b,
        lease_seconds=args.lease_seconds,
    )
    _start_worker(args, env_b)
    report.worker_b_instance = None
    # Observation window: several claim loops.
    report.observation_seconds = float(args.observe_seconds)
    report.expected_min_claim_cycles = max(
        1, int(report.observation_seconds // max(1, args.poll_seconds))
    )
    deadline = time.monotonic() + report.observation_seconds
    probe_kinds: list[str] = []
    while time.monotonic() < deadline:
        probe = _probe_claim_batch(args, command_id)
        for item in probe.get("results") or []:
            probe_kinds.append(str(item.get("kind")))
        report.reclaim_probe_count = _reclaim_candidates(args, command_id)
        time.sleep(max(1.0, float(args.poll_seconds)))
    report.claim_probe_kinds = probe_kinds
    report.worker_b_instance = _parse_worker_instance(_worker_logs(args))
    report.after_restart = _snapshot_command(args, command_id)
    report.sink_after_restart = _sink_count(args, command_id)
    report.provider_entered_after_restart = (
        _marker_path(args, campaign_a, "provider_entered").is_file()
        or _marker_path(args, campaign_b, "provider_entered").is_file()
    )

    _assert_true(report, report.sink_after_restart == 0, "A4 sink remains 0 (C3)")
    _assert_true(
        report,
        report.after_restart.status == "provider_write_started",
        "A4 status unchanged provider_write_started",
    )
    _assert_true(
        report,
        report.after_restart.provider_write_started_at
        == report.after_kill.provider_write_started_at,
        "A4 provider_write_started_at unchanged",
    )
    _assert_true(
        report,
        report.reclaim_probe_count == 0,
        "A4 reclaim SQL excludes command",
    )
    _assert_true(
        report,
        _pending_candidates(args, command_id) == 0,
        "A4 pending claim path excludes command",
    )
    _assert_true(
        report,
        all(k in {"none", "disabled"} for k in probe_kinds) and len(probe_kinds) >= 1,
        f"A4 claim_batch never returns command (kinds={probe_kinds})",
    )
    _assert_true(
        report,
        not report.provider_entered_after_restart,
        "A4 provider_entered remains absent",
    )
    _assert_true(
        report,
        report.after_restart.attempt_count
        == (report.before_kill.attempt_count if report.before_kill else 0),
        "A4 no new attempt created",
    )
    _assert_true(
        report,
        report.worker_a_instance is not None
        and report.worker_b_instance is not None
        and report.worker_a_instance != report.worker_b_instance,
        "A4 worker A/B instance ids differ",
    )
    report.notes.append("intentionally_stranded=post_barrier_zero_effect")
    report.notes.append("phase_e_untouched=true")
    report.ok = True
    return report


def _run_post_provider(args: argparse.Namespace, *, reset: bool) -> CampaignReport:
    hold_point = "before_finalize"
    campaign_a = f"a5a6-{uuid4().hex[:8]}"
    campaign_b = f"a5a6-b-{uuid4().hex[:8]}"
    seed = _prepare_stack(args, reset=reset)
    command_id = seed["command_id"]
    report = CampaignReport(
        scenario="post_provider",
        campaign_id_a=campaign_a,
        campaign_id_b=campaign_b,
        command_id=command_id,
        hold_point=hold_point,
    )
    env_a = _campaign_env(
        args,
        hold_point=hold_point,
        campaign_id=campaign_a,
        lease_seconds=args.lease_seconds,
    )
    _start_worker(args, env_a, build=True)
    marker = _wait_marker(args, campaign_a, hold_point, args.marker_timeout)
    meta = _parse_marker(marker)
    report.worker_a_id = meta.get("worker_id")
    report.worker_a_instance = _parse_worker_instance(_worker_logs(args))

    # Ensure provider markers/sink settled.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and _sink_count(args, command_id) < 1:
        time.sleep(0.1)

    report.before_kill = _snapshot_command(args, command_id)
    report.sink_before_kill = _sink_count(args, command_id)
    report.provider_entered_before_kill = _marker_path(
        args, campaign_a, "provider_entered"
    ).is_file()
    _assert_true(
        report,
        report.before_kill.status == "provider_write_started",
        "A5 before kill status=provider_write_started",
    )
    _assert_true(
        report,
        report.before_kill.provider_write_started_at is not None,
        "A5 before kill provider_write_started_at set",
    )
    _assert_true(report, report.sink_before_kill == 1, "A5 before kill sink=1")
    _assert_true(
        report,
        report.provider_entered_before_kill,
        "A5 provider_entered present",
    )
    _assert_true(
        report,
        _marker_path(args, campaign_a, "after_provider").is_file(),
        "A5 after_provider marker present (result known)",
    )

    report.kill = _sigkill_worker(args)
    report.after_kill = _snapshot_command(args, command_id)
    report.sink_after_kill = _sink_count(args, command_id)
    _assert_true(
        report,
        report.after_kill.status == "provider_write_started",
        "A5 after kill remains provider_write_started (finalizer not committed)",
    )
    _assert_true(report, report.sink_after_kill == 1, "A5 after kill sink=1")

    _assert_release_isolation(args, report, hold_point)
    _remove_worker(args)
    env_b = _campaign_env(
        args,
        hold_point="",
        campaign_id=campaign_b,
        lease_seconds=args.lease_seconds,
    )
    _start_worker(args, env_b)
    report.observation_seconds = float(args.observe_seconds)
    report.expected_min_claim_cycles = max(
        1, int(report.observation_seconds // max(1, args.poll_seconds))
    )
    deadline = time.monotonic() + report.observation_seconds
    probe_kinds: list[str] = []
    while time.monotonic() < deadline:
        probe = _probe_claim_batch(args, command_id)
        for item in probe.get("results") or []:
            probe_kinds.append(str(item.get("kind")))
        report.reclaim_probe_count = _reclaim_candidates(args, command_id)
        time.sleep(max(1.0, float(args.poll_seconds)))
    report.claim_probe_kinds = probe_kinds
    report.worker_b_instance = _parse_worker_instance(_worker_logs(args))
    report.after_restart = _snapshot_command(args, command_id)
    report.sink_after_restart = _sink_count(args, command_id)
    # Second provider_entered under B campaign would prove replay.
    report.provider_entered_after_restart = _marker_path(
        args, campaign_b, "provider_entered"
    ).is_file()

    _assert_true(report, report.sink_after_restart == 1, "A6 sink remains exactly 1 (C4)")
    _assert_true(
        report,
        report.after_restart.status == "provider_write_started",
        "A6 remains provider_write_started (no speculative finalizer)",
    )
    _assert_true(
        report,
        report.reclaim_probe_count == 0,
        "A6 reclaim SQL excludes command",
    )
    _assert_true(
        report,
        all(k in {"none", "disabled"} for k in probe_kinds) and len(probe_kinds) >= 1,
        f"A6 claim_batch never returns command (kinds={probe_kinds})",
    )
    _assert_true(
        report,
        not report.provider_entered_after_restart,
        "A6 no second provider_entered under worker B",
    )
    _assert_true(
        report,
        report.worker_a_instance is not None
        and report.worker_b_instance is not None
        and report.worker_a_instance != report.worker_b_instance,
        "A6 worker A/B instance ids differ",
    )
    report.notes.append("intentionally_stranded=post_provider_one_effect")
    report.notes.append("phase_e_untouched=true")
    report.notes.append(
        "finalizer_in_flight=deferred_no_mid_tx_hook",
    )
    report.ok = True
    return report


def _dump_report(report: CampaignReport) -> None:
    payload = asdict(report)
    _print("=== CAMPAIGN REPORT ===")
    _print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("pre_barrier", "post_barrier", "post_provider", "all-required"),
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
    parser.add_argument("--restart-timeout", type=float, default=120.0)
    parser.add_argument("--observe-seconds", type=float, default=8.0)
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Skip down -v (unsafe across scenarios; for debug only)",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        help="Optional path to write aggregated JSON reports",
    )
    args = parser.parse_args(argv)

    if args.project != DEFAULT_PROJECT:
        raise SystemExit(f"refusing non-staging project name: {args.project}")
    if args.lease_seconds < 30:
        raise SystemExit("lease-seconds must be >= 30 (production clamp floor)")

    args.evidence_host_path = Path(args.evidence_host_path).resolve()
    args.compose_file = Path(args.compose_file).resolve()
    args.override_file = Path(args.override_file).resolve()
    args.env_file = Path(args.env_file).resolve()

    scenarios: list[Scenario]
    if args.scenario == "all-required":
        scenarios = ["pre_barrier", "post_barrier", "post_provider"]
    else:
        scenarios = [args.scenario]  # type: ignore[list-item]

    reports: list[CampaignReport] = []
    reset_first = not args.no_reset
    try:
        for idx, scenario in enumerate(scenarios):
            reset = reset_first or idx > 0
            # Always reset between distinct scenarios for isolation.
            if scenario == "pre_barrier":
                report = _run_pre_barrier(args, reset=reset)
            elif scenario == "post_barrier":
                report = _run_post_barrier(args, reset=True)
            elif scenario == "post_provider":
                report = _run_post_provider(args, reset=True)
            else:
                raise CampaignError(f"unknown scenario {scenario}")
            _dump_report(report)
            reports.append(report)
            if not report.ok:
                return 1
    except CampaignError as exc:
        _print(f"CAMPAIGN FAILED: {exc}")
        if args.report_json:
            args.report_json.write_text(
                json.dumps([asdict(r) for r in reports] + [{"error": str(exc)}], indent=2),
                encoding="utf-8",
            )
        return 1
    finally:
        # Leave stack up for inspection unless all-required completed cleanly;
        # caller may down. Do not prune production.
        pass

    if args.report_json:
        args.report_json.write_text(
            json.dumps([asdict(r) for r in reports], indent=2, default=str),
            encoding="utf-8",
        )

    _print("=== ALL REQUIRED CAMPAIGNS PASSED ===")
    _print("A7/A8 finalizer-in-flight: DEFERRED (no mid-finalizer TX DI hook)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
