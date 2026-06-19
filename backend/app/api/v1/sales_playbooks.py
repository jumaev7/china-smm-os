from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.sales_playbook import (
    SalesPlaybookApplyRequest,
    SalesPlaybookApplyResult,
    SalesPlaybookCreate,
    SalesPlaybookGenerateRequest,
    SalesPlaybookListResponse,
    SalesPlaybookRecommendRequest,
    SalesPlaybookRecommendResponse,
    SalesPlaybookResponse,
    SalesPlaybookStepCreate,
    SalesPlaybookStepResponse,
    SalesPlaybookStepUpdate,
    SalesPlaybookUpdate,
)
from app.services.sales_playbook_service import SalesPlaybookService

router = APIRouter(prefix="/sales-playbooks", tags=["sales-playbooks"])


@router.get("", response_model=SalesPlaybookListResponse)
async def list_sales_playbooks(
    client_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.list_playbooks(
        db, client_id=client_id, status=status, skip=skip, limit=limit,
    )


@router.post("", response_model=SalesPlaybookResponse, status_code=201)
async def create_sales_playbook(
    body: SalesPlaybookCreate,
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.create_playbook(db, body)


@router.post("/generate", response_model=SalesPlaybookResponse, status_code=201)
async def generate_sales_playbook(
    body: SalesPlaybookGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        SalesPlaybookService.generate(db, body),
        label="sales-playbooks.generate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/recommend", response_model=SalesPlaybookRecommendResponse)
async def recommend_sales_playbook(
    body: SalesPlaybookRecommendRequest,
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.recommend(db, body)


@router.patch("/steps/{step_id}", response_model=SalesPlaybookStepResponse)
async def update_playbook_step(
    step_id: UUID,
    body: SalesPlaybookStepUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.update_step(db, step_id, body)


@router.get("/{playbook_id}", response_model=SalesPlaybookResponse)
async def get_sales_playbook(
    playbook_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.get_playbook(db, playbook_id)


@router.patch("/{playbook_id}", response_model=SalesPlaybookResponse)
async def update_sales_playbook(
    playbook_id: UUID,
    body: SalesPlaybookUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.update_playbook(db, playbook_id, body)


@router.post("/{playbook_id}/steps", response_model=SalesPlaybookStepResponse, status_code=201)
async def create_playbook_step(
    playbook_id: UUID,
    body: SalesPlaybookStepCreate,
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.create_step(db, playbook_id, body)


@router.post("/{playbook_id}/apply-to-lead/{lead_id}", response_model=SalesPlaybookApplyResult)
async def apply_playbook_to_lead(
    playbook_id: UUID,
    lead_id: UUID,
    body: SalesPlaybookApplyRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await SalesPlaybookService.apply_to_lead(db, playbook_id, lead_id, body)
