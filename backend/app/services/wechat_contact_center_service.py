"""WeChat Contact Center v1 — manual copy/paste workflow, AI drafts only."""
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
from app.models.communication import (
    CommunicationContact,
    CommunicationMessage,
    CommunicationThread,
)
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.proposal_document import ProposalDocument
from app.models.sales_playbook import SalesPlaybook
from app.schemas.communication import WECHAT_CHANNELS
from app.schemas.wechat_contact_center import (
    WeChatContactCreate,
    WeChatCreateLeadRequest,
    WeChatGenerateReplyRequest,
    WeChatPasteInboundRequest,
    WeChatThreadCreate,
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

MARKER = "[WeChat Center]"

_REPLY_SYSTEM = """\
You draft WeChat/WeCom replies for a B2B export sales operator.
The operator copies your text manually into WeChat — NEVER imply the message was sent.
Do NOT suggest automation, scraping, or unofficial WeChat tools.

Return ONLY JSON:
{
  "language": "zh|ru|en|uz",
  "reply_text": "complete reply ready to paste into WeChat",
  "tone": "professional|friendly|formal|consultative",
  "recommended_next_action": "single imperative next step for operator",
  "risk_flags": ["optional short risk strings, empty array if none"]
}

Rules:
- Match contact preferred language when known; Chinese buyers prefer zh unless they write in English
- WeChat style: concise, polite, clear next step; avoid overly long blocks
- Use thread history and CRM context only — do not invent prices, MOQ, or delivery dates
- Flag risks: price commitment without approval, missing specs, language mismatch, stale follow-up
- Draft only — operator sends manually
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sync_wechat_fields(contact: CommunicationContact, data: WeChatContactCreate) -> None:
    if data.wechat_id and not contact.wechat:
        contact.wechat = data.wechat_id
    if data.wechat_id:
        contact.wechat_id = data.wechat_id
    if data.wecom_id:
        contact.wecom_id = data.wecom_id
    if data.qr_code_url:
        contact.qr_code_url = data.qr_code_url
    if data.preferred_language:
        contact.preferred_language = data.preferred_language
        if not contact.language:
            contact.language = data.preferred_language
    if data.company and not contact.company:
        contact.company = data.company
    if data.country and not contact.country:
        contact.country = data.country


def _heuristic_reply(
    thread: CommunicationThread,
    contact: CommunicationContact | None,
) -> dict[str, Any]:
    lang = (contact.preferred_language if contact else None) or (contact.language if contact else None) or "zh"
    name = contact.name if contact else "there"
    if lang == "zh":
        reply = f"您好 {name}，感谢您的消息。我们会尽快查看并回复您。请问方便提供更多产品规格或数量需求吗？"
    elif lang == "ru":
        reply = f"Здравствуйте, {name}! Спасибо за сообщение. Мы изучим запрос и ответим в ближайшее время."
    else:
        reply = f"Hello {name}, thank you for your message. We will review and get back to you shortly."
    return {
        "language": lang,
        "reply_text": reply,
        "tone": "professional",
        "recommended_next_action": "Review thread context and paste reply manually in WeChat.",
        "risk_flags": ["demo_mode"],
    }


async def _deal_title_map(db: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    r = await db.execute(select(CrmDeal.id, CrmDeal.title).where(CrmDeal.id.in_(ids)))
    return {row[0]: row[1] for row in r.all()}


async def _load_wechat_thread(
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
    if thread.channel not in WECHAT_CHANNELS:
        raise HTTPException(status_code=400, detail="Thread is not a WeChat/WeCom channel")
    if tenant_id is not None:
        client_ids = await tenant_client_ids(db, tenant_id)
        if thread.tenant_id != tenant_id and thread.client_id not in client_ids:
            raise HTTPException(status_code=403, detail="Thread not in tenant scope")
    return thread


async def _build_ai_context(db: AsyncSession, thread: CommunicationThread) -> str:
    contact = thread.contact
    parts: list[str] = [
        f"THREAD: {thread.title}",
        f"CHANNEL: {thread.channel}",
    ]
    if contact:
        parts.append(
            "CONTACT: "
            + ", ".join(
                f"{k}={v}"
                for k, v in {
                    "name": contact.name,
                    "company": contact.company,
                    "country": contact.country,
                    "wechat_id": contact.wechat_id or contact.wechat,
                    "wecom_id": contact.wecom_id,
                    "preferred_language": contact.preferred_language or contact.language,
                }.items()
                if v
            )
        )

    if thread.lead_id:
        lead = await CrmService.get_lead(db, thread.lead_id)
        parts.append(
            "LEAD: "
            + ", ".join(
                f"{k}={v}"
                for k, v in {
                    "name": lead.get("name"),
                    "status": lead.get("status"),
                    "priority": lead.get("priority"),
                    "interest": (lead.get("interest") or "")[:300],
                    "lead_score": lead.get("lead_score"),
                    "recommended_action": lead.get("recommended_action"),
                }.items()
                if v
            )
        )

    if thread.deal_id:
        deal = await DealService.get_deal(db, thread.deal_id)
        parts.append(
            "DEAL: "
            + ", ".join(
                f"{k}={v}"
                for k, v in {
                    "title": deal.get("title"),
                    "status": deal.get("status"),
                    "expected_value": deal.get("expected_value"),
                    "probability": deal.get("probability"),
                }.items()
                if v is not None
            )
        )

    if thread.lead_id:
        pr = await db.execute(
            select(ProposalDocument.title, ProposalDocument.status)
            .where(ProposalDocument.lead_id == thread.lead_id)
            .order_by(ProposalDocument.updated_at.desc())
            .limit(3)
        )
        proposals = pr.all()
        if proposals:
            parts.append(
                "PROPOSALS: "
                + "; ".join(f"{title} ({status})" for title, status in proposals)
            )

    if thread.client_id:
        pb = await db.execute(
            select(SalesPlaybook.name)
            .where(
                SalesPlaybook.status == "active",
                or_(
                    SalesPlaybook.client_id == thread.client_id,
                    SalesPlaybook.client_id.is_(None),
                ),
            )
            .order_by(SalesPlaybook.updated_at.desc())
            .limit(1)
        )
        playbook_name = pb.scalar_one_or_none()
        if playbook_name:
            parts.append(f"SALES_PLAYBOOK: {playbook_name}")

    transcript = "\n".join(
        f"[{m.direction}] {m.sender_name}: {m.message_text[:500]}"
        for m in (thread.messages or [])[-20:]
    )
    parts.append(f"MESSAGES:\n{transcript or '(none)'}")
    return "\n\n".join(parts)


async def _build_ai_panel(db: AsyncSession, thread: CommunicationThread) -> dict[str, Any]:
    messages = thread.messages or []
    inbound = [m.message_text for m in messages if m.direction == "inbound"][-5:]
    summary = " ".join(inbound)[:400] if inbound else "No inbound messages yet."
    next_action = "Paste the latest WeChat message from the contact."
    if thread.lead_id:
        lead = await CrmService.get_lead(db, thread.lead_id)
        if lead.get("recommended_action"):
            next_action = str(lead["recommended_action"])[:500]
        elif lead.get("ai_summary"):
            summary = str(lead["ai_summary"])[:400]
    proposal_count = 0
    if thread.lead_id:
        pc = await db.execute(
            select(func.count()).select_from(ProposalDocument).where(
                ProposalDocument.lead_id == thread.lead_id
            )
        )
        proposal_count = pc.scalar_one()

    playbook_name = None
    if thread.client_id:
        pb = await db.execute(
            select(SalesPlaybook.name)
            .where(
                SalesPlaybook.status == "active",
                or_(
                    SalesPlaybook.client_id == thread.client_id,
                    SalesPlaybook.client_id.is_(None),
                ),
            )
            .order_by(SalesPlaybook.updated_at.desc())
            .limit(1)
        )
        playbook_name = pb.scalar_one_or_none()

    return {
        "summary": summary,
        "recommended_next_action": next_action,
        "sentiment": "neutral",
        "has_linked_lead": bool(thread.lead_id),
        "has_linked_deal": bool(thread.deal_id),
        "proposal_count": proposal_count,
        "playbook_name": playbook_name,
    }


class WeChatContactCenterService:
    @staticmethod
    async def list_contacts(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
        search: str | None = None,
        channel: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        wechat_filter = or_(
            CommunicationContact.wechat_id.isnot(None),
            CommunicationContact.wecom_id.isnot(None),
            CommunicationContact.wechat.isnot(None),
        )
        q = select(CommunicationContact).where(wechat_filter)
        count_q = select(func.count()).select_from(CommunicationContact).where(wechat_filter)
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
                | CommunicationContact.wechat_id.ilike(like)
                | CommunicationContact.wecom_id.ilike(like)
                | CommunicationContact.wechat.ilike(like)
            )
            q = q.where(filt)
            count_q = count_q.where(filt)
        if channel and channel in WECHAT_CHANNELS:
            thread_contact_ids = select(CommunicationThread.contact_id).where(
                CommunicationThread.channel == channel
            )
            q = q.where(CommunicationContact.id.in_(thread_contact_ids))
            count_q = count_q.where(CommunicationContact.id.in_(thread_contact_ids))

        total = (await db.execute(count_q)).scalar_one()
        contacts = list(
            (await db.execute(
                q.order_by(CommunicationContact.updated_at.desc()).offset(skip).limit(limit)
            )).scalars().all()
        )

        contact_ids = [c.id for c in contacts]
        thread_counts: dict[UUID, int] = {}
        if contact_ids:
            tc = await db.execute(
                select(CommunicationThread.contact_id, func.count())
                .where(
                    CommunicationThread.contact_id.in_(contact_ids),
                    CommunicationThread.channel.in_(WECHAT_CHANNELS),
                )
                .group_by(CommunicationThread.contact_id)
            )
            thread_counts = {row[0]: row[1] for row in tc.all()}

        client_names = await _client_name_map(db, {c.client_id for c in contacts if c.client_id})
        lead_names = await _lead_name_map(db, {c.lead_id for c in contacts if c.lead_id})

        items = [
            _serialize_contact(
                c,
                client_name=client_names.get(c.client_id) if c.client_id else None,
                lead_name=lead_names.get(c.lead_id) if c.lead_id else None,
                thread_count=thread_counts.get(c.id, 0),
            )
            for c in contacts
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def create_contact(
        db: AsyncSession,
        data: WeChatContactCreate,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        if data.channel not in WECHAT_CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid WeChat channel")

        existing = None
        if data.wechat_id:
            r = await db.execute(
                select(CommunicationContact).where(CommunicationContact.wechat_id == data.wechat_id).limit(1)
            )
            existing = r.scalar_one_or_none()
        if not existing and data.wecom_id:
            r = await db.execute(
                select(CommunicationContact).where(CommunicationContact.wecom_id == data.wecom_id).limit(1)
            )
            existing = r.scalar_one_or_none()

        if existing:
            _sync_wechat_fields(existing, data)
            if data.name:
                existing.name = data.name
            existing.updated_at = _utcnow()
            await db.commit()
            await db.refresh(existing)
            logger.info("%s contact created: id=%s name=%s (existing)", MARKER, existing.id, existing.name)
            return _serialize_contact(existing)

        contact = CommunicationContact(
            tenant_id=tenant_id,
            name=data.name,
            client_id=data.client_id,
            lead_id=data.lead_id,
            company=data.company,
            country=data.country,
            phone=data.phone,
            email=data.email,
            notes=data.notes,
            wechat_id=data.wechat_id,
            wecom_id=data.wecom_id,
            qr_code_url=data.qr_code_url,
            preferred_language=data.preferred_language,
            language=data.preferred_language,
            wechat=data.wechat_id,
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        logger.info("%s contact created: id=%s name=%s", MARKER, contact.id, contact.name)
        return _serialize_contact(contact)

    @staticmethod
    async def list_threads(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
        contact_id: UUID | None = None,
        channel: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        return await WeChatContactCenterService.list_all_threads(
            db,
            tenant_id=tenant_id,
            client_id=client_id,
            contact_id=contact_id,
            channel=channel,
            status=status,
            skip=skip,
            limit=limit,
        )

    @staticmethod
    async def list_all_threads(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
        contact_id: UUID | None = None,
        channel: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        channels = [channel] if channel in WECHAT_CHANNELS else list(WECHAT_CHANNELS)
        q = select(CommunicationThread).where(CommunicationThread.channel.in_(channels))
        count_q = select(func.count()).select_from(CommunicationThread).where(
            CommunicationThread.channel.in_(channels)
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
        data: WeChatThreadCreate,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        if data.channel not in WECHAT_CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid WeChat channel")

        cr = await db.execute(
            select(CommunicationContact).where(CommunicationContact.id == data.contact_id)
        )
        contact = cr.scalar_one_or_none()
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")

        tr = await db.execute(
            select(CommunicationThread).where(
                CommunicationThread.contact_id == data.contact_id,
                CommunicationThread.channel == data.channel,
            ).limit(1)
        )
        existing = tr.scalar_one_or_none()
        if existing:
            if data.lead_id:
                existing.lead_id = data.lead_id
            if data.deal_id:
                existing.deal_id = data.deal_id
            if data.client_id:
                existing.client_id = data.client_id
            if data.external_contact_id:
                existing.external_contact_id = data.external_contact_id
            existing.updated_at = _utcnow()
            await db.commit()
            await db.refresh(existing)
            return _serialize_thread(existing)

        title = data.title or f"WeChat — {contact.name}"
        thread = CommunicationThread(
            tenant_id=tenant_id or contact.tenant_id,
            contact_id=data.contact_id,
            client_id=data.client_id or contact.client_id,
            lead_id=data.lead_id or contact.lead_id,
            deal_id=data.deal_id,
            channel=data.channel,
            external_contact_id=data.external_contact_id,
            title=title,
            status="open",
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
        logger.info("%s thread created: id=%s channel=%s", MARKER, thread.id, thread.channel)
        return _serialize_thread(thread)

    @staticmethod
    async def get_thread(
        db: AsyncSession,
        thread_id: UUID,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        thread = await _load_wechat_thread(db, thread_id, tenant_id=tenant_id)
        client_name = None
        if thread.client_id:
            cm = await _client_name_map(db, {thread.client_id})
            client_name = cm.get(thread.client_id)
        lead_name = None
        if thread.lead_id:
            lm = await _lead_name_map(db, {thread.lead_id})
            lead_name = lm.get(thread.lead_id)
        deal_title = None
        if thread.deal_id:
            dm = await _deal_title_map(db, {thread.deal_id})
            deal_title = dm.get(thread.deal_id)

        messages = [_serialize_message(m) for m in thread.messages]
        last_preview = _preview(messages[-1]["message_text"]) if messages else None
        contact_data = _serialize_contact(thread.contact) if thread.contact else None
        ai_panel = await _build_ai_panel(db, thread)

        return {
            **_serialize_thread(
                thread,
                contact_name=thread.contact.name if thread.contact else None,
                client_name=client_name,
                lead_name=lead_name,
                message_count=len(messages),
                last_message_preview=last_preview,
            ),
            "deal_title": deal_title,
            "messages": messages,
            "contact": contact_data,
            "ai_panel": ai_panel,
        }

    @staticmethod
    async def paste_inbound(
        db: AsyncSession,
        thread_id: UUID,
        data: WeChatPasteInboundRequest,
    ) -> dict[str, Any]:
        thread = await _load_wechat_thread(db, thread_id)
        sender = (data.sender_name or "").strip() or (thread.contact.name if thread.contact else "Contact")
        now = _utcnow()
        msg = CommunicationMessage(
            thread_id=thread_id,
            direction="inbound",
            sender_name=sender,
            message_text=data.message_text.strip(),
            original_language=data.original_language,
            translated_text=data.translated_text,
        )
        db.add(msg)
        thread.last_message_at = now
        thread.last_manual_sync_at = now
        thread.updated_at = now
        if thread.status == "closed":
            thread.status = "open"
        if thread.contact:
            thread.contact.updated_at = now

        if thread.lead_id:
            try:
                await CommunicationCrmService.sync_message_activity(db, thread, msg)
            except Exception as exc:
                logger.debug("%s activity sync skipped: %s", MARKER, exc)

        await db.commit()
        await db.refresh(msg)
        logger.info("%s inbound pasted: thread=%s message=%s", MARKER, thread_id, msg.id)
        return _serialize_message(msg)

    @staticmethod
    async def generate_reply(
        db: AsyncSession,
        thread_id: UUID,
        data: WeChatGenerateReplyRequest | None = None,
    ) -> dict[str, Any]:
        thread = await _load_wechat_thread(db, thread_id)
        if not thread.messages:
            raise HTTPException(status_code=400, detail="Thread has no messages — paste inbound first")

        context = await _build_ai_context(db, thread)
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
                "language": str(parsed.get("language") or "zh")[:10],
                "reply_text": str(parsed.get("reply_text") or "")[:4000],
                "tone": str(parsed.get("tone") or "professional")[:50],
                "recommended_next_action": str(parsed.get("recommended_next_action") or "")[:500],
                "risk_flags": [str(f)[:200] for f in risk_flags[:10]],
            }
            if not result["reply_text"]:
                raise ValueError("empty reply")
        except Exception as exc:
            demo_mode = True
            logger.info("%s reply generated fallback: %s", MARKER, exc)
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
        )
        db.add(msg)
        thread.updated_at = _utcnow()
        await db.commit()
        await db.refresh(msg)
        logger.info("%s reply generated: thread=%s message=%s demo=%s", MARKER, thread_id, msg.id, demo_mode)
        return {
            "message_id": msg.id,
            **result,
            "demo_mode": demo_mode,
        }

    @staticmethod
    async def mark_copied(db: AsyncSession, message_id: UUID) -> dict[str, Any]:
        r = await db.execute(select(CommunicationMessage).where(CommunicationMessage.id == message_id))
        msg = r.scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        if msg.direction not in ("draft", "outbound"):
            raise HTTPException(status_code=400, detail="Only draft/outbound messages can be marked copied")
        now = _utcnow()
        msg.copied_at = now
        await db.commit()
        logger.info("%s reply copied: message=%s", MARKER, message_id)
        return {"message_id": msg.id, "copied_at": now}

    @staticmethod
    async def mark_manually_sent(db: AsyncSession, message_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(CommunicationMessage)
            .options(selectinload(CommunicationMessage.thread))
            .where(CommunicationMessage.id == message_id)
        )
        msg = r.scalar_one_or_none()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        if msg.direction not in ("draft", "outbound"):
            raise HTTPException(status_code=400, detail="Only draft/outbound messages can be marked sent")

        thread = msg.thread
        if thread and thread.channel not in WECHAT_CHANNELS:
            raise HTTPException(status_code=400, detail="Message thread is not WeChat/WeCom")

        now = _utcnow()
        msg.manual_sent_at = now
        msg.direction = "outbound"
        msg.sender_name = "Operator"
        if thread:
            thread.last_message_at = now
            thread.last_manual_sync_at = now
            thread.updated_at = now

        if thread and thread.lead_id:
            try:
                await CommunicationCrmService.sync_message_activity(db, thread, msg)
            except Exception as exc:
                logger.debug("%s activity sync skipped: %s", MARKER, exc)

        await db.commit()
        logger.info("%s manually sent: message=%s", MARKER, message_id)
        return {"message_id": msg.id, "manual_sent_at": now, "direction": "outbound"}

    @staticmethod
    async def create_lead(
        db: AsyncSession,
        thread_id: UUID,
        data: WeChatCreateLeadRequest | None = None,
    ) -> dict[str, Any]:
        thread = await _load_wechat_thread(db, thread_id)
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
                lead.source = "wechat" if thread.channel == "wechat" else "wecom"
                await db.commit()

        logger.info("%s lead created: thread=%s lead=%s", MARKER, thread_id, result["lead_id"])
        return result

    @staticmethod
    async def link_lead(db: AsyncSession, thread_id: UUID, lead_id: UUID) -> dict[str, Any]:
        await _load_wechat_thread(db, thread_id)
        result = await CommunicationHubService.link_lead(db, thread_id, lead_id)
        logger.info("%s lead linked: thread=%s lead=%s", MARKER, thread_id, lead_id)
        return {
            "thread_id": thread_id,
            "lead_id": result["lead_id"],
            "lead_name": result["lead_name"],
        }

    @staticmethod
    async def link_deal(db: AsyncSession, thread_id: UUID, deal_id: UUID) -> dict[str, Any]:
        thread = await _load_wechat_thread(db, thread_id)
        deal = await DealService.get_deal(db, deal_id)
        thread.deal_id = deal_id
        if not thread.lead_id:
            thread.lead_id = deal["lead_id"]
        if not thread.client_id:
            thread.client_id = deal["client_id"]
        await db.commit()
        logger.info("%s deal linked: thread=%s deal=%s", MARKER, thread_id, deal_id)
        return {
            "thread_id": thread_id,
            "deal_id": deal_id,
            "deal_title": deal["title"],
            "lead_id": deal["lead_id"],
        }
