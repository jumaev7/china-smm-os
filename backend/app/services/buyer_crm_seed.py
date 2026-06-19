"""Seed demo Buyer Network CRM data for tenants without existing buyers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_crm import Buyer, BuyerActivity, BuyerEntityLink, BuyerNote
from app.models.sales_crm import SalesCustomer, SalesDeal, SalesLead, SalesProposal
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

_DEMO_BUYERS = [
    {
        "company_name": "Tashkent Trade Group",
        "contact_person": "Aziz Karimov",
        "country": "Uzbekistan",
        "city": "Tashkent",
        "industry": "Construction Materials",
        "website": "https://tashkenttrade.uz",
        "email": "aziz@tashkenttrade.uz",
        "phone": "+998901234567",
        "telegram": "@aziz_tt",
        "whatsapp": "+998901234567",
        "annual_purchase_volume": "$500K–$1M",
        "product_categories": ["Steel", "Cement", "Tiles"],
        "tags": ["Central Asia", "Priority"],
        "status": "negotiating",
        "notes": "Large distributor for building materials across Uzbekistan.",
    },
    {
        "company_name": "Almaty Industrial Supply",
        "contact_person": "Nurbol Sadykov",
        "country": "Kazakhstan",
        "city": "Almaty",
        "industry": "Industrial Equipment",
        "email": "nurbol@almatyind.kz",
        "phone": "+77011234567",
        "telegram": "@nurbol_ais",
        "annual_purchase_volume": "$1M–$3M",
        "product_categories": ["Machinery", "Pumps", "Generators"],
        "tags": ["Kazakhstan", "OEM"],
        "status": "active_buyer",
        "notes": "Repeat buyer — annual framework agreement in place.",
    },
    {
        "company_name": "Bishkek Commerce LLC",
        "contact_person": "Aida Toktomamatova",
        "country": "Kyrgyzstan",
        "city": "Bishkek",
        "industry": "Consumer Goods",
        "email": "aida@bishkekcommerce.kg",
        "phone": "+996555123456",
        "whatsapp": "+996555123456",
        "annual_purchase_volume": "$200K–$500K",
        "product_categories": ["Electronics", "Home Appliances"],
        "tags": ["Kyrgyzstan"],
        "status": "interested",
        "notes": "Requested samples and pricing for Q3 shipment.",
    },
    {
        "company_name": "Dushanbe Import House",
        "contact_person": "Farhod Rahimov",
        "country": "Tajikistan",
        "city": "Dushanbe",
        "industry": "Textiles",
        "email": "farhod@dushanbeimport.tj",
        "phone": "+992901112233",
        "annual_purchase_volume": "$100K–$300K",
        "product_categories": ["Fabrics", "Garments"],
        "tags": ["Tajikistan", "Textile"],
        "status": "contacted",
        "notes": "Met at trade fair — follow up on MOQ.",
    },
    {
        "company_name": "Ashgabat Trading Co",
        "contact_person": "Gurbanguly Orazov",
        "country": "Turkmenistan",
        "city": "Ashgabat",
        "industry": "Agriculture",
        "email": "g.orazov@ashgabattrade.tm",
        "phone": "+99365123456",
        "wechat": "gorazov_tm",
        "annual_purchase_volume": "$300K–$800K",
        "product_categories": ["Irrigation", "Fertilizers", "Seeds"],
        "tags": ["Turkmenistan", "Agri"],
        "status": "prospect",
        "notes": "New prospect from marketplace referral.",
    },
    {
        "company_name": "Samarkand Wholesale",
        "contact_person": "Dilnoza Mirzayeva",
        "country": "Uzbekistan",
        "city": "Samarkand",
        "industry": "Food & Beverage",
        "email": "dilnoza@samwholesale.uz",
        "phone": "+998931234567",
        "telegram": "@dilnoza_sw",
        "annual_purchase_volume": "$150K–$400K",
        "product_categories": ["Packaging", "Beverages"],
        "tags": ["Uzbekistan"],
        "status": "inactive",
        "notes": "Paused orders due to local regulatory review.",
    },
]


async def seed_buyer_crm_demo(db: AsyncSession) -> None:
    """Idempotent seed — skips tenants that already have buyers."""
    tenants = (await db.execute(select(Tenant).limit(20))).scalars().all()
    if not tenants:
        return

    for tenant in tenants:
        existing = (await db.execute(
            select(func.count()).select_from(Buyer).where(Buyer.tenant_id == tenant.id)
        )).scalar_one()
        if existing > 0:
            continue

        now = datetime.now(timezone.utc)
        created_buyers: list[Buyer] = []

        for idx, spec in enumerate(_DEMO_BUYERS):
            buyer = Buyer(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                created_at=now - timedelta(days=30 - idx * 4),
                **spec,
            )
            db.add(buyer)
            created_buyers.append(buyer)

        await db.flush()

        for buyer in created_buyers[:3]:
            db.add(BuyerNote(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                buyer_id=buyer.id,
                content=f"Initial outreach to {buyer.contact_person} at {buyer.company_name}.",
                created_by="demo@factory.local",
                created_at=now - timedelta(days=10),
            ))
            db.add(BuyerActivity(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                buyer_id=buyer.id,
                type="call",
                title="Introductory call",
                description="Discussed product range and shipping terms.",
                created_by="demo@factory.local",
                activity_date=now - timedelta(days=8),
            ))

        lead = (await db.execute(
            select(SalesLead).where(SalesLead.tenant_id == tenant.id).limit(1)
        )).scalar_one_or_none()
        customer = (await db.execute(
            select(SalesCustomer).where(SalesCustomer.tenant_id == tenant.id).limit(1)
        )).scalar_one_or_none()
        deal = (await db.execute(
            select(SalesDeal).where(SalesDeal.tenant_id == tenant.id).limit(1)
        )).scalar_one_or_none()
        proposal = (await db.execute(
            select(SalesProposal).where(SalesProposal.tenant_id == tenant.id).limit(1)
        )).scalar_one_or_none()

        primary = created_buyers[0]
        if lead:
            db.add(BuyerEntityLink(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                buyer_id=primary.id,
                entity_type="lead",
                entity_id=lead.id,
            ))
        if customer:
            db.add(BuyerEntityLink(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                buyer_id=primary.id,
                entity_type="customer",
                entity_id=customer.id,
            ))
        if deal:
            db.add(BuyerEntityLink(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                buyer_id=created_buyers[1].id,
                entity_type="deal",
                entity_id=deal.id,
            ))
        if proposal:
            db.add(BuyerEntityLink(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                buyer_id=created_buyers[1].id,
                entity_type="proposal",
                entity_id=proposal.id,
            ))

        await db.commit()
        logger.info("Seeded buyer CRM demo for tenant %s", tenant.id)
