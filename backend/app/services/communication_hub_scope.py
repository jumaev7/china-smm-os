"""Tenant scoping helpers for Communication Hub."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.communication import CommunicationContact, CommunicationThread


async def tenant_client_ids(db: AsyncSession, tenant_id: UUID) -> list[UUID]:
    rows = (
        await db.execute(
            select(Client.id).where(Client.tenant_id == tenant_id)
        )
    ).scalars().all()
    return list(rows)


async def thread_tenant_filter(tenant_id: UUID | None, client_ids: list[UUID]):
    """SQLAlchemy filter for threads belonging to a tenant."""
    if tenant_id is None:
        return None
    clauses = [CommunicationThread.tenant_id == tenant_id]
    if client_ids:
        clauses.append(CommunicationThread.client_id.in_(client_ids))
    return or_(*clauses)


async def contact_tenant_filter(tenant_id: UUID | None, client_ids: list[UUID]):
    if tenant_id is None:
        return None
    clauses = [CommunicationContact.tenant_id == tenant_id]
    if client_ids:
        clauses.append(CommunicationContact.client_id.in_(client_ids))
    return or_(*clauses)
