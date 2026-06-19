"""
Dashboard AI assistant — context-aware chat with optional content field patches.
"""
import json
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.ai_service import get_openai, _extract_json, _validate_api_key
from app.services.brand_profile import brand_profile_from_client
from app.schemas.content import ContentUpdate
from app.services.client_service import ClientService
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

_PATCHABLE_FIELDS = frozenset({
    "caption_short_ru",
    "caption_short_uz",
    "caption_short_en",
    "caption_long_ru",
    "caption_long_uz",
    "caption_long_en",
    "hashtags",
    "internal_notes",
})

# Never auto-apply destructive or workflow actions (publish, schedule, delete media, etc.)
_BLOCKED_PATCH_FIELDS = frozenset({
    "status",
    "platforms",
    "scheduled_for",
    "media_file_id",
    "client_id",
    "published_at",
    "approved_at",
})

_SYSTEM_PROMPT = """\
You are the in-app AI assistant for China SMM OS — an internal tool for Chinese \
businesses marketing in Uzbekistan (captions in RU / UZ / EN).

You help operators with:
- Rewriting captions
- Making text shorter or more formal
- Making copy more sales-focused
- Translating captions (Russian, Uzbek Latin, English)
- Improving hashtags
- Suggesting posting times for Instagram/TikTok in Uzbekistan (Tashkent timezone)
- Explaining what the current media/content is about

Rules:
- Be concise and actionable
- Match brand tone when brand profile is provided
- When auto-apply is enabled, return suggested_patch and the server saves it; otherwise \
the user confirms before Apply
- When the user asks to edit captions/hashtags/subtitle text AND a content item is in context, \
include a suggested_patch object with ONLY changed fields
- suggested_patch keys allowed: caption_short_ru, caption_short_uz, caption_short_en, \
caption_long_ru, caption_long_uz, caption_long_en, hashtags, internal_notes (transcript/subtitle text)
- NEVER include status, platforms, scheduled_for, or media_file_id in suggested_patch
- If no content item is in context, give advice only (no suggested_patch)
- ALWAYS respond with valid JSON only:
{"reply": "your message to the user", "suggested_patch": null}
or with suggested_patch as an object when appropriate.
"""


def _filter_patch(raw: dict | None) -> dict | None:
    if not raw or not isinstance(raw, dict):
        return None
    filtered = {
        k: v for k, v in raw.items()
        if k in _PATCHABLE_FIELDS
        and k not in _BLOCKED_PATCH_FIELDS
        and v is not None
        and str(v).strip()
    }
    return filtered or None


async def apply_assistant_patch(
    db: AsyncSession,
    content_id: UUID,
    patch: dict,
    *,
    auto: bool,
) -> dict:
    """Apply a whitelisted content patch. Logs auto vs manual apply."""
    filtered = _filter_patch(patch)
    if not filtered:
        raise ValueError("No safe content fields to apply")

    await ContentService.update(db, content_id, ContentUpdate(**filtered))

    log_label = "auto apply" if auto else "manual apply"
    logger.info(
        "[Assistant] %s: content_id=%s fields=%s",
        log_label,
        content_id,
        sorted(filtered.keys()),
    )
    return filtered


