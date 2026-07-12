"""Event bus subscriber contracts."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent, SubscriberResult


@runtime_checkable
class EventSubscriber(Protocol):
    """Synchronous (async) handler invoked by the event dispatcher."""

    name: str

    async def handle(
        self,
        db: AsyncSession,
        event: PlatformEvent,
    ) -> SubscriberResult: ...
