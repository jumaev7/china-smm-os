"""Content Studio — campaign-aware draft generation from media + client context."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.storage import storage
from app.models.campaign import Campaign
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media_library import MediaAsset
from app.models.product import Product
from app.schemas.content import ContentCreate, GeneratedContent, PLATFORMS
from app.schemas.content_studio import (
    CONTENT_STUDIO_GOALS,
    ContentStudioGenerateRequest,
    ContentStudioSuggestionsRequest,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.client_service import ClientService
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

CONTENT_STUDIO_SOURCE = "content_studio"
CONTENT_STUDIO_MARKER = "[Content Studio]"

_GENERATE_SYSTEM = """\
You are an SMM content strategist. Generate social media draft posts for operator review.
NEVER auto-approve, auto-publish, or send to clients — drafts only.

Return ONLY JSON:
{
  "drafts": [
    {
      "title": "internal working title",
      "angle": "1-2 sentence creative angle",
      "platforms": ["instagram", "facebook"],
      "caption_short_ru": "≤150 chars",
      "caption_short_uz": "≤150 chars",
      "caption_short_en": "≤150 chars",
      "caption_long_ru": "200-450 chars with CTA",
      "caption_long_uz": "200-450 chars with CTA",
      "caption_long_en": "200-450 chars with CTA",
      "hashtags": "#tag1 #tag2 ... (10-15 tags)"
    }
  ]
}

Rules:
- Match content_goal and campaign objective when provided
- Use client KB and product catalog facts — do not invent unsupported claims
- Each draft must have a distinct angle
- Platforms must be subset of requested platforms when provided
- Relate captions to selected media assets when described
- Never mention AI or internal tools in captions
"""

_SUGGEST_SYSTEM = """\
You suggest content ideas for an SMM team planning upcoming posts.
Advisory only — no auto-publish or outreach.

