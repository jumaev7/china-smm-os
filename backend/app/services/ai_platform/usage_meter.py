"""Low-cardinality usage metering helpers (no tenant labels in metrics)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ai_platform.metrics")

# In-process counters for verification (not a full Prometheus client).
_COUNTERS: dict[str, int] = {
    "ai_requests_total": 0,
    "ai_requests_success_total": 0,
    "ai_requests_failed_total": 0,
    "ai_input_tokens_total": 0,
    "ai_output_tokens_total": 0,
    "ai_estimated_cost_minor_total": 0,
    "ai_validation_failures_total": 0,
    "ai_quota_blocks_total": 0,
}


def reset_metrics() -> None:
    for key in _COUNTERS:
        _COUNTERS[key] = 0


def get_metrics() -> dict[str, int]:
    return dict(_COUNTERS)


def inc(metric: str, amount: int = 1, **labels: Any) -> None:
    """Increment a low-cardinality metric. Labels must not include tenant/content IDs."""
    forbidden = {"tenant_id", "content_id", "request_id", "caption", "prompt"}
    if forbidden.intersection(labels):
        labels = {k: v for k, v in labels.items() if k not in forbidden}
    if metric in _COUNTERS:
        _COUNTERS[metric] += amount
    # Safe structured log — no sensitive content.
    logger.info(
        "metric=%s amount=%s labels=%s",
        metric,
        amount,
        {k: labels[k] for k in sorted(labels) if k in ("provider", "task_type", "status", "model_alias")},
    )


def observe_latency_ms(latency_ms: int, *, provider: str, status: str) -> None:
    logger.info(
        "metric=ai_request_latency_ms value=%s provider=%s status=%s",
        latency_ms,
        provider,
        status,
    )
