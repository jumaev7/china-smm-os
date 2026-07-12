"""Tenant Notification Center API."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.notification import (
    NotificationDeleteResponse,
    NotificationListResponse,
    NotificationMarkAllReadResponse,
    NotificationMarkReadResponse,
    NotificationUnreadCountResponse,
)
from app.services.notification_service import NotificationService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
async def notification_unread_count(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        NotificationService.get_unread_count(db, user.tenant_id),
        label="notifications.unread-count",
    )


@router.patch("/actions/read-all", response_model=NotificationMarkAllReadResponse)
async def notification_mark_all_read(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        NotificationService.mark_all_as_read(db, user.tenant_id),
        label="notifications.read-all",
    )


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    severity: str | None = None,
    is_read: bool | None = None,
    event_type: str | None = None,
    search: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        NotificationService.list_notifications(
            db,
            user.tenant_id,
            page=page,
            page_size=page_size,
            category=category,
            severity=severity,
            is_read=is_read,
            event_type=event_type,
            search=search,
            created_from=created_from,
            created_to=created_to,
        ),
        label="notifications.list",
    )


@router.patch("/{notification_id}/read", response_model=NotificationMarkReadResponse)
async def notification_mark_read(
    notification_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        NotificationService.mark_as_read(db, user.tenant_id, notification_id),
        label="notifications.mark-read",
    )


@router.delete("/{notification_id}", response_model=NotificationDeleteResponse)
async def notification_delete(
    notification_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    return await run_guarded(
        NotificationService.delete_notification(db, user.tenant_id, notification_id),
        label="notifications.delete",
    )
