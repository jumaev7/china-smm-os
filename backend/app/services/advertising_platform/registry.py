"""Read-only advertising provider adapter registry.

``get_adapter(provider)`` returns a cached, read-only adapter instance. Unknown
providers resolve to :class:`UnsupportedAdvertisingAdapter` (mock_only for mock
connections, otherwise unsupported); this function never raises so the caller
decides how to surface "unsupported".

Only Meta (live, read-only) and Mock (deterministic demo/QA) are wired in
Phase 1. Every adapter here exposes read/observe methods only — there is no
create/update/delete/pause/activate/set_budget surface anywhere.
"""
from __future__ import annotations

from app.services.advertising_intelligence.schemas import (
    AdvertisingCapabilities,
    EntityInsightResult,
    InsightsFetchRequest,
    InsightsFetchResponse,
    ProviderAccount,
    ProviderCampaign,
    ProviderHealth,
    ProviderMetric,
    StructureFetchRequest,
    StructureFetchResponse,
)
from app.services.advertising_platform.interfaces import (
    AdvertisingProviderAdapter,
    utcnow,
)

# Metric keys exposed by the Phase-1 read pipeline (provider-native + derived).
_CORE_METRIC_KEYS = frozenset({
    "impressions",
    "reach",
    "frequency",
    "clicks",
    "spend",
    "cpc",
    "cpm",
    "ctr",
    "conversions",
    "cost_per_conversion",
    "conversion_value",
})

_CORE_BREAKDOWNS = frozenset({
    "age",
    "gender",
    "country",
    "region",
    "publisher_platform",
    "platform_position",
    "device_platform",
    "impression_device",
})


class MetaAdvertisingAdapter(AdvertisingProviderAdapter):
    """Read-only Meta (Facebook/Instagram) advertising adapter.

    Reads account structure and insights only. Live Graph API wiring is
    injected by the ingestion layer; this adapter never performs any write /
    mutation call and stores no tokens.
    """

    provider = "meta"

    def capabilities(self, *, connection_status: str) -> AdvertisingCapabilities:
        if connection_status == "mock":
            return AdvertisingCapabilities(
                provider=self.provider,
                capability_status="mock_only",
                supports_structure_import=True,
                supports_insights=True,
                supports_conversions=True,
                supports_breakdowns=True,
                supported_metric_keys=_CORE_METRIC_KEYS,
                supported_breakdowns=_CORE_BREAKDOWNS,
                notes="Mock connection uses deterministic data.",
            )
        if self.is_disconnected(connection_status):
            return AdvertisingCapabilities(
                provider=self.provider,
                capability_status="unsupported",
                supports_structure_import=False,
                supports_insights=False,
                supports_conversions=False,
                supports_breakdowns=False,
                unsupported_reason=f"Meta account connection is '{connection_status}'.",
            )
        return AdvertisingCapabilities(
            provider=self.provider,
            capability_status="full",
            supports_structure_import=True,
            supports_insights=True,
            supports_conversions=True,
            supports_breakdowns=True,
            supported_metric_keys=_CORE_METRIC_KEYS,
            supported_breakdowns=_CORE_BREAKDOWNS,
        )

    async def health_check(self, *, connection_status: str) -> ProviderHealth:
        caps = self.capabilities(connection_status=connection_status)
        if connection_status == "mock":
            status = "ok"
        elif self.is_disconnected(connection_status):
            status = "permission_blocked" if connection_status == "permission_blocked" else "unavailable"
        else:
            status = "ok"
        return ProviderHealth(
            provider=self.provider,
            status=status,
            connection_status=connection_status,
            capability_status=caps.capability_status,
            checked_at=utcnow(),
        )

    async def fetch_structure(self, request: StructureFetchRequest) -> StructureFetchResponse:
        if request.connection_status == "mock":
            return _mock_structure(request)
        if self.is_disconnected(request.connection_status):
            return StructureFetchResponse(
                status="unavailable",
                provider_request_count=0,
                message=f"Meta account connection is '{request.connection_status}'.",
            )
        # Live Graph API reads are performed by the ingestion layer, which
        # injects the fetched payloads. Absent an injected client, return an
        # empty (but successful) read rather than fabricating data.
        return StructureFetchResponse(status="ok", provider_request_count=0)

    async def fetch_insights(self, request: InsightsFetchRequest) -> InsightsFetchResponse:
        if request.connection_status == "mock":
            return _mock_insights(request)
        if self.is_disconnected(request.connection_status):
            return InsightsFetchResponse(
                status="unavailable",
                provider_request_count=0,
                message=f"Meta account connection is '{request.connection_status}'.",
            )
        return InsightsFetchResponse(status="ok", provider_request_count=0)


