"""Smart Inbox v2 — AI analysis, grouping, and operator workspace helpers."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.telegram_buffer import TelegramGroupBufferMessage
from app.schemas.content import PLATFORMS
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.operator_common import CLIENT_SENDER_ROLES, parse_schedule_iso
from app.services.telegram_group_agent_service import (
    _catalogue_client_buffer,
    _load_buffer_entries,
    _scoped_client_entries_for_reply,
)
from app.services.telegram_instruction_service import _parse_schedule_datetime

logger = logging.getLogger(__name__)

GROUP_WINDOW = timedelta(minutes=10)
VALID_PRIORITIES = frozenset({"high", "medium", "low"})

_SMART_ANALYZE_SYSTEM = """\
You are an SMM operator inbox analyst. Summarize what the Telegram client wants and extract metadata.
Do NOT suggest auto-publishing or auto-approval.

Return ONLY JSON:
{
  "ai_summary": "1-3 sentences: what the client wants the operator to do",
  "priority": "high|medium|low",
  "suggested_publish_date": "ISO-8601 UTC datetime or null",
  "suggested_platforms": ["instagram", "telegram", ...],
  "detected_deadline": "human-readable deadline from message or null",
  "detected_offer": "promo/discount/offer text or null",
  "detected_language": "ru|uz|en|zh|mixed"
}

