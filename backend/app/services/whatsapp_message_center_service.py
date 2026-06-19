"""WhatsApp Message Center — manual copy/paste workflow via Communication Hub."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.communication import CommunicationContact, CommunicationMessage, CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.proposal_document import ProposalDocument
from app.models.sales_playbook import SalesPlaybook
from app.schemas.whatsapp_message_center import (
    WhatsAppContactCreate,
    WhatsAppCreateLeadRequest,
    WhatsAppGenerateReplyRequest,
    WhatsAppPasteInboundRequest,
    WhatsAppThreadCreate,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.communication_crm_service import CommunicationCrmService
from app.services.communication_hub_scope import contact_tenant_filter, tenant_client_ids, thread_tenant_filter
from app.services.communication_service import (
    CommunicationHubService,
    _client_name_map,
    _lead_name_map,
    _preview,
    _serialize_contact,
    _serialize_message,
    _serialize_thread,
)
from app.services.crm_service import CrmService
from app.services.deal_service import DealService

logger = logging.getLogger(__name__)
MARKER = "[WhatsApp Center]"
WHATSAPP_CHANNEL = "whatsapp"

_REPLY_SYSTEM = """\
You draft WhatsApp Business replies for a B2B export sales operator.
The operator copies your text manually into WhatsApp — NEVER imply the message was sent.
Return ONLY JSON:
{
  "language": "zh|ru|en|uz",
  "reply_text": "complete reply ready to paste into WhatsApp",
  "tone": "professional|friendly|formal|consultative",
  "recommended_next_action": "single imperative next step for operator",
  "risk_flags": ["optional short risk strings, empty array if none"]
}
Rules: concise, professional B2B tone; do not invent prices or MOQ; draft only.
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _heuristic_reply(thread: CommunicationThread, contact: CommunicationContact | None) -> dict[str, Any]:
    lang = (contact.preferred_language if contact else None) or (contact.language if contact else None) or "en"
    name = contact.name if contact else "there"
    if lang == "zh":
        reply = f"您好 {name}，感谢您的WhatsApp消息。我们会尽快回复，请提供产品规格和数量需求。"
    elif lang == "ru":
        reply = f"Здравствуйте, {name}! Спасибо за сообщение в WhatsApp. Мы ответим в ближайшее время."
    else:
        reply = f"Hello {name}, thank you for your WhatsApp message. We will review and respond shortly."
    return {
        "language": lang,
        "reply_text": reply,
        "tone": "professional",
        "recommended_next_action": "Review thread context and paste reply manually in WhatsApp.",
        "risk_flags": ["demo_mode"],
    }


