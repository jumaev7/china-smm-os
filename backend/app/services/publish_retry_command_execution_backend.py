"""Fail-closed execution-backend resolver (Phase 3C.1C-D2-B1 / B2b1-A).

Classifies ``PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND`` only.

- ``none`` — D2-B1 runnable (safe pre-executor stop after claim).
- ``fake`` — recognized / requested, **not** approved here. Staging worker
  bootstrap (B2b1-A) must verify identity before constructing a worker with
  a frozen fake execution context.
- real / platform / unknown — fail closed.

This module must never import publishers, ADAPTERS, httpx, FakeProviderExecutor,
the executor, or staging identity guards.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.config import settings

logger = logging.getLogger(__name__)

# Only "none" is D2-B1-executable without staging bootstrap.
D2B1_EXECUTABLE_BACKEND: Final[str] = "none"

# Recognized as a requested staging-fake backend. Approval is NOT granted here.
REQUESTED_FAKE_BACKEND: Final[str] = "fake"
RESERVED_UNIMPLEMENTED_BACKENDS: Final[frozenset[str]] = frozenset({REQUESTED_FAKE_BACKEND})

# Explicit real/platform strings — always refuse; never map to adapters.
UNSUPPORTED_REAL_BACKENDS: Final[frozenset[str]] = frozenset(
    {"telegram", "facebook", "instagram", "real"},
)


class ExecutionBackendKind(str, Enum):
    """Coarse classification of a resolved backend string."""

    NONE = "none"
    RESERVED_UNIMPLEMENTED = "reserved_unimplemented"
    UNSUPPORTED_REAL = "unsupported_real"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ExecutionBackendResolution:
    """Result of normalizing + validating EXECUTION_BACKEND."""

    raw: str
    value: str
    kind: ExecutionBackendKind
    # True only when D2-B1 may proceed past claim into the none-stop path.
    # Fake is never d2b1_runnable — entrypoint must bootstrap separately.
    d2b1_runnable: bool
    reason: str


def normalize_execution_backend(raw: str | None) -> str:
    """Blank/missing → none. Otherwise strip + lowercase. No dynamic import."""
    if raw is None:
        return D2B1_EXECUTABLE_BACKEND
    text = str(raw).strip().lower()
    if not text:
        return D2B1_EXECUTABLE_BACKEND
    return text


def resolve_execution_backend(raw: str | None = None) -> ExecutionBackendResolution:
    """Classify backend from explicit raw or settings. Never approves fake."""
    source = (
        settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND
        if raw is None
        else raw
    )
    value = normalize_execution_backend(source)
    if value == D2B1_EXECUTABLE_BACKEND:
        return ExecutionBackendResolution(
            raw=str(source) if source is not None else "",
            value=value,
            kind=ExecutionBackendKind.NONE,
            d2b1_runnable=True,
            reason="backend_none",
        )
    if value in RESERVED_UNIMPLEMENTED_BACKENDS:
        return ExecutionBackendResolution(
            raw=str(source),
            value=value,
            kind=ExecutionBackendKind.RESERVED_UNIMPLEMENTED,
            d2b1_runnable=False,
            reason="backend_fake_requires_staging_bootstrap",
        )
    if value in UNSUPPORTED_REAL_BACKENDS:
        return ExecutionBackendResolution(
            raw=str(source),
            value=value,
            kind=ExecutionBackendKind.UNSUPPORTED_REAL,
            d2b1_runnable=False,
            reason="backend_unsupported",
        )
    return ExecutionBackendResolution(
        raw=str(source),
        value=value,
        kind=ExecutionBackendKind.INVALID,
        d2b1_runnable=False,
        reason="backend_invalid",
    )


def assert_worker_execution_backend_or_exit() -> None:
    """Startup gate for the backend=none D2-B1 path only.

    Non-zero exit if backend is not ``none``. Entrypoint must NOT call this
    when dispatching the staging-fake bootstrap path — bootstrap owns fake
    approval. Prefer fail-visible over silent hard-disable.
    """
    resolution = resolve_execution_backend()
    if resolution.d2b1_runnable and resolution.value == D2B1_EXECUTABLE_BACKEND:
        return
    logger.error(
        "[RetryCommandWorker] refusing start: PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=%r "
        "reason=%s (D2-B1 allows only 'none' here; fake requires staging bootstrap; "
        "real platforms unsupported)",
        resolution.value,
        resolution.reason,
    )
    raise SystemExit(2)
