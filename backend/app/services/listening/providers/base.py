"""Read-only source adapter contract for Social Listening Phase 1.

Adapters may only fetch/observe. They must not expose publish, reply, DM,
like, follow, block, report, or any provider mutation methods.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.listening.schemas import ObservationPage, SourceCapabilities


class ListeningSourceAdapter(ABC):
    """Base class for listening source adapters."""

    source_type: str

    @abstractmethod
    def capabilities(self) -> SourceCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def validate_configuration(self, config: dict[str, Any] | None) -> list[str]:
        """Return a list of validation error messages (empty if OK)."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_observations(
        self,
        *,
        config: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 50,
        items: list[dict[str, Any]] | None = None,
    ) -> ObservationPage:
        """Fetch a page of raw observations. Never mutates provider state."""
        raise NotImplementedError

    async def health_check(self, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
        caps = self.capabilities()
        return {
            "source_type": self.source_type,
            "status": "ok" if caps.capability_status != "unsupported" else "unavailable",
            "capability_status": caps.capability_status,
            "notes": caps.notes,
        }


__all__ = ["ListeningSourceAdapter"]
