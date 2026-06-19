"""Seed demo Business Matching opportunities for development."""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_matching import BusinessMatchingOpportunity
from app.models.buyer_crm import Buyer
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


async def seed_business_matching_demo(db: AsyncSession) -> None:
    existing = await db.execute(select(BusinessMatchingOpportunity).limit(1))
    if existing.scalar_one_or_none():
        return

    tenant_r = await db.execute(select(Tenant).limit(1))
    tenant = tenant_r.scalar_one_or_none()
    if not tenant:
        return

    buyers_r = await db.execute(
        select(Buyer).where(Buyer.tenant_id == tenant.id).limit(3),
    )
    buyers = list(buyers_r.scalars().all())
    if not buyers:
        logger.info("[Business Matching Seed] No buyers found — skipping")
        return

    demos = [
        {
            "title": "Uzbekistan textile import partnership",
            "opportunity_type": "import",
            "buyer": buyers[0],
            "score": 78,
            "confidence_score": 72,
            "estimated_value": Decimal("120000"),
            "status": "new",
            "match_reasoning": "Industry alignment with Central Asia textile demand",
        },
        {
            "title": "Kazakhstan distribution channel",
            "opportunity_type": "distribution",
            "buyer": buyers[1] if len(buyers) > 1 else buyers[0],
            "score": 65,
            "confidence_score": 60,
            "estimated_value": Decimal("85000"),
            "status": "contacted",
            "match_reasoning": "Export market fit for Kazakhstan distribution network",
        },
        {
            "title": "Government procurement — industrial equipment",
            "opportunity_type": "government",
            "buyer": buyers[2] if len(buyers) > 2 else buyers[0],
            "score": 55,
            "confidence_score": 48,
            "estimated_value": Decimal("250000"),
            "status": "qualified",
            "match_reasoning": "Government sector opportunity with certification requirements",
        },
    ]

    for d in demos:
        db.add(BusinessMatchingOpportunity(
            tenant_id=tenant.id,
            title=d["title"],
            opportunity_type=d["opportunity_type"],
            buyer_id=d["buyer"].id,
            score=d["score"],
            confidence_score=d["confidence_score"],
            estimated_value=d["estimated_value"],
            status=d["status"],
            match_reasoning=d["match_reasoning"],
            notes=f"Demo opportunity for {d['buyer'].company_name}",
        ))

    await db.commit()
    logger.info("[Business Matching Seed] Created %s demo opportunities", len(demos))
