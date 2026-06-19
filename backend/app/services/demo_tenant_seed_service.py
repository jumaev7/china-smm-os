"""Seed minimal tenant-scoped demo data for the factory demo account."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.content import ContentItem
from app.models.content_factory import ContentFactory, ContentFactoryItem
from app.models.crm_lead import CrmLead
from app.models.tenant import Tenant
from app.services.tenant_auth_service import DEMO_TENANT_NAME, DEMO_USER_EMAIL

logger = logging.getLogger(__name__)
MARKER = "[DEMO_TENANT_SEED]"


async def ensure_demo_tenant_data(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    """Idempotent — ensures demo tenant has a client and minimal product-page data."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        return {}

    try:
        client = await _ensure_demo_client(db, tenant)
        content_count = await _seed_content(db, client.id)
        crm_count = await _seed_crm_leads(db, client.id)
        factory_count = await _seed_content_factory(db, client.id)
        counts = {
            "clients": 1,
            "content": content_count,
            "crm_leads": crm_count,
            "content_factory_items": factory_count,
        }
        await db.commit()
        logger.info("%s tenant=%s counts=%s", MARKER, tenant_id, counts)
        return counts
    except Exception:
        await db.rollback()
        logger.exception("%s failed for tenant=%s", MARKER, tenant_id)
        return {}


async def _ensure_demo_client(db: AsyncSession, tenant: Tenant) -> Client:
    result = await db.execute(
        select(Client)
        .where(Client.tenant_id == tenant.id)
        .order_by(Client.created_at.asc())
        .limit(1),
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    client = Client(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        company_name=tenant.company_name or DEMO_TENANT_NAME,
        source_language="zh",
        business_category="manufacturing",
        content_style="professional",
        status="active",
        brand_name=tenant.company_name or DEMO_TENANT_NAME,
        business_description="Demo factory profile for tenant product pages.",
        notes=f"{MARKER} Auto-seeded for {DEMO_USER_EMAIL}",
    )
    db.add(client)
    await db.flush()
    return client


async def _seed_content(db: AsyncSession, client_id: uuid.UUID) -> int:
    count = int(
        (await db.execute(
            select(func.count()).select_from(ContentItem).where(ContentItem.client_id == client_id),
        )).scalar() or 0,
    )
    if count >= 3:
        return count

    now = datetime.now(timezone.utc)
    samples = [
        ("Ceramic tile showcase", "ready", "Product launch post for export buyers."),
        ("Factory tour highlights", "draft", "Behind-the-scenes manufacturing content."),
        ("Quality certification", "approved", "ISO and export compliance messaging."),
    ]
    for title, status, notes in samples:
        db.add(ContentItem(
            id=uuid.uuid4(),
            client_id=client_id,
            platforms=["instagram", "telegram"],
            status=status,
            source="manual",
            caption_short_en=title,
            internal_notes=f"{MARKER} {notes}",
            created_at=now,
            updated_at=now,
        ))
    await db.flush()
    return count + len(samples)


async def _seed_crm_leads(db: AsyncSession, client_id: uuid.UUID) -> int:
    count = int(
        (await db.execute(
            select(func.count()).select_from(CrmLead).where(CrmLead.client_id == client_id),
        )).scalar() or 0,
    )
    if count >= 3:
        return count

    now = datetime.now(timezone.utc)
    rows = [
        ("Almaty Trading LLC", "Dmitry Petrov", "qualified", "high"),
        ("Tashkent Import Co", "Sardor Karimov", "contacted", "medium"),
        ("Dubai Build Materials", "Omar Hassan", "new", "high"),
    ]
    for company, name, status, priority in rows:
        db.add(CrmLead(
            id=uuid.uuid4(),
            client_id=client_id,
            name=name,
            company=company,
            source="referral",
            language="ru",
            status=status,
            priority=priority,
            interest="Import of factory products",
            estimated_value=Decimal("25000"),
            next_follow_up_at=now + timedelta(days=3),
            notes=MARKER,
        ))
    await db.flush()
    return count + len(rows)


async def _seed_content_factory(db: AsyncSession, client_id: uuid.UUID) -> int:
    existing_items = int(
        (await db.execute(
            select(func.count())
            .select_from(ContentFactoryItem)
            .join(ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id)
            .where(ContentFactory.client_id == client_id),
        )).scalar() or 0,
    )
    if existing_items >= 2:
        return existing_items

    content_row = (
        await db.execute(
            select(ContentItem.id)
            .where(ContentItem.client_id == client_id)
            .order_by(ContentItem.created_at.asc())
            .limit(1),
        )
    ).scalar_one_or_none()

    factory = ContentFactory(
        id=uuid.uuid4(),
        client_id=client_id,
        source_content_id=content_row,
        status="generated",
        input_type="text",
        input_text="Export growth product content for Central Asia buyers.",
        content_category="product",
        target_languages_json=json.dumps(["ru", "en"]),
    )
    db.add(factory)
    await db.flush()

    now = datetime.now(timezone.utc)
    for title, review_status in (
        ("Export catalog carousel", "generated"),
        ("Buyer outreach post", "approved"),
    ):
        db.add(ContentFactoryItem(
            id=uuid.uuid4(),
            factory_id=factory.id,
            content_type="post",
            theme="export",
            angle="buyer acquisition",
            title=title,
            platforms_json=json.dumps(["instagram", "telegram"]),
            preview_caption=f"{title} — demo content for tenant dashboard.",
            review_status=review_status,
            headline=title,
            quality_scores_json=json.dumps({"overall_score": 78}),
            created_at=now,
        ))
    await db.flush()
    return existing_items + 2
