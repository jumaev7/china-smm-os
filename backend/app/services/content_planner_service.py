"""AI Content Planner — monthly plans from client brand profile."""
from __future__ import annotations

import calendar
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.content_plan import ContentPlan, ContentPlanItem
from app.schemas.content import ContentCreate, PLATFORMS
from app.schemas.content_planner import ContentPlanGenerateRequest, ContentPlanUpdate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.brand_profile import brand_profile_from_client
from app.services.client_service import ClientService
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

CONTENT_TYPES = frozenset({"image", "video", "carousel", "story"})
PLAN_STATUSES = frozenset({"draft", "approved"})
CONTENT_PLAN_SOURCE = "content_plan"
CONTENT_PLAN_AI_MARKER = "[Content Plan AI]"
ITEM_STATUSES = frozenset({"planned", "draft_created"})

_CATEGORY_THEMES: dict[str, list[str]] = {
    "restaurant": ["Menu spotlight", "Chef's special", "Behind the kitchen", "Customer favorites", "Seasonal dish"],
    "retail": ["New arrivals", "Product highlight", "Customer review", "Sale preview", "Store atmosphere"],
    "beauty": ["Before & after", "Service showcase", "Tips & care", "Team introduction", "Promotion"],
    "construction": ["Project progress", "Finished work", "Materials quality", "Team on site", "Client testimonial"],
    "logistics": ["Fleet & delivery", "Route efficiency", "Warehouse ops", "Customer success", "Safety first"],
    "technology": ["Product feature", "Use case story", "Team update", "Industry insight", "Tutorial tip"],
    "education": ["Student success", "Course highlight", "Learning tip", "Campus life", "Enrollment reminder"],
    "healthcare": ["Health tip", "Service overview", "Patient care", "Team credentials", "Wellness advice"],
    "real_estate": ["Property showcase", "Neighborhood guide", "Market update", "Client story", "Virtual tour"],
    "other": ["Brand story", "Product value", "Customer quote", "Team culture", "Industry news"],
}

_CONTENT_TYPE_ROTATION = ["image", "carousel", "video", "image", "story", "carousel", "image", "video"]

_GENERATE_SYSTEM = """\
You are an SMM content strategist. Create a monthly content plan for a client.
Do NOT include publishing automation — admin creates and approves content manually.

Return ONLY JSON:
{
  "title": "Plan title for the month",
  "items": [
    {
      "planned_date": "YYYY-MM-DD",
      "theme": "post theme title",
      "goal": "what this post should achieve (1-2 sentences)",
      "platform_suggestions": ["instagram", "telegram"],
      "content_type": "image|video|carousel|story"
    }
  ]
}

Rules:
- Spread posts across the month on varied weekdays
- Match client tone, category, and audience
- platform_suggestions from: instagram, facebook, tiktok, telegram, linkedin
- Mix content types appropriately
- Each item must have a distinct theme
"""


