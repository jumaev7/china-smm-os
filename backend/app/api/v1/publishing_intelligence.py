"""Tenant-scoped Publishing Intelligence APIs — deterministic pre-publish review."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.publishing_intelligence import (
    CategoryScoreResponse,
    PlatformReviewResponse,
    PublishingCheckCatalogResponse,
    PublishingPolicyCatalogResponse,
    PublishingReviewListResponse,
    PublishingReviewResponse,
    PublishingValidateResponse,
    ReviewCheckResponse,
    ReviewRecommendationResponse,
)
from app.services.publishing_intelligence.platform_policies import check_catalog, list_policies
from app.services.publishing_intelligence.review_engine import PublishingReviewEngine
from app.services.publishing_intelligence.schemas import ReviewEngineResult
from app.services.publish_safety_service import PublishSafetyService
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/publishing-intelligence", tags=["publishing-intelligence"])


def _to_response(result: ReviewEngineResult) -> PublishingReviewResponse:
    return PublishingReviewResponse(
        review_id=result.review_id,
        content_id=result.content_id,
        review_version=result.review_version,
        review_engine_version=result.review_engine_version,
        content_fingerprint=result.content_fingerprint,
        overall_score=result.overall_score,
        status=result.status,
        is_current=result.is_current,
        is_stale=result.is_stale,
        primary_language=result.primary_language,
        target_platforms=result.target_platforms,
        summary=result.summary,
        category_scores={
            k: CategoryScoreResponse(
                category=v.category,
                score=v.score,
                weight=v.weight,
                applicable=v.applicable,
                warning_count=v.warning_count,
                failure_count=v.failure_count,
                evidence=v.evidence,
            )
            for k, v in result.category_scores.items()
        },
        platform_reviews=[
            PlatformReviewResponse(
                platform=p.platform,
                platform_score=p.platform_score,
                caption_score=p.caption_score,
                media_score=p.media_score,
                cta_score=p.cta_score,
                hashtag_score=p.hashtag_score,
                language_score=p.language_score,
                compliance_score=p.compliance_score,
                recommendations=p.recommendations,
            )
            for p in result.platform_reviews
        ],
        checks=[
            ReviewCheckResponse(
                check_key=c.check_key,
                category=c.category,
                status=c.status,
                severity=c.severity,
                score=c.score,
                weight=c.weight,
                evidence=c.evidence,
                recommendation_key=c.recommendation_key,
                recommendation_params=c.recommendation_params,
            )
            for c in result.checks
        ],
        recommendations=[
            ReviewRecommendationResponse(
                key=r.key,
                category=r.category,
                priority=r.priority,
                reason=r.reason,
                evidence_summary=r.evidence_summary,
                suggested_action=r.suggested_action,
                params=r.params,
            )
            for r in result.recommendations
        ],
        publish_readiness=result.publish_readiness,
        created_at=result.created_at,
        completed_at=result.completed_at,
    )


@router.post(
    "/content/{content_id}/review",
    response_model=PublishingReviewResponse,
)
async def create_publishing_review(
    content_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        PublishingReviewEngine.create_review(
            db,
            user.tenant_id,
            content_id,
            created_by=user.id,
        ),
        label="publishing_intelligence.review",
    )
    await db.commit()
    return _to_response(result)


@router.get(
    "/content/{content_id}/reviews",
    response_model=PublishingReviewListResponse,
)
async def list_publishing_reviews(
    content_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await run_guarded(
        PublishingReviewEngine.list_reviews(
            db,
            user.tenant_id,
            content_id,
            page=page,
            page_size=page_size,
        ),
        label="publishing_intelligence.list",
    )
    await db.commit()
    return PublishingReviewListResponse(
        items=[_to_response(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/content/{content_id}/reviews/latest",
    response_model=PublishingReviewResponse,
)
async def get_latest_publishing_review(
    content_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        PublishingReviewEngine.get_latest(db, user.tenant_id, content_id),
        label="publishing_intelligence.latest",
    )
    await db.commit()
    if result is None:
        raise HTTPException(status_code=404, detail="No publishing review found")
    return _to_response(result)


@router.get(
    "/reviews/{review_id}",
    response_model=PublishingReviewResponse,
)
async def get_publishing_review(
    review_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        PublishingReviewEngine.get_review(db, user.tenant_id, review_id),
        label="publishing_intelligence.get",
    )
    return _to_response(result)


@router.get("/policies", response_model=PublishingPolicyCatalogResponse)
async def get_publishing_policies(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user
    data = list_policies()
    return PublishingPolicyCatalogResponse(**data)


@router.get("/check-catalog", response_model=PublishingCheckCatalogResponse)
async def get_check_catalog(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user
    data = check_catalog()
    return PublishingCheckCatalogResponse(**data)


@router.post(
    "/content/{content_id}/validate",
    response_model=PublishingValidateResponse,
)
async def validate_publishing_readiness(
    content_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    """Hard-blocker validation distinct from persisted quality review."""
    latest = await PublishingReviewEngine.get_latest(db, user.tenant_id, content_id)
    item = await PublishingReviewEngine._load_content_for_tenant(
        db, user.tenant_id, content_id,
    )
    safety = await PublishSafetyService.evaluate(
        db,
        item,
        target_platforms=list(item.platforms or []),
        mode="manual_publish",
    )
    errors = safety.get("errors") or []
    critical = [e for e in errors if e.get("critical")]
    if safety.get("passed"):
        readiness = "ready"
    elif critical:
        readiness = "blocked"
    else:
        readiness = "ready_with_warnings"
    await db.commit()
    return PublishingValidateResponse(
        content_id=content_id,
        publish_readiness=readiness,
        overall_score=latest.overall_score if latest else None,
        is_advisory_score=True,
        hard_blockers=critical,
        notes=[
            "Publishing Score is advisory and does not replace hard publish validation.",
            "Hard blockers come from PublishSafetyService.",
        ],
    )