Return ONLY JSON:
{
  "suggestions": [
    {
      "title": "short idea title",
      "angle": "1-2 sentences",
      "content_goal": "Brand awareness|Lead generation|Product promotion|Distributor recruitment|Trade show announcement",
      "suggested_platforms": ["instagram", "linkedin"],
      "rationale": "why this fits now"
    }
  ]
}
Return 4-6 suggestions sorted by relevance.
"""


def _normalize_platforms(raw: Any, requested: list[str]) -> list[str]:
    allowed = set(requested) if requested else set(PLATFORMS)
    if not isinstance(raw, list):
        return list(allowed)[:2] if allowed else ["instagram"]
    out: list[str] = []
    for p in raw:
        key = str(p).lower().strip()
        if key in PLATFORMS and key in allowed and key not in out:
            out.append(key)
    if out:
        return out
    return list(allowed)[:2] if allowed else ["instagram"]


def _preview_from_captions(captions: dict[str, Any]) -> str:
    for field in ("caption_long_en", "caption_short_en", "caption_long_ru", "caption_short_ru"):
        val = str(captions.get(field) or "").strip()
        if val:
            return val[:160] + ("…" if len(val) > 160 else "")
    return str(captions.get("title") or "Draft")


def _ensure_caption_payload(raw: dict[str, Any], *, fallback_title: str) -> dict[str, str]:
    fb = fallback_title[:120]
    fields = (
        "caption_short_ru", "caption_short_uz", "caption_short_en",
        "caption_long_ru", "caption_long_uz", "caption_long_en",
        "hashtags",
    )
    out: dict[str, str] = {}
    for field in fields:
        val = str(raw.get(field) or "").strip()
        if not val:
            if field == "hashtags":
                val = "#content #marketing"
            elif field.startswith("caption_short"):
                val = fb[:150]
            else:
                val = fb[:400]
        out[field] = val
    return out


def _heuristic_drafts(
    *,
    client: Client,
    count: int,
    content_goal: str,
    platforms: list[str],
) -> list[dict[str, Any]]:
    plats = platforms[:2] if platforms else ["instagram"]
    company = client.company_name
    drafts: list[dict[str, Any]] = []
    templates = [
        (f"{content_goal}: {company}", f"Highlight {company} strengths for {content_goal.lower()}."),
        (f"Behind the scenes — {company}", f"Show craftsmanship and trust for {content_goal.lower()}."),
        (f"Customer value — {company}", f"Connect product benefits to audience needs."),
    ]
    for i in range(count):
        title, angle = templates[i % len(templates)]
        base = f"{angle} {company}."
        drafts.append({
            "title": title,
            "angle": angle,
            "platforms": plats,
            "caption_short_ru": base[:150],
            "caption_short_uz": base[:150],
            "caption_short_en": base[:150],
            "caption_long_ru": base[:400],
            "caption_long_uz": base[:400],
            "caption_long_en": base[:400],
            "hashtags": f"#{company.replace(' ', '')} #content",
        })
    return drafts[:count]


def _heuristic_suggestions(*, client: Client, campaign: Campaign | None) -> list[dict[str, Any]]:
    camp = f" for campaign «{campaign.name}»" if campaign else ""
    return [
        {
            "title": f"Brand spotlight{camp}",
            "angle": f"Introduce {client.company_name} values and visual identity.",
            "content_goal": "Brand awareness",
            "suggested_platforms": ["instagram", "facebook"],
            "rationale": "Build recognition with consistent brand storytelling.",
        },
        {
            "title": "Product hero post",
            "angle": "Feature a flagship product with specs and MOQ-friendly CTA.",
            "content_goal": "Product promotion",
            "suggested_platforms": ["linkedin", "telegram"],
            "rationale": "Catalog-aligned post for B2B buyers.",
        },
        {
            "title": "Trade fair teaser",
            "angle": "Announce booth presence and invite distributors to meet.",
            "content_goal": "Trade show announcement",
            "suggested_platforms": ["linkedin", "telegram"],
            "rationale": "Timely if campaign objective mentions events.",
        },
        {
            "title": "Partner recruitment",
            "angle": "Explain distributor benefits and application path.",
            "content_goal": "Distributor recruitment",
            "suggested_platforms": ["linkedin"],
            "rationale": "Supports partner network growth.",
        },
    ]


async def _load_media_assets(
    db: AsyncSession,
    client_id: UUID,
    asset_ids: list[UUID],
) -> list[MediaAsset]:
    if not asset_ids:
        return []
    r = await db.execute(
        select(MediaAsset)
        .options(selectinload(MediaAsset.media_file))
        .where(MediaAsset.id.in_(asset_ids), MediaAsset.client_id == client_id)
    )
    assets = list(r.scalars().all())
    if len(assets) != len(asset_ids):
        raise HTTPException(status_code=404, detail="One or more media assets not found")
    return assets


async def _build_context_block(
    db: AsyncSession,
    *,
    client: Client,
    campaign: Campaign | None,
    assets: list[MediaAsset],
) -> str:
    kb = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, max_chars=3500, context="content_studio",
    )
    products_r = await db.execute(
        select(Product)
        .where(Product.client_id == client.id, Product.active.is_(True))
        .order_by(Product.name)
        .limit(12)
    )
    products = list(products_r.scalars().all())
    product_lines = [
        f"- {p.name}" + (f" ({p.category})" if p.category else "")
        for p in products[:8]
    ]

    recent_r = await db.execute(
        select(ContentItem)
        .where(ContentItem.client_id == client.id)
        .order_by(ContentItem.created_at.desc())
        .limit(6)
    )
    recent = list(recent_r.scalars().all())
    recent_lines = []
    for item in recent:
        preview = item.caption_short_en or item.caption_short_ru or item.internal_notes or ""
        if preview:
            recent_lines.append(f"- [{item.status}] {str(preview)[:80]}")

    asset_lines = []
    for a in assets:
        labels = a.ai_labels_json or {}
        tags = ", ".join((a.tags_json or [])[:5])
        asset_lines.append(
            f"- {a.title} ({a.file_type}): {a.description or a.original_filename}"
            + (f" | tags: {tags}" if tags else "")
            + (f" | AI products: {', '.join((labels.get('products') or [])[:3])}" if labels.get("products") else "")
        )

    brand = brand_profile_from_client(client)
    parts = [
        f"CLIENT: {client.company_name}",
        f"CATEGORY: {client.business_category}",
        f"STYLE: {client.content_style}",
    ]
    if campaign:
        parts.extend([
            f"CAMPAIGN: {campaign.name}",
            f"CAMPAIGN OBJECTIVE: {campaign.objective or '—'}",
            f"CAMPAIGN DESCRIPTION: {campaign.description or '—'}",
        ])
    if brand.get("business_description"):
        parts.append(f"BRAND: {brand['business_description'][:400]}")
    if asset_lines:
        parts.append("MEDIA ASSETS:\n" + "\n".join(asset_lines))
    if product_lines:
        parts.append("PRODUCT CATALOG:\n" + "\n".join(product_lines))
    if recent_lines:
        parts.append("RECENT CONTENT:\n" + "\n".join(recent_lines))
    if kb:
        parts.append(kb)
    return "\n\n".join(parts)


class ContentStudioService:
    @staticmethod
    async def generate(
        db: AsyncSession,
        data: ContentStudioGenerateRequest,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, data.client_id)
        campaign: Campaign | None = None
        if data.campaign_id:
            cr = await db.execute(select(Campaign).where(Campaign.id == data.campaign_id))
            campaign = cr.scalar_one_or_none()
            if not campaign:
                raise HTTPException(status_code=404, detail="Campaign not found")
            if campaign.client_id != client.id:
                raise HTTPException(status_code=400, detail="Campaign belongs to a different client")

        platforms = [p for p in data.platforms if p in PLATFORMS] or list(PLATFORMS[:3])
        assets = await _load_media_assets(db, client.id, data.media_asset_ids)
        context_block = await _build_context_block(db, client=client, campaign=campaign, assets=assets)

        demo_mode = False
        raw_drafts: list[dict[str, Any]] = []
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            user_prompt = f"""\
CONTENT GOAL: {data.content_goal}
DRAFTS NEEDED: {data.content_count}
PLATFORMS (use subset): {', '.join(platforms)}