def _normalize_platforms(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return ["instagram"]
    out: list[str] = []
    for p in raw:
        key = str(p).lower().strip()
        if key in PLATFORMS and key not in out:
            out.append(key)
    return out or ["instagram"]


def _normalize_content_type(raw: Any, index: int) -> str:
    key = str(raw or "").lower().strip()
    if key in CONTENT_TYPES:
        return key
    return _CONTENT_TYPE_ROTATION[index % len(_CONTENT_TYPE_ROTATION)]


def _spread_dates(year: int, month: int, count: int) -> list[date]:
    last_day = calendar.monthrange(year, month)[1]
    candidates = [
        date(year, month, day)
        for day in range(1, last_day + 1)
        if date(year, month, day).weekday() < 5
    ]
    if not candidates:
        candidates = [date(year, month, d) for d in range(1, last_day + 1)]
    if count >= len(candidates):
        return candidates[:count]
    step = len(candidates) / count
    return [candidates[int(i * step)] for i in range(count)]


def _heuristic_plan(
    *,
    client: Client,
    year: int,
    month: int,
    posts_per_month: int,
) -> dict[str, Any]:
    themes = _CATEGORY_THEMES.get(
        client.business_category,
        _CATEGORY_THEMES["other"],
    )
    dates = _spread_dates(year, month, posts_per_month)
    month_name = date(year, month, 1).strftime("%B %Y")
    items: list[dict[str, Any]] = []

    for i, planned in enumerate(dates):
        theme = themes[i % len(themes)]
        ctype = _CONTENT_TYPE_ROTATION[i % len(_CONTENT_TYPE_ROTATION)]
        items.append({
            "planned_date": planned.isoformat(),
            "theme": theme,
            "goal": f"Engage {client.target_audience or 'audience'} and reinforce {client.company_name} brand presence.",
            "platform_suggestions": ["instagram", "telegram"],
            "content_type": ctype,
        })

    return {
        "title": f"{client.company_name} — {month_name} Content Plan",
        "items": items,
        "source": "fallback",
    }


async def _ai_plan(
    db: AsyncSession,
    *,
    client: Client,
    year: int,
    month: int,
    posts_per_month: int,
) -> dict[str, Any]:
    _validate_api_key()
    openai = get_openai()
    profile = brand_profile_from_client(client)
    month_name = date(year, month, 1).strftime("%B %Y")
    last_day = calendar.monthrange(year, month)[1]

    user_block = (
        f"CLIENT PROFILE:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
        f"MONTH: {month_name} ({year}-{month:02d}-01 to {year}-{month:02d}-{last_day})\n"
        f"POSTS NEEDED: {posts_per_month}\n"
        f"CATEGORY: {client.business_category}\n"
        f"CONTENT STYLE: {client.content_style}"
    )
    from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, context="content_planner",
    )
    if kb_block:
        user_block = f"{user_block}\n\n{kb_block}"
    response = await openai.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _GENERATE_SYSTEM},
            {"role": "user", "content": user_block},
        ],
        temperature=0.4,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    raw = _extract_json(response.choices[0].message.content or "{}")
    items_raw = raw.get("items") or []
    items: list[dict[str, Any]] = []
    fallback_dates = _spread_dates(year, month, posts_per_month)

    for i, row in enumerate(items_raw[:posts_per_month]):
        if not isinstance(row, dict):
            continue
        pd = row.get("planned_date")
        try:
            planned = date.fromisoformat(str(pd)[:10]) if pd else fallback_dates[i]
        except (ValueError, TypeError, IndexError):
            planned = fallback_dates[min(i, len(fallback_dates) - 1)]
        if planned.month != month or planned.year != year:
            planned = fallback_dates[min(i, len(fallback_dates) - 1)]

        items.append({
            "planned_date": planned.isoformat(),
            "theme": (row.get("theme") or f"Post {i + 1}")[:500],
            "goal": (row.get("goal") or "Brand engagement")[:1000],
            "platform_suggestions": _normalize_platforms(row.get("platform_suggestions")),
            "content_type": _normalize_content_type(row.get("content_type"), i),
        })

    while len(items) < posts_per_month:
        i = len(items)
        items.append({
            "planned_date": fallback_dates[i].isoformat(),
            "theme": _CATEGORY_THEMES.get(client.business_category, _CATEGORY_THEMES["other"])[i % 5],
            "goal": f"Support {client.company_name} monthly content rhythm.",
            "platform_suggestions": ["instagram"],
            "content_type": _CONTENT_TYPE_ROTATION[i % len(_CONTENT_TYPE_ROTATION)],
        })

    return {
        "title": (raw.get("title") or f"{client.company_name} — {month_name} Content Plan")[:255],
        "items": items,
        "source": "ai",
    }


def _parse_platforms_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return _normalize_platforms(data)
    except json.JSONDecodeError:
        pass
    return []


def _serialize_item(item: ContentPlanItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "planned_date": item.planned_date,
        "theme": item.theme,
        "goal": item.goal,
        "platform_suggestions": _parse_platforms_json(item.platform_suggestions_json),
        "content_type": item.content_type,
        "status": item.status,
        "linked_content_id": item.linked_content_id,
        "created_at": item.created_at,
    }