Rules:
- high: urgent words (срочно, urgent, asap, today, сегодня), deadline within 48h
- medium: normal post request with materials
- low: vague chat, question only, no clear publish intent
- suggested_platforms subset of: instagram, facebook, tiktok, telegram, linkedin
- detected_offer: only if discount/sale/promo/акция/% mentioned
"""


def _normalize_priority(raw: Any) -> str:
    key = str(raw or "medium").lower().strip()
    return key if key in VALID_PRIORITIES else "medium"


def _normalize_platforms(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for p in raw:
        key = str(p).lower().strip()
        if key in PLATFORMS and key not in out:
            out.append(key)
    return out


def _detect_language(text: str) -> str:
    lower = (text or "").lower()
    if not lower.strip():
        return "mixed"
    cyr = len(re.findall(r"[а-яё]", lower))
    lat = len(re.findall(r"[a-z]", lower))
    uz_markers = sum(1 for m in ("o'", "g'", "qiz", "uchun", "kerak") if m in lower)
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    scores = {"ru": cyr, "en": lat, "uz": uz_markers * 3, "zh": zh * 2}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "mixed"
    second = sorted(scores.values(), reverse=True)
    if len(second) > 1 and second[0] > 0 and second[1] > second[0] * 0.4:
        return "mixed"
    return best


def _heuristic_smart_analyze(
    *,
    texts: list[str],
    catalogue: dict[str, Any],
) -> dict[str, Any]:
    combined = "\n".join(t for t in texts if t).strip()
    lower = combined.lower()

    priority = "medium"
    if any(w in lower for w in ("срочно", "urgent", "asap", "сегодня", "today", "немедленно")):
        priority = "high"
    elif not combined and not (catalogue.get("photos") or catalogue.get("videos")):
        priority = "low"
    elif "?" in combined and not any(
        w in lower for w in ("опублик", "post", "пост", "вылож")
    ):
        priority = "low"

    offer: str | None = None
    for pat in (
        r"\d+\s*%", r"скид", r"discount", r"\bsale\b", r"акци", r"promo",
        r"распрод", r"бесплат",
    ):
        if re.search(pat, lower):
            offer = "Promo or discount mentioned in client message"
            break

    schedule_dt = _parse_schedule_datetime(combined)
    deadline: str | None = None
    suggested_publish: str | None = None
    if schedule_dt:
        suggested_publish = schedule_dt.astimezone(timezone.utc).isoformat()
        deadline = schedule_dt.strftime("%Y-%m-%d %H:%M UTC")

    platforms: list[str] = []
    if "telegram" in lower or "телеграм" in lower or "тг" in lower:
        platforms.append("telegram")
    if "instagram" in lower or "инстаграм" in lower or "инста" in lower:
        platforms.append("instagram")
    if "facebook" in lower or "фейсбук" in lower:
        platforms.append("facebook")
    if "tiktok" in lower or "тикток" in lower:
        platforms.append("tiktok")
    if "linkedin" in lower:
        platforms.append("linkedin")
    platforms = _normalize_platforms(platforms) or (["instagram"] if catalogue.get("photos") else [])

    photos = len(catalogue.get("photos") or [])
    videos = len(catalogue.get("videos") or [])
    if combined:
        summary = combined[:280] + ("…" if len(combined) > 280 else "")
    elif photos or videos:
        summary = f"Client sent {photos} photo(s) and {videos} video(s) for a post."
    else:
        summary = "Client message — review needed."

    return {
        "ai_summary": summary,
        "priority": priority,
        "suggested_publish_date": suggested_publish,
        "suggested_platforms": platforms,
        "detected_deadline": deadline,
        "detected_offer": offer,
        "detected_language": _detect_language(combined),
        "source": "fallback",
    }


async def _ai_smart_analyze(
    *,
    texts: list[str],
    catalogue: dict[str, Any],
    company: str,
) -> dict[str, Any]:
    _validate_api_key()
    openai = get_openai()
    user_block = (
        f"CLIENT: {company}\n"
        f"MESSAGES:\n{json.dumps(texts, ensure_ascii=False)}\n\n"
        f"PHOTOS:\n{json.dumps(catalogue['photos'], ensure_ascii=False)}\n\n"
        f"VIDEOS:\n{json.dumps(catalogue['videos'], ensure_ascii=False)}"
    )
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SMART_ANALYZE_SYSTEM},
            {"role": "user", "content": user_block},
        ],
        temperature=0.2,
        max_tokens=400,
        response_format={"type": "json_object"},
    )
    raw = _extract_json(response.choices[0].message.content or "{}")
    schedule = raw.get("suggested_publish_date")
    schedule_iso: str | None = None
    if schedule:
        dt = parse_schedule_iso(str(schedule))
        if dt:
            schedule_iso = dt.isoformat()
    if not schedule_iso:
        dt = _parse_schedule_datetime("\n".join(texts))
        if dt:
            schedule_iso = dt.isoformat()

    return {
        "ai_summary": (raw.get("ai_summary") or "Client request for review")[:500],
        "priority": _normalize_priority(raw.get("priority")),
        "suggested_publish_date": schedule_iso,
        "suggested_platforms": _normalize_platforms(raw.get("suggested_platforms")),
        "detected_deadline": (raw.get("detected_deadline") or None),
        "detected_offer": (raw.get("detected_offer") or None),
        "detected_language": str(raw.get("detected_language") or _detect_language("\n".join(texts)))[:10],
        "source": "ai",
    }


def cluster_client_entries(
    entries: list[TelegramGroupBufferMessage],
) -> list[list[TelegramGroupBufferMessage]]:
    by_client: dict[UUID, list[TelegramGroupBufferMessage]] = {}
    for entry in entries:
        if entry.sender_role not in CLIENT_SENDER_ROLES:
            continue
        by_client.setdefault(entry.client_id, []).append(entry)

    clusters: list[list[TelegramGroupBufferMessage]] = []
    for client_entries in by_client.values():
        sorted_entries = sorted(client_entries, key=lambda e: e.message_at)
        current: list[TelegramGroupBufferMessage] = []
        for entry in sorted_entries:
            if not current:
                current = [entry]
            elif entry.message_at - current[-1].message_at <= GROUP_WINDOW:
                current.append(entry)
            else:
                clusters.append(current)
                current = [entry]
        if current:
            clusters.append(current)
    return clusters


async def ensure_auto_groups(
    db: AsyncSession,
    entries: list[TelegramGroupBufferMessage],
) -> dict[UUID, list[TelegramGroupBufferMessage]]:
    """Assign grouped_task_id for bursts within 10 minutes (same client)."""
    group_map: dict[UUID, list[TelegramGroupBufferMessage]] = {}
    dirty = False

    for cluster in cluster_client_entries(entries):
        if len(cluster) < 2:
            continue
        manual_ids = {e.grouped_task_id for e in cluster if e.grouped_task_id}
        group_id = next(iter(manual_ids)) if len(manual_ids) == 1 else uuid.uuid4()
        if len(manual_ids) > 1:
            group_id = uuid.uuid4()

        for entry in cluster:
            if entry.grouped_task_id != group_id:
                entry.grouped_task_id = group_id
                dirty = True
        group_map[group_id] = sorted(cluster, key=lambda e: e.message_at)

    if dirty:
        await db.flush()
        await db.commit()

    for entry in entries:
        if entry.grouped_task_id and entry.grouped_task_id not in group_map:
            siblings = [e for e in entries if e.grouped_task_id == entry.grouped_task_id]
            if len(siblings) > 1:
                group_map[entry.grouped_task_id] = sorted(siblings, key=lambda e: e.message_at)

    return group_map


def primary_in_group(members: list[TelegramGroupBufferMessage]) -> TelegramGroupBufferMessage:
    return min(members, key=lambda e: e.message_at)


def parse_platforms_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return _normalize_platforms(data)
    except json.JSONDecodeError:
        pass
    return []


def smart_fields_from_entry(entry: TelegramGroupBufferMessage) -> dict[str, Any]:
    return {
        "ai_summary": entry.ai_summary,
        "priority": entry.priority,
        "suggested_publish_date": (
            entry.suggested_publish_date.isoformat()
            if entry.suggested_publish_date
            else None
        ),
        "suggested_platforms": parse_platforms_json(entry.suggested_platforms_json),
        "detected_deadline": entry.detected_deadline,
        "detected_offer": entry.detected_offer,
        "detected_language": entry.detected_language,
        "grouped_task_id": str(entry.grouped_task_id) if entry.grouped_task_id else None,
    }


def apply_smart_analysis(entry: TelegramGroupBufferMessage, data: dict[str, Any]) -> None:
    entry.ai_summary = (data.get("ai_summary") or "")[:500] or None
    entry.priority = _normalize_priority(data.get("priority"))
    schedule = data.get("suggested_publish_date")
    entry.suggested_publish_date = parse_schedule_iso(str(schedule)) if schedule else None
    platforms = _normalize_platforms(data.get("suggested_platforms"))
    entry.suggested_platforms_json = json.dumps(platforms) if platforms else None
    entry.detected_deadline = (data.get("detected_deadline") or None)
    if entry.detected_deadline:
        entry.detected_deadline = str(entry.detected_deadline)[:200]
    entry.detected_offer = (data.get("detected_offer") or None)
    if entry.detected_offer:
        entry.detected_offer = str(entry.detected_offer)[:300]
    entry.detected_language = (data.get("detected_language") or None)
    if entry.detected_language:
        entry.detected_language = str(entry.detected_language)[:10]
    entry.smart_analyzed_at = datetime.now(timezone.utc)


class OperatorSmartInboxService:
    @staticmethod
    async def _collect_group_context(
        db: AsyncSession,
        entry: TelegramGroupBufferMessage,
        all_entries: list[TelegramGroupBufferMessage] | None = None,
    ) -> tuple[list[TelegramGroupBufferMessage], list[str], dict[str, Any]]:
        members = [entry]
        if entry.grouped_task_id and all_entries:
            members = [
                e for e in all_entries
                if e.grouped_task_id == entry.grouped_task_id
            ] or [entry]
        members = sorted(members, key=lambda e: e.message_at)

        texts: list[str] = []
        catalogues: list[dict] = []
        for member in members:
            group_entries = await _load_buffer_entries(db, member.client_id, member.group_id)
            scope = _scoped_client_entries_for_reply(group_entries, member)
            catalogues.append(_catalogue_client_buffer(scope))
            t = (member.text or "").strip()
            if t:
                texts.append(t)
            for e in scope:
                if e.text and (e.text or "").strip() and e.text.strip() not in texts:
                    texts.append(e.text.strip())

        merged_catalogue = {
            "photos": [],
            "videos": [],
            "texts": [],
        }
        for cat in catalogues:
            merged_catalogue["photos"].extend(cat.get("photos") or [])
            merged_catalogue["videos"].extend(cat.get("videos") or [])
            merged_catalogue["texts"].extend(cat.get("texts") or [])

        return members, texts, merged_catalogue

    @staticmethod
    async def smart_analyze(
        db: AsyncSession,
        inbox_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        result = await db.execute(
            select(TelegramGroupBufferMessage)
            .options(selectinload(TelegramGroupBufferMessage.client))
            .where(TelegramGroupBufferMessage.id == inbox_id)
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Inbox item not found")
        if entry.sender_role not in CLIENT_SENDER_ROLES:
            raise HTTPException(status_code=400, detail="Not a client buffer message")

        if not force_refresh and entry.ai_summary and entry.smart_analyzed_at:
            logger.info("[Smart Inbox] analyze: inbox=%s cached=true", inbox_id)
            out = smart_fields_from_entry(entry)
            out["inbox_id"] = str(inbox_id)
            out["cached"] = True
            out["cached_at"] = entry.smart_analyzed_at.isoformat()
            out["source"] = "cached"
            return out

        all_result = await db.execute(
            select(TelegramGroupBufferMessage).where(
                TelegramGroupBufferMessage.sender_role.in_(tuple(CLIENT_SENDER_ROLES)),
            )
        )
        all_entries = list(all_result.scalars().all())
        await ensure_auto_groups(db, all_entries)

        members, texts, catalogue = await OperatorSmartInboxService._collect_group_context(
            db, entry, all_entries,
        )
        company = entry.client.company_name if entry.client else "Unknown"

        if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
            analysis = _heuristic_smart_analyze(texts=texts, catalogue=catalogue)
            logger.info("[Smart Inbox] fallback: inbox=%s priority=%s", inbox_id, analysis["priority"])
        else:
            try:
                analysis = await _ai_smart_analyze(
                    texts=texts, catalogue=catalogue, company=company,
                )
                logger.info("[Smart Inbox] analyze: inbox=%s priority=%s source=ai", inbox_id, analysis["priority"])
            except Exception as exc:
                logger.warning("[Smart Inbox] fallback: inbox=%s error=%s", inbox_id, exc)
                analysis = _heuristic_smart_analyze(texts=texts, catalogue=catalogue)

        for member in members:
            apply_smart_analysis(member, analysis)

        await db.commit()
        await db.refresh(entry)

        out = smart_fields_from_entry(entry)
        out["inbox_id"] = str(inbox_id)
        out["cached"] = True
        out["cached_at"] = entry.smart_analyzed_at.isoformat() if entry.smart_analyzed_at else None
        out["source"] = analysis.get("source")
        return out

    @staticmethod
    async def group_inbox_items(
        db: AsyncSession,
        inbox_ids: list[UUID],
    ) -> dict[str, Any]:
        if len(inbox_ids) < 2:
            raise HTTPException(status_code=400, detail="Select at least 2 inbox items to group")

        result = await db.execute(
            select(TelegramGroupBufferMessage)
            .options(selectinload(TelegramGroupBufferMessage.client))
            .where(TelegramGroupBufferMessage.id.in_(inbox_ids))
        )
        entries = list(result.scalars().all())
        if len(entries) != len(inbox_ids):
            raise HTTPException(status_code=404, detail="One or more inbox items not found")

        client_ids = {e.client_id for e in entries}
        if len(client_ids) > 1:
            raise HTTPException(status_code=400, detail="All items must belong to the same client")

        group_id = uuid.uuid4()
        for entry in entries:
            entry.grouped_task_id = group_id

        primary = primary_in_group(entries)
        await db.commit()

        logger.info(
            "[Smart Inbox] grouped: task=%s items=%d primary=%s",
            group_id,
            len(entries),
            primary.id,
        )
        return {
            "ok": True,
            "message": f"Grouped {len(entries)} inbox items",
            "grouped_task_id": str(group_id),
            "primary_inbox_id": primary.id,
            "inbox_ids": [str(e.id) for e in entries],
        }
