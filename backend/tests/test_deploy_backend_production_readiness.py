"""Mocked readiness / safety tests for ops/deploy-backend-production.sh.

Proves:
  A. health unavailable then 200 → success, single recreate
  B. health never ready → non-zero after short timeout
  C. runtime SCHEDULED_PUBLISH_ENABLED=true → still fails
  D. retry flag enabled → still fails
  E. only one compose up/recreate invocation

No real Docker / production host. Short injectable readiness timing.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SRC = REPO_ROOT / "ops" / "deploy-backend-production.sh"

GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.is_file() else shutil.which("bash")


pytestmark = pytest.mark.skipif(
    not BASH,
    reason="bash required to run deploy helper tests",
)


SAFE_RESOLVED = textwrap.dedent(
    """\
    name: test
    services:
      backend:
        environment:
          SCHEDULED_PUBLISH_ENABLED: "false"
          PUBLISH_RETRY_COMMANDS_ENABLED: "false"
          PUBLISH_RETRY_COMMAND_WORKER_ENABLED: "false"
          PUBLISH_RETRY_COMMAND_CLAIM_ENABLED: "false"
          PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED: "false"
          PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND: "none"
        image: test-backend
    """
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _prepare_workspace(tmp_path: Path) -> Path:
    """Minimal git workspace that satisfies the helper's file gates."""
    root = tmp_path / "app"
    (root / "ops").mkdir(parents=True)
    deploy = root / "ops" / "deploy-backend-production.sh"
    deploy.write_text(
        DEPLOY_SRC.read_text(encoding="utf-8").replace("\r\n", "\n"),
        encoding="utf-8",
        newline="\n",
    )
    _write_executable(deploy, deploy.read_text(encoding="utf-8"))

    (root / "docker-compose.production.yml").write_text(
        "services:\n  backend:\n    image: test\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "cutover-safe.yml").write_text(
        'services:\n  backend:\n    environment:\n      SCHEDULED_PUBLISH_ENABLED: "false"\n',
        encoding="utf-8",
        newline="\n",
    )
    (root / ".env.production").write_text(
        "SCHEDULED_PUBLISH_ENABLED=false\n",
        encoding="utf-8",
        newline="\n",
    )

    subprocess.run(
        ["git", "init"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "test"],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )
    return root


