"""Platform event types and publish results."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EventIntegrations:
    """Which downstream integrations should process an event type."""

    audit: bool = False
    activity: bool = True
    notification: bool = False
    customer_success: bool = False
    automation: bool = False


@dataclass(frozen=True)
class EventDefinition:
    """Registered platform event type with integration metadata."""

    event_type: str
    category: str
    description: str
    integrations: EventIntegrations = field(default_factory=EventIntegrations)
    tenant_scoped: bool = True


@dataclass
class PlatformEvent:
    """Tenant-scoped domain event dispatched synchronously through the bus."""

    event_type: str
    tenant_id: UUID | None
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)
    actor_type: str | None = None
    actor_id: UUID | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    title: str | None = None
    description: str | None = None
    occurred_at: datetime = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def require_tenant_id(self) -> UUID:
        if self.tenant_id is None:
            raise ValueError(f"Event {self.event_type!r} requires tenant_id")
        return self.tenant_id


@dataclass
class SubscriberResult:
    """Outcome of a single subscriber invocation."""

    subscriber: str
    handled: bool
    detail: str | None = None


@dataclass
class PublishResult:
    """Aggregate outcome of a synchronous publish/dispatch cycle."""

    event: PlatformEvent
    subscriber_results: list[SubscriberResult] = field(default_factory=list)

    @property
    def handled_count(self) -> int:
        return sum(1 for r in self.subscriber_results if r.handled)
