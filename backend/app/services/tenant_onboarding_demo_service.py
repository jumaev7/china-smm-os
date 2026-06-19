"""One-click demo environment for factory onboarding."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_crm import Buyer, BuyerActivity
from app.models.communication import CommunicationContact, CommunicationFollowUp, CommunicationMessage, CommunicationThread
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.models.sales_crm import SalesActivity, SalesCustomer, SalesDeal, SalesLead, SalesProposal, SalesProposalItem
from app.models.tenant import Tenant
from app.services.communication_template_service import CommunicationTemplateService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)
MARKER = "[Onboarding Demo]"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TenantOnboardingDemoService:
    @staticmethod
    async def generate_for_tenant(db: AsyncSession, tenant_id: UUID) -> dict[str, int]:
        """Seed demo buyers, leads, deals, proposals, communications, and sample content."""
        tenant = await TenantService.get_tenant(db, tenant_id)
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        client_id = client_ids[0] if client_ids else None

        counts: dict[str, int] = {
            "buyers": 0,
            "leads": 0,
            "deals": 0,
            "proposals": 0,
            "communications": 0,
            "content": 0,
        }
        now = _utcnow()

        buyer_count = int(
            (await db.execute(select(func.count()).select_from(Buyer).where(Buyer.tenant_id == tenant_id))).scalar() or 0
        )
        if buyer_count == 0:
            demo_buyers = [
                ("Gulf Import Partners", "Ahmed Hassan", "UAE", "Dubai", "Electronics"),
                ("Central Asia Trade", "Dilshod Rakhimov", "Uzbekistan", "Tashkent", "Textiles"),
                ("Euro Wholesale GmbH", "Klaus Weber", "Germany", "Hamburg", "Machinery"),
            ]
            for company, contact, country, city, industry in demo_buyers:
                buyer = Buyer(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    company_name=company,
                    contact_person=contact,
                    country=country,
                    city=city,
                    industry=industry,
                    email=f"{contact.split()[0].lower()}@demo.example",
                    status="interested",
                    notes=f"{MARKER} Demo buyer for onboarding preview.",
                    tags=["demo", "onboarding"],
                )
                db.add(buyer)
                await db.flush()
                db.add(BuyerActivity(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    buyer_id=buyer.id,
                    type="note",
                    title="Initial demo inquiry",
                    description="Interested in product catalog.",
                    created_by="onboarding-demo",
                ))
                counts["buyers"] += 1

        lead_count = int(
            (await db.execute(
                select(func.count()).select_from(SalesLead).where(SalesLead.tenant_id == tenant_id)
            )).scalar() or 0
        )
        if lead_count == 0:
            customer = SalesCustomer(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                name="Maria Santos",
                company="Brasil Import Co",
                email="maria@demo.example",
                country="Brazil",
                city="São Paulo",
                notes=f"{MARKER} Demo customer.",
            )
            db.add(customer)
            await db.flush()

            lead1 = SalesLead(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                customer_id=customer.id,
                name="Maria Santos",
                company="Brasil Import Co",
                email="maria@demo.example",
                source="website",
                status="qualified",
                priority="high",
                country="Brazil",
                notes=f"{MARKER} Demo lead.",
            )
            lead2 = SalesLead(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                name="Chen Wei",
                company="Shanghai Electronics",
                email="chen@demo.example",
                source="exhibition",
                status="new",
                priority="medium",
                country="China",
                notes=f"{MARKER} Demo lead.",
            )
            db.add_all([lead1, lead2])
            await db.flush()
            counts["leads"] += 2

            deal = SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                customer_id=customer.id,
                lead_id=lead1.id,
                title="Brasil Import — Machinery Order",
                value=Decimal("95000"),
                currency="USD",
                stage="negotiation",
                probability=55,
                expected_close_date=now + timedelta(days=21),
                notes=f"{MARKER} Demo deal.",
            )
            db.add(deal)
            await db.flush()
            counts["deals"] += 1

            proposal = SalesProposal(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                proposal_number=f"DEMO-{now.year}-0001",
                customer_id=customer.id,
                lead_id=lead1.id,
                deal_id=deal.id,
                title="Machinery Supply Proposal — Q2",
                issue_date=now,
                valid_until=now + timedelta(days=14),
                currency="USD",
                subtotal=Decimal("95000"),
                discount=Decimal("0"),
                tax=Decimal("0"),
                total=Decimal("95000"),
                status="sent",
                notes=f"{MARKER} Demo proposal.",
            )
            db.add(proposal)
            await db.flush()
            db.add(SalesProposalItem(
                id=uuid.uuid4(),
                proposal_id=proposal.id,
                product_or_service_name="Industrial CNC Machine — Model X200",
                description="Includes installation support",
                quantity=Decimal("2"),
                unit_price=Decimal("47500"),
                discount=Decimal("0"),
                total=Decimal("95000"),
                sort_order=0,
            ))
            counts["proposals"] += 1

            db.add(SalesActivity(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                type="email",
                title="Sent product catalog",
                description="Sent product catalog to demo lead.",
                lead_id=lead1.id,
                deal_id=deal.id,
                created_by="onboarding-demo",
                activity_date=now,
            ))

        thread_count = int(
            (await db.execute(
                select(func.count()).select_from(CommunicationThread).where(
                    CommunicationThread.tenant_id == tenant_id,
                )
            )).scalar() or 0
        )
        if thread_count == 0:
            await CommunicationTemplateService.ensure_default_templates(db, tenant_id)
            contact = CommunicationContact(
                tenant_id=tenant_id,
                name="Dmitry Petrov",
                company="Almaty Trading LLC",
                country="Kazakhstan",
                telegram="@dmitry_demo",
            )
            db.add(contact)
            await db.flush()
            thread = CommunicationThread(
                tenant_id=tenant_id,
                contact_id=contact.id,
                channel="telegram",
                title="Product inquiry — demo",
                status="open",
                last_message_at=now - timedelta(hours=2),
            )
            db.add(thread)
            await db.flush()
            db.add(CommunicationMessage(
                thread_id=thread.id,
                direction="inbound",
                sender_name="Dmitry Petrov",
                message_text=f"{MARKER} Hello, we need MOQ and lead time for your products.",
                status="unanswered",
            ))
            db.add(CommunicationFollowUp(
                tenant_id=tenant_id,
                thread_id=thread.id,
                title="Follow up on demo inquiry",
                description="Send catalog and MOQ details.",
                due_date=now + timedelta(days=1),
                status="pending",
            ))
            counts["communications"] += 1

        if client_id:
            content_count = int(
                (await db.execute(
                    select(func.count()).select_from(ContentItem).where(ContentItem.client_id == client_id)
                )).scalar() or 0
            )
            if content_count == 0:
                media = MediaFile(
                    id=uuid.uuid4(),
                    client_id=client_id,
                    original_filename="onboarding-demo-product.jpg",
                    file_type="image",
                    mime_type="image/jpeg",
                    storage_path="/demo/onboarding-product.jpg",
                    file_size=102400,
                )
                db.add(media)
                await db.flush()
                db.add(ContentItem(
                    id=uuid.uuid4(),
                    client_id=client_id,
                    media_file_id=media.id,
                    status="draft",
                    caption_short_en=f"{MARKER} Premium factory products — ready for export.",
                    caption_short_ru="Демо контент — продукция для экспорта.",
                    internal_notes="Generated by onboarding demo environment.",
                ))
                counts["content"] += 1

        if tenant.company_name.startswith("Demo") or not tenant.company_name.strip():
            pass  # leave tenant name as-is

        await db.flush()
        logger.info("%s Generated demo data for tenant %s: %s", MARKER, tenant_id, counts)
        return counts
