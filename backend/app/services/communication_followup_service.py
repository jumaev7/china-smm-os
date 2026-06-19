"""Communication Hub follow-up management."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.communication import (
    FOLLOW_UP_STATUSES,
    CommunicationFollowUp,
    CommunicationThread,
)
from app.schemas.communication_hub import (
    FollowUpCreate,
    FollowUpListResponse,
    FollowUpResponse,
    FollowUpUpdate,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class CommunicationFollowUpService:
    @staticmethod
    def _to_response(
        row: CommunicationFollowUp,
        *,
        thread_title: str | None = None,
        channel: str | None = None,
    ) -> FollowUpResponse:
        now = _utcnow()
        due = _aware(row.due_date) or now
        is_overdue = row.status == "pending" and due < _start_of_day(now)
        return FollowUpResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            communication_id=row.communication_id,
            thread_id=row.thread_id,
            title=row.title,
            description=row.description,
            due_date=row.due_date,
            status=row.status,
            assigned_user=row.assigned_user,
            is_overdue=is_overdue,
            thread_title=thread_title,
            channel=channel,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    async def _load(
        db: AsyncSession,
        follow_up_id: UUID,
        tenant_id: UUID,
    ) -> CommunicationFollowUp:
        row = (
            await db.execute(
                select(CommunicationFollowUp)
                .options(selectinload(CommunicationFollowUp.communication))
                .where(
                    CommunicationFollowUp.id == follow_up_id,
                    CommunicationFollowUp.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Follow-up not found")
        return row

    @staticmethod
    async def _thread_meta(
        db: AsyncSession,
        thread_id: UUID | None,
    ) -> tuple[str | None, str | None]:
        if not thread_id:
            return None, None
        thread = (
            await db.execute(
                select(CommunicationThread).where(CommunicationThread.id == thread_id)
            )
        ).scalar_one_or_none()
        if not thread:
            return None, None
        return thread.title, thread.channel

    @staticmethod
    async def list_followups(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        bucket: str | None = None,
        status: str | None = None,
        assigned_user: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> FollowUpListResponse:
        now = _utcnow()
        today_start = _start_of_day(now)
        tomorrow_end = today_start.replace(hour=23, minute=59, second=59, microsecond=999999)

        q = (
            select(CommunicationFollowUp)
            .where(CommunicationFollowUp.tenant_id == tenant_id)
            .order_by(CommunicationFollowUp.due_date.asc())
        )
        count_q = (
            select(func.count())
            .select_from(CommunicationFollowUp)
            .where(CommunicationFollowUp.tenant_id == tenant_id)
        )

        if status:
            q = q.where(CommunicationFollowUp.status == status)
            count_q = count_q.where(CommunicationFollowUp.status == status)
        if assigned_user:
            q = q.where(CommunicationFollowUp.assigned_user == assigned_user)
            count_q = count_q.where(CommunicationFollowUp.assigned_user == assigned_user)

        if bucket == "overdue":
            q = q.where(
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date < today_start,
            )
            count_q = count_q.where(
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date < today_start,
            )
        elif bucket == "today":
            q = q.where(
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date >= today_start,
                CommunicationFollowUp.due_date <= tomorrow_end,
            )
            count_q = count_q.where(
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date >= today_start,
                CommunicationFollowUp.due_date <= tomorrow_end,
            )
        elif bucket == "upcoming":
            q = q.where(
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date > tomorrow_end,
            )
            count_q = count_q.where(
                CommunicationFollowUp.status == "pending",
                CommunicationFollowUp.due_date > tomorrow_end,
            )

        total = int((await db.execute(count_q)).scalar() or 0)
        rows = list(
            (await db.execute(q.offset(skip).limit(limit))).scalars().all()
        )

        overdue_count = int(
            (await db.execute(
                select(func.count()).select_from(CommunicationFollowUp).where(
                    CommunicationFollowUp.tenant_id == tenant_id,
                    CommunicationFollowUp.status == "pending",
                    CommunicationFollowUp.due_date < today_start,
                )
            )).scalar() or 0
        )
        today_count = int(
            (await db.execute(
                select(func.count()).select_from(CommunicationFollowUp).where(
                    CommunicationFollowUp.tenant_id == tenant_id,
                    CommunicationFollowUp.status == "pending",
                    CommunicationFollowUp.due_date >= today_start,
                    CommunicationFollowUp.due_date <= tomorrow_end,
                )
            )).scalar() or 0
        )
        upcoming_count = int(
            (await db.execute(
                select(func.count()).select_from(CommunicationFollowUp).where(
                    CommunicationFollowUp.tenant_id == tenant_id,
                    CommunicationFollowUp.status == "pending",
                    CommunicationFollowUp.due_date > tomorrow_end,
                )
            )).scalar() or 0
        )

        items: list[FollowUpResponse] = []
        for row in rows:
            title, channel = await CommunicationFollowUpService._thread_meta(db, row.thread_id)
            items.append(CommunicationFollowUpService._to_response(row, thread_title=title, channel=channel))

        return FollowUpListResponse(
            items=items,
            total=total,
            overdue_count=overdue_count,
            today_count=today_count,
            upcoming_count=upcoming_count,
        )

    @staticmethod
    async def create_followup(
        db: AsyncSession,
        tenant_id: UUID,
        data: FollowUpCreate,
    ) -> FollowUpResponse:
        row = CommunicationFollowUp(
            tenant_id=tenant_id,
            communication_id=data.communication_id,
            thread_id=data.thread_id,
            title=data.title.strip(),
            description=data.description,
            due_date=data.due_date,
            status="pending",
            assigned_user=data.assigned_user,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        title, channel = await CommunicationFollowUpService._thread_meta(db, row.thread_id)
        return CommunicationFollowUpService._to_response(row, thread_title=title, channel=channel)

    @staticmethod
    async def update_followup(
        db: AsyncSession,
        tenant_id: UUID,
        follow_up_id: UUID,
        data: FollowUpUpdate,
    ) -> FollowUpResponse:
        row = await CommunicationFollowUpService._load(db, follow_up_id, tenant_id)
        if data.title is not None:
            row.title = data.title.strip()
        if data.description is not None:
            row.description = data.description
        if data.due_date is not None:
            row.due_date = data.due_date
        if data.status is not None:
            if data.status not in FOLLOW_UP_STATUSES:
                raise HTTPException(status_code=422, detail="Invalid follow-up status")
            row.status = data.status
        if data.assigned_user is not None:
            row.assigned_user = data.assigned_user or None
        row.updated_at = _utcnow()
        await db.commit()
        await db.refresh(row)
        title, channel = await CommunicationFollowUpService._thread_meta(db, row.thread_id)
        return CommunicationFollowUpService._to_response(row, thread_title=title, channel=channel)

    @staticmethod
    async def complete_followup(
        db: AsyncSession,
        tenant_id: UUID,
        follow_up_id: UUID,
    ) -> FollowUpResponse:
        return await CommunicationFollowUpService.update_followup(
            db, tenant_id, follow_up_id, FollowUpUpdate(status="completed"),
        )
