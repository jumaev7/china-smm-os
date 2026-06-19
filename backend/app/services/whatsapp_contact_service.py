"""WhatsApp Contact Center — contacts and CRM linking (mock data v1)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.client import Client
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage, WhatsAppThread

logger = logging.getLogger(__name__)

MARKER = "[WhatsApp Center]"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _preview(text: str | None, limit: int = 120) -> str | None:
    if not text:
        return None
    t = text.strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _serialize_contact(
    contact: WhatsAppContact,
    *,
    crm_client_name: str | None = None,
) -> dict[str, Any]:
    return {
        "id": contact.id,
        "phone": contact.phone,
        "display_name": contact.display_name,
        "company": contact.company,
        "country": contact.country,
        "crm_client_id": contact.crm_client_id,
        "crm_client_name": crm_client_name,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


async def _client_name_map(db: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    r = await db.execute(select(Client.id, Client.company_name).where(Client.id.in_(ids)))
    return {row[0]: row[1] for row in r.all()}


async def _ensure_mock_data(db: AsyncSession) -> None:
    """Seed demo contacts/threads/messages when tables are empty."""
    count = (await db.execute(select(func.count()).select_from(WhatsAppContact))).scalar_one()
    if count > 0:
        return

    now = _utcnow()
    contacts = [
        WhatsAppContact(
            phone="+998901234567",
            display_name="Ahmed Karimov",
            company="Tashkent Trading LLC",
            country="Uzbekistan",
        ),
        WhatsAppContact(
            phone="+8613800138000",
            display_name="Li Wei",
            company="Guangzhou Export Co.",
            country="China",
        ),
        WhatsAppContact(
            phone="+971501234567",
            display_name="Omar Hassan",
            company="Dubai Imports",
            country="UAE",
        ),
    ]
    for c in contacts:
        db.add(c)
    await db.flush()

    threads: list[WhatsAppThread] = []
    for contact in contacts[:2]:
        thread = WhatsAppThread(
            contact_id=contact.id,
            last_message_at=now - timedelta(hours=2),
            unread_count=1,
        )
        db.add(thread)
        threads.append(thread)
    await db.flush()

    messages_data = [
        (threads[0], "incoming", "Hello, we are interested in your textile products. Can you send a catalog?", "delivered"),
        (threads[0], "outgoing", "Thank you for reaching out! We will prepare a catalog and send it shortly.", "read"),
        (threads[0], "incoming", "Also, what is the MOQ for cotton fabrics?", "delivered"),
        (threads[1], "incoming", "您好，请问有现货吗？", "delivered"),
        (threads[1], "outgoing", "您好！部分产品有现货，请告知具体型号和数量。", "sent"),
    ]
    for thread, direction, content, status in messages_data:
        db.add(WhatsAppMessage(
            thread_id=thread.id,
            direction=direction,
            content=content,
            status=status,
        ))

    await db.commit()
    logger.info("%s mock data seeded: contacts=%s threads=%s", MARKER, len(contacts), len(threads))


class WhatsAppContactService:
    @staticmethod
    async def list_contacts(
        db: AsyncSession,
        *,
        search: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        await _ensure_mock_data(db)
        limit = clamp_limit(limit)

        q = select(WhatsAppContact)
        count_q = select(func.count()).select_from(WhatsAppContact)

        if search:
            like = f"%{search.strip()}%"
            filt = (
                WhatsAppContact.display_name.ilike(like)
                | WhatsAppContact.company.ilike(like)
                | WhatsAppContact.phone.ilike(like)
                | WhatsAppContact.country.ilike(like)
            )
            q = q.where(filt)
            count_q = count_q.where(filt)

        total = (await db.execute(count_q)).scalar_one()
        contacts = list(
            (await db.execute(
                q.order_by(WhatsAppContact.updated_at.desc()).offset(skip).limit(limit)
            )).scalars().all()
        )

        client_names = await _client_name_map(
            db, {c.crm_client_id for c in contacts if c.crm_client_id}
        )
        items = [
            _serialize_contact(c, crm_client_name=client_names.get(c.crm_client_id) if c.crm_client_id else None)
            for c in contacts
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def get_contact(db: AsyncSession, contact_id: UUID) -> dict[str, Any]:
        r = await db.execute(select(WhatsAppContact).where(WhatsAppContact.id == contact_id))
        contact = r.scalar_one_or_none()
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        client_names = await _client_name_map(
            db, {contact.crm_client_id} if contact.crm_client_id else set()
        )
        return _serialize_contact(
            contact,
            crm_client_name=client_names.get(contact.crm_client_id) if contact.crm_client_id else None,
        )

    @staticmethod
    async def link_crm(
        db: AsyncSession,
        *,
        contact_id: UUID,
        crm_client_id: UUID,
    ) -> dict[str, Any]:
        r = await db.execute(select(WhatsAppContact).where(WhatsAppContact.id == contact_id))
        contact = r.scalar_one_or_none()
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")

        cr = await db.execute(select(Client).where(Client.id == crm_client_id))
        client = cr.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="CRM client not found")

        contact.crm_client_id = crm_client_id
        contact.updated_at = _utcnow()
        await db.commit()
        logger.info("%s CRM linked: contact=%s client=%s", MARKER, contact_id, crm_client_id)
        return {
            "contact_id": contact_id,
            "crm_client_id": crm_client_id,
            "crm_client_name": client.company_name,
            "message": "WhatsApp contact linked to CRM client.",
        }
