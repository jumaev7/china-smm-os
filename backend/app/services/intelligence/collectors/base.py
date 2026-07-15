"""Signal collector base class."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.events.types import PlatformEvent
from app.services.intelligence.types import NormalizedSignal


class SignalCollector(ABC):
    """Convert a platform event into zero or more normalized marketing signals."""

    name: str
    source: str
    event_types: frozenset[str]

    def supports(self, event: PlatformEvent) -> bool:
        return event.event_type in self.event_types

    @abstractmethod
    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        raise NotImplementedError
