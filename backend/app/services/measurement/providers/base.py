"""Provider adapter contract for the measurement pipeline.

Adapters are deliberately decoupled from ORM models: they receive plain
identifiers/status strings (never SQLAlchemy sessions or tokens) so that
provider integration code can never accidentally read or log credentials.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.services.measurement.schemas import (
    AdapterCapabilities,
    MetricFetchRequest,
    MetricFetchResponse,
    PublicationMetricResult,
)

# Account statuses (mirrors app.models.publishing_account.ACCOUNT_STATUSES)
# that should be treated as "cannot collect live metrics right now".
DISCONNECTED_ACCOUNT_STATUSES = frozenset({
    "disconnected", "expired", "invalid", "missing_permissions", "blocked",
})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MetricProviderAdapter(ABC):
    """Base class for all platform metric provider adapters."""

    platform: str

    @abstractmethod
    def capabilities(self, *, account_status: str) -> AdapterCapabilities:
        """Report what this adapter can do for the given account status."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_publication_metrics(self, request: MetricFetchRequest) -> MetricFetchResponse:
        """Fetch raw provider-native metrics for a batch of publications."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_account_publications(
        self,
        *,
        account_status: str,
        provider_account_id: str | None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List provider-side publications for backfill/discovery.

        Returns (publications, next_cursor). Each publication dict should
        contain at least ``provider_publication_id`` and ``published_at``.
        """
        raise NotImplementedError

    @abstractmethod
    async def health_check(self, *, account_status: str) -> dict[str, Any]:
        """Lightweight connectivity/capability check. Never raises."""
        raise NotImplementedError

    # -- shared helpers -----------------------------------------------------

    def _unsupported_result(
        self, provider_publication_id: str, *, message: str,
    ) -> PublicationMetricResult:
        return PublicationMetricResult(
            provider_publication_id=provider_publication_id,
            status="unsupported",
            provider_metrics={},
            provider_data_timestamp=None,
            raw_summary={},
            message=message,
        )

    def _unavailable_result(
        self, provider_publication_id: str, *, message: str,
    ) -> PublicationMetricResult:
        return PublicationMetricResult(
            provider_publication_id=provider_publication_id,
            status="unavailable",
            provider_metrics={},
            provider_data_timestamp=None,
            raw_summary={},
            message=message,
        )

    def is_disconnected(self, account_status: str) -> bool:
        return account_status in DISCONNECTED_ACCOUNT_STATUSES


class UnsupportedAdapter(MetricProviderAdapter):
    """Fallback adapter for platforms without a dedicated integration yet.

    For ``mock`` accounts it delegates fully to the mock adapter (so demo /
    QA tenants still see deterministic data). For any other account status it
    reports the capability as unsupported and never fabricates metrics.
    """

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def capabilities(self, *, account_status: str) -> AdapterCapabilities:
        if account_status == "mock":
            from app.services.measurement.metric_catalog import ALL_METRIC_KEYS
            return AdapterCapabilities(
                platform=self.platform,
                capability_status="mock_only",
                supports_post_level_metrics=True,
                supported_metric_keys=frozenset(ALL_METRIC_KEYS),
                notes=f"No live {self.platform} integration yet; mock account uses deterministic mock data.",
            )
        return AdapterCapabilities(
            platform=self.platform,
            capability_status="unsupported",
            supports_post_level_metrics=False,
            supported_metric_keys=frozenset(),
            unsupported_reason=f"No live metric integration is implemented for platform '{self.platform}' yet.",
        )

    async def fetch_publication_metrics(self, request: MetricFetchRequest) -> MetricFetchResponse:
        if request.account_status == "mock":
            from app.services.measurement.providers.mock import MockAdapter
            delegate = MockAdapter()
            delegate.platform = self.platform
            return await delegate.fetch_publication_metrics(request)
        results = {
            pub_id: self._unsupported_result(
                pub_id,
                message=f"Live metric collection is not implemented for platform '{self.platform}'.",
            )
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
        return [], None

    async def health_check(self, *, account_status: str) -> dict[str, Any]:
        if account_status == "mock":
            return {"status": "ok", "capability_status": "mock_only", "platform": self.platform}
        if self.is_disconnected(account_status):
            return {"status": "unavailable", "capability_status": "unsupported", "platform": self.platform}
        return {"status": "ok", "capability_status": "unsupported", "platform": self.platform}


__all__ = [
    "MetricProviderAdapter",
    "UnsupportedAdapter",
    "DISCONNECTED_ACCOUNT_STATUSES",
    "utcnow",
]
