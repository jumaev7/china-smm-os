"""Deterministic retry delay calculation for durable automation jobs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.automation import (
    AUTOMATION_RETRY_BACKOFFS,
    DEFAULT_RETRY_DELAY_SECONDS,
    MAX_SCHEDULER_DELAY_SECONDS,
)


def clamp_retry_delay_seconds(value: int | None) -> int:
    """Clamp policy base delay to a positive bounded value."""
    try:
        delay = int(value) if value is not None else DEFAULT_RETRY_DELAY_SECONDS
    except (TypeError, ValueError):
        delay = DEFAULT_RETRY_DELAY_SECONDS
    if delay <= 0:
        delay = DEFAULT_RETRY_DELAY_SECONDS
    return min(delay, MAX_SCHEDULER_DELAY_SECONDS)


def normalize_retry_backoff(value: str | None) -> str:
    backoff = (value or "fixed").strip().lower()
    if backoff not in AUTOMATION_RETRY_BACKOFFS:
        return "fixed"
    return backoff


def compute_retry_delay_seconds(
    *,
    retry_number: int,
    base_delay_seconds: int | None,
    backoff: str | None,
    max_delay_seconds: int = MAX_SCHEDULER_DELAY_SECONDS,
) -> int:
    """
    Compute bounded delay for retry_number (1-based).

    fixed:       delay = base
    linear:      delay = base * retry_number
    exponential: delay = base * 2^(retry_number - 1)
    """
    if retry_number <= 0:
        return 0

    base = clamp_retry_delay_seconds(base_delay_seconds)
    mode = normalize_retry_backoff(backoff)
    cap = max(1, min(int(max_delay_seconds), MAX_SCHEDULER_DELAY_SECONDS))

    if mode == "linear":
        delay = base * retry_number
    elif mode == "exponential":
        # Cap exponent growth before multiply to avoid overflow.
        exp = min(retry_number - 1, 20)
        delay = base * (2 ** exp)
    else:
        delay = base

    return min(max(0, int(delay)), cap)


def compute_retry_schedule(
    *,
    retry_number: int,
    base_delay_seconds: int | None,
    backoff: str | None,
    now: datetime | None = None,
    max_delay_seconds: int = MAX_SCHEDULER_DELAY_SECONDS,
) -> tuple[datetime, datetime, int]:
    """Return (scheduled_for, available_at, delay_seconds) in UTC."""
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delay = compute_retry_delay_seconds(
        retry_number=retry_number,
        base_delay_seconds=base_delay_seconds,
        backoff=backoff,
        max_delay_seconds=max_delay_seconds,
    )
    due = when + timedelta(seconds=delay)
    return due, due, delay
