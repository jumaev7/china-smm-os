"""Content inventory for campaign planning.

Lists tenant-owned content items (scoped via client → tenant) as assignable
candidates, with lightweight readiness-relevant metadata. Never mutates content.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import TenantCampaignSlotAssignment
from app.models.client import Client
from app.models.content import ContentItem

_LOCALE_FIELDS = {
    "en": ("caption_long_en", "caption_short_en"),
    "ru": ("caption_long_ru", "caption_short_ru"),
    "uz": ("caption_long_uz", "caption_short_uz"),
    "zh": ("caption_long_en", "caption_short_en"),
}


def _available_locales(item: ContentItem) -> list[str]:
    out: list[str] = []
    for loc, fields in _LOCALE_FIELDS.items():
        if loc == "zh":
            continue
        if any((getattr(item, f, None) or "").strip() for f in fields):
            out.append(loc)
    return out


class InventoryService:
    @staticmethod
    async def list_inventory(
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        *,
        platform: str | None = None,
        locale: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        # Content items owned by this tenant (via client).
        base = (
            select(ContentItem)
            .join(Client, Client.id == ContentItem.client_id)
            .where(Client.tenant_id == tenant_id)
        )
        rows = (
            await db.execute(
                base.order_by(ContentItem.created_at.desc()).limit(min(limit, 200)).offset(max(0, offset))
            )
        ).scalars().all()
        total = int(
            (
                await db.execute(
                    select(func.count()).select_from(ContentItem)
                    .join(Client, Client.id == ContentItem.client_id)
                    .where(Client.tenant_id == tenant_id)
                )
            ).scalar() or 0
        )

        # Which content is already assigned in this campaign.
        assigned_rows = (
            await db.execute(
                select(TenantCampaignSlotAssignment.content_id).where(
                    TenantCampaignSlotAssignment.tenant_id == tenant_id,
                    TenantCampaignSlotAssignment.campaign_id == campaign_id,
                    TenantCampaignSlotAssignment.content_id.isnot(None),
                )
            )
        ).scalars().all()
        assigned_ids = {str(cid) for cid in assigned_rows if cid}

        items: list[dict[str, Any]] = []
        for item in rows:
            locales = _available_locales(item)
            platforms = list(item.platforms or [])
            if platform and platforms and platform not in platforms:
                continue
            if locale and locales and locale not in locales:
                continue
            items.append({
                "content_id": item.id,
                "status": item.status,
                "platforms": platforms,
                "available_locales": locales,
                "has_media": bool(getattr(item, "media_file_id", None)),
                "is_assigned_in_campaign": str(item.id) in assigned_ids,
                "approved": getattr(item, "approved_at", None) is not None,
                "created_at": item.created_at,
            })

        return {
            "items": items,
            "total": total,
            "returned": len(items),
        }
