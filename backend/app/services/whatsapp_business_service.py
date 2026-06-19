"""WhatsApp Business Integration — tenant-scoped dashboard, accounts, demo, CRM links."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.buyer_crm import Buyer
from app.models.communication import (
    CommunicationContact,
    CommunicationFollowUp,
    CommunicationMessage,
    CommunicationThread,
)
from app.models.crm_lead import CrmLead
from app.models.sales_crm import SalesCustomer, SalesLead, SalesProposal
from app.models.whatsapp_sync import WHATSAPP_ACCOUNT_STATUSES, WhatsAppSyncAccount
from app.services.communication_hub_scope import contact_tenant_filter, tenant_client_ids, thread_tenant_filter

logger = logging.getLogger(__name__)
MARKER = "[WhatsApp Business]"
WHATSAPP_CHANNEL = "whatsapp"

_LEGACY_STATUS_MAP = {
    "pending": "not_connected",
    "error": "sync_error",
    "failed": "sync_error",
    "inactive": "disabled",
}

_DEMO_CONTACTS = [
    {
        "name": "Ahmed Karimov",
        "phone": "+998901234567",
        "company": "Tashkent Trading LLC",
        "country": "UZ",
        "city": "Tashkent",
        "industry": "Textile Import",
        "tags": ["buyer", "high-intent", "demo"],
        "messages": [
            ("inbound", "Hello, we are interested in your textile products. Can you send a catalog?", "Ahmed Karimov"),
            ("outbound", "Thank you for reaching out! We will prepare a catalog and send it shortly.", "Operator"),
            ("inbound", "Also, what is the MOQ for cotton fabrics?", "Ahmed Karimov"),
        ],
    },
    {
        "name": "Li Wei",
        "phone": "+8613800138000",
        "company": "Guangzhou Export Co.",
        "country": "CN",
        "city": "Guangzhou",
        "industry": "Electronics Export",
        "tags": ["buyer", "demo"],
        "messages": [
            ("inbound", "您好，请问有现货吗？", "Li Wei"),
            ("outbound", "您好！部分产品有现货，请告知具体型号和数量。", "Operator"),
        ],
    },
    {
        "name": "Omar Hassan",
        "phone": "+971501234567",
        "company": "Dubai Imports",
        "country": "AE",
        "city": "Dubai",
        "industry": "Consumer Goods",
        "tags": ["buyer", "follow-up", "demo"],
        "messages": [
            ("inbound", "We need stainless steel kitchen equipment for a hotel project. Please share specs.", "Omar Hassan"),
        ],
    },
]

_DEMO_ACCOUNTS = [
    {
        "account_name": "Demo Factory WhatsApp",
        "account_type": "whatsapp_cloud_api",
        "phone_number": "+8613800000001",
        "business_display_name": "Demo Export Factory",
        "status": "connected",
        "provider": "demo",
    },
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_week(now: datetime) -> datetime:
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def normalize_account_status(status: str | None) -> str:
    if not status:
        return "not_connected"
    if status in WHATSAPP_ACCOUNT_STATUSES:
        return status
    return _LEGACY_STATUS_MAP.get(status, status)


def _webhook_configured() -> bool:
    return bool(
        (settings.WHATSAPP_ACCESS_TOKEN or "").strip()
        and (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
        and (settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN or "").strip()
    )


def _serialize_account(account: WhatsAppSyncAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "tenant_id": account.tenant_id,
        "account_name": account.account_name,
        "phone_number": account.phone_number,
        "business_display_name": account.business_display_name,
        "account_type": account.account_type,
        "status": normalize_account_status(account.status),
        "provider": account.provider,
        "external_account_id": account.external_account_id,
        "connected_at": account.connected_at or (
            account.created_at if normalize_account_status(account.status) == "connected" else None
        ),
        "last_sync_at": account.last_sync_at,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


class WhatsAppBusinessService:
    @staticmethod
    async def _scoped_whatsapp_contact_filter(db: AsyncSession, tenant_id: UUID | None):
        wa_filter = or_(
            CommunicationContact.whatsapp.isnot(None),
            CommunicationContact.phone.isnot(None),
        )
        tenant_filter = await contact_tenant_filter(tenant_id, await tenant_client_ids(db, tenant_id))
        thread_contact_ids = select(CommunicationThread.contact_id).where(
            CommunicationThread.channel == WHATSAPP_CHANNEL
        )
        channel_filter = CommunicationContact.id.in_(thread_contact_ids) | CommunicationContact.whatsapp.isnot(None)
        combined = wa_filter & channel_filter
        if tenant_filter is not None:
            return combined & tenant_filter
        return combined

    @staticmethod
    async def _scoped_whatsapp_thread_filter(db: AsyncSession, tenant_id: UUID | None):
        channel_filter = CommunicationThread.channel == WHATSAPP_CHANNEL
        tenant_filter = await thread_tenant_filter(
            tenant_id,
            await tenant_client_ids(db, tenant_id),
        )
        if tenant_filter is not None:
            return channel_filter & tenant_filter
        return channel_filter

    @staticmethod
    async def _assert_contact_in_scope(
        db: AsyncSession,
        contact_id: UUID,
        tenant_id: UUID | None,
    ) -> CommunicationContact:
        contact = await db.get(CommunicationContact, contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        if tenant_id is None:
            return contact
        client_ids = await tenant_client_ids(db, tenant_id)
        if contact.tenant_id == tenant_id:
            return contact
        if contact.client_id and contact.client_id in client_ids:
            return contact
        raise HTTPException(status_code=403, detail="Contact not in tenant scope")

    @staticmethod
    async def _assert_thread_in_scope(
        db: AsyncSession,
        thread_id: UUID,
        tenant_id: UUID | None,
    ) -> CommunicationThread:
        thread = await db.get(CommunicationThread, thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        if thread.channel != WHATSAPP_CHANNEL:
            raise HTTPException(status_code=400, detail="Thread is not a WhatsApp channel")
        if tenant_id is None:
            return thread
        client_ids = await tenant_client_ids(db, tenant_id)
        if thread.tenant_id == tenant_id:
            return thread
        if thread.client_id and thread.client_id in client_ids:
            return thread
        raise HTTPException(status_code=403, detail="Thread not in tenant scope")

    @staticmethod
    async def list_accounts(db: AsyncSession, tenant_id: UUID | None) -> dict[str, Any]:
        await WhatsAppBusinessService.ensure_tenant_demo_accounts(db, tenant_id)
        q = select(WhatsAppSyncAccount).order_by(WhatsAppSyncAccount.created_at.asc())
        if tenant_id is not None:
            q = q.where(
                or_(
                    WhatsAppSyncAccount.tenant_id == tenant_id,
                    WhatsAppSyncAccount.tenant_id.is_(None),
                )
            )
        rows = list((await db.execute(q)).scalars().all())
        if tenant_id is not None:
            tenant_rows = [a for a in rows if a.tenant_id == tenant_id]
            if tenant_rows:
                rows = tenant_rows
        return {
            "items": [_serialize_account(a) for a in rows],
            "total": len(rows),
        }

    @staticmethod
    async def create_account(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        account_name: str,
        account_type: str,
        phone_number: str | None = None,
        business_display_name: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        account = WhatsAppSyncAccount(
            tenant_id=tenant_id,
            account_name=account_name,
            account_type=account_type,
            phone_number=phone_number,
            business_display_name=business_display_name,
            status="not_connected",
            provider=provider or "demo",
            config_json={"demo": provider == "demo" or provider is None},
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        logger.info("%s account created tenant=%s name=%s", MARKER, tenant_id, account_name)
        return _serialize_account(account)

    @staticmethod
    async def update_account(
        db: AsyncSession,
        tenant_id: UUID | None,
        account_id: UUID,
        *,
        account_name: str | None = None,
        phone_number: str | None = None,
        business_display_name: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        account = await db.get(WhatsAppSyncAccount, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        if tenant_id and account.tenant_id and account.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Account not in tenant scope")
        if account_name:
            account.account_name = account_name
        if phone_number is not None:
            account.phone_number = phone_number
        if business_display_name is not None:
            account.business_display_name = business_display_name
        if provider is not None:
            account.provider = provider
        if status:
            if status not in WHATSAPP_ACCOUNT_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid account status")
            account.status = status
            if status == "connected" and not account.connected_at:
                account.connected_at = _utcnow()
        account.updated_at = _utcnow()
        await db.commit()
        await db.refresh(account)
        return _serialize_account(account)

    @staticmethod
    async def ensure_tenant_demo_accounts(db: AsyncSession, tenant_id: UUID | None) -> None:
        if tenant_id is None:
            return
        count = await db.scalar(
            select(func.count())
            .select_from(WhatsAppSyncAccount)
            .where(WhatsAppSyncAccount.tenant_id == tenant_id)
        ) or 0
        if count > 0:
            return
        now = _utcnow()
        for spec in _DEMO_ACCOUNTS:
            db.add(
                WhatsAppSyncAccount(
                    tenant_id=tenant_id,
                    account_name=spec["account_name"],
                    account_type=spec["account_type"],
                    phone_number=spec["phone_number"],
                    business_display_name=spec["business_display_name"],
                    status=spec["status"],
                    provider=spec["provider"],
                    connected_at=now,
                    last_sync_at=now,
                    config_json={"sync_interval_minutes": 60, "demo": True},
                ),
            )
        await db.commit()
        logger.info("%s seeded demo accounts for tenant=%s", MARKER, tenant_id)

    @staticmethod
    async def list_contacts_extended(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        search: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        base_filter = await WhatsAppBusinessService._scoped_whatsapp_contact_filter(db, tenant_id)
        q = select(CommunicationContact).where(base_filter)
        count_q = select(func.count()).select_from(CommunicationContact).where(base_filter)
        if search:
            like = f"%{search.strip()}%"
            filt = (
                CommunicationContact.name.ilike(like)
                | CommunicationContact.company.ilike(like)
                | CommunicationContact.whatsapp.ilike(like)
                | CommunicationContact.phone.ilike(like)
                | CommunicationContact.country.ilike(like)
            )
            q = q.where(filt)
            count_q = count_q.where(filt)
        total = int((await db.execute(count_q)).scalar() or 0)
        contacts = list(
            (await db.execute(
                q.order_by(CommunicationContact.updated_at.desc()).offset(skip).limit(limit)
            )).scalars().all()
        )
        items = await WhatsAppBusinessService._serialize_contacts_extended(db, contacts)
        return {"items": items, "total": total}

    @staticmethod
    async def _serialize_contacts_extended(
        db: AsyncSession,
        contacts: list[CommunicationContact],
    ) -> list[dict[str, Any]]:
        if not contacts:
            return []
        contact_ids = [c.id for c in contacts]
        thread_rows = (
            await db.execute(
                select(
                    CommunicationThread.contact_id,
                    func.count(),
                    func.max(CommunicationThread.last_message_at),
                )
                .where(
                    CommunicationThread.contact_id.in_(contact_ids),
                    CommunicationThread.channel == WHATSAPP_CHANNEL,
                )
                .group_by(CommunicationThread.contact_id)
            )
        ).all()
        thread_counts = {r[0]: r[1] for r in thread_rows}
        last_interactions = {r[0]: r[2] for r in thread_rows}

        lead_ids = {c.lead_id for c in contacts if c.lead_id}
        sales_lead_ids = {c.sales_lead_id for c in contacts if c.sales_lead_id}
        buyer_ids = {c.buyer_id for c in contacts if c.buyer_id}
        customer_ids = {c.customer_id for c in contacts if c.customer_id}

        lead_names: dict[UUID, str] = {}
        if lead_ids:
            rows = (await db.execute(select(CrmLead.id, CrmLead.name).where(CrmLead.id.in_(lead_ids)))).all()
            lead_names = {r[0]: r[1] for r in rows}
        sales_lead_names: dict[UUID, str] = {}
        if sales_lead_ids:
            rows = (
                await db.execute(select(SalesLead.id, SalesLead.name).where(SalesLead.id.in_(sales_lead_ids)))
            ).all()
            sales_lead_names = {r[0]: r[1] for r in rows}
        buyer_names: dict[UUID, str] = {}
        if buyer_ids:
            rows = (await db.execute(select(Buyer.id, Buyer.company_name).where(Buyer.id.in_(buyer_ids)))).all()
            buyer_names = {r[0]: r[1] for r in rows}
        customer_names: dict[UUID, str] = {}
        if customer_ids:
            rows = (
                await db.execute(
                    select(SalesCustomer.id, SalesCustomer.company, SalesCustomer.name).where(
                        SalesCustomer.id.in_(customer_ids)
                    )
                )
            ).all()
            customer_names = {r[0]: (r[1] or r[2]) for r in rows}

        items: list[dict[str, Any]] = []
        for c in contacts:
            linked_lead_name = None
            if c.lead_id:
                linked_lead_name = lead_names.get(c.lead_id)
            elif c.sales_lead_id:
                linked_lead_name = sales_lead_names.get(c.sales_lead_id)
            items.append({
                "id": c.id,
                "tenant_id": c.tenant_id,
                "phone_number": c.whatsapp or c.phone,
                "display_name": c.name,
                "company": c.company,
                "country": c.country,
                "city": getattr(c, "city", None),
                "industry": c.industry,
                "tags": list(c.tags_json or []),
                "linked_lead_id": c.lead_id,
                "linked_sales_lead_id": c.sales_lead_id,
                "linked_buyer_id": c.buyer_id,
                "linked_customer_id": c.customer_id,
                "linked_lead_name": linked_lead_name,
                "linked_buyer_name": buyer_names.get(c.buyer_id) if c.buyer_id else None,
                "linked_customer_name": customer_names.get(c.customer_id) if c.customer_id else None,
                "last_interaction_at": last_interactions.get(c.id) or c.updated_at,
                "thread_count": thread_counts.get(c.id, 0),
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            })
        return items

    @staticmethod
    async def link_contact_buyer(
        db: AsyncSession,
        tenant_id: UUID | None,
        contact_id: UUID,
        buyer_id: UUID,
    ) -> dict[str, Any]:
        contact = await WhatsAppBusinessService._assert_contact_in_scope(db, contact_id, tenant_id)
        buyer = await db.get(Buyer, buyer_id)
        if not buyer:
            raise HTTPException(status_code=404, detail="Buyer not found")
        if tenant_id and buyer.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Buyer not in tenant scope")
        contact.buyer_id = buyer_id
        contact.updated_at = _utcnow()
        await db.commit()
        return {"contact_id": contact.id, "buyer_id": buyer.id, "buyer_name": buyer.company_name}

    @staticmethod
    async def link_contact_customer(
        db: AsyncSession,
        tenant_id: UUID | None,
        contact_id: UUID,
        customer_id: UUID,
    ) -> dict[str, Any]:
        contact = await WhatsAppBusinessService._assert_contact_in_scope(db, contact_id, tenant_id)
        customer = await db.get(SalesCustomer, customer_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        if tenant_id and customer.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Customer not in tenant scope")
        contact.customer_id = customer_id
        contact.updated_at = _utcnow()
        await db.commit()
        return {
            "contact_id": contact.id,
            "customer_id": customer.id,
            "customer_name": customer.company or customer.name,
        }

    @staticmethod
    async def link_contact_lead(
        db: AsyncSession,
        tenant_id: UUID | None,
        contact_id: UUID,
        lead_id: UUID,
    ) -> dict[str, Any]:
        contact = await WhatsAppBusinessService._assert_contact_in_scope(db, contact_id, tenant_id)
        sales_lead = await db.get(SalesLead, lead_id)
        if sales_lead:
            if tenant_id and sales_lead.tenant_id != tenant_id:
                raise HTTPException(status_code=403, detail="Lead not in tenant scope")
            contact.sales_lead_id = lead_id
            lead_name = sales_lead.name
        else:
            legacy = await db.get(CrmLead, lead_id)
            if not legacy:
                raise HTTPException(status_code=404, detail="Lead not found")
            contact.lead_id = lead_id
            lead_name = legacy.name
        contact.updated_at = _utcnow()
        await db.commit()
        return {"contact_id": contact.id, "lead_id": lead_id, "lead_name": lead_name}

    @staticmethod
    async def link_thread_deal(
        db: AsyncSession,
        tenant_id: UUID | None,
        thread_id: UUID,
        deal_id: UUID,
    ) -> dict[str, Any]:
        from app.models.sales_crm import SalesDeal

        thread = await WhatsAppBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
        sales_deal = await db.get(SalesDeal, deal_id)
        if sales_deal:
            if tenant_id and sales_deal.tenant_id != tenant_id:
                raise HTTPException(status_code=403, detail="Deal not in tenant scope")
            thread.sales_deal_id = deal_id
            if sales_deal.lead_id:
                thread.sales_lead_id = sales_deal.lead_id
            deal_title = sales_deal.title
        else:
            from app.models.crm_deal import CrmDeal

            legacy = await db.get(CrmDeal, deal_id)
            if not legacy:
                raise HTTPException(status_code=404, detail="Deal not found")
            thread.deal_id = deal_id
            if legacy.lead_id:
                thread.lead_id = legacy.lead_id
            deal_title = legacy.title
        thread.updated_at = _utcnow()
        await db.commit()
        return {"thread_id": thread.id, "deal_id": deal_id, "deal_title": deal_title}

    @staticmethod
    async def link_thread_proposal(
        db: AsyncSession,
        tenant_id: UUID | None,
        thread_id: UUID,
        proposal_id: UUID,
    ) -> dict[str, Any]:
        thread = await WhatsAppBusinessService._assert_thread_in_scope(db, thread_id, tenant_id)
        proposal = await db.get(SalesProposal, proposal_id)
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if tenant_id and proposal.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Proposal not in tenant scope")
        if proposal.lead_id:
            thread.sales_lead_id = proposal.lead_id
        if proposal.deal_id:
            thread.sales_deal_id = proposal.deal_id
        if proposal.customer_id:
            thread.customer_id = proposal.customer_id
        thread.updated_at = _utcnow()
        await db.commit()
        return {
            "thread_id": thread.id,
            "proposal_id": proposal.id,
            "proposal_title": proposal.title,
            "lead_id": proposal.lead_id,
            "deal_id": proposal.deal_id,
        }

    @staticmethod
    async def dashboard(db: AsyncSession, tenant_id: UUID | None) -> dict[str, Any]:
        await WhatsAppBusinessService.ensure_tenant_demo_accounts(db, tenant_id)
        accounts_data = await WhatsAppBusinessService.list_accounts(db, tenant_id)
        accounts = accounts_data["items"]
        connected = sum(1 for a in accounts if a["status"] == "connected")
        last_sync = max((a["last_sync_at"] for a in accounts if a["last_sync_at"]), default=None)

        contact_filter = await WhatsAppBusinessService._scoped_whatsapp_contact_filter(db, tenant_id)
        thread_filter = await WhatsAppBusinessService._scoped_whatsapp_thread_filter(db, tenant_id)

        total_contacts = int(
            (await db.execute(select(func.count()).select_from(CommunicationContact).where(contact_filter))).scalar()
            or 0
        )
        active_conversations = int(
            (await db.execute(
                select(func.count())
                .select_from(CommunicationThread)
                .where(thread_filter, CommunicationThread.status == "open")
            )).scalar()
            or 0
        )
        week_start = _start_of_week(_utcnow())
        new_this_week = int(
            (await db.execute(
                select(func.count())
                .select_from(CommunicationThread)
                .where(thread_filter, CommunicationThread.created_at >= week_start)
            )).scalar()
            or 0
        )
        opportunities = int(
            (await db.execute(
                select(func.count())
                .select_from(CommunicationThread)
                .where(
                    thread_filter,
                    or_(
                        CommunicationThread.lead_id.isnot(None),
                        CommunicationThread.sales_lead_id.isnot(None),
                        CommunicationThread.deal_id.isnot(None),
                        CommunicationThread.sales_deal_id.isnot(None),
                    ),
                )
            )).scalar()
            or 0
        )
        follow_ups = 0
        if tenant_id:
            follow_ups = int(
                (await db.execute(
                    select(func.count())
                    .select_from(CommunicationFollowUp)
                    .where(
                        CommunicationFollowUp.tenant_id == tenant_id,
                        CommunicationFollowUp.status == "pending",
                    )
                )).scalar()
                or 0
            )
        thread_ids_subq = select(CommunicationThread.id).where(thread_filter)
        messages_total = int(
            (await db.execute(
                select(func.count())
                .select_from(CommunicationMessage)
                .where(CommunicationMessage.thread_id.in_(thread_ids_subq))
            )).scalar()
            or 0
        )

        recent_threads = list(
            (await db.execute(
                select(CommunicationThread)
                .options(selectinload(CommunicationThread.contact))
                .where(thread_filter)
                .order_by(CommunicationThread.last_message_at.desc().nullslast())
                .limit(8)
            )).scalars().all()
        )
        activity: list[dict[str, Any]] = []
        for th in recent_threads:
            activity.append({
                "id": th.id,
                "activity_type": "conversation",
                "title": th.title,
                "subtitle": th.contact.name if th.contact else None,
                "channel": th.channel,
                "occurred_at": th.last_message_at or th.updated_at,
                "thread_id": th.id,
                "contact_id": th.contact_id,
            })

        overall = "connected" if connected > 0 else "not_connected"
        if any(a["status"] == "sync_error" for a in accounts):
            overall = "sync_error"

        return {
            "connection": {
                "overall_status": overall,
                "accounts_total": len(accounts),
                "accounts_connected": connected,
                "demo_mode": settings.DEMO_MODE or all(
                    (a.get("provider") == "demo" for a in accounts)
                ),
                "provider_ready": connected > 0,
                "webhook_configured": _webhook_configured(),
                "last_sync_at": last_sync,
            },
            "kpis": {
                "total_contacts": total_contacts,
                "active_conversations": active_conversations,
                "new_conversations_this_week": new_this_week,
                "opportunities_discovered": opportunities,
                "follow_ups_required": follow_ups,
                "messages_total": messages_total,
                "accounts_connected": connected,
            },
            "linked_accounts": accounts[:5],
            "recent_activity": activity,
            "communication_hub_channel": "whatsapp",
        }

    @staticmethod
    async def seed_demo_environment(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        await WhatsAppBusinessService.ensure_tenant_demo_accounts(db, tenant_id)
        existing = int(
            (await db.execute(
                select(func.count())
                .select_from(CommunicationContact)
                .where(
                    CommunicationContact.tenant_id == tenant_id,
                    CommunicationContact.whatsapp.isnot(None),
                )
            )).scalar()
            or 0
        )
        if existing >= 3:
            return {
                "seeded": False,
                "accounts_created": 0,
                "contacts_created": 0,
                "conversations_created": 0,
                "message": "Demo WhatsApp environment already exists for this tenant.",
            }

        now = _utcnow()
        contacts_created = 0
        conversations_created = 0
        for spec in _DEMO_CONTACTS:
            contact = CommunicationContact(
                tenant_id=tenant_id,
                name=spec["name"],
                company=spec["company"],
                country=spec["country"],
                city=spec["city"],
                industry=spec["industry"],
                tags_json=spec["tags"],
                phone=spec["phone"],
                whatsapp=spec["phone"],
                preferred_language="en",
                language="en",
            )
            db.add(contact)
            await db.flush()
            contacts_created += 1

            thread = CommunicationThread(
                tenant_id=tenant_id,
                contact_id=contact.id,
                channel=WHATSAPP_CHANNEL,
                title=f"{spec['company']} — WhatsApp inquiry",
                status="open",
                last_message_at=now - timedelta(hours=contacts_created * 4),
            )
            db.add(thread)
            await db.flush()
            conversations_created += 1

            for idx, (direction, text, sender) in enumerate(spec["messages"]):
                db.add(
                    CommunicationMessage(
                        thread_id=thread.id,
                        direction=direction,
                        sender_name=sender,
                        message_text=text,
                        status="unanswered" if direction == "inbound" else "sent",
                        created_at=now - timedelta(hours=contacts_created * 4 - idx),
                    )
                )

        await db.commit()
        logger.info(
            "%s demo seed tenant=%s contacts=%s conversations=%s",
            MARKER, tenant_id, contacts_created, conversations_created,
        )
        return {
            "seeded": True,
            "accounts_created": len(_DEMO_ACCOUNTS),
            "contacts_created": contacts_created,
            "conversations_created": conversations_created,
            "message": "Demo WhatsApp environment created with sample contacts and conversations.",
        }

    @staticmethod
    def ai_capabilities() -> dict[str, Any]:
        return {
            "capabilities": [
                {
                    "id": "summarize_conversation",
                    "label": "Summarize conversations",
                    "description": "Uses Communication Hub AI summary on WhatsApp threads.",
                    "status": "ready",
                },
                {
                    "id": "detect_buyer_intent",
                    "label": "Detect buyer intent",
                    "description": "CRM extract pipeline via CommunicationCrmService.",
                    "status": "ready",
                },
                {
                    "id": "recommend_replies",
                    "label": "Recommend replies",
                    "description": "WhatsApp message center draft generation (manual copy/paste).",
                    "status": "ready",
                },
                {
                    "id": "detect_opportunities",
                    "label": "Detect high-value opportunities",
                    "description": "Conversation intelligence heuristics + CRM linking.",
                    "status": "planned",
                },
                {
                    "id": "suggest_follow_ups",
                    "label": "Suggest follow-ups",
                    "description": "Communication Hub follow-up tasks for unanswered messages.",
                    "status": "ready",
                },
                {
                    "id": "unanswered_messages",
                    "label": "Identify unanswered messages",
                    "description": "Dashboard KPIs and Communication Hub inbox filters.",
                    "status": "ready",
                },
            ],
            "uses_communication_ai_hub": True,
            "demo_mode": settings.DEMO_MODE,
        }
