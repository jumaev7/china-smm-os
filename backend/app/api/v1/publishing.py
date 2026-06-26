from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import get_current_admin_optional
from app.core.database import get_db
from app.core.tenant_access import get_current_tenant_user_optional
from app.schemas.publishing import (
    PublishingAccountCreate,
    PublishingAccountUpdate,
    PublishingAccountResponse,
    PublishingAccountListResponse,
    ScheduledPublishDebugResponse,
    PublishingCalendarResponse,
    PublishingQueueResponse,
    PublishingQueueActionResponse,
)
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.publishing_account_service import PublishingAccountService
from app.services.publishing_calendar_service import PublishingCalendarService
from app.services.publishing_queue_service import PublishingQueueService
from app.services.publishing_tenant_scope import resolve_publishing_tenant_id
from app.services.scheduled_publish_diagnostics_service import ScheduledPublishDiagnosticsService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/publishing", tags=["publishing"])


def _resolve_scope(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
    tenant_id: UUID | None,
) -> UUID:
    return resolve_publishing_tenant_id(user, admin, tenant_id)


@router.get("/accounts", response_model=PublishingAccountListResponse)
async def list_publishing_accounts(
    platform: str | None = None,
    status: str | None = None,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    items, total = await PublishingAccountService.list_all(
        db, scope_tenant_id, platform=platform, status=status,
    )
    return {
        "items": [PublishingAccountService._serialize(a) for a in items],
        "total": total,
    }


@router.post("/accounts", response_model=PublishingAccountResponse, status_code=201)
async def create_publishing_account(
    data: PublishingAccountCreate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    account = await PublishingAccountService.create(db, scope_tenant_id, data)
    return PublishingAccountService._serialize(account)


@router.patch("/accounts/{account_id}", response_model=PublishingAccountResponse)
async def update_publishing_account(
    account_id: UUID,
    data: PublishingAccountUpdate,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    account = await PublishingAccountService.update(db, scope_tenant_id, account_id, data)
    return PublishingAccountService._serialize(account)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_publishing_account(
    account_id: UUID,
    tenant_id: UUID | None = Query(None, description="Tenant scope (required for admin)"),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser | None = Depends(get_current_tenant_user_optional),
    admin: CurrentAdminUser | None = Depends(get_current_admin_optional),
):
    scope_tenant_id = _resolve_scope(user, admin, tenant_id)
    await PublishingAccountService.delete(db, scope_tenant_id, account_id)


@router.get("/queue", response_model=PublishingQueueResponse)
async def publishing_queue(
    client_timezone: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Scheduled / publishing queue with block reasons and safety status."""
    return await PublishingQueueService.list_queue(db, client_timezone=client_timezone)


@router.post("/queue/{content_id}/cancel", response_model=PublishingQueueActionResponse)
async def cancel_scheduled_queue_item(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PublishingQueueService.cancel_schedule(db, content_id)


@router.post("/queue/{content_id}/retry", response_model=PublishingQueueActionResponse)
async def retry_scheduled_queue_item(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PublishingQueueService.retry_publish(db, content_id)


@router.post("/queue/{content_id}/send-client-review", response_model=PublishingQueueActionResponse)
async def send_client_review_queue_item(
    content_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    return await PublishingQueueService.send_client_review(db, content_id)


@router.get("/scheduled-debug", response_model=ScheduledPublishDebugResponse)
async def scheduled_publish_debug(
    client_timezone: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Diagnostics: why scheduled content is or is not picked up by the scheduler."""
    return await ScheduledPublishDiagnosticsService.list_scheduled_debug(
        db, client_timezone=client_timezone,
    )


@router.get("/calendar", response_model=PublishingCalendarResponse)
async def publishing_calendar(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    client_id: UUID | None = None,
    platform: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Scheduled, published, and failed posts for the publishing calendar view."""
    if to_date < from_date:
        from_date, to_date = to_date, from_date
    return await PublishingCalendarService.list_calendar(
        db,
        from_date=from_date,
        to_date=to_date,
        client_id=client_id,
        platform=platform,
        status=status,
    )
