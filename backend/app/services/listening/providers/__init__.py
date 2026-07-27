"""Listening source adapter registry.

Phase 1: manual_import, fixture.
Phase 3: facebook_page_comments, facebook_page_mentions (governed Meta read-only).

Unknown source types resolve to an unsupported adapter that never fabricates
live data and never exposes mutation methods.
"""
from __future__ import annotations

from typing import Any

from app.services.listening.providers.base import ListeningSourceAdapter
from app.services.listening.providers.facebook_page_comments import FacebookPageCommentsAdapter
from app.services.listening.providers.facebook_page_mentions import FacebookPageMentionsAdapter
from app.services.listening.providers.fixture import FixtureAdapter
from app.services.listening.providers.manual_import import ManualImportAdapter
from app.services.listening.schemas import ObservationPage, SourceCapabilities

LIVE_SOURCE_TYPES = frozenset({
    "facebook_page_comments",
    "facebook_page_mentions",
})

_ADAPTERS: dict[str, ListeningSourceAdapter] = {
    "manual_import": ManualImportAdapter(),
    "fixture": FixtureAdapter(),
    "facebook_page_comments": FacebookPageCommentsAdapter(),
    "facebook_page_mentions": FacebookPageMentionsAdapter(),
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
                f"source '{self.source_type}'."
            ),
            notes=(
                "Supported live sources: facebook_page_comments, facebook_page_mentions. "
                "Also: manual_import, fixture."
            ),
            observation_origin="manual_import",
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
    # Explicit catalog entries for commonly assumed-but-unsupported providers.
    for deferred_type, reason in (
        (
            "instagram_media_comments",
            "Instagram comment read requires instagram_manage_comments "
            "(not in current OAuth scopes; permission also allows write actions).",
        ),
        (
            "keyword_search",
            "No authorized global keyword / Public Content Access feature is configured.",
        ),
    ):
        caps.append(
            SourceCapabilities(
                source_type=deferred_type,
                capability_status="unsupported",
                unsupported_reason=reason,
                notes="Deferred — capability recorded for honesty, not invented.",
                observation_origin="live_provider",
            )
        )
    return caps


def is_live_source_type(source_type: str) -> bool:
    return source_type in LIVE_SOURCE_TYPES


__all__ = [
    "LIVE_SOURCE_TYPES",
    "get_adapter",
    "list_source_capabilities",
    "is_live_source_type",
    "UnsupportedListeningAdapter",
]
