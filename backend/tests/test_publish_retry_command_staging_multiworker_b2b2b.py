"""Phase 3C.1C-D2-B2b2-B — multi-worker + stale-owner concurrency proofs.

Focused tests:
- committed multi-worker runner / dual-worker compose override
- no production claim/barrier/executor semantic edits in this gate
- Docker process campaigns B1–B6 (+ optional B7) marked staging_docker

Core invariant: fake_invoke_count <= 1 per command with two live workers.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
SERVICES = BACKEND / "app" / "services"
CLAIM_PATH = SERVICES / "publish_retry_command_claim_service.py"
BARRIER_PATH = SERVICES / "publish_retry_command_barrier_service.py"
EXECUTOR_PATH = SERVICES / "publish_retry_command_executor.py"
RUNNER = SCRIPTS / "run_staging_retry_command_multiworker_campaign.py"
SEED = SCRIPTS / "seed_staging_retry_command_fixture.py"
PROBE = SCRIPTS / "probe_staging_retry_command_claim.py"
COMPOSE = REPO_ROOT / "docker-compose.staging.yml"
OVERRIDE = REPO_ROOT / "docker-compose.staging.b2b2b-campaign.yml"
ENV_STAGING = REPO_ROOT / ".env.staging.example"
DOCS = REPO_ROOT / "docs" / "STAGING_RETRY_COMMAND_WORKER.md"

CANONICAL_SERVICE_FILES = [
    SERVICES / "publish_retry_command_claim_service.py",
    SERVICES / "publish_retry_command_preparation_service.py",
    SERVICES / "publish_retry_command_barrier_service.py",
    SERVICES / "publish_retry_command_finalization_service.py",
    SERVICES / "publish_retry_command_executor.py",
]


def test_multiworker_runner_and_helpers_committed():
    assert RUNNER.is_file()
    assert SEED.is_file()
    assert PROBE.is_file()
    assert OVERRIDE.is_file()
    assert COMPOSE.is_file()
    assert ENV_STAGING.is_file()
    text = RUNNER.read_text(encoding="utf-8")
    assert "china-smm-os-staging" in text
    assert "WORKER_A" in text or "worker-a" in text
    assert "WORKER_B" in text or "worker-b" in text
    assert "fake_invoke" in text or "sink" in text
    assert "FOR UPDATE SKIP LOCKED" in text or "SKIP LOCKED" in text
    assert "stale_owner" in text
    assert "claim_race" in text
    assert "Phase E" in text or "phase_e" in text.lower()


def test_compose_dual_workers_pid1_and_evidence_mount():
    override = OVERRIDE.read_text(encoding="utf-8")
    assert "publish-retry-command-worker-a" in override
    assert "publish-retry-command-worker-b" in override
    assert "hostname: worker-a" in override
    assert "hostname: worker-b" in override
    assert 'restart: "no"' in override
    assert "STAGING_EVIDENCE_HOST_PATH" in override
    assert "WORKER_A_HOLD_POINT" in override
    assert "WORKER_B_HOLD_POINT" in override
    assert "python scripts/run_publish_retry_command_worker.py" in override
    base = COMPOSE.read_text(encoding="utf-8")
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND: fake" in base
    assert "china-smm-os-staging" in base


def test_no_runtime_correctness_semantics_touched_by_runner():
    """Diff gate: runner/tests must not rewrite claim/barrier/executor services."""
    runner = RUNNER.read_text(encoding="utf-8")
    # Runner may reference services only as documentation strings, not import them
    # into production mutation paths.
    assert "PublishRetryCommandClaimService" not in runner
    assert "PublishRetryCommandBarrierService" not in runner
    for path in CANONICAL_SERVICE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "PhaseE" not in text
        assert "phase_e_recovery" not in text


def test_claim_still_uses_skip_locked_and_barrier_validates_owner():
    claim = CLAIM_PATH.read_text(encoding="utf-8")
    assert "skip_locked=True" in claim
    barrier = BARRIER_PATH.read_text(encoding="utf-8")
    assert "lease_owner_mismatch" in barrier
    assert "lease_expired" in barrier
    assert ".with_for_update()" in barrier


def test_pending_claim_sql_not_silently_hardened():
    """B2b2-B must not silently add provider_write_started_at to pending SQL.

    Pending claim still filters in Python; SQL selects status==pending only.
    """
    tree = ast.parse(CLAIM_PATH.read_text(encoding="utf-8"))
    pending_fn = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "PublishRetryCommandClaimService":
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == "_claim_pending":
                    pending_fn = item
                    break
    assert pending_fn is not None
    dump = ast.dump(pending_fn)
    assert "status" in dump
    src = CLAIM_PATH.read_text(encoding="utf-8")
    assert "if row.provider_write_started_at is not None:" in src
    assert "provider_write_started_at.is_(None)" in src


def test_canonical_services_do_not_import_coordinator_or_phase_e():
    forbidden = (
        "publish_retry_command_staging_lifecycle_coordinator",
        "PhaseE",
        "phase_e_recovery",
        "mark_ambiguous_stranded",
    )
    for path in CANONICAL_SERVICE_FILES:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} must not reference {token}"


def test_docs_mention_multiworker_campaign():
    text = DOCS.read_text(encoding="utf-8")
    assert "B2b2-B" in text
    assert "run_staging_retry_command_multiworker_campaign.py" in text


def test_runner_help_smoke():
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--help"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "claim_race" in result.stdout
    assert "stale_owner" in result.stdout
    assert "two_command" in result.stdout
    assert "reclaim_barrier_race" in result.stdout


def test_executor_has_no_process_local_lock_for_cross_worker_safety():
    """Cross-process safety must not depend on asyncio/threading locks in executor."""
    src = EXECUTOR_PATH.read_text(encoding="utf-8")
    assert "asyncio.Lock" not in src
    assert "threading.Lock" not in src
    claim = CLAIM_PATH.read_text(encoding="utf-8")
    assert "asyncio.Lock" not in claim
    assert "threading.Lock" not in claim


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.staging_docker
def test_docker_multiworker_campaigns_b1_through_b6():
    """Process-level B1–B6 gate. Requires Docker. Do not silently skip in gate runs."""
    if os.environ.get("B2B2B_SKIP_DOCKER") == "1":
        pytest.fail(
            "B2B2B_SKIP_DOCKER=1 is set — refusing silent skip during B2b2-B gate"
        )
    if not _docker_available():
        pytest.fail("Docker unavailable — B2b2-B process campaigns cannot run")

    report_path = REPO_ROOT / ".staging-b2b2b-evidence" / "campaign-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Include optional B7 in the gate when INCLUDE_OPTIONAL=1 (default on).
    include_optional = os.environ.get("B2B2B_INCLUDE_OPTIONAL", "1") == "1"
    cmd = [
        sys.executable,
        str(RUNNER),
        "--scenario",
        "all-required",
        "--lease-seconds",
        "30",
        "--poll-seconds",
        "1",
        "--observe-seconds",
        "8",
        "--claim-iterations",
        os.environ.get("B2B2B_CLAIM_ITERATIONS", "12"),
        "--report-json",
        str(report_path),
    ]
    if include_optional:
        cmd.append("--include-optional")

    result = subprocess.run(
        cmd,
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "multi-worker campaigns failed\n"
            f"stdout:\n{result.stdout[-8000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    assert report_path.is_file()
    reports = json.loads(report_path.read_text(encoding="utf-8"))
    by_scenario = {r["scenario"]: r for r in reports if "scenario" in r}
    assert "claim_race" in by_scenario
    assert "stale_owner" in by_scenario
    assert "two_command" in by_scenario
    assert "reclaim_barrier_race" in by_scenario
    for key in ("claim_race", "stale_owner", "two_command", "reclaim_barrier_race"):
        r = by_scenario[key]
        assert r["ok"] is True, key
        assert r["worker_a"]["worker_instance"]
        assert r["worker_b"]["worker_instance"]
        assert r["worker_a"]["worker_instance"] != r["worker_b"]["worker_instance"]
        for cid, sink in (r.get("sink_by_command") or {}).items():
            assert sink <= 1, f"{key} {cid} sink={sink}"
    claim = by_scenario["claim_race"]
    assert len(claim["iterations"]) >= 10
    assert all(it["ok"] and it["sink"] == 1 for it in claim["iterations"])
    stale = by_scenario["stale_owner"]
    assert stale["attempt_count"] == 1
    assert list(stale["sink_by_command"].values()) == [1]
    two = by_scenario["two_command"]
    assert len(two["command_ids"]) == 2
    assert all(v == 1 for v in two["sink_by_command"].values())
    if include_optional:
        assert "post_barrier_overlap" in by_scenario
        assert by_scenario["post_barrier_overlap"]["ok"] is True
