"""Communication Hub — contacts, threads, messages, CRM linking, AI summaries."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit
from app.models.client import Client
from app.models.communication import (
    CommunicationContact,
    CommunicationMessage,
    CommunicationThread,
)
from app.models.crm_lead import CrmLead
from app.models.partner import Partner
from app.schemas.communication import (
    COMMUNICATION_CHANNELS,
    MESSAGE_DIRECTIONS,
    THREAD_STATUSES,
    CommunicationContactCreate,
    CommunicationMessageCreate,
    CommunicationThreadCreate,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.crm_service import CrmService

logger = logging.getLogger(__name__)

HUB_MARKER = "[Communication Hub]"

_AI_SUMMARY_SYSTEM = """\
You analyze buyer/client communication threads for a B2B export sales team.
Advisory only — never auto-send messages or auto-create outreach.

Return ONLY JSON:
{
  "summary": "2-4 sentence thread summary",
  "next_action": "imperative next step for operator",
  "sentiment": "positive|neutral|negative|mixed",
  "possible_lead_interest": "product/service interest inferred from messages"
}

Rules:
- Base analysis only on provided messages
- Do not invent contact details or commitments
- next_action is for manual operator follow-up only
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _preview(text: str | None, limit: int = 120) -> str | None:
    if not text:
        return None
    t = text.strip()
    if not t:
        return None
    return t[:limit] + ("…" if len(t) > limit else "")


def _serialize_contact(
    contact: CommunicationContact,
    *,
    client_name: str | None = None,
    lead_name: str | None = None,
    partner_name: str | None = None,
    thread_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": contact.id,
        "client_id": contact.client_id,
        "lead_id": contact.lead_id,
        "partner_id": contact.partner_id,
        "name": contact.name,
        "company": contact.company,
        "role": contact.role,
        "phone": contact.phone,
        "telegram": contact.telegram,
        "whatsapp": contact.whatsapp,
        "wechat": contact.wechat,
        "wechat_id": contact.wechat_id,
        "wecom_id": contact.wecom_id,
        "qr_code_url": contact.qr_code_url,
        "email": contact.email,
        "country": contact.country,
        "language": contact.language,
        "preferred_language": contact.preferred_language,
        "notes": contact.notes,
        "client_name": client_name,
        "lead_name": lead_name,
        "partner_name": partner_name,
        "thread_count": thread_count,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def _serialize_thread(
    thread: CommunicationThread,
    *,
    contact_name: str | None = None,
    client_name: str | None = None,
    lead_name: str | None = None,
    message_count: int = 0,
    last_message_preview: str | None = None,
) -> dict[str, Any]:
    return {
        "id": thread.id,
        "contact_id": thread.contact_id,
        "client_id": thread.client_id,
        "lead_id": thread.lead_id,
        "partner_id": thread.partner_id,
        "channel": thread.channel,
        "external_thread_id": thread.external_thread_id,
        "external_contact_id": thread.external_contact_id,
        "last_manual_sync_at": thread.last_manual_sync_at,
        "title": thread.title,
        "status": thread.status,
        "last_message_at": thread.last_message_at,
        "contact_name": contact_name,
        "client_name": client_name,
        "lead_name": lead_name,
        "deal_id": thread.deal_id,
        "message_count": message_count,
        "last_message_preview": last_message_preview,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
    }


def _serialize_message(msg: CommunicationMessage) -> dict[str, Any]:
    return {
        "id": msg.id,
        "thread_id": msg.thread_id,
        "direction": msg.direction,
        "sender_name": msg.sender_name,
        "message_text": msg.message_text,
        "attachments_json": msg.attachments_json,
        "original_language": msg.original_language,
        "translated_text": msg.translated_text,
        "ai_summary": msg.ai_summary,
        "copied_at": msg.copied_at,
        "manual_sent_at": msg.manual_sent_at,
        "created_at": msg.created_at,
    }


async def _client_name_map(db: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    r = await db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids)))
    return {row[0]: row[1] for row in r.all()}


