"""Lightweight in-memory TTL cache for analytics aggregates."""
from __future__ import annotations

import time
from typing import Any, Callable, Awaitable

_DEFAULT_TTL_SECONDS = 60

_store: dict[str, tuple[float, Any]] = {}


def get_cached(key: str) -> Any | None:
    entry = _store.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _store.pop(key, None)
        return None
    return value


def set_cached(key: str, value: Any, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
    _store[key] = (time.monotonic() + ttl_seconds, value)


async def cached_async(
    key: str,
    loader: Callable[[], Awaitable[Any]],
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> Any:
    hit = get_cached(key)
    if hit is not None:
        return hit
    value = await loader()
    set_cached(key, value, ttl_seconds=ttl_seconds)
    return value