{context_block}
"""
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _GENERATE_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.65,
                max_tokens=4500,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            raw_drafts = parsed.get("drafts") or []
            if not isinstance(raw_drafts, list) or not raw_drafts:
                raise ValueError("empty drafts")
        except Exception as exc:
            demo_mode = True
            logger.info("[Content Studio] generate fallback: %s", exc)
            raw_drafts = _heuristic_drafts(
                client=client,
                count=data.content_count,
                content_goal=data.content_goal,
                platforms=platforms,
            )

        created: list[dict[str, Any]] = []
        for i, raw in enumerate(raw_drafts[: data.content_count]):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or f"Studio draft {i + 1}").strip()[:255]
            angle = str(raw.get("angle") or title).strip()
            draft_platforms = _normalize_platforms(raw.get("platforms"), platforms)

            asset = assets[i % len(assets)] if assets else None
            media_file_id = asset.media_file_id if asset else None

            notes = (
                f"{CONTENT_STUDIO_MARKER}\n"
                f"Title: {title}\n"
                f"Goal: {data.content_goal}\n"
                f"Angle: {angle}\n"
                + (f"Campaign: {campaign.name}\n" if campaign else "")
                + (f"Media asset: {asset.title}\n" if asset else "")
            )

            content = await ContentService.create(
                db,
                ContentCreate(
                    client_id=client.id,
                    media_file_id=media_file_id,
                    platforms=draft_platforms,
                    internal_notes=notes,
                    source=CONTENT_STUDIO_SOURCE,
                ),
            )
            content_row = await ContentService.get(db, content.id)
            if campaign:
                content_row.campaign_id = campaign.id

            payload = _ensure_caption_payload(raw, fallback_title=title)
            generated = GeneratedContent(**payload)
            await ContentService.apply_generated(db, content.id, generated)
            content_row = await ContentService.get(db, content.id)
            content_row.status = "draft"
            await db.commit()

            media_url = None
            if content_row.media_file:
                media_url = storage.get_url(content_row.media_file.storage_path)

            created.append({
                "content_id": content_row.id,
                "title": title,
                "preview": _preview_from_captions({**raw, "title": title}),
                "platforms": draft_platforms,
                "media_asset_id": asset.id if asset else None,
                "media_url": media_url,
                "status": "draft",
            })

        logger.info(
            "[Content Studio] generated: client=%s count=%s demo=%s",
            client.id, len(created), demo_mode,
        )
        return {
            "drafts": created,
            "generated_count": len(created),
            "demo_mode": demo_mode,
        }

    @staticmethod
    async def suggestions(
        db: AsyncSession,
        params: ContentStudioSuggestionsRequest,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, params.client_id)
        campaign: Campaign | None = None
        if params.campaign_id:
            cr = await db.execute(select(Campaign).where(Campaign.id == params.campaign_id))
            campaign = cr.scalar_one_or_none()
            if not campaign:
                raise HTTPException(status_code=404, detail="Campaign not found")
            if campaign.client_id != client.id:
                raise HTTPException(status_code=400, detail="Campaign belongs to a different client")

        assets = await _load_media_assets(db, client.id, params.media_asset_ids)
        suggestions = _heuristic_suggestions(client=client, campaign=campaign)
        logger.info("[Content Studio] suggestions: client=%s count=%s (heuristic)", client.id, len(suggestions))
        return {"suggestions": suggestions, "demo_mode": True}
