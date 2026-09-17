"""Counting mock provider adapters — never call real APIs."""

from __future__ import annotations

import asyncio
from typing import Any


class CountingAdapter:
    def __init__(
        self,
        platform: str,
        *,
        post_id: str = "f4-new-post",
        success: bool = True,
        delay_s: float = 0.0,
        error: str | None = None,
        ambiguous: bool = False,
        mock: bool = False,
    ):
        self.platform = platform
        self.post_id = post_id
        self.success = success
        self.delay_s = delay_s
        self.error = error
        self.ambiguous = ambiguous
        self.mock = mock
        self.invocation_count = 0
        self.calls: list[Any] = []

    async def __call__(self, ctx) -> dict:
        self.invocation_count += 1
        account = getattr(ctx, "account", None) or getattr(ctx, "publishing_account", None)
        account_id = getattr(account, "id", None) if account is not None else None
        self.calls.append(
            {
                "platform": self.platform,
                "account_id": str(account_id) if account_id else None,
                "content_id": str(getattr(ctx, "content_id", None)),
            }
        )
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.ambiguous:
            return {
                "platform": self.platform,
                "success": False,
                "error": "ambiguous provider outcome",
                "ambiguous": True,
                "platform_post_id": None,
                "mock": False,
                "retryable": False,
            }
        if not self.success:
            return {
                "platform": self.platform,
                "success": False,
                "error": self.error or "provider failure",
                "platform_post_id": None,
                "mock": False,
                "retryable": True,
            }
        return {
            "platform": self.platform,
            "success": True,
            "platform_post_id": self.post_id,
            "post_url": None,
            "mock": self.mock,
        }


class TimeoutAdapter(CountingAdapter):
    async def __call__(self, ctx) -> dict:
        self.invocation_count += 1
        self.calls.append({"platform": self.platform, "timeout": True})
        raise TimeoutError("simulated provider timeout")
