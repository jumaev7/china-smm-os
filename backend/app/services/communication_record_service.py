"""Communication records — unified DTO over messages + threads."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.communication import (
    CommunicationContact,
    CommunicationMessage,
    CommunicationThread,
)
from app.schemas.communication import COMMUNICATION_CHANNELS, MESSAGE_DIRECTIONS
from app.schemas.communication_hub import (
    CommunicationRecordCreate,
    CommunicationRecordListResponse,
    CommunicationRecordResponse,
)
from app.services.communication_hub_scope import tenant_client_ids, thread_tenant_filter

MARKER = "[Communication Records]"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommunicationRecordService:
    @staticmethod
    def _serialize(
        msg: CommunicationMessage,
        thread: CommunicationThread,
        contact: CommunicationContact | None,
    ) -> CommunicationRecordResponse:
        return CommunicationRecordResponse(
            id=msg.id,
            tenant_id=thread.tenant_id,
            channel=thread.channel,
            customer_id=thread.customer_id,
            buyer_id=thread.buyer_id,
            lead_id=thread.lead_id,
            deal_id=thread.deal_id,
            client_id=thread.client_id,
            thread_id=thread.id,
            subject=thread.title,
            content=msg.message_text,
            direction=msg.direction,
            status=msg.status,
            contact_name=contact.name if contact else None,
            created_at=msg.created_at,
            updated_at=msg.updated_at or msg.created_at,
        )

    @staticmethod
    async def list_records(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        channel: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> CommunicationRecordListResponse:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        thread_filt = await thread_tenant_filter(tenant_id, client_ids)

        q = (
            select(CommunicationMessage)
            .join(CommunicationThread)
            .options(
                selectinload(CommunicationMessage.thread).selectinload(CommunicationThread.contact),
            )
            .order_by(CommunicationMessage.created_at.desc())
        )
        count_q = (
            select(func.count())
            .select_from(CommunicationMessage)
            .join(CommunicationThread)
        )
        if thread_filt is not None:
            q = q.where(thread_filt)
            count_q = count_q.where(thread_filt)
        if channel:
            q = q.where(CommunicationThread.channel == channel)
            count_q = count_q.where(CommunicationThread.channel == channel)
        if status:
            q = q.where(CommunicationMessage.status == status)
            count_q = count_q.where(CommunicationMessage.status == status)

        total = int((await db.execute(count_q)).scalar() or 0)
        rows = list((await db.execute(q.offset(skip).limit(limit))).scalars().all())
        items = [
            CommunicationRecordService._serialize(
                msg, msg.thread, msg.thread.contact if msg.thread else None,
            )
            for msg in rows
        ]
        return CommunicationRecordListResponse(items=items, total=total)

    @staticmethod
    async def create_manual_record(
        db: AsyncSession,
        tenant_id: UUID,
        data: CommunicationRecordCreate,
    ) -> CommunicationRecordResponse:
        if data.channel not in COMMUNICATION_CHANNELS:
            raise HTTPException(status_code=422, detail="Invalid channel")
        if data.direction not in MESSAGE_DIRECTIONS:
            raise HTTPException(status_code=422, detail="Invalid direction")

        contact_name = (data.contact_name or "Manual contact").strip()
        contact = CommunicationContact(
            tenant_id=tenant_id,
            client_id=data.client_id,
            lead_id=data.lead_id,
            name=contact_name,
        )
        db.add(contact)
        await db.flush()

        thread = CommunicationThread(
            tenant_id=tenant_id,
            contact_id=contact.id,
            client_id=data.client_id,
            lead_id=data.lead_id,
            deal_id=data.deal_id,
            buyer_id=data.buyer_id,
            customer_id=data.customer_id,
            channel=data.channel,
            title=data.subject.strip(),
            status="open",
            last_message_at=_utcnow(),
        )
        db.add(thread)
        await db.flush()

        msg = CommunicationMessage(
            thread_id=thread.id,
            direction=data.direction,
            sender_name=contact_name if data.direction == "inbound" else "Operator",
            message_text=data.content.strip(),
            status=data.status,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)
        await db.refresh(thread)
        return CommunicationRecordService._serialize(msg, thread, contact)
