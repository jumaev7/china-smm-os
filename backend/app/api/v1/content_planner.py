from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.schemas.content_planner import (
    ContentPlanCreateDraftRequest,
    ContentPlanDraftResponse,
    ContentPlanGenerateRequest,
    ContentPlanResponse,
    ContentPlanUpdate,
)
from app.services.content_planner_service import ContentPlannerService

router = APIRouter(prefix="/content-planner", tags=["content-planner"])


@router.post("/generate", response_model=ContentPlanResponse)
async def generate_content_plan(
    body: ContentPlanGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await ContentPlannerService.generate(db, body)


@router.get("/plans/{plan_id}", response_model=ContentPlanResponse)
async def get_content_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ContentPlannerService.get_plan(db, plan_id)


@router.get("/plans", response_model=ContentPlanResponse | None)
async def find_content_plan(
    client_id: UUID,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2100),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ContentPlannerService.find_plan(
            db, client_id=client_id, month=month, year=year,
        ),
        label="content-planner.find",
    )


@router.patch("/plans/{plan_id}", response_model=ContentPlanResponse)
async def update_content_plan(
    plan_id: UUID,
    body: ContentPlanUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await ContentPlannerService.update_plan(db, plan_id, body)


@router.post("/plans/{plan_id}/approve", response_model=ContentPlanResponse)
async def approve_content_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ContentPlannerService.approve_plan(db, plan_id)


@router.post("/items/{item_id}/create-draft", response_model=ContentPlanDraftResponse)
async def create_draft_from_plan_item(
    item_id: UUID,
    body: ContentPlanCreateDraftRequest = Body(default=ContentPlanCreateDraftRequest()),
    db: AsyncSession = Depends(get_db),
):
    return await ContentPlannerService.create_draft_from_item(
        db, item_id, generate_ai=body.generate_ai,
    )
