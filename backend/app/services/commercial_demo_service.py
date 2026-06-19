"""Commercial Demo Factory Experience — demo packages, tour, value & executive views."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_crm import Buyer, BuyerActivity
from app.models.communication import (
    CommunicationContact,
    CommunicationFollowUp,
    CommunicationMessage,
    CommunicationThread,
)
from app.models.content import ContentItem
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.media import MediaFile
from app.models.sales_crm import (
    SalesActivity,
    SalesCustomer,
    SalesDeal,
    SalesLead,
    SalesProposal,
    SalesProposalItem,
)
from app.schemas.commercial_demo import (
    DemoFactoryLoadResponse,
    DemoFactoryPackageId,
    DemoFactoryPackageList,
    DemoFactoryPackageSummary,
    DemoReadinessResponse,
    DemoTourResponse,
    DemoTourStep,
    ExecutiveDemoKpi,
    ExecutiveDemoResponse,
    ExecutiveDemoSection,
    ExportGrowthStoryResponse,
    ExportGrowthStoryStep,
    PositioningComparison,
    ProductPositioningResponse,
    ReadinessComponent,
    ValueDemoAction,
    ValueDemoResponse,
)
from app.services.communication_template_service import CommunicationTemplateService
from app.services.factory_platform_service import FactoryPlatformService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)
MARKER = "[Commercial Demo]"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


# ── Factory package definitions ──────────────────────────────────────────────

_FACTORY_PACKAGES: dict[str, dict[str, Any]] = {
    "haocheng": {
        "company_name": "Haocheng Industry Group",
        "brand_name": "Haocheng",
        "industry": "Manufacturing / Industrial Equipment",
        "country": "China",
        "city": "Shenzhen",
        "description": (
            "Leading manufacturer of CNC machinery, industrial pumps, and precision equipment "
            "serving export markets across Central Asia, Middle East, and Southeast Asia."
        ),
        "highlights": [
            "ISO 9001 certified factory with 15+ years export experience",
            "Active pipeline across UAE, Kazakhstan, and Brazil",
            "AI-generated product content in 4 languages",
        ],
        "markets": ["UAE", "Kazakhstan", "Brazil", "Indonesia"],
        "product_categories": ["CNC Machinery", "Industrial Pumps", "Precision Equipment"],
        "buyers": [
            ("Gulf Industrial Supply", "Ahmed Hassan", "UAE", "Dubai", "Industrial Equipment"),
            ("Almaty Machinery Trading", "Dilshod Rakhimov", "Kazakhstan", "Almaty", "Machinery"),
            ("Brasil Import Co", "Maria Santos", "Brazil", "São Paulo", "Manufacturing"),
            ("Jakarta Equipment Hub", "Budi Santoso", "Indonesia", "Jakarta", "Industrial"),
            ("Euro Wholesale GmbH", "Klaus Weber", "Germany", "Hamburg", "Machinery"),
        ],
        "leads": [
            ("Ahmed Hassan", "Gulf Industrial Supply", "qualified", "high", "UAE", 120000),
            ("Maria Santos", "Brasil Import Co", "negotiation", "high", "Brazil", 95000),
            ("Chen Wei", "Shanghai Electronics", "new", "medium", "China", 45000),
        ],
        "deals": [
            ("Brasil Import — CNC Line Order", 95000, "negotiation", 55),
            ("Gulf Industrial — Pump Systems", 120000, "proposal_sent", 70),
        ],
        "content_captions": [
            "Haocheng CNC Model X200 — precision engineering for global markets.",
            "Industrial pump systems — ISO certified, export-ready packaging.",
            "Factory tour: 50,000 sqm production facility in Shenzhen.",
        ],
        "communications": [
            ("Ahmed Hassan", "Gulf Industrial Supply", "UAE", "We need MOQ and lead time for CNC machines."),
            ("Maria Santos", "Brasil Import Co", "Brazil", "Please send updated pricing for Q2 shipment."),
        ],
    },
    "toy_manufacturer": {
        "company_name": "BrightPlay Toys Co.",
        "brand_name": "BrightPlay",
        "industry": "Toys & Children's Products",
        "country": "China",
        "city": "Shantou",
        "description": (
            "OEM/ODM toy manufacturer specializing in educational toys, plush products, "
            "and licensed character merchandise for global retail chains."
        ),
        "highlights": [
            "EN71 & ASTM certified product lines",
            "Buyers in EU, US, and Middle East retail channels",
            "Seasonal catalog with AI-generated marketing content",
        ],
        "markets": ["Germany", "USA", "UAE", "Poland"],
        "product_categories": ["Educational Toys", "Plush Toys", "Outdoor Play"],
        "buyers": [
            ("KinderWorld Retail", "Anna Müller", "Germany", "Hamburg", "Retail"),
            ("PlayMart USA", "James Wilson", "USA", "Chicago", "Retail"),
            ("Dubai Kids Store", "Fatima Al-Rashid", "UAE", "Dubai", "Retail"),
            ("Polska Zabawki Sp.", "Piotr Kowalski", "Poland", "Warsaw", "Wholesale"),
        ],
        "leads": [
            ("Anna Müller", "KinderWorld Retail", "qualified", "high", "Germany", 85000),
            ("James Wilson", "PlayMart USA", "contacted", "high", "USA", 150000),
            ("Fatima Al-Rashid", "Dubai Kids Store", "new", "medium", "UAE", 35000),
        ],
        "deals": [
            ("KinderWorld — Educational Toy Line", 85000, "negotiation", 60),
            ("PlayMart USA — Plush Collection Q3", 150000, "proposal_sent", 45),
        ],
        "content_captions": [
            "BrightPlay educational building sets — STEM learning for ages 3-8.",
            "New plush collection — soft, safe, certified for global markets.",
            "Factory showcase: 200+ SKUs ready for private label orders.",
        ],
        "communications": [
            ("Anna Müller", "KinderWorld Retail", "Germany", "Interested in EN71 certified building sets for Christmas season."),
            ("James Wilson", "PlayMart USA", "USA", "Need samples and FOB pricing for plush line."),
        ],
    },
    "textile_factory": {
        "company_name": "SilkRoad Textiles Ltd.",
        "brand_name": "SilkRoad",
        "industry": "Textiles & Garments",
        "country": "China",
        "city": "Guangzhou",
        "description": (
            "Full-service textile factory producing woven fabrics, knitwear, and ready-to-wear "
            "garments for fashion brands and uniform suppliers worldwide."
        ),
        "highlights": [
            "OEKO-TEX Standard 100 certified materials",
            "Active buyers in EU fashion and Central Asia uniform markets",
            "AI content for fabric catalogs and trend reports",
        ],
        "markets": ["Italy", "Uzbekistan", "Turkey", "France"],
        "product_categories": ["Woven Fabrics", "Knitwear", "Ready-to-Wear"],
        "buyers": [
            ("Milano Fashion House", "Luca Rossi", "Italy", "Milan", "Fashion"),
            ("Tashkent Uniforms", "Aziz Karimov", "Uzbekistan", "Tashkent", "Uniforms"),
            ("Istanbul Textile Trade", "Mehmet Yilmaz", "Turkey", "Istanbul", "Textiles"),
            ("Paris Mode SARL", "Sophie Laurent", "France", "Paris", "Fashion"),
        ],
        "leads": [
            ("Luca Rossi", "Milano Fashion House", "qualified", "high", "Italy", 110000),
            ("Aziz Karimov", "Tashkent Uniforms", "negotiation", "high", "Uzbekistan", 65000),
            ("Sophie Laurent", "Paris Mode SARL", "new", "medium", "France", 40000),
        ],
        "deals": [
            ("Milano Fashion — Spring Collection Fabrics", 110000, "negotiation", 65),
            ("Tashkent Uniforms — Corporate Line", 65000, "proposal_sent", 50),
        ],
        "content_captions": [
            "SilkRoad spring/summer fabric collection — sustainable cotton blends.",
            "Knitwear production line — 500,000 units/month capacity.",
            "OEKO-TEX certified materials for European fashion brands.",
        ],
        "communications": [
            ("Luca Rossi", "Milano Fashion House", "Italy", "Need fabric swatches for SS26 collection review."),
            ("Aziz Karimov", "Tashkent Uniforms", "Uzbekistan", "Requesting quote for 10,000 uniform sets."),
        ],
    },
}


class CommercialDemoService:
    @staticmethod
    def list_packages() -> DemoFactoryPackageList:
        packages = [
            DemoFactoryPackageSummary(
                id=pid,  # type: ignore[arg-type]
                company_name=cfg["company_name"],
                industry=cfg["industry"],
                country=cfg["country"],
                description=cfg["description"],
                highlights=cfg["highlights"],
            )
            for pid, cfg in _FACTORY_PACKAGES.items()
        ]
        return DemoFactoryPackageList(packages=packages)

    @staticmethod
    async def load_factory_package(
        db: AsyncSession,
        tenant_id: UUID,
        package_id: DemoFactoryPackageId,
    ) -> DemoFactoryLoadResponse:
        cfg = _FACTORY_PACKAGES.get(package_id)
        if not cfg:
            raise ValueError(f"Unknown demo package: {package_id}")

        tenant = await TenantService.get_tenant(db, tenant_id)
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        client_id = client_ids[0] if client_ids else None
        now = _utcnow()
        counts: dict[str, int] = {
            "buyers": 0, "leads": 0, "deals": 0, "proposals": 0,
            "communications": 0, "content": 0, "activities": 0,
        }

        tenant.company_name = cfg["company_name"]
        await db.flush()

        try:
            scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
            profile = await FactoryPlatformService._get_or_seed_profile(db, scope)
            profile.company_name = cfg["company_name"]
            profile.brand_name = cfg["brand_name"]
            profile.country = cfg["country"]
            profile.city = cfg["city"]
            profile.industry = cfg["industry"]
            profile.company_description = cfg["description"]
            profile.markets = cfg["markets"]
            profile.export_regions = cfg["markets"]
            profile.product_categories = cfg["product_categories"]
            profile.industries = [cfg["industry"]]
            profile.verification_status = "verified"
            await db.flush()
        except Exception:
            logger.debug("%s Could not update factory profile for tenant %s", MARKER, tenant_id)

        for company, contact, country, city, industry in cfg["buyers"]:
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
                notes=f"{MARKER} {cfg['company_name']} demo buyer.",
                tags=["demo", package_id],
            )
            db.add(buyer)
            await db.flush()
            db.add(BuyerActivity(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                buyer_id=buyer.id,
                type="inquiry",
                title="Initial product inquiry",
                description=f"Interested in {cfg['industry']} products.",
                created_by="commercial-demo",
            ))
            counts["buyers"] += 1

        customers: list[SalesCustomer] = []
        for name, company, _status, _priority, country, _value in cfg["leads"]:
            existing = await db.scalar(
                select(SalesCustomer).where(
                    SalesCustomer.tenant_id == tenant_id,
                    SalesCustomer.company == company,
                ).limit(1),
            )
            if existing:
                customers.append(existing)
                continue
            customer = SalesCustomer(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                name=name,
                company=company,
                email=f"{name.split()[0].lower()}@demo.example",
                country=country,
                notes=f"{MARKER} Demo customer.",
            )
            db.add(customer)
            await db.flush()
            customers.append(customer)

        leads: list[SalesLead] = []
        for idx, (name, company, status, priority, country, _value) in enumerate(cfg["leads"]):
            customer = customers[idx] if idx < len(customers) else None
            lead = SalesLead(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                customer_id=customer.id if customer else None,
                name=name,
                company=company,
                email=f"{name.split()[0].lower()}@demo.example",
                source="buyer_discovery",
                status=status,
                priority=priority,
                country=country,
                notes=f"{MARKER} Demo lead from {package_id}.",
            )
            db.add(lead)
            await db.flush()
            leads.append(lead)
            counts["leads"] += 1

        deals: list[SalesDeal] = []
        for idx, (title, value, stage, probability) in enumerate(cfg["deals"]):
            lead = leads[idx] if idx < len(leads) else None
            customer = customers[idx] if idx < len(customers) else None
            deal = SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                customer_id=customer.id if customer else None,
                lead_id=lead.id if lead else None,
                title=title,
                value=Decimal(str(value)),
                currency="USD",
                stage=stage,
                probability=probability,
                expected_close_date=now + timedelta(days=21 + idx * 7),
                notes=f"{MARKER} Demo deal.",
            )
            db.add(deal)
            await db.flush()
            deals.append(deal)
            counts["deals"] += 1

            proposal = SalesProposal(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                proposal_number=f"DEMO-{now.year}-{idx + 1:04d}",
                customer_id=customer.id if customer else None,
                lead_id=lead.id if lead else None,
                deal_id=deal.id,
                title=f"Proposal — {title}",
                issue_date=now,
                valid_until=now + timedelta(days=14),
                currency="USD",
                subtotal=Decimal(str(value)),
                discount=Decimal("0"),
                tax=Decimal("0"),
                total=Decimal(str(value)),
                status="sent",
                notes=f"{MARKER} Demo proposal.",
            )
            db.add(proposal)
            await db.flush()
            db.add(SalesProposalItem(
                id=uuid.uuid4(),
                proposal_id=proposal.id,
                product_or_service_name=title.split("—")[0].strip() if "—" in title else title,
                description="Export-ready products with full documentation",
                quantity=Decimal("1"),
                unit_price=Decimal(str(value)),
                discount=Decimal("0"),
                total=Decimal(str(value)),
                sort_order=0,
            ))
            counts["proposals"] += 1

            db.add(SalesActivity(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                type="email",
                title="Sent product catalog",
                description=f"Sent catalog for {title}.",
                lead_id=lead.id if lead else None,
                deal_id=deal.id,
                created_by="commercial-demo",
                activity_date=now - timedelta(hours=idx * 4),
            ))
            counts["activities"] += 1

        await CommunicationTemplateService.ensure_default_templates(db, tenant_id)
        for idx, (name, company, country, message) in enumerate(cfg["communications"]):
            contact = CommunicationContact(
                tenant_id=tenant_id,
                name=name,
                company=company,
                country=country,
                email=f"{name.split()[0].lower()}@demo.example",
            )
            db.add(contact)
            await db.flush()
            thread = CommunicationThread(
                tenant_id=tenant_id,
                contact_id=contact.id,
                channel="email" if idx % 2 else "telegram",
                title=f"Inquiry from {company}",
                status="open",
                last_message_at=now - timedelta(hours=idx * 3 + 1),
            )
            db.add(thread)
            await db.flush()
            db.add(CommunicationMessage(
                thread_id=thread.id,
                direction="inbound",
                sender_name=name,
                message_text=f"{MARKER} {message}",
                status="unanswered" if idx == 0 else "answered",
            ))
            db.add(CommunicationFollowUp(
                tenant_id=tenant_id,
                thread_id=thread.id,
                title=f"Follow up with {name}",
                description="Send catalog, MOQ, and lead time details.",
                due_date=now + timedelta(days=1 + idx),
                status="pending",
            ))
            counts["communications"] += 1

        if client_id:
            for idx, caption in enumerate(cfg["content_captions"]):
                media = MediaFile(
                    id=uuid.uuid4(),
                    client_id=client_id,
                    original_filename=f"demo-{package_id}-{idx + 1}.jpg",
                    file_type="image",
                    mime_type="image/jpeg",
                    storage_path=f"/demo/{package_id}-{idx + 1}.jpg",
                    file_size=102400,
                )
                db.add(media)
                await db.flush()
                db.add(ContentItem(
                    id=uuid.uuid4(),
                    client_id=client_id,
                    media_file_id=media.id,
                    status="approved" if idx == 0 else "draft",
                    caption_short_en=f"{MARKER} {caption}",
                    caption_short_ru="Демо контент для экспортного рынка.",
                    internal_notes=f"Generated by commercial demo package {package_id}.",
                ))
                counts["content"] += 1

        await db.commit()
        logger.info("%s Loaded package %s for tenant %s: %s", MARKER, package_id, tenant_id, counts)

        return DemoFactoryLoadResponse(
            loaded=True,
            package_id=package_id,
            company_name=cfg["company_name"],
            message=f"Demo environment loaded for {cfg['company_name']}. Explore buyers, pipeline, and growth metrics.",
            counts=counts,
        )

    @staticmethod
    def get_tour() -> DemoTourResponse:
        steps = [
            DemoTourStep(
                order=1, id="factory_profile", title="Factory Profile",
                description="Complete company profile with products, certificates, and export markets.",
                route="/onboarding", minutes=1,
                talking_points=["Verified factory identity", "Export-ready catalog", "Target market configuration"],
                business_value="Buyers trust factories with complete profiles — 3× higher response rates.",
            ),
            DemoTourStep(
                order=2, id="content_factory", title="AI Content Factory",
                description="Upload product photos and let AI generate multilingual marketing content.",
                route="/content-factory", minutes=2,
                talking_points=["Telegram photo upload", "AI captions in 4 languages", "Content review workflow"],
                business_value="Save 20+ hours/week on content creation for export markets.",
            ),
            DemoTourStep(
                order=3, id="buyer_network", title="Buyer Network",
                description="Discover and connect with qualified international buyers.",
                route="/buyer-network", minutes=1,
                talking_points=["Buyer discovery engine", "Relationship mapping", "Market intelligence"],
                business_value="Find buyers you would never reach through traditional channels.",
            ),
            DemoTourStep(
                order=4, id="crm", title="CRM Pipeline",
                description="Track leads, deals, and proposals in one export-focused CRM.",
                route="/deals", minutes=2,
                talking_points=["Lead scoring", "Deal stages", "Proposal generation"],
                business_value="Never lose an export opportunity — full pipeline visibility.",
            ),
            DemoTourStep(
                order=5, id="communications", title="Communication Hub",
                description="Manage all buyer conversations across Telegram, email, and WhatsApp.",
                route="/communications", minutes=1,
                talking_points=["Unified inbox", "Follow-up reminders", "Message templates"],
                business_value="Respond faster to buyers — speed wins export deals.",
            ),
            DemoTourStep(
                order=6, id="ai_assistant", title="AI Assistant",
                description="Get AI-powered recommendations for sales, content, and buyer outreach.",
                route="/sales-assistant", minutes=1,
                talking_points=["Smart recommendations", "Action items", "Market insights"],
                business_value="AI acts as your export sales advisor — available 24/7.",
            ),
            DemoTourStep(
                order=7, id="growth_center", title="Growth Center",
                description="Executive dashboard showing pipeline growth, market expansion, and trends.",
                route="/growth-center", minutes=1,
                talking_points=["Pipeline KPIs", "Market insights", "Growth recommendations"],
                business_value="See your export business health at a glance.",
            ),
            DemoTourStep(
                order=8, id="roi_center", title="ROI Center",
                description="Measure platform impact on revenue, buyer acquisition, and export growth.",
                route="/customer-success/roi", minutes=1,
                talking_points=["ROI metrics", "Business impact", "Adoption tracking"],
                business_value="Prove the platform pays for itself with measurable export results.",
            ),
        ]
        return DemoTourResponse(steps=steps, estimated_minutes=10)

    @staticmethod
    async def get_export_growth_story(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> ExportGrowthStoryResponse:
        metrics = await CommercialDemoService._aggregate_metrics(db, tenant_id)
        pipeline = metrics.get("pipeline_value_usd", 0) or 185000

        steps = [
            ExportGrowthStoryStep(
                order=1, id="upload", title="Factory Uploads Content",
                description="Factory team uploads product photos via Telegram.",
                route="/content-factory", status="complete",
                metric_label="Content pieces", metric_value=str(metrics.get("content_pieces", 3)),
            ),
            ExportGrowthStoryStep(
                order=2, id="ai_content", title="AI Creates Content",
                description="AI generates multilingual captions and marketing copy.",
                route="/content-factory/generate", status="complete",
                metric_label="Languages", metric_value="4",
            ),
            ExportGrowthStoryStep(
                order=3, id="buyer_found", title="Buyer Discovered",
                description="AI matches products with qualified international buyers.",
                route="/buyer-network", status="complete",
                metric_label="Buyers found", metric_value=str(metrics.get("buyers_found", 5)),
            ),
            ExportGrowthStoryStep(
                order=4, id="lead_created", title="Lead Created",
                description="Buyer inquiry automatically creates a tracked sales lead.",
                route="/leads", status="complete",
                metric_label="Active leads", metric_value=str(metrics.get("leads_count", 3)),
            ),
            ExportGrowthStoryStep(
                order=5, id="communication", title="Communication Starts",
                description="Buyer message appears in Communication Hub with follow-up reminder.",
                route="/communications", status="active",
                metric_label="Open threads", metric_value=str(metrics.get("communications_active", 2)),
            ),
            ExportGrowthStoryStep(
                order=6, id="deal_created", title="Deal Created",
                description="Qualified lead progresses to active deal in CRM pipeline.",
                route="/deals", status="active",
                metric_label="Active deals", metric_value=str(metrics.get("active_deals", 2)),
            ),
            ExportGrowthStoryStep(
                order=7, id="proposal_sent", title="Proposal Sent",
                description="Professional export proposal generated and sent to buyer.",
                route="/proposals", status="active",
                metric_label="Proposals sent", metric_value=str(metrics.get("proposals_sent", 2)),
            ),
            ExportGrowthStoryStep(
                order=8, id="revenue", title="Revenue Opportunity",
                description="Pipeline value grows as deals progress through stages.",
                route="/deals", status="pending",
                metric_label="Pipeline value", metric_value=f"${pipeline:,.0f}",
            ),
            ExportGrowthStoryStep(
                order=9, id="growth_updated", title="Growth Center Updated",
                description="Executive dashboard reflects new pipeline and market activity.",
                route="/growth-center", status="pending",
            ),
            ExportGrowthStoryStep(
                order=10, id="roi_improved", title="ROI Improves",
                description="Customer Success Center shows measurable export growth impact.",
                route="/customer-success/roi", status="pending",
                metric_label="ROI improvement", metric_value="+32%",
            ),
        ]
        return ExportGrowthStoryResponse(
            subtitle="From product photo to export revenue — the complete growth loop",
            steps=steps,
            total_pipeline_usd=float(pipeline),
            roi_improvement_pct=32.0,
        )

    @staticmethod
    async def get_value_demo(db: AsyncSession, tenant_id: UUID) -> ValueDemoResponse:
        metrics = await CommercialDemoService._aggregate_metrics(db, tenant_id)
        tenant = await TenantService.get_tenant(db, tenant_id)
        demo_loaded = metrics.get("demo_records", 0) > 0

        actions: list[ValueDemoAction] = []
        if metrics.get("communications_unanswered", 0) > 0:
            actions.append(ValueDemoAction(
                id="reply_messages", title="Reply to buyer messages",
                description=f"{metrics['communications_unanswered']} unanswered buyer inquiries waiting.",
                route="/communications/inbox", priority="high",
            ))
        if metrics.get("proposals_draft", 0) > 0:
            actions.append(ValueDemoAction(
                id="send_proposals", title="Send pending proposals",
                description="Finalize and send draft proposals to close deals faster.",
                route="/proposals", priority="high",
            ))
        actions.append(ValueDemoAction(
            id="review_pipeline", title="Review deal pipeline",
            description="Check active deals and update stages for accurate forecasting.",
            route="/deals", priority="medium",
        ))
        actions.append(ValueDemoAction(
            id="generate_content", title="Generate new content",
            description="Upload latest product photos and create export marketing content.",
            route="/content-factory", priority="medium",
        ))
        if not demo_loaded:
            actions.insert(0, ValueDemoAction(
                id="load_demo", title="Load demo factory data",
                description="Generate a complete demo environment to explore platform value.",
                route="/demo-tour", priority="high",
            ))

        return ValueDemoResponse(
            buyers_found=metrics.get("buyers_found", 0),
            opportunities_generated=metrics.get("leads_count", 0) + metrics.get("active_deals", 0),
            pipeline_value_usd=metrics.get("pipeline_value_usd", 0),
            estimated_revenue_influenced_usd=metrics.get("pipeline_value_usd", 0) * 0.35,
            active_deals=metrics.get("active_deals", 0),
            proposals_sent=metrics.get("proposals_sent", 0),
            communications_active=metrics.get("communications_active", 0),
            content_pieces=metrics.get("content_pieces", 0),
            ai_recommendations=max(3, metrics.get("leads_count", 0)),
            actions_today=actions[:5],
            demo_data_loaded=demo_loaded,
            company_name=tenant.company_name,
        )

    @staticmethod
    async def get_executive_demo(db: AsyncSession, tenant_id: UUID) -> ExecutiveDemoResponse:
        metrics = await CommercialDemoService._aggregate_metrics(db, tenant_id)
        tenant = await TenantService.get_tenant(db, tenant_id)

        profile_industry = None
        profile_country = None
        profile_r = await db.execute(
            select(FactoryPlatformProfile).where(FactoryPlatformProfile.tenant_id == tenant_id),
        )
        profile = profile_r.scalar_one_or_none()
        if profile:
            profile_industry = profile.industry
            profile_country = profile.country

        buyers = metrics.get("buyers_found", 0)
        pipeline = metrics.get("pipeline_value_usd", 0)
        deals = metrics.get("active_deals", 0)
        proposals = metrics.get("proposals_sent", 0)
        comms = metrics.get("communications_active", 0)

        kpis = [
            ExecutiveDemoKpi(label="Buyers in Network", value=str(buyers), change="+12 this month", trend="up"),
            ExecutiveDemoKpi(label="Pipeline Value", value=f"${pipeline:,.0f}", change="+18% vs last month", trend="up"),
            ExecutiveDemoKpi(label="Active Deals", value=str(deals), change=f"{proposals} proposals sent", trend="up"),
            ExecutiveDemoKpi(label="Buyer Conversations", value=str(comms), change="2 awaiting reply", trend="neutral"),
            ExecutiveDemoKpi(label="Content Published", value=str(metrics.get("content_pieces", 0)), change="AI-generated", trend="up"),
            ExecutiveDemoKpi(label="Export Markets", value=str(metrics.get("buyer_countries", 3)), change="Expanding", trend="up"),
        ]

        sections = [
            ExecutiveDemoSection(
                id="buyer_growth", title="Buyer Growth",
                summary=f"{buyers} qualified buyers discovered across {metrics.get('buyer_countries', 3)} markets.",
                route="/buyer-network",
                highlights=["AI-powered buyer matching", "Relationship intelligence", "Market expansion tracking"],
            ),
            ExecutiveDemoSection(
                id="pipeline", title="Pipeline Growth",
                summary=f"${pipeline:,.0f} in active pipeline across {deals} deals.",
                route="/deals",
                highlights=["Stage-based tracking", "Probability forecasting", "Deal risk alerts"],
            ),
            ExecutiveDemoSection(
                id="proposals", title="Proposal Activity",
                summary=f"{proposals} proposals sent to international buyers.",
                route="/proposals",
                highlights=["Professional export proposals", "Multi-currency support", "Document tracking"],
            ),
            ExecutiveDemoSection(
                id="communications", title="Communication Activity",
                summary=f"{comms} active buyer conversations managed centrally.",
                route="/communications",
                highlights=["Multi-channel inbox", "Follow-up automation", "Response time tracking"],
            ),
        ]

        recommendations = [
            "Reply to 2 unanswered buyer inquiries to maintain response rate above 90%.",
            "Send updated catalog to qualified leads in UAE and Brazil markets.",
            "Generate AI content for 3 new product lines to expand buyer discovery.",
            "Review negotiation-stage deals — 2 deals worth $215K need follow-up this week.",
        ]

        roi_score = _clamp(
            min(95, 40 + buyers * 5 + deals * 8 + proposals * 6 + (10 if comms > 0 else 0)),
        )

        return ExecutiveDemoResponse(
            company_name=tenant.company_name,
            industry=profile_industry,
            country=profile_country,
            headline=f"{tenant.company_name} — Export Growth Overview",
            kpis=kpis,
            sections=sections,
            ai_recommendations=recommendations,
            roi_score=roi_score,
            generated_at=_utcnow(),
        )

    @staticmethod
    def get_product_positioning() -> ProductPositioningResponse:
        return ProductPositioningResponse(
            mission=(
                "Help factory owners grow export revenue by connecting product content, "
                "buyer discovery, sales pipeline, and communication in one AI-powered platform."
            ),
            tagline="From factory floor to global buyers — powered by AI.",
            differentiators=[
                "Built specifically for factory export growth, not generic CRM",
                "AI content generation from factory photos via Telegram",
                "Buyer discovery engine matched to your products and markets",
                "Unified communication hub for all buyer channels",
                "Executive dashboards showing real export ROI",
            ],
            comparisons=[
                PositioningComparison(
                    category="Traditional CRM",
                    traditional="Generic contact management, no buyer discovery or content tools",
                    this_platform="Export-focused CRM with buyer matching, proposals, and pipeline built in",
                ),
                PositioningComparison(
                    category="Social Media Tools",
                    traditional="Post scheduling only, no buyer connection or deal tracking",
                    this_platform="Content creation + buyer discovery + deal pipeline in one flow",
                ),
                PositioningComparison(
                    category="Marketing Platforms",
                    traditional="Broad marketing automation, not factory-specific",
                    this_platform="Factory-first: product content → buyer match → deal close",
                ),
                PositioningComparison(
                    category="Export Agencies",
                    traditional="High cost, limited transparency, dependency on agents",
                    this_platform="Self-service platform — you own the buyer relationships and data",
                ),
            ],
            key_capabilities=[
                "Buyer discovery from product content",
                "AI multilingual content generation",
                "Export CRM with proposals and deal rooms",
                "Multi-channel communication management",
                "Growth Center with pipeline analytics",
                "ROI tracking and business impact reports",
            ],
        )

    @staticmethod
    async def get_readiness_score(db: AsyncSession, tenant_id: UUID) -> DemoReadinessResponse:
        metrics = await CommercialDemoService._aggregate_metrics(db, tenant_id)

        has_buyers = metrics.get("buyers_found", 0) >= 3
        has_leads = metrics.get("leads_count", 0) >= 2
        has_deals = metrics.get("active_deals", 0) >= 1
        has_proposals = metrics.get("proposals_sent", 0) >= 1
        has_comms = metrics.get("communications_active", 0) >= 1
        has_content = metrics.get("content_pieces", 0) >= 1
        has_pipeline = metrics.get("pipeline_value_usd", 0) > 0

        profile_score = 0
        profile_r = await db.execute(
            select(FactoryPlatformProfile).where(FactoryPlatformProfile.tenant_id == tenant_id),
        )
        profile = profile_r.scalar_one_or_none()
        if profile and profile.company_description:
            profile_score = 80
        elif profile:
            profile_score = 40

        components = [
            ReadinessComponent(
                key="demo_data", label="Demo Data Quality", score=_clamp(
                    (20 if has_buyers else 0) + (15 if has_leads else 0) + (15 if has_deals else 0)
                    + (10 if has_proposals else 0) + (10 if has_comms else 0) + (10 if has_content else 0)
                    + (20 if has_pipeline else 0),
                ), weight=0.25, status="ready" if has_buyers and has_deals else "partial" if has_buyers else "missing",
                notes="Buyers, leads, deals, and communications seeded",
            ),
            ReadinessComponent(
                key="factory_profile", label="Factory Profile", score=profile_score,
                weight=0.15, status="ready" if profile_score >= 70 else "partial" if profile_score > 0 else "missing",
            ),
            ReadinessComponent(
                key="user_experience", label="User Experience", score=85,
                weight=0.20, status="ready",
                notes="Demo tour, value demo, and executive demo routes available",
            ),
            ReadinessComponent(
                key="executive_visibility", label="Executive Value Visibility", score=_clamp(
                    30 + (20 if has_pipeline else 0) + (15 if has_deals else 0) + (15 if has_proposals else 0) + 20,
                ), weight=0.20, status="ready" if has_pipeline else "partial",
            ),
            ReadinessComponent(
                key="sales_readiness", label="Sales Readiness", score=82,
                weight=0.20, status="ready",
                notes="Product positioning, demo tour, and demo mode toggle implemented",
            ),
        ]

        total = sum(c.score * c.weight for c in components)
        score = _clamp(int(total))

        strengths = []
        gaps = []
        if has_buyers:
            strengths.append(f"{metrics['buyers_found']} demo buyers across multiple markets")
        else:
            gaps.append("Load a demo factory package to populate buyer data")
        if has_pipeline:
            strengths.append(f"${metrics['pipeline_value_usd']:,.0f} pipeline value for executive demos")
        else:
            gaps.append("No pipeline value — load demo data before sales presentations")
        if has_content:
            strengths.append("AI content samples ready for Content Factory demo")
        else:
            gaps.append("No content samples — upload or load demo content")
        strengths.extend([
            "Interactive demo tour with 8 guided steps",
            "Executive demo page suitable for factory owner presentations",
            "Product positioning content explaining platform differentiation",
        ])

        next_steps = []
        if not has_buyers:
            next_steps.append("Load Haocheng Industry Group demo package from Demo Tour")
        if not has_content:
            next_steps.append("Generate demo content via Content Factory")
        next_steps.extend([
            "Practice 10-minute demo flow: Profile → Content → Buyers → CRM → ROI",
            "Enable Demo Mode during sales presentations",
            "Review executive demo page before first factory owner meeting",
        ])

        return DemoReadinessResponse(
            score=score,
            grade=_grade(score),  # type: ignore[arg-type]
            components=components,
            strengths=strengths,
            gaps=gaps,
            recommended_next_steps=next_steps[:5],
        )

    @staticmethod
    async def _aggregate_metrics(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        buyers_found = int(await db.scalar(
            select(func.count()).select_from(Buyer).where(Buyer.tenant_id == tenant_id),
        ) or 0)

        demo_records = int(await db.scalar(
            select(func.count()).select_from(Buyer).where(
                Buyer.tenant_id == tenant_id,
                Buyer.notes.contains(MARKER),
            ),
        ) or 0)

        leads_count = int(await db.scalar(
            select(func.count()).select_from(SalesLead).where(SalesLead.tenant_id == tenant_id),
        ) or 0)

        active_deals = int(await db.scalar(
            select(func.count()).select_from(SalesDeal).where(
                SalesDeal.tenant_id == tenant_id,
                SalesDeal.stage.notin_(["won", "lost", "closed"]),
            ),
        ) or 0)

        pipeline_value = await db.scalar(
            select(func.coalesce(func.sum(SalesDeal.value), 0)).where(
                SalesDeal.tenant_id == tenant_id,
                SalesDeal.stage.notin_(["won", "lost", "closed"]),
            ),
        )
        pipeline_value_usd = float(pipeline_value or 0)

        proposals_sent = int(await db.scalar(
            select(func.count()).select_from(SalesProposal).where(
                SalesProposal.tenant_id == tenant_id,
                SalesProposal.status.in_(["sent", "accepted", "viewed"]),
            ),
        ) or 0)

        proposals_draft = int(await db.scalar(
            select(func.count()).select_from(SalesProposal).where(
                SalesProposal.tenant_id == tenant_id,
                SalesProposal.status == "draft",
            ),
        ) or 0)

        communications_active = int(await db.scalar(
            select(func.count()).select_from(CommunicationThread).where(
                CommunicationThread.tenant_id == tenant_id,
                CommunicationThread.status == "open",
            ),
        ) or 0)

        communications_unanswered = int(await db.scalar(
            select(func.count()).select_from(CommunicationMessage)
            .join(CommunicationThread, CommunicationMessage.thread_id == CommunicationThread.id)
            .where(
                CommunicationThread.tenant_id == tenant_id,
                CommunicationMessage.status == "unanswered",
            ),
        ) or 0)

        content_pieces = 0
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        if client_ids:
            content_pieces = int(await db.scalar(
                select(func.count()).select_from(ContentItem).where(
                    ContentItem.client_id.in_(client_ids),
                ),
            ) or 0)

        countries_r = await db.execute(
            select(Buyer.country).where(
                Buyer.tenant_id == tenant_id, Buyer.country.isnot(None),
            ).distinct(),
        )
        buyer_countries = len([c for c in countries_r.scalars().all() if c])

        return {
            "buyers_found": buyers_found,
            "demo_records": demo_records,
            "leads_count": leads_count,
            "active_deals": active_deals,
            "pipeline_value_usd": pipeline_value_usd,
            "proposals_sent": proposals_sent,
            "proposals_draft": proposals_draft,
            "communications_active": communications_active,
            "communications_unanswered": communications_unanswered,
            "content_pieces": content_pieces,
            "buyer_countries": buyer_countries,
        }
