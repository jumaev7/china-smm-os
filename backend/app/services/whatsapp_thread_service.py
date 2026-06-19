"""WhatsApp Contact Center — threads and messages (mock data v1)."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage, WhatsAppThread
from app.services.whatsapp_contact_service import _ensure_mock_data, _preview

logger = logging.getLogger(__name__)

MARKER = "[WhatsApp Center]"


def _serialize_message(msg: WhatsAppMessage) -> dict[str, Any]:
    return {
        "id": msg.id,
        "thread_id": msg.thread_id,
        "direction": msg.direction,
        "content": msg.content,
        "status": msg.status,
        "created_at": msg.created_at,
    }


def _serialize_thread(
    thread: WhatsAppThread,
    *,
    contact: WhatsAppContact | None = None,
    last_message_preview: str | None = None,
) -> dict[str, Any]:
    return {
        "id": thread.id,
        "contact_id": thread.contact_id,
        "contact_name": contact.display_name if contact else None,
        "contact_phone": contact.phone if contact else None,
        "company": contact.company if contact else None,
        "country": contact.country if contact else None,
        "crm_client_id": contact.crm_client_id if contact else None,
        "last_message_at": thread.last_message_at,
        "unread_count": thread.unread_count or 0,
        "last_message_preview": last_message_preview,
        "created_at": thread.created_at,
    }


class WhatsAppThreadService:
    @staticmethod
    async def list_threads(
        db: AsyncSession,
        *,
        contact_id: UUID | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        await _ensure_mock_data(db)
        limit = clamp_limit(limit)

        q = select(WhatsAppThread).options(selectinload(WhatsAppThread.contact))
        count_q = select(func.count()).select_from(WhatsAppThread)

        if contact_id:
            q = q.where(WhatsAppThread.contact_id == contact_id)
            count_q = count_q.where(WhatsAppThread.contact_id == contact_id)

        total = (await db.execute(count_q)).scalar_one()
        threads = list(
            (await db.execute(
                q.order_by(
                    WhatsAppThread.last_message_at.desc().nullslast(),
                    WhatsAppThread.created_at.desc(),
                ).offset(skip).limit(limit)
            )).scalars().unique().all()
        )

        thread_ids = [t.id for t in threads]
        last_previews: dict[UUID, str | None] = {}
        if thread_ids:
            lr = await db.execute(
                select(
                    WhatsAppMessage.thread_id,
                    func.max(WhatsAppMessage.created_at),
                )
                .where(WhatsAppMessage.thread_id.in_(thread_ids))
                .group_by(WhatsAppMessage.thread_id)
            )
            latest_at = {row[0]: row[1] for row in lr.all()}
            if latest_at:
                mr = await db.execute(
                    select(WhatsAppMessage).where(
                        WhatsAppMessage.thread_id.in_(thread_ids),
                    )
                )
                for msg in mr.scalars().all():
                    if latest_at.get(msg.thread_id) == msg.created_at:
                        last_previews[msg.thread_id] = _preview(msg.content)

        items = [
            _serialize_thread(
                t,
                contact=t.contact,
                last_message_preview=last_previews.get(t.id),
            )
            for t in threads
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def list_messages(
        db: AsyncSession,
        thread_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        await _ensure_mock_data(db)
        limit = clamp_limit(limit)

        tr = await db.execute(select(WhatsAppThread).where(WhatsAppThread.id == thread_id))
        if not tr.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Thread not found")

        count_q = select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.thread_id == thread_id
        )
        total = (await db.execute(count_q)).scalar_one()

        mr = await db.execute(
            select(WhatsAppMessage)
            .where(WhatsAppMessage.thread_id == thread_id)
            .order_by(WhatsAppMessage.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        messages = list(mr.scalars().all())
        return {"items": [_serialize_message(m) for m in messages], "total": total}

    @staticmethod
    async def get_thread_with_messages(
        db: AsyncSession,
        thread_id: UUID,
    ) -> dict[str, Any]:
        r = await db.execute(
            select(WhatsAppThread)
            .options(
                selectinload(WhatsAppThread.contact),
                selectinload(WhatsAppThread.messages),
            )
            .where(WhatsAppThread.id == thread_id)
        )
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        messages = [_serialize_message(m) for m in (thread.messages or [])]
        last_preview = _preview(messages[-1]["content"]) if messages else None
        return {
            **_serialize_thread(thread, contact=thread.contact, last_message_preview=last_preview),
            "messages": messages,
        }
