"""Listening source adapter registry.

Only ``manual_import`` and ``fixture`` are wired in Phase 1. Unknown source
types resolve to an unsupported adapter that never fabricates live data and
never exposes mutation methods.
"""
from __future__ import annotations

from typing import Any

from app.services.listening.providers.base import ListeningSourceAdapter
from app.services.listening.providers.fixture import FixtureAdapter
from app.services.listening.providers.manual_import import ManualImportAdapter
from app.services.listening.schemas import ObservationPage, SourceCapabilities

_ADAPTERS: dict[str, ListeningSourceAdapter] = {
    "manual_import": ManualImportAdapter(),
    "fixture": FixtureAdapter(),
}


class UnsupportedListeningAdapter(ListeningSourceAdapter):
    def __init__(self, source_type: str) -> None:
        self.source_type = source_type

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            source_type=self.source_type,
            capability_status="unsupported",
            unsupported_reason=(
                f"No live social listening integration is implemented for "
                f"source '{self.source_type}' in Phase 1."
            ),
            notes="Phase 1 supports manual_import and fixture only.",
        )

    async def validate_configuration(self, config: dict[str, Any] | None) -> list[str]:
        return [f"source_type '{self.source_type}' is unsupported"]

    async def fetch_observations(
        self,
        *,
        config: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 50,
        items: list[dict[str, Any]] | None = None,
    ) -> ObservationPage:
        return ObservationPage(
            items=[],
            fetched_count=0,
            rejected_count=0,
            error_summary=f"Unsupported source type '{self.source_type}'",
        )


def get_adapter(source_type: str) -> ListeningSourceAdapter:
    return _ADAPTERS.get(source_type, UnsupportedListeningAdapter(source_type))


def list_source_capabilities() -> list[SourceCapabilities]:
    caps = [adapter.capabilities() for adapter in _ADAPTERS.values()]
    caps.append(
        SourceCapabilities(
            source_type="live_provider",
            capability_status="unsupported",
            unsupported_reason=(
                "No live keyword/market listening provider is connected. "
                "Coverage is limited to configured supported sources only."
            ),
            notes="Deferred to a later phase.",
        )
    )
    return caps


__all__ = [
    "get_adapter",
    "list_source_capabilities",
    "UnsupportedListeningAdapter",
]
