"""Client AI Knowledge Base — CRUD, AI summarize, prompt integration."""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.client_knowledge_base import ClientKnowledgeBaseEntry
from app.models.content import ContentItem
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.schemas.client_knowledge_base import (
    ClientKnowledgeBaseEntryCreate,
    ClientKnowledgeBaseEntryUpdate,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_service import ClientService
from app.services.operator_common import CLIENT_SENDER_ROLES

logger = logging.getLogger(__name__)

KB_SECTIONS = frozenset({
    "company_profile",
    "products_services",
    "pricing",
    "target_audience",
    "tone_style",
    "faq",
    "past_campaigns",
    "do_not_say",
    "competitors",
    "notes",
})
KB_SOURCES = frozenset({"manual", "telegram", "content", "ai_summary"})
KB_IMPORTANCE = frozenset({"low", "medium", "high"})
IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}

_SECTION_LABELS = {
    "company_profile": "Company profile",
    "products_services": "Products & services",
    "pricing": "Pricing",
    "target_audience": "Target audience",
    "tone_style": "Tone & style",
    "faq": "FAQ",
    "past_campaigns": "Past campaigns",
    "do_not_say": "Do not say",
    "competitors": "Competitors",
    "notes": "Notes",
}

_SUMMARIZE_SYSTEM = """\
You build a structured client knowledge base for an SMM team.
The knowledge base SUPPLEMENTS the existing brand profile — never contradict it.

Return ONLY JSON:
{
  "entries": [
    {
      "section": "company_profile|products_services|pricing|target_audience|tone_style|faq|past_campaigns|do_not_say|competitors|notes",
      "title": "short label",
      "content": "2-6 sentences of useful facts for AI content generation",
      "importance": "low|medium|high"
    }
  ]
}

Rules:
- Include only sections with meaningful information from the inputs
- do_not_say: phrases/topics to avoid (from words_to_avoid, client messages, etc.)
- tone_style: voice, style, language preferences
- past_campaigns: themes from recent published/approved content if visible
- Be factual — do not invent products, prices, or claims not supported by inputs
- Skip empty sections rather than padding
"""


