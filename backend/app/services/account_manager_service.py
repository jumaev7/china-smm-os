"""AI Account Manager — understand client Telegram messages and assist operators."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.client_review_telegram_service import send_telegram_message
from app.services.operator_common import CLIENT_SENDER_ROLES

logger = logging.getLogger(__name__)

ACCOUNT_MANAGER_INTENTS = frozenset({
    "new_content_request",
    "change_request",
    "media_upload",
    "schedule_request",
    "question",
    "complaint",
    "pricing_billing",
    "unclear",
})

PRIORITIES = frozenset({"low", "medium", "high"})

AUTO_DRAFT_INTENTS = frozenset({"new_content_request", "schedule_request"})

_DEFAULT_REPLIES: dict[str, str] = {
    "new_content_request": "Принял, подготовим черновик.",
    "change_request": "Понял, внесём изменения.",
    "media_upload": "Спасибо, материалы получены.",
    "schedule_request": "Принял, учтём расписание при подготовке.",
    "question": "Спасибо за вопрос — команда скоро ответит.",
    "complaint": "Спасибо за сообщение, мы передали его команде.",
    "pricing_billing": "Спасибо, передали ваш вопрос менеджеру.",
    "unclear": "Уточните, пожалуйста, что именно нужно опубликовать?",
}

_ACCOUNT_MANAGER_SYSTEM = """\
You are a polite AI account manager for a social media agency Telegram group.
You help clients feel supported while operators prepare content manually.

Analyze the client message and return ONLY JSON:
{
  "intent": "new_content_request|change_request|media_upload|schedule_request|question|complaint|pricing_billing|unclear",
  "summary": "1-2 sentence internal summary for operators (English or Russian)",
  "recommended_action": "imperative for operator — what to do next",
  "priority": "low|medium|high",
  "reply_text": "short polite reply to client in Russian (or match client language if obvious)",
  "safe_to_reply": true,
  "is_clear_content_request": false
}

