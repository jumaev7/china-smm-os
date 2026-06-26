"""Resolve tenant scope for publishing accounts — no global lookups."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.content import ContentItem
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.tenant_auth_service import CurrentTenantUser


def resolve_publishing_tenant_id(
    user: CurrentTenantUser | None,
    admin: CurrentAdminUser | None,
    tenant_id: UUID | None,
) -> UUID:
    """Tenant users are pinned to their tenant; admins must pass tenant_id."""
    if user:
        if tenant_id is not None and tenant_id != user.tenant_id:
            raise HTTPException(
                status_code=403,
                detail="Cannot access another tenant's publishing accounts",
            )
        return user.tenant_id
    if admin:
        if tenant_id is None:
            raise HTTPException(
                status_code=400,
                detail="tenant_id query parameter is required for admin publishing scope",
            )
        return tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


async def tenant_id_for_content(db: AsyncSession, item: ContentItem) -> UUID:
    if not item.client_id:
        raise HTTPException(
            status_code=400,
            detail="Content has no client — cannot resolve publishing tenant",
        )
    result = await db.execute(
        select(Client.tenant_id).where(Client.id == item.client_id),
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Content client has no tenant — publishing account cannot be resolved",
        )
    return tenant_id


async def tenant_id_for_content_optional(db: AsyncSession, item: ContentItem) -> UUID | None:
    if not item.client_id:
        return None
    result = await db.execute(
        select(Client.tenant_id).where(Client.id == item.client_id),
    )
    return result.scalar_one_or_none()
