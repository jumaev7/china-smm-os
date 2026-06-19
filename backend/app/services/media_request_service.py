"""Media Request Assistant — ask clients for materials via Telegram intake group."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.content_plan import ContentPlanItem
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.services.ai_service import _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_review_telegram_service import send_telegram_message
from app.services.content_service import ContentService
from app.services.operator_common import CLIENT_SENDER_ROLES, INBOX_USED

logger = logging.getLogger(__name__)

TELEGRAM_INTAKE_NOT_LINKED = "Client Telegram intake group not linked"

MEDIA_REQUEST_FORMATS = frozenset({"photo", "video", "carousel", "story", "any"})
MEDIA_REQUEST_STATUSES = frozenset({"requested", "fulfilled", "skipped"})

PLAN_TYPE_TO_FORMAT = {
    "image": "photo",
    "video": "video",
    "carousel": "carousel",
    "story": "story",
}

_FORMAT_LABELS = {
    "photo": "photo",
    "video": "video",
    "carousel": "carousel (multiple photos)",
    "story": "story format (vertical photo or video)",
    "any": "photo or video",
}

_LANG_NAMES = {
    "zh": "Chinese (Simplified)",
    "en": "English",
    "ru": "Russian",
    "uz": "Uzbek",
    "ko": "Korean",
    "ja": "Japanese",
}

_MEDIA_REQUEST_SYSTEM = """\
You write polite, professional Telegram messages to clients asking them to send media \
materials for an upcoming social media post.

Rules:
- Write in the requested language (natural, warm, not robotic)
- Mention the post theme/context briefly
- Clearly state what type of media is needed
- Ask them to send files in this Telegram group
- Keep the message concise (2-5 short paragraphs max)
- Do NOT mention publishing automation or approval workflows
- Return ONLY the message text — no JSON, no markdown fences
"""


def _primary_caption(item: ContentItem) -> str:
    for short_attr, long_attr in (
        ("caption_short_ru", "caption_long_ru"),
        ("caption_short_uz", "caption_long_uz"),
        ("caption_short_en", "caption_long_en"),
    ):
        body = (getattr(item, long_attr) or getattr(item, short_attr) or "").strip()
        if body:
            return body[:500]
    return ""


def _heuristic_media_request_message(
    *,
    client: Client,
    required_format: str,
    theme: str | None,
    goal: str | None,
    caption: str,
) -> str:
    lang = (client.source_language or "ru").lower()
    fmt = _FORMAT_LABELS.get(required_format, required_format)
    company = client.brand_name or client.company_name
    theme_line = theme or caption[:120] or "upcoming post"

    if lang == "zh":
        return (
            f"您好！我们正在为 {company} 准备一条社交媒体内容，需要您提供{fmt}素材。\n\n"
            f"主题：{theme_line}\n"
            + (f"目标：{goal}\n\n" if goal else "\n")
            + "请将文件直接发送到此群组，谢谢您的配合！🙏"
        )
    if lang == "uz":
        return (
            f"Assalomu alaykum! {company} uchun ijtimoiy tarmoq posti tayyorlayapmiz — "
            f"bizga {fmt} kerak.\n\n"
            f"Mavzu: {theme_line}\n"
            + (f"Maqsad: {goal}\n\n" if goal else "\n")
            + "Iltimos, fayllarni shu guruhga yuboring. Rahmat! 🙏"
        )
    if lang == "en":
        return (
            f"Hello! We're preparing a social media post for {company} and need {fmt}.\n\n"
            f"Theme: {theme_line}\n"
            + (f"Goal: {goal}\n\n" if goal else "\n")
            + "Please send the files to this group. Thank you! 🙏"
        )
    return (
        f"Здравствуйте! Готовим публикацию для {company} — нужен материал: {fmt}.\n\n"
        f"Тема: {theme_line}\n"
        + (f"Цель: {goal}\n\n" if goal else "\n")
        + "Пожалуйста, отправьте файлы в эту группу. Спасибо! 🙏"
    )


async def _get_plan_item_for_content(
    db: AsyncSession,
    content_id: UUID,
) -> ContentPlanItem | None:
    result = await db.execute(
        select(ContentPlanItem)
        .options(selectinload(ContentPlanItem.plan))
        .where(ContentPlanItem.linked_content_id == content_id)
    )
    return result.scalar_one_or_none()


async def _resolve_required_format(
    db: AsyncSession,
    content: ContentItem,
    requested: str,
) -> str:
    if requested and requested != "any":
        return requested
    plan_item = await _get_plan_item_for_content(db, content.id)
    if plan_item:
        return PLAN_TYPE_TO_FORMAT.get(plan_item.content_type, "any")
    return "any"


def _media_matches_format(
    message_type: str,
    required_format: str,
) -> bool:
    if required_format == "any":
        return message_type in ("photo", "video", "document")
    if required_format == "photo":
        return message_type == "photo"
    if required_format == "video":
        return message_type == "video"
    if required_format in ("carousel", "story"):
        return message_type in ("photo", "video")
    return True


async def _generate_media_request_message(
    *,
    db: AsyncSession,
    client: Client,
    content: ContentItem,
    required_format: str,
    theme: str | None,
    goal: str | None,
) -> str:
    caption = _primary_caption(content)
    notes = (content.internal_notes or "").strip()
    lang = client.source_language or "ru"
    brand = brand_profile_from_client(client)

    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        msg = _heuristic_media_request_message(
            client=client,
            required_format=required_format,
            theme=theme,
            goal=goal,
            caption=caption,
        )
        logger.info("[Media Request] generated: content=%s source=fallback", content.id)
        return msg

    _validate_api_key()
    lang_display = _LANG_NAMES.get(lang, lang)
    fmt_label = _FORMAT_LABELS.get(required_format, required_format)

    user_prompt = f"""Write a Telegram message in {lang_display}.

