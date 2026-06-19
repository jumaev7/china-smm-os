"""AI Content Repurposing Engine — multi-format drafts from media, content, or campaign assets."""
from __future__ import annotations

import logging
from dataclasses import dataclass
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
from app.schemas.content_repurpose import (
    REPURPOSE_FORMAT_LABELS,
    REPURPOSE_OUTPUT_FORMATS,
    ContentRepurposeGenerateRequest,
    ContentRepurposeSuggestionsRequest,
)
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.client_service import ClientService
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

REPURPOSE_SOURCE = "repurpose_engine"
REPURPOSE_MARKER = "[Repurpose Engine]"
SUGGESTION_MARKER = "[Repurpose Suggestion]"

FORMAT_PLATFORMS: dict[str, list[str]] = {
    "instagram_post": ["instagram"],
    "facebook_post": ["facebook"],
    "linkedin_post": ["linkedin"],
    "telegram_post": ["telegram"],
    "short_video_script": ["tiktok", "instagram"],
    "carousel_post": ["instagram", "facebook"],
    "distributor_recruitment_post": ["linkedin", "telegram"],
}

_GENERATE_SYSTEM = """\
You are an SMM repurposing strategist. Transform one source into multiple platform-specific drafts.
NEVER auto-approve, auto-publish, or send to clients — drafts only for operator review.

Return ONLY JSON:
{
  "outputs": [
    {
      "output_format": "instagram_post",
      "caption_short_ru": "≤150 chars",
      "caption_short_uz": "≤150 chars",
      "caption_short_en": "≤150 chars",
      "caption_long_ru": "platform-appropriate length with CTA",
      "caption_long_uz": "platform-appropriate length with CTA",
      "caption_long_en": "platform-appropriate length with CTA",
      "hashtags": "#tag1 #tag2 ...",
      "extra_notes": "carousel slide bullets or video script beats when relevant"
    }
  ]
}

Rules:
- One output object per requested output_format — use exact format keys provided
- Match tone to platform (LinkedIn professional, Telegram concise, etc.)
- short_video_script: put hook + scenes + CTA in extra_notes and caption_long fields
- carousel_post: list 4-6 slide headlines in extra_notes
- distributor_recruitment_post: emphasize partnership benefits and MOQ/export angle
- Use client KB, campaign objective, and product catalog — no invented claims
- Never mention AI or internal tools in captions
"""

_SUGGEST_SYSTEM = """\
You recommend the best repurposing output formats for a given source asset or content.
Advisory only — no auto-publish.

Return ONLY JSON:
{
  "suggestions": [
    {
      "output_format": "instagram_post",
      "rationale": "why this format fits the source",
      "priority": 1
    }
  ]
}

Allowed output_format values:
instagram_post, facebook_post, linkedin_post, telegram_post, short_video_script, carousel_post, distributor_recruitment_post

Return 3-5 suggestions sorted by priority (1 = best fit).
"""


@dataclass
class _ResolvedSource:
    source_type: str
    source_id: UUID
    client_id: UUID
    campaign: Campaign | None
    assets: list[MediaAsset]
    source_content: ContentItem | None
    media_file_id: UUID | None
    parent_content_id: UUID | None
    parent_media_asset_id: UUID | None


def _normalize_formats(raw: list[str]) -> list[str]:
    out: list[str] = []
    for fmt in raw:
        key = str(fmt).strip()
        if key in REPURPOSE_OUTPUT_FORMATS and key not in out:
            out.append(key)
    return out


def _preview_from_payload(raw: dict[str, Any], *, fmt: str) -> str:
    for field in ("caption_long_en", "caption_short_en", "caption_long_ru", "caption_short_ru"):
        val = str(raw.get(field) or "").strip()
        if val:
            return val[:160] + ("…" if len(val) > 160 else "")
    extra = str(raw.get("extra_notes") or "").strip()
    if extra:
        return extra[:160] + ("…" if len(extra) > 160 else "")
    return REPURPOSE_FORMAT_LABELS.get(fmt, fmt)


def _ensure_caption_payload(raw: dict[str, Any], *, fmt: str) -> dict[str, str]:
    fb = REPURPOSE_FORMAT_LABELS.get(fmt, fmt)[:120]
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


