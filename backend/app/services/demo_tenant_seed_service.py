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
from app.models.media import MediaFile
from app.models.product import Product
from app.models.tenant import Tenant, TenantUser
from app.services.content_review_service import CLIENT_REVIEW_APPROVED
from app.services.tenant_auth_service import DEMO_TENANT_NAME, DEMO_USER_EMAIL

logger = logging.getLogger(__name__)
MARKER = "[DEMO_TENANT_SEED]"
PUBLISH_VERIFY_READY_MARKER = "[PUBLISH_VERIFY_READY]"
PUBLISH_VERIFY_BLOCKED_MARKER = "[PUBLISH_VERIFY_BLOCKED]"
PUBLISH_VERIFY_READY_CONTENT_ID = uuid.UUID("b0c0d001-0001-4000-8000-000000000101")
PUBLISH_VERIFY_READY_MEDIA_ID = uuid.UUID("b0c0d001-0001-4000-8000-000000000102")
PUBLISH_VERIFY_BLOCKED_CONTENT_ID = uuid.UUID("b0c0d001-0001-4000-8000-000000000103")
_PUBLISH_VERIFY_READY_AT = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
_PUBLISH_VERIFY_MOCK_PLATFORMS = ("instagram", "telegram")


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
        product_count = await _seed_products(db, client.id)
        publish_ready = await ensure_publish_verify_ready_content(db, client.id)
        counts = {
            "clients": 1,
            "content": content_count,
            "crm_leads": crm_count,
            "content_factory_items": factory_count,
            "products": product_count,
            "publish_verify_ready": 1 if publish_ready else 0,
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


async def ensure_publish_verify_ready_content(db: AsyncSession, client_id: uuid.UUID) -> bool:
    """Idempotent publish-ready fixture for mock publish verification."""
    media = await db.get(MediaFile, PUBLISH_VERIFY_READY_MEDIA_ID)
    if not media:
        media = MediaFile(
            id=PUBLISH_VERIFY_READY_MEDIA_ID,
            client_id=client_id,
            original_filename="publish-verify-ready.jpg",
            file_type="image",
            mime_type="image/jpeg",
            storage_path="demo/publish-verify-ready.jpg",
            file_size=512,
            uploaded_at=_PUBLISH_VERIFY_READY_AT,
        )
        db.add(media)
    else:
        media.client_id = client_id

    item = await db.get(ContentItem, PUBLISH_VERIFY_READY_CONTENT_ID)
    if not item:
        item = ContentItem(
            id=PUBLISH_VERIFY_READY_CONTENT_ID,
            client_id=client_id,
            media_file_id=PUBLISH_VERIFY_READY_MEDIA_ID,
            platforms=["instagram", "telegram"],
            status="approved",
            source="manual",
            context_ai_override="product",
            caption_short_en="Export-quality ceramic tiles — demo publish verify.",
            caption_long_en=(
                "Premium glazed ceramic tiles for wholesale distributors. "
                "Deterministic publish-verify fixture."
            ),
            hashtags="#export #ceramics #factory",
            internal_notes=f"{PUBLISH_VERIFY_READY_MARKER} Deterministic mock publish fixture.",
            approved_at=_PUBLISH_VERIFY_READY_AT,
            client_review_status=CLIENT_REVIEW_APPROVED,
            client_approved_at=_PUBLISH_VERIFY_READY_AT,
            scheduled_for=_PUBLISH_VERIFY_READY_AT,
            created_at=_PUBLISH_VERIFY_READY_AT,
            updated_at=_PUBLISH_VERIFY_READY_AT,
        )
        db.add(item)
    else:
        item.client_id = client_id
        item.media_file_id = PUBLISH_VERIFY_READY_MEDIA_ID
        item.platforms = ["instagram", "telegram"]
        item.status = "approved"
        item.context_ai_override = "product"
        item.caption_short_en = "Export-quality ceramic tiles — demo publish verify."
        item.caption_long_en = (
            "Premium glazed ceramic tiles for wholesale distributors. "
            "Deterministic publish-verify fixture."
        )
        item.hashtags = "#export #ceramics #factory"
        if PUBLISH_VERIFY_READY_MARKER not in (item.internal_notes or ""):
            notes = item.internal_notes or ""
            item.internal_notes = f"{notes}\n{PUBLISH_VERIFY_READY_MARKER}".strip()
        item.approved_at = _PUBLISH_VERIFY_READY_AT
        item.client_review_status = CLIENT_REVIEW_APPROVED
        item.client_approved_at = _PUBLISH_VERIFY_READY_AT
        item.scheduled_for = _PUBLISH_VERIFY_READY_AT
        item.updated_at = _PUBLISH_VERIFY_READY_AT

    await db.flush()
    logger.info(
        "%s publish-verify-ready content=%s media=%s client=%s",
        PUBLISH_VERIFY_READY_MARKER,
        PUBLISH_VERIFY_READY_CONTENT_ID,
        PUBLISH_VERIFY_READY_MEDIA_ID,
        client_id,
    )
    return True


async def ensure_publish_verify_mock_accounts(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Idempotent mock IG/Telegram accounts required by publishing truth verification."""
    from app.models.publishing_account import PublishingAccount
    from app.schemas.publishing import MOCK_ACCOUNT_LABELS

    created = 0
    for platform in _PUBLISH_VERIFY_MOCK_PLATFORMS:
        existing = (
            await db.execute(
                select(PublishingAccount).where(
                    PublishingAccount.tenant_id == tenant_id,
                    PublishingAccount.platform == platform,
                    PublishingAccount.status == "mock",
                ).limit(1),
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(
            PublishingAccount(
                tenant_id=tenant_id,
                platform=platform,
                account_name=MOCK_ACCOUNT_LABELS.get(platform, f"{platform.title()} Mock"),
                account_id=f"mock-{platform}-publish-verify",
                status="mock",
            ),
        )
        created += 1
    if created:
        await db.flush()
    return created


async def ensure_publish_verify_blocked_content(db: AsyncSession, client_id: uuid.UUID) -> bool:
    """Deterministic draft/no-media item for blocked-path publish verification."""
    existing = await db.get(ContentItem, PUBLISH_VERIFY_BLOCKED_CONTENT_ID)
    if existing is not None:
        existing.status = "draft"
        existing.media_file_id = None
        existing.caption_short_en = None
        existing.caption_short_ru = None
        existing.caption_short_uz = None
        existing.caption_long_en = None
        existing.caption_long_ru = None
        existing.caption_long_uz = None
        existing.internal_notes = f"{PUBLISH_VERIFY_BLOCKED_MARKER} Draft without media/caption."
        await db.flush()
        return True

    db.add(
        ContentItem(
            id=PUBLISH_VERIFY_BLOCKED_CONTENT_ID,
            client_id=client_id,
            platforms=["instagram", "telegram"],
            status="draft",
            source="manual",
            media_file_id=None,
            internal_notes=f"{PUBLISH_VERIFY_BLOCKED_MARKER} Draft without media/caption.",
            created_at=_PUBLISH_VERIFY_READY_AT,
            updated_at=_PUBLISH_VERIFY_READY_AT,
        ),
    )
    await db.flush()
    return True


async def ensure_publish_verify_ready_for_demo_user(db: AsyncSession) -> dict | None:
    """Resolve demo tenant client and ensure publish-verify fixtures exist."""
    row = (
        await db.execute(
            select(TenantUser.tenant_id)
            .where(TenantUser.email == DEMO_USER_EMAIL)
            .limit(1),
        )
    ).scalar_one_or_none()
    if not row:
        return None
    tenant = await db.get(Tenant, row)
    if not tenant:
        return None
    client = await _ensure_demo_client(db, tenant)
    await ensure_publish_verify_ready_content(db, client.id)
    await ensure_publish_verify_blocked_content(db, client.id)
    mock_created = await ensure_publish_verify_mock_accounts(db, tenant.id)
    await db.commit()
    return {
        "tenant_id": str(tenant.id),
        "client_id": str(client.id),
        "content_id": str(PUBLISH_VERIFY_READY_CONTENT_ID),
        "media_id": str(PUBLISH_VERIFY_READY_MEDIA_ID),
        "blocked_content_id": str(PUBLISH_VERIFY_BLOCKED_CONTENT_ID),
        "mock_accounts_created": mock_created,
    }


async def _seed_products(db: AsyncSession, client_id: uuid.UUID) -> int:
    count = int(
        (await db.execute(
            select(func.count()).select_from(Product).where(Product.client_id == client_id),
        )).scalar() or 0,
    )
    if count >= 2:
        return count

    samples = [
        (
            "Smart CNC Precision Lathe XL-500",
            "CNC Machinery",
            "High-precision CNC lathe for export markets — MOQ 5 units.",
            Decimal("28500"),
        ),
        (
            "Industrial Ceramic Tile Series A",
            "Building Materials",
            "Premium glazed ceramic tiles for wholesale distributors.",
            Decimal("12.50"),
        ),
    ]
    for name, category, description, unit_price in samples:
        db.add(Product(
            id=uuid.uuid4(),
            client_id=client_id,
            name=name,
            category=category,
            description=f"{MARKER} {description}",
            unit_price=unit_price,
            currency="USD",
            moq=5,
            active=True,
        ))
    await db.flush()
    return count + len(samples)
