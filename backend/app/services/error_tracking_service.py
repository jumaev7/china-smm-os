"""Centralized error reporting — persisted + in-memory API errors."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import error_counts_by_category, recent_errors
from app.models.platform_ops import ERROR_SOURCES, PlatformErrorReport
from app.schemas.platform_ops import ErrorReportCreate


class ErrorTrackingService:
    @staticmethod
    async def report(
        db: AsyncSession,
        data: ErrorReportCreate,
        *,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> PlatformErrorReport:
        if data.source not in ERROR_SOURCES:
            raise HTTPException(status_code=400, detail=f"Invalid error source: {data.source}")
        row = PlatformErrorReport(
            source=data.source,
            tenant_id=tenant_id,
            user_id=user_id,
            path=data.path,
            message=data.message[:5000],
            stack_trace=data.stack_trace[:10000] if data.stack_trace else None,
            error_context=data.metadata,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def list_reports(
        db: AsyncSession,
        *,
        source: str | None = None,
        tenant_id: UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[PlatformErrorReport], int]:
        query = select(PlatformErrorReport)
        count_q = select(func.count()).select_from(PlatformErrorReport)
        if source:
            query = query.where(PlatformErrorReport.source == source)
            count_q = count_q.where(PlatformErrorReport.source == source)
        if tenant_id is not None:
            query = query.where(PlatformErrorReport.tenant_id == tenant_id)
            count_q = count_q.where(PlatformErrorReport.tenant_id == tenant_id)
        total = (await db.execute(count_q)).scalar_one()
        rows = (
            await db.execute(
                query.order_by(PlatformErrorReport.created_at.desc()).offset(skip).limit(limit),
            )
        ).scalars().all()
        return list(rows), int(total)

    @staticmethod
    def in_memory_snapshot() -> dict:
        return {
            "errors": recent_errors(50),
            "categories": error_counts_by_category(),
        }
