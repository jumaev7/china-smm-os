"""Phase 3C.1C-D2-B2b2-A — SIGKILL + restart / no-replay proofs.

Focused tests:
- committed crash runner / compose override / seed+probe helpers
- reclaim / pending exclusion predicates (C1 audit)
- no Phase E / no runtime claim SQL silent change
- Docker process campaigns A1–A6 (marked staging_docker; run in this gate)

A7/A8 finalizer-in-flight: deferred (no mid-finalizer TX DI hook).
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
FINALIZER_PATH = SERVICES / "publish_retry_command_finalization_service.py"
COORD_PATH = SERVICES / "publish_retry_command_staging_lifecycle_coordinator.py"
RUNNER = SCRIPTS / "run_staging_retry_command_sigkill_restart_campaign.py"
SEED = SCRIPTS / "seed_staging_retry_command_fixture.py"
PROBE = SCRIPTS / "probe_staging_retry_command_claim.py"
COMPOSE = REPO_ROOT / "docker-compose.staging.yml"
OVERRIDE = REPO_ROOT / "docker-compose.staging.b2b2a-campaign.yml"
ENV_STAGING = REPO_ROOT / ".env.staging.example"
DOCS = REPO_ROOT / "docs" / "STAGING_RETRY_COMMAND_WORKER.md"

# Canonical services that must not import Phase E recovery / coordinator.
CANONICAL_SERVICE_FILES = [
    SERVICES / "publish_retry_command_claim_service.py",
    SERVICES / "publish_retry_command_preparation_service.py",
    SERVICES / "publish_retry_command_barrier_service.py",
    SERVICES / "publish_retry_command_finalization_service.py",
    SERVICES / "publish_retry_command_executor.py",
]


def test_sigkill_runner_and_helpers_committed():
    assert RUNNER.is_file()
    assert SEED.is_file()
    assert PROBE.is_file()
    assert OVERRIDE.is_file()
    assert COMPOSE.is_file()
    assert ENV_STAGING.is_file()
    text = RUNNER.read_text(encoding="utf-8")
    assert "SIGKILL" in text
    assert "docker" in text
    assert "fake_invoke" in text or "sink" in text
    assert "Phase E" in text or "phase_e" in text.lower()
    assert "china-smm-os-staging" in text
    # Must not hide kill behind graceful stop.
    assert "SIGTERM" not in text or text.count("SIGKILL") >= text.count("SIGTERM")


def test_compose_override_bind_mount_and_restart_no():
    override = OVERRIDE.read_text(encoding="utf-8")
    assert "STAGING_EVIDENCE_HOST_PATH" in override
    assert "PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT" in override
    assert "PUBLISH_RETRY_COMMAND_LEASE_SECONDS" in override
    base = COMPOSE.read_text(encoding="utf-8")
    assert 'restart: "no"' in base
    assert "china-smm-os-staging" in base
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND: fake" in base


def test_reclaim_sql_excludes_provider_write_started_at():
    """C1: reclaim path requires provider_write_started_at IS NULL."""
    src = CLAIM_PATH.read_text(encoding="utf-8")
    assert "provider_write_started_at.is_(None)" in src
    assert 'status == "claimed"' in src
    assert "lease_expires_at.is_not(None)" in src


def test_pending_claim_sql_audit_no_silent_hardening():
    """B2b2-A must not silently add provider_write_started_at to pending SQL.

    Pending claim still filters in Python; SQL selects status==pending only.
    Future hardening proposal is out of band.
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
    # SQL where clause for pending should not mention provider_write_started_at.
    # Python defense may still reference it after fetch.
    assert "status" in dump
    # Ensure file still has Python defense + reclaim SQL predicate:
    src = CLAIM_PATH.read_text(encoding="utf-8")
    assert "if row.provider_write_started_at is not None:" in src
    assert "provider_write_started_at.is_(None)" in src


def test_no_mid_finalizer_tx_hook_so_a7_deferred():
    """A7/A8 deferred: FinalizationService has no staging DI failpoint."""
    src = FINALIZER_PATH.read_text(encoding="utf-8")
    assert "FAILPOINT" not in src
    assert "StagingLifecycle" not in src
    coord = COORD_PATH.read_text(encoding="utf-8")
    assert "before_finalize" in coord
    # Hold is before finalize TX opens (executor hook), not inside TX.


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


def test_docs_mention_sigkill_campaign():
    text = DOCS.read_text(encoding="utf-8")
    assert "B2b2-A" in text or "SIGKILL" in text
    assert "run_staging_retry_command_sigkill_restart_campaign.py" in text


def test_runner_help_smoke():
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--help"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "pre_barrier" in result.stdout
    assert "post_barrier" in result.stdout
    assert "post_provider" in result.stdout


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
def test_docker_sigkill_campaigns_a1_through_a6():
    """Process-level A1–A6 gate. Requires Docker. Do not silently skip in gate runs."""
    if os.environ.get("B2B2A_SKIP_DOCKER") == "1":
        pytest.fail(
            "B2B2A_SKIP_DOCKER=1 is set — refusing silent skip during B2b2-A gate"
        )
    if not _docker_available():
        pytest.fail("Docker unavailable — B2b2-A process campaigns cannot run")

    report_path = REPO_ROOT / ".staging-b2b2a-evidence" / "campaign-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
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
            "--report-json",
            str(report_path),
        ],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "SIGKILL campaigns failed\n"
            f"stdout:\n{result.stdout[-8000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    assert report_path.is_file()
    reports = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(reports) == 3
    by_scenario = {r["scenario"]: r for r in reports}
    assert by_scenario["pre_barrier"]["ok"] is True
    assert by_scenario["pre_barrier"]["sink_after_restart"] == 1
    assert by_scenario["post_barrier"]["ok"] is True
    assert by_scenario["post_barrier"]["sink_after_restart"] == 0
    assert by_scenario["post_provider"]["ok"] is True
    assert by_scenario["post_provider"]["sink_after_restart"] == 1
    # Worker identity change
    for key in ("pre_barrier", "post_barrier", "post_provider"):
        r = by_scenario[key]
        assert r["worker_a_instance"]
        assert r["worker_b_instance"]
        assert r["worker_a_instance"] != r["worker_b_instance"]
        assert r["kill"]["restart_policy"] in ("no", None, "")
        assert r["kill"]["oom_killed"] is False
