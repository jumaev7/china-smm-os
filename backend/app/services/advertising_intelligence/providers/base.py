"""Base re-exports for advertising intelligence provider adapters.

The canonical, read-only provider adapter contract lives in
``app.services.advertising_platform``. This module re-exports it so the rest of
the advertising *intelligence* domain has a single, stable import location and
never depends on the low-level platform package layout directly.

There are no write methods anywhere in this contract: adapters only ever read
account structure and insights.
"""
from __future__ import annotations

from app.services.advertising_platform.interfaces import (
    DISCONNECTED_CONNECTION_STATUSES,
    AdvertisingProviderAdapter,
    utcnow,
)
from app.services.advertising_intelligence.schemas import (
    AdvertisingCapabilities,
    EntityInsightResult,
    InsightsFetchRequest,
    InsightsFetchResponse,
    ProviderAccount,
    ProviderAd,
    ProviderAdGroup,
    ProviderCampaign,
    ProviderConversion,
    ProviderCreative,
    ProviderHealth,
    ProviderMetric,
    StructureFetchRequest,
    StructureFetchResponse,
)

__all__ = [
    "AdvertisingProviderAdapter",
    "DISCONNECTED_CONNECTION_STATUSES",
    "utcnow",
    "AdvertisingCapabilities",
    "ProviderHealth",
    "ProviderAccount",
    "ProviderCampaign",
    "ProviderAdGroup",
    "ProviderAd",
    "ProviderCreative",
    "ProviderMetric",
    "ProviderConversion",
    "EntityInsightResult",
    "StructureFetchRequest",
    "StructureFetchResponse",
    "InsightsFetchRequest",
    "InsightsFetchResponse",
]
