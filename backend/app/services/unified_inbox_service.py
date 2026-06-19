"""Unified Inbox — aggregate conversations across channels (read + manual actions only)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit
from app.models.buyer_outreach import BuyerOutreachMessage
from app.models.communication import (
    CommunicationContact,
    CommunicationMessage,
    CommunicationThread,
)
from app.models.crm_lead import CrmLead
from app.models.proposal_document import ProposalDocument
from app.schemas.communication import CommunicationCrmCreateTaskRequest
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage, WhatsAppThread
from app.schemas.unified_inbox import (
    THREAD_INBOX_CHANNELS,
    UNIFIED_INBOX_CHANNELS,
    UnifiedInboxCreateTaskRequest,
)
from app.services.communication_crm_service import CommunicationCrmService
from app.services.communication_service import CommunicationHubService, _preview
from app.services.crm_service import CrmService
from app.services.sales_assistant_service import SalesAssistantService
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.wechat_contact_center_service import _build_ai_panel
from app.services.whatsapp_contact_service import _ensure_mock_data as _ensure_whatsapp_mock_data

logger = logging.getLogger(__name__)

MARKER = "[Unified Inbox]"

PRIORITIES = frozenset({"high", "medium", "low"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_unified_id(source: str, source_id: UUID) -> str:
    return f"{source}:{source_id}"


def parse_unified_id(raw_id: str) -> tuple[str, UUID]:
    if ":" not in raw_id:
        try:
            return "thread", UUID(raw_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid conversation id") from exc
    source, uid = raw_id.split(":", 1)
    if source not in ("thread", "outreach", "whatsapp"):
        raise HTTPException(status_code=400, detail="Invalid conversation id prefix")
    try:
        return source, UUID(uid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conversation id") from exc


def _calc_unread(messages: list[CommunicationMessage]) -> int:
    if not messages:
        return 0
    outbound_times = [m.created_at for m in messages if m.direction == "outbound"]
    last_out = max(outbound_times) if outbound_times else None
    if last_out is None:
        return sum(1 for m in messages if m.direction == "inbound")
    return sum(1 for m in messages if m.direction == "inbound" and m.created_at > last_out)


def _priority_for_thread(thread: CommunicationThread, lead: dict[str, Any] | None) -> str:
    if lead and lead.get("priority") in PRIORITIES:
        return str(lead["priority"])
    if thread.status == "waiting":
        return "high"
    return "medium"


def _priority_for_outreach(outreach: BuyerOutreachMessage) -> str:
    if outreach.status in ("approved", "sent"):
        return "high"
    if outreach.status == "draft":
        return "medium"
    return "low"


def _last_message_text(messages: list[CommunicationMessage], fallback: str | None = None) -> str | None:
    if messages:
        return _preview(messages[-1].message_text, 200)
    return _preview(fallback, 200) if fallback else None


def _thread_conversation(
    thread: CommunicationThread,
    contact: CommunicationContact | None,
    *,
    message_count: int = 0,
    last_text: str | None = None,
    unread: int = 0,
    lead_name: str | None = None,
    priority: str = "medium",
) -> dict[str, Any]:
    name = contact.name if contact else thread.title
    company = contact.company if contact else None
    country = contact.country if contact else None
    channel = thread.channel if thread.channel in THREAD_INBOX_CHANNELS else "manual"
    return {
        "id": format_unified_id("thread", thread.id),
        "source": "thread",
        "source_id": thread.id,
        "channel": channel,
        "contact_name": name,
        "company": company,
        "country": country,
        "lead_id": thread.lead_id,
        "deal_id": thread.deal_id,
        "contact_id": thread.contact_id,
        "client_id": thread.client_id,
        "last_message": last_text,
        "last_message_at": thread.last_message_at or thread.updated_at,
        "unread_count": unread,
        "priority": priority if priority in PRIORITIES else "medium",
        "status": thread.status,
        "lead_name": lead_name,
        "deal_title": None,
        "thread_id": thread.id,
        "outreach_id": None,
        "whatsapp_thread_id": None,
        "whatsapp_contact_id": None,
        "communication_health_score": None,
        "communication_classification": None,
        "_message_count": message_count,
    }


def _whatsapp_conversation(
    thread: WhatsAppThread,
    contact: WhatsAppContact | None,
    *,
    last_text: str | None = None,
) -> dict[str, Any]:
    name = contact.display_name if contact else "WhatsApp contact"
    return {
        "id": format_unified_id("whatsapp", thread.id),
        "source": "whatsapp",
        "source_id": thread.id,
        "channel": "whatsapp",
        "contact_name": name,
        "company": contact.company if contact else None,
        "country": contact.country if contact else None,
        "lead_id": None,
        "deal_id": None,
        "contact_id": None,
        "client_id": contact.crm_client_id if contact else None,
        "last_message": last_text,
        "last_message_at": thread.last_message_at or thread.created_at,
        "unread_count": thread.unread_count or 0,
        "priority": "high" if (thread.unread_count or 0) > 0 else "medium",
        "status": "open",
        "lead_name": None,
        "deal_title": None,
        "thread_id": None,
        "outreach_id": None,
        "whatsapp_thread_id": thread.id,
        "whatsapp_contact_id": thread.contact_id,
        "communication_health_score": None,
        "communication_classification": None,
        "_message_count": 0,
    }


def _outreach_conversation(
    outreach: BuyerOutreachMessage,
    *,
    unread: int = 0,
    lead_name: str | None = None,
) -> dict[str, Any]:
    name = (outreach.buyer_name or outreach.buyer_company or "Buyer").strip()
    last_at = outreach.last_action_at or outreach.sent_at or outreach.updated_at
    return {
        "id": format_unified_id("outreach", outreach.id),
        "source": "outreach",
        "source_id": outreach.id,
        "channel": "outreach",
        "contact_name": name,
        "company": outreach.buyer_company,
        "country": outreach.country,
        "lead_id": outreach.lead_id,
        "deal_id": None,
        "contact_id": None,
        "client_id": outreach.client_id,
        "last_message": _preview(outreach.message_text, 200),
        "last_message_at": last_at,
        "unread_count": unread,
        "priority": _priority_for_outreach(outreach),
        "status": outreach.status,
        "lead_name": lead_name,
        "deal_title": None,
        "thread_id": outreach.communication_thread_id,
        "outreach_id": outreach.id,
        "whatsapp_thread_id": None,
        "whatsapp_contact_id": None,
        "_message_count": 1,
    }


def _strip_internal(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


async def _attach_communication_summary(
    db: AsyncSession,
    row: dict[str, Any],
    *,
    thread: CommunicationThread | None = None,
    wa_thread: WhatsAppThread | None = None,
) -> None:
    try:
        if thread is not None:
            item = await CommunicationIntelligenceService._analyze_thread(db, thread)
        elif wa_thread is not None:
            item = await CommunicationIntelligenceService._analyze_whatsapp(db, wa_thread)
        else:
            return
        intel = item.get("intelligence") or {}
        row["communication_health_score"] = intel.get("health_score")
        row["communication_classification"] = intel.get("classification")
    except Exception as exc:
        logger.debug("%s comm summary skip: %s", MARKER, exc)


async def _communication_intelligence_detail(
    db: AsyncSession,
    raw_id: str,
) -> dict[str, Any] | None:
    try:
        return await CommunicationIntelligenceService.analyze_conversation(db, raw_id)
    except Exception as exc:
        logger.debug("%s comm detail skip: %s err=%s", MARKER, raw_id, exc)
        return None


def _matches_search(
    row: dict[str, Any],
    *,
    search: str | None,
    message_haystack: str | None = None,
) -> bool:
    if not search:
        return True
    q = search.strip().lower()
    if not q:
        return True
    parts = [
        row.get("contact_name") or "",
        row.get("company") or "",
        row.get("last_message") or "",
        message_haystack or "",
    ]
    return any(q in (p or "").lower() for p in parts)


class UnifiedInboxService:
    @staticmethod
    async def list_conversations(
        db: AsyncSession,
        *,
        channel: str | None = None,
        country: str | None = None,
        company: str | None = None,
        linked: str | None = None,
        unread: bool | None = None,
        priority: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        if channel and channel not in UNIFIED_INBOX_CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel filter")
        if priority and priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority filter")
        if linked and linked not in ("linked", "unlinked"):
            raise HTTPException(status_code=400, detail="linked must be linked or unlinked")

        thread_channels = list(THREAD_INBOX_CHANNELS)
        if channel and channel in THREAD_INBOX_CHANNELS:
            thread_channels = [channel]

        rows: list[dict[str, Any]] = []

        if not channel or channel in THREAD_INBOX_CHANNELS:
            tq = (
                select(CommunicationThread)
                .options(
                    selectinload(CommunicationThread.contact),
                    selectinload(CommunicationThread.messages),
                )
                .where(CommunicationThread.channel.in_(thread_channels))
            )
            if country or company:
                tq = tq.join(CommunicationContact)
                if country:
                    tq = tq.where(CommunicationContact.country.ilike(f"%{country.strip()}%"))
                if company:
                    tq = tq.where(CommunicationContact.company.ilike(f"%{company.strip()}%"))

            tr = await db.execute(
                tq.order_by(
                    CommunicationThread.last_message_at.desc().nullslast(),
                    CommunicationThread.updated_at.desc(),
                ).limit(MAX_LIMIT)
            )
            threads = list(tr.scalars().unique().all())

            lead_ids = {t.lead_id for t in threads if t.lead_id}
            lead_map: dict[UUID, dict[str, Any]] = {}
            for lid in lead_ids:
                try:
                    lead_map[lid] = await CrmService.get_lead(db, lid)
                except HTTPException:
                    pass

            for thread in threads:
                contact = thread.contact
                lead = lead_map.get(thread.lead_id) if thread.lead_id else None
                msgs = list(thread.messages or [])
                unread_n = _calc_unread(msgs)
                row = _thread_conversation(
                    thread,
                    contact,
                    last_text=_last_message_text(msgs),
                    unread=unread_n,
                    lead_name=lead["name"] if lead else None,
                    priority=_priority_for_thread(thread, lead),
                )
                haystack = " ".join(m.message_text[:200] for m in msgs[-15:])
                if not _matches_search(row, search=search, message_haystack=haystack):
                    continue
                if linked == "linked" and not row["lead_id"]:
                    continue
                if linked == "unlinked" and row["lead_id"]:
                    continue
                if unread is True and unread_n == 0:
                    continue
                if unread is False and unread_n > 0:
                    continue
                if priority and row["priority"] != priority:
                    continue
                await _attach_communication_summary(db, row, thread=thread)
                rows.append(row)

        if not channel or channel == "whatsapp":
            await _ensure_whatsapp_mock_data(db)
            wq = (
                select(WhatsAppThread)
                .options(
                    selectinload(WhatsAppThread.contact),
                    selectinload(WhatsAppThread.messages),
                )
            )
            if country or company:
                wq = wq.join(WhatsAppContact)
                if country:
                    wq = wq.where(WhatsAppContact.country.ilike(f"%{country.strip()}%"))
                if company:
                    wq = wq.where(WhatsAppContact.company.ilike(f"%{company.strip()}%"))

            wr = await db.execute(
                wq.order_by(
                    WhatsAppThread.last_message_at.desc().nullslast(),
                    WhatsAppThread.created_at.desc(),
                ).limit(MAX_LIMIT)
            )
            wa_threads = list(wr.scalars().unique().all())

            for wa_thread in wa_threads:
                contact = wa_thread.contact
                msgs = list(wa_thread.messages or [])
                last_text = _preview(msgs[-1].content, 200) if msgs else None
                row = _whatsapp_conversation(wa_thread, contact, last_text=last_text)
                haystack = " ".join(m.content[:200] for m in msgs[-15:])
                if not _matches_search(row, search=search, message_haystack=haystack):
                    continue
                if linked == "linked" and not row["client_id"]:
                    continue
                if linked == "unlinked" and row["client_id"]:
                    continue
                if unread is True and (row["unread_count"] or 0) == 0:
                    continue
                if unread is False and (row["unread_count"] or 0) > 0:
                    continue
                if priority and row["priority"] != priority:
                    continue
                await _attach_communication_summary(db, row, wa_thread=wa_thread)
                rows.append(row)

        if not channel or channel == "outreach":
            oq = select(BuyerOutreachMessage).where(
                BuyerOutreachMessage.communication_thread_id.is_(None),
                BuyerOutreachMessage.status != "archived",
            )
            if country:
                oq = oq.where(BuyerOutreachMessage.country.ilike(f"%{country.strip()}%"))
            if company:
                oq = oq.where(BuyerOutreachMessage.buyer_company.ilike(f"%{company.strip()}%"))

            or_ = await db.execute(
                oq.order_by(BuyerOutreachMessage.updated_at.desc()).limit(MAX_LIMIT)
            )
            outreach_items = list(or_.scalars().all())

            lead_ids = {o.lead_id for o in outreach_items if o.lead_id}
            lead_names: dict[UUID, str] = {}
            if lead_ids:
                lr = await db.execute(select(CrmLead.id, CrmLead.name).where(CrmLead.id.in_(lead_ids)))
                lead_names = {row[0]: row[1] for row in lr.all()}

            for outreach in outreach_items:
                lead_name = lead_names.get(outreach.lead_id) if outreach.lead_id else None
                row = _outreach_conversation(outreach, lead_name=lead_name)
                if not _matches_search(row, search=search, message_haystack=outreach.message_text):
                    continue
                if linked == "linked" and not row["lead_id"]:
                    continue
                if linked == "unlinked" and row["lead_id"]:
                    continue
                if unread is True:
                    continue
                if unread is False:
                    pass
                if priority and row["priority"] != priority:
                    continue
                rows.append(row)

        rows.sort(
            key=lambda r: r.get("last_message_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        total = len(rows)
        page = [_strip_internal(r) for r in rows[skip : skip + limit]]
        return {"items": page, "total": total}

    @staticmethod
    async def _sales_assistant_for_conversation(
        db: AsyncSession,
        raw_id: str,
    ) -> list[dict[str, Any]]:
        data = await SalesAssistantService.list_recommendations(
            db, status="open", conversation_id=raw_id, limit=10,
        )
        return data.get("items") or []

    @staticmethod
    async def get_conversation(db: AsyncSession, raw_id: str) -> dict[str, Any]:
        source, source_id = parse_unified_id(raw_id)

        if source == "whatsapp":
            await _ensure_whatsapp_mock_data(db)
            r = await db.execute(
                select(WhatsAppThread)
                .options(
                    selectinload(WhatsAppThread.contact),
                    selectinload(WhatsAppThread.messages),
                )
                .where(WhatsAppThread.id == source_id)
            )
            wa_thread = r.scalar_one_or_none()
            if not wa_thread:
                raise HTTPException(status_code=404, detail="Conversation not found")

            contact = wa_thread.contact
            msgs = list(wa_thread.messages or [])
            last_text = _preview(msgs[-1].content, 200) if msgs else None
            conv = _strip_internal(_whatsapp_conversation(wa_thread, contact, last_text=last_text))

            messages: list[dict[str, Any]] = []
            for msg in msgs:
                if msg.direction == "incoming":
                    direction = "inbound"
                    sender = contact.display_name if contact else "Contact"
                elif msg.status == "draft":
                    direction = "draft"
                    sender = "AI Draft"
                else:
                    direction = "outbound"
                    sender = "Operator"
                messages.append({
                    "id": msg.id,
                    "thread_id": msg.thread_id,
                    "direction": direction,
                    "sender_name": sender,
                    "message_text": msg.content,
                    "attachments_json": None,
                    "original_language": None,
                    "translated_text": None,
                    "ai_summary": None,
                    "copied_at": None,
                    "manual_sent_at": None,
                    "created_at": msg.created_at,
                })

            inbound = [m.content for m in msgs if m.direction == "incoming"][-5:]
            summary = " ".join(inbound)[:400] if inbound else "No inbound WhatsApp messages yet."
            ai_panel = {
                "summary": summary,
                "lead_status": None,
                "proposal_status": None,
                "recommended_action": "Review WhatsApp thread and generate a reply draft when ready.",
                "has_linked_lead": False,
                "has_linked_deal": False,
                "proposal_count": 0,
                "can_create_lead": False,
                "can_create_proposal": False,
                "can_create_task": True,
            }

            contact_data = None
            if contact:
                contact_data = {
                    "id": contact.id,
                    "client_id": contact.crm_client_id,
                    "lead_id": None,
                    "deal_id": None,
                    "partner_id": None,
                    "name": contact.display_name,
                    "company": contact.company,
                    "role": None,
                    "phone": contact.phone,
                    "telegram": None,
                    "whatsapp": contact.phone,
                    "wechat": None,
                    "wechat_id": None,
                    "wecom_id": None,
                    "qr_code_url": None,
                    "email": None,
                    "country": contact.country,
                    "language": None,
                    "preferred_language": None,
                    "notes": None,
                    "client_name": None,
                    "lead_name": None,
                    "partner_name": None,
                    "thread_count": 0,
                    "created_at": contact.created_at,
                    "updated_at": contact.updated_at,
                }

            logger.info("%s conversation loaded: id=%s source=whatsapp", MARKER, raw_id)
            sa_recs = await UnifiedInboxService._sales_assistant_for_conversation(db, raw_id)
            comm_intel = await _communication_intelligence_detail(db, raw_id)
            return {
                "conversation": conv,
                "thread": None,
                "messages": messages,
                "contact": contact_data,
                "ai_panel": ai_panel,
                "linked_outreach": [],
                "sales_assistant_recommendations": sa_recs,
                "communication_intelligence": comm_intel,
            }

        if source == "thread":
            detail = await CommunicationHubService.get_thread(db, source_id)
            r = await db.execute(
                select(CommunicationThread)
                .options(
                    selectinload(CommunicationThread.messages),
                    selectinload(CommunicationThread.contact),
                )
                .where(CommunicationThread.id == source_id)
            )
            thread = r.scalar_one_or_none()
            if not thread:
                raise HTTPException(status_code=404, detail="Conversation not found")

            lead = None
            if thread.lead_id:
                try:
                    lead = await CrmService.get_lead(db, thread.lead_id)
                except HTTPException:
                    lead = None

            msgs = list(thread.messages or [])
            conv = _strip_internal(
                _thread_conversation(
                    thread,
                    thread.contact,
                    last_text=_last_message_text(msgs, detail.get("last_message_preview")),
                    unread=_calc_unread(msgs),
                    lead_name=detail.get("lead_name"),
                    priority=_priority_for_thread(thread, lead),
                )
            )
            ai_base = await _build_ai_panel(db, thread)
            proposal_status = None
            if thread.lead_id:
                pr = await db.execute(
                    select(ProposalDocument.status)
                    .where(ProposalDocument.lead_id == thread.lead_id)
                    .order_by(ProposalDocument.updated_at.desc())
                    .limit(1)
                )
                proposal_status = pr.scalar_one_or_none()

            ai_panel = {
                "summary": ai_base.get("summary") or "",
                "lead_status": lead.get("status") if lead else None,
                "proposal_status": proposal_status,
                "recommended_action": ai_base.get("recommended_next_action") or "",
                "has_linked_lead": bool(thread.lead_id),
                "has_linked_deal": bool(thread.deal_id),
                "proposal_count": ai_base.get("proposal_count") or 0,
                "can_create_lead": not bool(thread.lead_id),
                "can_create_proposal": bool(thread.lead_id),
                "can_create_task": True,
            }

            logger.info("%s conversation loaded: id=%s source=thread", MARKER, raw_id)
            sa_recs = await UnifiedInboxService._sales_assistant_for_conversation(db, raw_id)
            comm_intel = await _communication_intelligence_detail(db, raw_id)
            return {
                "conversation": conv,
                "thread": {k: detail[k] for k in detail if k not in ("messages", "contact", "linked_outreach")},
                "messages": detail.get("messages") or [],
                "contact": detail.get("contact"),
                "ai_panel": ai_panel,
                "linked_outreach": detail.get("linked_outreach") or [],
                "sales_assistant_recommendations": sa_recs,
                "communication_intelligence": comm_intel,
            }

        outreach = await db.execute(
            select(BuyerOutreachMessage)
            .options(selectinload(BuyerOutreachMessage.client))
            .where(BuyerOutreachMessage.id == source_id)
        )
        outreach_row = outreach.scalar_one_or_none()
        if not outreach_row:
            raise HTTPException(status_code=404, detail="Conversation not found")

        lead_name = None
        lead = None
        if outreach_row.lead_id:
            try:
                lead = await CrmService.get_lead(db, outreach_row.lead_id)
                lead_name = lead.get("name")
            except HTTPException:
                pass

        messages: list[dict[str, Any]] = []
        thread_data = None
        contact_data = None
        linked_outreach: list[dict] = []

        if outreach_row.communication_thread_id:
            detail = await CommunicationHubService.get_thread(db, outreach_row.communication_thread_id)
            thread_data = {k: detail[k] for k in detail if k not in ("messages", "contact", "linked_outreach")}
            messages = detail.get("messages") or []
            contact_data = detail.get("contact")
            linked_outreach = detail.get("linked_outreach") or []
        else:
            sender = outreach_row.client.company_name if outreach_row.client else "Outreach"
            messages = [
                {
                    "id": outreach_row.id,
                    "thread_id": outreach_row.id,
                    "direction": "outbound",
                    "sender_name": sender[:255],
                    "message_text": outreach_row.message_text,
                    "attachments_json": None,
                    "original_language": outreach_row.language,
                    "translated_text": None,
                    "ai_summary": None,
                    "copied_at": outreach_row.copied_at,
                    "manual_sent_at": outreach_row.sent_at,
                    "created_at": outreach_row.created_at,
                }
            ]

        conv = _strip_internal(_outreach_conversation(outreach_row, lead_name=lead_name))
        proposal_status = None
        if outreach_row.proposal_id:
            proposal_status = "linked"
        elif outreach_row.lead_id:
            pr = await db.execute(
                select(ProposalDocument.status)
                .where(ProposalDocument.lead_id == outreach_row.lead_id)
                .order_by(ProposalDocument.updated_at.desc())
                .limit(1)
            )
            proposal_status = pr.scalar_one_or_none()

        ai_panel = {
            "summary": _preview(outreach_row.message_text, 400) or "",
            "lead_status": lead.get("status") if lead else None,
            "proposal_status": proposal_status,
            "recommended_action": "Review outreach draft and send manually when ready.",
            "has_linked_lead": bool(outreach_row.lead_id),
            "has_linked_deal": False,
            "proposal_count": 1 if outreach_row.proposal_id else 0,
            "can_create_lead": not bool(outreach_row.lead_id),
            "can_create_proposal": bool(outreach_row.lead_id) and not outreach_row.proposal_id,
            "can_create_task": True,
        }

        logger.info("%s conversation loaded: id=%s source=outreach", MARKER, raw_id)
        sa_recs = await UnifiedInboxService._sales_assistant_for_conversation(db, raw_id)
        comm_intel = None
        if outreach_row.communication_thread_id:
            comm_intel = await _communication_intelligence_detail(
                db, format_unified_id("thread", outreach_row.communication_thread_id),
            )
        return {
            "conversation": conv,
            "thread": thread_data,
            "messages": messages,
            "contact": contact_data,
            "ai_panel": ai_panel,
            "linked_outreach": linked_outreach,
            "sales_assistant_recommendations": sa_recs,
            "communication_intelligence": comm_intel,
        }

    @staticmethod
    async def link_lead(db: AsyncSession, raw_id: str, lead_id: UUID) -> dict[str, Any]:
        source, source_id = parse_unified_id(raw_id)
        if source == "thread":
            result = await CommunicationHubService.link_lead(db, source_id, lead_id)
            logger.info("%s lead linked: id=%s lead=%s", MARKER, raw_id, lead_id)
            return {
                "id": raw_id,
                "lead_id": result["lead_id"],
                "lead_name": result["lead_name"],
                "message": "Lead linked to conversation.",
            }

        r = await db.execute(
            select(BuyerOutreachMessage).where(BuyerOutreachMessage.id == source_id)
        )
        outreach = r.scalar_one_or_none()
        if not outreach:
            raise HTTPException(status_code=404, detail="Conversation not found")

        lead = await CrmService.get_lead(db, lead_id)
        outreach.lead_id = lead_id
        outreach.updated_at = _utcnow()
        if outreach.communication_thread_id:
            await CommunicationHubService.link_lead(db, outreach.communication_thread_id, lead_id)
        await db.commit()
        logger.info("%s lead linked: id=%s lead=%s", MARKER, raw_id, lead_id)
        return {
            "id": raw_id,
            "lead_id": lead_id,
            "lead_name": lead["name"],
            "message": "Lead linked to outreach conversation.",
        }

    @staticmethod
    async def link_deal(db: AsyncSession, raw_id: str, deal_id: UUID) -> dict[str, Any]:
        source, source_id = parse_unified_id(raw_id)
        if source != "thread":
            raise HTTPException(status_code=400, detail="Deal linking is only supported for thread conversations")

        from app.services.wechat_contact_center_service import WeChatContactCenterService

        result = await WeChatContactCenterService.link_deal(db, source_id, deal_id)
        logger.info("%s deal linked: id=%s deal=%s", MARKER, raw_id, deal_id)
        return {
            "id": raw_id,
            "deal_id": result["deal_id"],
            "deal_title": result["deal_title"],
            "lead_id": result.get("lead_id"),
            "message": "Deal linked to conversation.",
        }

    @staticmethod
    async def create_task(
        db: AsyncSession,
        raw_id: str,
        data: UnifiedInboxCreateTaskRequest,
    ) -> dict[str, Any]:
        source, source_id = parse_unified_id(raw_id)
        body = CommunicationCrmCreateTaskRequest(
            task_type=data.task_type,
            title=data.title,
            description=data.description,
            priority=data.priority,
            due_at=data.due_at,
        )

        if source == "thread":
            result = await CommunicationCrmService.create_task(db, source_id, body)
            logger.info("%s task created: id=%s task=%s", MARKER, raw_id, result["task_id"])
            return {
                "id": raw_id,
                "task_id": result["task_id"],
                "title": result["title"],
                "task_type": result["task_type"],
                "message": "Task created from conversation.",
            }

        if source == "whatsapp":
            from app.schemas.operator_task import OperatorTaskCreate
            from app.services.operator_task_service import OperatorTaskService

            r = await db.execute(
                select(WhatsAppThread)
                .options(selectinload(WhatsAppThread.contact))
                .where(WhatsAppThread.id == source_id)
            )
            wa_thread = r.scalar_one_or_none()
            if not wa_thread:
                raise HTTPException(status_code=404, detail="Conversation not found")

            templates = CommunicationCrmService.TASK_TEMPLATES
            title, desc, prio = templates.get(
                data.task_type,
                ("Follow up on WhatsApp", "Review WhatsApp thread and follow up.", "medium"),
            )
            contact = wa_thread.contact
            task = await OperatorTaskService.create_task(
                db,
                OperatorTaskCreate(
                    client_id=contact.crm_client_id if contact else None,
                    source_type="whatsapp",
                    source_id=wa_thread.id,
                    title=data.title or title,
                    description=data.description or desc,
                    priority=data.priority or prio,
                    due_at=data.due_at,
                ),
            )
            result = {
                "task_id": UUID(str(task["id"])),
                "title": task["title"],
                "task_type": data.task_type,
            }
            logger.info("%s task created: id=%s task=%s", MARKER, raw_id, result["task_id"])
            return {
                "id": raw_id,
                "task_id": result["task_id"],
                "title": result["title"],
                "task_type": result["task_type"],
                "message": "Task created from WhatsApp conversation.",
            }

        r = await db.execute(
            select(BuyerOutreachMessage).where(BuyerOutreachMessage.id == source_id)
        )
        outreach = r.scalar_one_or_none()
        if not outreach:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if outreach.communication_thread_id:
            result = await CommunicationCrmService.create_task(db, outreach.communication_thread_id, body)
        else:
            from app.schemas.operator_task import OperatorTaskCreate
            from app.services.operator_task_service import OperatorTaskService

            templates = CommunicationCrmService.TASK_TEMPLATES
            title, desc, prio = templates.get(
                data.task_type,
                ("Follow up on outreach", "Review outreach and follow up.", "medium"),
            )
            task = await OperatorTaskService.create_task(
                db,
                OperatorTaskCreate(
                    client_id=outreach.client_id,
                    source_type="outreach",
                    source_id=outreach.id,
                    title=data.title or title,
                    description=data.description or desc,
                    priority=data.priority or prio,
                    due_at=data.due_at,
                ),
            )
            result = {
                "task_id": UUID(str(task["id"])),
                "title": task["title"],
                "task_type": data.task_type,
            }

        logger.info("%s task created: id=%s task=%s", MARKER, raw_id, result["task_id"])
        return {
            "id": raw_id,
            "task_id": result["task_id"],
            "title": result["title"],
            "task_type": result["task_type"],
            "message": "Task created from conversation.",
        }
