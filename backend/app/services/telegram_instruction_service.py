"""
Parse and apply natural-language Telegram group instructions from admins.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.schemas.content import ContentUpdate
from app.services.ai_service import get_openai, _extract_json, _validate_api_key
from app.services.assistant_service import _filter_patch
from app.services.brand_profile import brand_profile_from_client
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

_ADMIN_INSTRUCTION_MARKER = "[Admin instruction]:"
_PENDING_CLIENT_MARKER = "[Pending client text]:"
_SKIP_SOURCE_PREFIXES = (
    "[Admin instruction]:",
    "[Internal comment]:",
    "[Low confidence note]:",
    "[Telegram instruction]:",
    "[OCR]:",
    "[Transcript]:",
    "[Context AI]:",
    "[Client source]:",
)


def is_admin_meta_instruction(text: str) -> bool:
    """True when text is an operator command, not publishable client content."""
    lower = (text or "").lower().strip()
    if not lower:
        return False
    meta_phrases = (
        "сделай так", "как хочет клиент", "как хочет", "пожелание клиента",
        "используй пожелание", "follow client", "use client wish",
        "client request", "сделай так как", "хочет клиент",
        "только видео", "only video", "убери фото", "не публику",
        "сделай стиль", "сделай более", "сделай текст", "убери эмодзи",
    )
    if any(p in lower for p in meta_phrases):
        return True
    admin_verbs = ("сделай", "убери", "добавь", "используй", "сделайте")
    return any(lower.startswith(v) or f" {v}" in f" {lower}" for v in admin_verbs)


def is_follow_client_instruction(text: str) -> bool:
    lower = (text or "").lower()
    return any(p in lower for p in (
        "как хочет клиент", "пожелание клиента", "используй пожелание",
        "сделай так как", "follow client", "client wish", "хочет клиент",
    ))


def extract_client_source_text(notes: str | None) -> str:
    """Publishable client source only — never admin/operator commands."""
    if not notes:
        return ""
    for line in notes.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in _SKIP_SOURCE_PREFIXES):
            continue
        if is_admin_meta_instruction(stripped):
            continue
        return stripped
    return ""


def extract_admin_instruction(notes: str | None) -> str:
    if not notes:
        return ""
    for line in notes.split("\n"):
        if line.strip().startswith(_ADMIN_INSTRUCTION_MARKER):
            return line.strip()[len(_ADMIN_INSTRUCTION_MARKER):].strip()
    return ""


def extract_client_text_from_reply(reply_to_message: dict | None) -> str:
    if not reply_to_message:
        return ""
    return (reply_to_message.get("text") or reply_to_message.get("caption") or "").strip()


def _machine_suffix_lines(notes: str | None) -> list[str]:
    if not notes:
        return []
    suffix: list[str] = []
    for line in notes.split("\n"):
        s = line.strip()
        if s.startswith(("[OCR]:", "[Transcript]:", "[Context AI]:", "[Internal comment]:",
                          "[Low confidence note]:", "[Telegram instruction]:")):
            suffix.append(line)
    return suffix


def set_client_source(item: ContentItem, client_text: str) -> None:
    """Store client publish text separately from admin instruction layer."""
    client_text = client_text.strip()
    if not client_text or is_admin_meta_instruction(client_text):
        return
    admin_line = ""
    existing_admin = extract_admin_instruction(item.internal_notes)
    if existing_admin:
        admin_line = f"\n{_ADMIN_INSTRUCTION_MARKER} {existing_admin}"
    suffix = _machine_suffix_lines(item.internal_notes)
    suffix_block = ("\n" + "\n".join(suffix)) if suffix else ""
    item.internal_notes = f"{client_text}{admin_line}{suffix_block}".strip()


def set_admin_instruction(item: ContentItem, instruction: str) -> None:
    instruction = instruction.strip()
    if not instruction:
        return
    line = f"{_ADMIN_INSTRUCTION_MARKER} {instruction}"
    notes = item.internal_notes or ""
    if _ADMIN_INSTRUCTION_MARKER in notes:
        rebuilt = []
        for ln in notes.split("\n"):
            if ln.strip().startswith(_ADMIN_INSTRUCTION_MARKER):
                rebuilt.append(line)
            else:
                rebuilt.append(ln)
        item.internal_notes = "\n".join(rebuilt).strip()
    else:
        item.internal_notes = f"{notes}\n{line}".strip() if notes else line


def build_generation_context_hint(
    admin_instruction: str,
    explicit_hint: str | None = None,
) -> str | None:
    if explicit_hint and explicit_hint.strip():
        return explicit_hint.strip()
    if admin_instruction.strip():
        return f"Operator instruction: {admin_instruction.strip()}"
    return None


_SYSTEM_PROMPT = """\
You parse admin instructions sent in a Telegram group for an SMM content task.

