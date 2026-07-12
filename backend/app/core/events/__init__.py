"""Application-level event bus — synchronous, tenant-isolated, in-process."""
from app.core.events.bus import EventBus, event_bus
from app.core.events.context import build_event_from_auth, build_tenant_event
from app.core.events.errors import (
    EventBusError,
    SubscriberError,
    TenantIsolationError,
    UnknownEventTypeError,
)
from app.core.events.interfaces import EventSubscriber
from app.core.events.registry import EventRegistry, event_registry
from app.core.events.types import (
    EventDefinition,
    EventIntegrations,
    PlatformEvent,
    PublishResult,
    SubscriberResult,
)

__all__ = [
    "EventBus",
    "EventBusError",
    "EventDefinition",
    "EventIntegrations",
    "EventRegistry",
    "EventSubscriber",
    "PlatformEvent",
    "PublishResult",
    "SubscriberResult",
    "SubscriberError",
    "TenantIsolationError",
    "UnknownEventTypeError",
    "build_event_from_auth",
    "build_tenant_event",
    "event_bus",
    "event_registry",
]
