from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.client_service import ClientService
from app.schemas.client import ClientCreate, ClientUpdate, ClientResponse, ClientListResponse
from app.schemas.billing import ClientBillingResponse, ClientBillingUpdate
from app.services.billing_service import BillingService
from app.schemas.client_knowledge_base import (
    ClientKnowledgeBaseAiSummarizeResponse,
    ClientKnowledgeBaseEntryCreate,
    ClientKnowledgeBaseEntryResponse,
    ClientKnowledgeBaseEntryUpdate,
    ClientKnowledgeBaseListResponse,
)
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService

router = APIRouter(prefix="/clients", tags=["clients"])


@router.post("", response_model=ClientResponse, status_code=201)
async def create_client(data: ClientCreate, db: AsyncSession = Depends(get_db)):
    return await ClientService.create(db, data)


@router.get("", response_model=ClientListResponse)
async def list_clients(
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    items, total = await ClientService.list_all(db, skip, limit, status)
    return {"items": items, "total": total}


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(client_id: UUID, db: AsyncSession = Depends(get_db)):
    return await ClientService.get(db, client_id)


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: UUID, data: ClientUpdate, db: AsyncSession = Depends(get_db)
):
    return await ClientService.update(db, client_id, data)


@router.delete("/{client_id}", status_code=204)
async def delete_client(client_id: UUID, db: AsyncSession = Depends(get_db)):
    await ClientService.delete(db, client_id)


@router.get("/{client_id}/billing", response_model=ClientBillingResponse)
async def get_client_billing(client_id: UUID, db: AsyncSession = Depends(get_db)):
    return await BillingService.get_client_billing(db, client_id)


@router.patch("/{client_id}/billing", response_model=ClientBillingResponse)
async def update_client_billing(
    client_id: UUID,
    data: ClientBillingUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await BillingService.update_client_billing(db, client_id, data)


@router.get("/{client_id}/knowledge-base", response_model=ClientKnowledgeBaseListResponse)
async def list_client_knowledge_base(client_id: UUID, db: AsyncSession = Depends(get_db)):
    return await ClientKnowledgeBaseService.list_entries(db, client_id)


@router.post(
    "/{client_id}/knowledge-base",
    response_model=ClientKnowledgeBaseEntryResponse,
    status_code=201,
)
async def create_client_knowledge_base_entry(
    client_id: UUID,
    data: ClientKnowledgeBaseEntryCreate,
    db: AsyncSession = Depends(get_db),
):
    return await ClientKnowledgeBaseService.create_entry(db, client_id, data)


@router.post(
    "/{client_id}/knowledge-base/ai-summarize",
    response_model=ClientKnowledgeBaseAiSummarizeResponse,
)
async def ai_summarize_client_knowledge_base(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await ClientKnowledgeBaseService.ai_summarize(db, client_id)


@router.patch(
    "/{client_id}/knowledge-base/{kb_id}",
    response_model=ClientKnowledgeBaseEntryResponse,
)
async def update_client_knowledge_base_entry(
    client_id: UUID,
    kb_id: UUID,
    data: ClientKnowledgeBaseEntryUpdate,
    db: AsyncSession = Depends(get_db),
):
    return await ClientKnowledgeBaseService.update_entry(db, client_id, kb_id, data)


@router.delete("/{client_id}/knowledge-base/{kb_id}", status_code=204)
async def delete_client_knowledge_base_entry(
    client_id: UUID,
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await ClientKnowledgeBaseService.delete_entry(db, client_id, kb_id)
