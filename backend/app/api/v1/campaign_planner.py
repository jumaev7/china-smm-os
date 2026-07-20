"""Tenant-scoped Campaign Planner APIs.

Prefix: /campaign-planner. Separate from legacy client-scoped /campaigns.
Assignment never schedules or publishes. Publishing Score is advisory.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.models.campaign_planner import (
    TenantCampaignAudience,
    TenantCampaignGoal,
    TenantCampaignKpi,
    TenantCampaignPhase,
    TenantCampaignPillar,
)
from app.schemas.campaign_planner import (
    AIPlanRequest,
    AIPlanRequestListItem,
    AIPlanRequestListResponse,
    AIPlanRequestResponse,
    AssignmentResponse,
    AudienceCreateRequest,
    AudienceResponse,
    AudienceUpdateRequest,
    AutoAssignRequest,
    AutoAssignResponse,
    CampaignCreateRequest,
    CampaignListResponse,
    CampaignPillarCreateRequest,
    CampaignPillarResponse,
    CampaignPillarUpdateRequest,
    CampaignResponse,
    CampaignUpdateRequest,
    ContentPillarCreateRequest,
    ContentPillarListResponse,
    ContentPillarResponse,
    ContentPillarUpdateRequest,
    GoalCreateRequest,
    GoalResponse,
    GoalUpdateRequest,
    InventoryResponse,
    KpiCreateRequest,
    KpiResponse,
    KpiUpdateRequest,
    NestedListResponse,
    PhaseCreateRequest,
    PhaseResponse,
    PhaseUpdateRequest,
    PlanGenerateRequest,
    PlanListResponse,
    PlanResponse,
    ReviewListResponse,
    ReviewResponse,
    SlotAssignRequest,
    SlotCreateRequest,
    SlotListResponse,
    SlotResponse,
    SlotUpdateRequest,
)
from app.services.campaign_planner.ai_plan_service import CampaignAIPlanService
from app.services.campaign_planner.calendar_service import CalendarService
from app.services.campaign_planner.campaign_service import CampaignService
from app.services.campaign_planner.inventory_service import InventoryService
from app.services.campaign_planner.planning_service import PlanningService
from app.services.campaign_planner.review_engine import CampaignReviewEngine
from app.services.campaign_planner.slot_assignment import SlotAssignmentService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/campaign-planner", tags=["campaign-planner"])


def _campaign_dict(c) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "status": c.status,
        "objective": c.objective,
        "timezone": c.timezone,
        "primary_locale": c.primary_locale,
        "locales": list(c.locales or []),
        "platforms": list(c.platforms or []),
        "start_date": c.start_date,
        "end_date": c.end_date,
        "blackout_dates": list(c.blackout_dates or []),
        "cadence": c.cadence or {},
        "brand_profile_id": c.brand_profile_id,
        "brand_profile_version_id": c.brand_profile_version_id,
        "current_plan_version_id": c.current_plan_version_id,
        "published_plan_version_id": c.published_plan_version_id,
        "planner_version": c.planner_version,
        "policy_version": c.policy_version,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "archived_at": c.archived_at,
    }


def _plan_dict(p) -> dict:
    return {
        "id": p.id,
        "campaign_id": p.campaign_id,
        "version": p.version,
        "status": p.status,
        "generation_method": p.generation_method,
        "plan_fingerprint": p.plan_fingerprint,
        "planner_version": p.planner_version,
        "policy_version": p.policy_version,
        "parameters": p.parameters or {},
        "summary": p.summary or {},
        "notes": p.notes,
        "source_ai_request_id": p.source_ai_request_id,
        "parent_version_id": p.parent_version_id,
        "slot_count": p.slot_count,
        "created_at": p.created_at,
        "reviewed_at": p.reviewed_at,
        "published_at": p.published_at,
    }


def _slot_dict(s) -> dict:
    return {
        "id": s.id,
        "plan_version_id": s.plan_version_id,
        "campaign_id": s.campaign_id,
        "slot_index": s.slot_index,
        "platform": s.platform,
        "locale": s.locale,
        "pillar_id": s.pillar_id,
        "phase_id": s.phase_id,
        "scheduled_date": s.scheduled_date,
        "scheduled_time": s.scheduled_time,
        "suggested_time_label": s.suggested_time_label,
        "status": s.status,
        "slot_fingerprint": s.slot_fingerprint,
        "notes": s.notes,
    }


def _assignment_dict(a) -> dict:
    return {
        "id": a.id,
        "slot_id": a.slot_id,
        "content_id": a.content_id,
        "content_variant_id": a.content_variant_id,
        "assignment_type": getattr(a, "assignment_type", "content") or "content",
        "assigned_platform": a.assigned_platform,
        "assigned_locale": a.assigned_locale,
        "assignment_status": a.assignment_status,
        "readiness_status": a.readiness_status,
        "readiness_score": a.readiness_score,
        "publishing_review_id": a.publishing_review_id,
        "warnings": a.warnings,
        "assigned_at": a.assigned_at,
    }


def _review_dict(r) -> dict:
    return {
        "id": r.id,
        "campaign_id": r.campaign_id,
        "plan_version_id": r.plan_version_id,
        "review_type": r.review_type,
        "coverage_score": r.coverage_score,
        "readiness_score": r.readiness_score,
        "total_slots": r.total_slots,
        "assigned_slots": r.assigned_slots,
        "blocked_slots": r.blocked_slots,
        "unassigned_slots": r.unassigned_slots,
        "conflict_count": r.conflict_count,
        "gap_count": r.gap_count,
        "summary": r.summary or {},
        "engine_version": r.engine_version,
        "created_at": r.created_at,
    }


# ===========================================================================
# Content pillars
# ===========================================================================


@router.get("/content-pillars", response_model=ContentPillarListResponse)
async def list_content_pillars(
    active_only: bool = Query(False),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items = await run_guarded(
        CampaignService.list_pillars(db, user.tenant_id, active_only=active_only),
        label="campaign_planner.list_pillars",
    )
    return ContentPillarListResponse(
        items=[ContentPillarResponse.model_validate(i, from_attributes=True) for i in items],
        total=len(items),
    )


@router.post("/content-pillars", response_model=ContentPillarResponse)
async def create_content_pillar(
    body: ContentPillarCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await run_guarded(
        CampaignService.create_pillar(db, user.tenant_id, body.model_dump(), created_by=user.id),
        label="campaign_planner.create_pillar",
    )
    await db.commit()
    return ContentPillarResponse.model_validate(row, from_attributes=True)


@router.get("/content-pillars/{pillar_id}", response_model=ContentPillarResponse)
async def get_content_pillar(
    pillar_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await run_guarded(
        CampaignService.get_pillar(db, user.tenant_id, pillar_id),
        label="campaign_planner.get_pillar",
    )
    return ContentPillarResponse.model_validate(row, from_attributes=True)


@router.patch("/content-pillars/{pillar_id}", response_model=ContentPillarResponse)
async def update_content_pillar(
    pillar_id: UUID,
    body: ContentPillarUpdateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await run_guarded(
        CampaignService.update_pillar(
            db, user.tenant_id, pillar_id, body.model_dump(exclude_unset=True),
        ),
        label="campaign_planner.update_pillar",
    )
    await db.commit()
    return ContentPillarResponse.model_validate(row, from_attributes=True)


@router.delete("/content-pillars/{pillar_id}")
async def delete_content_pillar(
    pillar_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await run_guarded(
        CampaignService.delete_pillar(db, user.tenant_id, pillar_id),
        label="campaign_planner.delete_pillar",
    )
    await db.commit()
    return {"ok": True}


# ===========================================================================
# Campaigns
# ===========================================================================


@router.get("/campaigns", response_model=CampaignListResponse)
async def list_campaigns(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await run_guarded(
        CampaignService.list_campaigns(
            db, user.tenant_id, status=status, limit=limit, offset=offset,
        ),
        label="campaign_planner.list_campaigns",
    )
    return CampaignListResponse(
        items=[CampaignResponse(**_campaign_dict(c)) for c in items],
        total=total,
    )


@router.post("/campaigns", response_model=CampaignResponse)
async def create_campaign(
    body: CampaignCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await run_guarded(
        CampaignService.create_campaign(
            db, user.tenant_id, body.model_dump(), created_by=user.id,
        ),
        label="campaign_planner.create_campaign",
    )
    await db.commit()
    return CampaignResponse(**_campaign_dict(row))


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await run_guarded(
        CampaignService.load_campaign(db, user.tenant_id, campaign_id),
        label="campaign_planner.get_campaign",
    )
    return CampaignResponse(**_campaign_dict(row))


@router.patch("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: UUID,
    body: CampaignUpdateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = body.model_dump(exclude_unset=True)
    expected = data.pop("expected_updated_at", None)
    row = await run_guarded(
        CampaignService.update_campaign(
            db, user.tenant_id, campaign_id, data, expected_updated_at=expected,
        ),
        label="campaign_planner.update_campaign",
    )
    await db.commit()
    return CampaignResponse(**_campaign_dict(row))


@router.post("/campaigns/{campaign_id}/archive", response_model=CampaignResponse)
async def archive_campaign(
    campaign_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    row = await run_guarded(
        CampaignService.archive_campaign(db, user.tenant_id, campaign_id),
        label="campaign_planner.archive_campaign",
    )
    await db.commit()
    return CampaignResponse(**_campaign_dict(row))


# ===========================================================================
# Nested: goals / kpis / audiences / pillars / phases
# ===========================================================================


def _nested_crud(name: str, create_fn, update_fn, model, create_schema, update_schema, response_schema):
    """Helper unused — routes written explicitly for clarity."""
    pass


@router.get("/campaigns/{campaign_id}/goals", response_model=NestedListResponse)
async def list_goals(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    items = await run_guarded(CampaignService.list_children(db, user.tenant_id, campaign_id, TenantCampaignGoal), label="cp.goals.list")
    return NestedListResponse(items=[GoalResponse.model_validate(i, from_attributes=True) for i in items], total=len(items))


@router.post("/campaigns/{campaign_id}/goals", response_model=GoalResponse)
async def create_goal(campaign_id: UUID, body: GoalCreateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.add_goal(db, user.tenant_id, campaign_id, body.model_dump()), label="cp.goals.create")
    await db.commit()
    return GoalResponse.model_validate(row, from_attributes=True)


@router.patch("/campaigns/{campaign_id}/goals/{goal_id}", response_model=GoalResponse)
async def update_goal(campaign_id: UUID, goal_id: UUID, body: GoalUpdateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.update_goal(db, user.tenant_id, campaign_id, goal_id, body.model_dump(exclude_unset=True)), label="cp.goals.update")
    await db.commit()
    return GoalResponse.model_validate(row, from_attributes=True)


@router.delete("/campaigns/{campaign_id}/goals/{goal_id}")
async def delete_goal(campaign_id: UUID, goal_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await run_guarded(CampaignService.delete_child(db, user.tenant_id, campaign_id, TenantCampaignGoal, goal_id), label="cp.goals.delete")
    await db.commit()
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/kpis", response_model=NestedListResponse)
async def list_kpis(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    items = await run_guarded(CampaignService.list_children(db, user.tenant_id, campaign_id, TenantCampaignKpi), label="cp.kpis.list")
    return NestedListResponse(items=[KpiResponse.model_validate(i, from_attributes=True) for i in items], total=len(items))


@router.post("/campaigns/{campaign_id}/kpis", response_model=KpiResponse)
async def create_kpi(campaign_id: UUID, body: KpiCreateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.add_kpi(db, user.tenant_id, campaign_id, body.model_dump()), label="cp.kpis.create")
    await db.commit()
    return KpiResponse.model_validate(row, from_attributes=True)


@router.patch("/campaigns/{campaign_id}/kpis/{kpi_id}", response_model=KpiResponse)
async def update_kpi(campaign_id: UUID, kpi_id: UUID, body: KpiUpdateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.update_kpi(db, user.tenant_id, campaign_id, kpi_id, body.model_dump(exclude_unset=True)), label="cp.kpis.update")
    await db.commit()
    return KpiResponse.model_validate(row, from_attributes=True)


@router.delete("/campaigns/{campaign_id}/kpis/{kpi_id}")
async def delete_kpi(campaign_id: UUID, kpi_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await run_guarded(CampaignService.delete_child(db, user.tenant_id, campaign_id, TenantCampaignKpi, kpi_id), label="cp.kpis.delete")
    await db.commit()
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/audiences", response_model=NestedListResponse)
async def list_audiences(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    items = await run_guarded(CampaignService.list_children(db, user.tenant_id, campaign_id, TenantCampaignAudience), label="cp.audiences.list")
    return NestedListResponse(items=[AudienceResponse.model_validate(i, from_attributes=True) for i in items], total=len(items))


@router.post("/campaigns/{campaign_id}/audiences", response_model=AudienceResponse)
async def create_audience(campaign_id: UUID, body: AudienceCreateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.add_audience(db, user.tenant_id, campaign_id, body.model_dump()), label="cp.audiences.create")
    await db.commit()
    return AudienceResponse.model_validate(row, from_attributes=True)


@router.patch("/campaigns/{campaign_id}/audiences/{audience_id}", response_model=AudienceResponse)
async def update_audience(campaign_id: UUID, audience_id: UUID, body: AudienceUpdateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.update_audience(db, user.tenant_id, campaign_id, audience_id, body.model_dump(exclude_unset=True)), label="cp.audiences.update")
    await db.commit()
    return AudienceResponse.model_validate(row, from_attributes=True)


@router.delete("/campaigns/{campaign_id}/audiences/{audience_id}")
async def delete_audience(campaign_id: UUID, audience_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await run_guarded(CampaignService.delete_child(db, user.tenant_id, campaign_id, TenantCampaignAudience, audience_id), label="cp.audiences.delete")
    await db.commit()
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/pillars", response_model=NestedListResponse)
async def list_campaign_pillars(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    items = await run_guarded(CampaignService.list_children(db, user.tenant_id, campaign_id, TenantCampaignPillar), label="cp.pillars.list")
    return NestedListResponse(items=[CampaignPillarResponse.model_validate(i, from_attributes=True) for i in items], total=len(items))


@router.post("/campaigns/{campaign_id}/pillars", response_model=CampaignPillarResponse)
async def create_campaign_pillar(campaign_id: UUID, body: CampaignPillarCreateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.add_campaign_pillar(db, user.tenant_id, campaign_id, body.model_dump()), label="cp.pillars.create")
    await db.commit()
    return CampaignPillarResponse.model_validate(row, from_attributes=True)


@router.patch("/campaigns/{campaign_id}/pillars/{link_id}", response_model=CampaignPillarResponse)
async def update_campaign_pillar(campaign_id: UUID, link_id: UUID, body: CampaignPillarUpdateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.update_campaign_pillar(db, user.tenant_id, campaign_id, link_id, body.model_dump(exclude_unset=True)), label="cp.pillars.update")
    await db.commit()
    return CampaignPillarResponse.model_validate(row, from_attributes=True)


@router.delete("/campaigns/{campaign_id}/pillars/{link_id}")
async def delete_campaign_pillar(campaign_id: UUID, link_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await run_guarded(CampaignService.delete_child(db, user.tenant_id, campaign_id, TenantCampaignPillar, link_id), label="cp.pillars.delete")
    await db.commit()
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/phases", response_model=NestedListResponse)
async def list_phases(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    items = await run_guarded(CampaignService.list_children(db, user.tenant_id, campaign_id, TenantCampaignPhase), label="cp.phases.list")
    return NestedListResponse(items=[PhaseResponse.model_validate(i, from_attributes=True) for i in items], total=len(items))


@router.post("/campaigns/{campaign_id}/phases", response_model=PhaseResponse)
async def create_phase(campaign_id: UUID, body: PhaseCreateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.add_phase(db, user.tenant_id, campaign_id, body.model_dump()), label="cp.phases.create")
    await db.commit()
    return PhaseResponse.model_validate(row, from_attributes=True)


@router.patch("/campaigns/{campaign_id}/phases/{phase_id}", response_model=PhaseResponse)
async def update_phase(campaign_id: UUID, phase_id: UUID, body: PhaseUpdateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignService.update_phase(db, user.tenant_id, campaign_id, phase_id, body.model_dump(exclude_unset=True)), label="cp.phases.update")
    await db.commit()
    return PhaseResponse.model_validate(row, from_attributes=True)


@router.delete("/campaigns/{campaign_id}/phases/{phase_id}")
async def delete_phase(campaign_id: UUID, phase_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await run_guarded(CampaignService.delete_child(db, user.tenant_id, campaign_id, TenantCampaignPhase, phase_id), label="cp.phases.delete")
    await db.commit()
    return {"ok": True}


# ===========================================================================
# Plans
# ===========================================================================


@router.post("/campaigns/{campaign_id}/plans/generate", response_model=PlanResponse)
async def generate_plan(
    campaign_id: UUID,
    body: PlanGenerateRequest | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    cadence = body.cadence if body else None
    plan = await run_guarded(
        PlanningService.generate(
            db, user.tenant_id, campaign_id, cadence_override=cadence, created_by=user.id,
        ),
        label="campaign_planner.generate_plan",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return PlanResponse(**_plan_dict(plan))


@router.get("/campaigns/{campaign_id}/plans", response_model=PlanListResponse)
async def list_plans(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await CampaignService.load_campaign(db, user.tenant_id, campaign_id)
    items = await run_guarded(CalendarService.list_plans(db, user.tenant_id, campaign_id), label="cp.plans.list")
    return PlanListResponse(items=[PlanResponse(**_plan_dict(p)) for p in items], total=len(items))


@router.get("/campaigns/{campaign_id}/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(campaign_id: UUID, plan_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    plan = await run_guarded(CalendarService.load_plan(db, user.tenant_id, campaign_id, plan_id), label="cp.plans.get")
    return PlanResponse(**_plan_dict(plan))


@router.post("/campaigns/{campaign_id}/plans/{plan_id}/review", response_model=ReviewResponse)
async def review_plan(campaign_id: UUID, plan_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    review = await run_guarded(
        PlanningService.review(db, user.tenant_id, campaign_id, plan_id, created_by=user.id),
        label="cp.plans.review",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return ReviewResponse(**_review_dict(review))


@router.post("/campaigns/{campaign_id}/plans/{plan_id}/publish", response_model=PlanResponse)
async def publish_plan(campaign_id: UUID, plan_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    plan = await run_guarded(
        PlanningService.publish(db, user.tenant_id, campaign_id, plan_id, published_by=user.id),
        label="cp.plans.publish",
    )
    await db.commit()
    return PlanResponse(**_plan_dict(plan))


@router.post("/campaigns/{campaign_id}/plans/{plan_id}/clone", response_model=PlanResponse)
async def clone_plan(campaign_id: UUID, plan_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    plan = await run_guarded(
        PlanningService.clone(db, user.tenant_id, campaign_id, plan_id, created_by=user.id),
        label="cp.plans.clone",
    )
    await db.commit()
    return PlanResponse(**_plan_dict(plan))


# ===========================================================================
# Slots
# ===========================================================================


@router.get("/campaigns/{campaign_id}/plans/{plan_id}/slots", response_model=SlotListResponse)
async def list_slots(campaign_id: UUID, plan_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await CalendarService.load_plan(db, user.tenant_id, campaign_id, plan_id)
    items = await run_guarded(CalendarService.list_slots(db, user.tenant_id, plan_id), label="cp.slots.list")
    return SlotListResponse(items=[SlotResponse(**_slot_dict(s)) for s in items], total=len(items))


@router.post("/campaigns/{campaign_id}/plans/{plan_id}/slots", response_model=SlotResponse)
async def create_slot(campaign_id: UUID, plan_id: UUID, body: SlotCreateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(
        CalendarService.create_slot(db, user.tenant_id, campaign_id, plan_id, body.model_dump(), created_by=user.id),
        label="cp.slots.create",
    )
    await db.commit()
    return SlotResponse(**_slot_dict(row))


@router.patch("/campaigns/{campaign_id}/plans/{plan_id}/slots/{slot_id}", response_model=SlotResponse)
async def update_slot(campaign_id: UUID, plan_id: UUID, slot_id: UUID, body: SlotUpdateRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(
        CalendarService.update_slot(db, user.tenant_id, campaign_id, plan_id, slot_id, body.model_dump(exclude_unset=True)),
        label="cp.slots.update",
    )
    await db.commit()
    return SlotResponse(**_slot_dict(row))


@router.delete("/campaigns/{campaign_id}/plans/{plan_id}/slots/{slot_id}")
async def delete_slot(campaign_id: UUID, plan_id: UUID, slot_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await run_guarded(CalendarService.delete_slot(db, user.tenant_id, campaign_id, plan_id, slot_id), label="cp.slots.delete")
    await db.commit()
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/plans/{plan_id}/slots/{slot_id}/assign", response_model=AssignmentResponse)
async def assign_slot(campaign_id: UUID, plan_id: UUID, slot_id: UUID, body: SlotAssignRequest, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(
        SlotAssignmentService.assign(
            db, user.tenant_id, campaign_id, plan_id, slot_id, body.content_id,
            content_variant_id=body.content_variant_id,
            platform_override=body.platform,
            locale_override=body.locale,
            allow_warnings=body.allow_warnings,
            assigned_by=user.id,
        ),
        label="cp.slots.assign",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return AssignmentResponse(**_assignment_dict(row))


@router.delete("/campaigns/{campaign_id}/plans/{plan_id}/slots/{slot_id}/assignment")
async def unassign_slot(campaign_id: UUID, plan_id: UUID, slot_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await run_guarded(
        SlotAssignmentService.unassign(db, user.tenant_id, campaign_id, plan_id, slot_id),
        label="cp.slots.unassign",
    )
    await db.commit()
    return {"ok": True}


@router.post("/campaigns/{campaign_id}/plans/{plan_id}/auto-assign", response_model=AutoAssignResponse)
async def auto_assign(campaign_id: UUID, plan_id: UUID, body: AutoAssignRequest | None = None, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    result = await run_guarded(
        SlotAssignmentService.auto_assign(
            db, user.tenant_id, campaign_id, plan_id,
            allow_warnings=body.allow_warnings if body else True,
            run_publish_safety=body.run_publish_safety if body else False,
            assigned_by=user.id,
        ),
        label="cp.slots.auto_assign",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return AutoAssignResponse(**result)


# ===========================================================================
# Reviews / inventory
# ===========================================================================


@router.get("/campaigns/{campaign_id}/reviews", response_model=ReviewListResponse)
async def list_reviews(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await CampaignService.load_campaign(db, user.tenant_id, campaign_id)
    items = await run_guarded(CampaignReviewEngine.list_reviews(db, user.tenant_id, campaign_id), label="cp.reviews.list")
    return ReviewListResponse(items=[ReviewResponse(**_review_dict(r)) for r in items], total=len(items))


@router.get("/campaigns/{campaign_id}/reviews/latest", response_model=ReviewResponse)
async def latest_review(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    await CampaignService.load_campaign(db, user.tenant_id, campaign_id)
    items = await run_guarded(CampaignReviewEngine.list_reviews(db, user.tenant_id, campaign_id), label="cp.reviews.latest")
    if not items:
        from app.services.campaign_planner.errors import ReviewNotFoundError
        raise ReviewNotFoundError("No reviews yet").to_http()
    return ReviewResponse(**_review_dict(items[0]))


@router.get("/campaign-reviews/{review_id}", response_model=ReviewResponse)
async def get_review(review_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    row = await run_guarded(CampaignReviewEngine.get_review(db, user.tenant_id, review_id), label="cp.reviews.get")
    return ReviewResponse(**_review_dict(row))


@router.get("/campaigns/{campaign_id}/content-inventory", response_model=InventoryResponse)
async def content_inventory(
    campaign_id: UUID,
    platform: str | None = Query(None),
    locale: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await CampaignService.load_campaign(db, user.tenant_id, campaign_id)
    result = await run_guarded(
        InventoryService.list_inventory(
            db, user.tenant_id, campaign_id, platform=platform, locale=locale, limit=limit, offset=offset,
        ),
        label="cp.inventory",
    )
    return InventoryResponse(**result)


# ===========================================================================
# AI plan
# ===========================================================================


@router.post("/campaigns/{campaign_id}/ai-plan", response_model=AIPlanRequestResponse)
async def request_ai_plan(
    campaign_id: UUID,
    body: AIPlanRequest | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        CampaignAIPlanService.request_plan(
            db, user.tenant_id, campaign_id,
            brand_profile_version_id=body.brand_profile_version_id if body else None,
            quality_mode=body.quality_mode if body else None,
            idempotency_key=body.idempotency_key if body else None,
            requested_by=user.id,
        ),
        label="cp.ai_plan.request",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return AIPlanRequestResponse(**result)


@router.get("/campaigns/{campaign_id}/ai-plan-requests", response_model=AIPlanRequestListResponse)
async def list_ai_plan_requests(campaign_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    items = await run_guarded(
        CampaignAIPlanService.list_requests_for_campaign(db, user.tenant_id, campaign_id),
        label="cp.ai_plan.list",
    )
    return AIPlanRequestListResponse(
        items=[AIPlanRequestListItem(**i) for i in items],
        total=len(items),
    )


@router.get("/campaign-ai-requests/{request_id}", response_model=AIPlanRequestResponse)
async def get_ai_plan_request(request_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    result = await run_guarded(
        CampaignAIPlanService.get_request_detail(db, user.tenant_id, request_id),
        label="cp.ai_plan.get",
    )
    return AIPlanRequestResponse(**result)


@router.post("/campaign-ai-requests/{request_id}/apply", response_model=AIPlanRequestResponse)
async def apply_ai_plan(request_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    result = await run_guarded(
        CampaignAIPlanService.apply_proposal(db, user.tenant_id, request_id, applied_by=user.id),
        label="cp.ai_plan.apply",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return AIPlanRequestResponse(**result)


@router.post("/campaign-ai-requests/{request_id}/reject", response_model=AIPlanRequestResponse)
async def reject_ai_plan(request_id: UUID, user: CurrentTenantUser = Depends(get_current_tenant_user), db: AsyncSession = Depends(get_db)):
    result = await run_guarded(
        CampaignAIPlanService.reject_proposal(db, user.tenant_id, request_id),
        label="cp.ai_plan.reject",
    )
    await db.commit()
    return AIPlanRequestResponse(**result)