Understand Russian, Uzbek, and English instructions. Examples:
- add text to description / internal notes
- make captions more formal / business-like
- remove emojis from captions
- exclude photos, publish video only
- use only the latest video
- add address or CTA details to notes or captions

Return ONLY valid JSON:
{
  "summary": "short line describing what was applied",
  "patch": {
    "caption_short_ru": "optional full replacement",
    "caption_short_uz": "optional",
    "caption_short_en": "optional",
    "caption_long_ru": "optional",
    "caption_long_uz": "optional",
    "caption_long_en": "optional",
    "hashtags": "optional",
    "append_internal_notes": "text to append to operator notes",
    "replace_source_text": "optional replacement for human source/caption line in notes"
  },
  "exclude_photos": false,
  "exclude_this_content": false,
  "prefer_latest_video": false
}

Rules:
- patch keys must only change captions, hashtags, or notes — never status or platforms
- append_internal_notes for "add to description" style requests
- exclude_photos=true when admin says not to publish photos / only video
- exclude_this_content=true when admin rejects the replied media item
- prefer_latest_video=true when admin wants only the latest video used
- NEVER put admin instruction text into replace_source_text or caption fields verbatim
- replace_source_text is ONLY for correcting client source text, never operator commands
- Meta instructions like "follow client wish" / "сделай как хочет клиент" → update captions from CLIENT SOURCE below, not from admin text
- summary in Russian if instruction was in Russian, else match instruction language
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_instruction_history(
    item: ContentItem,
    instruction: str,
    summary: str,
    admin_name: str,
    *,
    status: str = "applied",
) -> None:
    history: list[dict] = []
    if item.telegram_instructions:
        try:
            history = json.loads(item.telegram_instructions)
        except json.JSONDecodeError:
            history = []
    history.append({
        "at": _utcnow_iso(),
        "instruction": instruction[:500],
        "summary": summary[:300],
        "from": admin_name[:100],
        "status": status,
    })
    item.telegram_instructions = json.dumps(history[-20:], ensure_ascii=False)


_TELEGRAM_PATCH_MARKER = "[Telegram instruction]:"


def _apply_notes_patch(item: ContentItem, patch: dict) -> None:
    if patch.get("replace_source_text"):
        notes = item.internal_notes or ""
        ocr_idx = notes.find("\n[OCR]:")
        transcript_idx = notes.find("\n[Transcript]:")
        cut = [i for i in (ocr_idx, transcript_idx) if i != -1]
        suffix = notes[min(cut):] if cut else ""
        item.internal_notes = patch["replace_source_text"].strip() + suffix

    if patch.get("append_internal_notes"):
        line = f"{_TELEGRAM_PATCH_MARKER} {patch['append_internal_notes'].strip()}"
        notes = item.internal_notes or ""
        item.internal_notes = f"{notes}\n{line}".strip() if notes else line


TG_GROUP_BUFFER_SOURCE = "tg_group_buffer"
_GROUP_CONTENT_SOURCES = ("telegram_group", TG_GROUP_BUFFER_SOURCE)
_ACTIVE_GROUP_STATUSES = ("draft", "ready", "ready_for_approval")
_NEW_CONTENT_KEYWORDS = (
    "создай новый пост", "новая публикация", "новый контент",
    "new post", "new content", "another post",
)
GROUP_TASK_NO_ACTIVE_REPLY = "⚠️ Нет активной задачи. Сначала создайте контент из материалов."
GROUP_TASK_APPLIED_REPLY = "✅ Инструкция применена к текущей задаче."


def is_explicit_new_content_request(text: str) -> bool:
    lower = (text or "").lower().strip()
    return any(k in lower for k in _NEW_CONTENT_KEYWORDS)


def is_task_edit_instruction(text: str) -> bool:
    """True when admin edits the active task — not a buffer assembly / selection-only message."""
    lower = (text or "").lower().strip()
    return any(p in lower for p in (
        "добавь", "убери", "сделай стиль", "скидк", "перенеси", "запланиру",
        "завтра", "address", "discount", "remove", "schedule", "дороже",
        "формальн", "premium", "luxury", "эмодзи", "emoji", "делов",
    ))