Client: {client.company_name}
Required media: {fmt_label}
Theme: {theme or "(see caption)"}
Goal: {goal or "(not specified)"}
Caption context: {caption or "(none yet)"}
Internal notes: {notes[:400] if notes else "(none)"}
Brand tone: {brand.get("tone_of_voice") or client.content_style}
"""
    from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, context="media_request",
    )
    if kb_block:
        user_prompt = f"{user_prompt}\n\n{kb_block}"

    try:
        openai = get_openai()
        response = await openai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _MEDIA_REQUEST_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.65,
            max_tokens=600,
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise RuntimeError("Empty AI response")
        logger.info("[Media Request] generated: content=%s source=ai", content.id)
        return text
    except Exception as exc:
        logger.warning("[Media Request] AI fallback: content=%s error=%s", content.id, exc)
        return _heuristic_media_request_message(
            client=client,
            required_format=required_format,
            theme=theme,
            goal=goal,
            caption=caption,
        )


class MediaRequestService:
    @staticmethod
    async def request_media(
        db: AsyncSession,
        content_id: UUID,
        *,
        required_format: str = "any",
    ) -> dict[str, Any]:
        if required_format not in MEDIA_REQUEST_FORMATS:
            raise HTTPException(status_code=400, detail="Invalid media request format")

        item = await ContentService.get(db, content_id)
        result = await db.execute(
            select(Client).where(Client.id == item.client_id)
        )
        client = result.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        group_id = (client.telegram_group_id or "").strip()
        if not group_id:
            logger.warning("[Media Request] failed: content=%s reason=no_telegram_group", content_id)
            raise HTTPException(status_code=400, detail=TELEGRAM_INTAKE_NOT_LINKED)

        resolved_format = await _resolve_required_format(db, item, required_format)
        plan_item = await _get_plan_item_for_content(db, content_id)
        theme = plan_item.theme if plan_item else None
        goal = plan_item.goal if plan_item else None

        message = await _generate_media_request_message(
            db=db,
            client=client,
            content=item,
            required_format=resolved_format,
            theme=theme,
            goal=goal,
        )

        ok, err = await send_telegram_message(group_id, message)
        if not ok:
            logger.warning(
                "[Media Request] failed: content=%s group=%s error=%s",
                content_id,
                group_id,
                err,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to send Telegram message: {err or 'unknown error'}",
            )

        now = datetime.now(timezone.utc)
        item.media_request_sent_at = now
        item.media_request_message = message
        item.media_request_status = "requested"
        item.media_request_format = resolved_format
        await db.commit()

        logger.info("[Media Request] sent: content=%s group=%s format=%s", content_id, group_id, resolved_format)
        refreshed = await ContentService.get(db, content_id)
        return {
            "ok": True,
            "message": "Media request sent to client Telegram group",
            "media_request_status": refreshed.media_request_status,
            "media_request_sent_at": refreshed.media_request_sent_at,
            "media_request_message": refreshed.media_request_message,
            "media_request_format": refreshed.media_request_format,
        }

    @staticmethod
    async def try_fulfill_from_buffer(
        db: AsyncSession,
        entry: TelegramGroupBufferMessage,
        client: Client,
    ) -> bool:
        if entry.sender_role not in CLIENT_SENDER_ROLES:
            return False
        if not entry.media_file_id:
            return False

        result = await db.execute(
            select(ContentItem)
            .where(
                ContentItem.client_id == client.id,
                ContentItem.media_request_status == "requested",
            )
            .order_by(ContentItem.media_request_sent_at.desc())
        )
        content = result.scalars().first()
        if not content:
            return False

        required = content.media_request_format or "any"
        if not _media_matches_format(entry.message_type, required):
            entry.linked_content_id = content.id
            logger.info(
                "[Media Request] linked (format mismatch): content=%s inbox=%s type=%s want=%s",
                content.id,
                entry.id,
                entry.message_type,
                required,
            )
            return True

        entry.linked_content_id = content.id
        entry.inbox_status = INBOX_USED

        if not content.media_file_id:
            content.media_file_id = entry.media_file_id

        content.media_request_status = "fulfilled"
        await db.flush()

        logger.info(
            "[Media Request] fulfilled: content=%s inbox=%s media=%s",
            content.id,
            entry.id,
            entry.media_file_id,
        )
        return True

    @staticmethod
    async def content_ids_with_media_request(
        db: AsyncSession,
        content_ids: list[UUID],
    ) -> set[UUID]:
        if not content_ids:
            return set()
        result = await db.execute(
            select(ContentItem.id).where(
                ContentItem.id.in_(content_ids),
                ContentItem.media_request_sent_at.isnot(None),
            )
        )
        return {row[0] for row in result.all()}
