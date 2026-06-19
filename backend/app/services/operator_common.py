"""Shared helpers for operator inbox and auto-draft services."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.services.telegram_group_agent_service import TG_GROUP_BUFFER_SOURCE

TG_INBOX_AUTO_DRAFT_SOURCE = "tg_inbox_auto_draft"

INBOX_NEW = "new"
INBOX_USED = "used"
INBOX_IGNORED = "ignored"
CLIENT_SENDER_ROLES = frozenset({"client"})

BUFFER_LINKED_CONTENT_SOURCES = (
    TG_GROUP_BUFFER_SOURCE,
    TG_INBOX_AUTO_DRAFT_SOURCE,
    "telegram_group",
)


def parse_schedule_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def effective_inbox_status(entry: TelegramGroupBufferMessage) -> str:
    if (entry.inbox_status or INBOX_NEW) == INBOX_IGNORED:
        return INBOX_IGNORED
    if entry.linked_content_id:
        return INBOX_USED
    return entry.inbox_status or INBOX_NEW


async def find_content_linked_to_buffer(
    db: AsyncSession,
    buffer_id: UUID,
    *,
    message_id: int | None = None,
) -> ContentItem | None:
    if message_id is not None:
        result = await db.execute(
            select(ContentItem)
            .where(
                ContentItem.source.in_(BUFFER_LINKED_CONTENT_SOURCES),
                ContentItem.telegram_buffer_refs.isnot(None),
            )
            .order_by(ContentItem.created_at.desc())
            .limit(200)
        )
        for item in result.scalars().all():
            if not item.telegram_buffer_refs:
                continue
            try:
                refs = json.loads(item.telegram_buffer_refs)
            except json.JSONDecodeError:
                continue
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if str(ref.get("buffer_id") or "") == str(buffer_id):
                    return item
                if message_id and int(ref.get("message_id") or 0) == int(message_id):
                    return item
    return None
