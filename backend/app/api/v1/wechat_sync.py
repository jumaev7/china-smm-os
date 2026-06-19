"""WeChat Sync v1 — integration-ready sync endpoints (no message sending)."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.schemas.wechat_sync import (
    WeChatSyncAccountsResponse,
    WeChatSyncContactsRequest,
    WeChatSyncConversationsRequest,
    WeChatSyncJobsResponse,
    WeChatSyncRunResponse,
    WeChatSyncStatusOverview,
    WeChatSyncTestConnectionRequest,
    WeChatSyncTestConnectionResponse,
)
from app.services.wechat_sync_service import WeChatSyncService

router = APIRouter(prefix="/wechat-sync", tags=["wechat-sync"])


@router.get("/accounts", response_model=WeChatSyncAccountsResponse)
async def list_accounts(db: AsyncSession = Depends(get_db)):
    data = await WeChatSyncService.list_accounts(db)
    return data


@router.get("/jobs", response_model=WeChatSyncJobsResponse)
async def list_jobs(
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
):
    return await WeChatSyncService.list_jobs(db, skip=skip, limit=limit, status=status)


@router.get("/status", response_model=WeChatSyncStatusOverview)
async def sync_status(db: AsyncSession = Depends(get_db)):
    return await WeChatSyncService.status_overview(db)


@router.post("/sync-contacts", response_model=WeChatSyncRunResponse)
async def sync_contacts(
    body: WeChatSyncContactsRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    account_id = body.account_id if body else None
    return await run_guarded(
        WeChatSyncService.sync_contacts(db, account_id=account_id),
        label="wechat_sync.sync-contacts",
    )


@router.post("/sync-conversations", response_model=WeChatSyncRunResponse)
async def sync_conversations(
    body: WeChatSyncConversationsRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    account_id = body.account_id if body else None
    return await run_guarded(
        WeChatSyncService.sync_conversations(db, account_id=account_id),
        label="wechat_sync.sync-conversations",
    )


@router.post("/test-connection", response_model=WeChatSyncTestConnectionResponse)
async def test_connection(
    body: WeChatSyncTestConnectionRequest,
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        WeChatSyncService.test_connection(db, account_id=body.account_id),
        label="wechat_sync.test-connection",
    )
