"""System health monitoring and demo data seed/reset."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_state import uptime_seconds
from app.core.config import settings
from app.core.database import pool_status
from app.models.client import Client
from app.models.content import ContentItem
from app.models.crm_deal import CrmDeal, CrmDealEvent
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.operator_task import OperatorTask
from app.models.partner import Partner, ReferralLink
from app.models.revenue_event import RevenueEvent
from app.models.sales_agent_recommendation import SalesAgentRecommendation
from app.services.scheduled_publish_service import ScheduledPublishService

logger = logging.getLogger(__name__)

DEMO_NOTES_MARKER = "[SYSTEM_DEMO_V1]"
DEMO_CLIENT_NAME = "Chinese Factory (Demo)"
DEMO_PARTNER_NAME = "Demo Referral Partner (Demo)"
DEMO_REFERRAL_CODE = "demo-ref-uz"

_LEAD_STATUSES = (
    "new", "contacted", "qualified", "proposal_sent", "negotiation", "won", "lost",
)
_DEAL_STATUSES = (
    "new", "proposal", "contract", "invoice", "waiting_payment", "won", "lost",
)


class SystemHealthService:
    @staticmethod
    async def health(db: AsyncSession) -> dict[str, Any]:
        stats = await SystemHealthService._platform_stats(db)
        db_status = await SystemHealthService._check_database(db)
        scheduler = SystemHealthService._scheduler_status()
        ai_status = SystemHealthService._ai_status()
        telegram = SystemHealthService._telegram_status()

        pool = pool_status()
        component_ok = db_status == "ok"
        pool_pressure = int(pool["checked_out"]) >= int(pool["pool_size"]) + int(pool["max_overflow"]) - 2
        overall = "degraded" if pool_pressure else ("ok" if component_ok else "degraded")

        return {
            "status": overall,
            "uptime": int(uptime_seconds()),
            "database": db_status,
            "db_pool": pool,
            "scheduler": scheduler,
            "ai_services": ai_status,
            "telegram_bot": telegram,
            "demo_mode": settings.DEMO_MODE,
            "total_clients": stats["total_clients"],
            "total_leads": stats["total_leads"],
            "total_deals": stats["total_deals"],
            "total_content": stats["total_content"],
            "total_posts": stats["total_posts"],
            "total_revenue": stats["total_revenue"],
            "total_commissions": stats["total_commissions"],
        }

    @staticmethod
    async def demo_seed(db: AsyncSession) -> dict[str, Any]:
        existing = await db.execute(
            select(Client.id).where(Client.notes.contains(DEMO_NOTES_MARKER))
        )
        if existing.scalar_one_or_none():
            return {
                "created": False,
                "message": "Demo data already exists — reset first or skip",
            }

        demo_notes = f"{DEMO_NOTES_MARKER} Auto-generated demo client. Safe to reset."

        client = Client(
            company_name=DEMO_CLIENT_NAME,
            source_language="zh",
            business_category="technology",
            content_style="professional",
            status="active",
            notes=demo_notes,
            brand_name="Chinese Factory Uzbekistan",
            business_description="Demo manufacturing client for SMM showcase.",
            plan_name="Growth",
            monthly_fee=Decimal("800"),
            monthly_post_limit=30,
            billing_status="active",
        )
        db.add(client)
        await db.flush()

        partner = Partner(
            name=DEMO_PARTNER_NAME,
            company="Demo Partners LLC",
            status="active",
            notes=f"{DEMO_NOTES_MARKER} Demo referral partner.",
        )
        db.add(partner)
        await db.flush()
        db.add(ReferralLink(
            partner_id=partner.id,
            code=DEMO_REFERRAL_CODE,
            description="Demo referral link",
        ))

        leads: list[CrmLead] = []
        for i in range(20):
            status = _LEAD_STATUSES[i % len(_LEAD_STATUSES)]
            leads.append(CrmLead(
                client_id=client.id,
                name=f"Demo Lead {i + 1}",
                company=f"Demo Buyer {i + 1}",
                source="referral" if i % 4 == 0 else "instagram",
                language="ru" if i % 2 == 0 else "uz",
                status=status,
                priority="high" if i < 4 else "medium",
                estimated_value=Decimal(str(2_000_000 + i * 150_000)),
                attribution_source="referral" if i % 4 == 0 else "instagram",
                partner_id=partner.id if i % 4 == 0 else None,
                referral_code=DEMO_REFERRAL_CODE if i % 4 == 0 else None,
                notes=demo_notes,
            ))
        db.add_all(leads)
        await db.flush()

        deals: list[CrmDeal] = []
        for i in range(10):
            lead = leads[i]
            if i < 5:
                deal_status = "won"
                amount = Decimal(str(5_000_000 + i * 500_000))
                comm_pct = Decimal("15")
                comm_amt = (amount * comm_pct / Decimal("100")).quantize(Decimal("0.01"))
                deal = CrmDeal(
                    client_id=client.id,
                    lead_id=lead.id,
                    title=f"Demo Won Deal {i + 1}",
                    status=deal_status,
                    expected_value=amount,
                    deal_amount=amount,
                    currency="UZS",
                    commission_percent=comm_pct,
                    commission_amount=comm_amt,
                    commission_status="pending" if i % 2 == 0 else "approved",
                    probability=100,
                )
                lead.status = "won"
            elif i < 8:
                deal = CrmDeal(
                    client_id=client.id,
                    lead_id=lead.id,
                    title=f"Demo Pipeline Deal {i + 1}",
                    status=_DEAL_STATUSES[(i % 4) + 1],
                    expected_value=Decimal(str(3_000_000 + i * 200_000)),
                    probability=40 + i * 5,
                )
            else:
                deal = CrmDeal(
                    client_id=client.id,
                    lead_id=lead.id,
                    title=f"Demo Lost Deal {i + 1}",
                    status="lost",
                    expected_value=Decimal("1000000"),
                    probability=0,
                )
                lead.status = "lost"
            deals.append(deal)
        db.add_all(deals)
        await db.flush()

        for deal in deals[:5]:
            db.add(RevenueEvent(deal_id=deal.id, type="won", amount=deal.deal_amount))
            db.add(CrmDealEvent(
                deal_id=deal.id,
                event_type="status_change",
                title=f"Demo won — {deal.deal_amount} UZS",
            ))

        content_items: list[ContentItem] = []
        statuses = ["draft", "ready", "scheduled", "published", "published"]
        for i, st in enumerate(statuses):
            content_items.append(ContentItem(
                client_id=client.id,
                platforms=["instagram", "telegram"],
                status=st,
                source="manual",
                caption_short_ru=f"Демо пост {i + 1} — Chinese Factory",
                caption_long_ru=f"Демо контент для презентации платформы. Пост #{i + 1}.",
            ))
        db.add_all(content_items)

        db.add(CrmActivity(
            lead_id=leads[0].id,
            type="note",
            content="Demo activity — initial outreach logged.",
        ))

        await db.commit()

        logger.info("[System] demo seed created: client=%s leads=20 deals=10", client.id)
        return {
            "created": True,
            "client_id": str(client.id),
            "partner_id": str(partner.id),
            "leads": 20,
            "deals": 10,
            "won_deals": 5,
            "content_items": len(content_items),
            "message": "Demo data seeded successfully",
        }

    @staticmethod
    async def demo_reset(db: AsyncSession) -> dict[str, Any]:
        demo_client_ids = await SystemHealthService._demo_client_ids(db)
        demo_partner_ids = await SystemHealthService._demo_partner_ids(db)

        if not demo_client_ids and not demo_partner_ids:
            return {"deleted": False, "message": "No demo-tagged data found"}

        counts: dict[str, int] = {}

        if demo_client_ids:
            deal_ids_q = select(CrmDeal.id).where(CrmDeal.client_id.in_(demo_client_ids))
            lead_ids_q = select(CrmLead.id).where(CrmLead.client_id.in_(demo_client_ids))

            for label, stmt in [
                ("recommendations", delete(SalesAgentRecommendation).where(
                    SalesAgentRecommendation.client_id.in_(demo_client_ids),
                )),
                ("tasks", delete(OperatorTask).where(
                    OperatorTask.client_id.in_(demo_client_ids),
                )),
                ("revenue_events", delete(RevenueEvent).where(
                    RevenueEvent.deal_id.in_(deal_ids_q),
                )),
                ("deal_events", delete(CrmDealEvent).where(
                    CrmDealEvent.deal_id.in_(deal_ids_q),
                )),
                ("deals", delete(CrmDeal).where(
                    CrmDeal.client_id.in_(demo_client_ids),
                )),
                ("activities", delete(CrmActivity).where(
                    CrmActivity.lead_id.in_(lead_ids_q),
                )),
                ("leads", delete(CrmLead).where(
                    CrmLead.client_id.in_(demo_client_ids),
                )),
                ("content", delete(ContentItem).where(
                    ContentItem.client_id.in_(demo_client_ids),
                )),
            ]:
                result = await db.execute(stmt)
                counts[label] = result.rowcount or 0

            result = await db.execute(
                delete(Client).where(Client.id.in_(demo_client_ids))
            )
            counts["clients"] = result.rowcount or 0

        if demo_partner_ids:
            orphan_leads = delete(CrmLead).where(CrmLead.partner_id.in_(demo_partner_ids))
            if demo_client_ids:
                orphan_leads = orphan_leads.where(~CrmLead.client_id.in_(demo_client_ids))
            await db.execute(orphan_leads)
            await db.execute(
                delete(ReferralLink).where(ReferralLink.partner_id.in_(demo_partner_ids))
            )
            result = await db.execute(
                delete(Partner).where(Partner.id.in_(demo_partner_ids))
            )
            counts["partners"] = result.rowcount or 0

        await db.commit()
        logger.info("[System] demo reset: %s", counts)
        return {"deleted": True, "counts": counts, "message": "Demo data removed"}

    @staticmethod
    async def _demo_client_ids(db: AsyncSession) -> list[UUID]:
        result = await db.execute(
            select(Client.id).where(Client.notes.contains(DEMO_NOTES_MARKER))
        )
        return list(result.scalars().all())

    @staticmethod
    async def _demo_partner_ids(db: AsyncSession) -> list[UUID]:
        result = await db.execute(
            select(Partner.id).where(Partner.notes.contains(DEMO_NOTES_MARKER))
        )
        return list(result.scalars().all())

    @staticmethod
    async def _platform_stats(db: AsyncSession) -> dict[str, Any]:
        total_clients = int(await db.scalar(select(func.count()).select_from(Client)) or 0)
        total_leads = int(await db.scalar(select(func.count()).select_from(CrmLead)) or 0)
        total_deals = int(await db.scalar(select(func.count()).select_from(CrmDeal)) or 0)
        total_content = int(await db.scalar(select(func.count()).select_from(ContentItem)) or 0)
        total_posts = int(await db.scalar(
            select(func.count()).select_from(ContentItem).where(ContentItem.status == "published")
        ) or 0)
        revenue_raw = await db.scalar(
            select(func.coalesce(func.sum(CrmDeal.deal_amount), 0))
            .select_from(CrmDeal)
            .where(CrmDeal.status == "won")
        )
        comm_raw = await db.scalar(
            select(func.coalesce(func.sum(CrmDeal.commission_amount), 0))
            .select_from(CrmDeal)
            .where(CrmDeal.status == "won")
        )
        return {
            "total_clients": total_clients,
            "total_leads": total_leads,
            "total_deals": total_deals,
            "total_content": total_content,
            "total_posts": total_posts,
            "total_revenue": Decimal(str(revenue_raw or 0)),
            "total_commissions": Decimal(str(comm_raw or 0)),
        }

    @staticmethod
    async def _check_database(db: AsyncSession) -> str:
        try:
            await db.execute(text("SELECT 1"))
            return "ok"
        except Exception as exc:
            logger.warning("[System] database check failed: %s", exc)
            return "error"

    @staticmethod
    def _scheduler_status() -> str:
        if not settings.SCHEDULED_PUBLISH_ENABLED:
            return "disabled"
        task = ScheduledPublishService._task
        if task and not task.done():
            return "running"
        return "stopped"

    @staticmethod
    def _ai_status() -> str:
        if settings.DEMO_MODE:
            return "demo"
        key = (settings.OPENAI_API_KEY or "").strip()
        if key.startswith("sk-"):
            return "ok"
        return "unconfigured"

    @staticmethod
    def _telegram_status() -> str:
        token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
        return "configured" if token else "unconfigured"
