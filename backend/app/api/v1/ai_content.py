"""Tenant-scoped Governed AI Content Adaptation APIs.

Clients cannot inject provider, raw model, system prompt, temperature,
max tokens, tenant_id, or scores. AI output is always a proposed immutable variant.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import SCAN_TIMEOUT_SEC, run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.governed_ai import (
    AdaptContentRequest,
    AIConfigurationResponse,
    AIGenerationResponse,
    AIRequestListItem,
    AIRequestListResponse,
    AIRequestResponse,
    AIUsageResponse,
)
from app.services.ai_content.adaptation_service import AIContentAdaptationService
from app.services.ai_content.schemas import AdaptRequest
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/ai-content", tags=["ai-content"])


@router.post(
    "/content/{content_id}/adapt",
    response_model=AIRequestResponse,
)
async def adapt_content(
    content_id: UUID,
    body: AdaptContentRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AIContentAdaptationService.adapt(
            db,
            user.tenant_id,
            AdaptRequest(
                content_id=content_id,
                platforms=body.platforms,
                locales=body.locales,
                length_profiles=body.length_profiles,
                brand_profile_version_id=body.brand_profile_version_id,
                approved_template_ids=body.approved_template_ids,
                quality_mode=body.quality_mode,
                idempotency_key=body.idempotency_key,
            ),
            requested_by=user.id,
        ),
        label="ai_content.adapt",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return AIRequestResponse(**result)


@router.get(
    "/content/{content_id}/requests",
    response_model=AIRequestListResponse,
)
async def list_adaptation_requests(
    content_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items = await run_guarded(
        AIContentAdaptationService.list_requests_for_content(
            db, user.tenant_id, content_id,
        ),
        label="ai_content.list_requests",
    )
    return AIRequestListResponse(
        items=[AIRequestListItem(**i) for i in items],
        total=len(items),
    )


@router.get(
    "/requests/{request_id}",
    response_model=AIRequestResponse,
)
async def get_adaptation_request(
    request_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AIContentAdaptationService.get_request_detail(
            db, user.tenant_id, request_id,
        ),
        label="ai_content.get_request",
    )
    return AIRequestResponse(**result)


@router.get(
    "/generations/{generation_id}",
    response_model=AIGenerationResponse,
)
async def get_generation(
    generation_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AIContentAdaptationService.get_generation(
            db, user.tenant_id, generation_id,
        ),
        label="ai_content.get_generation",
    )
    return AIGenerationResponse(**result)


@router.post(
    "/requests/{request_id}/retry",
    response_model=AIRequestResponse,
)
async def retry_adaptation_request(
    request_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AIContentAdaptationService.retry_request(
            db, user.tenant_id, request_id, requested_by=user.id,
        ),
        label="ai_content.retry",
        timeout=SCAN_TIMEOUT_SEC,
    )
    await db.commit()
    return AIRequestResponse(**result)


@router.get(
    "/configuration",
    response_model=AIConfigurationResponse,
)
async def get_ai_configuration(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AIContentAdaptationService.get_configuration(db, user.tenant_id),
        label="ai_content.configuration",
    )
    return AIConfigurationResponse(**result)


@router.get(
    "/usage",
    response_model=AIUsageResponse,
)
async def get_ai_usage(
    days: int = Query(30, ge=1, le=90),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        AIContentAdaptationService.get_usage(db, user.tenant_id, days=days),
        label="ai_content.usage",
    )
    return AIUsageResponse(**result)
