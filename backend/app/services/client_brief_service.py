"""Client Brief Intake — submit, AI plan, convert to content tasks."""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.client_brief import ClientBrief
from app.schemas.client_brief import (
    BriefContentPlan,
    BriefPlanItem,
    BriefPlanItemCaptions,
    ClientBriefCreate,
)
from app.schemas.content import ContentCreate, ContentUpdate, PLATFORMS
from app.schemas.operator_task import OperatorTaskCreate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_service import ClientService
from app.services.content_service import ContentService
from app.services.operator_task_service import OperatorTaskService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

BRIEF_STATUSES = frozenset({"new", "reviewing", "changes_requested", "approved", "converted"})
BRIEF_LANGUAGES = frozenset({"zh", "en", "ru", "uz"})
BRIEF_MEDIA_TYPES = frozenset({"image", "carousel", "reel", "story", "short_video"})
BRIEF_AI_MARKER = "[Client Brief AI]"
PLAN_ITEM_COUNT = 7

_LEGACY_STATUS_MAP = {
    "submitted": "new",
    "plan_generated": "reviewing",
    "tasks_created": "converted",
}

_GENERATE_PLAN_SYSTEM = """\
You are an SMM content strategist. Create a practical 7-post content plan from a client brief.
Return ONLY JSON:
{
  "summary": "2-3 sentence executive summary",
  "plan_status": "draft",
  "items": [
    {
      "theme": "post theme title",
      "goal": "what this post should achieve",
      "platform": "instagram",
      "media_type": "image|carousel|reel|story|short_video",
      "captions": {
        "ru": "full Russian caption for the post",
        "uz": "full Uzbek caption for the post",
        "en": "full English caption for the post",
        "zh": "full Chinese caption for the post"
      },
      "hashtags": "#tag1 #tag2 #tag3",
      "cta": "call to action text",
      "priority": "high|medium|low"
    }
  ],
  "source": "ai"
}

Rules:
- Exactly 7 content items — varied themes across the campaign
- platform: one recommended platform per post from instagram, facebook, tiktok, telegram, linkedin
- media_type: image, carousel, reel, story, or short_video — match platform best practices
- Write captions in RU, UZ, EN, ZH for every item (natural, platform-appropriate tone)
- Include relevant hashtags and a clear CTA per post
- Match target market and campaign goal
- Use product details from the brief
"""


def _normalize_status(raw: str | None) -> str:
    if not raw:
        return "new"
    if raw in BRIEF_STATUSES:
        return raw
    return _LEGACY_STATUS_MAP.get(raw, "new")


def _normalize_languages(raw: Any, fallback: str = "en") -> list[str]:
    if not isinstance(raw, list):
        return [fallback] if fallback in BRIEF_LANGUAGES else ["en"]
    out: list[str] = []
    for lang in raw:
        key = str(lang).lower().strip()
        if key in BRIEF_LANGUAGES and key not in out:
            out.append(key)
    if out:
        return out
    fb = fallback if fallback in BRIEF_LANGUAGES else "en"
    return [fb]


