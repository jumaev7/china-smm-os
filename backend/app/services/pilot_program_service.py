"""Pilot factory program tracking."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_ops import PILOT_FACTORY_STATUSES, PilotFactory
from app.schemas.platform_ops import PilotFactoryCreate, PilotFactoryUpdate


class PilotProgramService:
    @staticmethod
    async def list_factories(
        db: AsyncSession,
        *,
        status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[PilotFactory], int]:
        query = select(PilotFactory)
        count_q = select(func.count()).select_from(PilotFactory)
        if status:
            query = query.where(PilotFactory.pilot_status == status)
            count_q = count_q.where(PilotFactory.pilot_status == status)
        total = (await db.execute(count_q)).scalar_one()
        rows = (
            await db.execute(
                query.order_by(PilotFactory.created_at.desc()).offset(skip).limit(limit),
            )
        ).scalars().all()
        return list(rows), int(total)

    @staticmethod
    async def get_factory(db: AsyncSession, factory_id: UUID) -> PilotFactory:
        row = (
            await db.execute(select(PilotFactory).where(PilotFactory.id == factory_id))
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Pilot factory not found")
        return row

    @staticmethod
    async def create_factory(
        db: AsyncSession,
        data: PilotFactoryCreate,
    ) -> PilotFactory:
        if data.pilot_status not in PILOT_FACTORY_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid pilot status: {data.pilot_status}")
        row = PilotFactory(
            factory_name=data.factory_name.strip(),
            country=data.country.strip(),
            industry=data.industry.strip(),
            pilot_status=data.pilot_status,
            start_date=data.start_date,
            end_date=data.end_date,
            success_score=data.success_score,
            notes=data.notes,
            tenant_id=data.tenant_id,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def update_factory(
        db: AsyncSession,
        factory_id: UUID,
        data: PilotFactoryUpdate,
    ) -> PilotFactory:
        row = await PilotProgramService.get_factory(db, factory_id)
        if data.factory_name is not None:
            row.factory_name = data.factory_name.strip()
        if data.country is not None:
            row.country = data.country.strip()
        if data.industry is not None:
            row.industry = data.industry.strip()
        if data.pilot_status is not None:
            if data.pilot_status not in PILOT_FACTORY_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid pilot status: {data.pilot_status}")
            row.pilot_status = data.pilot_status
        if data.start_date is not None:
            row.start_date = data.start_date
        if data.end_date is not None:
            row.end_date = data.end_date
        if data.success_score is not None:
            row.success_score = data.success_score
        if data.notes is not None:
            row.notes = data.notes
        if data.tenant_id is not None:
            row.tenant_id = data.tenant_id
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def delete_factory(db: AsyncSession, factory_id: UUID) -> None:
        row = await PilotProgramService.get_factory(db, factory_id)
        await db.delete(row)
        await db.commit()