def _serialize(entry: ClientKnowledgeBaseEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "client_id": entry.client_id,
        "section": entry.section,
        "title": entry.title,
        "content": entry.content,
        "source": entry.source,
        "importance": entry.importance,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def _validate_section(section: str) -> None:
    if section not in KB_SECTIONS:
        raise HTTPException(status_code=400, detail=f"Invalid section: {section}")


def _validate_source(source: str) -> None:
    if source not in KB_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source: {source}")


def _validate_importance(importance: str) -> None:
    if importance not in KB_IMPORTANCE:
        raise HTTPException(status_code=400, detail=f"Invalid importance: {importance}")


async def _gather_summarize_context(db: AsyncSession, client: Client) -> dict[str, Any]:
    profile = brand_profile_from_client(client)

    content_result = await db.execute(
        select(ContentItem)
        .where(ContentItem.client_id == client.id)
        .order_by(ContentItem.created_at.desc())
        .limit(15)
    )
    content_rows = list(content_result.scalars().all())
    recent_content: list[dict[str, str]] = []
    for item in content_rows:
        caption = (
            (item.caption_short_ru or item.caption_long_ru or "")
            or (item.caption_short_en or item.caption_long_en or "")
            or (item.caption_short_uz or item.caption_long_uz or "")
        ).strip()
        recent_content.append({
            "status": item.status,
            "source": item.source,
            "platforms": ",".join(item.platforms or []),
            "caption": caption[:300],
            "notes": (item.internal_notes or "")[:200],
        })

    inbox_result = await db.execute(
        select(TelegramGroupBufferMessage)
        .where(
            TelegramGroupBufferMessage.client_id == client.id,
            TelegramGroupBufferMessage.sender_role.in_(tuple(CLIENT_SENDER_ROLES)),
        )
        .order_by(TelegramGroupBufferMessage.message_at.desc())
        .limit(25)
    )
    inbox_rows = list(inbox_result.scalars().all())
    inbox_history = [
        {
            "type": row.message_type,
            "text": (row.text or "")[:250],
            "at": row.message_at.isoformat() if row.message_at else None,
        }
        for row in inbox_rows
        if row.text and row.text.strip()
    ]

    return {
        "profile": profile,
        "client_notes": (client.notes or "").strip(),
        "business_category": client.business_category,
        "content_style": client.content_style,
        "recent_content": recent_content,
        "inbox_history": inbox_history,
    }


def _heuristic_summarize(client: Client, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    profile = ctx.get("profile") or {}
    entries: list[dict[str, Any]] = []

    if profile.get("business_description") or profile.get("brand_name"):
        entries.append({
            "section": "company_profile",
            "title": "Company overview",
            "content": (
                f"{profile.get('brand_name') or client.company_name}: "
                f"{(profile.get('business_description') or client.notes or client.business_category).strip()}"
            )[:800],
            "importance": "high",
        })
    if profile.get("products_services"):
        entries.append({
            "section": "products_services",
            "title": "Offerings",
            "content": profile["products_services"].strip()[:800],
            "importance": "high",
        })
    if profile.get("target_audience"):
        entries.append({
            "section": "target_audience",
            "title": "Audience",
            "content": profile["target_audience"].strip()[:800],
            "importance": "medium",
        })
    tone = profile.get("tone_of_voice") or client.content_style
    entries.append({
        "section": "tone_style",
        "title": "Voice & style",
        "content": f"Tone: {tone}. Content style: {client.content_style}.",
        "importance": "medium",
    })
    if profile.get("words_to_avoid"):
        entries.append({
            "section": "do_not_say",
            "title": "Avoid",
            "content": profile["words_to_avoid"].strip()[:800],
            "importance": "high",
        })

    themes: list[str] = []
    for row in ctx.get("recent_content") or []:
        cap = (row.get("caption") or "").strip()
        if cap and cap not in themes:
            themes.append(cap[:120])
        if len(themes) >= 5:
            break
    if themes:
        entries.append({
            "section": "past_campaigns",
            "title": "Recent post themes",
            "content": "Recent content themes: " + "; ".join(themes),
            "importance": "low",
        })

    inbox = ctx.get("inbox_history") or []
    if inbox:
        snippets = [m["text"][:100] for m in inbox[:5]]
        entries.append({
            "section": "notes",
            "title": "Client Telegram snippets",
            "content": "Recent client messages: " + " | ".join(snippets),
            "importance": "low",
        })

    return entries


async def _ai_summarize_entries(client: Client, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        return _heuristic_summarize(client, ctx)

    _validate_api_key()
    openai = get_openai()
    user_block = json.dumps(ctx, ensure_ascii=False, default=str)
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SUMMARIZE_SYSTEM},
            {"role": "user", "content": user_block[:12000]},
        ],
        temperature=0.3,
        max_tokens=2500,
        response_format={"type": "json_object"},
    )
    raw = _extract_json(response.choices[0].message.content or "{}")
    items = raw.get("entries") or []
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        section = str(row.get("section") or "").strip()
        if section not in KB_SECTIONS:
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        importance = str(row.get("importance") or "medium").lower()
        if importance not in KB_IMPORTANCE:
            importance = "medium"
        out.append({
            "section": section,
            "title": str(row.get("title") or _SECTION_LABELS.get(section, section))[:255],
            "content": content[:4000],
            "importance": importance,
        })
    return out or _heuristic_summarize(client, ctx)


