"""Pilot Demo Mode — guided demonstration with isolated demo data for factory presentations."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.client_brief import ClientBrief
from app.models.content import ContentItem
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.operator_task import OperatorTask
from app.models.revenue_event import RevenueEvent
from app.models.tenant import TenantUser
from app.schemas.client_brief import ClientBriefCreate
from app.services.client_brief_service import (
    BRIEF_AI_MARKER,
    ClientBriefService,
    _heuristic_plan,
    _parse_plan,
    _store_plan,
)
from app.services.client_service import ClientService
from app.services.tenant_auth_service import DEMO_USER_EMAIL
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[PILOT_DEMO_MODE_V1]"

_WORKFLOW_STEPS: tuple[dict[str, str], ...] = (
    {
        "id": "brief_submitted",
        "title": "Client submits brief",
        "description": "Factory client submits product/campaign brief for SMM content.",
        "action_key": "create_sample_brief",
    },
    {
        "id": "plan_generated",
        "title": "AI generates multilingual content plan",
        "description": "AI creates a 7-post content plan in Russian, English, and Chinese.",
        "action_key": "generate_sample_plan",
    },
    {
        "id": "plan_approved",
        "title": "Manager reviews and approves plan",
        "description": "Account manager reviews the AI plan and approves for production.",
        "action_key": "approve_sample_plan",
    },
    {
        "id": "tasks_created",
        "title": "System creates content tasks",
        "description": "Approved plan converts to content items and operator tasks.",
        "action_key": "create_sample_tasks",
    },
    {
        "id": "content_qa",
        "title": "Content QA review",
        "description": "Content passes internal QA and client review stages.",
        "action_key": "simulate_publishing_pipeline",
    },
    {
        "id": "publishing_prep",
        "title": "Scheduling and publishing preparation",
        "description": "Content is scheduled and prepared for multi-platform publishing.",
        "action_key": "simulate_publishing_pipeline",
    },
    {
        "id": "revenue_visibility",
        "title": "Leads, deals and revenue visibility",
        "description": "CRM pipeline shows leads, deals, and revenue attribution.",
        "action_key": "generate_sample_revenue_metrics",
    },
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safety_notice() -> str:
    return (
        "Pilot Demo Mode uses isolated demo data tagged with "
        f"{MARKER}. Never modifies real tenant or production content. "
        "Reset fully cleans demo records."
    )


def _marker_filter(column):
    return column.contains(MARKER)


class PilotDemoModeService:
    @staticmethod
    async def _resolve_demo_context(db: AsyncSession) -> dict[str, Any]:
        user = await db.scalar(
            select(TenantUser).where(func.lower(TenantUser.email) == DEMO_USER_EMAIL.lower()),
        )
        if not user:
            raise HTTPException(
                status_code=400,
                detail=f"Demo tenant user {DEMO_USER_EMAIL} not found — create demo user first",
            )
        client_ids = await TenantService.get_client_ids_for_tenant(db, user.tenant_id)
        if not client_ids:
            raise HTTPException(
                status_code=400,
                detail="Demo tenant has no linked client — run demo user bootstrap",
            )
        return {
            "tenant_id": user.tenant_id,
            "client_id": client_ids[0],
            "user_email": user.email,
        }

    @staticmethod
    async def _demo_brief(db: AsyncSession) -> ClientBrief | None:
        result = await db.execute(
            select(ClientBrief)
            .options(selectinload(ClientBrief.client), selectinload(ClientBrief.tenant))
            .where(_marker_filter(ClientBrief.notes))
            .order_by(ClientBrief.created_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _demo_content_count(db: AsyncSession, client_id: UUID) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.client_id == client_id,
                    _marker_filter(ContentItem.internal_notes),
                ),
            ) or 0,
        )

    @staticmethod
    async def _demo_task_count(db: AsyncSession, client_id: UUID) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(OperatorTask)
                .where(
                    OperatorTask.client_id == client_id,
                    _marker_filter(OperatorTask.description),
                ),
            ) or 0,
        )

    @staticmethod
    async def _demo_lead_count(db: AsyncSession, client_id: UUID) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(CrmLead)
                .where(
                    CrmLead.client_id == client_id,
                    _marker_filter(CrmLead.notes),
                ),
            ) or 0,
        )

    @staticmethod
    async def _demo_deal_count(db: AsyncSession, client_id: UUID) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(CrmDeal)
                .where(
                    CrmDeal.client_id == client_id,
                    _marker_filter(CrmDeal.title),
                ),
            ) or 0,
        )

    @staticmethod
    async def _content_pipeline_stats(db: AsyncSession, client_id: UUID) -> dict[str, int]:
        result = await db.execute(
            select(ContentItem.status, func.count())
            .where(
                ContentItem.client_id == client_id,
                _marker_filter(ContentItem.internal_notes),
            )
            .group_by(ContentItem.status),
        )
        stats = {row[0]: int(row[1]) for row in result.all()}
        return stats

    @staticmethod
    def _step_status(
        step_id: str,
        *,
        brief: ClientBrief | None,
        content_count: int,
        task_count: int,
        lead_count: int,
        pipeline_stats: dict[str, int],
    ) -> str:
        if not brief:
            return "active" if step_id == "brief_submitted" else "pending"

        has_plan = bool(brief.ai_content_plan)
        status = brief.status or "new"

        if step_id == "brief_submitted":
            return "complete"
        if step_id == "plan_generated":
            if has_plan:
                return "complete"
            return "active"
        if step_id == "plan_approved":
            if status in {"approved", "converted"}:
                return "complete"
            return "active" if has_plan else "pending"
        if step_id == "tasks_created":
            if status == "converted" and task_count > 0:
                return "complete"
            return "active" if status == "approved" else "pending"
        if step_id == "content_qa":
            qa_count = sum(
                pipeline_stats.get(s, 0)
                for s in ("internal_review", "client_review", "approved", "scheduled", "published")
            )
            if qa_count >= min(content_count, 1) and content_count > 0:
                return "complete"
            return "active" if task_count > 0 else "pending"
        if step_id == "publishing_prep":
            sched_count = pipeline_stats.get("scheduled", 0) + pipeline_stats.get("published", 0)
            if sched_count >= min(content_count, 1) and content_count > 0:
                return "complete"
            qa_done = sum(pipeline_stats.get(s, 0) for s in ("approved", "scheduled", "published"))
            return "active" if qa_done > 0 else "pending"
        if step_id == "revenue_visibility":
            if lead_count > 0:
                return "complete"
            sched_count = pipeline_stats.get("scheduled", 0) + pipeline_stats.get("published", 0)
            return "active" if sched_count > 0 else "pending"

        return "pending"

    @staticmethod
    def _current_step(steps: list[dict[str, Any]]) -> int:
        for s in steps:
            if s["status"] in {"active", "pending"}:
                return s["step"]
        return len(steps)

    @staticmethod
    def _progress_percent(steps: list[dict[str, Any]]) -> int:
        complete = sum(1 for s in steps if s["status"] == "complete")
        return int(complete / len(steps) * 100) if steps else 0

    @staticmethod
    def _readiness_score(steps: list[dict[str, Any]]) -> int:
        complete = sum(1 for s in steps if s["status"] == "complete")
        active = sum(1 for s in steps if s["status"] == "active")
        return min(100, int(complete / len(steps) * 80 + active * 5))

    @staticmethod
    def _readiness_status(score: int) -> str:
        if score >= 80:
            return "ready"
        if score >= 40:
            return "in_progress"
        return "not_started"

    @staticmethod
    def _workflow_diagram(steps: list[dict[str, Any]]) -> dict[str, Any]:
        nodes = [
            {
                "id": s["id"],
                "label": s["title"],
                "status": s["status"],
                "step": s["step"],
            }
            for s in steps
        ]
        edges = [
            {"from": steps[i]["id"], "to": steps[i + 1]["id"]}
            for i in range(len(steps) - 1)
        ]
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _executive_summary(
        steps: list[dict[str, Any]],
        *,
        brief: ClientBrief | None,
        content_count: int,
        lead_count: int,
        deal_count: int,
    ) -> str:
        complete = sum(1 for s in steps if s["status"] == "complete")
        product = brief.product_name if brief else "sample product"
        if complete == len(steps):
            return (
                f"Full demonstration workflow complete for {product}. "
                f"{content_count} content items, {lead_count} leads, {deal_count} deals visible. "
                "Ready to present end-to-end China SMM OS capabilities to factory stakeholders."
            )
        if complete == 0:
            return (
                "Demonstration not started. Click 'Create Sample Brief' to begin the guided "
                "workflow showcasing brief intake through revenue visibility."
            )
        current = next((s for s in steps if s["status"] == "active"), steps[0])
        return (
            f"Demonstration in progress ({complete}/{len(steps)} steps complete). "
            f"Current stage: {current['title']}. "
            f"Product: {product}. Use demo actions to advance the workflow."
        )

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        try:
            ctx = await PilotDemoModeService._resolve_demo_context(db)
        except HTTPException:
            empty_steps = [
                {
                    "step": i,
                    "id": spec["id"],
                    "title": spec["title"],
                    "description": spec["description"],
                    "status": "pending" if i > 1 else "active",
                    "completed_at": None,
                    "action_key": spec["action_key"],
                }
                for i, spec in enumerate(_WORKFLOW_STEPS, start=1)
            ]
            return {
                "workflow_steps": empty_steps,
                "current_step": 1,
                "progress_percent": 0,
                "readiness_status": "not_started",
                "readiness_score": 0,
                "kpis": [
                    {"key": "progress", "label": "Workflow progress", "value": "0%"},
                    {"key": "briefs", "label": "Demo briefs", "value": 0},
                    {"key": "content", "label": "Content items", "value": 0},
                    {"key": "tasks", "label": "Operator tasks", "value": 0},
                    {"key": "scheduled", "label": "Scheduled/published", "value": 0},
                    {"key": "leads", "label": "CRM leads", "value": 0},
                    {"key": "deals", "label": "Active deals", "value": 0},
                    {"key": "revenue", "label": "Revenue (USD)", "value": 0},
                ],
                "workflow_diagram": PilotDemoModeService._workflow_diagram(empty_steps),
                "executive_summary": (
                    f"Demo tenant not configured. Create demo user ({DEMO_USER_EMAIL}) first."
                ),
                "demo_data_present": False,
                "demo_brief_id": None,
                "demo_tenant_id": None,
                "demo_client_id": None,
                "safety_notice": _safety_notice(),
                "refreshed_at": _utc_now(),
            }

        brief = await PilotDemoModeService._demo_brief(db)
        content_count = await PilotDemoModeService._demo_content_count(db, ctx["client_id"])
        task_count = await PilotDemoModeService._demo_task_count(db, ctx["client_id"])
        lead_count = await PilotDemoModeService._demo_lead_count(db, ctx["client_id"])
        deal_count = await PilotDemoModeService._demo_deal_count(db, ctx["client_id"])
        pipeline_stats = await PilotDemoModeService._content_pipeline_stats(db, ctx["client_id"])

        steps: list[dict[str, Any]] = []
        for i, spec in enumerate(_WORKFLOW_STEPS, start=1):
            status = PilotDemoModeService._step_status(
                spec["id"],
                brief=brief,
                content_count=content_count,
                task_count=task_count,
                lead_count=lead_count,
                pipeline_stats=pipeline_stats,
            )
            steps.append({
                "step": i,
                "id": spec["id"],
                "title": spec["title"],
                "description": spec["description"],
                "status": status,
                "completed_at": _utc_now() if status == "complete" else None,
                "action_key": spec["action_key"],
            })

        progress = PilotDemoModeService._progress_percent(steps)
        score = PilotDemoModeService._readiness_score(steps)

        scheduled = pipeline_stats.get("scheduled", 0) + pipeline_stats.get("published", 0)
        revenue_total = float(
            await db.scalar(
                select(func.coalesce(func.sum(RevenueEvent.amount), 0))
                .select_from(RevenueEvent)
                .join(CrmDeal, RevenueEvent.deal_id == CrmDeal.id)
                .where(
                    CrmDeal.client_id == ctx["client_id"],
                    _marker_filter(CrmDeal.title),
                ),
            ) or 0,
        )

        kpis = [
            {"key": "progress", "label": "Workflow progress", "value": f"{progress}%"},
            {"key": "briefs", "label": "Demo briefs", "value": 1 if brief else 0},
            {"key": "content", "label": "Content items", "value": content_count},
            {"key": "tasks", "label": "Operator tasks", "value": task_count},
            {"key": "scheduled", "label": "Scheduled/published", "value": scheduled},
            {"key": "leads", "label": "CRM leads", "value": lead_count},
            {"key": "deals", "label": "Active deals", "value": deal_count},
            {"key": "revenue", "label": "Revenue (USD)", "value": round(revenue_total, 2)},
        ]

        return {
            "workflow_steps": steps,
            "current_step": PilotDemoModeService._current_step(steps),
            "progress_percent": progress,
            "readiness_status": PilotDemoModeService._readiness_status(score),
            "readiness_score": score,
            "kpis": kpis,
            "workflow_diagram": PilotDemoModeService._workflow_diagram(steps),
            "executive_summary": PilotDemoModeService._executive_summary(
                steps,
                brief=brief,
                content_count=content_count,
                lead_count=lead_count,
                deal_count=deal_count,
            ),
            "demo_data_present": brief is not None,
            "demo_brief_id": brief.id if brief else None,
            "demo_tenant_id": ctx["tenant_id"],
            "demo_client_id": ctx["client_id"],
            "safety_notice": _safety_notice(),
            "refreshed_at": _utc_now(),
        }

    @staticmethod
    async def create_sample_brief(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotDemoModeService._resolve_demo_context(db)
        existing = await PilotDemoModeService._demo_brief(db)
        if existing:
            return {
                "success": True,
                "action": "create_sample_brief",
                "message": "Demo brief already exists — proceed to generate content plan",
                "overview": await PilotDemoModeService.overview(db),
            }

        client = await ClientService.get(db, ctx["client_id"])
        data = ClientBriefCreate(
            product_name="Smart CNC Precision Lathe XL-500",
            product_description=(
                "High-precision CNC lathe for export markets. "
                "ISO 9001 certified, suitable for automotive and aerospace components."
            ),
            target_market="Russia, Central Asia, Middle East",
            campaign_goal="awareness",
            languages=["zh", "en", "ru"],
            desired_platforms=["instagram", "linkedin", "telegram"],
            notes=f"{MARKER} Demonstration brief for factory pilot presentation.",
        )
        brief_data = await ClientBriefService.submit(
            db,
            data,
            tenant_id=ctx["tenant_id"],
            submitted_by=ctx["user_email"],
        )

        logger.info("[Pilot Demo Mode] Created sample brief id=%s", brief_data["id"])
        return {
            "success": True,
            "action": "create_sample_brief",
            "message": "Sample brief created — ready for AI content plan generation",
            "overview": await PilotDemoModeService.overview(db),
        }

    @staticmethod
    async def generate_sample_plan(db: AsyncSession) -> dict[str, Any]:
        brief = await PilotDemoModeService._demo_brief(db)
        if not brief:
            raise HTTPException(status_code=400, detail="Create sample brief first")

        if brief.ai_content_plan:
            return {
                "success": True,
                "action": "generate_sample_plan",
                "message": "Content plan already generated — proceed to approve",
                "overview": await PilotDemoModeService.overview(db),
            }

        brief.status = "reviewing"
        await db.commit()

        client = brief.client or await ClientService.get(db, brief.client_id)
        plan = _heuristic_plan(brief, client)
        plan["plan_status"] = "draft"
        plan["summary"] = (
            f"{MARKER} Multilingual 7-post plan for {brief.product_name}. "
            f"Target: {brief.target_market}. Languages: RU, EN, ZH."
        )
        _store_plan(brief, plan)
        brief.status = "reviewing"
        await db.commit()

        logger.info("[Pilot Demo Mode] Generated sample plan brief=%s", brief.id)
        return {
            "success": True,
            "action": "generate_sample_plan",
            "message": "Multilingual content plan generated (7 posts, RU/EN/ZH)",
            "overview": await PilotDemoModeService.overview(db),
        }

    @staticmethod
    async def approve_sample_plan(db: AsyncSession) -> dict[str, Any]:
        brief = await PilotDemoModeService._demo_brief(db)
        if not brief:
            raise HTTPException(status_code=400, detail="Create sample brief first")
        if not brief.ai_content_plan:
            raise HTTPException(status_code=400, detail="Generate content plan first")

        plan = _parse_plan(brief)
        if not plan:
            raise HTTPException(status_code=400, detail="Invalid content plan")
        plan["plan_status"] = "approved"
        _store_plan(brief, plan)
        brief.status = "approved"
        await db.commit()

        logger.info("[Pilot Demo Mode] Approved sample plan brief=%s", brief.id)
        return {
            "success": True,
            "action": "approve_sample_plan",
            "message": "Content plan approved — ready to create tasks",
            "overview": await PilotDemoModeService.overview(db),
        }

    @staticmethod
    async def create_sample_tasks(db: AsyncSession) -> dict[str, Any]:
        brief = await PilotDemoModeService._demo_brief(db)
        if not brief:
            raise HTTPException(status_code=400, detail="Create sample brief first")
        if brief.status == "converted":
            return {
                "success": True,
                "action": "create_sample_tasks",
                "message": "Tasks already created from demo brief",
                "overview": await PilotDemoModeService.overview(db),
            }
        if brief.status != "approved":
            raise HTTPException(status_code=400, detail="Approve content plan first")

        result = await ClientBriefService.convert_to_tasks(db, brief.id)

        content_items = await db.execute(
            select(ContentItem).where(
                ContentItem.client_id == brief.client_id,
                ContentItem.internal_notes.contains(BRIEF_AI_MARKER),
                ContentItem.internal_notes.contains(str(brief.id)),
            ),
        )
        for item in content_items.scalars().all():
            item.internal_notes = f"{MARKER}\n{item.internal_notes or ''}".strip()

        tasks = await db.execute(
            select(OperatorTask).where(
                OperatorTask.client_id == brief.client_id,
                OperatorTask.source_type == "client_brief",
            ).order_by(OperatorTask.created_at.desc()).limit(20),
        )
        for task in tasks.scalars().all():
            if task.description and MARKER not in (task.description or ""):
                task.description = f"{MARKER}\n{task.description}".strip()

        await db.commit()

        logger.info(
            "[Pilot Demo Mode] Created tasks brief=%s tasks=%s content=%s",
            brief.id,
            result.get("tasks_created"),
            result.get("content_items_created"),
        )
        return {
            "success": True,
            "action": "create_sample_tasks",
            "message": (
                f"Created {result.get('tasks_created', 0)} tasks and "
                f"{result.get('content_items_created', 0)} content items"
            ),
            "overview": await PilotDemoModeService.overview(db),
        }

    @staticmethod
    async def simulate_publishing_pipeline(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotDemoModeService._resolve_demo_context(db)
        result = await db.execute(
            select(ContentItem).where(
                ContentItem.client_id == ctx["client_id"],
                _marker_filter(ContentItem.internal_notes),
            ).order_by(ContentItem.created_at),
        )
        items = list(result.scalars().all())
        if not items:
            raise HTTPException(status_code=400, detail="Create sample tasks first")

        now = _utc_now()
        updated = 0
        for i, item in enumerate(items):
            if i < 2:
                item.status = "internal_review"
            elif i < 4:
                item.status = "approved"
                item.approved_at = now
            elif i < 6:
                item.status = "scheduled"
                item.scheduled_for = now + timedelta(days=i - 3)
            else:
                item.status = "published"
                item.published_at = now - timedelta(hours=1)
            updated += 1

        await db.commit()
        logger.info("[Pilot Demo Mode] Simulated publishing pipeline items=%s", updated)
        return {
            "success": True,
            "action": "simulate_publishing_pipeline",
            "message": f"Updated {updated} content items through QA → scheduling → published",
            "overview": await PilotDemoModeService.overview(db),
        }

    @staticmethod
    async def generate_sample_revenue_metrics(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotDemoModeService._resolve_demo_context(db)
        existing_leads = await PilotDemoModeService._demo_lead_count(db, ctx["client_id"])
        if existing_leads > 0:
            return {
                "success": True,
                "action": "generate_sample_revenue_metrics",
                "message": "Revenue metrics already generated",
                "overview": await PilotDemoModeService.overview(db),
            }

        now = _utc_now()
        leads_data = [
            ("Alexei Volkov", "Volga Industrial LLC", "qualified", Decimal("45000")),
            ("Marina Chen", "Shanghai Trade Partners", "negotiation", Decimal("78000")),
            ("Omar Al-Rashid", "Gulf Machinery Import", "new", Decimal("32000")),
        ]
        lead_ids: list[UUID] = []
        for name, company, status, value in leads_data:
            lead = CrmLead(
                client_id=ctx["client_id"],
                name=name,
                company=company,
                source="demo",
                language="en",
                interest="CNC machinery export",
                notes=f"{MARKER} Demo lead for pilot presentation.",
                status=status,
                priority="high",
                estimated_value=value,
            )
            db.add(lead)
            await db.flush()
            lead_ids.append(lead.id)

        deal_titles = [
            (f"Export Deal — Volga Industrial {MARKER}", lead_ids[0], "negotiation", Decimal("45000")),
            (f"Export Deal — Shanghai Trade {MARKER}", lead_ids[1], "proposal", Decimal("78000")),
        ]
        for title, lead_id, status, amount in deal_titles:
            deal = CrmDeal(
                lead_id=lead_id,
                client_id=ctx["client_id"],
                title=title,
                status=status,
                expected_value=amount,
                deal_amount=amount,
                currency="USD",
                probability=60 if status == "negotiation" else 40,
            )
            db.add(deal)
            await db.flush()
            db.add(RevenueEvent(
                deal_id=deal.id,
                type="pipeline",
                amount=amount * Decimal("0.15"),
            ))

        await db.commit()
        logger.info("[Pilot Demo Mode] Generated revenue metrics leads=%s", len(leads_data))
        return {
            "success": True,
            "action": "generate_sample_revenue_metrics",
            "message": f"Created {len(leads_data)} leads, {len(deal_titles)} deals with revenue events",
            "overview": await PilotDemoModeService.overview(db),
        }

    @staticmethod
    async def reset_demo_data(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotDemoModeService._resolve_demo_context(db)
        deleted: dict[str, int] = {}

        revenue_result = await db.execute(
            delete(RevenueEvent).where(
                RevenueEvent.deal_id.in_(
                    select(CrmDeal.id).where(
                        CrmDeal.client_id == ctx["client_id"],
                        _marker_filter(CrmDeal.title),
                    ),
                ),
            ),
        )
        deleted["revenue_events"] = revenue_result.rowcount or 0

        deals_result = await db.execute(
            delete(CrmDeal).where(
                CrmDeal.client_id == ctx["client_id"],
                _marker_filter(CrmDeal.title),
            ),
        )
        deleted["deals"] = deals_result.rowcount or 0

        leads_result = await db.execute(
            delete(CrmLead).where(
                CrmLead.client_id == ctx["client_id"],
                _marker_filter(CrmLead.notes),
            ),
        )
        deleted["leads"] = leads_result.rowcount or 0

        tasks_result = await db.execute(
            delete(OperatorTask).where(
                OperatorTask.client_id == ctx["client_id"],
                _marker_filter(OperatorTask.description),
            ),
        )
        deleted["tasks"] = tasks_result.rowcount or 0

        content_result = await db.execute(
            delete(ContentItem).where(
                ContentItem.client_id == ctx["client_id"],
                _marker_filter(ContentItem.internal_notes),
            ),
        )
        deleted["content_items"] = content_result.rowcount or 0

        briefs_result = await db.execute(
            delete(ClientBrief).where(_marker_filter(ClientBrief.notes)),
        )
        deleted["briefs"] = briefs_result.rowcount or 0

        await db.commit()
        logger.info("[Pilot Demo Mode] Reset demo data deleted=%s", deleted)
        return {
            "success": True,
            "message": "Demo data fully reset — all tagged records removed",
            "deleted_counts": deleted,
            "overview": await PilotDemoModeService.overview(db),
        }

    @staticmethod
    async def run_action(db: AsyncSession, action: str) -> dict[str, Any]:
        actions = {
            "create_sample_brief": PilotDemoModeService.create_sample_brief,
            "generate_sample_plan": PilotDemoModeService.generate_sample_plan,
            "approve_sample_plan": PilotDemoModeService.approve_sample_plan,
            "create_sample_tasks": PilotDemoModeService.create_sample_tasks,
            "simulate_publishing_pipeline": PilotDemoModeService.simulate_publishing_pipeline,
            "generate_sample_revenue_metrics": PilotDemoModeService.generate_sample_revenue_metrics,
        }
        handler = actions.get(action)
        if not handler:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        return await handler(db)
