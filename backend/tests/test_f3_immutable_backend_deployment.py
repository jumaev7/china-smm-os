"""F3 — immutable backend deployment safety (mocked Docker/Compose).

Covers required cases A–V without real production deployment.
Destructive paths use fake docker/compose outputs only.
"""
from __future__ import annotations

import os
import re
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
DOCKERFILE_SRC = REPO_ROOT / "backend" / "Dockerfile"
COMPOSE_SRC = REPO_ROOT / "docker-compose.production.yml"

GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
BASH = str(GIT_BASH) if GIT_BASH.is_file() else shutil.which("bash")

pytestmark = pytest.mark.skipif(
    not BASH,
    reason="bash required to run deploy helper tests",
)

FULL_SHA = "d88ac6d10c183e3fe6e93a3ecdcc4ab27db8ce24"
IMAGE_ID = "sha256:" + ("a" * 64)
IMAGE_ID_WRONG = "sha256:" + ("b" * 64)
IMAGE_REF_DIGEST = f"china-smm-os-production-backend@{IMAGE_ID}"
IMAGE_REF_TAG = "china-smm-os-production-backend:r3-d88ac6d1"
WRONG_SHA = "0123456789abcdef0123456789abcdef01234567"

SAFE_ENV = textwrap.dedent(
    """\
    SCHEDULED_PUBLISH_ENABLED: "false"
    PUBLISH_WRITE_COORDINATION_SHADOW: "false"
    PUBLISH_WRITE_COORDINATION_ENABLED: "false"
    PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED: "false"
    PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED: "false"
    PUBLISH_RETRY_STRANDED_LIST_API_ENABLED: "false"
    PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED: "false"
    PUBLISH_RETRY_COMMANDS_ENABLED: "false"
    PUBLISH_RETRY_COMMAND_WORKER_ENABLED: "false"
    PUBLISH_RETRY_COMMAND_CLAIM_ENABLED: "false"
    PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED: "false"
    PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND: "none"
    OPERATOR_AUTO_ACK_ALERTS_ENABLED: "false"
    OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED: "false"
    """
)


def _safe_resolved(*, backend_image: str = IMAGE_REF_DIGEST, **env_overrides: str) -> str:
    env = {
        "SCHEDULED_PUBLISH_ENABLED": "false",
        "PUBLISH_WRITE_COORDINATION_SHADOW": "false",
        "PUBLISH_WRITE_COORDINATION_ENABLED": "false",
        "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED": "false",
        "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED": "false",
        "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED": "false",
        "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED": "false",
        "PUBLISH_RETRY_COMMANDS_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND": "none",
        "OPERATOR_AUTO_ACK_ALERTS_ENABLED": "false",
        "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED": "false",
    }
    env.update(env_overrides)
    env_lines = "\n".join(f'      {k}: "{v}"' for k, v in env.items())
    # Build with zero top-level indent (do not mix textwrap.dedent with interpolated blocks).
    return (
        "name: test\n"
        "services:\n"
        "  postgres:\n"
        "    image: postgres:16-alpine\n"
        "  backend:\n"
        f"    image: {backend_image}\n"
        "    environment:\n"
        f"{env_lines}\n"
        "  frontend:\n"
        "    image: test-frontend:latest\n"
        "  migrate:\n"
        "    image: china-smm-os-production-backend:latest\n"
        "    profiles:\n"
        "      - tools\n"
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _to_bash_path(path: Path | str) -> str:
    text = str(path).replace("\\", "/")
    if len(text) >= 2 and text[1] == ":":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def _prepare_workspace(tmp_path: Path, *, source_sha: str = FULL_SHA) -> Path:
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
        "services:\n  backend:\n    image: china-smm-os-production-backend:latest\n"
        "  postgres:\n    image: postgres:16-alpine\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "cutover-safe.yml").write_text(
        'services:\n  backend:\n    environment:\n      SCHEDULED_PUBLISH_ENABLED: "false"\n',
        encoding="utf-8",
        newline="\n",
    )
    (root / ".env.production").write_text(
        "SCHEDULED_PUBLISH_ENABLED=false\nDATABASE_URL=postgresql://x\n",
        encoding="utf-8",
        newline="\n",
    )

    # Minimal files for source-hash proof paths (content fixed for stable hashes).
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

    subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(root),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=str(root),
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "test"],
        cwd=str(root),
        check=True,
        capture_output=True,
    )
    # Soft-reset commit to desired SHA is impossible; store mapping via note file
    # and rewrite EXPECTED to actual HEAD unless caller needs a fixed SHA.
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(root), text=True
    ).strip()
    (root / ".f3_actual_sha").write_text(head, encoding="utf-8", newline="\n")
    if source_sha != FULL_SHA:
        # Keep marker only; callers use actual HEAD.
        pass
    return root


