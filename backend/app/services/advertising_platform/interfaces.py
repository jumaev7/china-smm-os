"""Read-only provider adapter contract for the advertising platform.

Adapters are deliberately decoupled from ORM models and from credentials: they
receive plain identifiers/status strings (never SQLAlchemy sessions or tokens)
so provider integration code can never read or log secrets.

READ-ONLY CONTRACT
------------------
``AdvertisingProviderAdapter`` exposes *only* read/observe methods. There are
deliberately NO methods to create, update, delete, pause, activate, resume,
archive, set budgets/bids, or otherwise mutate any provider-side object. Adding
such a method here is a contract violation; use ``capability_catalog`` to keep
the allowed surface auditable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.services.advertising_intelligence.schemas import (
    AdvertisingCapabilities,
    InsightsFetchRequest,
    InsightsFetchResponse,
    ProviderHealth,
    StructureFetchRequest,
    StructureFetchResponse,
)

# Connection statuses that mean "cannot collect live data right now".
DISCONNECTED_CONNECTION_STATUSES = frozenset({
    "disconnected", "expired", "revoked", "permission_blocked", "error",
})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AdvertisingProviderAdapter(ABC):
    """Base class for all read-only advertising provider adapters.

    Every method is a read/observe operation. No mutating methods exist by
    design (no create/update/delete/pause/activate/set_budget/set_bid/etc.).
    """

    provider: str

    # -- capability + health (read) ----------------------------------------

    @abstractmethod
    def capabilities(self, *, connection_status: str) -> AdvertisingCapabilities:
        """Report what this adapter can do for the given connection status."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self, *, connection_status: str) -> ProviderHealth:
        """Lightweight connectivity/permission check. Never raises."""
        raise NotImplementedError

    # -- structural import (read) ------------------------------------------

    @abstractmethod
    async def fetch_structure(self, request: StructureFetchRequest) -> StructureFetchResponse:
        """Read account + campaigns/ad groups/ads/creatives for one account.

        Purely a read: mirrors provider structure into DTOs. Never mutates.
        """
        raise NotImplementedError

    # -- insights / metrics (read) -----------------------------------------

    @abstractmethod
    async def fetch_insights(self, request: InsightsFetchRequest) -> InsightsFetchResponse:
        """Read provider-native insights (metrics + conversions) for entities.

        Read-only aggregation query; never creates or changes anything.
        """
        raise NotImplementedError

    # -- shared helpers -----------------------------------------------------

    def is_disconnected(self, connection_status: str) -> bool:
        return connection_status in DISCONNECTED_CONNECTION_STATUSES


__all__ = [
    "AdvertisingProviderAdapter",
    "DISCONNECTED_CONNECTION_STATUSES",
    "utcnow",
]