class MockAdvertisingAdapter(AdvertisingProviderAdapter):
    """Deterministic read-only adapter for demo/QA tenants."""

    provider = "mock"

    def capabilities(self, *, connection_status: str) -> AdvertisingCapabilities:
        return AdvertisingCapabilities(
            provider=self.provider,
            capability_status="mock_only",
            supports_structure_import=True,
            supports_insights=True,
            supports_conversions=True,
            supports_breakdowns=True,
            supported_metric_keys=_CORE_METRIC_KEYS,
            supported_breakdowns=_CORE_BREAKDOWNS,
            notes="Deterministic mock advertising data.",
        )

    async def health_check(self, *, connection_status: str) -> ProviderHealth:
        return ProviderHealth(
            provider=self.provider,
            status="ok",
            connection_status=connection_status,
            capability_status="mock_only",
            checked_at=utcnow(),
        )

    async def fetch_structure(self, request: StructureFetchRequest) -> StructureFetchResponse:
        return _mock_structure(request)

    async def fetch_insights(self, request: InsightsFetchRequest) -> InsightsFetchResponse:
        return _mock_insights(request)


class UnsupportedAdvertisingAdapter(AdvertisingProviderAdapter):
    """Fallback adapter for providers without a dedicated integration.

    Mock connections still receive deterministic mock data; any other
    connection status is reported as unsupported and never fabricates data.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def capabilities(self, *, connection_status: str) -> AdvertisingCapabilities:
        if connection_status == "mock":
            return AdvertisingCapabilities(
                provider=self.provider,
                capability_status="mock_only",
                supports_structure_import=True,
                supports_insights=True,
                supports_conversions=False,
                supports_breakdowns=False,
                supported_metric_keys=_CORE_METRIC_KEYS,
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
        status = "ok" if connection_status == "mock" else "unavailable"
        return ProviderHealth(
            provider=self.provider,
            status=status,
            connection_status=connection_status,
            capability_status=caps.capability_status,
            checked_at=utcnow(),
        )

    async def fetch_structure(self, request: StructureFetchRequest) -> StructureFetchResponse:
        if request.connection_status == "mock":
            return _mock_structure(request)
        return StructureFetchResponse(
            status="unsupported",
            provider_request_count=0,
            message=f"Structure import is not implemented for provider '{self.provider}'.",
        )

    async def fetch_insights(self, request: InsightsFetchRequest) -> InsightsFetchResponse:
        if request.connection_status == "mock":
            return _mock_insights(request)
        return InsightsFetchResponse(
            status="unsupported",
            provider_request_count=0,
            message=f"Insights are not implemented for provider '{self.provider}'.",
        )


# ---------------------------------------------------------------------------
# Deterministic mock payloads
# ---------------------------------------------------------------------------


def _mock_structure(request: StructureFetchRequest) -> StructureFetchResponse:
    # Delegate to the richer, deterministic mock in advertising_intelligence so
    # every code path (platform layer + intelligence import pipeline) yields the
    # same full campaign → ad group → ad → creative tree, not a single stub
    # campaign. Imported lazily to avoid an import cycle with the package init.
    from app.services.advertising_intelligence.providers.mock import build_structure

    return build_structure(request.provider_account_id)


def _mock_insights(request: InsightsFetchRequest) -> InsightsFetchResponse:
    from app.services.advertising_intelligence.providers.mock import build_insights

    return build_insights(request)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[AdvertisingProviderAdapter]] = {
    "meta": MetaAdvertisingAdapter,
    "mock": MockAdvertisingAdapter,
}

_instances: dict[str, AdvertisingProviderAdapter] = {}


def get_adapter(provider: str) -> AdvertisingProviderAdapter:
    """Return a cached read-only adapter instance for ``provider``.

    Unknown providers resolve to :class:`UnsupportedAdvertisingAdapter`. Never
    raises.
    """
    if provider in _instances:
        return _instances[provider]

    adapter_cls = _ADAPTERS.get(provider)
    adapter: AdvertisingProviderAdapter
    if adapter_cls is not None:
        adapter = adapter_cls()
    else:
        adapter = UnsupportedAdvertisingAdapter(provider)
    _instances[provider] = adapter
    return adapter


def registered_providers() -> frozenset[str]:
    return frozenset(_ADAPTERS.keys())


__all__ = [
    "get_adapter",
    "registered_providers",
    "MetaAdvertisingAdapter",
    "MockAdvertisingAdapter",
    "UnsupportedAdvertisingAdapter",
]
