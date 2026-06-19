from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.proposal import (
    ProposalCreateFollowUpRequest,
    ProposalDocumentListResponse,
    ProposalDocumentResponse,
    ProposalDocumentUpdate,
    ProposalExportResponse,
    ProposalGenerateRequest,
    ProposalMarkAcceptedRequest,
    ProposalMarkRejectedRequest,
    ProposalMarkSentRequest,
    ProposalRegenerateSectionRequest,
    ProposalWorkflowResponse,
)
from app.services.proposal_export_service import ProposalExportService
from app.services.proposal_generator_service import ProposalGeneratorService
from app.services.proposal_workflow_service import ProposalWorkflowService

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.post("/generate", response_model=ProposalDocumentResponse, status_code=201)
async def generate_proposal(
    body: ProposalGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProposalGeneratorService.generate(db, body),
        label="proposals.generate",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("", response_model=ProposalDocumentListResponse)
async def list_proposals(
    client_id: UUID | None = None,
    lead_id: UUID | None = None,
    deal_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await ProposalGeneratorService.list_documents(
        db,
        client_id=client_id,
        lead_id=lead_id,
        deal_id=deal_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.get("/{proposal_id}", response_model=ProposalDocumentResponse)
async def get_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalGeneratorService.get_document(db, proposal_id)


@router.patch("/{proposal_id}", response_model=ProposalDocumentResponse)
async def update_proposal(
    proposal_id: UUID,
    body: ProposalDocumentUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalGeneratorService.update_document(db, proposal_id, body)


@router.post("/{proposal_id}/regenerate-section", response_model=ProposalDocumentResponse)
async def regenerate_proposal_section(
    proposal_id: UUID,
    body: ProposalRegenerateSectionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProposalGeneratorService.regenerate_section(db, proposal_id, body),
        label="proposals.regenerate_section",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/{proposal_id}/export/pdf", response_model=ProposalExportResponse)
async def export_proposal_pdf(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProposalExportService.export_pdf(db, proposal_id),
        label="proposals.export_pdf",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.post("/{proposal_id}/export/docx", response_model=ProposalExportResponse)
async def export_proposal_docx(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        ProposalExportService.export_docx(db, proposal_id),
        label="proposals.export_docx",
        timeout=SCAN_TIMEOUT_SEC,
    )


@router.get("/{proposal_id}/download/pdf")
async def download_proposal_pdf(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await ProposalExportService.download_pdf(db, proposal_id)


@router.get("/{proposal_id}/download/docx")
async def download_proposal_docx(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    return await ProposalExportService.download_docx(db, proposal_id)


@router.post("/{proposal_id}/mark-sent", response_model=ProposalWorkflowResponse)
async def mark_proposal_sent(
    proposal_id: UUID,
    body: ProposalMarkSentRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalWorkflowService.mark_sent(db, proposal_id, body)


@router.post("/{proposal_id}/mark-accepted", response_model=ProposalWorkflowResponse)
async def mark_proposal_accepted(
    proposal_id: UUID,
    body: ProposalMarkAcceptedRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalWorkflowService.mark_accepted(db, proposal_id, body)


@router.post("/{proposal_id}/mark-rejected", response_model=ProposalWorkflowResponse)
async def mark_proposal_rejected(
    proposal_id: UUID,
    body: ProposalMarkRejectedRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalWorkflowService.mark_rejected(db, proposal_id, body)


@router.post("/{proposal_id}/create-follow-up-task", response_model=ProposalWorkflowResponse)
async def create_proposal_follow_up_task(
    proposal_id: UUID,
    body: ProposalCreateFollowUpRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalWorkflowService.create_follow_up_task(db, proposal_id, body)
