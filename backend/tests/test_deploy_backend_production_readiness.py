"""Mocked readiness / safety tests for ops/deploy-backend-production.sh.

Proves:
  A. health unavailable then 200 → success, single recreate
  B. health never ready → non-zero after short timeout
  C. runtime SCHEDULED_PUBLISH_ENABLED=true → still fails
  D. retry flag enabled → still fails
  E. only one compose up/recreate invocation

F3 immutable inputs are supplied with a mocked local image identity.
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
OVERRIDE_TEMPLATE_SRC = (
    REPO_ROOT / "ops" / "compose-backend-image.override.yml.template"
)

GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.is_file() else shutil.which("bash")


pytestmark = pytest.mark.skipif(
    not BASH,
    reason="bash required to run deploy helper tests",
)

IMAGE_ID = "sha256:" + ("c" * 64)
IMAGE_REF = f"china-smm-os-production-backend@{IMAGE_ID}"


def _safe_resolved(backend_image: str = IMAGE_REF) -> str:
    return (
        "name: test\n"
        "services:\n"
        "  postgres:\n"
        "    image: postgres:16-alpine\n"
        "  backend:\n"
        "    environment:\n"
        '      SCHEDULED_PUBLISH_ENABLED: "false"\n'
        '      PUBLISH_WRITE_COORDINATION_SHADOW: "false"\n'
        '      PUBLISH_WRITE_COORDINATION_ENABLED: "false"\n'
        '      PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED: "false"\n'
        '      PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED: "false"\n'
        '      PUBLISH_RETRY_STRANDED_LIST_API_ENABLED: "false"\n'
        '      PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED: "false"\n'
        '      PUBLISH_RETRY_COMMANDS_ENABLED: "false"\n'
        '      PUBLISH_RETRY_COMMAND_WORKER_ENABLED: "false"\n'
        '      PUBLISH_RETRY_COMMAND_CLAIM_ENABLED: "false"\n'
        '      PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED: "false"\n'
        '      PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND: "none"\n'
        '      OPERATOR_AUTO_ACK_ALERTS_ENABLED: "false"\n'
        f"    image: {backend_image}\n"
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
    (root / "ops" / "compose-backend-image.override.yml.template").write_text(
        OVERRIDE_TEMPLATE_SRC.read_text(encoding="utf-8").replace("\r\n", "\n"),
        encoding="utf-8",
        newline="\n",
    )

    (root / "docker-compose.production.yml").write_text(
        "services:\n  backend:\n    image: test\n  postgres:\n    image: postgres:16-alpine\n",
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

    files = {
        "app/services/publish_service.py": b"publish_service_v1\n",
        "app/core/config.py": b"config_v1\n",
        "app/main.py": b"main_v1\n",
        "app/api/v1/publishing.py": b"publishing_v1\n",
        "app/services/publish_resilience.py": b"resilience_v1\n",
    }
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)

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


def _actual_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(root), text=True
    ).strip()


def _file_hashes(root: Path) -> dict[str, str]:
    import hashlib

    out: dict[str, str] = {}
    for rel in (
        "app/services/publish_service.py",
        "app/core/config.py",
        "app/main.py",
        "app/api/v1/publishing.py",
        "app/services/publish_resilience.py",
    ):
        out["/app/" + rel] = hashlib.sha256((root / rel).read_bytes()).hexdigest()
    return out


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
    sha = _actual_sha(root)
    hashes = _file_hashes(root)

    (state / "health_hits").write_text("0", encoding="utf-8", newline="\n")
    (state / "up_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "resolved.yml").write_text(_safe_resolved(), encoding="utf-8", newline="\n")
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
    (state / "image_id").write_text(IMAGE_ID, encoding="utf-8", newline="\n")
    (state / "latest_id").write_text("sha256:" + ("d" * 64), encoding="utf-8", newline="\n")
    (state / "image_label_sha").write_text(sha, encoding="utf-8", newline="\n")
    hash_lines = "\n".join(f"{digest}  {path}" for path, digest in hashes.items())
    (state / "file_hashes.txt").write_text(hash_lines + "\n", encoding="utf-8", newline="\n")

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

        if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
          # (readiness mock — keep image identity stubs)
          shift 2
          fmt=""
          target=""
          while [[ $# -gt 0 ]]; do
            case "$1" in
              -f|--format) fmt="$2"; shift 2 ;;
              *) target="$1"; shift ;;
            esac
          done
          if [[ "$target" == "china-smm-os-production-backend:latest" ]]; then
            cat "$STATE/latest_id"
            exit 0
          fi
          if [[ "$fmt" == *".Id"* ]]; then
            cat "$STATE/image_id"
            exit 0
          fi
          if [[ "$fmt" == *"org.opencontainers.image.revision"* ]]; then
            cat "$STATE/image_label_sha"
            exit 0
          fi
          if [[ "$fmt" == *".Config.Env"* ]]; then
            echo "SOURCE_SHA=$(cat "$STATE/image_label_sha")"
            exit 0
          fi
          exit 0
        fi

        if [[ "${1:-}" == "run" ]]; then
          path=""
          for a in "$@"; do
            if [[ "$a" == /app/* ]]; then
              path="$a"
            fi
          done
          if [[ -n "$path" ]]; then
            grep -F "  $path" "$STATE/file_hashes.txt"
            exit 0
          fi
          exit 1
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
          if [[ "$fmt" == *".Image"* ]]; then
            cat "$STATE/image_id"
            exit 0
          fi
          if [[ "$fmt" == *"org.opencontainers.image.revision"* ]]; then
            cat "$STATE/image_label_sha"
            exit 0
          fi
          if [[ "$fmt" == *".State.StartedAt"* ]]; then
            echo "2026-09-17T00:00:00Z"
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
              PUBLISH_WRITE_COORDINATION_SHADOW|\
              PUBLISH_WRITE_COORDINATION_ENABLED|\
              PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED|\
              PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED|\
              PUBLISH_RETRY_STRANDED_LIST_API_ENABLED|\
              PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED|\
              OPERATOR_AUTO_ACK_ALERTS_ENABLED) echo "false" ;;
              PUBLISH_RETRY_COMMANDS_ENABLED) cat "$STATE/runtime_retry_cmds" ;;
              PUBLISH_RETRY_COMMAND_WORKER_ENABLED) cat "$STATE/runtime_retry_worker" ;;
              PUBLISH_RETRY_COMMAND_CLAIM_ENABLED) cat "$STATE/runtime_retry_claim" ;;
              PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED) cat "$STATE/runtime_retry_exec" ;;
              PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND) cat "$STATE/runtime_retry_backend" ;;
              SOURCE_SHA) cat "$STATE/image_label_sha" ;;
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
              "PUBLISH_WRITE_COORDINATION_SHADOW=False" \
              "PUBLISH_WRITE_COORDINATION_ENABLED=False" \
              "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED=False" \
              "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED=False" \
              "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED=False" \
              "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED=False" \
              "PUBLISH_RETRY_COMMANDS_ENABLED=${rc_py}" \
              "PUBLISH_RETRY_COMMAND_WORKER_ENABLED=${rw_py}" \
              "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=${rcl_py}" \
              "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=${re_py}" \
              "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=${rb}" \
              "OPERATOR_AUTO_ACK_ALERTS_ENABLED=False"
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
    env["BACKEND_IMAGE_REF"] = IMAGE_REF
    env["EXPECTED_BACKEND_IMAGE_ID"] = IMAGE_ID
    env["EXPECTED_SOURCE_SHA"] = _actual_sha(root)
    cwd = _to_bash_path(root)
    cmd = (
        f'export PATH="{bin_dir}:/usr/bin:/bin:/mingw64/bin"; '
        f'cd "{cwd}" && ./ops/deploy-backend-production.sh'
    )
    return subprocess.run(
        [BASH, "-c", cmd],
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
    assert script.count("up -d --no-deps --force-recreate") == 1
    assert "cutover-safe.yml" in script
    assert "BACKEND_IMAGE_REF" in script


def test_A_health_eventually_ok_single_recreate(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root, health_mode="eventually_ok")
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "readiness: PASS" in proc.stdout
    assert "DONE (immutable safe recreate)" in proc.stdout
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
