"""Campaign service — organizational grouping for content (no workflow changes)."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.client_scope_guard import guard_resource_client_id, scope_select
from app.core.storage import storage
from app.models.campaign import CAMPAIGN_STATUSES, Campaign
from app.models.client import Client
from app.models.content import ContentItem
from app.schemas.campaign import CampaignCreate, CampaignUpdate

logger = logging.getLogger(__name__)

_REVIEW_STATUSES = frozenset({"ready", "ready_for_approval", "changes_requested"})
_SCHEDULED_STATUSES = frozenset({"scheduled", "publishing"})


def _caption_preview(item: ContentItem) -> str | None:
    for field in (
        "caption_short_en", "caption_short_ru", "caption_short_uz",
        "caption_long_en", "caption_long_ru", "caption_long_uz",
        "internal_notes",
    ):
        val = getattr(item, field, None)
        if val and str(val).strip():
            text = str(val).strip()
            return text[:120] + ("…" if len(text) > 120 else "")
    return None


def _status_bucket(status: str) -> str | None:
    if status == "draft":
        return "draft"
    if status in _REVIEW_STATUSES:
        return "review"
    if status == "approved":
        return "approved"
    if status in _SCHEDULED_STATUSES:
        return "scheduled"
    if status == "published":
        return "published"
    return None


def _count_statuses(items: list[ContentItem]) -> dict[str, int]:
    counts = {"draft": 0, "review": 0, "approved": 0, "scheduled": 0, "published": 0}
    for item in items:
        bucket = _status_bucket(item.status)
        if bucket:
            counts[bucket] += 1
    return counts


def _serialize_content_item(item: ContentItem) -> dict[str, Any]:
    media_url = None
    if item.media_file:
        media_url = storage.get_url(item.media_file.storage_path)
    return {
        "id": item.id,
        "status": item.status,
        "platforms": list(item.platforms or []),
        "source": item.source,
        "scheduled_for": item.scheduled_for,
        "published_at": item.published_at,
        "created_at": item.created_at,
        "media_url": media_url,
        "caption_preview": _caption_preview(item),
    }


def _serialize_campaign(
    campaign: Campaign,
    *,
    client_name: str | None = None,
    posts_count: int | None = None,
) -> dict[str, Any]:
    count = posts_count if posts_count is not None else len(campaign.content_items or [])
    return {
        "id": campaign.id,
        "client_id": campaign.client_id,
        "name": campaign.name,
        "description": campaign.description,
        "objective": campaign.objective,
        "status": campaign.status,
        "start_date": campaign.start_date,
        "end_date": campaign.end_date,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
        "client_name": client_name or (campaign.client.name if campaign.client else None),
        "posts_count": count,
    }


class CampaignService:
    @staticmethod
    async def list_campaigns(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        q = (
            select(Campaign)
            .options(selectinload(Campaign.client))
            .order_by(Campaign.updated_at.desc())
        )
        count_q = select(func.count()).select_from(Campaign)
        q, count_q = scope_select(q, count_q, Campaign.client_id, client_id=client_id)
        if status:
            q = q.where(Campaign.status == status)
            count_q = count_q.where(Campaign.status == status)

        total = (await db.execute(count_q)).scalar_one()
        rows = list((await db.execute(q.offset(skip).limit(limit))).scalars().all())

        campaign_ids = [c.id for c in rows]
        posts_map: dict[UUID, int] = {}
        if campaign_ids:
            posts_r = await db.execute(
                select(ContentItem.campaign_id, func.count())
                .where(ContentItem.campaign_id.in_(campaign_ids))
                .group_by(ContentItem.campaign_id)
            )
            posts_map = {row[0]: row[1] for row in posts_r.all()}

        items = [
            _serialize_campaign(
                c,
                client_name=c.client.name if c.client else None,
                posts_count=posts_map.get(c.id, 0),
            )
            for c in rows
        ]
        logger.info("[Campaign] listed: total=%s returned=%s", total, len(items))
        return {"items": items, "total": total}

    @staticmethod
    async def create_campaign(db: AsyncSession, body: CampaignCreate) -> dict[str, Any]:
        client_r = await db.execute(select(Client).where(Client.id == body.client_id))
        if not client_r.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Client not found")
        if body.status not in CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid campaign status")
        if body.start_date and body.end_date and body.end_date < body.start_date:
            raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

        campaign = Campaign(
            client_id=body.client_id,
            name=body.name.strip(),
            description=body.description,
            objective=body.objective,
            status=body.status,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign, attribute_names=["client"])
        logger.info("[Campaign] created: id=%s client=%s", campaign.id, campaign.client_id)
        return _serialize_campaign(campaign, client_name=campaign.client.name if campaign.client else None)

    @staticmethod
    async def update_campaign(
        db: AsyncSession,
        campaign_id: UUID,
        body: CampaignUpdate,
    ) -> dict[str, Any]:
        r = await db.execute(
            select(Campaign)
            .options(selectinload(Campaign.client))
            .where(Campaign.id == campaign_id)
        )
        campaign = r.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        data = body.model_dump(exclude_unset=True)
        if "status" in data and data["status"] not in CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid campaign status")
        if "name" in data and data["name"]:
            data["name"] = data["name"].strip()

        start = data.get("start_date", campaign.start_date)
        end = data.get("end_date", campaign.end_date)
        if start and end and end < start:
            raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

        for key, val in data.items():
            setattr(campaign, key, val)
        await db.commit()
        await db.refresh(campaign)

        posts_r = await db.execute(
            select(func.count()).select_from(ContentItem).where(ContentItem.campaign_id == campaign_id)
        )
        posts_count = int(posts_r.scalar_one() or 0)
        logger.info("[Campaign] updated: id=%s", campaign_id)
        return _serialize_campaign(
            campaign,
            client_name=campaign.client.name if campaign.client else None,
            posts_count=posts_count,
        )

    @staticmethod
    async def get_campaign(db: AsyncSession, campaign_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(Campaign)
            .options(
                selectinload(Campaign.client),
                selectinload(Campaign.content_items).selectinload(ContentItem.media_file),
            )
            .where(Campaign.id == campaign_id)
        )
        campaign = r.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        guard_resource_client_id(campaign.client_id)

        items = sorted(campaign.content_items or [], key=lambda i: i.created_at, reverse=True)
        data = _serialize_campaign(
            campaign,
            client_name=campaign.client.name if campaign.client else None,
            posts_count=len(items),
        )
        data["status_counts"] = _count_statuses(items)
        data["content_items"] = [_serialize_content_item(i) for i in items]
        logger.info("[Campaign] detail: id=%s posts=%s", campaign_id, len(items))
        return data

    @staticmethod
    async def assign_content(
        db: AsyncSession,
        campaign_id: UUID,
        content_ids: list[UUID],
    ) -> dict[str, Any]:
        r = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
        campaign = r.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        content_r = await db.execute(
            select(ContentItem).where(ContentItem.id.in_(content_ids))
        )
        items = list(content_r.scalars().all())
        if len(items) != len(content_ids):
            raise HTTPException(status_code=404, detail="One or more content items not found")

        assigned = 0
        for item in items:
            if item.client_id != campaign.client_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Content {item.id} belongs to a different client",
                )
            item.campaign_id = campaign_id
            assigned += 1

        await db.commit()
        logger.info("[Campaign] assign: campaign=%s count=%s", campaign_id, assigned)
        return {"assigned": assigned, "campaign_id": campaign_id}

    @staticmethod
    async def unassign_content(
        db: AsyncSession,
        campaign_id: UUID,
        content_ids: list[UUID],
    ) -> dict[str, Any]:
        content_r = await db.execute(
            select(ContentItem).where(
                ContentItem.id.in_(content_ids),
                ContentItem.campaign_id == campaign_id,
            )
        )
        items = list(content_r.scalars().all())
        for item in items:
            item.campaign_id = None
        await db.commit()
        logger.info("[Campaign] unassign: campaign=%s count=%s", campaign_id, len(items))
        return {"unassigned": len(items), "campaign_id": campaign_id}
