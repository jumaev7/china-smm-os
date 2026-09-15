"""Low-cardinality counters for R3 write-coordination shadow observation.

Metrics failures must never affect publish/retry behavior.
No tenant, content, attempt, or command IDs in labels/keys.
"""
from __future__ import annotations

import logging
import threading
from typing import Dict

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_counters: Dict[str, int] = {
    "shadow_evaluations_total": 0,
    "shadow_no_intent_context_total": 0,
    "shadow_unresolved_detected_total": 0,
    "shadow_same_intent_success_total": 0,
    "shadow_disagreement_total": 0,
    "shadow_error_total": 0,
    # Bounded disagreement dimensions (no UUIDs)
    "shadow_disagreement_live_allow_shadow_block_total": 0,
    "shadow_disagreement_live_block_shadow_allow_total": 0,
}


def inc(name: str, amount: int = 1) -> None:
    """Best-effort counter increment. Never raises to callers."""
    try:
        with _lock:
            _counters[name] = int(_counters.get(name, 0)) + int(amount)
    except Exception:  # noqa: BLE001 — metrics must not break publish path
        logger.debug(
            "[WriteCoordShadowMetrics] increment failed name=%s",
            name,
            exc_info=True,
        )


def snapshot() -> Dict[str, int]:
    with _lock:
        return dict(_counters)


def reset_for_tests() -> None:
    with _lock:
        for key in list(_counters):
            _counters[key] = 0
