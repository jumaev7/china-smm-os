"""Production compose + deploy helper safety for scheduled publishing.

Proves the fail-closed posture that caused the recreate footgun cannot
resolve SCHEDULED_PUBLISH_ENABLED=true for the production backend under
the intended safe configuration.

No production deploy. Docker is optional for the resolved-config check.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.production.yml"
CUTOVER = REPO_ROOT / "cutover-safe.yml"
DEPLOY = REPO_ROOT / "ops" / "deploy-backend-production.sh"
ENV_EXAMPLE = REPO_ROOT / ".env.production.example"


def _service_blocks(text: str) -> dict[str, str]:
    services: dict[str, str] = {}
    lines = text.splitlines()
    in_services = False
    current: str | None = None
    buf: list[str] = []
    for line in lines:
        if line.startswith("services:"):
            in_services = True
            continue
        if not in_services:
            continue
        if line.startswith("networks:") or line.startswith("volumes:"):
            break
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            if current is not None:
                services[current] = "\n".join(buf)
            current = line.strip().rstrip(":")
            buf = []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        services[current] = "\n".join(buf)
    return services


def test_production_compose_hard_pins_scheduled_publish_false_on_backend():
    text = COMPOSE.read_text(encoding="utf-8")
    services = _service_blocks(text)
    backend = services["backend"]
    assert 'SCHEDULED_PUBLISH_ENABLED: "false"' in backend
    assert 'SCHEDULED_PUBLISH_ENABLED: "true"' not in backend
    # Must be a literal pin, not env interpolation (env true must not win).
    assert "${SCHEDULED_PUBLISH_ENABLED" not in backend


def test_cutover_safe_is_defense_in_depth_false_pin():
    text = CUTOVER.read_text(encoding="utf-8")
    assert 'SCHEDULED_PUBLISH_ENABLED: "false"' in text
    assert 'SCHEDULED_PUBLISH_ENABLED: "true"' not in text
    services = _service_blocks(text)
    assert "backend" in services
    assert 'SCHEDULED_PUBLISH_ENABLED: "false"' in services["backend"]


def test_deploy_script_requires_both_compose_files_and_hard_gates():
    script = DEPLOY.read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert "docker-compose.production.yml" in script
    assert "cutover-safe.yml" in script
    assert ".env.production" in script
    assert "--no-deps" in script
    assert "--force-recreate" in script
    assert "retry-command" in script
    assert "SCHEDULED_PUBLISH_ENABLED" in script
    assert "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND" in script
    # Backend-only recreate; no broad `up -d` without service name.
    assert re.search(
        r'up -d --no-deps --force-recreate\s+"\$BACKEND_SERVICE"',
        script,
    )
    assert "abort" in script.lower() or "die " in script


def test_env_production_example_defaults_scheduled_publish_false():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(r"^SCHEDULED_PUBLISH_ENABLED=false\s*$", text, re.M)
    assert not re.search(r"^SCHEDULED_PUBLISH_ENABLED=true\s*$", text, re.M)


def test_prepare_production_env_writes_scheduled_publish_false():
    ps1 = (REPO_ROOT / "scripts" / "prepare-production-env.ps1").read_text(
        encoding="utf-8"
    )
    assert 'SCHEDULED_PUBLISH_ENABLED = "false"' in ps1
    assert 'SCHEDULED_PUBLISH_ENABLED = "true"' not in ps1


def _minimal_production_env(path: Path) -> None:
    """Enough keys for compose ${VAR:?...} interpolation without real secrets."""
    required = {
        "DATABASE_URL": "postgresql+psycopg://u:p@postgres:5432/db",
        "SECRET_KEY": "test-secret-key-not-real",
        "ADMIN_SECRET_KEY": "test-admin-secret-not-real",
        "TENANT_SECRET_KEY": "test-tenant-secret-not-real",
        "POSTGRES_PASSWORD": "test-postgres-password",
        "S3_BUCKET": "test-bucket",
        "S3_ENDPOINT_URL": "https://example.invalid",
        "S3_ACCESS_KEY": "test-access",
        "S3_SECRET_KEY": "test-secret",
        "OPENAI_API_KEY": "sk-test",
        "TELEGRAM_BOT_TOKEN": "1:test",
        "TELEGRAM_ADMIN_ID": "1",
        "TELEGRAM_WEBHOOK_SECRET": "whsec-test",
        "META_APP_ID": "1",
        "META_APP_SECRET": "meta-secret",
        "LISTENING_META_WEBHOOK_VERIFY_TOKEN": "verify-test",
        "TUNNEL_TOKEN": "tunnel-test",
        # Footgun regression: even if env says true, compose must stay false.
        "SCHEDULED_PUBLISH_ENABLED": "true",
        "PUBLISH_RETRY_COMMANDS_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_WORKER_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED": "false",
        "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND": "none",
    }
    path.write_text(
        "\n".join(f"{k}={v}" for k, v in required.items()) + "\n",
        encoding="utf-8",
    )


def _backend_env_from_compose_config(yaml_text: str) -> dict[str, str]:
    services = _service_blocks(yaml_text)
    backend = services.get("backend", "")
    env: dict[str, str] = {}
    in_env = False
    for line in backend.splitlines():
        if re.match(r"^    environment:", line):
            in_env = True
            continue
        if in_env and re.match(r"^    [a-zA-Z0-9_]+:", line):
            break
        if not in_env:
            continue
        m = re.match(r'^\s+([A-Z0-9_]+):\s*"?([^"]*)"?\s*$', line)
        if m:
            env[m.group(1)] = m.group(2)
    return env


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_incident_command_production_compose_alone_resolves_scheduled_false():
    """Regression for the footgun recreate that omitted cutover-safe.yml.

    After hardening, this exact pattern must resolve backend scheduled
    publishing to false even when .env.production says true.
    """
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / "env.production.test"
        _minimal_production_env(env_path)
        proc = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_path),
                "-f",
                str(COMPOSE),
                "config",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "COMPOSE_ANSI": "never"},
        )
        assert proc.returncode == 0, proc.stderr
        backend_env = _backend_env_from_compose_config(proc.stdout)
        assert backend_env.get("SCHEDULED_PUBLISH_ENABLED") == "false"
        assert backend_env.get("PUBLISH_RETRY_COMMANDS_ENABLED") == "false"
        assert backend_env.get("PUBLISH_RETRY_COMMAND_WORKER_ENABLED") == "false"
        assert backend_env.get("PUBLISH_RETRY_COMMAND_CLAIM_ENABLED") == "false"
        assert backend_env.get("PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED") == "false"
        assert backend_env.get("PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND") == "none"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_canonical_pair_also_resolves_scheduled_false():
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / "env.production.test"
        _minimal_production_env(env_path)
        proc = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_path),
                "-f",
                str(COMPOSE),
                "-f",
                str(CUTOVER),
                "config",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "COMPOSE_ANSI": "never"},
        )
        assert proc.returncode == 0, proc.stderr
        backend_env = _backend_env_from_compose_config(proc.stdout)
        assert backend_env.get("SCHEDULED_PUBLISH_ENABLED") == "false"