def _install_docker_mock(
    root: Path,
    *,
    health_mode: str,
    runtime_sched: str = "false",
    runtime_retry_cmds: str = "false",
    runtime_retry_worker: str = "false",
    runtime_retry_claim: str = "false",
    runtime_retry_exec: str = "false",
    runtime_retry_backend: str = "none",
    settings_available: bool = True,
) -> Path:
    """Install a PATH docker stub. health_mode: eventually_ok | never | ok_immediate."""
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    state = root / "mock-state"
    state.mkdir(parents=True)
    (state / "health_hits").write_text("0", encoding="utf-8", newline="\n")
    (state / "up_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "resolved.yml").write_text(SAFE_RESOLVED, encoding="utf-8", newline="\n")
    (state / "health_mode").write_text(health_mode, encoding="utf-8", newline="\n")
    (state / "runtime_sched").write_text(runtime_sched, encoding="utf-8", newline="\n")
    (state / "runtime_retry_cmds").write_text(runtime_retry_cmds, encoding="utf-8", newline="\n")
    (state / "runtime_retry_worker").write_text(runtime_retry_worker, encoding="utf-8", newline="\n")
    (state / "runtime_retry_claim").write_text(runtime_retry_claim, encoding="utf-8", newline="\n")
    (state / "runtime_retry_exec").write_text(runtime_retry_exec, encoding="utf-8", newline="\n")
    (state / "runtime_retry_backend").write_text(runtime_retry_backend, encoding="utf-8", newline="\n")
    (state / "settings_available").write_text(
        "1" if settings_available else "0", encoding="utf-8", newline="\n"
    )

    mock = textwrap.dedent(
        r"""
        #!/usr/bin/env bash
        set -euo pipefail
        STATE="${MOCK_STATE:?}"

        _bump() {
          local f="$1"
          local n
          n="$(cat "$f")"
          echo $((n + 1)) >"$f"
          echo $((n + 1))
        }

        if [[ "${1:-}" == "compose" ]]; then
          shift
          sub=""
          args=("$@")
          i=0
          while (( i < ${#args[@]} )); do
            case "${args[$i]}" in
              config|up|ps)
                sub="${args[$i]}"
                break
                ;;
            esac
            i=$((i + 1))
          done
          case "$sub" in
            config)
              cat "$STATE/resolved.yml"
              exit 0
              ;;
            up)
              _bump "$STATE/up_count" >/dev/null
              echo "recreated backend" >&2
              exit 0
              ;;
            ps)
              echo "cid-test-backend"
              exit 0
              ;;
            *)
              echo "docker compose mock: unknown subcommand: $*" >&2
              exit 99
              ;;
          esac
        fi

        if [[ "${1:-}" == "inspect" ]]; then
          fmt=""
          while [[ $# -gt 0 ]]; do
            case "$1" in
              -f|--format)
                fmt="$2"
                shift 2
                ;;
              *)
                shift
                ;;
            esac
          done
          if [[ "$fmt" == *".Name"* ]]; then
            echo "/china-smm-os-production-backend-1"
            exit 0
          fi
          if [[ "$fmt" == *".State.Status"* && "$fmt" != *Health* ]]; then
            echo "running"
            exit 0
          fi
          hits="$(cat "$STATE/health_hits")"
          mode="$(cat "$STATE/health_mode")"
          if [[ "$mode" == "ok_immediate" ]]; then
            echo "healthy"
          elif [[ "$mode" == "never" ]]; then
            echo "starting"
          elif [[ "$hits" -ge 2 ]]; then
            echo "healthy"
          else
            echo "starting"
          fi
          exit 0
        fi

        if [[ "${1:-}" == "exec" ]]; then
          shift
          if [[ "${1:-}" == "-i" ]]; then
            shift
          fi
          shift  # cid
          if [[ "${1:-}" == "printenv" ]]; then
            key="${2:-}"
            case "$key" in
              SCHEDULED_PUBLISH_ENABLED) cat "$STATE/runtime_sched" ;;
              PUBLISH_RETRY_COMMANDS_ENABLED) cat "$STATE/runtime_retry_cmds" ;;
              PUBLISH_RETRY_COMMAND_WORKER_ENABLED) cat "$STATE/runtime_retry_worker" ;;
              PUBLISH_RETRY_COMMAND_CLAIM_ENABLED) cat "$STATE/runtime_retry_claim" ;;
              PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED) cat "$STATE/runtime_retry_exec" ;;
              PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND) cat "$STATE/runtime_retry_backend" ;;
              *) echo ""; exit 1 ;;
            esac
            exit 0
          fi
          if [[ "${1:-}" == "python" && "${2:-}" == "-" ]]; then
            if [[ "$(cat "$STATE/settings_available")" != "1" ]]; then
              exit 1
            fi
            sched="$(cat "$STATE/runtime_sched")"
            [[ "$sched" == "false" ]] && sched_py=False || sched_py=True
            rc="$(cat "$STATE/runtime_retry_cmds")"
            [[ "$rc" == "false" ]] && rc_py=False || rc_py=True
            rw="$(cat "$STATE/runtime_retry_worker")"
            [[ "$rw" == "false" ]] && rw_py=False || rw_py=True
            rcl="$(cat "$STATE/runtime_retry_claim")"
            [[ "$rcl" == "false" ]] && rcl_py=False || rcl_py=True
            re="$(cat "$STATE/runtime_retry_exec")"
            [[ "$re" == "false" ]] && re_py=False || re_py=True
            rb="$(cat "$STATE/runtime_retry_backend")"
            printf '%s\n' \
              "SCHEDULED_PUBLISH_ENABLED=${sched_py}" \
              "PUBLISH_RETRY_COMMANDS_ENABLED=${rc_py}" \
              "PUBLISH_RETRY_COMMAND_WORKER_ENABLED=${rw_py}" \
              "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=${rcl_py}" \
              "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=${re_py}" \
              "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=${rb}"
            exit 0
          fi
          if [[ "${1:-}" == "python" && "${2:-}" == "-c" ]]; then
            hits="$(_bump "$STATE/health_hits")"
            mode="$(cat "$STATE/health_mode")"
            if [[ "$mode" == "ok_immediate" ]]; then
              echo "200"
              exit 0
            fi
            if [[ "$mode" == "never" ]]; then
              exit 1
            fi
            if [[ "$hits" -ge 2 ]]; then
              echo "200"
              exit 0
            fi
            exit 1
          fi
          echo "docker exec mock: unhandled: $*" >&2
          exit 98
        fi

        if [[ "${1:-}" == "ps" ]]; then
          exit 0
        fi

        echo "docker mock: unhandled: $*" >&2
        exit 97
        """
    ).lstrip()

    docker_path = bin_dir / "docker"
    _write_executable(docker_path, mock)
    return state


def _to_bash_path(path: Path | str) -> str:
    """Convert a Windows path to a Git Bash / MSYS path when needed."""
    text = str(path).replace("\\", "/")
    if len(text) >= 2 and text[1] == ":":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def _run_helper(root: Path, state: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    bin_dir = _to_bash_path(root / "bin")
    # Keep PATH bash-native (:) so the mock `docker` wins under Git Bash on Windows.
    env["PATH"] = ":".join(
        [
            bin_dir,
            "/usr/bin",
            "/bin",
            "/mingw64/bin",
            "/cmd",
        ]
    )
    env["MOCK_STATE"] = _to_bash_path(state)
    env["APP_DIR"] = _to_bash_path(root)
    env["READINESS_POLL_INTERVAL_SEC"] = "1"
    env["READINESS_TIMEOUT_SEC"] = "3"
    cwd = _to_bash_path(root)
    return subprocess.run(
        [BASH, "-lc", 'cd "$1" && ./ops/deploy-backend-production.sh', "_", cwd],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_helper_script_declares_readiness_polling_defaults():
    script = DEPLOY_SRC.read_text(encoding="utf-8")
    assert 'READINESS_POLL_INTERVAL_SEC="${READINESS_POLL_INTERVAL_SEC:-2}"' in script
    assert 'READINESS_TIMEOUT_SEC="${READINESS_TIMEOUT_SEC:-60}"' in script
    assert "wait_for_backend_readiness" in script
    assert "backend readiness timeout" in script
    # Still single recreate; no automatic second up.
    assert script.count("force-recreate") == 1
    assert "cutover-safe.yml" in script


def test_A_health_eventually_ok_single_recreate(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root, health_mode="eventually_ok")
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "readiness: PASS" in proc.stdout
    assert "DONE (safe recreate)" in proc.stdout
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"


def test_B_health_never_ready_times_out(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root, health_mode="never")
    proc = _run_helper(root, state)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "backend readiness timeout" in combined
    assert "last_http=" in combined
    assert "last_docker_health=" in combined
    # Must not recreate again after timeout.
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"


def test_C_runtime_scheduled_publish_true_still_fails(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(
        root, health_mode="ok_immediate", runtime_sched="true"
    )
    proc = _run_helper(root, state)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "SCHEDULED_PUBLISH_ENABLED=true" in combined
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"


def test_D_retry_flag_enabled_still_fails(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(
        root,
        health_mode="ok_immediate",
        runtime_retry_exec="true",
    )
    proc = _run_helper(root, state)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=true" in combined
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"


def test_E_only_one_compose_up_recreate(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root, health_mode="eventually_ok")
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"
    # Failure path also stays at one.
    root2 = _prepare_workspace(tmp_path / "failcase")
    state2 = _install_docker_mock(root2, health_mode="never")
    proc2 = _run_helper(root2, state2)
    assert proc2.returncode != 0
    assert (state2 / "up_count").read_text(encoding="utf-8").strip() == "1"
