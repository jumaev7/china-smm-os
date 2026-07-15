"""Registry of Marketing Intelligence signal collectors."""
from __future__ import annotations

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.automation import AutomationCollector
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.collectors.content import ContentCollector
from app.services.intelligence.collectors.crm import CrmCollector
from app.services.intelligence.collectors.customer_success import CustomerSuccessCollector
from app.services.intelligence.collectors.integration import IntegrationCollector
from app.services.intelligence.collectors.notification import NotificationCollector
from app.services.intelligence.collectors.publishing import PublishingCollector
from app.services.intelligence.collectors.workflow import WorkflowCollector
from app.services.intelligence.types import NormalizedSignal


def default_collectors() -> list[SignalCollector]:
    return [
        PublishingCollector(),
        CrmCollector(),
        WorkflowCollector(),
        AutomationCollector(),
        NotificationCollector(),
        CustomerSuccessCollector(),
        IntegrationCollector(),
        ContentCollector(),
    ]


def collect_signals(event: PlatformEvent, collectors: list[SignalCollector] | None = None) -> list[NormalizedSignal]:
    """Run all matching collectors and return normalized signals."""
    signals: list[NormalizedSignal] = []
    for collector in collectors or default_collectors():
        if collector.supports(event):
            signals.extend(collector.collect(event))
    return signals
