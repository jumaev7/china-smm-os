"""WhatsApp Contact Center — AI reply drafts (heuristic mock, no auto-send)."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.whatsapp import WhatsAppMessage, WhatsAppThread
from app.services.whatsapp_contact_service import _utcnow

logger = logging.getLogger(__name__)

MARKER = "[WhatsApp Center]"


def _heuristic_draft(
    thread: WhatsAppThread,
    *,
    operator_notes: str | None = None,
) -> dict[str, Any]:
    contact = thread.contact
    name = contact.display_name if contact else "there"
    country = (contact.country or "").lower() if contact else ""
    last_inbound = next(
        (m.content for m in reversed(thread.messages or []) if m.direction == "incoming"),
        "",
    )
    has_chinese = any("\u4e00" <= c <= "\u9fff" for c in last_inbound)

    if "china" in country or has_chinese:
        content = f"您好 {name}，感谢您的消息。我们会尽快查看并回复您。请问方便提供更多产品规格或数量需求吗？"
        language = "zh"
    elif "uzbek" in country:
        content = f"Salom, {name}! Xabaringiz uchun rahmat. Tez orada javob beramiz. Mahsulot spetsifikatsiyasi yoki miqdorini yubora olasizmi?"
        language = "uz"
    elif "russia" in country:
        content = f"Здравствуйте, {name}! Спасибо за сообщение в WhatsApp. Мы изучим запрос и ответим в ближайшее время."
        language = "ru"
    else:
        content = (
            f"Hello {name}, thank you for your WhatsApp message. "
            "We will review and get back to you shortly. Please share product details or quantity if available."
        )
        language = "en"

    if operator_notes:
        content += f"\n\n(Operator note: {operator_notes.strip()[:200]})"

    return {
        "content": content,
        "language": language,
        "tone": "professional",
        "recommended_next_action": "Review thread context, copy draft, and paste manually in WhatsApp.",
        "demo_mode": True,
    }


class WhatsAppDraftService:
    @staticmethod
    async def create_draft(
        db: AsyncSession,
        *,
        thread_id: UUID,
        operator_notes: str | None = None,
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

        result = _heuristic_draft(thread, operator_notes=operator_notes)
        now = _utcnow()
        msg = WhatsAppMessage(
            thread_id=thread_id,
            direction="outgoing",
            content=result["content"],
            status="draft",
        )
        db.add(msg)
        thread.last_message_at = now
        await db.commit()
        await db.refresh(msg)

        logger.info("%s draft created: thread=%s message=%s", MARKER, thread_id, msg.id)
        return {
            "message_id": msg.id,
            "thread_id": thread_id,
            "content": result["content"],
            "language": result["language"],
            "tone": result["tone"],
            "recommended_next_action": result["recommended_next_action"],
            "demo_mode": result["demo_mode"],
        }
