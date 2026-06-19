"""WhatsApp Sync v1 — integration-ready sync endpoints (no message sending)."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.whatsapp_sync import (
    WhatsAppSyncAccountsResponse,
    WhatsAppSyncContactsRequest,
    WhatsAppSyncConversationsRequest,
    WhatsAppSyncJobsResponse,
    WhatsAppSyncRunResponse,
    WhatsAppSyncStatusOverview,
    WhatsAppSyncTestConnectionRequest,
    WhatsAppSyncTestConnectionResponse,
)
from app.services.whatsapp_sync_service import WhatsAppSyncService

router = APIRouter(prefix="/whatsapp-sync", tags=["whatsapp-sync"])


@router.get("/accounts", response_model=WhatsAppSyncAccountsResponse)
async def list_accounts(db: AsyncSession = Depends(get_db)):
    data = await WhatsAppSyncService.list_accounts(db)
    return data


@router.get("/jobs", response_model=WhatsAppSyncJobsResponse)
async def list_jobs(
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await WhatsAppSyncService.list_jobs(db, skip=skip, limit=limit, status=status)


@router.get("/status", response_model=WhatsAppSyncStatusOverview)
async def sync_status(db: AsyncSession = Depends(get_db)):
    return await WhatsAppSyncService.status_overview(db)


@router.post("/sync-contacts", response_model=WhatsAppSyncRunResponse)
async def sync_contacts(
    body: WhatsAppSyncContactsRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    account_id = body.account_id if body else None
    return await run_guarded(
        WhatsAppSyncService.sync_contacts(db, account_id=account_id),
        label="whatsapp_sync.sync-contacts",
    )


@router.post("/sync-conversations", response_model=WhatsAppSyncRunResponse)
async def sync_conversations(
    body: WhatsAppSyncConversationsRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    account_id = body.account_id if body else None
    return await run_guarded(
        WhatsAppSyncService.sync_conversations(db, account_id=account_id),
        label="whatsapp_sync.sync-conversations",
    )


@router.post("/test-connection", response_model=WhatsAppSyncTestConnectionResponse)
async def test_connection(
    body: WhatsAppSyncTestConnectionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WhatsAppSyncService.test_connection(db, account_id=body.account_id),
        label="whatsapp_sync.test-connection",
    )
