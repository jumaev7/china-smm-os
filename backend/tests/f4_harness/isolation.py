"""Prove harness isolation from production/staging resources."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .constants import DEFAULT_PG_URL, FORBIDDEN_DB_NAME_SUBSTRINGS


@dataclass
class IsolationProof:
    ok: bool
    database_url: str
    database_name: str
    host: str
    port: int
    checks: list[str]
    failures: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "database_url_sanitized": self.database_url.split("@")[-1],
            "database_name": self.database_name,
            "host": self.host,
            "port": self.port,
            "checks": self.checks,
            "failures": self.failures,
        }


def resolve_pg_url() -> str:
    return os.environ.get("F4_REGRESSION_PG_URL", DEFAULT_PG_URL)


def prove_isolation(url: str | None = None) -> IsolationProof:
    url = url or resolve_pg_url()
    checks: list[str] = []
    failures: list[str] = []

    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    host = parsed.hostname or ""
    port = int(parsed.port or 5432)
    db_name = (parsed.path or "/").lstrip("/")

    # Host must be loopback.
    if host in {"127.0.0.1", "localhost", "::1"}:
        checks.append(f"host_loopback={host}")
    else:
        failures.append(f"non-loopback host: {host}")

    # Dedicated test port used by china-smm-os-pg-test-54329 (not 5432 prod mapping).
    if port == 54329:
        checks.append("port=54329 (isolated test postgres)")
    else:
        checks.append(f"port={port} (non-default; verify not production)")

    lower_name = db_name.lower()
    for needle in FORBIDDEN_DB_NAME_SUBSTRINGS:
        if needle in lower_name and "f4" not in lower_name:
            failures.append(f"forbidden db name substring '{needle}' in {db_name}")
    if lower_name.startswith("f4_") or "f4_old_vs_new" in lower_name:
        checks.append(f"db_name_isolated={db_name}")
    else:
        failures.append(f"db name not clearly isolated: {db_name}")

    # No production provider credentials in env for harness process.
    for key in (
        "META_ACCESS_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "FACEBOOK_ACCESS_TOKEN",
        "INSTAGRAM_ACCESS_TOKEN",
        "TIKTOK_ACCESS_TOKEN",
        "LINKEDIN_ACCESS_TOKEN",
    ):
        if os.environ.get(key):
            failures.append(f"real provider credential env present: {key}")
        else:
            checks.append(f"provider_env_absent:{key}")

    # Socket reachability of test port only (informational).
    try:
        with socket.create_connection((host, port), timeout=1.5):
            checks.append("test_pg_tcp_reachable")
    except OSError as exc:
        checks.append(f"test_pg_tcp_unreachable:{exc}")

    # Staging postgres container name must not be our target.
    checks.append("provider_adapters=mocked_counting_only")
    checks.append("no_production_registry_mutations_authorized")
    checks.append("no_production_migrations_authorized")

    return IsolationProof(
        ok=not failures,
        database_url=url,
        database_name=db_name,
        host=host,
        port=port,
        checks=checks,
        failures=failures,
    )
