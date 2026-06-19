from uuid import UUID

from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.crm import (
    CrmActivityCreate,
    CrmActivityListResponse,
    CrmActivityResponse,
    CrmAiGenerateMessageRequest,
    CrmAiGenerateMessageResponse,
    CrmAiSaveMessageRequest,
    CrmAiSuggestNextStepResponse,
    CrmExtractLeadRequest,
    CrmExtractLeadResponse,
    CrmLeadCreate,
    CrmLeadListResponse,
    CrmLeadResponse,
    CrmLeadUpdate,
    CrmPipelineResponse,
    LeadIntelligenceMetrics,
    LeadRescoreRequest,
    LeadRescoreResponse,
    LeadScoreResponse,
    CrmProposalGenerateRequest,
    CrmProposalListResponse,
    CrmProposalResponse,
    CrmProposalUpdate,
    CrmDocumentGenerateRequest,
    CrmDocumentListResponse,
    CrmDocumentResponse,
    CrmDocumentUpdate,
    CrmDealCreate,
    CrmDealDetailResponse,
    CrmDealEventCreate,
    CrmDealEventResponse,
    CrmDealHealthResponse,
    CrmDealListResponse,
    CrmDealResponse,
    CrmDealUpdate,
)
from app.schemas.revenue import CrmDealMarkWonRequest
from app.services.crm_service import CrmService
from app.services.deal_service import DealService
from app.services.document_service import DocumentService
from app.services.lead_intelligence_service import LeadIntelligenceService
from app.services.proposal_service import ProposalService
from app.services.revenue_service import RevenueService
from app.services.sales_copilot_service import SalesCopilotService

router = APIRouter(prefix="/crm", tags=["crm"])


@router.get("/leads", response_model=CrmLeadListResponse)
async def list_crm_leads(
    client_id: UUID | None = None,
    status: str | None = None,
    priority: str | None = Query(None, description="high | medium | low"),
    source: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CrmService.list_leads(
            db,
            client_id=client_id,
            status=status,
            priority=priority,
            source=source,
            skip=skip,
            limit=limit,
        ),
        label="crm.leads",
    )


@router.post("/leads", response_model=CrmLeadResponse, status_code=201)
async def create_crm_lead(
    body: CrmLeadCreate,
    db: AsyncSession = Depends(get_db),
):
    return await CrmService.create_lead(db, body)


