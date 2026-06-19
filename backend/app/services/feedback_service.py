"""Platform feedback center for pilot factories."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_ops import FEEDBACK_CATEGORIES, FEEDBACK_TYPES, PlatformFeedback
from app.schemas.platform_ops import FeedbackCreate


class FeedbackService:
    @staticmethod
    async def submit(
        db: AsyncSession,
        data: FeedbackCreate,
        *,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
        pilot_factory_id: UUID | None = None,
    ) -> PlatformFeedback:
        if data.feedback_type not in FEEDBACK_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid feedback type: {data.feedback_type}")
        if data.category not in FEEDBACK_CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Invalid category: {data.category}")
        row = PlatformFeedback(
            tenant_id=tenant_id,
            user_id=user_id,
            pilot_factory_id=pilot_factory_id,
            feedback_type=data.feedback_type,
            category=data.category,
            title=data.title.strip(),
            description=data.description.strip(),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def list_feedback(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        category: str | None = None,
        feedback_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[PlatformFeedback], int]:
        query = select(PlatformFeedback)
        count_q = select(func.count()).select_from(PlatformFeedback)
        if tenant_id is not None:
            query = query.where(PlatformFeedback.tenant_id == tenant_id)
            count_q = count_q.where(PlatformFeedback.tenant_id == tenant_id)
        if category:
            query = query.where(PlatformFeedback.category == category)
            count_q = count_q.where(PlatformFeedback.category == category)
        if feedback_type:
            query = query.where(PlatformFeedback.feedback_type == feedback_type)
            count_q = count_q.where(PlatformFeedback.feedback_type == feedback_type)
        if status:
            query = query.where(PlatformFeedback.status == status)
            count_q = count_q.where(PlatformFeedback.status == status)
        total = (await db.execute(count_q)).scalar_one()
        rows = (
            await db.execute(
                query.order_by(PlatformFeedback.created_at.desc()).offset(skip).limit(limit),
            )
        ).scalars().all()
        return list(rows), int(total)
