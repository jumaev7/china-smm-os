"""Attribution link management, click tracking, and CRM/revenue integration."""
from __future__ import annotations

import logging
import secrets
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit
from app.models.attribution_link import AttributionLink, ClickEvent
from app.models.campaign import Campaign
from app.models.client import Client
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.partner import Partner
from app.models.product import Product
from app.schemas.attribution_link import ATTRIBUTION_LINK_CHANNELS, AttributionLinkCreate
from app.services.client_service import ClientService

logger = logging.getLogger(__name__)

LINK_MARKER = "[Attribution Link]"


def _tracking_url(code: str) -> str:
    base = (settings.MEDIA_BASE_URL or "http://localhost:8000").rstrip("/")
    return f"{base}/r/{code}"


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


async def _unique_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:10]
        r = await db.execute(select(AttributionLink.id).where(AttributionLink.code == code))
        if not r.scalar_one_or_none():
            return code
    raise HTTPException(status_code=500, detail="Could not generate unique link code")


async def _revenue_stats_for_links(
    db: AsyncSession,
    link_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    if not link_ids:
        return {}
    rows = await db.execute(
        select(
            CrmLead.attribution_link_id,
            func.count(CrmDeal.id),
            func.coalesce(func.sum(CrmDeal.deal_amount), 0),
            func.coalesce(func.sum(CrmDeal.commission_amount), 0),
        )
        .select_from(CrmDeal)
        .join(CrmLead, CrmDeal.lead_id == CrmLead.id)
        .where(
            CrmLead.attribution_link_id.in_(link_ids),
            CrmDeal.status == "won",
        )
        .group_by(CrmLead.attribution_link_id)
    )
    out: dict[UUID, dict[str, Any]] = {}
    for link_id, won_count, revenue, commission in rows.all():
        if link_id:
            out[link_id] = {
                "won_deals_count": int(won_count or 0),
                "linked_revenue": Decimal(str(revenue or 0)),
                "linked_commission": Decimal(str(commission or 0)),
            }
    return out


async def _serialize_link(
    db: AsyncSession,
    link: AttributionLink,
    *,
    client_names: dict[UUID, str] | None = None,
    campaign_names: dict[UUID, str] | None = None,
    product_names: dict[UUID, str] | None = None,
    partner_names: dict[UUID, str] | None = None,
    revenue_stats: dict[UUID, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if client_names is None:
        client_names = {}
    if campaign_names is None:
        campaign_names = {}
    if product_names is None:
        product_names = {}
    if partner_names is None:
        partner_names = {}
    if revenue_stats is None:
        revenue_stats = await _revenue_stats_for_links(db, [link.id])

    rev = revenue_stats.get(link.id, {
        "won_deals_count": 0,
        "linked_revenue": Decimal("0"),
        "linked_commission": Decimal("0"),
    })
    return {
        "id": link.id,
        "client_id": link.client_id,
        "campaign_id": link.campaign_id,
        "product_id": link.product_id,
        "partner_id": link.partner_id,
        "channel": link.channel,
        "code": link.code,
        "destination_url": link.destination_url,
        "title": link.title,
        "description": link.description,
        "clicks_count": link.clicks_count,
        "leads_count": link.leads_count,
        "tracking_url": _tracking_url(link.code),
        "client_name": client_names.get(link.client_id),
        "campaign_name": campaign_names.get(link.campaign_id) if link.campaign_id else None,
        "product_name": product_names.get(link.product_id) if link.product_id else None,
        "partner_name": partner_names.get(link.partner_id) if link.partner_id else None,
        "conversion_rate": _rate(link.leads_count, link.clicks_count),
        "linked_revenue": rev["linked_revenue"],
        "linked_commission": rev["linked_commission"],
        "won_deals_count": rev["won_deals_count"],
        "created_at": link.created_at,
    }


class AttributionLinkService:
    @staticmethod
    async def create(db: AsyncSession, data: AttributionLinkCreate) -> dict[str, Any]:
        if data.channel not in ATTRIBUTION_LINK_CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel")

        await ClientService.get(db, data.client_id)
        if data.campaign_id:
            cr = await db.execute(select(Campaign).where(Campaign.id == data.campaign_id))
            camp = cr.scalar_one_or_none()
            if not camp or camp.client_id != data.client_id:
                raise HTTPException(status_code=400, detail="Campaign not found for client")
        if data.product_id:
            pr = await db.execute(select(Product).where(Product.id == data.product_id))
            prod = pr.scalar_one_or_none()
            if not prod or prod.client_id != data.client_id:
                raise HTTPException(status_code=400, detail="Product not found for client")
        if data.partner_id:
            par = await db.execute(select(Partner).where(Partner.id == data.partner_id))
            if not par.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="Partner not found")

        code = await _unique_code(db)
        link = AttributionLink(
            client_id=data.client_id,
            campaign_id=data.campaign_id,
            product_id=data.product_id,
            partner_id=data.partner_id,
            channel=data.channel,
            code=code,
            destination_url=data.destination_url.strip(),
            title=data.title.strip(),
            description=data.description,
        )
        db.add(link)
        await db.commit()
        await db.refresh(link)
        logger.info("%s created: id=%s code=%s channel=%s", LINK_MARKER, link.id, code, link.channel)
        return await _serialize_link(db, link)

    @staticmethod
    async def list_links(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        campaign_id: UUID | None = None,
        product_id: UUID | None = None,
        partner_id: UUID | None = None,
        channel: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(AttributionLink)
        count_q = select(func.count()).select_from(AttributionLink)
        if client_id:
            q = q.where(AttributionLink.client_id == client_id)
            count_q = count_q.where(AttributionLink.client_id == client_id)
        if campaign_id:
            q = q.where(AttributionLink.campaign_id == campaign_id)
            count_q = count_q.where(AttributionLink.campaign_id == campaign_id)
        if product_id:
            q = q.where(AttributionLink.product_id == product_id)
            count_q = count_q.where(AttributionLink.product_id == product_id)
        if partner_id:
            q = q.where(AttributionLink.partner_id == partner_id)
            count_q = count_q.where(AttributionLink.partner_id == partner_id)
        if channel:
            if channel not in ATTRIBUTION_LINK_CHANNELS:
                raise HTTPException(status_code=400, detail="Invalid channel")
            q = q.where(AttributionLink.channel == channel)
            count_q = count_q.where(AttributionLink.channel == channel)

        total = int((await db.execute(count_q)).scalar_one())
        r = await db.execute(
            q.order_by(AttributionLink.created_at.desc()).offset(skip).limit(limit)
        )
        links = list(r.scalars().all())
        link_ids = [l.id for l in links]

        client_ids = {l.client_id for l in links}
        campaign_ids = {l.campaign_id for l in links if l.campaign_id}
        product_ids = {l.product_id for l in links if l.product_id}
        partner_ids = {l.partner_id for l in links if l.partner_id}

        client_names = {}
        if client_ids:
            cn = await db.execute(select(Client.id, Client.company_name).where(Client.id.in_(client_ids)))
            client_names = {row[0]: row[1] for row in cn.all()}
        campaign_names = {}
        if campaign_ids:
            cn = await db.execute(select(Campaign.id, Campaign.name).where(Campaign.id.in_(campaign_ids)))
            campaign_names = {row[0]: row[1] for row in cn.all()}
        product_names = {}
        if product_ids:
            pn = await db.execute(select(Product.id, Product.name).where(Product.id.in_(product_ids)))
            product_names = {row[0]: row[1] for row in pn.all()}
        partner_names = {}
        if partner_ids:
            pn = await db.execute(select(Partner.id, Partner.name).where(Partner.id.in_(partner_ids)))
            partner_names = {row[0]: row[1] for row in pn.all()}

        revenue_stats = await _revenue_stats_for_links(db, link_ids)
        items = [
            await _serialize_link(
                db, link,
                client_names=client_names,
                campaign_names=campaign_names,
                product_names=product_names,
                partner_names=partner_names,
                revenue_stats=revenue_stats,
            )
            for link in links
        ]
        return {"items": items, "total": total}

    @staticmethod
    async def record_click_and_redirect(
        db: AsyncSession,
        code: str,
        request: Request,
    ) -> str:
        r = await db.execute(select(AttributionLink).where(AttributionLink.code == code))
        link = r.scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")

        client_host = request.client.host if request.client else None
        user_agent = (request.headers.get("user-agent") or "")[:500] or None
        referrer = (request.headers.get("referer") or request.headers.get("referrer") or "")[:2000] or None

        event = ClickEvent(
            attribution_link_id=link.id,
            source_ip=client_host,
            user_agent=user_agent,
            referrer=referrer,
        )
        db.add(event)
        link.clicks_count = (link.clicks_count or 0) + 1
        await db.commit()
        logger.info("%s click: code=%s clicks=%s", LINK_MARKER, code, link.clicks_count)
        return link.destination_url

    @staticmethod
    async def apply_to_lead(
        db: AsyncSession,
        link_id: UUID,
        lead: CrmLead,
    ) -> None:
        if lead.attribution_link_id == link_id:
            return

        r = await db.execute(select(AttributionLink).where(AttributionLink.id == link_id))
        link = r.scalar_one_or_none()
        if not link:
            raise HTTPException(status_code=404, detail="Attribution link not found")
        if link.client_id != lead.client_id:
            raise HTTPException(status_code=400, detail="Attribution link belongs to a different client")

        first_link = lead.attribution_link_id is None
        lead.attribution_link_id = link_id
        lead.attribution_source = link.channel
        lead.attribution_campaign = link.title
        note_parts = [f"Attribution link: {link.title} ({link.code})"]
        if link.description:
            note_parts.append(link.description[:300])
        lead.attribution_notes = "\n".join(note_parts)

        if first_link:
            link.leads_count = (link.leads_count or 0) + 1
            logger.info(
                "%s lead attributed: link=%s lead=%s leads_count=%s",
                LINK_MARKER, link_id, lead.id, link.leads_count,
            )

    @staticmethod
    async def stats_breakdown(db: AsyncSession) -> list[dict[str, Any]]:
        r = await db.execute(select(AttributionLink).order_by(AttributionLink.leads_count.desc()))
        links = list(r.scalars().all())
        if not links:
            return []

        revenue_stats = await _revenue_stats_for_links(db, [l.id for l in links])
        items: list[dict[str, Any]] = []
        for link in links:
            rev = revenue_stats.get(link.id, {
                "won_deals_count": 0,
                "linked_revenue": Decimal("0"),
                "linked_commission": Decimal("0"),
            })
            items.append({
                "link_id": link.id,
                "title": link.title,
                "code": link.code,
                "channel": link.channel,
                "clicks_count": link.clicks_count,
                "leads_count": link.leads_count,
                "won_deals_count": rev["won_deals_count"],
                "revenue": rev["linked_revenue"],
                "commission": rev["linked_commission"],
                "click_to_lead_rate": _rate(link.leads_count, link.clicks_count),
                "lead_to_won_rate": _rate(rev["won_deals_count"], link.leads_count),
            })
        items.sort(key=lambda x: x["revenue"], reverse=True)
        return items
