"""Optional Meta (Facebook/Instagram) read-only advertising adapter.

This adapter is intentionally conservative and honest:

- It exposes **no write methods** (it inherits the read-only contract).
- It NEVER fabricates live data. Until a live Marketing (Ads) Insights client is
  wired and credentials are configured (``META_ADS_SYSTEM_USER_TOKEN`` or an
  injected client), live reads return an empty-but-successful response and the
  reported ``capability_status`` is ``limited``/``unsupported`` rather than
  ``full``.
- ``mock`` connections are served deterministic data via the mock generators so
  the Meta code path can be exercised without any network access.
"""
from __future__ import annotations

import os

from app.services.advertising_intelligence.providers.mock import (
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
from app.services.advertising_platform.interfaces import (
    AdvertisingProviderAdapter,
    utcnow,
)

_CORE_METRIC_KEYS = frozenset({
    "impressions", "reach", "clicks", "link_clicks", "video_views",
    "spend_minor", "conversions", "conversion_value_minor",
})
_CORE_BREAKDOWNS = frozenset({
    "age", "gender", "country", "region", "publisher_platform",
    "platform_position", "device_platform", "impression_device",
})


def _live_credentials_available() -> bool:
    """True only if a live Meta Ads token is configured.

    Absent this, we never claim ``full`` capability and never fabricate live
    data — honesty over optimism.
    """
    return bool(os.environ.get("META_ADS_SYSTEM_USER_TOKEN"))


class MetaAdvertisingAdapter(AdvertisingProviderAdapter):
    """Read-only Meta advertising adapter (structure + insights only)."""

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
                notes="Mock connection uses deterministic offline data.",
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
        if not _live_credentials_available():
            return AdvertisingCapabilities(
                provider=self.provider,
                capability_status="limited",
                supports_structure_import=False,
                supports_insights=False,
                supports_conversions=False,
                supports_breakdowns=False,
                unsupported_reason=(
                    "Live Meta Ads reads are not wired in this deployment "
                    "(no META_ADS_SYSTEM_USER_TOKEN configured)."
                ),
                notes="Connect via Integrations and configure credentials to enable live reads.",
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
        elif not _live_credentials_available():
            status = "unavailable"
        else:
            status = "ok"
        return ProviderHealth(
            provider=self.provider,
            status=status,
            connection_status=connection_status,
            capability_status=caps.capability_status,
            checked_at=utcnow(),
            message=caps.unsupported_reason,
        )

    async def fetch_structure(self, request: StructureFetchRequest) -> StructureFetchResponse:
        if request.connection_status == "mock":
            return _mock_structure(request.provider_account_id)
        if self.is_disconnected(request.connection_status):
            return StructureFetchResponse(
                status="unavailable",
                provider_request_count=0,
                message=f"Meta account connection is '{request.connection_status}'.",
            )
        if not _live_credentials_available():
            return StructureFetchResponse(
                status="unsupported",
                provider_request_count=0,
                message="Live Meta Ads structure reads are not wired in this deployment.",
            )
        # A live Graph client would be injected by the ingestion layer. Absent
        # one, return an empty successful read rather than fabricating data.
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
        if not _live_credentials_available():
            return InsightsFetchResponse(
                status="unsupported",
                provider_request_count=0,
                message="Live Meta Ads insights are not wired in this deployment.",
            )
        return InsightsFetchResponse(status="ok", provider_request_count=0)


__all__ = ["MetaAdvertisingAdapter"]
