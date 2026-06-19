"""Communication Hub → CRM automation — extract, lead/task creation, reply suggestions."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.communication import CommunicationContact, CommunicationMessage, CommunicationThread
from app.models.crm_lead import CrmLead
from app.schemas.communication import CommunicationCrmCreateLeadRequest, CommunicationCrmCreateTaskRequest
from app.schemas.crm import CrmActivityCreate, CrmLeadCreate, CrmLeadUpdate
from app.schemas.operator_task import OperatorTaskCreate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.crm_service import CrmService
from app.services.operator_task_service import OperatorTaskService

logger = logging.getLogger(__name__)

CRM_MARKER = "[Comm CRM]"

_EXTRACT_SYSTEM = """\
You extract CRM lead data from buyer/client communication threads for a B2B export team.
Advisory only — never auto-contact or auto-send messages.

Return ONLY JSON:
{
  "name": "contact person name or null",
  "company": "company name or null",
  "phone": "phone or null",
  "email": "email or null",
  "telegram": "telegram handle or null",
  "whatsapp": "whatsapp or null",
  "wechat": "wechat id or null",
  "country": "country or null",
  "language": "ru|uz|en|zh or null",
  "interest": "product/service interest summary",
  "urgency": "high|medium|low",
  "budget": "budget amount/text mentioned or null",
  "next_follow_up_at": "ISO8601 datetime or null",
  "suggested_status": "new|contacted|qualified|proposal_sent|negotiation",
  "suggested_priority": "high|medium|low"
}

Rules:
- Extract only facts present in messages or contact profile context
- Do not invent phone numbers or emails
- urgency high if deadline/urgent/large order mentioned
- suggested_status reflects conversation stage only
"""

_SUGGEST_REPLY_SYSTEM = """\
You draft a reply for an operator to review and send manually.
NEVER imply the message was already sent. Draft only.

Return ONLY JSON:
{
  "reply_text": "complete reply message in the contact's likely language (ru/uz/en/zh)"
}