def _parse_remove_photo_ordinals(instruction: str) -> list[int]:
    lower = (instruction or "").lower()
    if "фото" not in lower and "photo" not in lower:
        return []
    if not any(w in lower for w in ("убери", "remove", "исключ", "except", "кроме")):
        return []
    ord_map = {
        "перв": 1, "first": 1, "1": 1,
        "втор": 2, "second": 2, "2": 2,
        "трет": 3, "third": 3, "3": 3,
        "четверт": 4, "fourth": 4, "4": 4,
    }
    found: list[int] = []
    for key, num in ord_map.items():
        if key in lower:
            found.append(num)
    m = re.search(r"(?:убери|remove|исключ)\s+(\d)", lower)
    if m:
        found.append(int(m.group(1)))
    return sorted(set(found))


def _apply_buffer_media_removals(content_item: ContentItem, ordinals: list[int]) -> bool:
    if not ordinals or not content_item.telegram_buffer_refs:
        return False
    try:
        refs = json.loads(content_item.telegram_buffer_refs)
    except json.JSONDecodeError:
        return False
    if not isinstance(refs, list):
        return False

    photo_refs = [
        r for r in refs
        if r.get("message_type") == "photo" and r.get("media_file_id")
    ]
    remove_ids: set[str] = set()
    for ordinal in ordinals:
        for ref in photo_refs:
            if int(ref.get("ordinal") or 0) == ordinal:
                remove_ids.add(str(ref["media_file_id"]))
        if 1 <= ordinal <= len(photo_refs):
            remove_ids.add(str(photo_refs[ordinal - 1]["media_file_id"]))

    if not remove_ids:
        return False

    new_refs = [r for r in refs if str(r.get("media_file_id") or "") not in remove_ids]
    if len(new_refs) == len(refs):
        return False

    for i, ref in enumerate(new_refs, 1):
        ref["ordinal"] = i
    content_item.telegram_buffer_refs = json.dumps(new_refs, ensure_ascii=False)

    if content_item.media_file_id and str(content_item.media_file_id) in remove_ids:
        remaining = [r for r in new_refs if r.get("media_file_id")]
        if remaining:
            content_item.media_file_id = UUID(str(remaining[0]["media_file_id"]))
    return True


def _parse_schedule_datetime(instruction: str) -> datetime | None:
    lower = (instruction or "").lower()
    if not any(w in lower for w in (
        "перенеси", "запланиру", "schedule", "завтра", "tomorrow", "на завтра",
    )):
        return None
    now = datetime.now(timezone.utc)
    target_date = now.date()
    if "завтра" in lower or "tomorrow" in lower:
        target_date = (now + timedelta(days=1)).date()
    m = re.search(r"(\d{1,2})[:.:](\d{2})", instruction)
    hour, minute = (18, 0) if not m else (int(m.group(1)), int(m.group(2)))
    if hour > 23 or minute > 59:
        return None
    return datetime(
        target_date.year, target_date.month, target_date.day,
        hour, minute, tzinfo=timezone.utc,
    )


def _wants_caption_refresh(instruction: str) -> bool:
    lower = (instruction or "").lower()
    return any(p in lower for p in (
        "стиль", "дороже", "premium", "luxury", "формальн", "делов", "emoji", "эмодзи", "скидк",
    ))


def _apply_heuristic_task_edits(content_item: ContentItem, instruction: str) -> str | None:
    """Fast local edits for common task-memory instructions."""
    lower = instruction.lower()
    parts: list[str] = []

    if any(w in lower for w in ("адрес", "address")):
        detail = instruction.split(":", 1)[-1].strip() if ":" in instruction else instruction.strip()
        _apply_notes_patch(content_item, {"append_internal_notes": detail})
        parts.append("Адрес добавлен")

    if "скидк" in lower or "discount" in lower:
        _apply_notes_patch(content_item, {"append_internal_notes": instruction.strip()})
        parts.append("Скидка добавлена")

    removed = _parse_remove_photo_ordinals(instruction)
    if removed and _apply_buffer_media_removals(content_item, removed):
        parts.append(f"Убраны фото #{', #'.join(str(o) for o in removed)}")

    scheduled = _parse_schedule_datetime(instruction)
    if scheduled:
        content_item.scheduled_for = scheduled
        parts.append(f"Запланировано на {scheduled.strftime('%Y-%m-%d %H:%M')} UTC")

    return "; ".join(parts) if parts else None


