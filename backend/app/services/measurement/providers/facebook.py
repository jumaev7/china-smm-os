"""Facebook metric provider adapter.

Facebook's Graph API Page Insights *can* expose rich post-level metrics
(impressions, reach, reactions, clicks, video views, ...), but wiring up a
live, token-authenticated Insights fetch is out of scope for Phase 2. Rather
than fabricate numbers that look real, live accounts report the insights
capability as unsupported/limited. Mock accounts delegate to the deterministic
mock adapter so demo tenants still see data. Health checks report ``ok`` as
long as the account is connected — connectivity and metrics-capability are
tracked independently.
"""
from __future__ import annotations

from typing import Any

from app.services.measurement.metric_catalog import supported_metric_keys_for
from app.services.measurement.providers.base import MetricProviderAdapter, utcnow
from app.services.measurement.providers.mock import MockAdapter
from app.services.measurement.schemas import (
    AdapterCapabilities,
    MetricFetchRequest,
    MetricFetchResponse,
)

_UNSUPPORTED_REASON = (
    "Live Facebook Page Insights collection is not implemented in this phase. "
    "Provider field mappings are catalogued for future use, but no live "
    "metrics are fetched or fabricated."
)


class FacebookAdapter(MetricProviderAdapter):
    platform = "facebook"

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
                notes="Mock account — deterministic mock data used in place of live Facebook Insights.",
            )
        # Live: mappings are known (catalog), but fetching is unimplemented —
        # report "limited" rather than pretending full support, and don't
        # advertise any metric as actually fetchable yet.
        return AdapterCapabilities(
            platform=self.platform,
            capability_status="limited",
            supports_post_level_metrics=False,
            supported_metric_keys=frozenset(),
            unsupported_reason=_UNSUPPORTED_REASON,
            notes=(
                f"Known Graph API field mappings exist for "
                f"{sorted(supported_metric_keys_for('facebook'))}, but live fetch is not wired up yet."
            ),
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
                "capability_status": "limited",
                "platform": self.platform,
                "checked_at": utcnow().isoformat(),
            }
        return {
            "status": "ok",
            "capability_status": "limited",
            "platform": self.platform,
            "reason": _UNSUPPORTED_REASON,
            "checked_at": utcnow().isoformat(),
        }


__all__ = ["FacebookAdapter"]
