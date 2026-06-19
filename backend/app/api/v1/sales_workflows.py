"""Sales Workflow Automation v1 — recommendation-only endpoints."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.sales_workflow import (
    WorkflowCreateTaskResponse,
    WorkflowGenerateRequest,
    WorkflowGenerateResponse,
    WorkflowOverview,
    WorkflowRecommendationListResponse,
    WorkflowTemplateListResponse,
)
from app.services.sales_workflow_service import SalesWorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/overview", response_model=WorkflowOverview)
async def workflows_overview(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesWorkflowService.overview(db, client_id=client_id),
        label="workflows.overview",
    )


@router.get("/recommendations", response_model=WorkflowRecommendationListResponse)
async def workflows_recommendations(
    status: str | None = None,
    priority: str | None = None,
    workflow_type: str | None = None,
    client_id: UUID | None = None,
    lead_id: UUID | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesWorkflowService.list_recommendations(
            db,
            status=status,
            priority=priority,
            workflow_type=workflow_type,
            client_id=client_id,
            lead_id=lead_id,
            skip=skip,
            limit=limit,
        ),
        label="workflows.recommendations",
    )


@router.get("/templates", response_model=WorkflowTemplateListResponse)
async def workflows_templates():
    return SalesWorkflowService.templates()


@router.post("/generate", response_model=WorkflowGenerateResponse)
async def workflows_generate(
    body: WorkflowGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    req = body or WorkflowGenerateRequest()
    return await run_guarded(
        SalesWorkflowService.generate(db, client_id=req.client_id),
        label="workflows.generate",
    )


@router.post(
    "/recommendations/{recommendation_id}/create-task",
    response_model=WorkflowCreateTaskResponse,
)
async def create_task_from_workflow(
    recommendation_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesWorkflowService.create_task_suggestion(db, recommendation_id)