def _heuristic_outputs(
    *,
    client: Client,
    formats: list[str],
    source_label: str,
) -> list[dict[str, Any]]:
    company = client.company_name
    outputs: list[dict[str, Any]] = []
    for fmt in formats:
        label = REPURPOSE_FORMAT_LABELS.get(fmt, fmt)
        base = f"{label} repurposed from {source_label} — {company}."
        extra = ""
        if fmt == "short_video_script":
            extra = f"Hook: Discover {company}\nScene 1: Product showcase\nScene 2: Benefits\nCTA: Contact us"
        elif fmt == "carousel_post":
            extra = f"Slide 1: {company}\nSlide 2: Key benefit\nSlide 3: Product highlight\nSlide 4: CTA"
        elif fmt == "distributor_recruitment_post":
            base = f"Join {company} as a distributor. Export-ready products, reliable supply, partner support."
        outputs.append({
            "output_format": fmt,
            "caption_short_ru": base[:150],
            "caption_short_uz": base[:150],
            "caption_short_en": base[:150],
            "caption_long_ru": base[:400],
            "caption_long_uz": base[:400],
            "caption_long_en": base[:400],
            "hashtags": f"#{company.replace(' ', '')} #B2B",
            "extra_notes": extra,
        })
    return outputs


def _heuristic_suggestions(*, assets: list[MediaAsset], source_content: ContentItem | None) -> list[dict[str, Any]]:
    has_video = any(a.file_type == "video" for a in assets)
    has_image = any(a.file_type == "image" for a in assets)
    if source_content and source_content.media_file_id:
        has_video = has_video or (getattr(source_content, "media_file_type", None) == "video")

    suggestions: list[dict[str, Any]] = []
    if has_video:
        suggestions.append({
            "output_format": "short_video_script",
            "rationale": "Video source is ideal for short-form reel/TikTok scripts.",
            "priority": 1,
        })
        suggestions.append({
            "output_format": "instagram_post",
            "rationale": "Repurpose video key message as an Instagram caption.",
            "priority": 2,
        })
    if has_image:
        suggestions.append({
            "output_format": "instagram_post",
            "rationale": "Visual asset fits Instagram feed posts.",
            "priority": 1 if not has_video else 3,
        })
        suggestions.append({
            "output_format": "carousel_post",
            "rationale": "Image collections work well as multi-slide carousels.",
            "priority": 2,
        })
    suggestions.extend([
        {
            "output_format": "linkedin_post",
            "rationale": "Professional B2B angle for export and distributor audiences.",
            "priority": 3,
        },
        {
            "output_format": "telegram_post",
            "rationale": "Concise channel update for partner and buyer groups.",
            "priority": 4,
        },
        {
            "output_format": "distributor_recruitment_post",
            "rationale": "Recruitment CTA aligns with partner network growth.",
            "priority": 5,
        },
    ])
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for s in sorted(suggestions, key=lambda x: x["priority"]):
        fmt = s["output_format"]
        if fmt in seen:
            continue
        seen.add(fmt)
        deduped.append(s)
    return deduped[:5]


async def _resolve_source(
    db: AsyncSession,
    *,
    client_id: UUID,
    source_type: str,
    source_id: UUID,
) -> _ResolvedSource:
    if source_type == "media_asset":
        r = await db.execute(
            select(MediaAsset)
            .options(selectinload(MediaAsset.media_file))
            .where(MediaAsset.id == source_id, MediaAsset.client_id == client_id)
        )
        asset = r.scalar_one_or_none()
        if not asset:
            raise HTTPException(status_code=404, detail="Media asset not found")
        campaign = None
        if asset.campaign_id:
            cr = await db.execute(select(Campaign).where(Campaign.id == asset.campaign_id))
            campaign = cr.scalar_one_or_none()
        return _ResolvedSource(
            source_type=source_type,
            source_id=source_id,
            client_id=client_id,
            campaign=campaign,
            assets=[asset],
            source_content=None,
            media_file_id=asset.media_file_id,
            parent_content_id=None,
            parent_media_asset_id=asset.id,
        )

    if source_type == "content_item":
        r = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.media_file))
            .where(ContentItem.id == source_id, ContentItem.client_id == client_id)
        )
        item = r.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Content item not found")
        campaign = None
        if item.campaign_id:
            cr = await db.execute(select(Campaign).where(Campaign.id == item.campaign_id))
            campaign = cr.scalar_one_or_none()
        assets: list[MediaAsset] = []
        parent_media_id: UUID | None = None
        if item.media_file_id:
            ar = await db.execute(
                select(MediaAsset)
                .options(selectinload(MediaAsset.media_file))
                .where(MediaAsset.media_file_id == item.media_file_id, MediaAsset.client_id == client_id)
            )
            linked = ar.scalar_one_or_none()
            if linked:
                assets = [linked]
                parent_media_id = linked.id
        return _ResolvedSource(
            source_type=source_type,
            source_id=source_id,
            client_id=client_id,
            campaign=campaign,
            assets=assets,
            source_content=item,
            media_file_id=item.media_file_id,
            parent_content_id=item.id,
            parent_media_asset_id=parent_media_id,
        )

    if source_type == "campaign":
        cr = await db.execute(select(Campaign).where(Campaign.id == source_id))
        campaign = cr.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if campaign.client_id != client_id:
            raise HTTPException(status_code=400, detail="Campaign belongs to a different client")
        ar = await db.execute(
            select(MediaAsset)
            .options(selectinload(MediaAsset.media_file))
            .where(MediaAsset.campaign_id == campaign.id, MediaAsset.client_id == client_id)
            .order_by(MediaAsset.created_at)
        )
        assets = list(ar.scalars().all())
        parent_media_id = assets[0].id if len(assets) == 1 else None
        media_file_id = assets[0].media_file_id if assets else None
        return _ResolvedSource(
            source_type=source_type,
            source_id=source_id,
            client_id=client_id,
            campaign=campaign,
            assets=assets,
            source_content=None,
            media_file_id=media_file_id,
            parent_content_id=None,
            parent_media_asset_id=parent_media_id,
        )

    raise HTTPException(status_code=400, detail="Invalid source_type")


