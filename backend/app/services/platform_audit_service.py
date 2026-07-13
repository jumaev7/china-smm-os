"""Centralized platform audit logging with tenant isolation."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_ops import PlatformAuditLog
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


class PlatformAuditService:
    @staticmethod
    async def record(
        db: AsyncSession,
        *,
        actor_type: str,
        event_type: str,
        actor_id: UUID | None = None,
        tenant_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> PlatformAuditLog:
        if tenant_id is not None:
            tenant = await db.get(Tenant, tenant_id)
            if tenant is None:
                raise ValueError(f"tenant {tenant_id} not found for platform audit log")

        row = PlatformAuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=tenant_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        db.add(row)
        if commit:
            await db.commit()
            await db.refresh(row)
        else:
            await db.flush()
        return row

    @staticmethod
    async def list_logs(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        event_type: str | None = None,
        actor_type: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[PlatformAuditLog], int]:
        query = select(PlatformAuditLog)
        count_q = select(func.count()).select_from(PlatformAuditLog)
        if tenant_id is not None:
            query = query.where(PlatformAuditLog.tenant_id == tenant_id)
            count_q = count_q.where(PlatformAuditLog.tenant_id == tenant_id)
        if event_type:
            query = query.where(PlatformAuditLog.event_type == event_type)
            count_q = count_q.where(PlatformAuditLog.event_type == event_type)
        if actor_type:
            query = query.where(PlatformAuditLog.actor_type == actor_type)
            count_q = count_q.where(PlatformAuditLog.actor_type == actor_type)
        total = (await db.execute(count_q)).scalar_one()
        rows = (
            await db.execute(
                query.order_by(PlatformAuditLog.created_at.desc()).offset(skip).limit(limit),
            )
        ).scalars().all()
        return list(rows), int(total)