@router.get("/leads/intelligence-metrics", response_model=LeadIntelligenceMetrics)
async def lead_intelligence_metrics(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await LeadIntelligenceService.metrics(db, client_id=client_id)


@router.post("/leads/rescore", response_model=LeadRescoreResponse)
async def rescore_crm_leads(
    body: LeadRescoreRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await LeadIntelligenceService.rescore_leads(db, body)


@router.get("/leads/{lead_id}", response_model=CrmLeadResponse)
async def get_crm_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await CrmService.get_lead(db, lead_id)


@router.patch("/leads/{lead_id}", response_model=CrmLeadResponse)
async def update_crm_lead(
    lead_id: UUID,
    body: CrmLeadUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await CrmService.update_lead(db, lead_id, body)


@router.post("/leads/{lead_id}/score", response_model=LeadScoreResponse)
async def score_crm_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        LeadIntelligenceService.score_lead(db, lead_id),
        label="crm.lead_score",
    )


@router.delete("/leads/{lead_id}", status_code=204)
async def delete_crm_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await CrmService.delete_lead(db, lead_id)


@router.get("/leads/{lead_id}/activities", response_model=CrmActivityListResponse)
async def list_lead_activities(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await CrmService.list_activities(db, lead_id)


@router.post("/leads/{lead_id}/activities", response_model=CrmActivityResponse, status_code=201)
async def add_lead_activity(
    lead_id: UUID,
    body: CrmActivityCreate,
    db: AsyncSession = Depends(get_db),
):
    return await CrmService.add_activity(db, lead_id, body)


@router.get("/pipeline", response_model=CrmPipelineResponse)
async def get_crm_pipeline(
    client_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        CrmService.pipeline(db, client_id=client_id),
        label="crm.pipeline",
    )


@router.post("/extract-lead", response_model=CrmExtractLeadResponse)
async def extract_crm_lead(
    body: CrmExtractLeadRequest,
    db: AsyncSession = Depends(get_db),
):
    return await CrmService.extract_lead(db, body)


@router.post("/leads/{lead_id}/ai-suggest-next-step", response_model=CrmAiSuggestNextStepResponse)
async def ai_suggest_next_step(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await SalesCopilotService.suggest_next_step(db, lead_id)


@router.post("/leads/{lead_id}/ai-generate-message", response_model=CrmAiGenerateMessageResponse)
async def ai_generate_message(
    lead_id: UUID,
    body: CrmAiGenerateMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    return await SalesCopilotService.generate_message(
        db, lead_id, purpose=body.purpose, language=body.language,
    )


@router.post("/leads/{lead_id}/ai-save-message", response_model=CrmActivityResponse, status_code=201)
async def ai_save_message_activity(
    lead_id: UUID,
    body: CrmAiSaveMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    return await SalesCopilotService.save_message_as_activity(
        db,
        lead_id,
        message_text=body.message_text,
        purpose=body.purpose,
        tone=body.tone,
    )


@router.post(
    "/leads/{lead_id}/proposals/generate",
    response_model=CrmProposalResponse,
    status_code=201,
)
async def generate_proposal(
    lead_id: UUID,
    body: CrmProposalGenerateRequest = Body(default=CrmProposalGenerateRequest()),
    db: AsyncSession = Depends(get_db),
):
    return await ProposalService.generate(db, lead_id, body)


@router.get("/leads/{lead_id}/proposals", response_model=CrmProposalListResponse)
async def list_lead_proposals(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalService.list_for_lead(db, lead_id)


@router.get("/proposals/{proposal_id}", response_model=CrmProposalResponse)
async def get_proposal(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalService.get_proposal(db, proposal_id)


@router.patch("/proposals/{proposal_id}", response_model=CrmProposalResponse)
async def update_proposal(
    proposal_id: UUID,
    body: CrmProposalUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await ProposalService.update_proposal(db, proposal_id, body)


@router.post(
    "/proposals/{proposal_id}/documents/generate",
    response_model=CrmDocumentResponse,
    status_code=201,
)
async def generate_document(
    proposal_id: UUID,
    body: CrmDocumentGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService.generate(db, proposal_id, body)


@router.get("/proposals/{proposal_id}/documents", response_model=CrmDocumentListResponse)
async def list_proposal_documents(
    proposal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService.list_for_proposal(db, proposal_id)


@router.get("/documents/{document_id}", response_model=CrmDocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService.get_document(db, document_id)


@router.patch("/documents/{document_id}", response_model=CrmDocumentResponse)
async def update_document(
    document_id: UUID,
    body: CrmDocumentUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await DocumentService.update_document(db, document_id, body)


@router.get("/deals", response_model=CrmDealListResponse)
async def list_deals(
    client_id: UUID | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        DealService.list_deals(
            db, client_id=client_id, status=status, skip=skip, limit=limit,
        ),
        label="crm.deals",
    )


@router.post("/deals", response_model=CrmDealResponse, status_code=201)
async def create_deal(
    body: CrmDealCreate,
    db: AsyncSession = Depends(get_db),
):
    return await DealService.create_deal(db, body)


@router.get("/deals/{deal_id}", response_model=CrmDealDetailResponse)
async def get_deal(
    deal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await DealService.get_deal(db, deal_id)


@router.patch("/deals/{deal_id}", response_model=CrmDealResponse)
async def update_deal(
    deal_id: UUID,
    body: CrmDealUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await DealService.update_deal(db, deal_id, body)


@router.post("/deals/{deal_id}/mark-won", response_model=CrmDealResponse)
async def mark_deal_won(
    deal_id: UUID,
    body: CrmDealMarkWonRequest,
    db: AsyncSession = Depends(get_db),
):
    return await RevenueService.mark_won(db, deal_id, body)


@router.post(
    "/deals/{deal_id}/events",
    response_model=CrmDealEventResponse,
    status_code=201,
)
async def add_deal_event(
    deal_id: UUID,
    body: CrmDealEventCreate,
    db: AsyncSession = Depends(get_db),
):
    return await DealService.add_event(db, deal_id, body)


@router.post("/deals/{deal_id}/health", response_model=CrmDealHealthResponse)
async def assess_deal_health(
    deal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await DealService.assess_health(db, deal_id)


@router.get("/leads/{lead_id}/deal", response_model=CrmDealDetailResponse)
async def get_deal_for_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await DealService.get_deal_by_lead(db, lead_id)