async def _deal_title_map(db: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    r = await db.execute(select(CrmDeal.id, CrmDeal.title).where(CrmDeal.id.in_(ids)))
    return {row[0]: row[1] for row in r.all()}


async def _load_whatsapp_thread(
    db: AsyncSession,
    thread_id: UUID,
    tenant_id: UUID | None = None,
) -> CommunicationThread:
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
    if thread.channel != WHATSAPP_CHANNEL:
        raise HTTPException(status_code=400, detail="Thread is not a WhatsApp channel")
    if tenant_id is not None:
        client_ids = await tenant_client_ids(db, tenant_id)
        if thread.tenant_id != tenant_id and thread.client_id not in client_ids:
            raise HTTPException(status_code=403, detail="Thread not in tenant scope")
    return thread


async def _build_ai_panel(db: AsyncSession, thread: CommunicationThread) -> dict[str, Any]:
    messages = thread.messages or []
    inbound = [m.message_text for m in messages if m.direction == "inbound"][-5:]
    summary = " ".join(inbound)[:400] if inbound else "No inbound messages yet."
    next_action = "Paste the latest WhatsApp message from the contact."
    if thread.lead_id:
        lead = await CrmService.get_lead(db, thread.lead_id)
        if lead.get("recommended_action"):
            next_action = str(lead["recommended_action"])[:500]
    proposal_count = 0
    if thread.lead_id:
        proposal_count = (
            await db.execute(
                select(func.count()).select_from(ProposalDocument).where(
                    ProposalDocument.lead_id == thread.lead_id
                )
            )
        ).scalar_one()
    return {
        "summary": summary,
        "recommended_next_action": next_action,
        "sentiment": "neutral",
        "has_linked_lead": bool(thread.lead_id or thread.sales_lead_id),
        "has_linked_deal": bool(thread.deal_id or thread.sales_deal_id),
        "proposal_count": proposal_count,
        "playbook_name": None,
    }


class WhatsAppMessageCenterService:
    @staticmethod
    async def list_contacts(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        wa_filter = or_(
            CommunicationContact.whatsapp.isnot(None),
            CommunicationContact.id.in_(
                select(CommunicationThread.contact_id).where(
                    CommunicationThread.channel == WHATSAPP_CHANNEL
                )
            ),
        )
        q = select(CommunicationContact).where(wa_filter)
        count_q = select(func.count()).select_from(CommunicationContact).where(wa_filter)
        tenant_filter = await contact_tenant_filter(
            tenant_id,
            await tenant_client_ids(db, tenant_id) if tenant_id else [],
        )
        if tenant_filter is not None:
            q = q.where(tenant_filter)
            count_q = count_q.where(tenant_filter)
        if client_id:
            q = q.where(CommunicationContact.client_id == client_id)
            count_q = count_q.where(CommunicationContact.client_id == client_id)
        if search:
            like = f"%{search.strip()}%"
            filt = (
                CommunicationContact.name.ilike(like)
                | CommunicationContact.company.ilike(like)
                | CommunicationContact.whatsapp.ilike(like)
                | CommunicationContact.phone.ilike(like)
            )
            q = q.where(filt)
            count_q = count_q.where(filt)
        total = (await db.execute(count_q)).scalar_one()
        contacts = list(
            (await db.execute(
                q.order_by(CommunicationContact.updated_at.desc()).offset(skip).limit(limit)
            )).scalars().all()
        )
        client_names = await _client_name_map(db, {c.client_id for c in contacts if c.client_id})
        lead_names = await _lead_name_map(db, {c.lead_id for c in contacts if c.lead_id})
        items = [
            _serialize_contact(
                c,
                client_name=client_names.get(c.client_id) if c.client_id else None,
                lead_name=lead_names.get(c.lead_id) if c.lead_id else None,
            )
            for c in contacts
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def create_contact(
        db: AsyncSession,
        data: WhatsAppContactCreate,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        phone = data.phone.strip()
        existing = (
            await db.execute(
                select(CommunicationContact).where(
                    or_(
                        CommunicationContact.whatsapp == phone,
                        CommunicationContact.phone == phone,
                    )
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            existing.name = data.name
            existing.company = data.company or existing.company
            existing.country = data.country or existing.country
            existing.city = data.city or getattr(existing, "city", None)
            existing.industry = data.industry or existing.industry
            existing.whatsapp = phone
            existing.phone = phone
            existing.updated_at = _utcnow()
            await db.commit()
            await db.refresh(existing)
            return _serialize_contact(existing)

        contact = CommunicationContact(
            tenant_id=tenant_id,
            name=data.name,
            client_id=data.client_id,
            lead_id=data.lead_id,
            company=data.company,
            country=data.country,
            city=data.city,
            industry=data.industry,
            phone=phone,
            whatsapp=phone,
            email=data.email,
            notes=data.notes,
            preferred_language=data.preferred_language,
            language=data.preferred_language,
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        return _serialize_contact(contact)

    @staticmethod
    async def list_threads(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
        contact_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(CommunicationThread).where(CommunicationThread.channel == WHATSAPP_CHANNEL)
        count_q = select(func.count()).select_from(CommunicationThread).where(
            CommunicationThread.channel == WHATSAPP_CHANNEL
        )
        tenant_filter = await thread_tenant_filter(
            tenant_id,
            await tenant_client_ids(db, tenant_id) if tenant_id else [],
        )
        if tenant_filter is not None:
            q = q.where(tenant_filter)
            count_q = count_q.where(tenant_filter)
        if client_id:
            q = q.where(CommunicationThread.client_id == client_id)
            count_q = count_q.where(CommunicationThread.client_id == client_id)
        if contact_id:
            q = q.where(CommunicationThread.contact_id == contact_id)
            count_q = count_q.where(CommunicationThread.contact_id == contact_id)
        if status:
            q = q.where(CommunicationThread.status == status)
            count_q = count_q.where(CommunicationThread.status == status)
        total = (await db.execute(count_q)).scalar_one()
        threads = list(
            (await db.execute(
                q.order_by(
                    CommunicationThread.last_message_at.desc().nullslast(),
                    CommunicationThread.updated_at.desc(),
                ).offset(skip).limit(limit)
            )).scalars().all()
        )
        contact_ids = {t.contact_id for t in threads}
        contact_names: dict[UUID, str] = {}
        if contact_ids:
            cn = await db.execute(
                select(CommunicationContact.id, CommunicationContact.name).where(
                    CommunicationContact.id.in_(contact_ids)
                )
            )
            contact_names = {row[0]: row[1] for row in cn.all()}
        client_names = await _client_name_map(db, {t.client_id for t in threads if t.client_id})
        lead_names = await _lead_name_map(db, {t.lead_id for t in threads if t.lead_id})
        deal_titles = await _deal_title_map(db, {t.deal_id for t in threads if t.deal_id})
        thread_ids = [t.id for t in threads]
        msg_stats: dict[UUID, tuple[int, str | None]] = {}
        if thread_ids:
            ms = await db.execute(
                select(
                    CommunicationMessage.thread_id,
                    func.count(),
                    func.max(CommunicationMessage.message_text),
                )
                .where(CommunicationMessage.thread_id.in_(thread_ids))
                .group_by(CommunicationMessage.thread_id)
            )
            for tid, cnt, last_text in ms.all():
                msg_stats[tid] = (cnt, _preview(last_text))
        items = []
        for t in threads:
            row = _serialize_thread(
                t,
                contact_name=contact_names.get(t.contact_id),
                client_name=client_names.get(t.client_id) if t.client_id else None,
                lead_name=lead_names.get(t.lead_id) if t.lead_id else None,
                message_count=msg_stats.get(t.id, (0, None))[0],
                last_message_preview=msg_stats.get(t.id, (0, None))[1],
            )
            row["deal_title"] = deal_titles.get(t.deal_id) if t.deal_id else None
            items.append(row)
        return {"items": items, "total": total}

    @staticmethod
    async def create_thread(
        db: AsyncSession,
        data: WhatsAppThreadCreate,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        contact = await db.get(CommunicationContact, data.contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        existing = (
            await db.execute(
                select(CommunicationThread).where(
                    CommunicationThread.contact_id == data.contact_id,
                    CommunicationThread.channel == WHATSAPP_CHANNEL,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            return _serialize_thread(existing)
        title = data.title or f"WhatsApp — {contact.name}"
        thread = CommunicationThread(
            tenant_id=tenant_id or contact.tenant_id,
            contact_id=data.contact_id,
            client_id=data.client_id or contact.client_id,
            lead_id=data.lead_id or contact.lead_id,
            deal_id=data.deal_id,
            channel=WHATSAPP_CHANNEL,
            external_contact_id=data.external_contact_id,
            title=title,
            status="open",
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
        return _serialize_thread(thread)

    @staticmethod
    async def get_thread(
        db: AsyncSession,
        thread_id: UUID,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        thread = await _load_whatsapp_thread(db, thread_id, tenant_id=tenant_id)
        client_name = None
        if thread.client_id:
            client_name = (await _client_name_map(db, {thread.client_id})).get(thread.client_id)
        lead_name = None
        if thread.lead_id:
            lead_name = (await _lead_name_map(db, {thread.lead_id})).get(thread.lead_id)
        deal_title = None
        if thread.deal_id:
            deal_title = (await _deal_title_map(db, {thread.deal_id})).get(thread.deal_id)
        messages = [_serialize_message(m) for m in thread.messages]
        return {
            **_serialize_thread(
                thread,
                contact_name=thread.contact.name if thread.contact else None,
                client_name=client_name,
                lead_name=lead_name,
                message_count=len(messages),
                last_message_preview=_preview(messages[-1]["message_text"]) if messages else None,
            ),
            "deal_title": deal_title,
            "messages": messages,
            "contact": _serialize_contact(thread.contact) if thread.contact else None,
            "ai_panel": await _build_ai_panel(db, thread),
        }

    @staticmethod
    async def paste_inbound(
        db: AsyncSession,
        thread_id: UUID,
        data: WhatsAppPasteInboundRequest,
    ) -> dict[str, Any]:
        thread = await _load_whatsapp_thread(db, thread_id)
        sender = (data.sender_name or "").strip() or (thread.contact.name if thread.contact else "Contact")
        now = _utcnow()
        msg = CommunicationMessage(
            thread_id=thread_id,
            direction="inbound",
            sender_name=sender,
            message_text=data.message_text.strip(),
            original_language=data.original_language,
            translated_text=data.translated_text,
            status="unanswered",
        )
        db.add(msg)
        thread.last_message_at = now
        thread.last_manual_sync_at = now
        thread.updated_at = now
        if thread.status == "closed":
            thread.status = "open"
        if thread.contact:
            thread.contact.updated_at = now
        await db.commit()
        await db.refresh(msg)
        return _serialize_message(msg)

    @staticmethod
    async def generate_reply(
        db: AsyncSession,
        thread_id: UUID,
        data: WhatsAppGenerateReplyRequest | None = None,
    ) -> dict[str, Any]:
        thread = await _load_whatsapp_thread(db, thread_id)
        if not thread.messages:
            raise HTTPException(status_code=400, detail="Thread has no messages — paste inbound first")
        context = "\n".join(
            f"[{m.direction}] {m.sender_name}: {m.message_text[:500]}"
            for m in (thread.messages or [])[-20:]
        )
        if data and data.operator_notes:
            context += f"\n\nOPERATOR_NOTES: {data.operator_notes.strip()}"
        demo_mode = False
        result: dict[str, Any] = {}
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _REPLY_SYSTEM},
                    {"role": "user", "content": context},
                ],
                temperature=0.5,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            risk_flags = parsed.get("risk_flags") or []
            if not isinstance(risk_flags, list):
                risk_flags = [str(risk_flags)]
            result = {
                "language": str(parsed.get("language") or "en")[:10],
                "reply_text": str(parsed.get("reply_text") or "")[:4000],
                "tone": str(parsed.get("tone") or "professional")[:50],
                "recommended_next_action": str(parsed.get("recommended_next_action") or "")[:500],
                "risk_flags": [str(f)[:200] for f in risk_flags[:10]],
            }
            if not result["reply_text"]:
                raise ValueError("empty reply")
        except Exception as exc:
            demo_mode = True
            logger.info("%s reply fallback: %s", MARKER, exc)
            result = _heuristic_reply(thread, thread.contact)
        meta = {
            "language": result["language"],
            "tone": result["tone"],
            "recommended_next_action": result["recommended_next_action"],
            "risk_flags": result["risk_flags"],
        }
        msg = CommunicationMessage(
            thread_id=thread_id,
            direction="draft",
            sender_name="AI Draft",
            message_text=result["reply_text"],
            ai_summary=json.dumps(meta, ensure_ascii=False),
            status="draft",
        )
        db.add(msg)
        thread.updated_at = _utcnow()
        await db.commit()
        await db.refresh(msg)
        return {"message_id": msg.id, **result, "demo_mode": demo_mode}

    @staticmethod
    async def mark_copied(db: AsyncSession, message_id: UUID) -> dict[str, Any]:
        msg = (await db.execute(
            select(CommunicationMessage).where(CommunicationMessage.id == message_id)
        )).scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        now = _utcnow()
        msg.copied_at = now
        await db.commit()
        return {"message_id": msg.id, "copied_at": now}

    @staticmethod
    async def mark_manually_sent(db: AsyncSession, message_id: UUID) -> dict[str, Any]:
        msg = (
            await db.execute(
                select(CommunicationMessage)
                .options(selectinload(CommunicationMessage.thread))
                .where(CommunicationMessage.id == message_id)
            )
        ).scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        thread = msg.thread
        now = _utcnow()
        msg.manual_sent_at = now
        msg.direction = "outbound"
        msg.sender_name = "Operator"
        msg.status = "sent"
        if thread:
            thread.last_message_at = now
            thread.updated_at = now
        await db.commit()
        return {"message_id": msg.id, "manual_sent_at": now, "direction": "outbound"}

    @staticmethod
    async def create_lead(
        db: AsyncSession,
        thread_id: UUID,
        data: WhatsAppCreateLeadRequest | None = None,
    ) -> dict[str, Any]:
        await _load_whatsapp_thread(db, thread_id)
        payload = None
        if data:
            from app.schemas.communication import CommunicationCrmCreateLeadRequest

            payload = CommunicationCrmCreateLeadRequest(
                name=data.name,
                company=data.company,
                interest=data.interest,
                notes=data.notes,
            )
        result = await CommunicationCrmService.create_lead_from_thread(db, thread_id, payload)
        if result.get("created"):
            lr = await db.execute(select(CrmLead).where(CrmLead.id == result["lead_id"]))
            lead = lr.scalar_one_or_none()
            if lead and lead.source == "manual":
                lead.source = "whatsapp"
                await db.commit()
        return result

    @staticmethod
    async def link_lead(db: AsyncSession, thread_id: UUID, lead_id: UUID) -> dict[str, Any]:
        await _load_whatsapp_thread(db, thread_id)
        result = await CommunicationHubService.link_lead(db, thread_id, lead_id)
        return {"thread_id": thread_id, "lead_id": result["lead_id"], "lead_name": result["lead_name"]}

    @staticmethod
    async def link_deal(db: AsyncSession, thread_id: UUID, deal_id: UUID) -> dict[str, Any]:
        thread = await _load_whatsapp_thread(db, thread_id)
        deal = await DealService.get_deal(db, deal_id)
        thread.deal_id = deal_id
        if not thread.lead_id:
            thread.lead_id = deal["lead_id"]
        if not thread.client_id:
            thread.client_id = deal["client_id"]
        await db.commit()
        return {
            "thread_id": thread_id,
            "deal_id": deal_id,
            "deal_title": deal["title"],
            "lead_id": deal["lead_id"],
        }