async def set_active_group_content(
    db: AsyncSession,
    client: Client,
    content_id: UUID,
) -> None:
    client.telegram_active_content_id = content_id
    await db.commit()
    logger.info("[Group Task Memory] active_content_id: %s", content_id)


async def get_active_group_content(
    db: AsyncSession,
    client: Client,
) -> ContentItem | None:
    """Return pinned active task or latest draft/ready group content for this client."""
    active_id = getattr(client, "telegram_active_content_id", None)
    if active_id:
        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.media_file))
            .where(
                ContentItem.id == active_id,
                ContentItem.client_id == client.id,
                ContentItem.status.in_(_ACTIVE_GROUP_STATUSES),
            )
        )
        item = result.scalar_one_or_none()
        if item:
            logger.info("[Group Task Memory] active_content_id: %s", item.id)
            return item

    result = await db.execute(
        select(ContentItem)
        .options(selectinload(ContentItem.media_file))
        .where(
            ContentItem.client_id == client.id,
            ContentItem.source.in_(_GROUP_CONTENT_SOURCES),
            ContentItem.status.in_(_ACTIVE_GROUP_STATUSES),
        )
        .order_by(ContentItem.created_at.desc())
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if item:
        if getattr(client, "telegram_active_content_id", None) != item.id:
            client.telegram_active_content_id = item.id
            await db.flush()
        logger.info("[Group Task Memory] active_content_id: %s (fallback)", item.id)
    return item


async def find_latest_group_content(
    db: AsyncSession,
    client_id: UUID,
    *,
    within_minutes: int = 30,
) -> ContentItem | None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    result = await db.execute(
        select(ContentItem)
        .options(selectinload(ContentItem.media_file))
        .where(
            ContentItem.client_id == client_id,
            ContentItem.source.in_(_GROUP_CONTENT_SOURCES),
            ContentItem.status.in_(("draft", "ready", "ready_for_approval")),
            ContentItem.created_at >= cutoff,
        )
        .order_by(ContentItem.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_latest_buffer_content(
    db: AsyncSession,
    client_id: UUID,
    *,
    within_minutes: int = 120,
) -> ContentItem | None:
    """Latest content assembled from group buffer only — not auto-created telegram_group items."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    result = await db.execute(
        select(ContentItem)
        .options(selectinload(ContentItem.media_file))
        .where(
            ContentItem.client_id == client_id,
            ContentItem.source == TG_GROUP_BUFFER_SOURCE,
            ContentItem.status.in_(("draft", "ready", "ready_for_approval")),
            ContentItem.created_at >= cutoff,
        )
        .order_by(ContentItem.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def attach_client_text_to_recent(
    db: AsyncSession,
    client_id: UUID,
    text: str,
    *,
    within_minutes: int = 10,
) -> ContentItem | None:
    text = text.strip()
    if not text or is_admin_meta_instruction(text):
        return None
    item = await find_latest_group_content(db, client_id, within_minutes=within_minutes)
    if not item:
        return None
    set_client_source(item, text)
    await db.commit()
    return item


async def find_content_for_instruction(
    db: AsyncSession,
    client_id: UUID,
    reply_to_message: dict | None,
) -> ContentItem | None:
    return await _find_content_for_instruction(db, client_id, reply_to_message)


async def _find_content_for_instruction(
    db: AsyncSession,
    client_id: UUID,
    reply_to_message: dict | None,
) -> ContentItem | None:
    if reply_to_message:
        msg_id = reply_to_message.get("message_id")
        if msg_id is not None:
            result = await db.execute(
                select(ContentItem)
                .options(selectinload(ContentItem.media_file))
                .where(
                    ContentItem.client_id == client_id,
                    ContentItem.telegram_message_id == msg_id,
                )
            )
            item = result.scalar_one_or_none()
            if item:
                return item

    return await find_latest_group_content(db, client_id, within_minutes=30)


async def _exclude_photos_for_client(db: AsyncSession, client_id: UUID) -> int:
    result = await db.execute(
        select(ContentItem)
        .options(selectinload(ContentItem.media_file))
        .where(
            ContentItem.client_id == client_id,
            ContentItem.source == "telegram_group",
            ContentItem.status.in_(("draft", "ready", "ready_for_approval")),
        )
    )
    count = 0
    for item in result.scalars():
        if item.media_file and item.media_file.file_type == "image":
            item.telegram_excluded = True
            count += 1
    return count


async def _prefer_latest_video(db: AsyncSession, client_id: UUID) -> ContentItem | None:
    result = await db.execute(
        select(ContentItem)
        .join(MediaFile, ContentItem.media_file_id == MediaFile.id)
        .options(selectinload(ContentItem.media_file))
        .where(
            ContentItem.client_id == client_id,
            ContentItem.source == "telegram_group",
            ContentItem.status.in_(("draft", "ready", "ready_for_approval")),
            MediaFile.file_type == "video",
        )
        .order_by(ContentItem.created_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    if not latest:
        return None

    all_items = await db.execute(
        select(ContentItem)
        .where(
            ContentItem.client_id == client_id,
            ContentItem.source == "telegram_group",
            ContentItem.status.in_(("draft", "ready", "ready_for_approval")),
        )
    )
    for item in all_items.scalars():
        if item.id != latest.id:
            item.telegram_excluded = True
    return latest


def _build_context_block(item: ContentItem, client: Client) -> str:
    brand = brand_profile_from_client(client)
    lines = [
        f"Client: {client.company_name}",
        f"Content status: {item.status}",
        f"Excluded: {item.telegram_excluded}",
    ]
    if item.media_file:
        lines.append(f"Media type: {item.media_file.file_type}")
    for key in (
        "caption_short_ru", "caption_short_uz", "caption_short_en",
        "caption_long_ru", "caption_long_uz", "caption_long_en",
    ):
        val = getattr(item, key, None)
        if val:
            lines.append(f"{key}: {val[:400]}")
    if item.hashtags:
        lines.append(f"hashtags: {item.hashtags[:200]}")
    if item.internal_notes:
        lines.append(f"internal_notes: {item.internal_notes[:800]}")
    if brand.get("tone_of_voice"):
        lines.append(f"tone_of_voice: {brand['tone_of_voice']}")
    return "\n".join(lines)


async def _parse_instruction(
    instruction: str,
    item: ContentItem,
    client: Client,
    *,
    client_source: str = "",
) -> dict:
    if settings.DEMO_MODE:
        summary = "Демо: инструкция принята"
        patch: dict = {}
        lower = instruction.lower()
        if "делов" in lower or "formal" in lower:
            patch["caption_short_ru"] = "Качественный сервис для вашего бизнеса."
        if "эмодзи" in lower or "emoji" in lower:
            patch["caption_short_ru"] = re.sub(
                r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]+", "", item.caption_short_ru or ""
            ).strip()
        if "адрес" in lower or "address" in lower:
            patch["append_internal_notes"] = instruction.split(":", 1)[-1].strip()
        return {
            "summary": summary,
            "patch": patch,
            "exclude_photos": "фото" in lower and "не" in lower,
            "exclude_this_content": False,
            "prefer_latest_video": "видео" in lower and "последн" in lower,
        }

    _validate_api_key()
    openai = get_openai()
    context = _build_context_block(item, client)
    source_block = ""
    if client_source.strip():
        source_block = f"\nCLIENT SOURCE (publish from this — NOT the admin instruction):\n\"\"\"\n{client_source.strip()[:1500]}\n\"\"\"\n"
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}{source_block}\n\nADMIN INSTRUCTION (operator command — never publish verbatim):\n{instruction.strip()}"},
        ],
        temperature=0.35,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    return _extract_json(raw)


async def apply_group_instruction(
    db: AsyncSession,
    *,
    client: Client,
    content_item: ContentItem,
    instruction: str,
    admin_name: str,
    reply_to_message: dict | None = None,
) -> str:
    """Apply instruction to content; return summary for Telegram reply."""
    client_source = extract_client_text_from_reply(reply_to_message)
    if not client_source:
        client_source = extract_client_source_text(content_item.internal_notes)

    if client_source:
        set_client_source(content_item, client_source)
    set_admin_instruction(content_item, instruction)

    heuristic_summary = _apply_heuristic_task_edits(content_item, instruction)

    parsed = await _parse_instruction(
        instruction,
        content_item,
        client,
        client_source=client_source,
    )
    summary = (parsed.get("summary") or heuristic_summary or "Инструкция применена").strip()
    if heuristic_summary and parsed.get("summary"):
        summary = f"{heuristic_summary}; {parsed['summary']}".strip("; ")

    raw_patch = parsed.get("patch") or {}
    notes_patch = {
        k: raw_patch[k]
        for k in ("append_internal_notes", "replace_source_text")
        if raw_patch.get(k)
    }
    if notes_patch.get("replace_source_text"):
        r = notes_patch["replace_source_text"].strip()
        if is_admin_meta_instruction(r) or r == instruction.strip():
            notes_patch.pop("replace_source_text", None)
    if notes_patch:
        _apply_notes_patch(content_item, notes_patch)

    caption_patch = _filter_patch(raw_patch)
    if caption_patch:
        await ContentService.update(db, content_item.id, ContentUpdate(**caption_patch))
        content_item = await ContentService.get(db, content_item.id)

    if parsed.get("exclude_this_content"):
        content_item.telegram_excluded = True

    if parsed.get("exclude_photos"):
        await _exclude_photos_for_client(db, client.id)

    if parsed.get("prefer_latest_video"):
        latest = await _prefer_latest_video(db, client.id)
        if latest:
            content_item = latest

    if client_source and is_follow_client_instruction(instruction):
        from app.services.context_ai_service import build_context_signals
        from app.services.ai_service import generate_content

        context_signals = await build_context_signals(
            db, client=client, item=content_item, source_text=client_source,
        )
        generated = await generate_content(
            company_name=client.company_name,
            business_category=client.business_category,
            content_style=client.content_style,
            source_language=client.source_language or "zh",
            source_text=client_source,
            context_hint=build_generation_context_hint(instruction),
            client_notes=client.notes,
            brand_profile=brand_profile_from_client(client),
            context_signals=context_signals,
        )
        await ContentService.apply_generated(db, content_item.id, generated)
        content_item = await ContentService.get(db, content_item.id)
        set_client_source(content_item, client_source)
        set_admin_instruction(content_item, instruction)
    elif client_source and _wants_caption_refresh(instruction):
        from app.services.context_ai_service import build_context_signals
        from app.services.ai_service import generate_content

        context_signals = await build_context_signals(
            db, client=client, item=content_item, source_text=client_source,
        )
        generated = await generate_content(
            company_name=client.company_name,
            business_category=client.business_category,
            content_style=client.content_style,
            source_language=client.source_language or "zh",
            source_text=client_source,
            context_hint=build_generation_context_hint(instruction),
            client_notes=client.notes,
            brand_profile=brand_profile_from_client(client),
            context_signals=context_signals,
        )
        await ContentService.apply_generated(db, content_item.id, generated)
        content_item = await ContentService.get(db, content_item.id)
        set_client_source(content_item, client_source)
        set_admin_instruction(content_item, instruction)

    client.telegram_active_content_id = content_item.id

    _append_instruction_history(content_item, instruction, summary, admin_name, status="applied")
    await db.commit()

    logger.info(
        "[Instruction applied] content_id=%s client_source=%s instruction=%s",
        content_item.id,
        (client_source[:60] + "…") if len(client_source) > 60 else client_source,
        instruction[:120],
    )
    return summary


async def save_admin_note(
    db: AsyncSession,
    *,
    client: Client,
    text: str,
    admin_name: str,
    reply_to_message: dict | None,
    marker: str = "[Internal comment]:",
) -> tuple[bool, str]:
    """Save admin message as internal note only — never publish."""
    item = await _find_content_for_instruction(db, client.id, reply_to_message)
    if not item:
        return False, "⚠️ Не нашёл связанную задачу. Откройте сайт и выберите контент вручную."

    line = f"{marker} {text.strip()}"
    notes = item.internal_notes or ""
    item.internal_notes = f"{notes}\n{line}".strip() if notes else line
    _append_instruction_history(item, text, "Internal note saved", admin_name, status="internal note")
    await db.commit()
    logger.info("[Telegram Instruction] saved internal note content_id=%s", item.id)
    return True, "📝 Заметка сохранена."


async def resolve_and_apply_instruction(
    db: AsyncSession,
    *,
    client: Client,
    instruction: str,
    admin_name: str,
    reply_to_message: dict | None,
) -> tuple[bool, str]:
    """
    Find content and apply instruction.
    Returns (found, reply_text).
    """
    item = await _find_content_for_instruction(db, client.id, reply_to_message)
    if not item:
        logger.info(
            "[Telegram Instruction] no content for client_id=%s reply=%s",
            client.id,
            bool(reply_to_message),
        )
        return False, "⚠️ Не нашёл связанную задачу. Откройте сайт и выберите контент вручную."

    try:
        await apply_group_instruction(
            db,
            client=client,
            content_item=item,
            instruction=instruction,
            admin_name=admin_name,
            reply_to_message=reply_to_message,
        )
    except Exception as exc:
        logger.error("[Telegram Instruction] apply failed: %s", exc, exc_info=True)
        return False, "⚠️ Не удалось применить инструкцию. Попробуйте ещё раз или откройте сайт."

    return True, "✅ Инструкция применена."