def _serialize_plan(plan: ContentPlan, company_name: str | None = None) -> dict[str, Any]:
    return {
        "id": plan.id,
        "client_id": plan.client_id,
        "company_name": company_name,
        "month": plan.month,
        "year": plan.year,
        "title": plan.title,
        "status": plan.status,
        "posts_per_month": plan.posts_per_month,
        "items": [_serialize_item(i) for i in (plan.items or [])],
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _plan_item_context_hint(
    *,
    plan: ContentPlan,
    item: ContentPlanItem,
    platforms: list[str],
) -> str:
    return (
        f"Monthly content plan: {plan.title}\n"
        f"Theme: {item.theme}\n"
        f"Goal: {item.goal}\n"
        f"Format: {item.content_type}\n"
        f"Platforms: {', '.join(platforms)}\n"
        f"Planned publish date: {item.planned_date.isoformat()}\n"
        "No media attached yet — write captions based on the plan brief and brand profile."
    )


def _plan_item_source_text(item: ContentPlanItem) -> str:
    return f"Theme: {item.theme}\nGoal: {item.goal}"


async def _generate_captions_for_plan_item(
    db: AsyncSession,
    *,
    client: Client,
    content_id: UUID,
    plan: ContentPlan,
    item: ContentPlanItem,
    platforms: list[str],
) -> tuple[bool, str | None]:
    from app.services.ai_service import generate_content
    from app.services.context_ai_service import build_context_signals

    content_row = await ContentService.get(db, content_id)
    source_text = _plan_item_source_text(item)
    context_hint = _plan_item_context_hint(plan=plan, item=item, platforms=platforms)
    brand_profile = brand_profile_from_client(client)
    from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
    kb_block = await ClientKnowledgeBaseService.build_prompt_block(
        db, client.id, context="content_planner_draft",
    )

    try:
        context_signals = await build_context_signals(
            db,
            client=client,
            item=content_row,
            source_text=source_text,
        )
        generated = await generate_content(
            company_name=client.company_name,
            business_category=client.business_category,
            content_style=client.content_style,
            source_language=client.source_language or "zh",
            source_text=source_text,
            context_hint=context_hint,
            client_notes=client.notes,
            brand_profile=brand_profile,
            context_signals=context_signals,
            knowledge_base_block=kb_block or None,
        )
        await ContentService.apply_generated(db, content_id, generated)
        content_row = await ContentService.get(db, content_id)
        notes = (content_row.internal_notes or "").rstrip()
        content_row.internal_notes = (
            f"{notes}\n{CONTENT_PLAN_AI_MARKER} Captions generated automatically."
        ).strip()
        await db.commit()
        logger.info("[Content Planner] AI captions: item=%s content=%s", item.id, content_id)
        return True, None
    except Exception as exc:
        logger.warning(
            "[Content Planner] AI caption gen failed: item=%s content=%s error=%s",
            item.id,
            content_id,
            exc,
        )
        content_row = await ContentService.get(db, content_id)
        notes = (content_row.internal_notes or "").rstrip()
        content_row.internal_notes = f"{notes}\nAI generation failed: {exc}".strip()
        await db.commit()
        return False, str(exc)


class ContentPlannerService:
    @staticmethod
    async def _load_plan(db: AsyncSession, plan_id: UUID) -> ContentPlan:
        result = await db.execute(
            select(ContentPlan)
            .options(
                selectinload(ContentPlan.items),
                selectinload(ContentPlan.client),
            )
            .where(ContentPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()
        if not plan:
            raise HTTPException(status_code=404, detail="Content plan not found")
        return plan

    @staticmethod
    async def get_plan(
        db: AsyncSession,
        plan_id: UUID,
    ) -> dict[str, Any]:
        plan = await ContentPlannerService._load_plan(db, plan_id)
        name = plan.client.company_name if plan.client else None
        return _serialize_plan(plan, name)

    @staticmethod
    async def find_plan(
        db: AsyncSession,
        *,
        client_id: UUID,
        month: int,
        year: int,
    ) -> dict[str, Any] | None:
        result = await db.execute(
            select(ContentPlan)
            .options(
                selectinload(ContentPlan.items),
                selectinload(ContentPlan.client),
            )
            .where(
                ContentPlan.client_id == client_id,
                ContentPlan.month == month,
                ContentPlan.year == year,
            )
        )
        plan = result.scalar_one_or_none()
        if not plan:
            return None
        name = plan.client.company_name if plan.client else None
        return _serialize_plan(plan, name)

    @staticmethod
    async def generate(
        db: AsyncSession,
        data: ContentPlanGenerateRequest,
    ) -> dict[str, Any]:
        client = await ClientService.get(db, data.client_id)

        if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
            generated = _heuristic_plan(
                client=client,
                year=data.year,
                month=data.month,
                posts_per_month=data.posts_per_month,
            )
            logger.info("[Content Planner] fallback: client=%s month=%s/%s", client.id, data.month, data.year)
        else:
            try:
                generated = await _ai_plan(
                    db,
                    client=client,
                    year=data.year,
                    month=data.month,
                    posts_per_month=data.posts_per_month,
                )
                logger.info("[Content Planner] generated: client=%s month=%s/%s source=ai", client.id, data.month, data.year)
            except Exception as exc:
                logger.warning("[Content Planner] fallback: client=%s error=%s", client.id, exc)
                generated = _heuristic_plan(
                    client=client,
                    year=data.year,
                    month=data.month,
                    posts_per_month=data.posts_per_month,
                )

        existing = await db.execute(
            select(ContentPlan).where(
                ContentPlan.client_id == data.client_id,
                ContentPlan.month == data.month,
                ContentPlan.year == data.year,
            )
        )
        plan = existing.scalar_one_or_none()
        if plan:
            if plan.status == "approved":
                raise HTTPException(
                    status_code=409,
                    detail="Approved plan exists for this month — cannot regenerate",
                )
            await db.execute(
                delete(ContentPlanItem).where(ContentPlanItem.plan_id == plan.id)
            )
            plan.title = generated["title"]
            plan.posts_per_month = data.posts_per_month
            plan.status = "draft"
        else:
            plan = ContentPlan(
                client_id=data.client_id,
                month=data.month,
                year=data.year,
                title=generated["title"],
                posts_per_month=data.posts_per_month,
                status="draft",
            )
            db.add(plan)
            await db.flush()

        for row in generated["items"]:
            planned = date.fromisoformat(str(row["planned_date"])[:10])
            platforms = _normalize_platforms(row.get("platform_suggestions"))
            db.add(ContentPlanItem(
                plan_id=plan.id,
                planned_date=planned,
                theme=row["theme"],
                goal=row["goal"],
                platform_suggestions_json=json.dumps(platforms),
                content_type=row.get("content_type", "image"),
                status="planned",
            ))

        await db.commit()
        return await ContentPlannerService.get_plan(db, plan.id)

    @staticmethod
    async def update_plan(
        db: AsyncSession,
        plan_id: UUID,
        data: ContentPlanUpdate,
    ) -> dict[str, Any]:
        plan = await ContentPlannerService._load_plan(db, plan_id)
        if plan.status == "approved" and data.items:
            raise HTTPException(status_code=400, detail="Cannot edit items on approved plan")

        if data.title is not None:
            plan.title = data.title

        if data.items:
            item_map = {i.id: i for i in plan.items}
            for patch in data.items:
                item = item_map.get(patch.id)
                if not item:
                    continue
                if patch.planned_date is not None:
                    item.planned_date = patch.planned_date
                if patch.theme is not None:
                    item.theme = patch.theme
                if patch.goal is not None:
                    item.goal = patch.goal
                if patch.platform_suggestions is not None:
                    item.platform_suggestions_json = json.dumps(
                        _normalize_platforms(patch.platform_suggestions),
                    )
                if patch.content_type is not None:
                    if patch.content_type not in CONTENT_TYPES:
                        raise HTTPException(status_code=400, detail="Invalid content_type")
                    item.content_type = patch.content_type
                if patch.status is not None:
                    if patch.status not in ITEM_STATUSES:
                        raise HTTPException(status_code=400, detail="Invalid item status")
                    item.status = patch.status

        await db.commit()
        return await ContentPlannerService.get_plan(db, plan_id)

    @staticmethod
    async def approve_plan(db: AsyncSession, plan_id: UUID) -> dict[str, Any]:
        plan = await ContentPlannerService._load_plan(db, plan_id)
        if not plan.items:
            raise HTTPException(status_code=400, detail="Plan has no items")
        plan.status = "approved"
        await db.commit()
        logger.info("[Content Planner] approved: plan=%s", plan_id)
        return await ContentPlannerService.get_plan(db, plan_id)

    @staticmethod
    async def create_draft_from_item(
        db: AsyncSession,
        item_id: UUID,
        *,
        generate_ai: bool = True,
    ) -> dict[str, Any]:
        result = await db.execute(
            select(ContentPlanItem)
            .options(selectinload(ContentPlanItem.plan).selectinload(ContentPlan.client))
            .where(ContentPlanItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Plan item not found")
        if item.linked_content_id:
            return {
                "ok": True,
                "created": False,
                "message": "Draft already exists for this plan item",
                "plan_item_id": item_id,
                "content_id": item.linked_content_id,
                "ai_generated": False,
                "ai_error": None,
            }

        plan = item.plan
        client = plan.client
        platforms = _parse_platforms_json(item.platform_suggestions_json) or ["instagram"]
        scheduled = datetime.combine(
            item.planned_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        ) + timedelta(hours=12)

        notes = (
            f"[Content Plan]\n"
            f"Theme: {item.theme}\n"
            f"Goal: {item.goal}\n"
            f"Format: {item.content_type}\n"
            f"Planned date: {item.planned_date.isoformat()}\n"
            f"Plan: {plan.title}"
        )

        content = await ContentService.create(
            db,
            ContentCreate(
                client_id=plan.client_id,
                platforms=platforms,
                internal_notes=notes,
                source=CONTENT_PLAN_SOURCE,
                scheduled_for=scheduled,
            ),
        )
        item.linked_content_id = content.id
        item.status = "draft_created"
        await db.commit()

        ai_generated = False
        ai_error: str | None = None
        if generate_ai and client:
            ai_generated, ai_error = await _generate_captions_for_plan_item(
                db,
                client=client,
                content_id=content.id,
                plan=plan,
                item=item,
                platforms=platforms,
            )

        if ai_generated:
            message = "Draft created with AI captions (not published)"
        elif generate_ai and ai_error:
            message = "Draft created — AI caption generation failed"
        else:
            message = "Draft content created (not published)"

        logger.info(
            "[Content Planner] draft created: item=%s content=%s ai=%s",
            item_id,
            content.id,
            ai_generated,
        )
        return {
            "ok": True,
            "created": True,
            "message": message,
            "plan_item_id": item_id,
            "content_id": content.id,
            "ai_generated": ai_generated,
            "ai_error": ai_error,
        }
