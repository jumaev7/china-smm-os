"""Advertising intelligence provider adapter registry.

``get_adapter(provider)`` returns a cached, read-only adapter instance for use
by the import / ingestion engine. Unknown providers resolve to
:class:`UnsupportedAdvertisingAdapter` (which still serves deterministic mock
data for ``mock`` connections and otherwise reports ``unsupported`` without ever
fabricating live data). This function never raises.

Only Meta (read-only, credentials-gated) and Mock (deterministic offline) are
wired. Every adapter exposes read/observe methods only.
"""
from __future__ import annotations

from app.services.advertising_intelligence.providers.base import (
    AdvertisingProviderAdapter,
)
from app.services.advertising_intelligence.providers.meta import MetaAdvertisingAdapter
from app.services.advertising_intelligence.providers.mock import (
    MockAdvertisingAdapter,
    build_insights as _mock_insights,
    build_structure as _mock_structure,
)
from app.services.advertising_intelligence.schemas import (
    AdvertisingCapabilities,
    InsightsFetchRequest,
    InsightsFetchResponse,
    ProviderHealth,
    StructureFetchRequest,
    StructureFetchResponse,
)
from app.services.advertising_platform.interfaces import utcnow

_MOCK_CONNECTION = "mock"
_SUPPORTED_METRIC_KEYS = frozenset({
    "impressions", "reach", "clicks", "link_clicks", "video_views",
    "spend_minor", "conversions", "conversion_value_minor",
})


class UnsupportedAdvertisingAdapter(AdvertisingProviderAdapter):
    """Fallback for providers without a dedicated integration.

    Mock connections still receive deterministic data; every other connection
    status is reported as ``unsupported`` and never fabricates data.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def capabilities(self, *, connection_status: str) -> AdvertisingCapabilities:
        if connection_status == _MOCK_CONNECTION:
            return AdvertisingCapabilities(
                provider=self.provider,
                capability_status="mock_only",
                supports_structure_import=True,
                supports_insights=True,
                supports_conversions=True,
                supports_breakdowns=False,
                supported_metric_keys=_SUPPORTED_METRIC_KEYS,
                notes=f"No live '{self.provider}' integration; mock connection uses deterministic data.",
            )
        return AdvertisingCapabilities(
            provider=self.provider,
            capability_status="unsupported",
            supports_structure_import=False,
            supports_insights=False,
            supports_conversions=False,
            supports_breakdowns=False,
            unsupported_reason=f"No advertising integration implemented for provider '{self.provider}'.",
        )

    async def health_check(self, *, connection_status: str) -> ProviderHealth:
        caps = self.capabilities(connection_status=connection_status)
        return ProviderHealth(
            provider=self.provider,
            status="ok" if connection_status == _MOCK_CONNECTION else "unavailable",
            connection_status=connection_status,
            capability_status=caps.capability_status,
            checked_at=utcnow(),
        )

    async def fetch_structure(self, request: StructureFetchRequest) -> StructureFetchResponse:
        if request.connection_status == _MOCK_CONNECTION:
            return _mock_structure(request.provider_account_id)
        return StructureFetchResponse(
            status="unsupported",
            provider_request_count=0,
            message=f"Structure import is not implemented for provider '{self.provider}'.",
        )

    async def fetch_insights(self, request: InsightsFetchRequest) -> InsightsFetchResponse:
        if request.connection_status == _MOCK_CONNECTION:
            return _mock_insights(request)
        return InsightsFetchResponse(
            status="unsupported",
            provider_request_count=0,
            message=f"Insights are not implemented for provider '{self.provider}'.",
        )


_ADAPTERS: dict[str, type[AdvertisingProviderAdapter]] = {
    "mock": MockAdvertisingAdapter,
    "meta": MetaAdvertisingAdapter,
}

_instances: dict[str, AdvertisingProviderAdapter] = {}


def get_adapter(provider: str) -> AdvertisingProviderAdapter:
    """Return a cached read-only adapter for ``provider``. Never raises."""
    cached = _instances.get(provider)
    if cached is not None:
        return cached
    adapter_cls = _ADAPTERS.get(provider)
    adapter: AdvertisingProviderAdapter = (
        adapter_cls() if adapter_cls is not None else UnsupportedAdvertisingAdapter(provider)
    )
    _instances[provider] = adapter
    return adapter


def registered_providers() -> frozenset[str]:
    return frozenset(_ADAPTERS.keys())


__all__ = [
    "get_adapter",
    "registered_providers",
    "AdvertisingProviderAdapter",
    "MockAdvertisingAdapter",
    "MetaAdvertisingAdapter",
    "UnsupportedAdvertisingAdapter",
]
