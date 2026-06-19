"""AI Content Factory dashboard, library, KPIs, recommendations, demo mode."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.client_scope_guard import guard_resource_client_id, scope_select
from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.content_factory import ContentFactory, ContentFactoryItem
from app.services.content_factory_constants import (
    CONTENT_CATEGORIES,
    REVIEW_STATUSES,
    SUPPORTED_LANGUAGES,
    _CATEGORY_LABELS,
)
from app.services.content_service import ContentService
from app.services.client_service import ClientService

logger = logging.getLogger(__name__)


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_json_dict(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _serialize_item_summary(item: ContentFactoryItem, *, company_name: str | None = None) -> dict[str, Any]:
    platforms = _parse_json_list(item.platforms_json)
    scores = _parse_json_dict(item.quality_scores_json)
    return {
        "id": item.id,
        "factory_id": item.factory_id,
        "company_name": company_name,
        "content_type": item.content_type,
        "theme": item.theme,
        "title": item.title,
        "headline": item.headline,
        "platforms": platforms,
        "review_status": item.review_status or "generated",
        "preview_caption": item.preview_caption,
        "generated_content_id": item.generated_content_id,
        "overall_score": scores.get("overall_score") if scores else None,
        "scheduled_for": item.scheduled_for,
        "created_at": item.created_at,
    }


class ContentFactoryDashboardService:
    @staticmethod
    async def dashboard(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        guard_resource_client_id(client_id)

        item_q = (
            select(ContentFactoryItem)
            .join(ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id)
            .options(selectinload(ContentFactoryItem.factory).selectinload(ContentFactory.client))
            .order_by(ContentFactoryItem.created_at.desc())
        )
        item_q, _ = scope_select(item_q, None, ContentFactory.client_id, client_id=client_id)
        items = (await db.execute(item_q.limit(200))).scalars().all()

        content_q = select(ContentItem).where(ContentItem.source == "content_factory")
        content_q, _ = scope_select(content_q, None, ContentItem.client_id, client_id=client_id)
        factory_content = (await db.execute(content_q)).scalars().all()

        status_counts: dict[str, int] = {s: 0 for s in REVIEW_STATUSES}
        for item in items:
            st = item.review_status or "generated"
            status_counts[st] = status_counts.get(st, 0) + 1

        lang_usage: dict[str, int] = {l: 0 for l in SUPPORTED_LANGUAGES}
        type_counts: dict[str, int] = {}
        approved = 0
        published = 0
        for item in items:
            type_counts[item.content_type] = type_counts.get(item.content_type, 0) + 1
            if item.review_status == "approved":
                approved += 1
            if item.review_status == "published":
                published += 1
            factory = item.factory
            langs = _parse_json_list(factory.target_languages_json if factory else None)
            for lang in langs:
                if lang in lang_usage:
                    lang_usage[lang] += 1

        total_items = len(items)
        approval_rate = round(approved / total_items * 100, 1) if total_items else 0
        publishing_rate = round(published / total_items * 100, 1) if total_items else 0

        content_queue = [
            _serialize_item_summary(i, company_name=i.factory.client.company_name if i.factory and i.factory.client else None)
            for i in items
            if (i.review_status or "generated") in ("draft", "generated", "needs_review")
        ][:20]

        approval_queue = [
            _serialize_item_summary(i, company_name=i.factory.client.company_name if i.factory and i.factory.client else None)
            for i in items
            if (i.review_status or "") in ("needs_review", "generated")
        ][:20]

        publishing_queue = [
            _serialize_item_summary(i, company_name=i.factory.client.company_name if i.factory and i.factory.client else None)
            for i in items
            if (i.review_status or "") in ("approved", "scheduled")
        ][:20]

        generated = [
            _serialize_item_summary(i, company_name=i.factory.client.company_name if i.factory and i.factory.client else None)
            for i in items
            if (i.review_status or "generated") == "generated"
        ][:20]

        top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:5]

        return {
            "content_queue": content_queue,
            "generated_content": generated,
            "approval_queue": approval_queue,
            "publishing_queue": publishing_queue,
            "kpis": {
                "content_created": total_items,
                "content_published": published,
                "languages_used": lang_usage,
                "approval_rate": approval_rate,
                "publishing_rate": publishing_rate,
                "top_content_types": [{"type": t, "count": c} for t, c in top_types],
                "factory_drafts": len(factory_content),
            },
            "status_counts": status_counts,
        }

    @staticmethod
    async def library(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        language: str | None = None,
        content_type: str | None = None,
        content_category: str | None = None,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        guard_resource_client_id(client_id)

        q = (
            select(ContentFactoryItem)
            .join(ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id)
            .options(selectinload(ContentFactoryItem.factory).selectinload(ContentFactory.client))
            .order_by(ContentFactoryItem.created_at.desc())
        )
        count_q = select(func.count()).select_from(ContentFactoryItem).join(
            ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id,
        )
        q, count_q = scope_select(q, count_q, ContentFactory.client_id, client_id=client_id)

        if content_type:
            q = q.where(ContentFactoryItem.content_type == content_type)
            count_q = count_q.where(ContentFactoryItem.content_type == content_type)
        if status:
            q = q.where(ContentFactoryItem.review_status == status)
            count_q = count_q.where(ContentFactoryItem.review_status == status)
        if content_category:
            q = q.where(ContentFactory.content_category == content_category)
            count_q = count_q.where(ContentFactory.content_category == content_category)
        if language:
            q = q.where(ContentFactory.target_languages_json.ilike(f'%"{language}"%'))
            count_q = count_q.where(ContentFactory.target_languages_json.ilike(f'%"{language}"%'))
        if platform:
            q = q.where(ContentFactoryItem.platforms_json.ilike(f'%"{platform}"%'))
            count_q = count_q.where(ContentFactoryItem.platforms_json.ilike(f'%"{platform}"%'))

        total = (await db.execute(count_q)).scalar() or 0
        rows = (await db.execute(q.offset(offset).limit(min(limit, 100)))).scalars().all()

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": [
                {
                    **_serialize_item_summary(
                        row,
                        company_name=row.factory.client.company_name if row.factory and row.factory.client else None,
                    ),
                    "content_category": row.factory.content_category if row.factory else None,
                    "angle": row.angle,
                    "hashtags": row.hashtags,
                    "quality_scores": _parse_json_dict(row.quality_scores_json),
                }
                for row in rows
            ],
        }

    @staticmethod
    async def review_queue(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        guard_resource_client_id(client_id)
        statuses = [status] if status else list(REVIEW_STATUSES)

        q = (
            select(ContentFactoryItem)
            .join(ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id)
            .options(
                selectinload(ContentFactoryItem.factory).selectinload(ContentFactory.client),
                selectinload(ContentFactoryItem.factory).selectinload(ContentFactory.source_media),
            )
            .where(ContentFactoryItem.review_status.in_(statuses))
            .order_by(ContentFactoryItem.created_at.desc())
        )
        q, _ = scope_select(q, None, ContentFactory.client_id, client_id=client_id)
        rows = (await db.execute(q.limit(100))).scalars().all()

        from app.core.storage import storage

        items = []
        for row in rows:
            factory = row.factory
            media_url = None
            if factory and factory.source_media:
                media_url = storage.get_url(factory.source_media.storage_path)
            captions = _parse_json_dict(row.captions_json) or {}
            items.append({
                **_serialize_item_summary(row, company_name=factory.client.company_name if factory and factory.client else None),
                "angle": row.angle,
                "hashtags": row.hashtags,
                "headline": row.headline,
                "cta_suggestion": row.cta_suggestion,
                "captions": captions,
                "quality_scores": _parse_json_dict(row.quality_scores_json),
                "platform_variants": _parse_json_dict(row.platform_variants_json),
                "source_media_url": media_url,
                "content_category": factory.content_category if factory else None,
            })

        grouped: dict[str, list] = {s: [] for s in REVIEW_STATUSES}
        for item in items:
            st = item.get("review_status") or "generated"
            if st in grouped:
                grouped[st].append(item)

        return {"items": items, "grouped": grouped, "statuses": list(REVIEW_STATUSES)}

    @staticmethod
    async def update_review_status(
        db: AsyncSession,
        item_id: UUID,
        *,
        review_status: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if review_status not in REVIEW_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {review_status}")

        item = await ContentFactoryDashboardService._load_item(db, item_id)
        guard_resource_client_id(item.factory.client_id)

        item.review_status = review_status
        if notes:
            meta = _parse_json_dict(item.factory.metadata_json) or {}
            meta.setdefault("review_notes", {})[str(item_id)] = notes
            item.factory.metadata_json = json.dumps(meta, ensure_ascii=False)

        if review_status == "approved" and item.generated_content_id:
            content = await ContentService.get(db, item.generated_content_id)
            if content.status in ("draft", "needs_review", "ready"):
                content.status = "approved"
                content.approved_at = datetime.now(timezone.utc)

        await db.commit()
        return {"ok": True, "item_id": item_id, "review_status": review_status}

    @staticmethod
    async def recommendations(
        db: AsyncSession,
        *,
        client_id: UUID,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, client_id)
        guard_resource_client_id(client.id)

        q = (
            select(ContentFactoryItem)
            .join(ContentFactory, ContentFactoryItem.factory_id == ContentFactory.id)
            .where(ContentFactory.client_id == client_id)
        )
        items = (await db.execute(q)).scalars().all()

        type_counts: dict[str, int] = {c: 0 for c in CONTENT_CATEGORIES}
        lang_counts: dict[str, int] = {l: 0 for l in SUPPORTED_LANGUAGES}
        for item in items:
            factory_result = await db.execute(
                select(ContentFactory).where(ContentFactory.id == item.factory_id)
            )
            factory = factory_result.scalar_one_or_none()
            if factory and factory.content_category in type_counts:
                type_counts[factory.content_category] += 1
            if factory:
                for lang in _parse_json_list(factory.target_languages_json):
                    if lang in lang_counts:
                        lang_counts[lang] += 1

        missing_categories = [
            {"category": c, "label": _CATEGORY_LABELS.get(c, c)}
            for c, count in type_counts.items()
            if count == 0
        ][:5]

        suggested_languages = [
            lang for lang, count in sorted(lang_counts.items(), key=lambda x: x[1])
            if count < max(len(items) // 4, 1)
        ][:2]

        campaigns = []
        if missing_categories:
            cat = missing_categories[0]["category"]
            campaigns.append({
                "title": f"{_CATEGORY_LABELS.get(cat, cat)} campaign",
                "description": f"No {cat.replace('_', ' ')} content yet — ideal for buyer outreach",
                "suggested_platforms": ["linkedin", "telegram", "wechat"],
            })

        return {
            "best_posting_times": ["09:00", "12:30", "18:00"],
            "missing_content_categories": missing_categories,
            "suggested_campaigns": campaigns,
            "suggested_languages": suggested_languages or ["zh", "en"],
            "suggested_buyer_content": [
                "Export-ready product specs with MOQ and lead time",
                "Factory certification showcase (ISO, CE)",
                "Customer case study from CIS or Central Asia market",
            ],
        }

    @staticmethod
    async def demo_samples(db: AsyncSession, *, client_id: UUID) -> dict[str, Any]:
        client = await ClientService.get(db, client_id)
        guard_resource_client_id(client.id)

        if not settings.DEMO_MODE:
            raise HTTPException(status_code=400, detail="Demo samples only available in DEMO_MODE")

        name = client.company_name
        samples = [
            {
                "content_type": "post",
                "theme": "Product launch",
                "title": f"{name} — New export line",
                "headline": f"Introducing {name}'s latest export-ready product",
                "preview_caption": f"Premium manufacturing from {name}. MOQ available. Contact for catalog.",
                "platforms": ["linkedin", "telegram", "wechat"],
                "review_status": "generated",
                "quality_scores": {"overall_score": 82, "quality_score": 85, "engagement_score": 78},
            },
            {
                "content_type": "telegram",
                "theme": "Factory tour",
                "title": f"{name} production showcase",
                "headline": "See our production line in action",
                "preview_caption": "Behind the scenes at our facility — quality control at every step.",
                "platforms": ["telegram", "whatsapp_status"],
                "review_status": "needs_review",
                "quality_scores": {"overall_score": 76},
            },
        ]
        return {
            "samples": samples,
            "sample_campaigns": [
                {"name": "CIS Export Push", "platforms": ["telegram", "linkedin"], "languages": ["ru", "en"]},
                {"name": "WeChat B2B", "platforms": ["wechat"], "languages": ["zh", "en"]},
            ],
        }

    @staticmethod
    async def list_factories(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        guard_resource_client_id(client_id)
        q = (
            select(ContentFactory)
            .options(selectinload(ContentFactory.client), selectinload(ContentFactory.items))
            .order_by(ContentFactory.created_at.desc())
        )
        q, _ = scope_select(q, None, ContentFactory.client_id, client_id=client_id)
        rows = (await db.execute(q.limit(min(limit, 50)))).scalars().all()
        return {
            "factories": [
                {
                    "id": f.id,
                    "client_id": f.client_id,
                    "company_name": f.client.company_name if f.client else None,
                    "status": f.status,
                    "input_type": f.input_type,
                    "content_category": f.content_category,
                    "item_count": len(f.items),
                    "created_at": f.created_at,
                }
                for f in rows
            ],
        }

    @staticmethod
    async def _load_item(db: AsyncSession, item_id: UUID) -> ContentFactoryItem:
        result = await db.execute(
            select(ContentFactoryItem)
            .options(selectinload(ContentFactoryItem.factory).selectinload(ContentFactory.client))
            .where(ContentFactoryItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Factory item not found")
        return item
