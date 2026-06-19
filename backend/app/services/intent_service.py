"""
Classify Telegram group messages by intent before acting on them.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Literal

from app.core.config import settings
from app.services.ai_service import get_openai, _extract_json, _validate_api_key

logger = logging.getLogger(__name__)

IntentType = Literal[
    "CONTENT_INSTRUCTION",
    "INTERNAL_COMMENT",
    "CHAT_MESSAGE",
    "CLIENT_CONTENT",
]

LOW_CONFIDENCE_THRESHOLD = 0.55

_SYSTEM = """\
Classify a Telegram group message BEFORE the bot acts on it.

Categories:
1. CONTENT_INSTRUCTION (ADMIN_INSTRUCTION) — operator command to edit content; NEVER publishable text
2. INTERNAL_COMMENT — team chat, review notes, jokes — NEVER publish
3. CHAT_MESSAGE — greetings, thanks — ignore
4. CLIENT_CONTENT — client submitting actual post material (caption/media), NOT admin commands

CRITICAL: Admin messages like "сделай так как хочет клиент", "используй пожелание клиента", \
"только видео", "сделай стиль серьёзнее" are ALWAYS CONTENT_INSTRUCTION even if they mention "клиент". \
They are NOT client content to publish.

Return ONLY JSON:
{
  "type": "CONTENT_INSTRUCTION|INTERNAL_COMMENT|CHAT_MESSAGE|CLIENT_CONTENT",
  "confidence": 0.0 to 1.0,
  "reasoning": "short explanation"
}

Priority: understand meaning, not keyword matching alone.
"""


def _heuristic_intent(
    text: str,
    *,
    is_admin: bool,
    has_media: bool,
    is_reply: bool,
    has_bot_mention: bool = False,
) -> dict[str, Any]:
    lower = text.lower().strip()

    if is_admin and (has_bot_mention or is_reply) and not has_media:
        from app.services.telegram_instruction_service import is_admin_meta_instruction
        if is_admin_meta_instruction(text):
            return {"type": "CONTENT_INSTRUCTION", "confidence": 0.92, "reasoning": "admin meta instruction"}
        instruction_patterns = (
            "добав", "убери", "сделай", "только видео", "скидк", "адрес", "emoji", "эмодзи",
            "формал", "делов", "hashtag", "описан", "не публику", "фото", "используй",
            "add ", "remove", "make ", "only video", "discount", "address",
        )
        if any(p in lower for p in instruction_patterns):
            return {"type": "CONTENT_INSTRUCTION", "confidence": 0.88, "reasoning": "admin action verb"}
        return {"type": "CONTENT_INSTRUCTION", "confidence": 0.78, "reasoning": "admin bot/reply directive"}

    if has_media and not is_reply:
        return {"type": "CLIENT_CONTENT", "confidence": 0.8, "reasoning": "media upload"}

    chat_patterns = (
        r"^(привет|здравств|доброе утро|добрый|спасибо|thanks|ok|ок|понял|понятно|good morning|hello)\b",
        r"^(hi|hey|thank you)\b",
    )
    if any(re.search(p, lower) for p in chat_patterns) and len(lower) < 80:
        return {"type": "CHAT_MESSAGE", "confidence": 0.85, "reasoning": "greeting/thanks"}

    internal_patterns = (
        "хаха", "странно", "провер", "позже", "интересно", "что думаешь", "ray", "рей",
        "need to check", "looks weird", "later",
    )
    if any(p in lower for p in internal_patterns):
        return {"type": "INTERNAL_COMMENT", "confidence": 0.78, "reasoning": "team comment"}

    instruction_patterns = (
        "добав", "убери", "сделай", "только видео", "скидк", "адрес", "emoji", "эмодзи",
        "формал", "делов", "hashtag", "описан", "не публику", "фото",
        "add ", "remove", "make ", "only video", "discount", "address",
    )
    if is_admin and any(p in lower for p in instruction_patterns):
        return {"type": "CONTENT_INSTRUCTION", "confidence": 0.8, "reasoning": "action verb"}

    if is_reply and is_admin:
        return {"type": "CONTENT_INSTRUCTION", "confidence": 0.75, "reasoning": "admin reply"}

    if not is_admin:
        return {"type": "CLIENT_CONTENT", "confidence": 0.65, "reasoning": "non-admin message"}

    return {"type": "CHAT_MESSAGE", "confidence": 0.5, "reasoning": "unclear admin text"}


def _log_intent(result: dict[str, Any], *, is_admin: bool) -> None:
    intent_type = result.get("type")
    confidence = float(result.get("confidence", 0))
    if is_admin and intent_type == "CONTENT_INSTRUCTION":
        logger.info("[Intent] ADMIN_INSTRUCTION confidence: %.2f", confidence)
    elif intent_type == "CLIENT_CONTENT":
        logger.info("[Intent] CLIENT_CONTENT confidence: %.2f", confidence)
    else:
        logger.info("[Intent] type: %s confidence: %.2f", intent_type, confidence)


async def classify_message_intent(
    text: str,
    *,
    is_admin: bool,
    has_media: bool = False,
    is_reply: bool = False,
    has_bot_mention: bool = False,
    recent_messages: list[str] | None = None,
) -> dict[str, Any]:
    """Return {type, confidence, reasoning}."""
    text = (text or "").strip()
    if not text and has_media:
        result = {"type": "CLIENT_CONTENT", "confidence": 0.85, "reasoning": "media only"}
        _log_intent(result, is_admin=is_admin)
        return result

    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        result = _heuristic_intent(
            text, is_admin=is_admin, has_media=has_media, is_reply=is_reply,
            has_bot_mention=has_bot_mention,
        )
    else:
        try:
            _validate_api_key()
            recent = "\n".join(f"- {m[:200]}" for m in (recent_messages or [])[-5:])
            user_msg = (
                f"Sender role: {'admin/operator' if is_admin else 'client'}\n"
                f"Has media attachment: {has_media}\n"
                f"Is reply to another message: {is_reply}\n"
                f"Has bot @mention: {has_bot_mention}\n"
                f"Recent chat:\n{recent or '(none)'}\n\n"
                f"MESSAGE:\n{text[:1500]}"
            )
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.15,
                max_tokens=250,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            parsed = _extract_json(raw)
            intent_type = parsed.get("type", "CHAT_MESSAGE")
            if intent_type not in (
                "CONTENT_INSTRUCTION", "INTERNAL_COMMENT", "CHAT_MESSAGE", "CLIENT_CONTENT",
            ):
                intent_type = "CHAT_MESSAGE"
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
            result = {
                "type": intent_type,
                "confidence": confidence,
                "reasoning": (parsed.get("reasoning") or "")[:200],
            }
        except Exception as exc:
            logger.warning("[Intent] classification failed (%s) — heuristic", exc)
            result = _heuristic_intent(
                text, is_admin=is_admin, has_media=has_media, is_reply=is_reply,
                has_bot_mention=has_bot_mention,
            )

    if is_admin and result.get("type") == "CLIENT_CONTENT":
        result = {
            **result,
            "type": "CONTENT_INSTRUCTION",
            "confidence": max(float(result.get("confidence", 0)), 0.75),
            "reasoning": "admin reclassified from CLIENT_CONTENT",
        }

    _log_intent(result, is_admin=is_admin)
    return result