Rules:
- Professional B2B export tone
- Match thread channel style (Telegram shorter, Email formal)
- Do not promise pricing not discussed
- End with clear next step when appropriate
- Operator will copy/send manually — not auto-sent
"""

TASK_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "follow_up": ("Follow up on conversation", "Review communication thread and follow up with contact.", "medium"),
    "send_catalog": ("Send product catalog", "Send product catalog to contact based on thread interest.", "medium"),
    "send_proposal": ("Send proposal", "Prepare and send commercial proposal to contact.", "high"),
    "request_details": ("Request more details", "Ask contact for missing specs, MOQ, or delivery details.", "medium"),
    "schedule_call": ("Schedule call", "Propose and schedule a call with the contact.", "high"),
}

LEAD_STATUSES = frozenset({"new", "contacted", "qualified", "proposal_sent", "negotiation", "won", "lost"})
LEAD_PRIORITIES = frozenset({"high", "medium", "low"})


def _thread_transcript(messages: list[CommunicationMessage], limit: int = 30) -> str:
    chunk = messages[-limit:]
    return "\n".join(
        f"[{m.direction}] {m.sender_name}: {m.message_text[:500]}"
        for m in chunk
    )


def _merge_contact_context(contact: CommunicationContact | None) -> str:
    if not contact:
        return ""
    parts = [f"CONTACT: {contact.name}"]
    for field in ("company", "phone", "telegram", "whatsapp", "wechat", "email", "country", "language"):
        val = getattr(contact, field, None)
        if val:
            parts.append(f"{field}: {val}")
    return "\n".join(parts)


def _heuristic_extract(
    messages: list[CommunicationMessage],
    contact: CommunicationContact | None,
) -> dict[str, Any]:
    combined = " ".join(m.message_text for m in messages[-10:])
    name = contact.name if contact else "Unknown contact"
    company = contact.company if contact else None
    return {
        "name": name,
        "company": company,
        "phone": contact.phone if contact else None,
        "email": contact.email if contact else None,
        "telegram": contact.telegram if contact else None,
        "whatsapp": contact.whatsapp if contact else None,
        "wechat": contact.wechat if contact else None,
        "country": contact.country if contact else None,
        "language": contact.language if contact else None,
        "interest": combined[:500] if combined else None,
        "urgency": "medium",
        "budget": None,
        "next_follow_up_at": None,
        "suggested_status": "new",
        "suggested_priority": "medium",
    }


def _normalize_extract(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("suggested_status") or "new").strip()
    if status not in LEAD_STATUSES:
        status = "new"
    priority = str(raw.get("suggested_priority") or raw.get("urgency") or "medium").strip()
    if priority not in LEAD_PRIORITIES:
        priority = "medium"
    follow_up = raw.get("next_follow_up_at")
    parsed_follow_up = None
    if follow_up:
        try:
            parsed_follow_up = datetime.fromisoformat(str(follow_up).replace("Z", "+00:00"))
        except ValueError:
            parsed_follow_up = None
    return {
        "name": str(raw.get("name") or "").strip() or None,
        "company": str(raw.get("company") or "").strip() or None,
        "phone": str(raw.get("phone") or "").strip() or None,
        "email": str(raw.get("email") or "").strip() or None,
        "telegram": str(raw.get("telegram") or "").strip() or None,
        "whatsapp": str(raw.get("whatsapp") or "").strip() or None,
        "wechat": str(raw.get("wechat") or "").strip() or None,
        "country": str(raw.get("country") or "").strip() or None,
        "language": str(raw.get("language") or "").strip() or None,
        "interest": str(raw.get("interest") or "").strip() or None,
        "urgency": str(raw.get("urgency") or priority).strip(),
        "budget": str(raw.get("budget") or "").strip() or None,
        "next_follow_up_at": parsed_follow_up.isoformat() if parsed_follow_up else None,
        "suggested_status": status,
        "suggested_priority": priority,
    }


def _parse_budget_value(budget: str | None) -> Decimal | None:
    if not budget:
        return None
    nums = re.findall(r"[\d,]+(?:\.\d+)?", budget.replace(" ", ""))
    if not nums:
        return None
    try:
        return Decimal(nums[0].replace(",", ""))
    except InvalidOperation:
        return None


async def _load_thread(db: AsyncSession, thread_id: UUID) -> CommunicationThread:
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
    return thread


class CommunicationCrmService:
    @staticmethod
    async def extract_crm(db: AsyncSession, thread_id: UUID) -> dict[str, Any]:
        thread = await _load_thread(db, thread_id)
        if not thread.messages:
            raise HTTPException(status_code=400, detail="Thread has no messages to extract from")

        transcript = _thread_transcript(thread.messages)
        contact_ctx = _merge_contact_context(thread.contact)
        demo_mode = False

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _EXTRACT_SYSTEM},
                    {"role": "user", "content": f"THREAD: {thread.title}\nCHANNEL: {thread.channel}\n\n{contact_ctx}\n\n{transcript}"},
                ],
                temperature=0.35,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            extracted = _normalize_extract(parsed)
        except Exception as exc:
            demo_mode = True
            logger.info("%s extracted fallback: %s", CRM_MARKER, exc)
            extracted = _normalize_extract(_heuristic_extract(thread.messages, thread.contact))

        logger.info("%s extracted: thread=%s demo=%s", CRM_MARKER, thread_id, demo_mode)
        return {**extracted, "demo_mode": demo_mode}

    @staticmethod
    async def create_lead_from_thread(
        db: AsyncSession,
        thread_id: UUID,
        data: CommunicationCrmCreateLeadRequest | None = None,
    ) -> dict[str, Any]:
        thread = await _load_thread(db, thread_id)
        payload = data.model_dump(exclude_unset=True) if data else {}
        contact = thread.contact

        if thread.lead_id:
            lead_row = await CrmService._load_lead(db, thread.lead_id)
            update_fields: dict[str, Any] = {}
            note_lines = [f"Communication Hub update from thread: {thread.title}"]

            for field in ("name", "company", "phone", "telegram", "email", "language", "interest", "notes"):
                val = payload.get(field)
                if val:
                    if field == "notes":
                        note_lines.append(str(val))
                    elif field in ("name", "company", "phone", "telegram", "email", "language", "interest"):
                        update_fields[field] = val

            if payload.get("suggested_status"):
                update_fields["status"] = payload["suggested_status"]
            if payload.get("suggested_priority"):
                update_fields["priority"] = payload["suggested_priority"]
            if payload.get("next_follow_up_at"):
                try:
                    update_fields["next_follow_up_at"] = datetime.fromisoformat(
                        str(payload["next_follow_up_at"]).replace("Z", "+00:00")
                    )
                except ValueError:
                    pass
            budget = payload.get("budget")
            if budget:
                note_lines.append(f"Budget mentioned: {budget}")
                ev = _parse_budget_value(str(budget))
                if ev is not None:
                    update_fields["estimated_value"] = ev

            merged_notes = (lead_row.notes or "").strip()
            append = "\n".join(note_lines)
            update_fields["notes"] = f"{merged_notes}\n\n{append}".strip() if merged_notes else append

            if update_fields:
                await CrmService.update_lead(db, lead_row.id, CrmLeadUpdate(**update_fields))
            if payload.get("attribution_link_id"):
                lr = await db.execute(select(CrmLead).where(CrmLead.id == lead_row.id))
                lead_entity = lr.scalar_one()
                from app.services.attribution_link_service import AttributionLinkService
                await AttributionLinkService.apply_to_lead(db, payload["attribution_link_id"], lead_entity)

            activity_content = f"Thread update: {thread.title}\n" + (payload.get("interest") or "Communication synced from hub.")
            await CrmService.add_activity(
                db,
                lead_row.id,
                CrmActivityCreate(type="note", content=activity_content[:2000]),
            )

            if contact:
                for field in ("phone", "telegram", "whatsapp", "wechat", "email", "country", "language", "company"):
                    val = payload.get(field)
                    if val and not getattr(contact, field, None):
                        setattr(contact, field, val)
                contact.lead_id = lead_row.id
            await db.commit()

            logger.info("%s lead created: thread=%s lead=%s (updated existing)", CRM_MARKER, thread_id, lead_row.id)
            return {
                "lead_id": lead_row.id,
                "lead_name": lead_row.name,
                "thread_id": thread_id,
                "created": False,
                "updated": True,
            }

        client_id = thread.client_id or (contact.client_id if contact else None)
        if not client_id:
            raise HTTPException(status_code=400, detail="Thread must have client_id to create CRM lead")

        channel = thread.channel
        if channel == "telegram":
            source = "telegram"
        elif channel in ("wechat", "wecom"):
            source = channel
        else:
            source = "manual"

        name = (
            payload.get("name")
            or (contact.name if contact else None)
            or "Unknown contact"
        )
        interest = payload.get("interest")
        if not interest and thread.messages:
            inbound = [m for m in thread.messages if m.direction == "inbound"]
            interest = "\n".join(m.message_text[:200] for m in inbound[-5:])[:1000] or None

        notes_parts = [f"Created from Communication Hub thread: {thread.title}"]
        if payload.get("budget"):
            notes_parts.append(f"Budget: {payload['budget']}")
        if payload.get("urgency"):
            notes_parts.append(f"Urgency: {payload['urgency']}")

        next_follow_up = None
        if payload.get("next_follow_up_at"):
            try:
                next_follow_up = datetime.fromisoformat(
                    str(payload["next_follow_up_at"]).replace("Z", "+00:00")
                )
            except ValueError:
                pass

        lead = await CrmService.create_lead(
            db,
            CrmLeadCreate(
                client_id=client_id,
                name=name,
                company=payload.get("company") or (contact.company if contact else None),
                phone=payload.get("phone") or (contact.phone if contact else None),
                telegram=payload.get("telegram") or (contact.telegram if contact else None),
                email=payload.get("email") or (contact.email if contact else None),
                source=source,
                language=payload.get("language") or (contact.language if contact else None),
                interest=interest,
                notes="\n".join(notes_parts),
                status=payload.get("suggested_status") or "new",
                priority=payload.get("suggested_priority") or "medium",
                estimated_value=_parse_budget_value(str(payload.get("budget") or "")),
                next_follow_up_at=next_follow_up,
                attribution_link_id=payload.get("attribution_link_id"),
            ),
        )

        thread.lead_id = lead["id"]
        if contact:
            contact.lead_id = lead["id"]
            for field in ("phone", "telegram", "whatsapp", "wechat", "email", "country", "language", "company"):
                val = payload.get(field)
                if val and not getattr(contact, field, None):
                    setattr(contact, field, val)
        await db.commit()

        logger.info("%s lead created: thread=%s lead=%s", CRM_MARKER, thread_id, lead["id"])
        return {
            "lead_id": lead["id"],
            "lead_name": lead["name"],
            "thread_id": thread_id,
            "created": True,
            "updated": False,
        }

    @staticmethod
    async def create_task(
        db: AsyncSession,
        thread_id: UUID,
        data: CommunicationCrmCreateTaskRequest,
    ) -> dict[str, Any]:
        thread = await _load_thread(db, thread_id)
        client_id = thread.client_id or (thread.contact.client_id if thread.contact else None)
        if not client_id:
            raise HTTPException(status_code=400, detail="Thread must have client_id to create task")

        task_type = data.task_type
        if task_type not in TASK_TEMPLATES:
            raise HTTPException(status_code=400, detail="Invalid task_type")

        title, description, default_priority = TASK_TEMPLATES[task_type]
        description = f"{description}\n\nThread: {thread.title} (id={thread_id})"
        if data.description:
            description = f"{data.description}\n\n{description}"

        task = await OperatorTaskService.create_task(
            db,
            OperatorTaskCreate(
                client_id=client_id,
                source_type="communication_hub",
                source_id=None,
                title=data.title or title,
                description=description[:4000],
                priority=data.priority or default_priority,
                due_at=data.due_at,
                created_by="admin",
            ),
        )
        await db.commit()
        logger.info("%s task created: thread=%s task=%s type=%s", CRM_MARKER, thread_id, task["id"], task_type)
        return {"task_id": task["id"], "title": task["title"], "thread_id": thread_id, "task_type": task_type}

    @staticmethod
    async def suggest_reply(db: AsyncSession, thread_id: UUID) -> dict[str, Any]:
        thread = await _load_thread(db, thread_id)
        if not thread.messages:
            raise HTTPException(status_code=400, detail="Thread has no messages")

        transcript = _thread_transcript(thread.messages)
        contact_ctx = _merge_contact_context(thread.contact)
        demo_mode = False
        reply_text = ""

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _SUGGEST_REPLY_SYSTEM},
                    {"role": "user", "content": f"CHANNEL: {thread.channel}\n{contact_ctx}\n\n{transcript}"},
                ],
                temperature=0.6,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            reply_text = str(parsed.get("reply_text") or "").strip()
            if not reply_text:
                raise ValueError("empty reply")
        except Exception as exc:
            demo_mode = True
            logger.info("%s reply suggested fallback: %s", CRM_MARKER, exc)
            reply_text = (
                "Thank you for your message. We have reviewed your inquiry and will follow up shortly "
                "with the requested information. Please let us know if you have any additional requirements."
            )

        logger.info("%s reply suggested: thread=%s demo=%s", CRM_MARKER, thread_id, demo_mode)
        return {"reply_text": reply_text, "demo_mode": demo_mode}

    @staticmethod
    async def sync_message_activity(
        db: AsyncSession,
        thread: CommunicationThread,
        msg: CommunicationMessage,
    ) -> bool:
        if not thread.lead_id:
            return False
        activity_type = "note" if msg.direction == "internal_note" else "message"
        preview = msg.message_text[:500] + ("…" if len(msg.message_text) > 500 else "")
        content = (
            f"[Communication Hub — {msg.direction}]\n"
            f"From: {msg.sender_name}\n"
            f"Thread: {thread.title}\n\n{preview}"
        )
        await CrmService.add_activity(
            db,
            thread.lead_id,
            CrmActivityCreate(type=activity_type, content=content),
        )
        logger.info("%s activity synced: thread=%s lead=%s", CRM_MARKER, thread.id, thread.lead_id)
        return True
