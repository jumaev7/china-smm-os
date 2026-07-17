"""Persist AI adaptation output as immutable content variants."""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.content_optimizer import (
    TenantContentOptimizationRun,
    TenantContentVariant,
    TenantContentVariantTransformation,
)
from app.services.ai_content.schemas import FactualValidationResult
from app.services.ai_platform.structured_output import PlatformAdaptationOutput
from app.services.content_optimizer import hashtag_optimizer as ht
from app.services.content_optimizer.variant_fingerprint import compute_variant_fingerprint
from app.services.publishing_intelligence.platform_policies import POLICY_CATALOG_VERSION
from app.services.publishing_intelligence.review_engine import PublishingReviewEngine

logger = logging.getLogger(__name__)

AI_OPTIMIZER_VERSION = "ai-1.0.0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_ai_variant(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    item: ContentItem,
    run: TenantContentOptimizationRun,
    output: PlatformAdaptationOutput,
    source_fingerprint: str,
    ai_request_id: UUID,
    ai_generation_id: UUID,
    brand_profile_version_id: UUID | None,
    prompt_key: str,
    prompt_version: str,
    model_alias: str,
    resolved_provider: str,
    resolved_model: str,
    factual: FactualValidationResult,
    safety_status: str,
    source_score: int | None,
    created_by: UUID | None = None,
) -> TenantContentVariant:
    """Create an immutable AI-assisted variant. Never applies/publishes/approves."""
    vfp = compute_variant_fingerprint(
        platform=output.platform,
        locale=output.locale,
        length_profile=output.length_profile,
        caption=output.caption,
        hashtags=list(output.hashtags or []),
        cta=output.cta,
        link=output.link,
        optimizer_version=AI_OPTIMIZER_VERSION,
        policy_version=POLICY_CATALOG_VERSION,
    )
    variant = TenantContentVariant(
        id=uuid4(),
        tenant_id=tenant_id,
        optimization_run_id=run.id,
        content_id=item.id,
        platform=output.platform,
        locale=output.locale,
        length_profile=output.length_profile,
        variant_version=1,
        caption=output.caption,
        hashtags=list(output.hashtags or []),
        cta=output.cta,
        link=output.link,
        source_fingerprint=source_fingerprint,
        variant_fingerprint=vfp,
        status="generated",
        generation_method="ai_assisted",
        ai_request_id=ai_request_id,
        ai_generation_id=ai_generation_id,
        brand_profile_version_id=brand_profile_version_id,
        prompt_key=prompt_key,
        prompt_version=prompt_version,
        model_alias=model_alias,
        resolved_provider=resolved_provider,
        resolved_model=resolved_model,
        factual_validation_status=factual.status,
        safety_validation_status=safety_status,
        source_score=source_score,
        created_at=_utcnow(),
    )
    db.add(variant)
    await db.flush()

    for i, t in enumerate(output.transformations):
        db.add(
            TenantContentVariantTransformation(
                id=uuid4(),
                tenant_id=tenant_id,
                content_variant_id=variant.id,
                sequence=i,
                operation_key=t.type,
                category="ai_assisted",
                reason_key=t.reason,
                reason_params={"source_sections": t.source_sections},
                result_summary=t.reason[:240],
            )
        )

    base_ctx = PublishingReviewEngine.build_context(item, tenant_id)
    variant_ctx = replace(
        base_ctx,
        platforms=[output.platform],
        captions={output.locale: output.caption},
        primary_language=output.locale,
        hashtags=[ht.normalize_tag(t).casefold() for t in (output.hashtags or [])],
        hashtags_raw=" ".join(ht.render_hashtag(t) for t in (output.hashtags or [])),
        link=output.link,
        cta_hint=output.cta,
    )
    try:
        review = await PublishingReviewEngine.create_review_from_context(
            db,
            tenant_id,
            item.id,
            variant_ctx,
            created_by=created_by,
            variant_review=True,
            emit_signals=False,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("AI variant scoring failed content=%s", item.id)
        review = None

    if review is not None:
        variant.publishing_review_id = review.review_id
        variant.variant_score = review.overall_score
        if source_score is not None and review.overall_score is not None:
            variant.score_delta = int(review.overall_score) - int(source_score)
        variant.publish_readiness = review.publish_readiness
        variant.category_deltas = {
            key: cs.score
            for key, cs in (review.category_scores or {}).items()
            if getattr(cs, "applicable", True)
        }
    await db.flush()
    return variant