def _build_context_block(
    page_context: dict,
    client_data: dict | None,
    content_data: dict | None,
) -> str:
    lines = [
        f"PAGE: {page_context.get('page_type', 'other')}",
        f"PATH: {page_context.get('pathname', '')}",
    ]
    if page_context.get("summary"):
        lines.append(f"UI SUMMARY: {page_context['summary']}")

    if client_data:
        lines.append("\nCLIENT:")
        lines.append(f"- Company: {client_data.get('company_name')}")
        lines.append(f"- Category: {client_data.get('business_category')}")
        lines.append(f"- Tone: {client_data.get('tone_of_voice', 'friendly')}")
        if client_data.get("brand_name"):
            lines.append(f"- Brand: {client_data['brand_name']}")
        if client_data.get("business_description"):
            lines.append(f"- About: {client_data['business_description'][:500]}")
        if client_data.get("products_services"):
            lines.append(f"- Products/services: {client_data['products_services'][:400]}")
        if client_data.get("target_audience"):
            lines.append(f"- Audience: {client_data['target_audience'][:300]}")
        if client_data.get("hashtag_preferences"):
            lines.append(f"- Hashtag prefs: {client_data['hashtag_preferences'][:200]}")
        if client_data.get("words_to_avoid"):
            lines.append(f"- Avoid words: {client_data['words_to_avoid'][:200]}")

    if content_data:
        lines.append("\nCONTENT ITEM:")
        lines.append(f"- ID: {content_data.get('id')}")
        lines.append(f"- Status: {content_data.get('status')}")
        lines.append(f"- Source: {content_data.get('source')}")
        lines.append(f"- Platforms: {', '.join(content_data.get('platforms') or [])}")
        if content_data.get("media_file_type"):
            lines.append(f"- Media: {content_data['media_file_type']}")
        for key in (
            "caption_short_ru", "caption_short_uz", "caption_short_en",
            "caption_long_ru", "caption_long_uz", "caption_long_en",
        ):
            val = content_data.get(key)
            if val:
                lines.append(f"- {key}: {val[:400]}")
        if content_data.get("hashtags"):
            lines.append(f"- hashtags: {content_data['hashtags'][:300]}")
        notes = content_data.get("internal_notes") or ""
        if notes:
            excerpt = notes[:600].replace("\n", " ")
            lines.append(f"- internal_notes excerpt: {excerpt}")
        subs = []
        for lang in ("cn", "ru", "uz", "en"):
            if content_data.get(f"subtitle_url_{lang}"):
                subs.append(lang.upper())
        if subs:
            lines.append(f"- Subtitles available: {', '.join(subs)}")

    return "\n".join(lines)


async def _load_context(
    db: AsyncSession,
    client_id: UUID | None,
    content_id: UUID | None,
) -> tuple[dict | None, dict | None]:
    client_data = None
    content_data = None

    if content_id:
        item = await ContentService.get(db, content_id)
        serialized = ContentService.serialize(item)
        content_data = serialized
        if not client_id:
            client_id = item.client_id

    if client_id:
        client = await ClientService.get(db, client_id)
        client_data = {
            "company_name": client.company_name,
            "business_category": client.business_category,
            "content_style": client.content_style,
            **brand_profile_from_client(client),
        }

    return client_data, content_data


async def assistant_chat(
    db: AsyncSession,
    *,
    message: str,
    page_context: dict,
    client_id: UUID | None = None,
    content_id: UUID | None = None,
    history: list[dict] | None = None,
    auto_apply: bool = False,
) -> dict:
    """Return {reply, suggested_patch, applied}."""
    if settings.DEMO_MODE:
        patch = None
        if content_id and any(w in message.lower() for w in ("rewrite", "short", "formal", "sales", "hashtag")):
            patch = {"caption_short_ru": "✨ Демо — обновлённый короткий текст"}
        applied = False
        if patch and content_id and auto_apply:
            await apply_assistant_patch(db, content_id, patch, auto=True)
            applied = True
        return {
            "reply": (
                "Demo mode: I received your message. "
                "Configure OPENAI_API_KEY for full assistant replies."
            ),
            "suggested_patch": None if applied else patch,
            "applied": applied,
        }

    _validate_api_key()

    client_data, content_data = await _load_context(db, client_id, content_id)
    context_block = _build_context_block(page_context, client_data, content_data)

    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        for turn in history[-8:]:
            role = turn.get("role", "user")
            if role in ("user", "assistant") and turn.get("content"):
                messages.append({"role": role, "content": str(turn["content"])[:2000]})

    messages.append({
        "role": "user",
        "content": f"{context_block}\n\nUSER REQUEST:\n{message.strip()}",
    })

    openai = get_openai()
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,
        temperature=0.55,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    try:
        data = _extract_json(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Assistant: invalid JSON — %s", exc)
        return {
            "reply": raw.strip() or "Sorry, I could not parse a response.",
            "suggested_patch": None,
            "applied": False,
        }

    reply = (data.get("reply") or "").strip()
    if not reply:
        reply = "I’m here to help with captions, hashtags, and content questions."

    patch = _filter_patch(data.get("suggested_patch"))
    if patch and not content_id:
        patch = None

    applied = False
    if patch and content_id and auto_apply:
        await apply_assistant_patch(db, content_id, patch, auto=True)
        applied = True

    return {
        "reply": reply,
        "suggested_patch": None if applied else patch,
        "applied": applied,
    }
