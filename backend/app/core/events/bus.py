"""Synchronous in-process event dispatcher with tenant isolation."""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.errors import SubscriberError, TenantIsolationError, UnknownEventTypeError
from app.core.events.interfaces import EventSubscriber
from app.core.events.registry import EventRegistry, event_registry
from app.core.events.types import PlatformEvent, PublishResult, SubscriberResult

logger = logging.getLogger(__name__)


@dataclass(order=True)
class _Subscription:
    priority: int
    pattern: str
    subscriber: EventSubscriber = field(compare=False)

    def matches(self, event_type: str) -> bool:
        if self.pattern == "*":
            return True
        return fnmatch.fnmatch(event_type, self.pattern)


class EventBus:
    """Lightweight synchronous dispatcher — no external brokers."""

    def __init__(self, registry: EventRegistry | None = None) -> None:
        self._registry = registry or event_registry
        self._subscriptions: list[_Subscription] = []
        self._frozen = False

    @property
    def registry(self) -> EventRegistry:
        return self._registry

    def subscribe(
        self,
        subscriber: EventSubscriber,
        *,
        event_types: str | list[str] | None = None,
        priority: int = 100,
    ) -> None:
        if self._frozen:
            raise RuntimeError("Cannot subscribe after event bus registration is frozen")
        patterns: list[str]
        if event_types is None:
            patterns = ["*"]
        elif isinstance(event_types, str):
            patterns = [event_types]
        else:
            patterns = list(event_types)
        for pattern in patterns:
            self._subscriptions.append(
                _Subscription(priority=priority, pattern=pattern, subscriber=subscriber),
            )
        self._subscriptions.sort()

    def freeze(self) -> None:
        """Lock subscriber list — called once at application startup."""
        self._frozen = True

    def clear_subscribers(self) -> None:
        """Test helper — reset subscriber registry."""
        self._subscriptions.clear()
        self._frozen = False

    def _validate_event(self, event: PlatformEvent) -> None:
        definition = self._registry.get(event.event_type)
        if definition is None:
            raise UnknownEventTypeError(event.event_type)
        if definition.tenant_scoped and event.tenant_id is None:
            raise TenantIsolationError(
                f"Event {event.event_type!r} is tenant-scoped but tenant_id is missing",
            )

    def _matching_subscribers(self, event_type: str) -> list[EventSubscriber]:
        seen: set[str] = set()
        matched: list[EventSubscriber] = []
        for sub in self._subscriptions:
            if not sub.matches(event_type):
                continue
            name = sub.subscriber.name
            if name in seen:
                continue
            seen.add(name)
            matched.append(sub.subscriber)
        return matched

    async def publish(
        self,
        db: AsyncSession,
        event: PlatformEvent,
        *,
        require_registered: bool = True,
        stop_on_error: bool = False,
    ) -> PublishResult:
        """Dispatch event to subscribers synchronously within the caller's session."""
        if require_registered:
            self._validate_event(event)
        elif event.tenant_id is None:
            definition = self._registry.get(event.event_type)
            if definition is not None and definition.tenant_scoped:
                raise TenantIsolationError(
                    f"Event {event.event_type!r} is tenant-scoped but tenant_id is missing",
                )

        result = PublishResult(event=event)
        subscribers = self._matching_subscribers(event.event_type)
        for subscriber in subscribers:
            try:
                sub_result = await subscriber.handle(db, event)
                result.subscriber_results.append(sub_result)
            except Exception as exc:
                logger.exception(
                    "[EventBus] subscriber %s failed for %s",
                    subscriber.name,
                    event.event_type,
                )
                result.subscriber_results.append(
                    SubscriberResult(
                        subscriber=subscriber.name,
                        handled=False,
                        detail=str(exc),
                    ),
                )
                if stop_on_error:
                    raise SubscriberError(subscriber.name, exc) from exc
        return result


# Process-wide singleton bus.
event_bus = EventBus()
