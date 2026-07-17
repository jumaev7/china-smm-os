"""Tenant-scoped Brand Profile APIs for Governed AI Content Adaptation.

Clients cannot inject tenant IDs. Wrong tenant → 404 via AINotFoundError.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.governed_ai import (
    BrandProfileCreateRequest,
    BrandProfileDraftUpdateRequest,
    BrandProfileListResponse,
    BrandProfileResponse,
    BrandProfileVersionListResponse,
    BrandProfileVersionResponse,
)
from app.services.ai_content.brand_profile_service import BrandProfileService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/brand-profiles", tags=["brand-profiles"])


@router.get("/", response_model=BrandProfileListResponse)
async def list_brand_profiles(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await run_guarded(
        BrandProfileService.list_profiles(db, user.tenant_id),
        label="brand_profiles.list",
    )
    items = [BrandProfileResponse(**BrandProfileService.serialize_profile(p)) for p in rows]
    return BrandProfileListResponse(items=items, total=len(items))


@router.post("/", response_model=BrandProfileResponse)
async def create_brand_profile(
    body: BrandProfileCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await run_guarded(
        BrandProfileService.create_profile(
            db,
            user.tenant_id,
            name=body.name,
            draft=body.draft,
            created_by=user.id,
        ),
        label="brand_profiles.create",
    )
    await db.commit()
    return BrandProfileResponse(**BrandProfileService.serialize_profile(profile))


@router.get("/{profile_id}", response_model=BrandProfileResponse)
async def get_brand_profile(
    profile_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await run_guarded(
        BrandProfileService.get_profile(db, user.tenant_id, profile_id),
        label="brand_profiles.get",
    )
    return BrandProfileResponse(**BrandProfileService.serialize_profile(profile))


@router.patch("/{profile_id}/draft", response_model=BrandProfileResponse)
async def update_brand_profile_draft(
    profile_id: UUID,
    body: BrandProfileDraftUpdateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await run_guarded(
        BrandProfileService.update_draft(
            db,
            user.tenant_id,
            profile_id,
            draft=body.draft,
            expected_draft_version=body.expected_draft_version,
            name=body.name,
        ),
        label="brand_profiles.update_draft",
    )
    await db.commit()
    return BrandProfileResponse(**BrandProfileService.serialize_profile(profile))


@router.post("/{profile_id}/publish", response_model=BrandProfileVersionResponse)
async def publish_brand_profile(
    profile_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    version = await run_guarded(
        BrandProfileService.publish(
            db,
            user.tenant_id,
            profile_id,
            created_by=user.id,
        ),
        label="brand_profiles.publish",
    )
    await db.commit()
    return BrandProfileVersionResponse(**BrandProfileService.serialize_version(version))


@router.get("/{profile_id}/versions", response_model=BrandProfileVersionListResponse)
async def list_brand_profile_versions(
    profile_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await run_guarded(
        BrandProfileService.list_versions(db, user.tenant_id, profile_id),
        label="brand_profiles.list_versions",
    )
    items = [
        BrandProfileVersionResponse(**BrandProfileService.serialize_version(v))
        for v in rows
    ]
    return BrandProfileVersionListResponse(items=items, total=len(items))


@router.get(
    "/{profile_id}/versions/{version_id}",
    response_model=BrandProfileVersionResponse,
)
async def get_brand_profile_version(
    profile_id: UUID,
    version_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    version = await run_guarded(
        BrandProfileService.get_version(db, user.tenant_id, profile_id, version_id),
        label="brand_profiles.get_version",
    )
    return BrandProfileVersionResponse(**BrandProfileService.serialize_version(version))