async def _build_context_block(
    db: AsyncSession,
    *,
    client: Client,
    resolved: _ResolvedSource,
) -> str:
    kb = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, max_chars=3500, context="content_repurpose",
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

    asset_lines = []
    for a in resolved.assets:
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
        f"SOURCE TYPE: {resolved.source_type}",
    ]
    if resolved.campaign:
        parts.extend([
            f"CAMPAIGN: {resolved.campaign.name}",
            f"CAMPAIGN OBJECTIVE: {resolved.campaign.objective or '—'}",
            f"CAMPAIGN DESCRIPTION: {resolved.campaign.description or '—'}",
        ])
    if brand.get("business_description"):
        parts.append(f"BRAND: {brand['business_description'][:400]}")
    if resolved.source_content:
        sc = resolved.source_content
        parts.append("EXISTING CONTENT CONTEXT:")
        for field in (
            "caption_long_en", "caption_long_ru", "caption_short_en",
            "caption_short_ru", "hashtags", "internal_notes",
        ):
            val = getattr(sc, field, None)
            if val:
                parts.append(f"  {field}: {str(val)[:500]}")
        parts.append(f"  platforms: {', '.join(sc.platforms or [])}")
        parts.append(f"  status: {sc.status}")
    if asset_lines:
        parts.append("MEDIA ASSETS:\n" + "\n".join(asset_lines))
    elif resolved.source_type == "campaign":
        parts.append("MEDIA ASSETS: (campaign bundle — no uploaded assets yet; use campaign brief)")
    if product_lines:
        parts.append("PRODUCT CATALOG:\n" + "\n".join(product_lines))
    if kb:
        parts.append(kb)
    return "\n\n".join(parts)


def _source_label(resolved: _ResolvedSource) -> str:
    if resolved.source_type == "media_asset" and resolved.assets:
        return resolved.assets[0].title
    if resolved.source_type == "content_item" and resolved.source_content:
        preview = (
            resolved.source_content.caption_short_en
            or resolved.source_content.caption_short_ru
            or "content item"
        )
        return str(preview)[:80]
    if resolved.campaign:
        return f"campaign «{resolved.campaign.name}»"
    return resolved.source_type


