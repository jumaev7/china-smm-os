"""Tenant-scoped Notification Center service."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_event import TenantEventNotification
from app.schemas.notification import (
    NotificationDeleteResponse,
    NotificationItem,
    NotificationListResponse,
    NotificationMarkAllReadResponse,
    NotificationMarkReadResponse,
    NotificationUnreadCountResponse,
)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def _escape_ilike(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _active_filter(tenant_id: UUID):
    return (
        TenantEventNotification.tenant_id == tenant_id,
        TenantEventNotification.deleted_at.is_(None),
    )


def _row_to_item(row: TenantEventNotification) -> NotificationItem:
    return NotificationItem(
        id=row.id,
        event_id=row.event_id,
        event_type=row.event_type,
        title=row.title,
        message=row.body,
        category=row.category,  # type: ignore[arg-type]
        severity=row.severity,  # type: ignore[arg-type]
        is_read=row.is_read,
        read_at=row.read_at,
        action_url=row.action_url,
        metadata=row.payload,
        created_at=row.created_at,
    )


class NotificationService:
    @staticmethod
    async def list_notifications(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        category: str | None = None,
        severity: str | None = None,
        is_read: bool | None = None,
        event_type: str | None = None,
        search: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> NotificationListResponse:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        offset = (page - 1) * page_size

        filters = list(_active_filter(tenant_id))
        if category:
            filters.append(TenantEventNotification.category == category)
        if severity:
            filters.append(TenantEventNotification.severity == severity)
        if is_read is not None:
            filters.append(TenantEventNotification.is_read == is_read)
        if event_type:
            filters.append(TenantEventNotification.event_type == event_type)
        if created_from is not None:
            filters.append(TenantEventNotification.created_at >= created_from)
        if created_to is not None:
            filters.append(TenantEventNotification.created_at <= created_to)
        if search and search.strip():
            escaped = _escape_ilike(search.strip())
            term = f"%{escaped}%"
            filters.append(
                or_(
                    TenantEventNotification.title.ilike(term, escape="\\"),
                    TenantEventNotification.body.ilike(term, escape="\\"),
                ),
            )

        total = (
            await db.execute(
                select(func.count()).select_from(TenantEventNotification).where(*filters),
            )
        ).scalar_one()

        rows = (
            await db.execute(
                select(TenantEventNotification)
                .where(*filters)
                .order_by(
                    TenantEventNotification.created_at.desc(),
                    TenantEventNotification.id.desc(),
                )
                .offset(offset)
                .limit(page_size),
            )
        ).scalars().all()

        pages = max(1, math.ceil(int(total) / page_size)) if total else 0
        if total == 0:
            pages = 0

        return NotificationListResponse(
            items=[_row_to_item(row) for row in rows],
            total=int(total),
            page=page,
            page_size=page_size,
            pages=pages,
        )

    @staticmethod
    async def get_unread_count(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> NotificationUnreadCountResponse:
        count = (
            await db.execute(
                select(func.count())
                .select_from(TenantEventNotification)
                .where(
                    TenantEventNotification.tenant_id == tenant_id,
                    TenantEventNotification.is_read.is_(False),
                    TenantEventNotification.deleted_at.is_(None),
                ),
            )
        ).scalar_one()
        return NotificationUnreadCountResponse(unread_count=int(count))

    @staticmethod
    async def _get_active_row(
        db: AsyncSession,
        tenant_id: UUID,
        notification_id: UUID,
    ) -> TenantEventNotification:
        row = (
            await db.execute(
                select(TenantEventNotification).where(
                    TenantEventNotification.id == notification_id,
                    *_active_filter(tenant_id),
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        return row

    @staticmethod
    async def mark_as_read(
        db: AsyncSession,
        tenant_id: UUID,
        notification_id: UUID,
    ) -> NotificationMarkReadResponse:
        row = await NotificationService._get_active_row(db, tenant_id, notification_id)
        now = datetime.now(timezone.utc)
        if not row.is_read:
            row.is_read = True
            row.status = "read"
            if row.read_at is None:
                row.read_at = now
            row.updated_at = now
            await db.commit()
        return NotificationMarkReadResponse(
            id=row.id,
            is_read=row.is_read,
            read_at=row.read_at,
        )

    @staticmethod
    async def mark_all_as_read(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> NotificationMarkAllReadResponse:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(TenantEventNotification)
            .where(
                TenantEventNotification.tenant_id == tenant_id,
                TenantEventNotification.is_read.is_(False),
                TenantEventNotification.deleted_at.is_(None),
            )
            .values(is_read=True, status="read", read_at=now, updated_at=now)
            .execution_options(synchronize_session=False),
        )
        await db.commit()
        return NotificationMarkAllReadResponse(updated_count=int(result.rowcount or 0))

    @staticmethod
    async def delete_notification(
        db: AsyncSession,
        tenant_id: UUID,
        notification_id: UUID,
    ) -> NotificationDeleteResponse:
        row = await NotificationService._get_active_row(db, tenant_id, notification_id)
        now = datetime.now(timezone.utc)
        row.deleted_at = now
        row.status = "dismissed"
        row.updated_at = now
        await db.commit()
        return NotificationDeleteResponse(id=row.id, deleted=True)