def _normalize_platforms(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        if isinstance(raw, str) and raw.strip():
            key = raw.lower().strip()
            return [key] if key in PLATFORMS else ["instagram"]
        return ["instagram"]
    out: list[str] = []
    for p in raw:
        key = str(p).lower().strip()
        if key in PLATFORMS and key not in out:
            out.append(key)
    return out or ["instagram"]


def _normalize_media_type(raw: Any) -> str:
    key = str(raw or "image").lower().strip()
    if key in BRIEF_MEDIA_TYPES:
        return key
    if key == "video":
        return "short_video"
    return "image"


def _normalize_captions(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {"ru": "", "uz": "", "en": "", "zh": ""}
    return {
        "ru": str(raw.get("ru") or "").strip(),
        "uz": str(raw.get("uz") or "").strip(),
        "en": str(raw.get("en") or "").strip(),
        "zh": str(raw.get("zh") or "").strip(),
    }


def _normalize_plan_item(entry: dict[str, Any], brief: ClientBrief, index: int) -> dict[str, Any]:
    platforms = _normalize_platforms(entry.get("platform") or entry.get("platforms") or brief.desired_platforms)
    platform = platforms[0]
    priority = str(entry.get("priority") or "medium").lower()
    if priority not in {"high", "medium", "low"}:
        priority = "medium"
    theme = str(entry.get("theme") or f"{brief.product_name} — post {index + 1}").strip()
    goal = str(entry.get("goal") or brief.campaign_goal).strip()
    return {
        "theme": theme,
        "goal": goal,
        "platform": platform,
        "media_type": _normalize_media_type(entry.get("media_type") or entry.get("content_type")),
        "captions": _normalize_captions(entry.get("captions")),
        "hashtags": str(entry.get("hashtags") or "").strip(),
        "cta": str(entry.get("cta") or "").strip(),
        "priority": priority,
    }


def _normalize_plan(raw: dict[str, Any], brief: ClientBrief, *, source: str = "ai") -> dict[str, Any]:
    items_raw = raw.get("items") if isinstance(raw.get("items"), list) else []
    items = [
        _normalize_plan_item(entry, brief, i)
        for i, entry in enumerate(items_raw)
        if isinstance(entry, dict)
    ]
    while len(items) < PLAN_ITEM_COUNT:
        items.append(_normalize_plan_item({}, brief, len(items)))
    items = items[:PLAN_ITEM_COUNT]
    plan_status = raw.get("plan_status") or "draft"
    if plan_status not in {"draft", "approved"}:
        plan_status = "draft"
    return {
        "summary": str(raw.get("summary") or f"Content plan for {brief.product_name}").strip(),
        "plan_status": plan_status,
        "items": items,
        "source": source,
    }


def _parse_plan(brief: ClientBrief) -> dict[str, Any] | None:
    if not brief.ai_content_plan:
        return None
    try:
        raw = json.loads(brief.ai_content_plan)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    return _normalize_plan(raw, brief, source=str(raw.get("source") or "ai"))


def _store_plan(brief: ClientBrief, plan: dict[str, Any]) -> None:
    brief.ai_content_plan = json.dumps(plan, ensure_ascii=False, indent=2)


def _serialize(brief: ClientBrief) -> dict[str, Any]:
    company = brief.client.company_name if brief.client else None
    tenant_name = brief.tenant.company_name if brief.tenant else None
    languages = _normalize_languages(brief.languages, brief.language or "en")
    return {
        "id": brief.id,
        "client_id": brief.client_id,
        "company_name": company,
        "tenant_id": brief.tenant_id,
        "tenant_name": tenant_name,
        "product_name": brief.product_name,
        "product_description": brief.product_description,
        "target_market": brief.target_market,
        "campaign_goal": brief.campaign_goal,
        "language": languages[0],
        "languages": languages,
        "desired_platforms": brief.desired_platforms or [],
        "media_urls": brief.media_urls or [],
        "notes": brief.notes,
        "status": _normalize_status(brief.status),
        "ai_content_plan": brief.ai_content_plan,
        "admin_feedback": brief.admin_feedback,
        "submitted_by": brief.submitted_by,
        "created_at": brief.created_at,
        "updated_at": brief.updated_at,
    }


def _heuristic_plan(brief: ClientBrief, client: Client) -> dict[str, Any]:
    platforms = _normalize_platforms(brief.desired_platforms)
    primary = platforms[0]
    themes = [
        ("brand introduction", "Introduce the brand and core value proposition", "image", "high"),
        ("key benefits", brief.campaign_goal, "carousel", "high"),
        ("behind the scenes", "Build authenticity and trust", "reel", "medium"),
        ("customer story", "Social proof and use case", "short_video", "medium"),
        ("product spotlight", "Highlight product features", "carousel", "high"),
        ("tips & education", "Provide value to the audience", "image", "medium"),
        ("call to action", "Drive engagement and inquiries", "story", "high"),
    ]
    company = client.company_name or brief.product_name
    items: list[dict[str, Any]] = []
    for i, (theme_suffix, goal, media_type, priority) in enumerate(themes):
        theme = f"{brief.product_name} — {theme_suffix}"
        platform = platforms[i % len(platforms)]
        items.append({
            "theme": theme,
            "goal": goal,
            "platform": platform,
            "media_type": media_type,
            "captions": {
                "ru": f"{company}: {theme}. {goal}. Узнайте больше!",
                "uz": f"{company}: {theme}. {goal}. Batafsil!",
                "en": f"{company}: {theme}. {goal}. Learn more!",
                "zh": f"{company}：{theme}。{goal}。了解更多！",
            },
            "hashtags": f"#{brief.product_name.replace(' ', '')} #{primary} #marketing",
            "cta": "Contact us to learn more",
            "priority": priority,
        })
    return _normalize_plan({
        "summary": (
            f"Content plan for {brief.product_name} targeting {brief.target_market}. "
            f"Goal: {brief.campaign_goal}. Seven posts across {', '.join(platforms)}."
        ),
        "plan_status": "draft",
        "items": items,
        "source": "fallback",
    }, brief, source="fallback")


async def _ai_plan(brief: ClientBrief, client: Client) -> dict[str, Any]:
    _validate_api_key()
    openai = get_openai()
    profile = brand_profile_from_client(client)
    languages = _normalize_languages(brief.languages, brief.language or "en")
    user_block = json.dumps({
        "product_name": brief.product_name,
        "product_description": brief.product_description,
        "target_market": brief.target_market,
        "campaign_goal": brief.campaign_goal,
        "languages": languages,
        "desired_platforms": brief.desired_platforms or [],
        "notes": brief.notes,
        "media_assets": brief.media_urls or [],
        "client_profile": profile,
        "required_item_count": PLAN_ITEM_COUNT,
    }, ensure_ascii=False)

    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _GENERATE_PLAN_SYSTEM},
            {"role": "user", "content": user_block},
        ],
        temperature=0.4,
        max_tokens=6000,
        response_format={"type": "json_object"},
    )
    raw = _extract_json(response.choices[0].message.content or "{}")
    return _normalize_plan(raw, brief, source="ai")