def _actual_sha(root: Path) -> str:
    return (root / ".f3_actual_sha").read_text(encoding="utf-8").strip()


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
    health_mode: str = "ok_immediate",
    image_id: str = IMAGE_ID,
    image_label_sha: str | None = None,
    resolved: str | None = None,
    runtime_overrides: dict[str, str] | None = None,
    settings_available: bool = True,
    running_image_id: str | None = None,
    allow_mutate: bool = True,
) -> Path:
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    state = root / "mock-state"
    state.mkdir(parents=True)

    sha = image_label_sha if image_label_sha is not None else _actual_sha(root)
    hashes = _file_hashes(root)

    (state / "health_hits").write_text("0", encoding="utf-8", newline="\n")
    (state / "up_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "build_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "pull_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "tag_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "run_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "migrate_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "worker_start_count").write_text("0", encoding="utf-8", newline="\n")
    (state / "latest_id").write_text(IMAGE_ID_WRONG, encoding="utf-8", newline="\n")
    (state / "image_id").write_text(image_id, encoding="utf-8", newline="\n")
    (state / "running_image_id").write_text(
        running_image_id or image_id, encoding="utf-8", newline="\n"
    )
    (state / "image_label_sha").write_text(sha, encoding="utf-8", newline="\n")
    (state / "health_mode").write_text(health_mode, encoding="utf-8", newline="\n")
    (state / "settings_available").write_text(
        "1" if settings_available else "0", encoding="utf-8", newline="\n"
    )
    (state / "allow_mutate").write_text(
        "1" if allow_mutate else "0", encoding="utf-8", newline="\n"
    )
    (state / "override_seen").write_text("0", encoding="utf-8", newline="\n")
    (state / "resolved.yml").write_text(
        resolved or _safe_resolved(), encoding="utf-8", newline="\n"
    )

    runtime = {
        "SCHEDULED_PUBLISH_ENABLED": "false",
        "PUBLISH_WRITE_COORDINATION_SHADOW": "false",
        "PUBLISH_WRITE_COORDINATION_ENABLED": "false",
        "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED": "false",
        "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED": "false",
        "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED": "false",
        "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED": "false",
        "PUBLISH_RETRY_COMMANDS_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND": "none",
        "OPERATOR_AUTO_ACK_ALERTS_ENABLED": "false",
        "SOURCE_SHA": sha,
    }
    if runtime_overrides:
        runtime.update(runtime_overrides)
    for k, v in runtime.items():
        (state / f"runtime_{k}").write_text(v, encoding="utf-8", newline="\n")

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

        _refuse_if_dry() {
          if [[ "$(cat "$STATE/allow_mutate")" != "1" ]]; then
            echo "docker mock: mutation refused in dry-run: $*" >&2
            exit 90
          fi
        }

        if [[ "${1:-}" == "compose" ]]; then
          shift
          # Detect forbidden migrate / profile / worker activation.
          joined="$*"
          if [[ "$joined" == *migrate* && "$joined" == *up* ]]; then
            _bump "$STATE/migrate_count" >/dev/null
            echo "docker compose mock: migrate refused" >&2
            exit 91
          fi
          if [[ "$joined" == *"--profile"*retry* || "$joined" == *publish-retry-command-worker* ]]; then
            _bump "$STATE/worker_start_count" >/dev/null
            echo "docker compose mock: worker start refused" >&2
            exit 92
          fi
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
              # Tests pre-bake resolved.yml with the expected backend image.
              # Record that a backend-only override file was present on the CLI.
              j=0
              while (( j < ${#args[@]} )); do
                if [[ "${args[$j]}" == "-f" ]]; then
                  cand="${args[$((j + 1))]:-}"
                  if [[ -f "$cand" ]] && grep -qE 'backend:' "$cand" \
                    && grep -qE 'image:' "$cand" \
                    && ! grep -qE 'postgres:' "$cand"; then
                    echo "1" >"$STATE/override_seen"
                  fi
                fi
                j=$((j + 1))
              done
              cat "$STATE/resolved.yml"
              exit 0
              ;;
            up)
              _refuse_if_dry "$*"
              # Must be backend-only recreate.
              if [[ "$joined" != *"--no-deps"* || "$joined" != *"--force-recreate"* ]]; then
                echo "docker compose mock: expected --no-deps --force-recreate" >&2
                exit 93
              fi
              if [[ "$joined" != *" backend"* && "$joined" != *$'\tbackend'* ]]; then
                # last arg should be backend
                last="${args[$((${#args[@]} - 1))]}"
                if [[ "$last" != "backend" ]]; then
                  echo "docker compose mock: expected backend service only, got: $last" >&2
                  exit 94
                fi
              fi
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

        if [[ "${1:-}" == "build" ]]; then
          _bump "$STATE/build_count" >/dev/null
          echo "docker mock: build refused" >&2
          exit 95
        fi
        if [[ "${1:-}" == "pull" ]]; then
          _bump "$STATE/pull_count" >/dev/null
          echo "docker mock: pull refused" >&2
          exit 95
        fi
        if [[ "${1:-}" == "tag" ]]; then
          _bump "$STATE/tag_count" >/dev/null
          echo "docker mock: tag refused" >&2
          exit 95
        fi

        if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
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
            if [[ "$fmt" == *".Id"* ]]; then
              cat "$STATE/latest_id"
              exit 0
            fi
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
          echo "docker image inspect mock: unhandled fmt=$fmt target=$target" >&2
          exit 96
        fi

        if [[ "${1:-}" == "run" ]]; then
          # ephemeral hash probe — allowed even conceptually in deploy; dry-run helper skips it
          _bump "$STATE/run_count" >/dev/null
          # args: run --rm --entrypoint sha256sum REF PATH
          path=""
          for a in "$@"; do
            if [[ "$a" == /app/* ]]; then
              path="$a"
            fi
          done
          if [[ -n "$path" ]]; then
            line="$(grep -F "  $path" "$STATE/file_hashes.txt" || true)"
            if [[ -z "$line" ]]; then
              echo "missing hash for $path" >&2
              exit 1
            fi
            echo "$line"
            exit 0
          fi
          echo "docker run mock: unhandled $*" >&2
          exit 96
        fi

        if [[ "${1:-}" == "inspect" ]]; then
          fmt=""
          while [[ $# -gt 0 ]]; do
            case "$1" in
              -f|--format) fmt="$2"; shift 2 ;;
              *) shift ;;
            esac
          done
          if [[ "$fmt" == *".Name"* ]]; then
            echo "/china-smm-os-production-backend-1"
            exit 0
          fi
          if [[ "$fmt" == *".Image"* ]]; then
            cat "$STATE/running_image_id"
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
            if [[ -f "$STATE/runtime_$key" ]]; then
              cat "$STATE/runtime_$key"
              exit 0
            fi
            echo ""
            exit 1
          fi
          if [[ "${1:-}" == "python" && "${2:-}" == "-" ]]; then
            if [[ "$(cat "$STATE/settings_available")" != "1" ]]; then
              exit 1
            fi
            pybool() { [[ "$1" == "false" ]] && echo False || echo True; }
            printf '%s\n' \
              "SCHEDULED_PUBLISH_ENABLED=$(pybool "$(cat "$STATE/runtime_SCHEDULED_PUBLISH_ENABLED")")" \
              "PUBLISH_WRITE_COORDINATION_SHADOW=$(pybool "$(cat "$STATE/runtime_PUBLISH_WRITE_COORDINATION_SHADOW")")" \
              "PUBLISH_WRITE_COORDINATION_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_WRITE_COORDINATION_ENABLED")")" \
              "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED")")" \
              "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED")")" \
              "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_STRANDED_LIST_API_ENABLED")")" \
              "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED")")" \
              "PUBLISH_RETRY_COMMANDS_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_COMMANDS_ENABLED")")" \
              "PUBLISH_RETRY_COMMAND_WORKER_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_COMMAND_WORKER_ENABLED")")" \
              "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_COMMAND_CLAIM_ENABLED")")" \
              "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=$(pybool "$(cat "$STATE/runtime_PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED")")" \
              "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=$(cat "$STATE/runtime_PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND")" \
              "OPERATOR_AUTO_ACK_ALERTS_ENABLED=$(pybool "$(cat "$STATE/runtime_OPERATOR_AUTO_ACK_ALERTS_ENABLED")")"
            # alembic / registry probes also use python - ; return unknown-friendly empty for SQL
            exit 0
          fi
          if [[ "${1:-}" == "python" && "${2:-}" == "-c" ]]; then
            hits="$(_bump "$STATE/health_hits")"
            mode="$(cat "$STATE/health_mode")"
            if [[ "$mode" == "ok_immediate" || ( "$mode" != "never" && "$hits" -ge 2 ) ]]; then
              echo "200"
              exit 0
            fi
            exit 1
          fi
          echo "docker exec mock: unhandled: $*" >&2
          exit 98
        fi

        if [[ "${1:-}" == "ps" ]]; then
          # retry worker listing → empty
          exit 0
        fi

        echo "docker mock: unhandled: $*" >&2
        exit 97
        """
    ).lstrip()
    _write_executable(bin_dir / "docker", mock)
    return state


def _base_env(root: Path, state: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    bin_dir = _to_bash_path(root / "bin")
    env["PATH"] = ":".join([bin_dir, "/usr/bin", "/bin", "/mingw64/bin", "/cmd"])
    env["MOCK_STATE"] = _to_bash_path(state)
    env["APP_DIR"] = _to_bash_path(root)
    env["READINESS_POLL_INTERVAL_SEC"] = "1"
    env["READINESS_TIMEOUT_SEC"] = "3"
    env["BACKEND_IMAGE_REF"] = IMAGE_REF_DIGEST
    env["EXPECTED_BACKEND_IMAGE_ID"] = IMAGE_ID
    env["EXPECTED_SOURCE_SHA"] = _actual_sha(root)
    env.update(extra)
    return env


def _run_helper(
    root: Path,
    state: Path,
    *args: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _base_env(root, state, **(env_extra or {}))
    cwd = _to_bash_path(root)
    bin_dir = _to_bash_path(root / "bin")
    arg_str = " ".join(args)
    # Use non-login bash so profile scripts cannot rewrite PATH away from the mock.
    cmd = (
        f'export PATH="{bin_dir}:/usr/bin:/bin:/mingw64/bin"; '
        f'cd "{cwd}" && ./ops/deploy-backend-production.sh {arg_str}'
    )
    return subprocess.run(
        [BASH, "-c", cmd],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# ── Static / contract tests ──────────────────────────────────────────────────


def test_dockerfile_supports_source_sha_identity():
    text = DOCKERFILE_SRC.read_text(encoding="utf-8")
    assert "ARG SOURCE_SHA" in text
    assert "org.opencontainers.image.revision" in text
    assert 'ENV SOURCE_SHA="${SOURCE_SHA}"' in text


def test_override_template_backend_only():
    text = OVERRIDE_TEMPLATE_SRC.read_text(encoding="utf-8")
    assert "services:" in text
    assert "backend:" in text
    assert "__BACKEND_IMAGE_REF__" in text
    # Body may only declare the backend service (ignore comment wording).
    body = text.split("services:", 1)[1]
    assert "postgres" not in body.lower()
    assert "frontend" not in body.lower()
    assert "migrate" not in body.lower()
    assert body.count("image:") == 1


def test_compose_pins_stranded_alert_false():
    text = COMPOSE_SRC.read_text(encoding="utf-8")
    assert (
        "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED: "
        "${PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED:-false}"
    ) in text


def test_helper_script_immutable_contract_markers():
    script = DEPLOY_SRC.read_text(encoding="utf-8")
    assert "BACKEND_IMAGE_REF" in script
    assert "EXPECTED_BACKEND_IMAGE_ID" in script
    assert "EXPECTED_SOURCE_SHA" in script
    assert "dry-run" in script
    assert "--rollback" in script
    assert "force-recreate" in script
    # Exactly one recreate invocation site (array construction for up).
    assert script.count('up -d --no-deps --force-recreate') == 1
    # tolerate documentary mentions of force-recreate elsewhere
    assert "alembic upgrade" not in script
    assert "docker tag" not in script
    assert "docker pull" not in script
    assert "will not pull/build" in script


# ── A–V behavioral tests ─────────────────────────────────────────────────────


def test_A_valid_immutable_image_accepted(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "DONE (immutable safe recreate)" in proc.stdout
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"
    assert (state / "tag_count").read_text(encoding="utf-8").strip() == "0"
    assert (state / "pull_count").read_text(encoding="utf-8").strip() == "0"
    assert (state / "build_count").read_text(encoding="utf-8").strip() == "0"


def test_B_missing_image_reference_rejected(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    proc = _run_helper(root, state, env_extra={"BACKEND_IMAGE_REF": ""})
    assert proc.returncode != 0
    assert "BACKEND_IMAGE_REF is required" in (proc.stdout + proc.stderr)
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"


def test_C_missing_expected_image_id_rejected(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    proc = _run_helper(root, state, env_extra={"EXPECTED_BACKEND_IMAGE_ID": ""})
    assert proc.returncode != 0
    assert "EXPECTED_BACKEND_IMAGE_ID is required" in (proc.stdout + proc.stderr)
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"


def test_D_wrong_image_id_rejected(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root, image_id=IMAGE_ID)
    proc = _run_helper(
        root, state, env_extra={"EXPECTED_BACKEND_IMAGE_ID": IMAGE_ID_WRONG}
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "local_image_id" in combined
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"


def test_E_wrong_source_sha_rejected(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    proc = _run_helper(root, state, env_extra={"EXPECTED_SOURCE_SHA": WRONG_SHA})
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "image_revision_label" in combined or "EXPECTED_SOURCE_SHA" in combined
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"


def test_F_mutable_or_unverified_reference_rejected(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    for bad in (
        "china-smm-os-production-backend:latest",
        "china-smm-os-production-backend",
        "latest",
    ):
        proc = _run_helper(root, state, env_extra={"BACKEND_IMAGE_REF": bad})
        assert proc.returncode != 0, bad
        assert "rejected" in (proc.stdout + proc.stderr).lower()
        assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"


def test_G_latest_remains_unchanged(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    before = (state / "latest_id").read_text(encoding="utf-8").strip()
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    after = (state / "latest_id").read_text(encoding="utf-8").strip()
    assert before == after
    assert (state / "tag_count").read_text(encoding="utf-8").strip() == "0"
    assert "latest unchanged" in proc.stdout


def _flag_reject_case(tmp_path: Path, key: str, value: str = "true") -> None:
    root = _prepare_workspace(tmp_path)
    resolved = _safe_resolved(**{key: value})
    state = _install_docker_mock(root, resolved=resolved)
    proc = _run_helper(root, state)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert key in combined
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"


def test_H_shadow_true_rejected(tmp_path: Path):
    _flag_reject_case(tmp_path, "PUBLISH_WRITE_COORDINATION_SHADOW")


def test_I_write_coordination_true_rejected(tmp_path: Path):
    _flag_reject_case(tmp_path, "PUBLISH_WRITE_COORDINATION_ENABLED")


def test_J_manual_resolution_flags_true_rejected(tmp_path: Path):
    _flag_reject_case(tmp_path, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED")
    _flag_reject_case(
        tmp_path / "e22", "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED"
    )


def test_K_stranded_list_flag_true_rejected(tmp_path: Path):
    _flag_reject_case(tmp_path, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED")


def test_L_stranded_alert_flag_true_rejected(tmp_path: Path):
    _flag_reject_case(tmp_path, "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED")


def test_M_retry_claim_execution_activation_rejected(tmp_path: Path):
    for key in (
        "PUBLISH_RETRY_COMMANDS_ENABLED",
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED",
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED",
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED",
    ):
        _flag_reject_case(tmp_path / key, key)


def test_N_scheduled_publishing_true_rejected(tmp_path: Path):
    _flag_reject_case(tmp_path, "SCHEDULED_PUBLISH_ENABLED")


def test_O_execution_backend_other_than_none_rejected(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    resolved = _safe_resolved(PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND="real")
    state = _install_docker_mock(root, resolved=resolved)
    proc = _run_helper(root, state)
    assert proc.returncode != 0
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND" in (proc.stdout + proc.stderr)
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"


def test_P_valid_flags_pass(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root, resolved=_safe_resolved())
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "preflight gates: PASS" in proc.stdout


def test_Q_override_changes_backend_image_only(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    # Resolved config reflects the backend-only override pin (postgres stays alpine).
    state = _install_docker_mock(
        root,
        resolved=_safe_resolved(backend_image=IMAGE_REF_TAG),
    )
    proc = _run_helper(
        root,
        state,
        "--dry-run",
        env_extra={"BACKEND_IMAGE_REF": IMAGE_REF_TAG},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ephemeral backend image override" in proc.stdout
    assert (state / "override_seen").read_text(encoding="utf-8").strip() == "1"
    resolved_text = (state / "resolved.yml").read_text(encoding="utf-8")
    assert "postgres:16-alpine" in resolved_text
    assert IMAGE_REF_TAG in resolved_text
    assert "china-smm-os-production-backend:latest" in resolved_text  # migrate still latest


def test_R_dry_run_performs_zero_mutations(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root, allow_mutate=False)
    proc = _run_helper(root, state, "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "dry-run complete (zero mutations)" in proc.stdout
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "0"
    assert (state / "build_count").read_text(encoding="utf-8").strip() == "0"
    assert (state / "pull_count").read_text(encoding="utf-8").strip() == "0"
    assert (state / "tag_count").read_text(encoding="utf-8").strip() == "0"
    assert (state / "run_count").read_text(encoding="utf-8").strip() == "0"
    assert "SECRET" not in proc.stdout
    assert "DATABASE_URL=" not in proc.stdout


def test_S_migration_command_never_invoked(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (state / "migrate_count").read_text(encoding="utf-8").strip() == "0"
    script = DEPLOY_SRC.read_text(encoding="utf-8")
    assert "alembic upgrade" not in script
    assert 'profiles: ["tools"]' not in script


def test_T_workers_never_started(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(root)
    proc = _run_helper(root, state)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (state / "worker_start_count").read_text(encoding="utf-8").strip() == "0"
    assert "retry-command worker absent" in proc.stdout


def test_U_wrong_post_deploy_image_identity_detected(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(
        root,
        image_id=IMAGE_ID,
        running_image_id=IMAGE_ID_WRONG,
    )
    proc = _run_helper(root, state)
    assert proc.returncode != 0
    assert "running_container_image_id" in (proc.stdout + proc.stderr)
    # Recreate happened once; postcheck caught mismatch (no auto-rollback).
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"


def test_V_rollback_selects_correct_old_immutable_image(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    old_id = IMAGE_ID
    old_ref = IMAGE_REF_DIGEST
    state = _install_docker_mock(root, image_id=old_id, resolved=_safe_resolved(backend_image=old_ref))
    proc = _run_helper(
        root,
        state,
        "--rollback",
        env_extra={
            "BACKEND_IMAGE_REF": old_ref,
            "EXPECTED_BACKEND_IMAGE_ID": old_id,
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DONE (immutable rollback recreate)" in proc.stdout
    assert old_ref in proc.stdout
    assert (state / "up_count").read_text(encoding="utf-8").strip() == "1"
    assert (state / "migrate_count").read_text(encoding="utf-8").strip() == "0"


def test_sha_specific_tag_accepted_with_id_check(tmp_path: Path):
    root = _prepare_workspace(tmp_path)
    state = _install_docker_mock(
        root, resolved=_safe_resolved(backend_image=IMAGE_REF_TAG)
    )
    proc = _run_helper(
        root, state, env_extra={"BACKEND_IMAGE_REF": IMAGE_REF_TAG}
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "image ref form: tag" in proc.stdout


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker unavailable")
def test_compose_merge_backend_image_only_real_docker(tmp_path: Path):
    """Real `docker compose config` merge: override changes backend image only."""
    root = tmp_path / "merge"
    root.mkdir()
    prod = COMPOSE_SRC.read_text(encoding="utf-8")
    cutover = (REPO_ROOT / "cutover-safe.yml").read_text(encoding="utf-8")
    (root / "docker-compose.production.yml").write_text(prod, encoding="utf-8", newline="\n")
    (root / "cutover-safe.yml").write_text(cutover, encoding="utf-8", newline="\n")
    # Minimal env to satisfy ${VAR:?} interpolations in production compose.
    env_keys = sorted(set(re.findall(r"\$\{([A-Z0-9_]+)(?:\?|:-[^}]*)?\}", prod)))
    lines = []
    for k in env_keys:
        if k in ("PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND",):
            lines.append(f"{k}=none")
        else:
            lines.append(f"{k}=false" if k.endswith("_ENABLED") or "SHADOW" in k else f"{k}=test-value")
    # Force known required secrets-ish keys
    for k in (
        "DATABASE_URL",
        "SECRET_KEY",
        "ADMIN_SECRET_KEY",
        "TENANT_SECRET_KEY",
        "POSTGRES_PASSWORD",
        "S3_BUCKET",
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "OPENAI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ADMIN_ID",
        "TELEGRAM_WEBHOOK_SECRET",
        "META_APP_ID",
        "META_APP_SECRET",
        "LISTENING_META_WEBHOOK_VERIFY_TOKEN",
        "TUNNEL_TOKEN",
    ):
        if not any(line.startswith(k + "=") for line in lines):
            lines.append(f"{k}=test-value")
    (root / ".env.production").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    override = root / "override.yml"
    override.write_text(
        f"services:\n  backend:\n    image: {IMAGE_REF_DIGEST}\n",
        encoding="utf-8",
        newline="\n",
    )
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env.production",
            "-f",
            "docker-compose.production.yml",
            "-f",
            "cutover-safe.yml",
            "-f",
            "override.yml",
            "config",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert f"image: {IMAGE_REF_DIGEST}" in out or f'image: "{IMAGE_REF_DIGEST}"' in out
    assert "postgres:16-alpine" in out
    # migrate / workers still reference the common latest image, not the override digest-only service
    assert "china-smm-os-production-backend:latest" in out
    assert "PUBLISH_WRITE_COORDINATION_SHADOW" in out
    assert "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED" in out
