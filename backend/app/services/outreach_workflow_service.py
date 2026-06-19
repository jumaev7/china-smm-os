"""Outreach → Communication & Follow-up workflow — manual send only."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.buyer_outreach import BuyerOutreachMessage, OutreachEvent
from app.models.communication import CommunicationContact, CommunicationMessage, CommunicationThread
from app.schemas.crm import CrmActivityCreate
from app.schemas.operator_task import OperatorTaskCreate
from app.schemas.outreach import (
    OutreachCreateFollowUpRequest,
    OutreachLinkThreadRequest,
    OutreachMarkSentRequest,
)
from app.services.buyer_outreach_service import BuyerOutreachService, _serialize
from app.services.crm_service import CrmService
from app.services.operator_task_service import OperatorTaskService

logger = logging.getLogger(__name__)

MARKER = "[Outreach Workflow]"
FOLLOW_UP_DAYS = 3

EVENT_TYPES = frozenset({
    "generated",
    "approved",
    "copied",
    "sent",
    "follow_up_created",
    "thread_linked",
})

OUTREACH_TO_COMM_CHANNEL = {
    "email": "email",
    "whatsapp": "whatsapp",
    "wechat": "wechat",
    "linkedin": "manual",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _comm_channel(outreach_channel: str) -> str:
    return OUTREACH_TO_COMM_CHANNEL.get(outreach_channel, "manual")


def _buyer_label(outreach: BuyerOutreachMessage) -> str:
    return (outreach.buyer_company or outreach.buyer_name or "Buyer").strip()


def _serialize_event(event: OutreachEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "payload_json": event.payload_json,
        "created_at": event.created_at,
    }


async def _log_event(
    db: AsyncSession,
    outreach_id: UUID,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> OutreachEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Invalid event type: {event_type}")
    event = OutreachEvent(
        outreach_id=outreach_id,
        event_type=event_type,
        payload_json=payload,
    )
    db.add(event)
    await db.flush()
    return event


def _follow_up_description(outreach: BuyerOutreachMessage) -> str:
    parts = [f"Outreach id: {outreach.id}"]
    if outreach.lead_id:
        parts.append(f"Lead id: {outreach.lead_id}")
    if outreach.product_id:
        parts.append(f"Product id: {outreach.product_id}")
    if outreach.proposal_id:
        parts.append(f"Proposal id: {outreach.proposal_id}")
    return " · ".join(parts)


class OutreachWorkflowService:
    @staticmethod
    async def log_generated(db: AsyncSession, outreach_id: UUID) -> None:
        await _log_event(db, outreach_id, "generated")
        await db.flush()

    @staticmethod
    async def _create_follow_up_task(
        db: AsyncSession,
        outreach: BuyerOutreachMessage,
        due_at: datetime,
    ) -> dict[str, Any] | None:
        title = f"Follow up outreach: {_buyer_label(outreach)}"[:255]
        try:
            return await OperatorTaskService.create_task(
                db,
                OperatorTaskCreate(
                    client_id=outreach.client_id,
                    source_type="outreach",
                    source_id=outreach.id,
                    title=title,
                    description=_follow_up_description(outreach),
                    due_at=due_at,
                    created_by="admin",
                ),
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                logger.info("%s follow-up task already exists: outreach=%s", MARKER, outreach.id)
                return None
            raise

    @staticmethod
    async def _find_or_create_thread(
        db: AsyncSession,
        outreach: BuyerOutreachMessage,
    ) -> UUID:
        if outreach.communication_thread_id:
            r = await db.execute(
                select(CommunicationThread).where(
                    CommunicationThread.id == outreach.communication_thread_id,
                )
            )
            if r.scalar_one_or_none():
                return outreach.communication_thread_id

        comm_channel = _comm_channel(outreach.channel)

        if outreach.lead_id:
            tr = await db.execute(
                select(CommunicationThread)
                .where(
                    CommunicationThread.lead_id == outreach.lead_id,
                    CommunicationThread.channel == comm_channel,
                )
                .order_by(CommunicationThread.updated_at.desc())
                .limit(1)
            )
            existing = tr.scalar_one_or_none()
            if existing:
                return existing.id

        contact: CommunicationContact | None = None
        if outreach.lead_id:
            cr = await db.execute(
                select(CommunicationContact)
                .where(CommunicationContact.lead_id == outreach.lead_id)
                .limit(1)
            )
            contact = cr.scalar_one_or_none()

        if not contact:
            contact = CommunicationContact(
                client_id=outreach.client_id,
                lead_id=outreach.lead_id,
                name=(outreach.buyer_name or outreach.buyer_company or "Buyer")[:255],
                company=outreach.buyer_company,
                country=outreach.country,
                language=outreach.language,
            )
            db.add(contact)
            await db.flush()
            contact_id = contact.id
        else:
            contact_id = contact.id

        title = f"Outreach: {_buyer_label(outreach)}"[:255]
        thread = CommunicationThread(
            contact_id=contact_id,
            channel=comm_channel,
            title=title,
            client_id=outreach.client_id,
            lead_id=outreach.lead_id,
            status="open",
        )
        db.add(thread)
        await db.flush()
        return thread.id

    @staticmethod
    async def _add_outbound_message(
        db: AsyncSession,
        thread_id: UUID,
        outreach: BuyerOutreachMessage,
    ) -> None:
        r = await db.execute(select(CommunicationThread).where(CommunicationThread.id == thread_id))
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        sender = outreach.client.company_name if outreach.client else "Operator"
        body = outreach.message_text
        if outreach.subject:
            body = f"Subject: {outreach.subject}\n\n{body}"
        body = f"[Outreach sent manually — not auto-delivered]\n\n{body}"

        msg = CommunicationMessage(
            thread_id=thread_id,
            direction="outbound",
            sender_name=sender[:255],
            message_text=body,
        )
        db.add(msg)
        now = _now()
        thread.last_message_at = now
        thread.updated_at = now
        await db.flush()

    @staticmethod
    async def approve(db: AsyncSession, outreach_id: UUID) -> dict[str, Any]:
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        if outreach.status == "archived":
            raise HTTPException(status_code=400, detail="Cannot approve archived outreach")
        if outreach.status == "sent":
            raise HTTPException(status_code=400, detail="Outreach already marked as sent")

        now = _now()
        outreach.status = "approved"
        outreach.approved_at = now
        outreach.last_action_at = now
        outreach.updated_at = now
        await _log_event(db, outreach_id, "approved")

        if outreach.lead_id:
            await CrmService.add_activity(
                db,
                outreach.lead_id,
                CrmActivityCreate(
                    type="note",
                    content=f"Outreach approved for {_buyer_label(outreach)} ({outreach.channel})",
                ),
            )

        await db.commit()
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        logger.info("%s approved: id=%s", MARKER, outreach_id)
        return {
            "outreach": _serialize(outreach),
            "follow_up_task_id": outreach.follow_up_task_id,
            "communication_thread_id": outreach.communication_thread_id,
            "message": "Outreach approved. No message was sent.",
        }

    @staticmethod
    async def mark_copied(db: AsyncSession, outreach_id: UUID) -> dict[str, Any]:
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        if outreach.status == "archived":
            raise HTTPException(status_code=400, detail="Cannot update archived outreach")

        now = _now()
        outreach.copied_at = now
        outreach.last_action_at = now
        outreach.updated_at = now
        await _log_event(db, outreach_id, "copied")

        await db.commit()
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        logger.info("%s copied: id=%s", MARKER, outreach_id)
        return {
            "outreach": _serialize(outreach),
            "follow_up_task_id": outreach.follow_up_task_id,
            "communication_thread_id": outreach.communication_thread_id,
            "message": "Copy event recorded.",
        }

    @staticmethod
    async def mark_sent(
        db: AsyncSession,
        outreach_id: UUID,
        data: OutreachMarkSentRequest | None = None,
    ) -> dict[str, Any]:
        body = data or OutreachMarkSentRequest()
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        if outreach.status == "archived":
            raise HTTPException(status_code=400, detail="Cannot mark archived outreach as sent")
        if outreach.status == "sent":
            raise HTTPException(status_code=400, detail="Outreach already marked as sent")

        now = _now()
        outreach.status = "sent"
        outreach.sent_at = now
        outreach.last_action_at = now
        if not outreach.approved_at:
            outreach.approved_at = now
        outreach.updated_at = now

        thread_id = outreach.communication_thread_id
        if not thread_id:
            thread_id = await OutreachWorkflowService._find_or_create_thread(db, outreach)
            outreach.communication_thread_id = thread_id

        await OutreachWorkflowService._add_outbound_message(db, thread_id, outreach)
        await _log_event(
            db,
            outreach_id,
            "sent",
            {"communication_thread_id": str(thread_id), "channel": outreach.channel},
        )

        follow_up_task_id = outreach.follow_up_task_id
        if body.create_follow_up_task and not follow_up_task_id:
            due = now + timedelta(days=FOLLOW_UP_DAYS)
            task = await OutreachWorkflowService._create_follow_up_task(db, outreach, due)
            if task:
                follow_up_task_id = UUID(str(task["id"]))
                outreach.follow_up_task_id = follow_up_task_id
                await _log_event(
                    db,
                    outreach_id,
                    "follow_up_created",
                    {"task_id": str(follow_up_task_id), "due_at": due.isoformat()},
                )

        if outreach.lead_id:
            await CrmService.add_activity(
                db,
                outreach.lead_id,
                CrmActivityCreate(
                    type="message",
                    content=f"Outreach sent via {outreach.channel}: {_buyer_label(outreach)}",
                ),
            )

        await db.commit()
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        logger.info("%s marked sent: id=%s thread=%s", MARKER, outreach_id, thread_id)
        return {
            "outreach": _serialize(outreach),
            "follow_up_task_id": follow_up_task_id,
            "communication_thread_id": thread_id,
            "message": "Marked as sent. Operator confirmed manual delivery — nothing was auto-sent.",
        }

    @staticmethod
    async def create_follow_up(
        db: AsyncSession,
        outreach_id: UUID,
        data: OutreachCreateFollowUpRequest | None = None,
    ) -> dict[str, Any]:
        body = data or OutreachCreateFollowUpRequest()
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        due = body.due_at or (_now() + timedelta(days=FOLLOW_UP_DAYS))

        if outreach.follow_up_task_id:
            existing = await OperatorTaskService._find_by_source(db, "outreach", outreach.id)
            if existing and existing.id == outreach.follow_up_task_id:
                raise HTTPException(status_code=409, detail="Follow-up task already linked to this outreach")

        task = await OutreachWorkflowService._create_follow_up_task(db, outreach, due)
        if not task:
            raise HTTPException(status_code=409, detail="Follow-up task already exists for this outreach")

        outreach.follow_up_task_id = UUID(str(task["id"]))
        outreach.last_action_at = _now()
        outreach.updated_at = _now()
        await _log_event(
            db,
            outreach_id,
            "follow_up_created",
            {"task_id": str(task["id"]), "due_at": due.isoformat()},
        )

        await db.commit()
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        logger.info("%s follow-up created: id=%s task=%s", MARKER, outreach_id, task["id"])
        return {
            "outreach": _serialize(outreach),
            "follow_up_task_id": outreach.follow_up_task_id,
            "communication_thread_id": outreach.communication_thread_id,
            "message": "Follow-up task created.",
        }

    @staticmethod
    async def link_thread(
        db: AsyncSession,
        outreach_id: UUID,
        data: OutreachLinkThreadRequest,
    ) -> dict[str, Any]:
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        r = await db.execute(
            select(CommunicationThread).where(CommunicationThread.id == data.communication_thread_id)
        )
        thread = r.scalar_one_or_none()
        if not thread:
            raise HTTPException(status_code=404, detail="Communication thread not found")

        outreach.communication_thread_id = thread.id
        outreach.last_action_at = _now()
        outreach.updated_at = _now()
        await _log_event(
            db,
            outreach_id,
            "thread_linked",
            {"communication_thread_id": str(thread.id), "thread_title": thread.title},
        )

        await db.commit()
        outreach = await BuyerOutreachService._load_message(db, outreach_id)
        logger.info("%s thread linked: id=%s thread=%s", MARKER, outreach_id, thread.id)
        return {
            "outreach": _serialize(outreach),
            "follow_up_task_id": outreach.follow_up_task_id,
            "communication_thread_id": thread.id,
            "message": "Communication thread linked.",
        }

    @staticmethod
    async def linked_outreach_for_thread(
        db: AsyncSession,
        thread_id: UUID,
    ) -> list[dict[str, Any]]:
        r = await db.execute(
            select(BuyerOutreachMessage)
            .options(selectinload(BuyerOutreachMessage.events))
            .where(BuyerOutreachMessage.communication_thread_id == thread_id)
            .order_by(BuyerOutreachMessage.updated_at.desc())
        )
        return [_serialize(m) for m in r.scalars().all()]
