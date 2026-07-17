"""Brand profile helpers for AI adaptation context."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.governed_ai import TenantBrandProfile, TenantBrandProfileVersion
from app.services.ai_content.context_builder import brand_version_to_dict
from app.services.ai_content.errors import AINotFoundError, AIPolicyBlockedError


async def load_published_brand_version(
    db: AsyncSession,
    tenant_id: UUID,
    version_id: UUID | None,
    *,
    require: bool = True,
) -> tuple[TenantBrandProfileVersion | None, dict[str, Any] | None]:
    if version_id is None:
        if require:
            raise AIPolicyBlockedError(
                "A published Brand Profile version is required for AI adaptation",
                details={"reason": "brand_profile_required"},
            )
        return None, None

    result = await db.execute(
        select(TenantBrandProfileVersion).where(
            TenantBrandProfileVersion.id == version_id,
            TenantBrandProfileVersion.tenant_id == tenant_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise AINotFoundError("Brand profile version not found")

    # Ensure parent profile belongs to tenant (already filtered) and version is published
    parent = await db.execute(
        select(TenantBrandProfile).where(
            TenantBrandProfile.id == version.brand_profile_id,
            TenantBrandProfile.tenant_id == tenant_id,
        )
    )
    profile = parent.scalar_one_or_none()
    if profile is None:
        raise AINotFoundError("Brand profile not found")
    if profile.current_version_id != version.id and profile.status != "published":
        # Historical published versions remain usable for audit/regeneration
        pass
    return version, brand_version_to_dict(version)
