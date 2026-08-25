"""Static assertions for production Compose Integration Health flag wiring.

No Docker required — parses docker-compose.production.yml as text so CI stays light.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.production.yml"

CHECK_KEY = "INTEGRATION_HEALTH_CHECK_ENABLED"
REMOTE_KEY = "INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED"
FAIL_CLOSED = "${INTEGRATION_HEALTH_CHECK_ENABLED:-false}"
FAIL_CLOSED_REMOTE = "${INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED:-false}"


def _service_blocks(text: str) -> dict[str, str]:
    """Split top-level compose services into name -> block body."""
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


def test_production_compose_wires_ih_flags_on_backend_only_fail_closed():
    text = COMPOSE.read_text(encoding="utf-8")
    assert CHECK_KEY in text
    assert REMOTE_KEY in text
    assert FAIL_CLOSED in text
    assert FAIL_CLOSED_REMOTE in text

    services = _service_blocks(text)
    assert "backend" in services
    backend = services["backend"]
    assert CHECK_KEY in backend
    assert REMOTE_KEY in backend
    assert FAIL_CLOSED in backend
    assert FAIL_CLOSED_REMOTE in backend

    # Workers inherit shared env but must not receive IH scheduler permission keys.
    for name in (
        "automation-worker",
        "telegram-webhook-worker",
        "listening-worker",
        "publish-alert-telegram-worker",
        "migrate",
    ):
        body = services.get(name, "")
        assert CHECK_KEY not in body, f"{name} must not define {CHECK_KEY}"
        assert REMOTE_KEY not in body, f"{name} must not define {REMOTE_KEY}"

    # Shared anchor must also stay free of IH keys (backend-only override).
    assert f"    {CHECK_KEY}:" not in text.split("services:")[0]
    assert f"    {REMOTE_KEY}:" not in text.split("services:")[0]
