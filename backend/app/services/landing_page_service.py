"""Landing page management and public lead capture."""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit
from app.models.attribution_link import AttributionLink
from app.models.campaign import Campaign
from app.models.client import Client
from app.models.communication import CommunicationContact
from app.models.landing_page import LandingLead, LandingPage
from app.models.product import Product
from app.schemas.crm import CrmLeadCreate
from app.schemas.landing_page import (
    LANDING_PAGE_STATUSES,
    LandingPageCreate,
    LandingPageUpdate,
    PublicLandingLeadSubmit,
)
from app.services.client_service import ClientService
from app.services.crm_service import CrmService

logger = logging.getLogger(__name__)

LINK_MARKER = "[Landing Page]"


def _public_url(slug: str) -> str:
    base = (settings.PUBLIC_APP_URL or "http://localhost:3000").rstrip("/")
    return f"{base}/l/{slug}"


def _normalize_slug(slug: str) -> str:
    s = slug.strip().lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if len(s) < 2:
        raise HTTPException(status_code=400, detail="Slug must be at least 2 characters")
    return s[:120]


async def _validate_refs(
    db: AsyncSession,
    *,
    client_id: UUID,
    campaign_id: UUID | None,
    product_id: UUID | None,
    attribution_link_id: UUID | None,
) -> None:
    if campaign_id:
        cr = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
        camp = cr.scalar_one_or_none()
        if not camp or camp.client_id != client_id:
            raise HTTPException(status_code=400, detail="Campaign not found for client")
    if product_id:
        pr = await db.execute(select(Product).where(Product.id == product_id))
        prod = pr.scalar_one_or_none()
        if not prod or prod.client_id != client_id:
            raise HTTPException(status_code=400, detail="Product not found for client")
    if attribution_link_id:
        ar = await db.execute(select(AttributionLink).where(AttributionLink.id == attribution_link_id))
        link = ar.scalar_one_or_none()
        if not link or link.client_id != client_id:
            raise HTTPException(status_code=400, detail="Attribution link not found for client")


async def _lead_counts(db: AsyncSession, page_ids: list[UUID]) -> dict[UUID, int]:
    if not page_ids:
        return {}
    rows = await db.execute(
        select(LandingLead.landing_page_id, func.count())
        .where(LandingLead.landing_page_id.in_(page_ids))
        .group_by(LandingLead.landing_page_id)
    )
    return {pid: int(cnt) for pid, cnt in rows.all()}


async def _serialize_page(
    db: AsyncSession,
    page: LandingPage,
    *,
    client_names: dict[UUID, str] | None = None,
    campaign_names: dict[UUID, str] | None = None,
    product_names: dict[UUID, str] | None = None,
    leads_counts: dict[UUID, int] | None = None,
) -> dict[str, Any]:
    if client_names is None:
        client_names = {}
    if campaign_names is None:
        campaign_names = {}
    if product_names is None:
        product_names = {}
    if leads_counts is None:
        leads_counts = await _lead_counts(db, [page.id])

    return {
        "id": page.id,
        "client_id": page.client_id,
        "campaign_id": page.campaign_id,
        "product_id": page.product_id,
        "attribution_link_id": page.attribution_link_id,
        "slug": page.slug,
        "title": page.title,
        "subtitle": page.subtitle,
        "description": page.description,
        "hero_image_url": page.hero_image_url,
        "cta_text": page.cta_text,
        "status": page.status,
        "public_url": _public_url(page.slug),
        "client_name": client_names.get(page.client_id),
        "campaign_name": campaign_names.get(page.campaign_id) if page.campaign_id else None,
        "product_name": product_names.get(page.product_id) if page.product_id else None,
        "leads_count": leads_counts.get(page.id, 0),
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }


async def _bulk_names(
    db: AsyncSession,
    pages: list[LandingPage],
) -> tuple[dict[UUID, str], dict[UUID, str], dict[UUID, str]]:
    client_ids = {p.client_id for p in pages}
    campaign_ids = {p.campaign_id for p in pages if p.campaign_id}
    product_ids = {p.product_id for p in pages if p.product_id}

    client_names: dict[UUID, str] = {}
    if client_ids:
        rows = await db.execute(select(Client.id, Client.company_name).where(Client.id.in_(client_ids)))
        client_names = {cid: name for cid, name in rows.all()}

    campaign_names: dict[UUID, str] = {}
    if campaign_ids:
        rows = await db.execute(select(Campaign.id, Campaign.name).where(Campaign.id.in_(campaign_ids)))
        campaign_names = {cid: name for cid, name in rows.all()}

    product_names: dict[UUID, str] = {}
    if product_ids:
        rows = await db.execute(select(Product.id, Product.name).where(Product.id.in_(product_ids)))
        product_names = {pid: name for pid, name in rows.all()}

    return client_names, campaign_names, product_names