class ContentRepurposeService:
    @staticmethod
    async def generate(
        db: AsyncSession,
        data: ContentRepurposeGenerateRequest,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, data.client_id)
        formats = _normalize_formats(list(data.output_formats))
        if not formats:
            raise HTTPException(status_code=400, detail="No valid output formats")

        resolved = await _resolve_source(
            db,
            client_id=data.client_id,
            source_type=data.source_type,
            source_id=data.source_id,
        )
        context_block = await _build_context_block(db, client=client, resolved=resolved)
        source_label = _source_label(resolved)

        demo_mode = False
        raw_outputs: list[dict[str, Any]] = []
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            format_list = ", ".join(formats)
            user_prompt = f"""\
Repurpose the source into these output formats (one output object each): {format_list}

{context_block}
"""
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _GENERATE_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_tokens=5000,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            raw = parsed.get("outputs") or []
            if not isinstance(raw, list) or not raw:
                raise ValueError("empty outputs")
            raw_outputs = [o for o in raw if isinstance(o, dict)]
        except Exception as exc:
            demo_mode = True
            logger.info("[Repurpose Engine] generate fallback: %s", exc)
            raw_outputs = _heuristic_outputs(client=client, formats=formats, source_label=source_label)

        by_format: dict[str, dict[str, Any]] = {}
        for raw in raw_outputs:
            fmt = str(raw.get("output_format") or "").strip()
            if fmt in formats and fmt not in by_format:
                by_format[fmt] = raw

        for fmt in formats:
            if fmt not in by_format:
                by_format[fmt] = _heuristic_outputs(
                    client=client, formats=[fmt], source_label=source_label,
                )[0]

        created: list[dict[str, Any]] = []
        asset = resolved.assets[0] if resolved.assets else None

        for fmt in formats:
            raw = by_format[fmt]
            platforms = [p for p in FORMAT_PLATFORMS.get(fmt, ["instagram"]) if p in PLATFORMS]
            if not platforms:
                platforms = ["instagram"]

            extra = str(raw.get("extra_notes") or "").strip()
            notes = (
                f"{REPURPOSE_MARKER}\n"
                f"Format: {REPURPOSE_FORMAT_LABELS.get(fmt, fmt)}\n"
                f"Source type: {resolved.source_type}\n"
                f"Source: {source_label}\n"
            )
            if extra:
                notes += f"\n{extra}\n"

            content = await ContentService.create(
                db,
                ContentCreate(
                    client_id=client.id,
                    media_file_id=resolved.media_file_id,
                    platforms=platforms,
                    internal_notes=notes,
                    source=REPURPOSE_SOURCE,
                ),
            )
            content_row = await ContentService.get(db, content.id)
            if resolved.campaign:
                content_row.campaign_id = resolved.campaign.id
            content_row.parent_content_id = resolved.parent_content_id
            content_row.parent_media_asset_id = resolved.parent_media_asset_id
            content_row.status = "draft"

            payload = _ensure_caption_payload(raw, fmt=fmt)
            generated = GeneratedContent(**payload)
            await ContentService.apply_generated(db, content.id, generated)
            content_row = await ContentService.get(db, content.id)
            content_row.status = "draft"
            content_row.parent_content_id = resolved.parent_content_id
            content_row.parent_media_asset_id = resolved.parent_media_asset_id
            await db.commit()

            media_url = None
            if content_row.media_file:
                media_url = storage.get_url(content_row.media_file.storage_path)

            created.append({
                "content_id": content_row.id,
                "output_format": fmt,
                "format_label": REPURPOSE_FORMAT_LABELS.get(fmt, fmt),
                "preview": _preview_from_payload({**raw, **payload}, fmt=fmt),
                "platforms": platforms,
                "media_asset_id": asset.id if asset else None,
                "media_url": media_url,
                "parent_content_id": resolved.parent_content_id,
                "parent_media_asset_id": resolved.parent_media_asset_id,
                "status": "draft",
            })

        logger.info(
            "[Repurpose Engine] generated: client=%s source=%s/%s formats=%s count=%s demo=%s",
            client.id, data.source_type, data.source_id, formats, len(created), demo_mode,
        )
        return {
            "drafts": created,
            "generated_count": len(created),
            "demo_mode": demo_mode,
        }

    @staticmethod
    async def suggestions(
        db: AsyncSession,
        params: ContentRepurposeSuggestionsRequest,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, params.client_id)
        resolved = await _resolve_source(
            db,
            client_id=params.client_id,
            source_type=params.source_type,
            source_id=params.source_id,
        )
        suggestions = [
            {
                "output_format": s["output_format"],
                "format_label": REPURPOSE_FORMAT_LABELS.get(s["output_format"], s["output_format"]),
                "rationale": s["rationale"],
                "priority": s["priority"],
            }
            for s in _heuristic_suggestions(
                assets=resolved.assets,
                source_content=resolved.source_content,
            )
        ]
        suggestions.sort(key=lambda x: x.get("priority", 99))
        logger.info(
            "[Repurpose Suggestion] client=%s source=%s/%s count=%s (heuristic)",
            client.id, params.source_type, params.source_id, len(suggestions),
        )
        return {"suggestions": suggestions[:5], "demo_mode": True}
