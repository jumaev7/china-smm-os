"""Advertising Decision Support APIs (Phase 2).

Prefix: /advertising. Advisory / simulated / proposed only.
NEVER mutates provider campaigns, budgets, bids, creatives, or schedules.
Tenant identity always comes from auth — never from the request body.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.advertising import (
    ChangePlanListResponse,
    ChangePlanResponse,
    ComparisonRequest,
    ComparisonResponse,
    CreateExperimentRequest,
    CreateSimulationRequest,
    DiagnosticResponse,
    ExperimentListResponse,
    ExperimentResponse,
    ExperimentReviewResponse,
    PatchExperimentRequest,
    SimulationListResponse,
    SimulationResponse,
)
from app.services.advertising_decision_support import (
    budget_simulation_engine,
    change_plan_service,
    comparison_engine,
    concentration_analysis,
    creative_rotation,
    diminishing_returns,
    experiment_planner,
    experiment_review,
    pacing_projection,
    recommendation_engine,
)
from app.services.advertising_intelligence.errors import AdvertisingError
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/advertising", tags=["advertising-decision-support"])


async def _guarded(coro, *, label: str):
    try:
        return await run_guarded(coro, label=label)
    except AdvertisingError as exc:
        raise exc.to_http() from exc


def _as_dict(result) -> dict:
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if hasattr(result, "__dict__"):
        return {k: v for k, v in vars(result).items() if not k.startswith("_")}
    return dict(result)


# ===========================================================================
# Comparisons
# ===========================================================================


@router.post("/comparisons", response_model=ComparisonResponse)
async def create_comparison_endpoint(
    body: ComparisonRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        comparison_engine.compare_entities(
            db,
            user.tenant_id,
            entity_type=body.entity_type,
            entity_ids=body.entity_ids,
            metric_keys=body.metric_keys,
        ),
        label="advertising.comparisons.create",
    )
    return ComparisonResponse(**data)


@router.get("/comparisons", response_model=ComparisonResponse)
async def get_comparison_endpoint(
    entity_type: str = Query(..., max_length=40),
    entity_ids: list[UUID] = Query(..., min_length=2),
    metric_keys: list[str] | None = Query(None),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        comparison_engine.compare_entities(
            db,
            user.tenant_id,
            entity_type=entity_type,
            entity_ids=entity_ids,
            metric_keys=metric_keys,
        ),
        label="advertising.comparisons.get",
    )
    return ComparisonResponse(**data)


# ===========================================================================
# Budget simulations
# ===========================================================================


@router.post("/simulations", response_model=SimulationResponse)
async def create_simulation_endpoint(
    body: CreateSimulationRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    allocations = [
        {"campaign_id": str(a.campaign_id), "allocation_pct": a.allocation_pct}
        for a in body.allocations
    ]
    data = await _guarded(
        budget_simulation_engine.create_simulation(
            db,
            user.tenant_id,
            campaign_allocations=allocations,
            total_budget_minor=body.total_budget_minor,
            currency=body.currency,
            window_key=body.measurement_window_key,
            assumptions=body.assumptions,
            user_id=user.id,
        ),
        label="advertising.simulations.create",
    )
    await db.commit()
    return SimulationResponse(**_as_dict(data))


@router.get("/simulations", response_model=SimulationListResponse)
async def list_simulations_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        budget_simulation_engine.list_simulations(
            db, user.tenant_id, limit=limit, offset=offset,
        ),
        label="advertising.simulations.list",
    )
    return SimulationListResponse(
        items=[SimulationResponse(**_as_dict(i)) for i in items],
        total=total,
    )


@router.get("/simulations/{simulation_id}", response_model=SimulationResponse)
async def get_simulation_endpoint(
    simulation_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        budget_simulation_engine.get_simulation(db, user.tenant_id, simulation_id),
        label="advertising.simulations.get",
    )
    return SimulationResponse(**_as_dict(data))


# ===========================================================================
# Diagnostics
# ===========================================================================


@router.get("/diagnostics/concentration", response_model=DiagnosticResponse)
async def concentration_diagnostic_endpoint(
    account_id: UUID | None = Query(None),
    level: str = Query("campaign", pattern="^(campaign|creative)$"),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    if level == "creative":
        data = await _guarded(
            concentration_analysis.analyze_creative_concentration(
                db, user.tenant_id, account_id=account_id,
            ),
            label="advertising.diagnostics.concentration.creative",
        )
    else:
        data = await _guarded(
            concentration_analysis.analyze_campaign_concentration(
                db, user.tenant_id, account_id=account_id,
            ),
            label="advertising.diagnostics.concentration.campaign",
        )
    payload = _as_dict(data)
    return DiagnosticResponse(
        status=payload.get("classification") or payload.get("status"),
        classification=payload.get("classification"),
        kind="OBSERVED",
        engine_version=payload.get("engine_version"),
        observation=payload.get("observation"),
        evidence=payload.get("evidence") or {},
        interpretation=payload.get("interpretation"),
        possible_consideration=payload.get("possible_consideration"),
        details=payload,
    )


@router.get("/diagnostics/pacing", response_model=DiagnosticResponse)
async def pacing_diagnostic_endpoint(
    campaign_id: UUID = Query(...),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        pacing_projection.project_campaign_pacing(db, user.tenant_id, campaign_id),
        label="advertising.diagnostics.pacing",
    )
    payload = _as_dict(data)
    return DiagnosticResponse(
        status=payload.get("status") or payload.get("pacing_status"),
        kind="MECHANICAL_PROJECTION",
        engine_version=payload.get("engine_version") or payload.get("calculation_version"),
        observation=payload.get("observation") or payload.get("label"),
        evidence=payload.get("evidence") or payload,
        interpretation=payload.get("interpretation"),
        possible_consideration=payload.get("possible_consideration"),
        label=payload.get("label") or "Mechanical projection based on current spend rate",
        formula=payload.get("formula"),
        disclaimer=payload.get("disclaimer"),
        details=payload,
    )


@router.get("/diagnostics/creative-rotation", response_model=DiagnosticResponse)
async def creative_rotation_diagnostic_endpoint(
    account_id: UUID | None = Query(None),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        creative_rotation.analyze_creative_rotation(
            db, user.tenant_id, account_id=account_id,
        ),
        label="advertising.diagnostics.creative_rotation",
    )
    payload = _as_dict(data)
    return DiagnosticResponse(
        status=payload.get("status"),
        classification=payload.get("status"),
        kind="OBSERVED",
        engine_version=payload.get("engine_version"),
        observation=payload.get("observation"),
        evidence=payload.get("evidence") or {},
        interpretation=payload.get("interpretation"),
        possible_consideration=payload.get("possible_consideration"),
        details=payload,
    )


@router.get("/diagnostics/diminishing-returns", response_model=DiagnosticResponse)
async def diminishing_returns_diagnostic_endpoint(
    campaign_id: UUID = Query(...),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        diminishing_returns.analyze_campaign_diminishing_returns(
            db, user.tenant_id, campaign_id,
        ),
        label="advertising.diagnostics.diminishing_returns",
    )
    payload = _as_dict(data)
    return DiagnosticResponse(
        status=payload.get("status"),
        classification=payload.get("status"),
        kind="DIRECTIONAL",
        engine_version=payload.get("engine_version"),
        observation=payload.get("observation"),
        evidence=payload.get("evidence") or {},
        interpretation=payload.get("interpretation"),
        possible_consideration=payload.get("possible_consideration"),
        disclaimer="Historical indicator only — does not claim causal diminishing returns.",
        details=payload,
    )


# ===========================================================================
# Experiments (planning / observation only — does NOT launch on providers)
# ===========================================================================


@router.post("/experiments", response_model=ExperimentResponse)
async def create_experiment_endpoint(
    body: CreateExperimentRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    variants = [v.model_dump() for v in body.variants]
    data = await _guarded(
        experiment_planner.create_experiment(
            db,
            user.tenant_id,
            name=body.name,
            experiment_type=body.experiment_type,
            hypothesis=body.hypothesis,
            primary_metric_key=body.primary_metric_key,
            variants=variants,
            secondary_metric_keys=body.secondary_metric_keys,
            observation_start=body.observation_start,
            observation_end=body.observation_end,
            minimum_observations=body.minimum_observations,
            minimum_spend_minor=body.minimum_spend_minor,
            minimum_conversions=body.minimum_conversions,
            currency=body.currency,
            attribution_method=body.attribution_method,
            notes=body.notes,
            user_id=user.id,
        ),
        label="advertising.experiments.create",
    )
    await db.commit()
    return ExperimentResponse(**_as_dict(data))


@router.get("/experiments", response_model=ExperimentListResponse)
async def list_experiments_endpoint(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        experiment_planner.list_experiments(
            db, user.tenant_id, status=status, limit=limit, offset=offset,
        ),
        label="advertising.experiments.list",
    )
    return ExperimentListResponse(
        items=[ExperimentResponse(**_as_dict(i)) for i in items],
        total=total,
    )


@router.get("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment_endpoint(
    experiment_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        experiment_planner.get_experiment(db, user.tenant_id, experiment_id),
        label="advertising.experiments.get",
    )
    return ExperimentResponse(**_as_dict(data))


@router.patch("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def patch_experiment_endpoint(
    experiment_id: UUID,
    body: PatchExperimentRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        experiment_planner.patch_experiment(
            db,
            user.tenant_id,
            experiment_id,
            **body.model_dump(exclude_unset=True),
        ),
        label="advertising.experiments.patch",
    )
    await db.commit()
    return ExperimentResponse(**_as_dict(data))


@router.post("/experiments/{experiment_id}/start-observation", response_model=ExperimentResponse)
async def start_experiment_observation_endpoint(
    experiment_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        experiment_planner.start_observation(db, user.tenant_id, experiment_id),
        label="advertising.experiments.start_observation",
    )
    await db.commit()
    return ExperimentResponse(**_as_dict(data))


@router.post("/experiments/{experiment_id}/complete", response_model=ExperimentResponse)
async def complete_experiment_endpoint(
    experiment_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        experiment_planner.complete_experiment(db, user.tenant_id, experiment_id),
        label="advertising.experiments.complete",
    )
    await db.commit()
    return ExperimentResponse(**_as_dict(data))


@router.post("/experiments/{experiment_id}/cancel", response_model=ExperimentResponse)
async def cancel_experiment_endpoint(
    experiment_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        experiment_planner.cancel_experiment(db, user.tenant_id, experiment_id),
        label="advertising.experiments.cancel",
    )
    await db.commit()
    return ExperimentResponse(**_as_dict(data))


@router.get("/experiments/{experiment_id}/review", response_model=ExperimentReviewResponse)
async def get_experiment_review_endpoint(
    experiment_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        experiment_review.get_review(db, user.tenant_id, experiment_id),
        label="advertising.experiments.review",
    )
    payload = _as_dict(data)
    return ExperimentReviewResponse(
        experiment_id=payload.get("experiment_id") or str(experiment_id),
        result_status=payload.get("result_status") or "insufficient_data",
        conclusion=payload.get("conclusion") or "",
        evidence=payload.get("evidence") or {},
        variants=payload.get("variants") or [],
        comparison=payload.get("comparison") or {},
        limitations=payload.get("limitations") or [],
        kind=payload.get("kind") or "DIRECTIONAL",
        claims_statistical_significance=False,
        review_id=payload.get("review_id"),
        engine_version=payload.get("engine_version"),
    )


@router.post("/experiments/{experiment_id}/review", response_model=ExperimentReviewResponse)
async def build_experiment_review_endpoint(
    experiment_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        experiment_review.build_review(
            db, user.tenant_id, experiment_id, user_id=user.id, persist=True,
        ),
        label="advertising.experiments.review.build",
    )
    await db.commit()
    payload = _as_dict(data)
    return ExperimentReviewResponse(
        experiment_id=payload.get("experiment_id") or str(experiment_id),
        result_status=payload.get("result_status") or "insufficient_data",
        conclusion=payload.get("conclusion") or "",
        evidence=payload.get("evidence") or {},
        variants=payload.get("variants") or [],
        comparison=payload.get("comparison") or {},
        limitations=payload.get("limitations") or [],
        kind=payload.get("kind") or "DIRECTIONAL",
        claims_statistical_significance=False,
        review_id=payload.get("review_id"),
        engine_version=payload.get("engine_version"),
    )


# ===========================================================================
# Change plans (advisory only — never executable)
# ===========================================================================


@router.get("/change-plans", response_model=ChangePlanListResponse)
async def list_change_plans_endpoint(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await _guarded(
        change_plan_service.list_change_plans(
            db, user.tenant_id, status=status, limit=limit, offset=offset,
        ),
        label="advertising.change_plans.list",
    )
    return ChangePlanListResponse(
        items=[ChangePlanResponse(**_as_dict(i)) for i in items],
        total=total,
    )


@router.get("/change-plans/{plan_id}", response_model=ChangePlanResponse)
async def get_change_plan_endpoint(
    plan_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        change_plan_service.get_change_plan(db, user.tenant_id, plan_id),
        label="advertising.change_plans.get",
    )
    return ChangePlanResponse(**_as_dict(data))


@router.post("/change-plans/{plan_id}/review", response_model=ChangePlanResponse)
async def review_change_plan_endpoint(
    plan_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        change_plan_service.review_change_plan(db, user.tenant_id, plan_id),
        label="advertising.change_plans.review",
    )
    await db.commit()
    return ChangePlanResponse(**_as_dict(data))


@router.post("/change-plans/{plan_id}/dismiss", response_model=ChangePlanResponse)
async def dismiss_change_plan_endpoint(
    plan_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    data = await _guarded(
        change_plan_service.dismiss_change_plan(db, user.tenant_id, plan_id),
        label="advertising.change_plans.dismiss",
    )
    await db.commit()
    return ChangePlanResponse(**_as_dict(data))


@router.post("/change-plans/generate", response_model=ChangePlanResponse)
async def generate_change_plan_endpoint(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a draft advisory change plan from deterministic recommendations."""
    data = await _guarded(
        recommendation_engine.generate_draft_change_plan(
            db, user.tenant_id, user_id=user.id,
        ),
        label="advertising.change_plans.generate",
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "AD_CHANGE_PLAN_EMPTY",
                "message": "No advisory recommendations available to materialize.",
            },
        )
    await db.commit()
    return ChangePlanResponse(**_as_dict(data))


@router.get("/decision-support/recommendations")
async def decision_support_recommendations_endpoint(
    limit: int = Query(50, ge=1, le=200),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items = await _guarded(
        recommendation_engine.generate_recommendations(db, user.tenant_id),
        label="advertising.decision_support.recommendations",
    )
    sliced = list(items)[:limit]
    return {"items": sliced, "total": len(sliced), "read_only": True, "advisory": True}
