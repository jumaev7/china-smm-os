"""Low-cardinality in-process counters for retry-command claim/prepare/barrier/executor.

Metrics failures must never affect claim/prepare/barrier/executor correctness.
No tenant or command IDs.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_counters: Dict[str, int] = {
    "retry_command_claim_total": 0,
    "retry_command_reclaim_total": 0,
    "retry_command_claim_none_total": 0,
    "retry_command_claim_error_total": 0,
    "retry_command_claim_disabled_total": 0,
    "retry_command_prepare_total": 0,
    "retry_command_prepare_reuse_total": 0,
    "retry_command_prepare_blocked_total": 0,
    "retry_command_prepare_invariant_error_total": 0,
    "retry_command_barrier_crossed_total": 0,
    "retry_command_barrier_denied_total": 0,
    "retry_command_barrier_invariant_error_total": 0,
    # D2-A executor / fake provider (no tenant/account/command labels)
    "retry_command_provider_calls_total": 0,
    "retry_command_provider_success_total": 0,
    "retry_command_provider_failure_total": 0,
    "retry_command_provider_ambiguous_total": 0,
    "retry_command_finalize_total": 0,
}


def inc(name: str, amount: int = 1) -> None:
    """Best-effort counter increment. Never raises to callers."""
    try:
        with _lock:
            _counters[name] = int(_counters.get(name, 0)) + int(amount)
    except Exception:  # noqa: BLE001 — metrics must not break claim path
        logger.debug("[RetryCommandMetrics] increment failed name=%s", name, exc_info=True)


def snapshot() -> Dict[str, int]:
    with _lock:
        return dict(_counters)


def reset_for_tests() -> None:
    with _lock:
        for key in list(_counters):
            _counters[key] = 0
