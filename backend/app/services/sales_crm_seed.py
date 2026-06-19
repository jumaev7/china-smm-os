"""Seed demo Sales CRM data for tenants without existing records."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales_crm import SalesActivity, SalesCustomer, SalesDeal, SalesLead, SalesProposal, SalesProposalItem
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


async def seed_sales_crm_demo(db: AsyncSession) -> None:
    """Idempotent seed — skips tenants that already have sales leads."""
    tenants = (await db.execute(select(Tenant).limit(20))).scalars().all()
    if not tenants:
        return

    for tenant in tenants:
        existing = (await db.execute(
            select(func.count()).select_from(SalesLead).where(SalesLead.tenant_id == tenant.id)
        )).scalar_one()
        if existing > 0:
            continue

        now = datetime.now(timezone.utc)
        customer1 = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="Ahmed Al-Rashid",
            company="Gulf Trading LLC",
            phone="+971501234567",
            email="ahmed@gulftrading.ae",
            telegram="@ahmed_gulf",
            whatsapp="+971501234567",
            country="UAE",
            city="Dubai",
            notes="Key buyer for textile exports.",
        )
        customer2 = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="Maria Santos",
            company="Brasil Import Co",
            phone="+5511987654321",
            email="maria@brasilimport.com.br",
            whatsapp="+5511987654321",
            country="Brazil",
            city="São Paulo",
            notes="Interested in agricultural machinery.",
        )
        db.add_all([customer1, customer2])
        await db.flush()

        lead1 = SalesLead(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            customer_id=customer1.id,
            name="Ahmed Al-Rashid",
            company="Gulf Trading LLC",
            phone="+971501234567",
            email="ahmed@gulftrading.ae",
            source="referral",
            status="qualified",
            priority="high",
            country="UAE",
            city="Dubai",
            assigned_to="sales@demo.com",
            notes="Requested product catalog and MOQ details.",
        )
        lead2 = SalesLead(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name="Chen Wei",
            company="Shanghai Electronics",
            phone="+8613812345678",
            email="chen@shanghai-elec.cn",
            wechat="chenwei_sz",
            source="exhibition",
            status="new",
            priority="medium",
            country="China",
            city="Shanghai",
            notes="Met at Canton Fair — follow up within 48h.",
        )
        lead3 = SalesLead(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            customer_id=customer2.id,
            name="Maria Santos",
            company="Brasil Import Co",
            email="maria@brasilimport.com.br",
            source="website",
            status="contacted",
            priority="high",
            country="Brazil",
            city="São Paulo",
        )
        db.add_all([lead1, lead2, lead3])
        await db.flush()

        deal1 = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            customer_id=customer1.id,
            lead_id=lead1.id,
            title="Gulf Trading — Q3 Textile Order",
            value=Decimal("85000"),
            currency="USD",
            stage="negotiation",
            probability=60,
            expected_close_date=now + timedelta(days=30),
            notes="Volume discount under discussion.",
        )
        deal2 = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            lead_id=lead2.id,
            title="Shanghai Electronics — Component Supply",
            value=Decimal("42000"),
            currency="USD",
            stage="new_lead",
            probability=20,
            expected_close_date=now + timedelta(days=60),
        )
        deal3 = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            customer_id=customer2.id,
            lead_id=lead3.id,
            title="Brasil Import — Machinery Deal",
            value=Decimal("120000"),
            currency="USD",
            stage="proposal_sent",
            probability=75,
            expected_close_date=now + timedelta(days=14),
        )
        db.add_all([deal1, deal2, deal3])
        await db.flush()

        activities = [
            SalesActivity(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                type="call",
                title="Intro call with Ahmed",
                description="Discussed product range and shipping terms.",
                customer_id=customer1.id,
                lead_id=lead1.id,
                deal_id=deal1.id,
                created_by="sales@demo.com",
                activity_date=now - timedelta(days=2),
            ),
            SalesActivity(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                type="email",
                title="Sent proposal to Maria",
                description="Proposal #2024-089 attached.",
                customer_id=customer2.id,
                lead_id=lead3.id,
                deal_id=deal3.id,
                created_by="sales@demo.com",
                activity_date=now - timedelta(days=1),
            ),
            SalesActivity(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                type="meeting",
                title="Canton Fair follow-up scheduled",
                lead_id=lead2.id,
                deal_id=deal2.id,
                created_by="sales@demo.com",
                activity_date=now - timedelta(hours=6),
            ),
        ]
        db.add_all(activities)

        proposal1 = SalesProposal(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            proposal_number=f"PROP-{now.year}-0001",
            title="Gulf Trading — Q3 Textile Quotation",
            customer_id=customer1.id,
            lead_id=lead1.id,
            deal_id=deal1.id,
            issue_date=now - timedelta(days=3),
            valid_until=now + timedelta(days=27),
            currency="USD",
            subtotal=Decimal("85000"),
            discount=Decimal("2500"),
            tax=Decimal("0"),
            total=Decimal("82500"),
            status="sent",
            notes="Volume discount applied for 500+ units.",
            terms="Payment: 30% advance, 70% before shipment. Delivery: 45 days FOB.",
            status_history=[
                {"status": "draft", "at": (now - timedelta(days=4)).isoformat(), "note": "Proposal created"},
                {"status": "sent", "at": (now - timedelta(days=3)).isoformat(), "note": None},
            ],
        )
        proposal2 = SalesProposal(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            proposal_number=f"PROP-{now.year}-0002",
            title="Brasil Import — Machinery Quote",
            customer_id=customer2.id,
            lead_id=lead3.id,
            deal_id=deal3.id,
            issue_date=now - timedelta(days=1),
            valid_until=now + timedelta(days=29),
            currency="USD",
            subtotal=Decimal("120000"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("120000"),
            status="draft",
            terms="Valid for 30 days. Incoterms: CIF Santos.",
            status_history=[
                {"status": "draft", "at": (now - timedelta(days=1)).isoformat(), "note": "Proposal created"},
            ],
        )
        db.add_all([proposal1, proposal2])
        await db.flush()

        db.add_all([
            SalesProposalItem(
                id=uuid.uuid4(),
                proposal_id=proposal1.id,
                product_or_service_name="Premium Cotton Fabric — Grade A",
                description="500 rolls, assorted colors",
                quantity=Decimal("500"),
                unit_price=Decimal("120"),
                discount=Decimal("2500"),
                total=Decimal("57500"),
                sort_order=0,
            ),
            SalesProposalItem(
                id=uuid.uuid4(),
                proposal_id=proposal1.id,
                product_or_service_name="Polyester Blend — Export Grade",
                description="300 rolls",
                quantity=Decimal("300"),
                unit_price=Decimal("95"),
                discount=Decimal("0"),
                total=Decimal("28500"),
                sort_order=1,
            ),
            SalesProposalItem(
                id=uuid.uuid4(),
                proposal_id=proposal2.id,
                product_or_service_name="Industrial Harvester Model X200",
                description="Includes installation and 1-year warranty",
                quantity=Decimal("2"),
                unit_price=Decimal("60000"),
                discount=Decimal("0"),
                total=Decimal("120000"),
                sort_order=0,
            ),
        ])

        logger.info("Seeded Sales CRM demo data for tenant %s", tenant.id)

    await db.commit()
