"""Cross-module relationship resolver — aggregates links across tenant sales stack."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_crm import Buyer, BuyerEntityLink
from app.models.communication import CommunicationThread
from app.models.content import ContentItem
from app.models.sales_crm import SalesCustomer, SalesDeal, SalesLead, SalesProposal
from app.schemas.platform_relationships import PlatformRelationshipsResponse, RelatedEntityItem


def _item(
    entity_type: str,
    entity_id: UUID,
    label: str,
    *,
    href: str | None = None,
    status: str | None = None,
    updated_at: datetime | None = None,
    meta: dict | None = None,
) -> RelatedEntityItem:
    return RelatedEntityItem(
        entity_type=entity_type,
        entity_id=entity_id,
        label=label,
        href=href,
        status=status,
        updated_at=updated_at,
        meta=meta,
    )


class PlatformRelationshipsService:
    @staticmethod
    async def _buyers_for_entity(
        db: AsyncSession,
        tenant_id: UUID | None,
        entity_type: str,
        entity_id: UUID,
    ) -> list[RelatedEntityItem]:
        q = (
            select(BuyerEntityLink, Buyer)
            .join(Buyer, Buyer.id == BuyerEntityLink.buyer_id)
            .where(
                BuyerEntityLink.entity_type == entity_type,
                BuyerEntityLink.entity_id == entity_id,
            )
        )
        if tenant_id is not None:
            q = q.where(BuyerEntityLink.tenant_id == tenant_id)
        rows = (await db.execute(q)).all()
        return [
            _item(
                "buyer",
                buyer.id,
                buyer.company_name,
                href=f"/buyers/{buyer.id}",
                status=buyer.status,
                updated_at=buyer.updated_at,
            )
            for _link, buyer in rows
        ]

    @staticmethod
    async def _communications_for(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        buyer_id: UUID | None = None,
        customer_id: UUID | None = None,
        sales_lead_id: UUID | None = None,
        sales_deal_id: UUID | None = None,
    ) -> list[RelatedEntityItem]:
        filters = []
        if buyer_id:
            filters.append(CommunicationThread.buyer_id == buyer_id)
        if customer_id:
            filters.append(CommunicationThread.customer_id == customer_id)
        if sales_lead_id:
            filters.append(CommunicationThread.sales_lead_id == sales_lead_id)
        if sales_deal_id:
            filters.append(CommunicationThread.sales_deal_id == sales_deal_id)
        if not filters:
            return []
        q = select(CommunicationThread).where(or_(*filters))
        if tenant_id is not None:
            q = q.where(CommunicationThread.tenant_id == tenant_id)
        threads = (await db.execute(q.order_by(CommunicationThread.updated_at.desc()).limit(50))).scalars().all()
        return [
            _item(
                "communication",
                t.id,
                t.title,
                href=f"/communications/threads/{t.id}",
                status=t.status,
                updated_at=t.last_message_at or t.updated_at,
                meta={"channel": t.channel},
            )
            for t in threads
        ]

    @staticmethod
    async def _content_for(
        db: AsyncSession,
        *,
        lead_id: UUID | None = None,
        buyer_id: UUID | None = None,
        deal_id: UUID | None = None,
    ) -> list[RelatedEntityItem]:
        filters = []
        if lead_id:
            filters.append(ContentItem.linked_sales_lead_id == lead_id)
        if buyer_id:
            filters.append(ContentItem.linked_buyer_id == buyer_id)
        if deal_id:
            filters.append(ContentItem.linked_sales_deal_id == deal_id)
        if not filters:
            return []
        items = (
            await db.execute(
                select(ContentItem)
                .where(or_(*filters))
                .order_by(ContentItem.updated_at.desc())
                .limit(50)
            )
        ).scalars().all()
        return [
            _item(
                "content",
                c.id,
                (c.caption_short_en or c.caption_short_ru or f"Content {str(c.id)[:8]}"),
                href=f"/content/{c.id}",
                status=c.status,
                updated_at=c.updated_at,
                meta={"platforms": c.platforms or []},
            )
            for c in items
        ]

    @classmethod
    async def for_lead(
        cls,
        db: AsyncSession,
        lead_id: UUID,
        tenant_id: UUID | None,
    ) -> PlatformRelationshipsResponse:
        q = select(SalesLead).where(SalesLead.id == lead_id)
        if tenant_id is not None:
            q = q.where(SalesLead.tenant_id == tenant_id)
        lead = (await db.execute(q)).scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        deals = (
            await db.execute(select(SalesDeal).where(SalesDeal.lead_id == lead_id))
        ).scalars().all()
        proposals = (
            await db.execute(select(SalesProposal).where(SalesProposal.lead_id == lead_id))
        ).scalars().all()
        customer_item: list[RelatedEntityItem] = []
        if lead.customer_id:
            cust = (await db.execute(
                select(SalesCustomer).where(SalesCustomer.id == lead.customer_id)
            )).scalar_one_or_none()
            if cust:
                customer_item = [
                    _item("customer", cust.id, cust.company or cust.name, href="/customers", status=None)
                ]

        return PlatformRelationshipsResponse(
            entity_type="lead",
            entity_id=lead_id,
            related_leads=[],
            related_buyers=await cls._buyers_for_entity(db, tenant_id, "lead", lead_id),
            related_deals=[
                _item("deal", d.id, d.title, href="/deals", status=d.stage, updated_at=d.updated_at)
                for d in deals
            ],
            related_proposals=[
                _item(
                    "proposal", p.id, p.title,
                    href=f"/proposals/{p.id}", status=p.status, updated_at=p.updated_at,
                )
                for p in proposals
            ],
            related_communications=await cls._communications_for(
                db, tenant_id, sales_lead_id=lead_id, customer_id=lead.customer_id,
            ),
            related_content=await cls._content_for(db, lead_id=lead_id),
            related_customers=customer_item,
        )

    @classmethod
    async def for_deal(
        cls,
        db: AsyncSession,
        deal_id: UUID,
        tenant_id: UUID | None,
    ) -> PlatformRelationshipsResponse:
        q = select(SalesDeal).where(SalesDeal.id == deal_id)
        if tenant_id is not None:
            q = q.where(SalesDeal.tenant_id == tenant_id)
        deal = (await db.execute(q)).scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")

        lead_items: list[RelatedEntityItem] = []
        if deal.lead_id:
            lead = (await db.execute(
                select(SalesLead).where(SalesLead.id == deal.lead_id)
            )).scalar_one_or_none()
            if lead:
                lead_items = [
                    _item("lead", lead.id, lead.company or lead.name, href="/leads", status=lead.status)
                ]

        proposals = (
            await db.execute(select(SalesProposal).where(SalesProposal.deal_id == deal_id))
        ).scalars().all()

        customer_items: list[RelatedEntityItem] = []
        if deal.customer_id:
            cust = (await db.execute(
                select(SalesCustomer).where(SalesCustomer.id == deal.customer_id)
            )).scalar_one_or_none()
            if cust:
                customer_items = [
                    _item("customer", cust.id, cust.company or cust.name, href="/customers")
                ]

        buyer_items = await cls._buyers_for_entity(db, tenant_id, "deal", deal_id)
        comms = await cls._communications_for(
            db, tenant_id,
            sales_deal_id=deal_id,
            sales_lead_id=deal.lead_id,
            customer_id=deal.customer_id,
        )

        return PlatformRelationshipsResponse(
            entity_type="deal",
            entity_id=deal_id,
            related_leads=lead_items,
            related_buyers=buyer_items,
            related_deals=[],
            related_proposals=[
                _item("proposal", p.id, p.title, href=f"/proposals/{p.id}", status=p.status)
                for p in proposals
            ],
            related_communications=comms,
            related_content=await cls._content_for(db, deal_id=deal_id),
            related_customers=customer_items,
        )

    @classmethod
    async def for_proposal(
        cls,
        db: AsyncSession,
        proposal_id: UUID,
        tenant_id: UUID | None,
    ) -> PlatformRelationshipsResponse:
        q = select(SalesProposal).where(SalesProposal.id == proposal_id)
        if tenant_id is not None:
            q = q.where(SalesProposal.tenant_id == tenant_id)
        proposal = (await db.execute(q)).scalar_one_or_none()
        if not proposal:
            raise HTTPException(status_code=404, detail="Proposal not found")

        lead_items: list[RelatedEntityItem] = []
        if proposal.lead_id:
            lead = (await db.execute(
                select(SalesLead).where(SalesLead.id == proposal.lead_id)
            )).scalar_one_or_none()
            if lead:
                lead_items = [_item("lead", lead.id, lead.company or lead.name, href="/leads", status=lead.status)]

        deal_items: list[RelatedEntityItem] = []
        if proposal.deal_id:
            deal = (await db.execute(
                select(SalesDeal).where(SalesDeal.id == proposal.deal_id)
            )).scalar_one_or_none()
            if deal:
                deal_items = [_item("deal", deal.id, deal.title, href="/deals", status=deal.stage)]

        customer_items: list[RelatedEntityItem] = []
        if proposal.customer_id:
            cust = (await db.execute(
                select(SalesCustomer).where(SalesCustomer.id == proposal.customer_id)
            )).scalar_one_or_none()
            if cust:
                customer_items = [_item("customer", cust.id, cust.company or cust.name, href="/customers")]

        comms = await cls._communications_for(
            db, tenant_id,
            sales_lead_id=proposal.lead_id,
            sales_deal_id=proposal.deal_id,
            customer_id=proposal.customer_id,
        )

        return PlatformRelationshipsResponse(
            entity_type="proposal",
            entity_id=proposal_id,
            related_leads=lead_items,
            related_buyers=await cls._buyers_for_entity(db, tenant_id, "proposal", proposal_id),
            related_deals=deal_items,
            related_proposals=[],
            related_communications=comms,
            related_content=[],
            related_customers=customer_items,
        )

    @classmethod
    async def for_buyer(
        cls,
        db: AsyncSession,
        buyer_id: UUID,
        tenant_id: UUID | None,
    ) -> PlatformRelationshipsResponse:
        q = select(Buyer).where(Buyer.id == buyer_id)
        if tenant_id is not None:
            q = q.where(Buyer.tenant_id == tenant_id)
        buyer = (await db.execute(q)).scalar_one_or_none()
        if not buyer:
            raise HTTPException(status_code=404, detail="Buyer not found")

        links = (
            await db.execute(select(BuyerEntityLink).where(BuyerEntityLink.buyer_id == buyer_id))
        ).scalars().all()

        leads: list[RelatedEntityItem] = []
        deals: list[RelatedEntityItem] = []
        proposals: list[RelatedEntityItem] = []
        customers: list[RelatedEntityItem] = []

        for link in links:
            if link.entity_type == "lead":
                row = (await db.execute(
                    select(SalesLead).where(SalesLead.id == link.entity_id)
                )).scalar_one_or_none()
                if row:
                    leads.append(_item("lead", row.id, row.company or row.name, href="/leads", status=row.status))
            elif link.entity_type == "deal":
                row = (await db.execute(
                    select(SalesDeal).where(SalesDeal.id == link.entity_id)
                )).scalar_one_or_none()
                if row:
                    deals.append(_item("deal", row.id, row.title, href="/deals", status=row.stage))
            elif link.entity_type == "proposal":
                row = (await db.execute(
                    select(SalesProposal).where(SalesProposal.id == link.entity_id)
                )).scalar_one_or_none()
                if row:
                    proposals.append(_item("proposal", row.id, row.title, href=f"/proposals/{row.id}", status=row.status))
            elif link.entity_type == "customer":
                row = (await db.execute(
                    select(SalesCustomer).where(SalesCustomer.id == link.entity_id)
                )).scalar_one_or_none()
                if row:
                    customers.append(_item("customer", row.id, row.company or row.name, href="/customers"))

        return PlatformRelationshipsResponse(
            entity_type="buyer",
            entity_id=buyer_id,
            related_leads=leads,
            related_buyers=[],
            related_deals=deals,
            related_proposals=proposals,
            related_communications=await cls._communications_for(db, tenant_id, buyer_id=buyer_id),
            related_content=await cls._content_for(db, buyer_id=buyer_id),
            related_customers=customers,
        )

    @classmethod
    async def for_content(
        cls,
        db: AsyncSession,
        content_id: UUID,
    ) -> PlatformRelationshipsResponse:
        item = (await db.execute(
            select(ContentItem).where(ContentItem.id == content_id)
        )).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Content not found")

        leads: list[RelatedEntityItem] = []
        buyers: list[RelatedEntityItem] = []
        deals: list[RelatedEntityItem] = []

        if item.linked_sales_lead_id:
            lead = (await db.execute(
                select(SalesLead).where(SalesLead.id == item.linked_sales_lead_id)
            )).scalar_one_or_none()
            if lead:
                leads.append(_item("lead", lead.id, lead.company or lead.name, href="/leads", status=lead.status))
                tenant_id = lead.tenant_id
                buyers.extend(await cls._buyers_for_entity(db, tenant_id, "lead", lead.id))

        if item.linked_buyer_id:
            buyer = (await db.execute(
                select(Buyer).where(Buyer.id == item.linked_buyer_id)
            )).scalar_one_or_none()
            if buyer:
                buyers.append(_item("buyer", buyer.id, buyer.company_name, href=f"/buyers/{buyer.id}", status=buyer.status))

        if item.linked_sales_deal_id:
            deal = (await db.execute(
                select(SalesDeal).where(SalesDeal.id == item.linked_sales_deal_id)
            )).scalar_one_or_none()
            if deal:
                deals.append(_item("deal", deal.id, deal.title, href="/deals", status=deal.stage))

        tenant_id = None
        if item.linked_sales_lead_id:
            lead = (await db.execute(
                select(SalesLead.tenant_id).where(SalesLead.id == item.linked_sales_lead_id)
            )).scalar_one_or_none()
            tenant_id = lead

        comms = await cls._communications_for(
            db, tenant_id,
            sales_lead_id=item.linked_sales_lead_id,
            sales_deal_id=item.linked_sales_deal_id,
            buyer_id=item.linked_buyer_id,
        )

        return PlatformRelationshipsResponse(
            entity_type="content",
            entity_id=content_id,
            related_leads=leads,
            related_buyers=buyers,
            related_deals=deals,
            related_proposals=[],
            related_communications=comms,
            related_content=[],
            related_customers=[],
        )
