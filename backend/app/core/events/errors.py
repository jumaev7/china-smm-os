"""Event bus error types."""
from __future__ import annotations


class EventBusError(Exception):
    """Base error for the platform event bus."""


class UnknownEventTypeError(EventBusError):
    """Raised when publishing an unregistered event type."""

    def __init__(self, event_type: str) -> None:
        super().__init__(f"Unknown event type: {event_type}")
        self.event_type = event_type


class TenantIsolationError(EventBusError):
    """Raised when tenant context is missing or mismatched."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class SubscriberError(EventBusError):
    """Raised when a subscriber fails during dispatch."""

    def __init__(self, subscriber_name: str, cause: Exception) -> None:
        super().__init__(f"Subscriber {subscriber_name!r} failed: {cause}")
        self.subscriber_name = subscriber_name
        self.cause = cause
