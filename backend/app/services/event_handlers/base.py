"""Shared helpers for event bus integration handlers."""
from __future__ import annotations

from app.core.events.registry import EventRegistry, event_registry
from app.core.events.types import EventDefinition, PlatformEvent, SubscriberResult


class IntegrationHandler:
    """Base class for registry-aware subscribers."""

    name: str
    integration_key: str  # audit | activity | notification | customer_success | automation

    def __init__(self, registry: EventRegistry | None = None) -> None:
        self._registry = registry or event_registry

    def _definition(self, event: PlatformEvent) -> EventDefinition | None:
        return self._registry.get(event.event_type)

    def _is_enabled(self, event: PlatformEvent) -> bool:
        definition = self._definition(event)
        if definition is None:
            return False
        return bool(getattr(definition.integrations, self.integration_key, False))

    def _skip(self, reason: str) -> SubscriberResult:
        return SubscriberResult(subscriber=self.name, handled=False, detail=reason)

    def _handled(self, detail: str | None = None) -> SubscriberResult:
        return SubscriberResult(subscriber=self.name, handled=True, detail=detail)