class ClientKnowledgeBaseService:
    @staticmethod
    async def list_entries(db: AsyncSession, client_id: UUID) -> dict[str, Any]:
        await ClientService.get(db, client_id)
        result = await db.execute(
            select(ClientKnowledgeBaseEntry)
            .where(ClientKnowledgeBaseEntry.client_id == client_id)
        )
        items = list(result.scalars().all())
        items.sort(
            key=lambda e: (
                e.section,
                IMPORTANCE_ORDER.get(e.importance, 9),
                -(e.updated_at.timestamp() if e.updated_at else 0),
            ),
        )
        return {"items": [_serialize(e) for e in items], "total": len(items)}

    @staticmethod
    async def create_entry(
        db: AsyncSession,
        client_id: UUID,
        data: ClientKnowledgeBaseEntryCreate,
    ) -> dict[str, Any]:
        await ClientService.get(db, client_id)
        _validate_section(data.section)
        _validate_source(data.source)
        _validate_importance(data.importance)
        entry = ClientKnowledgeBaseEntry(
            client_id=client_id,
            section=data.section,
            title=data.title.strip(),
            content=data.content.strip(),
            source=data.source,
            importance=data.importance,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return _serialize(entry)

    @staticmethod
    async def update_entry(
        db: AsyncSession,
        client_id: UUID,
        kb_id: UUID,
        data: ClientKnowledgeBaseEntryUpdate,
    ) -> dict[str, Any]:
        entry = await ClientKnowledgeBaseService._get_entry(db, client_id, kb_id)
        if data.section is not None:
            _validate_section(data.section)
            entry.section = data.section
        if data.title is not None:
            entry.title = data.title.strip()
        if data.content is not None:
            entry.content = data.content.strip()
        if data.source is not None:
            _validate_source(data.source)
            entry.source = data.source
        if data.importance is not None:
            _validate_importance(data.importance)
            entry.importance = data.importance
        await db.commit()
        await db.refresh(entry)
        return _serialize(entry)

    @staticmethod
    async def delete_entry(db: AsyncSession, client_id: UUID, kb_id: UUID) -> None:
        entry = await ClientKnowledgeBaseService._get_entry(db, client_id, kb_id)
        await db.delete(entry)
        await db.commit()

    @staticmethod
    async def _get_entry(
        db: AsyncSession,
        client_id: UUID,
        kb_id: UUID,
    ) -> ClientKnowledgeBaseEntry:
        result = await db.execute(
            select(ClientKnowledgeBaseEntry).where(
                ClientKnowledgeBaseEntry.id == kb_id,
                ClientKnowledgeBaseEntry.client_id == client_id,
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Knowledge base entry not found")
        return entry

    @staticmethod
    async def ai_summarize(db: AsyncSession, client_id: UUID) -> dict[str, Any]:
        client = await ClientService.get(db, client_id)
        ctx = await _gather_summarize_context(db, client)
        proposed = await _ai_summarize_entries(client, ctx)

        created = 0
        updated = 0
        saved: list[ClientKnowledgeBaseEntry] = []

        for row in proposed:
            section = row["section"]
            result = await db.execute(
                select(ClientKnowledgeBaseEntry).where(
                    ClientKnowledgeBaseEntry.client_id == client_id,
                    ClientKnowledgeBaseEntry.section == section,
                    ClientKnowledgeBaseEntry.source == "ai_summary",
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.title = row["title"]
                existing.content = row["content"]
                existing.importance = row["importance"]
                saved.append(existing)
                updated += 1
            else:
                entry = ClientKnowledgeBaseEntry(
                    client_id=client_id,
                    section=section,
                    title=row["title"],
                    content=row["content"],
                    source="ai_summary",
                    importance=row["importance"],
                )
                db.add(entry)
                saved.append(entry)
                created += 1

        await db.commit()
        for entry in saved:
            await db.refresh(entry)

        logger.info(
            "[Client KB] ai summarized: client=%s created=%s updated=%s",
            client_id,
            created,
            updated,
        )
        return {
            "ok": True,
            "message": f"Knowledge base updated ({created} created, {updated} updated)",
            "created": created,
            "updated": updated,
            "items": [_serialize(e) for e in saved],
        }

    @staticmethod
    async def build_prompt_block(
        db: AsyncSession,
        client_id: UUID,
        *,
        max_chars: int = 4000,
        context: str = "generation",
    ) -> str:
        result = await db.execute(
            select(ClientKnowledgeBaseEntry)
            .where(ClientKnowledgeBaseEntry.client_id == client_id)
            .order_by(ClientKnowledgeBaseEntry.importance.asc())
        )
        entries = list(result.scalars().all())
        if not entries:
            return ""

        entries.sort(key=lambda e: (IMPORTANCE_ORDER.get(e.importance, 9), e.section))

        lines = [
            "CLIENT KNOWLEDGE BASE (supplements brand profile — follow do_not_say strictly):",
        ]
        total = len(lines[0])
        used = 0
        for entry in entries:
            label = _SECTION_LABELS.get(entry.section, entry.section)
            line = f"[{label}] {entry.title} ({entry.importance}): {entry.content.strip()}"
            if total + len(line) + 1 > max_chars:
                break
            lines.append(line)
            total += len(line) + 1
            used += 1

        block = "\n".join(lines)
        logger.info(
            "[Client KB] loaded: client=%s entries=%s context=%s",
            client_id,
            len(entries),
            context,
        )
        logger.info(
            "[Client KB] used in prompt: client=%s entries=%s chars=%s context=%s",
            client_id,
            used,
            len(block),
            context,
        )
        return block
