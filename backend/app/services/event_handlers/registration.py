"""Register default event bus subscribers at application startup."""
from __future__ import annotations

import logging

from app.core.events.bus import EventBus, event_bus
from app.services.event_handlers.activity_handler import ActivityEventHandler
from app.services.event_handlers.audit_handler import AuditEventHandler
from app.services.event_handlers.automation_handler import AutomationEventHandler
from app.services.event_handlers.customer_success_handler import CustomerSuccessEventHandler
from app.services.event_handlers.notification_handler import NotificationEventHandler
from app.services.intelligence.handler import IntelligenceEventHandler

logger = logging.getLogger(__name__)

_REGISTERED = False


def register_event_bus_subscribers(bus: EventBus | None = None) -> EventBus:
    """Idempotent registration of platform integration handlers."""
    global _REGISTERED
    target = bus or event_bus
    if _REGISTERED and bus is None:
        return target

    handlers = [
        AuditEventHandler(),
        ActivityEventHandler(),
        NotificationEventHandler(),
        CustomerSuccessEventHandler(),
        AutomationEventHandler(),
        IntelligenceEventHandler(),
    ]
    for handler in handlers:
        target.subscribe(handler, event_types="*", priority=100)

    target.freeze()
    if bus is None:
        _REGISTERED = True
    logger.info("[EventBus] registered %d subscribers", len(handlers))
    return target


def reset_event_bus_registration() -> None:
    """Test helper — allow re-registration in isolated tests."""
    global _REGISTERED
    _REGISTERED = False
    event_bus.clear_subscribers()