class ClientBriefService:
    @staticmethod
    async def _load(db: AsyncSession, brief_id: UUID) -> ClientBrief:
        result = await db.execute(
            select(ClientBrief)
            .options(
                selectinload(ClientBrief.client),
                selectinload(ClientBrief.tenant),
            )
            .where(ClientBrief.id == brief_id),
        )
        brief = result.scalar_one_or_none()
        if not brief:
            raise HTTPException(status_code=404, detail="Client brief not found")
        return brief

    @staticmethod
    async def _resolve_client_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
        client_id: UUID | None,
    ) -> Client:
        if client_id:
            await TenantService.validate_client_belongs_to_tenant(db, tenant_id, client_id)
            return await ClientService.get(db, client_id)
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        if not client_ids:
            raise HTTPException(status_code=400, detail="No client linked to this tenant")
        return await ClientService.get(db, client_ids[0])

    @staticmethod
    async def submit(
        db: AsyncSession,
        data: ClientBriefCreate,
        *,
        tenant_id: UUID,
        submitted_by: str | None = None,
    ) -> dict[str, Any]:
        client = await ClientBriefService._resolve_client_for_tenant(
            db, tenant_id, data.client_id,
        )
        languages = _normalize_languages(
            data.languages or [data.language],
            data.language,
        )
        brief = ClientBrief(
            client_id=client.id,
            tenant_id=tenant_id,
            product_name=data.product_name.strip(),
            product_description=(data.product_description or "").strip() or None,
            target_market=data.target_market.strip(),
            campaign_goal=data.campaign_goal,
            language=languages[0],
            languages=languages,
            desired_platforms=_normalize_platforms(data.desired_platforms),
            media_urls=[u.strip() for u in data.media_urls if u and u.strip()],
            notes=(data.notes or "").strip() or None,
            status="new",
            submitted_by=submitted_by,
        )
        db.add(brief)
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief.id))

    @staticmethod
    async def list_briefs(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        query = select(ClientBrief).options(
            selectinload(ClientBrief.client),
            selectinload(ClientBrief.tenant),
        )
        count_q = select(func.count()).select_from(ClientBrief)
        if tenant_id:
            query = query.where(ClientBrief.tenant_id == tenant_id)
            count_q = count_q.where(ClientBrief.tenant_id == tenant_id)
        total = (await db.execute(count_q)).scalar_one()
        result = await db.execute(
            query.order_by(ClientBrief.created_at.desc()).offset(skip).limit(limit),
        )
        items = [_serialize(b) for b in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def get_brief(db: AsyncSession, brief_id: UUID) -> dict[str, Any]:
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def mark_reviewed(db: AsyncSession, brief_id: UUID) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        status = _normalize_status(brief.status)
        if status == "converted":
            raise HTTPException(status_code=400, detail="Brief already converted to tasks")
        brief.status = "reviewing"
        brief.admin_feedback = None
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def approve_brief(db: AsyncSession, brief_id: UUID) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        status = _normalize_status(brief.status)
        if status == "converted":
            raise HTTPException(status_code=400, detail="Brief already converted to tasks")
        if status not in {"new", "reviewing", "changes_requested"}:
            raise HTTPException(status_code=400, detail=f"Cannot approve brief in status '{status}'")
        brief.status = "reviewing"
        brief.admin_feedback = None
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def request_changes(
        db: AsyncSession,
        brief_id: UUID,
        *,
        feedback: str,
    ) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        status = _normalize_status(brief.status)
        if status == "converted":
            raise HTTPException(status_code=400, detail="Brief already converted to tasks")
        brief.status = "changes_requested"
        brief.admin_feedback = feedback.strip()
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def generate_plan(db: AsyncSession, brief_id: UUID) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        status = _normalize_status(brief.status)
        if status == "converted":
            raise HTTPException(status_code=400, detail="Brief already converted to tasks")
        if status in {"new", "changes_requested"}:
            raise HTTPException(
                status_code=400,
                detail="Approve the brief before generating a content plan",
            )
        client = brief.client or await ClientService.get(db, brief.client_id)
        try:
            plan = await _ai_plan(brief, client)
        except Exception as exc:
            logger.warning("[Client Brief] AI plan failed brief=%s error=%s", brief_id, exc)
            plan = _heuristic_plan(brief, client)

        plan["plan_status"] = "draft"
        _store_plan(brief, plan)
        brief.status = "reviewing"
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def update_plan(db: AsyncSession, brief_id: UUID, plan: BriefContentPlan) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        status = _normalize_status(brief.status)
        if status == "converted":
            raise HTTPException(status_code=400, detail="Brief already converted to tasks")
        normalized = _normalize_plan(plan.model_dump(), brief, source="manual")
        normalized["plan_status"] = "draft"
        _store_plan(brief, normalized)
        if status == "approved":
            brief.status = "reviewing"
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def approve_plan(db: AsyncSession, brief_id: UUID) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        status = _normalize_status(brief.status)
        if status == "converted":
            raise HTTPException(status_code=400, detail="Brief already converted to tasks")
        plan = _parse_plan(brief)
        if not plan or not plan.get("items"):
            raise HTTPException(status_code=400, detail="Generate a content plan first")
        plan["plan_status"] = "approved"
        _store_plan(brief, plan)
        brief.status = "approved"
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def add_media(
        db: AsyncSession,
        brief_id: UUID,
        *,
        tenant_id: UUID,
        media_urls: list[str],
    ) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        ClientBriefService.assert_tenant_can_access(brief, tenant_id)
        status = _normalize_status(brief.status)
        if status != "changes_requested":
            raise HTTPException(
                status_code=400,
                detail="Additional files can only be uploaded when changes are requested",
            )
        existing = list(brief.media_urls or [])
        for url in media_urls:
            cleaned = url.strip()
            if cleaned and cleaned not in existing:
                existing.append(cleaned)
        brief.media_urls = existing
        brief.status = "reviewing"
        await db.commit()
        return _serialize(await ClientBriefService._load(db, brief_id))

    @staticmethod
    async def convert_to_tasks(db: AsyncSession, brief_id: UUID) -> dict[str, Any]:
        brief = await ClientBriefService._load(db, brief_id)
        status = _normalize_status(brief.status)
        if status != "approved":
            raise HTTPException(
                status_code=400,
                detail="Approve the content plan before creating tasks",
            )
        plan = _parse_plan(brief)
        if not plan:
            raise HTTPException(status_code=400, detail="Generate a content plan first")
        if plan.get("plan_status") != "approved":
            raise HTTPException(status_code=400, detail="Approve the content plan first")

        items = plan.get("items") or []
        if not items:
            raise HTTPException(status_code=400, detail="Content plan has no items")

        tasks_created = 0
        content_created = 0

        for entry in items:
            if not isinstance(entry, dict):
                continue
            theme = str(entry.get("theme") or brief.product_name).strip()
            goal = str(entry.get("goal") or brief.campaign_goal).strip()
            platform = _normalize_platforms(entry.get("platform"))[0]
            media_type = _normalize_media_type(entry.get("media_type"))
            captions = _normalize_captions(entry.get("captions"))
            hashtags = str(entry.get("hashtags") or "").strip()
            cta = str(entry.get("cta") or "").strip()
            priority = str(entry.get("priority") or "medium").lower()
            if priority not in {"high", "medium", "low"}:
                priority = "medium"

            zh_note = f"Caption ZH: {captions['zh']}" if captions["zh"] else ""
            content = await ContentService.create(
                db,
                ContentCreate(
                    client_id=brief.client_id,
                    platforms=[platform],
                    internal_notes=(
                        f"{BRIEF_AI_MARKER}\n"
                        f"From brief: {brief.product_name}\n"
                        f"Brief ID: {brief.id}\n"
                        f"Theme: {theme}\n"
                        f"Goal: {goal}\n"
                        f"Media type: {media_type}\n"
                        f"Target market: {brief.target_market}\n"
                        f"CTA: {cta}\n"
                        f"{zh_note}"
                    ).strip(),
                    source="client_brief",
                ),
            )
            await ContentService.update(
                db,
                content.id,
                ContentUpdate(
                    caption_short_ru=captions["ru"][:500] or None,
                    caption_short_uz=captions["uz"][:500] or None,
                    caption_short_en=captions["en"][:500] or None,
                    caption_long_ru=captions["ru"] or None,
                    caption_long_uz=captions["uz"] or None,
                    caption_long_en=captions["en"] or None,
                    hashtags=hashtags or None,
                ),
            )
            content_created += 1

            await OperatorTaskService.create_task(
                db,
                OperatorTaskCreate(
                    client_id=brief.client_id,
                    source_type="client_brief",
                    source_id=content.id,
                    title=f"Content: {theme[:200]}",
                    description=f"{goal}\nPlatform: {platform} · {media_type}",
                    priority=priority,  # type: ignore[arg-type]
                    created_by="admin",
                    linked_content_id=content.id,
                ),
            )
            tasks_created += 1

        brief.status = "converted"
        await db.commit()
        updated = await ClientBriefService._load(db, brief_id)
        return {
            "brief": _serialize(updated),
            "tasks_created": tasks_created,
            "content_items_created": content_created,
        }

    @staticmethod
    def assert_tenant_can_access(brief: ClientBrief, tenant_id: UUID) -> None:
        if brief.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Client brief not found")
