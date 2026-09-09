"""Fail-closed execution-backend resolver (Phase 3C.1C-D2-B1 / D2-B2a).

D2-B1 allows only ``none`` as a runnable worker configuration. That value means
a safe pre-executor stop after claim/reclaim — no Preparation, Barrier,
provider, or Finalizer invocation.

``fake`` is recognized as reserved for the D2-B2a staging harness but remains
**not worker-runnable**. Harness fake resolution requires
VerifiedRetryCommandStagingContext and lives outside this worker path.

Real platform names and unknown values fail closed. This module must never
import publishers, ADAPTERS, httpx, FakeProviderExecutor, or the executor.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.config import settings

logger = logging.getLogger(__name__)

# Only "none" is executable by the worker in D2-B1/B2a. Missing/blank → none.
D2B1_EXECUTABLE_BACKEND: Final[str] = "none"

# Recognized for staging harness (D2-B2a) but intentionally unimplemented for
# the long-running worker path.
RESERVED_UNIMPLEMENTED_BACKENDS: Final[frozenset[str]] = frozenset({"fake"})

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
    """Resolve backend from explicit raw or settings. Never falls back to adapters."""
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
            reason="backend_unimplemented",
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
    """Startup gate when the worker process is intentionally enabled.

    Decision (D2-B1): non-zero process exit if WORKER=true and backend != none.
    Prefer fail-visible over silent hard-disable so misconfiguration cannot
    look like healthy claim observation under an unimplemented backend.
    """
    resolution = resolve_execution_backend()
    if resolution.d2b1_runnable and resolution.value == D2B1_EXECUTABLE_BACKEND:
        return
    logger.error(
        "[RetryCommandWorker] refusing start: PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=%r "
        "reason=%s (D2-B1/B2a allows only 'none'; fake is staging-harness-only; "
        "real platforms unsupported)",
        resolution.value,
        resolution.reason,
    )
    raise SystemExit(2)
