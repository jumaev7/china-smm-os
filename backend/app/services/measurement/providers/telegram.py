"""Telegram metric provider adapter.

The Telegram Bot API does not expose a reliable, generally-available
post-level metrics endpoint (no impressions/reach/likes/comments/shares for
channel posts via the Bot API). We deliberately do NOT fabricate these
numbers. For accounts with ``status == "mock"`` we delegate to the mock
adapter so demo tenants still see data; for any live account we report the
capability as unsupported rather than guessing.
"""
from __future__ import annotations

from typing import Any

from app.services.measurement.providers.base import MetricProviderAdapter, utcnow
from app.services.measurement.providers.mock import MockAdapter
from app.services.measurement.schemas import (
    AdapterCapabilities,
    MetricFetchRequest,
    MetricFetchResponse,
)

_UNSUPPORTED_REASON = (
    "The Telegram Bot API does not provide reliable post-level engagement "
    "metrics (impressions, reach, likes, comments, shares) for channel or "
    "group posts. Only limited signals (e.g. view counts on channel posts, "
    "when available) may be exposed in future phases."
)


class TelegramAdapter(MetricProviderAdapter):
    platform = "telegram"

    def __init__(self) -> None:
        self._mock = MockAdapter()

    def capabilities(self, *, account_status: str) -> AdapterCapabilities:
        if account_status == "mock":
            mock_caps = self._mock.capabilities(account_status=account_status)
            return AdapterCapabilities(
                platform=self.platform,
                capability_status="mock_only",
                supports_post_level_metrics=True,
                supported_metric_keys=mock_caps.supported_metric_keys,
                notes="Mock account — deterministic mock data used in place of live Telegram metrics.",
            )
        return AdapterCapabilities(
            platform=self.platform,
            capability_status="unsupported",
            supports_post_level_metrics=False,
            supported_metric_keys=frozenset(),
            unsupported_reason=_UNSUPPORTED_REASON,
        )

    async def fetch_publication_metrics(self, request: MetricFetchRequest) -> MetricFetchResponse:
        if request.account_status == "mock":
            return await self._mock.fetch_publication_metrics(request)
        results = {
            pub_id: self._unsupported_result(pub_id, message=_UNSUPPORTED_REASON)
            for pub_id in request.publication_ids
        }
        return MetricFetchResponse(results=results, provider_request_count=0)

    async def fetch_account_publications(
        self,
        *,
        account_status: str,
        provider_account_id: str | None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if account_status == "mock":
            return await self._mock.fetch_account_publications(
                account_status=account_status,
                provider_account_id=provider_account_id,
                cursor=cursor,
                limit=limit,
            )
        return [], None

    async def health_check(self, *, account_status: str) -> dict[str, Any]:
        if account_status == "mock":
            return await self._mock.health_check(account_status=account_status)
        if self.is_disconnected(account_status):
            return {
                "status": "unavailable",
                "capability_status": "unsupported",
                "platform": self.platform,
                "checked_at": utcnow().isoformat(),
            }
        return {
            "status": "ok",
            "capability_status": "unsupported",
            "platform": self.platform,
            "reason": _UNSUPPORTED_REASON,
            "checked_at": utcnow().isoformat(),
        }


__all__ = ["TelegramAdapter"]
