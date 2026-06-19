"""Publishing calendar — scheduled, published, and failed posts for admin calendar view."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.content import ContentItem

CALENDAR_STATUSES = frozenset({
    "scheduled",
    "publishing",
    "published",
    "failed",
    "partial_failed",
})


def _pick_title(item: ContentItem) -> str:
    for field in (
        "caption_short_ru",
        "caption_short_en",
        "caption_short_uz",
        "caption_long_ru",
        "caption_long_en",
        "caption_long_uz",
    ):
        value = getattr(item, field, None)
        if value and str(value).strip():
            text = str(value).strip()
            return text[:80] + ("…" if len(text) > 80 else "")
    return "Post"


def _event_at_expr():
    return case(
        (
            ContentItem.status.in_(("published", "failed", "partial_failed", "publishing")),
            func.coalesce(ContentItem.published_at, ContentItem.scheduled_for),
        ),
        else_=ContentItem.scheduled_for,
    )


class PublishingCalendarService:
    @staticmethod
    def _parse_range(from_date: date, to_date: date) -> tuple[datetime, datetime]:
        start = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
        end = datetime.combine(to_date, time.max.replace(microsecond=0), tzinfo=timezone.utc)
        return start, end

    @staticmethod
    async def list_calendar(
        db: AsyncSession,
        *,
        from_date: date,
        to_date: date,
        client_id: UUID | None = None,
        platform: str | None = None,
        status: str | None = None,
    ) -> dict:
        range_start, range_end = PublishingCalendarService._parse_range(from_date, to_date)
        event_at = _event_at_expr()

        statuses = CALENDAR_STATUSES
        if status:
            requested = {s.strip() for s in status.split(",") if s.strip()}
            statuses = requested & CALENDAR_STATUSES
            if not statuses:
                return {"items": [], "total": 0, "from_date": from_date, "to_date": to_date}

        query = (
            select(ContentItem)
            .join(Client, ContentItem.client_id == Client.id)
            .where(
                ContentItem.status.in_(tuple(statuses)),
                event_at.isnot(None),
                event_at >= range_start,
                event_at <= range_end,
            )
            .options(selectinload(ContentItem.client))
            .order_by(event_at.asc())
        )

        if client_id:
            query = query.where(ContentItem.client_id == client_id)
        if platform:
            query = query.where(ContentItem.platforms.contains([platform]))

        result = await db.execute(query)
        items = list(result.scalars().all())

        serialized = [
            PublishingCalendarService._serialize_item(item) for item in items
        ]
        return {
            "items": serialized,
            "total": len(serialized),
            "from_date": from_date,
            "to_date": to_date,
        }

    @staticmethod
    def _serialize_item(item: ContentItem) -> dict:
        client: Client | None = item.client
        return {
            "id": item.id,
            "title": _pick_title(item),
            "client_id": item.client_id,
            "company_name": client.company_name if client else "Unknown",
            "status": item.status,
            "scheduled_for": item.scheduled_for,
            "published_at": item.published_at,
            "platforms": list(item.platforms or []),
        }