async def _lead_name_map(db: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    r = await db.execute(select(CrmLead.id, CrmLead.name).where(CrmLead.id.in_(ids)))
    return {row[0]: row[1] for row in r.all()}


async def _partner_name_map(db: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    r = await db.execute(select(Partner.id, Partner.name).where(Partner.id.in_(ids)))
    return {row[0]: row[1] for row in r.all()}


def _heuristic_ai_summary(messages: list[CommunicationMessage]) -> dict[str, str]:
    texts = [m.message_text.strip() for m in messages if m.message_text.strip()][-10:]
    combined = " ".join(texts)[:800] or "No messages yet."
    return {
        "summary": combined[:400],
        "next_action": "Review thread and respond manually via the appropriate channel.",
        "sentiment": "neutral",
        "possible_lead_interest": "Review product catalog alignment with message content.",
    }


class CommunicationHubService:
    @staticmethod
    async def list_contacts(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        lead_id: UUID | None = None,
        partner_id: UUID | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(CommunicationContact)
        count_q = select(func.count()).select_from(CommunicationContact)
        if client_id:
            q = q.where(CommunicationContact.client_id == client_id)
            count_q = count_q.where(CommunicationContact.client_id == client_id)
        if lead_id:
            q = q.where(CommunicationContact.lead_id == lead_id)
            count_q = count_q.where(CommunicationContact.lead_id == lead_id)
        if partner_id:
            q = q.where(CommunicationContact.partner_id == partner_id)
            count_q = count_q.where(CommunicationContact.partner_id == partner_id)
        if search:
            like = f"%{search.strip()}%"
            filt = (
                CommunicationContact.name.ilike(like)
                | CommunicationContact.company.ilike(like)
                | CommunicationContact.email.ilike(like)
            )
            q = q.where(filt)
            count_q = count_q.where(filt)

        total_r = await db.execute(count_q)
        total = total_r.scalar_one()
        r = await db.execute(
            q.order_by(CommunicationContact.updated_at.desc()).offset(skip).limit(limit)
        )
        contacts = list(r.scalars().all())

        contact_ids = [c.id for c in contacts]
        thread_counts: dict[UUID, int] = {}
        if contact_ids:
            tc_r = await db.execute(
                select(CommunicationThread.contact_id, func.count())
                .where(CommunicationThread.contact_id.in_(contact_ids))
                .group_by(CommunicationThread.contact_id)
            )
            thread_counts = {row[0]: row[1] for row in tc_r.all()}

        client_names = await _client_name_map(db, {c.client_id for c in contacts if c.client_id})
        lead_names = await _lead_name_map(db, {c.lead_id for c in contacts if c.lead_id})
        partner_names = await _partner_name_map(db, {c.partner_id for c in contacts if c.partner_id})

        items = [
            _serialize_contact(
                c,
                client_name=client_names.get(c.client_id) if c.client_id else None,
                lead_name=lead_names.get(c.lead_id) if c.lead_id else None,
                partner_name=partner_names.get(c.partner_id) if c.partner_id else None,
                thread_count=thread_counts.get(c.id, 0),
            )
            for c in contacts
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def get_contact(db: AsyncSession, contact_id: UUID) -> dict[str, Any]:
        r = await db.execute(select(CommunicationContact).where(CommunicationContact.id == contact_id))
        contact = r.scalar_one_or_none()
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")

        tc_r = await db.execute(
            select(func.count()).select_from(CommunicationThread).where(
                CommunicationThread.contact_id == contact_id
            )
        )
        thread_count = tc_r.scalar_one()

        client_name = None
        if contact.client_id:
            cm = await _client_name_map(db, {contact.client_id})
            client_name = cm.get(contact.client_id)
        lead_name = None
        if contact.lead_id:
            lm = await _lead_name_map(db, {contact.lead_id})
            lead_name = lm.get(contact.lead_id)
        partner_name = None
        if contact.partner_id:
            pm = await _partner_name_map(db, {contact.partner_id})
            partner_name = pm.get(contact.partner_id)

        threads = await CommunicationHubService.list_threads(db, contact_id=contact_id, limit=MAX_LIMIT)
        return {
            **_serialize_contact(
                contact,
                client_name=client_name,
                lead_name=lead_name,
                partner_name=partner_name,
                thread_count=thread_count,
            ),
            "threads": threads["items"],
        }

    @staticmethod
    async def create_contact(db: AsyncSession, data: CommunicationContactCreate) -> dict[str, Any]:
        contact = CommunicationContact(**data.model_dump())
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        logger.info("%s contact created: id=%s name=%s", HUB_MARKER, contact.id, contact.name)
        return _serialize_contact(contact)

    @staticmethod
    async def list_threads(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        contact_id: UUID | None = None,
        lead_id: UUID | None = None,
        channel: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(CommunicationThread)
        count_q = select(func.count()).select_from(CommunicationThread)
        if client_id:
            q = q.where(CommunicationThread.client_id == client_id)
            count_q = count_q.where(CommunicationThread.client_id == client_id)
        if contact_id:
            q = q.where(CommunicationThread.contact_id == contact_id)
            count_q = count_q.where(CommunicationThread.contact_id == contact_id)
        if lead_id:
            q = q.where(CommunicationThread.lead_id == lead_id)
            count_q = count_q.where(CommunicationThread.lead_id == lead_id)
        if channel:
            if channel not in COMMUNICATION_CHANNELS:
                raise HTTPException(status_code=400, detail="Invalid channel")
            q = q.where(CommunicationThread.channel == channel)
            count_q = count_q.where(CommunicationThread.channel == channel)
        if status:
            if status not in THREAD_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid status")
            q = q.where(CommunicationThread.status == status)
            count_q = count_q.where(CommunicationThread.status == status)

        total_r = await db.execute(count_q)
        total = total_r.scalar_one()
        r = await db.execute(
            q.order_by(
                CommunicationThread.last_message_at.desc().nullslast(),
                CommunicationThread.updated_at.desc(),
            ).offset(skip).limit(limit)
        )
        threads = list(r.scalars().all())

        contact_ids = {t.contact_id for t in threads}
        contact_names: dict[UUID, str] = {}
        if contact_ids:
            cn_r = await db.execute(
                select(CommunicationContact.id, CommunicationContact.name).where(
                    CommunicationContact.id.in_(contact_ids)
                )
            )
            contact_names = {row[0]: row[1] for row in cn_r.all()}

        client_names = await _client_name_map(db, {t.client_id for t in threads if t.client_id})
        lead_names = await _lead_name_map(db, {t.lead_id for t in threads if t.lead_id})

        thread_ids = [t.id for t in threads]
        msg_stats: dict[UUID, tuple[int, str | None]] = {}
        if thread_ids:
            ms_r = await db.execute(
                select(
                    CommunicationMessage.thread_id,
                    func.count(),
                    func.max(CommunicationMessage.message_text),
                )
                .where(CommunicationMessage.thread_id.in_(thread_ids))
                .group_by(CommunicationMessage.thread_id)
            )
            for tid, cnt, last_text in ms_r.all():
                msg_stats[tid] = (cnt, _preview(last_text))

        items = [
            _serialize_thread(
                t,
                contact_name=contact_names.get(t.contact_id),
                client_name=client_names.get(t.client_id) if t.client_id else None,
                lead_name=lead_names.get(t.lead_id) if t.lead_id else None,
                message_count=msg_stats.get(t.id, (0, None))[0],
                last_message_preview=msg_stats.get(t.id, (0, None))[1],
            )
            for t in threads
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def create_thread(db: AsyncSession, data: CommunicationThreadCreate) -> dict[str, Any]:
        if data.channel not in COMMUNICATION_CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel")
        if data.status not in THREAD_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")

        cr = await db.execute(
            select(CommunicationContact).where(CommunicationContact.id == data.contact_id)
        )
        if not cr.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Contact not found")

        thread = CommunicationThread(**data.model_dump())
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
        logger.info(
            "%s thread created: id=%s channel=%s contact=%s",
            HUB_MARKER, thread.id, thread.channel, thread.contact_id,
        )
        return _serialize_thread(thread)

    @staticmethod
    async def get_thread(db: AsyncSession, thread_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(CommunicationThread)
            .options(
                selectinload(CommunicationThread.messages),
                selectinload(CommunicationThread.contact),
            )
            .where(CommunicationThread.id == thread_id)
        )
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        client_name = None
        if thread.client_id:
            cm = await _client_name_map(db, {thread.client_id})
            client_name = cm.get(thread.client_id)
        lead_name = None
        if thread.lead_id:
            lm = await _lead_name_map(db, {thread.lead_id})
            lead_name = lm.get(thread.lead_id)

        contact_data = None
        if thread.contact:
            c = thread.contact
            contact_data = _serialize_contact(c)

        messages = [_serialize_message(m) for m in thread.messages]
        last_preview = _preview(messages[-1]["message_text"]) if messages else None

        from app.services.outreach_workflow_service import OutreachWorkflowService
        linked_outreach = await OutreachWorkflowService.linked_outreach_for_thread(db, thread_id)

        return {
            **_serialize_thread(
                thread,
                contact_name=thread.contact.name if thread.contact else None,
                client_name=client_name,
                lead_name=lead_name,
                message_count=len(messages),
                last_message_preview=last_preview,
            ),
            "messages": messages,
            "contact": contact_data,
            "linked_outreach": linked_outreach,
        }

    @staticmethod
    async def add_message(
        db: AsyncSession,
        thread_id: UUID,
        data: CommunicationMessageCreate,
    ) -> dict[str, Any]:
        if data.direction not in MESSAGE_DIRECTIONS:
            raise HTTPException(status_code=400, detail="Invalid direction")

        r = await db.execute(select(CommunicationThread).where(CommunicationThread.id == thread_id))
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        msg = CommunicationMessage(
            thread_id=thread_id,
            direction=data.direction,
            sender_name=data.sender_name,
            message_text=data.message_text,
            attachments_json=data.attachments_json,
        )
        db.add(msg)
        now = _utcnow()
        thread.last_message_at = now
        thread.updated_at = now
        if data.direction == "inbound" and thread.status == "closed":
            thread.status = "open"
        await db.flush()

        activity_synced = False
        if thread.lead_id:
            try:
                from app.services.communication_crm_service import CommunicationCrmService
                activity_synced = await CommunicationCrmService.sync_message_activity(db, thread, msg)
            except Exception as exc:
                logger.debug("%s activity sync skipped: %s", HUB_MARKER, exc)

        await db.commit()
        await db.refresh(msg)
        logger.info(
            "%s message stored: thread=%s direction=%s",
            HUB_MARKER, thread_id, data.direction,
        )
        result = _serialize_message(msg)
        result["activity_synced"] = activity_synced
        return result

    @staticmethod
    async def ai_summary(db: AsyncSession, thread_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .where(CommunicationThread.id == thread_id)
        )
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        messages = thread.messages[-30:]
        if not messages:
            raise HTTPException(status_code=400, detail="Thread has no messages to summarize")

        transcript = "\n".join(
            f"[{m.direction}] {m.sender_name}: {m.message_text[:500]}"
            for m in messages
        )
        demo_mode = False
        result: dict[str, str] = {}
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _AI_SUMMARY_SYSTEM},
                    {"role": "user", "content": f"THREAD: {thread.title}\nCHANNEL: {thread.channel}\n\n{transcript}"},
                ],
                temperature=0.4,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            result = {
                "summary": str(parsed.get("summary") or "")[:2000],
                "next_action": str(parsed.get("next_action") or "")[:500],
                "sentiment": str(parsed.get("sentiment") or "neutral")[:50],
                "possible_lead_interest": str(parsed.get("possible_lead_interest") or "")[:500],
            }
            if not result["summary"]:
                raise ValueError("empty summary")
        except Exception as exc:
            demo_mode = True
            logger.info("%s ai summary fallback: %s", HUB_MARKER, exc)
            result = _heuristic_ai_summary(messages)

        logger.info("%s ai summary: thread=%s demo=%s", HUB_MARKER, thread_id, demo_mode)
        return {**result, "demo_mode": demo_mode}

    @staticmethod
    async def link_lead(db: AsyncSession, thread_id: UUID, lead_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.contact))
            .where(CommunicationThread.id == thread_id)
        )
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        lead = await CrmService.get_lead(db, lead_id)
        thread.lead_id = lead_id
        if thread.contact and not thread.contact.lead_id:
            thread.contact.lead_id = lead_id
        if not thread.client_id:
            thread.client_id = lead["client_id"]
        await db.commit()
        logger.info("%s lead linked: thread=%s lead=%s", HUB_MARKER, thread_id, lead_id)
        return {"thread_id": thread_id, "lead_id": lead_id, "lead_name": lead["name"]}

    @staticmethod
    async def create_lead_from_thread(db: AsyncSession, thread_id: UUID, data=None) -> dict[str, Any]:
        from app.services.communication_crm_service import CommunicationCrmService
        return await CommunicationCrmService.create_lead_from_thread(db, thread_id, data)

    @staticmethod
    async def store_telegram_group_message(
        db: AsyncSession,
        *,
        client: Client,
        chat_id: int,
        chat_title: str,
        message: dict,
        sender_name: str,
        telegram_user_id: int,
    ) -> dict[str, Any] | None:
        """Copy Telegram group intake message into Communication Hub (non-blocking)."""
        text = (message.get("text") or message.get("caption") or "").strip()
        has_media = bool(
            message.get("photo") or message.get("video")
            or message.get("document") or message.get("video_note")
        )
        if not text and not has_media:
            return None

        user = message.get("from") or {}
        username = user.get("username")
        telegram_handle = f"@{username}" if username else str(telegram_user_id)
        external_id = str(chat_id)

        contact_name = sender_name.strip() or chat_title or client.company_name
        cr = await db.execute(
            select(CommunicationContact).where(
                CommunicationContact.client_id == client.id,
                CommunicationContact.telegram == telegram_handle,
            ).limit(1)
        )
        contact = cr.scalar_one_or_none()
        if not contact:
            contact = CommunicationContact(
                client_id=client.id,
                name=contact_name,
                company=client.company_name,
                telegram=telegram_handle,
                language=client.source_language,
            )
            db.add(contact)
            await db.flush()

        tr = await db.execute(
            select(CommunicationThread).where(
                CommunicationThread.contact_id == contact.id,
                CommunicationThread.channel == "telegram",
                CommunicationThread.external_thread_id == external_id,
            ).limit(1)
        )
        thread = tr.scalar_one_or_none()
        if not thread:
            thread = CommunicationThread(
                contact_id=contact.id,
                client_id=client.id,
                channel="telegram",
                external_thread_id=external_id,
                title=chat_title or f"Telegram — {client.company_name}",
                status="open",
            )
            db.add(thread)
            await db.flush()
            logger.info(
                "%s thread created: id=%s channel=telegram client=%s",
                HUB_MARKER, thread.id, client.id,
            )

        msg_text = text or "[media attachment]"
        attachments = None
        if has_media:
            attachments = [{"type": "telegram_media", "message_id": message.get("message_id")}]

        msg = CommunicationMessage(
            thread_id=thread.id,
            direction="inbound",
            sender_name=contact_name,
            message_text=msg_text,
            attachments_json=attachments,
        )
        db.add(msg)
        now = _utcnow()
        thread.last_message_at = now
        thread.updated_at = now
        contact.updated_at = now
        await db.flush()

        if thread.lead_id:
            try:
                from app.services.communication_crm_service import CommunicationCrmService
                await CommunicationCrmService.sync_message_activity(db, thread, msg)
            except Exception as exc:
                logger.debug("%s activity sync skipped: %s", HUB_MARKER, exc)

        logger.info(
            "%s message stored: thread=%s direction=inbound telegram",
            HUB_MARKER, thread.id,
        )
        return {"thread_id": str(thread.id), "message_id": str(msg.id)}
