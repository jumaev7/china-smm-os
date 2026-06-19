"""Timeout and partial-response helpers for heavy endpoints."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import is_pool_exhaustion_error

logger = logging.getLogger(__name__)

ENDPOINT_TIMEOUT_SEC = 12.0
SCAN_TIMEOUT_SEC = 30.0

T = TypeVar("T")


async def run_guarded(
    coro: Awaitable[T],
    *,
    label: str,
    timeout: float = ENDPOINT_TIMEOUT_SEC,
) -> T:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("[API TIMEOUT] %s exceeded %.1fs", label, timeout)
        raise HTTPException(
            status_code=504,
            detail=f"Request timed out ({label}). Try again or narrow filters.",
        ) from None
    except Exception as exc:
        if is_pool_exhaustion_error(exc):
            logger.error("[API POOL] %s: database pool exhausted", label)
            raise HTTPException(
                status_code=503,
                detail="Database temporarily overloaded — retry shortly.",
            ) from exc
        raise


async def safe_section(
    name: str,
    coro: Awaitable[T],
    *,
    default: T,
    errors: list[str],
    timeout: float = 8.0,
    db: AsyncSession | None = None,
) -> T:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("[API PARTIAL] %s: timed out", name)
        errors.append(name)
        if db is not None:
            await db.rollback()
        return default
    except Exception as exc:
        if is_pool_exhaustion_error(exc):
            logger.error("[API PARTIAL] %s: database pool exhausted", name)
        else:
            logger.warning("[API PARTIAL] %s: %s", name, exc)
        errors.append(name)
        if db is not None:
            await db.rollback()
        return default


async def gather_sections(
    sections: list[tuple[str, Callable[[], Awaitable[Any]], Any]],
    errors: list[str],
    *,
    timeout: float = 8.0,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, factory, default in sections:
        out[key] = await safe_section(key, factory(), default=default, errors=errors, timeout=timeout)
    return out