Rules:
- new_content_request: client wants a new post/publication with materials or brief
- change_request: edits to existing draft/post/caption
- media_upload: mainly sending photos/videos without clear publish brief
- schedule_request: mentions timing (завтра, в 18:00, Monday, schedule)
- question: general question without clear publish task
- complaint: dissatisfaction, problem, delay
- pricing_billing: price, invoice, plan, payment questions
- unclear: not enough information
- is_clear_content_request: true only when intent is new_content_request or schedule_request AND enough detail/media to start a draft
- Never mention internal systems, AI, inbox, drafts workflow, or admin approval in reply_text
- Never promise automatic publishing — say team will prepare/review
- Keep reply_text under 280 characters, warm and professional
- safe_to_reply false only if message is abusive/spam or requires human-only handling
"""


def _normalize_intent(raw: Any) -> str:
    key = str(raw or "unclear").lower().strip().replace(" ", "_").replace("/", "_")
    if key in ("pricing", "billing", "pricing_billing_question"):
        return "pricing_billing"
    if key in ACCOUNT_MANAGER_INTENTS:
        return key
    return "unclear"


def _normalize_priority(raw: Any) -> str:
    key = str(raw or "medium").lower().strip()
    return key if key in PRIORITIES else "medium"


def _heuristic_analyze(
    *,
    text: str,
    has_media: bool,
    client: Client,
    media_request_fulfilled: bool,
) -> dict[str, Any]:
    lower = (text or "").lower()

    if media_request_fulfilled or (has_media and not text.strip()):
        intent = "media_upload"
        clear = False
        priority = "medium"
        summary = "Client sent media materials."
        action = "Review uploaded media and attach to content or create draft."
    elif any(w in lower for w in ("жалоб", "complaint", "недовол", "плохо", "ужас")):
        intent = "complaint"
        clear = False
        priority = "high"
        summary = "Client complaint or dissatisfaction."
        action = "Review complaint and respond personally."
    elif any(w in lower for w in ("цена", "тариф", "оплат", "invoice", "billing", "план", "стоим")):
        intent = "pricing_billing"
        clear = False
        priority = "medium"
        summary = "Pricing or billing question."
        action = "Forward to account/billing manager."
    elif any(w in lower for w in ("измен", "правк", "edit", "update", "поменя", "исправ")):
        intent = "change_request"
        clear = False
        priority = "medium"
        summary = "Client requests changes to content."
        action = "Open linked draft and apply client feedback."
    elif any(w in lower for w in ("завтра", "schedule", "распис", "в ", "monday", "понедель", "опублик")):
        intent = "schedule_request"
        clear = has_media or len(text.strip()) > 20
        priority = "medium"
        summary = "Client mentions publication schedule."
        action = "Create or update draft with suggested schedule."
    elif any(w in lower for w in ("?", "как ", "what", "when", "сколько", "можно")):
        intent = "question"
        clear = False
        priority = "low"
        summary = "Client question."
        action = "Answer client or clarify before creating content."
    elif has_media or any(w in lower for w in ("пост", "post", "контент", "сделай", "нужен", "публ")):
        intent = "new_content_request"
        clear = has_media or len(text.strip()) > 15
        priority = "medium"
        summary = "Client content/publication request."
        action = "Review materials and prepare draft for operator approval."
    else:
        intent = "unclear"
        clear = False
        priority = "low"
        summary = "Client message needs clarification."
        action = "Ask client for details or review manually."

    reply = _DEFAULT_REPLIES.get(intent, _DEFAULT_REPLIES["unclear"])
    if intent == "unclear":
        reply = _DEFAULT_REPLIES["unclear"]

    related = client.telegram_active_content_id if intent == "change_request" else None

    return {
        "intent": intent,
        "summary": summary,
        "recommended_action": action,
        "priority": priority,
        "reply_text": reply,
        "safe_to_reply": True,
        "is_clear_content_request": clear and intent in AUTO_DRAFT_INTENTS,
        "related_content_id": str(related) if related else None,
        "source": "fallback",
    }


async def _ai_analyze(
    db: AsyncSession,
    *,
    text: str,
    has_media: bool,
    client: Client,
    media_request_fulfilled: bool,
) -> dict[str, Any]:
    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        return _heuristic_analyze(
            text=text,
            has_media=has_media,
            client=client,
            media_request_fulfilled=media_request_fulfilled,
        )

    _validate_api_key()
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, max_chars=2500, context="account_manager",
    )
    active_line = ""
    if client.telegram_active_content_id:
        active_line = f"Active draft content_id: {client.telegram_active_content_id}\n"

    user_block = (
        f"CLIENT: {client.company_name}\n"
        f"SOURCE LANGUAGE: {client.source_language or 'ru'}\n"
        f"{active_line}"
        f"HAS_MEDIA: {has_media}\n"
        f"MEDIA_REQUEST_FULFILLED: {media_request_fulfilled}\n"
        f"MESSAGE:\n{(text or '(media only)')[:2500]}\n"
    )
    if kb_block:
        user_block = f"{user_block}\n{kb_block}"

    openai = get_openai()
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _ACCOUNT_MANAGER_SYSTEM},
            {"role": "user", "content": user_block},
        ],
        temperature=0.25,
        max_tokens=700,
        response_format={"type": "json_object"},
    )
    raw = _extract_json(response.choices[0].message.content or "{}")
    intent = _normalize_intent(raw.get("intent"))
    if media_request_fulfilled and intent not in ("change_request", "complaint", "pricing_billing"):
        intent = "media_upload"

    is_clear = bool(raw.get("is_clear_content_request"))
    if intent not in AUTO_DRAFT_INTENTS:
        is_clear = False

    related = raw.get("related_content_id")
    if not related and intent == "change_request" and client.telegram_active_content_id:
        related = str(client.telegram_active_content_id)

    reply = (raw.get("reply_text") or "").strip() or _DEFAULT_REPLIES.get(intent, _DEFAULT_REPLIES["unclear"])

    return {
        "intent": intent,
        "summary": (raw.get("summary") or "Client message")[:500],
        "recommended_action": (raw.get("recommended_action") or "Review inbox item")[:500],
        "priority": _normalize_priority(raw.get("priority")),
        "reply_text": reply[:280],
        "safe_to_reply": bool(raw.get("safe_to_reply", True)),
        "is_clear_content_request": is_clear,
        "related_content_id": str(related) if related else None,
        "source": "ai",
    }


def _parse_related_content_id(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


class AccountManagerService:
    @staticmethod
    async def process_client_message(
        db: AsyncSession,
        *,
        entry: TelegramGroupBufferMessage,
        client: Client,
        chat_id: int | str,
        message: dict,
        has_media: bool,
        media_request_fulfilled: bool = False,
    ) -> dict[str, Any]:
        if entry.sender_role not in CLIENT_SENDER_ROLES:
            logger.info("[Account Manager] skipped: inbox=%s reason=not_client", entry.id)
            return {"skipped": True, "reply_sent": False, "should_auto_draft": False}

        if entry.account_manager_processed_at:
            logger.info("[Account Manager] skipped: inbox=%s reason=already_processed", entry.id)
            return {
                "skipped": True,
                "reply_sent": bool(entry.account_manager_reply_sent),
                "should_auto_draft": False,
            }

        text = (entry.text or "").strip()
        if not text and not has_media:
            logger.info("[Account Manager] skipped: inbox=%s reason=no_content", entry.id)
            return {"skipped": True, "reply_sent": False, "should_auto_draft": False}

        try:
            analysis = await _ai_analyze(
                db,
                text=text,
                has_media=has_media,
                client=client,
                media_request_fulfilled=media_request_fulfilled,
            )
        except Exception as exc:
            logger.warning("[Account Manager] fallback: inbox=%s error=%s", entry.id, exc)
            analysis = _heuristic_analyze(
                text=text,
                has_media=has_media,
                client=client,
                media_request_fulfilled=media_request_fulfilled,
            )

        intent = analysis["intent"]
        logger.info("[Account Manager] intent: inbox=%s intent=%s source=%s", entry.id, intent, analysis.get("source"))

        related_id = _parse_related_content_id(analysis.get("related_content_id"))
        if related_id:
            exists = await db.execute(
                select(ContentItem.id).where(
                    ContentItem.id == related_id,
                    ContentItem.client_id == client.id,
                )
            )
            if not exists.scalar_one_or_none():
                related_id = None

        now = datetime.now(timezone.utc)
        entry.account_manager_intent = intent
        entry.account_manager_summary = analysis["summary"]
        entry.account_manager_recommended_action = analysis["recommended_action"]
        entry.account_manager_priority = analysis["priority"]
        entry.account_manager_related_content_id = related_id
        entry.account_manager_processed_at = now

        if not entry.priority:
            entry.priority = analysis["priority"]
        if not entry.ai_summary:
            entry.ai_summary = analysis["summary"]

        reply_sent = False
        reply_text = analysis.get("reply_text") or ""
        if analysis.get("safe_to_reply") and reply_text:
            client_msg_id = message.get("message_id")
            ok, err = await send_telegram_message(
                chat_id,
                reply_text,
            )
            if ok:
                reply_sent = True
                entry.account_manager_reply_sent = True
                entry.account_manager_reply_text = reply_text
                logger.info("[Account Manager] reply sent: inbox=%s chat=%s", entry.id, chat_id)
            else:
                logger.warning(
                    "[Account Manager] reply failed: inbox=%s error=%s",
                    entry.id,
                    err,
                )
        else:
            logger.info("[Account Manager] skipped: inbox=%s reason=reply_not_safe", entry.id)

        should_auto_draft = (
            bool(analysis.get("is_clear_content_request"))
            and intent in AUTO_DRAFT_INTENTS
            and not media_request_fulfilled
        )

        logger.info(
            "[Account Manager] task created: inbox=%s intent=%s priority=%s auto_draft=%s",
            entry.id,
            intent,
            analysis["priority"],
            should_auto_draft,
        )

        await db.flush()

        return {
            "ok": True,
            "skipped": False,
            "intent": intent,
            "summary": analysis["summary"],
            "recommended_action": analysis["recommended_action"],
            "priority": analysis["priority"],
            "reply_sent": reply_sent,
            "reply_text": reply_text if reply_sent else None,
            "related_content_id": str(related_id) if related_id else None,
            "should_auto_draft": should_auto_draft,
        }