class LandingPageService:
    @staticmethod
    async def create(db: AsyncSession, data: LandingPageCreate) -> dict[str, Any]:
        if data.status not in LANDING_PAGE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        await ClientService.get(db, data.client_id)
        await _validate_refs(
            db,
            client_id=data.client_id,
            campaign_id=data.campaign_id,
            product_id=data.product_id,
            attribution_link_id=data.attribution_link_id,
        )
        slug = _normalize_slug(data.slug)
        existing = await db.execute(select(LandingPage.id).where(LandingPage.slug == slug))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Slug already in use")

        page = LandingPage(
            client_id=data.client_id,
            campaign_id=data.campaign_id,
            product_id=data.product_id,
            attribution_link_id=data.attribution_link_id,
            slug=slug,
            title=data.title.strip(),
            subtitle=data.subtitle,
            description=data.description,
            hero_image_url=data.hero_image_url,
            cta_text=(data.cta_text or "Get in touch").strip(),
            status=data.status,
        )
        db.add(page)
        await db.commit()
        await db.refresh(page)
        logger.info("%s created: id=%s slug=%s status=%s", LINK_MARKER, page.id, slug, page.status)
        return await _serialize_page(db, page)

    @staticmethod
    async def list_pages(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(LandingPage).order_by(LandingPage.updated_at.desc())
        count_q = select(func.count()).select_from(LandingPage)
        if client_id:
            q = q.where(LandingPage.client_id == client_id)
            count_q = count_q.where(LandingPage.client_id == client_id)
        if status:
            q = q.where(LandingPage.status == status)
            count_q = count_q.where(LandingPage.status == status)

        total = (await db.execute(count_q)).scalar_one()
        result = await db.execute(q.offset(skip).limit(limit))
        pages = list(result.scalars().all())
        if not pages:
            return {"items": [], "total": total}

        client_names, campaign_names, product_names = await _bulk_names(db, pages)
        leads_counts = await _lead_counts(db, [p.id for p in pages])
        items = [
            await _serialize_page(
                db, p,
                client_names=client_names,
                campaign_names=campaign_names,
                product_names=product_names,
                leads_counts=leads_counts,
            )
            for p in pages
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def get_page(db: AsyncSession, page_id: UUID) -> dict[str, Any]:
        r = await db.execute(select(LandingPage).where(LandingPage.id == page_id))
        page = r.scalar_one_or_none()
        if not page:
            raise HTTPException(status_code=404, detail="Landing page not found")
        client_names, campaign_names, product_names = await _bulk_names(db, [page])
        return await _serialize_page(
            db, page,
            client_names=client_names,
            campaign_names=campaign_names,
            product_names=product_names,
        )

    @staticmethod
    async def update(db: AsyncSession, page_id: UUID, data: LandingPageUpdate) -> dict[str, Any]:
        r = await db.execute(select(LandingPage).where(LandingPage.id == page_id))
        page = r.scalar_one_or_none()
        if not page:
            raise HTTPException(status_code=404, detail="Landing page not found")

        payload = data.model_dump(exclude_unset=True)
        if "status" in payload and payload["status"] not in LANDING_PAGE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if "slug" in payload:
            payload["slug"] = _normalize_slug(payload["slug"])
            existing = await db.execute(
                select(LandingPage.id).where(
                    LandingPage.slug == payload["slug"],
                    LandingPage.id != page_id,
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Slug already in use")

        new_client_id = page.client_id
        new_campaign_id = payload.get("campaign_id", page.campaign_id)
        new_product_id = payload.get("product_id", page.product_id)
        new_link_id = payload.get("attribution_link_id", page.attribution_link_id)
        await _validate_refs(
            db,
            client_id=new_client_id,
            campaign_id=new_campaign_id,
            product_id=new_product_id,
            attribution_link_id=new_link_id,
        )

        for key, value in payload.items():
            if key == "title" and value is not None:
                value = value.strip()
            if key == "cta_text" and value is not None:
                value = value.strip()
            setattr(page, key, value)

        await db.commit()
        await db.refresh(page)
        logger.info("%s updated: id=%s slug=%s status=%s", LINK_MARKER, page.id, page.slug, page.status)
        return await LandingPageService.get_page(db, page_id)

    @staticmethod
    async def get_public(db: AsyncSession, slug: str) -> dict[str, Any]:
        try:
            lookup_slug = _normalize_slug(slug)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Landing page not found") from None
        r = await db.execute(select(LandingPage).where(LandingPage.slug == lookup_slug))
        page = r.scalar_one_or_none()
        if not page or page.status != "published":
            raise HTTPException(status_code=404, detail="Landing page not found")

        product_info = None
        if page.product_id:
            pr = await db.execute(select(Product).where(Product.id == page.product_id))
            prod = pr.scalar_one_or_none()
            if prod:
                desc = prod.description
                if desc and len(desc) > 500:
                    desc = desc[:497] + "..."
                product_info = {
                    "name": prod.name,
                    "category": prod.category,
                    "description": desc,
                }

        campaign_info = None
        if page.campaign_id:
            cr = await db.execute(select(Campaign).where(Campaign.id == page.campaign_id))
            camp = cr.scalar_one_or_none()
            if camp:
                campaign_info = {
                    "name": camp.name,
                    "objective": camp.objective,
                }

        return {
            "slug": page.slug,
            "title": page.title,
            "subtitle": page.subtitle,
            "description": page.description,
            "hero_image_url": page.hero_image_url,
            "cta_text": page.cta_text,
            "product": product_info,
            "campaign": campaign_info,
        }

    @staticmethod
    async def _find_or_create_contact(
        db: AsyncSession,
        *,
        client_id: UUID,
        lead_id: UUID,
        data: PublicLandingLeadSubmit,
        slug: str,
    ) -> CommunicationContact | None:
        if not any([data.email, data.phone, data.telegram, data.whatsapp, data.wechat]):
            return None

        conditions = []
        if data.email:
            conditions.append(CommunicationContact.email == data.email.strip())
        if data.phone:
            conditions.append(CommunicationContact.phone == data.phone.strip())
        if data.telegram:
            conditions.append(CommunicationContact.telegram == data.telegram.strip())
        if data.whatsapp:
            conditions.append(CommunicationContact.whatsapp == data.whatsapp.strip())
        if data.wechat:
            conditions.append(CommunicationContact.wechat == data.wechat.strip())

        from sqlalchemy import or_
        cr = await db.execute(
            select(CommunicationContact).where(
                CommunicationContact.client_id == client_id,
                or_(*conditions),
            ).limit(1)
        )
        contact = cr.scalar_one_or_none()
        if contact:
            if not contact.lead_id:
                contact.lead_id = lead_id
            return contact

        contact = CommunicationContact(
            client_id=client_id,
            lead_id=lead_id,
            name=data.name.strip(),
            company=data.company,
            phone=data.phone,
            email=data.email,
            telegram=data.telegram,
            whatsapp=data.whatsapp,
            wechat=data.wechat,
            country=data.country,
            notes=f"Captured from landing page: {slug}",
        )
        db.add(contact)
        await db.flush()
        logger.info("%s contact created: contact=%s lead=%s", LINK_MARKER, contact.id, lead_id)
        return contact

    @staticmethod
    async def submit_lead(
        db: AsyncSession,
        slug: str,
        data: PublicLandingLeadSubmit,
    ) -> dict[str, Any]:
        try:
            lookup_slug = _normalize_slug(slug)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Landing page not found") from None
        r = await db.execute(select(LandingPage).where(LandingPage.slug == lookup_slug))
        page = r.scalar_one_or_none()
        if not page or page.status != "published":
            raise HTTPException(status_code=404, detail="Landing page not found")

        if not data.name.strip():
            raise HTTPException(status_code=400, detail="Name is required")

        interest_parts: list[str] = [page.title]
        if page.product_id:
            pr = await db.execute(select(Product.name).where(Product.id == page.product_id))
            pname = pr.scalar_one_or_none()
            if pname:
                interest_parts.append(pname)
        if page.campaign_id:
            cr = await db.execute(select(Campaign.name).where(Campaign.id == page.campaign_id))
            cname = cr.scalar_one_or_none()
            if cname:
                interest_parts.append(cname)

        notes_lines = [f"Landing page: {page.title} ({page.slug})"]
        if data.message:
            notes_lines.append(data.message.strip())

        lead_data = CrmLeadCreate(
            client_id=page.client_id,
            name=data.name.strip(),
            company=data.company,
            phone=data.phone,
            email=data.email,
            telegram=data.telegram,
            source="landing_page",
            interest=" · ".join(interest_parts),
            notes="\n".join(notes_lines),
            attribution_source="landing_page",
            attribution_campaign=page.title,
            attribution_notes=f"Submitted via landing page /l/{page.slug}",
            attributed_by="landing_page",
            attribution_link_id=page.attribution_link_id,
        )
        crm_lead = await CrmService.create_lead(db, lead_data)

        landing_lead = LandingLead(
            landing_page_id=page.id,
            name=data.name.strip(),
            company=data.company,
            phone=data.phone,
            email=data.email,
            telegram=data.telegram,
            whatsapp=data.whatsapp,
            wechat=data.wechat,
            country=data.country,
            message=data.message,
            crm_lead_id=crm_lead["id"],
        )
        db.add(landing_lead)
        await db.flush()

        await LandingPageService._find_or_create_contact(
            db,
            client_id=page.client_id,
            lead_id=crm_lead["id"],
            data=data,
            slug=page.slug,
        )

        await db.commit()
        logger.info(
            "%s lead captured: slug=%s landing_lead=%s crm_lead=%s link=%s",
            LINK_MARKER, page.slug, landing_lead.id, crm_lead["id"], page.attribution_link_id,
        )
        logger.info(
            "%s revenue attribution: source=landing_page slug=%s crm_lead=%s attribution_link=%s",
            LINK_MARKER, page.slug, crm_lead["id"], page.attribution_link_id,
        )

        return {"ok": True, "message": "Thank you. We will contact you soon."}
