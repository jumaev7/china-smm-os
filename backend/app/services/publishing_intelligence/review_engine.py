"""Publishing review engine — load, evaluate, persist immutable snapshots."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.content import ContentItem
from app.models.media import MediaFile
from app.models.publishing_account import PublishingAccount
from app.models.publishing_intelligence import (
    TenantPublishingPlatformReview,
    TenantPublishingReview,
    TenantPublishingReviewCheck,
)
from app.services.automation_domain_events import emit_domain_event
from app.services.publishing_intelligence.checks import run_all_checks
from app.services.publishing_intelligence.content_fingerprint import compute_content_fingerprint
from app.services.publishing_intelligence.platform_policies import (
    LOW_SCORE_THRESHOLD,
    PLATFORM_FIT_LOW_THRESHOLD,
    SUPPORTED_PLATFORMS,
)
from app.services.publishing_intelligence.score_engine import (
    SCORE_ENGINE_VERSION,
    build_recommendations,
    compute_category_scores,
    compute_overall_score,
    compute_platform_reviews,
)
from app.services.publishing_intelligence.schemas import (
    CategoryScore,
    CheckResult,
    RecommendationItem,
    ReviewContext,
    ReviewEngineResult,
)
from app.services.publishing_tenant_scope import tenant_id_for_content
from app.services.publish_safety_service import PublishSafetyService

logger = logging.getLogger(__name__)

REVIEW_ENGINE_VERSION = "1.0.0"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_hashtags(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,;\s]+", raw.strip())
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        tag = part.strip().lstrip("#").lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _extract_keywords_from_notes(notes: str | None) -> list[str]:
    """Optional keyword list from internal_notes prefix `keywords:` — explicit only."""
    if not notes:
        return []
    for line in notes.splitlines():
        if line.lower().startswith("keywords:"):
            payload = line.split(":", 1)[1]
            return [p.strip().lower() for p in payload.split(",") if p.strip()]
    return []


def _primary_language(captions: dict[str, str]) -> str | None:
    for lang in ("en", "ru", "uz", "zh"):
        if captions.get(lang):
            return lang
    return next(iter(captions.keys()), None)


class PublishingReviewEngine:
    """Orchestrates deterministic pre-publish reviews (caller owns commit)."""

    version = REVIEW_ENGINE_VERSION

    @staticmethod
    async def _load_content_for_tenant(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
    ) -> ContentItem:
        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.media_file))
            .where(ContentItem.id == content_id)
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Content not found")
        content_tenant = await tenant_id_for_content(db, item)
        if content_tenant != tenant_id:
            raise HTTPException(status_code=404, detail="Content not found")
        return item

    @staticmethod
    def build_context(item: ContentItem, tenant_id: UUID) -> ReviewContext:
        captions: dict[str, str] = {}
        for lang, short_attr, long_attr in (
            ("ru", "caption_short_ru", "caption_long_ru"),
            ("uz", "caption_short_uz", "caption_long_uz"),
            ("en", "caption_short_en", "caption_long_en"),
        ):
            long_val = getattr(item, long_attr, None) or ""
            short_val = getattr(item, short_attr, None) or ""
            text = (long_val or short_val).strip()
            if text:
                captions[lang] = text

        media_payload = None
        content_type = "text"
        mf: MediaFile | None = item.media_file
        if mf is not None:
            content_type = mf.file_type or "unknown"
            media_payload = {
                "id": mf.id,
                "file_type": mf.file_type,
                "mime_type": mf.mime_type,
                "file_size": mf.file_size,
                "thumbnail_present": bool(mf.thumbnail_path),
                "upload_complete": bool(mf.storage_path),
                "has_storage_path": bool(mf.storage_path),
            }
        elif item.media_file_id:
            content_type = "unknown"
            media_payload = {
                "id": item.media_file_id,
                "file_type": None,
                "mime_type": None,
                "file_size": 0,
                "thumbnail_present": False,
                "upload_complete": False,
                "has_storage_path": False,
            }

        platforms = [p for p in (item.platforms or []) if p in SUPPORTED_PLATFORMS]
        return ReviewContext(
            content_id=item.id,
            tenant_id=tenant_id,
            status=item.status or "draft",
            platforms=platforms,
            captions=captions,
            primary_language=_primary_language(captions),
            hashtags_raw=item.hashtags or "",
            hashtags=_parse_hashtags(item.hashtags),
            scheduled_for=item.scheduled_for,
            approved_at=item.approved_at,
            client_review_status=item.client_review_status,
            media=media_payload,
            content_type=content_type,
            keywords=_extract_keywords_from_notes(item.internal_notes),
            cta_hint=None,
            link=None,
        )

    @staticmethod
    async def _account_statuses(
        db: AsyncSession,
        tenant_id: UUID,
        platforms: list[str],
    ) -> dict[str, str]:
        if not platforms:
            return {}
        result = await db.execute(
            select(PublishingAccount.platform, PublishingAccount.status).where(
                PublishingAccount.tenant_id == tenant_id,
                PublishingAccount.platform.in_(platforms),
            )
        )
        status_map: dict[str, str] = {}
        for platform, status in result.all():
            # Prefer connected over other statuses if multiple accounts
            current = status_map.get(platform)
            if current == "connected":
                continue
            if status == "connected" or current is None:
                status_map[platform] = status
        return status_map

    @staticmethod
    async def _next_version(db: AsyncSession, content_id: UUID) -> int:
        result = await db.execute(
            select(func.coalesce(func.max(TenantPublishingReview.review_version), 0)).where(
                TenantPublishingReview.content_id == content_id,
            )
        )
        return int(result.scalar_one()) + 1

    @staticmethod
    async def _supersede_previous(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
        *,
        now: datetime,
    ) -> None:
        await db.execute(
            update(TenantPublishingReview)
            .where(
                TenantPublishingReview.tenant_id == tenant_id,
                TenantPublishingReview.content_id == content_id,
                TenantPublishingReview.status == "completed",
            )
            .values(status="superseded", superseded_at=now)
        )

    @staticmethod
    async def mark_stale_if_fingerprint_mismatch(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
    ) -> TenantPublishingReview | None:
        """Mark latest completed review stale when content fingerprint changed."""
        item = await PublishingReviewEngine._load_content_for_tenant(db, tenant_id, content_id)
        ctx = PublishingReviewEngine.build_context(item, tenant_id)
        fingerprint = compute_content_fingerprint(ctx)
        latest = await PublishingReviewEngine.get_latest_row(db, tenant_id, content_id)
        if latest is None:
            return None
        if latest.status == "completed" and latest.content_fingerprint != fingerprint:
            latest.status = "stale"
            await emit_domain_event(
                db,
                "tenant.publishing.review_became_stale",
                tenant_id,
                payload={
                    "content_id": str(content_id),
                    "review_id": str(latest.id),
                    "overall_score": latest.overall_score,
                    "review_engine_version": latest.review_engine_version,
                },
                resource_type="publishing_review",
                resource_id=str(latest.id),
                title="Publishing review became stale",
            )
        return latest

    @staticmethod
    async def create_review(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
        *,
        created_by: UUID | None = None,
    ) -> ReviewEngineResult:
        item = await PublishingReviewEngine._load_content_for_tenant(db, tenant_id, content_id)
        ctx = PublishingReviewEngine.build_context(item, tenant_id)
        fingerprint = compute_content_fingerprint(ctx)
        account_statuses = await PublishingReviewEngine._account_statuses(
            db, tenant_id, ctx.platforms,
        )
        checks = run_all_checks(ctx, account_status_by_platform=account_statuses)
        category_scores = compute_category_scores(checks)
        overall, score_meta = compute_overall_score(category_scores)
        platform_reviews = compute_platform_reviews(ctx.platforms, checks, category_scores)
        recommendations = build_recommendations(checks)

        # Hard publish readiness from existing safety (advisory score never blocks alone)
        publish_readiness = await PublishingReviewEngine._publish_readiness(
            db, item, ctx.platforms,
        )

        now = _utcnow()
        await PublishingReviewEngine._supersede_previous(db, tenant_id, content_id, now=now)
        version = await PublishingReviewEngine._next_version(db, content_id)

        warning_count = sum(1 for c in checks if c.status == "warning")
        failure_count = sum(1 for c in checks if c.status == "failed")
        critical_count = sum(
            1 for c in checks if c.status == "failed" and c.severity in {"critical", "error"}
        )

        summary = {
            "overall_score": overall,
            "warning_count": warning_count,
            "failure_count": failure_count,
            "critical_issue_count": critical_count,
            "category_scores": {
                k: {"score": v.score, "applicable": v.applicable, "weight": v.weight}
                for k, v in category_scores.items()
            },
            "platform_scores": {p.platform: p.platform_score for p in platform_reviews},
            "recommendation_keys": [r.key for r in recommendations[:20]],
            "publish_readiness": publish_readiness,
            "score_meta": score_meta,
            "score_engine_version": SCORE_ENGINE_VERSION,
            "advisory": True,
            "notes": [
                "Publishing Score is advisory and does not replace hard publish validation.",
                "Phase 1 checks are deterministic rule-based heuristics — not AI understanding.",
            ],
        }

        review = TenantPublishingReview(
            id=uuid4(),
            tenant_id=tenant_id,
            content_id=content_id,
            review_version=version,
            review_engine_version=REVIEW_ENGINE_VERSION,
            content_fingerprint=fingerprint,
            overall_score=overall,
            status="completed",
            primary_language=ctx.primary_language,
            target_platforms=list(ctx.platforms),
            summary=summary,
            created_by=created_by,
            created_at=now,
            completed_at=now,
        )
        db.add(review)
        await db.flush()

        for c in checks:
            db.add(
                TenantPublishingReviewCheck(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    publishing_review_id=review.id,
                    check_key=c.check_key,
                    category=c.category,
                    severity=c.severity,
                    status=c.status,
                    score=c.score,
                    weight=c.weight,
                    evidence=c.evidence,
                    recommendation_key=c.recommendation_key,
                    recommendation_params=c.recommendation_params,
                    created_at=now,
                )
            )
        for pr in platform_reviews:
            db.add(
                TenantPublishingPlatformReview(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    publishing_review_id=review.id,
                    platform=pr.platform,
                    platform_score=pr.platform_score,
                    caption_score=pr.caption_score,
                    media_score=pr.media_score,
                    cta_score=pr.cta_score,
                    hashtag_score=pr.hashtag_score,
                    language_score=pr.language_score,
                    compliance_score=pr.compliance_score,
                    recommendations=pr.recommendations,
                    created_at=now,
                )
            )
        await db.flush()

        await PublishingReviewEngine._emit_intelligence_signals(
            db,
            tenant_id=tenant_id,
            review=review,
            platform_reviews=platform_reviews,
            warning_count=warning_count,
            failure_count=failure_count,
            critical_count=critical_count,
        )

        return PublishingReviewEngine._to_result(
            review,
            checks=checks,
            category_scores=category_scores,
            platform_reviews=platform_reviews,
            recommendations=recommendations,
            fingerprint_current=fingerprint,
        )

    @staticmethod
    async def _publish_readiness(
        db: AsyncSession,
        item: ContentItem,
        platforms: list[str],
    ) -> str:
        try:
            safety = await PublishSafetyService.evaluate(
                db,
                item,
                target_platforms=platforms or list(item.platforms or []),
                mode="manual_publish",
            )
        except Exception:
            logger.exception("publish safety evaluate failed during review")
            return "ready_with_warnings"

        if safety.get("passed"):
            return "ready"
        errors = safety.get("errors") or []
        critical = [e for e in errors if e.get("critical")]
        if critical:
            return "blocked"
        return "ready_with_warnings"

    @staticmethod
    async def _emit_intelligence_signals(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        review: TenantPublishingReview,
        platform_reviews: list,
        warning_count: int,
        failure_count: int,
        critical_count: int,
    ) -> None:
        base_payload = {
            "content_id": str(review.content_id),
            "review_id": str(review.id),
            "overall_score": review.overall_score,
            "platform_scores": {p.platform: p.platform_score for p in platform_reviews},
            "warning_count": warning_count,
            "failure_count": failure_count,
            "critical_issue_count": critical_count,
            "review_engine_version": review.review_engine_version,
            "review_version": review.review_version,
        }
        await emit_domain_event(
            db,
            "tenant.publishing.review_completed",
            tenant_id,
            payload=base_payload,
            resource_type="publishing_review",
            resource_id=str(review.id),
            title="Publishing review completed",
        )
        if review.overall_score < LOW_SCORE_THRESHOLD:
            await emit_domain_event(
                db,
                "tenant.publishing.score_low",
                tenant_id,
                payload=base_payload,
                resource_type="publishing_review",
                resource_id=str(review.id),
                title="Publishing score low",
            )
        if critical_count > 0:
            await emit_domain_event(
                db,
                "tenant.publishing.critical_issue_detected",
                tenant_id,
                payload=base_payload,
                resource_type="publishing_review",
                resource_id=str(review.id),
                title="Publishing critical issue detected",
            )
        low_fit = [p for p in platform_reviews if p.platform_score < PLATFORM_FIT_LOW_THRESHOLD]
        if low_fit:
            await emit_domain_event(
                db,
                "tenant.publishing.platform_fit_low",
                tenant_id,
                payload={
                    **base_payload,
                    "low_fit_platforms": [p.platform for p in low_fit],
                },
                resource_type="publishing_review",
                resource_id=str(review.id),
                title="Publishing platform fit low",
            )

    @staticmethod
    async def get_latest_row(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
    ) -> TenantPublishingReview | None:
        result = await db.execute(
            select(TenantPublishingReview)
            .where(
                TenantPublishingReview.tenant_id == tenant_id,
                TenantPublishingReview.content_id == content_id,
            )
            .order_by(TenantPublishingReview.review_version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_review(
        db: AsyncSession,
        tenant_id: UUID,
        review_id: UUID,
    ) -> ReviewEngineResult:
        result = await db.execute(
            select(TenantPublishingReview).where(
                TenantPublishingReview.id == review_id,
                TenantPublishingReview.tenant_id == tenant_id,
            )
        )
        review = result.scalar_one_or_none()
        if review is None:
            raise HTTPException(status_code=404, detail="Review not found")
        return await PublishingReviewEngine._hydrate(db, tenant_id, review)

    @staticmethod
    async def list_reviews(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ReviewEngineResult], int]:
        # Ensure content belongs to tenant
        await PublishingReviewEngine._load_content_for_tenant(db, tenant_id, content_id)
        count_result = await db.execute(
            select(func.count()).select_from(TenantPublishingReview).where(
                TenantPublishingReview.tenant_id == tenant_id,
                TenantPublishingReview.content_id == content_id,
            )
        )
        total = int(count_result.scalar_one())
        result = await db.execute(
            select(TenantPublishingReview)
            .where(
                TenantPublishingReview.tenant_id == tenant_id,
                TenantPublishingReview.content_id == content_id,
            )
            .order_by(TenantPublishingReview.review_version.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        rows = list(result.scalars().all())
        items = [await PublishingReviewEngine._hydrate(db, tenant_id, row) for row in rows]
        return items, total

    @staticmethod
    async def get_latest(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
        *,
        refresh_stale: bool = True,
    ) -> ReviewEngineResult | None:
        if refresh_stale:
            await PublishingReviewEngine.mark_stale_if_fingerprint_mismatch(
                db, tenant_id, content_id,
            )
        row = await PublishingReviewEngine.get_latest_row(db, tenant_id, content_id)
        if row is None:
            # Still validate content access
            await PublishingReviewEngine._load_content_for_tenant(db, tenant_id, content_id)
            return None
        return await PublishingReviewEngine._hydrate(db, tenant_id, row)

    @staticmethod
    async def _hydrate(
        db: AsyncSession,
        tenant_id: UUID,
        review: TenantPublishingReview,
    ) -> ReviewEngineResult:
        checks_result = await db.execute(
            select(TenantPublishingReviewCheck).where(
                TenantPublishingReviewCheck.tenant_id == tenant_id,
                TenantPublishingReviewCheck.publishing_review_id == review.id,
            )
        )
        check_rows = list(checks_result.scalars().all())
        checks = [
            CheckResult(
                check_key=c.check_key,
                category=c.category,
                status=c.status,
                severity=c.severity,
                score=c.score,
                weight=c.weight,
                evidence=c.evidence or {},
                recommendation_key=c.recommendation_key,
                recommendation_params=c.recommendation_params,
            )
            for c in check_rows
        ]

        platforms_result = await db.execute(
            select(TenantPublishingPlatformReview).where(
                TenantPublishingPlatformReview.tenant_id == tenant_id,
                TenantPublishingPlatformReview.publishing_review_id == review.id,
            )
        )
        platform_rows = list(platforms_result.scalars().all())
        from app.services.publishing_intelligence.schemas import PlatformReviewResult

        platform_reviews = [
            PlatformReviewResult(
                platform=p.platform,
                platform_score=p.platform_score,
                caption_score=p.caption_score,
                media_score=p.media_score,
                cta_score=p.cta_score,
                hashtag_score=p.hashtag_score,
                language_score=p.language_score,
                compliance_score=p.compliance_score,
                recommendations=list(p.recommendations or []),
            )
            for p in platform_rows
        ]

        category_scores = compute_category_scores(checks)
        recommendations = build_recommendations(checks)

        # Current fingerprint for stale/current flags
        try:
            item = await PublishingReviewEngine._load_content_for_tenant(
                db, tenant_id, review.content_id,
            )
            current_fp = compute_content_fingerprint(
                PublishingReviewEngine.build_context(item, tenant_id)
            )
        except HTTPException:
            current_fp = review.content_fingerprint

        return PublishingReviewEngine._to_result(
            review,
            checks=checks,
            category_scores=category_scores,
            platform_reviews=platform_reviews,
            recommendations=recommendations,
            fingerprint_current=current_fp,
        )

    @staticmethod
    def _to_result(
        review: TenantPublishingReview,
        *,
        checks: list[CheckResult],
        category_scores: dict[str, CategoryScore],
        platform_reviews: list,
        recommendations: list[RecommendationItem],
        fingerprint_current: str,
    ) -> ReviewEngineResult:
        is_stale = (
            review.status == "stale"
            or (
                review.status == "completed"
                and review.content_fingerprint != fingerprint_current
            )
        )
        is_current = review.status == "completed" and not is_stale
        summary = dict(review.summary or {})
        return ReviewEngineResult(
            review_id=review.id,
            content_id=review.content_id,
            review_version=review.review_version,
            review_engine_version=review.review_engine_version,
            content_fingerprint=review.content_fingerprint,
            overall_score=review.overall_score,
            status="stale" if is_stale and review.status == "completed" else review.status,
            is_current=is_current,
            is_stale=is_stale,
            primary_language=review.primary_language,
            target_platforms=list(review.target_platforms or []),
            summary=summary,
            category_scores=category_scores,
            platform_reviews=platform_reviews,
            checks=checks,
            recommendations=recommendations,
            publish_readiness=str(summary.get("publish_readiness") or "ready_with_warnings"),
            created_at=review.created_at,
            completed_at=review.completed_at,
        )

    @staticmethod
    def result_to_dict(result: ReviewEngineResult) -> dict[str, Any]:
        return {
            "review_id": str(result.review_id),
            "content_id": str(result.content_id),
            "review_version": result.review_version,
            "review_engine_version": result.review_engine_version,
            "content_fingerprint": result.content_fingerprint,
            "overall_score": result.overall_score,
            "status": result.status,
            "is_current": result.is_current,
            "is_stale": result.is_stale,
            "primary_language": result.primary_language,
            "target_platforms": result.target_platforms,
            "summary": result.summary,
            "category_scores": {
                k: {
                    "category": v.category,
                    "score": v.score,
                    "weight": v.weight,
                    "applicable": v.applicable,
                    "warning_count": v.warning_count,
                    "failure_count": v.failure_count,
                    "evidence": v.evidence,
                }
                for k, v in result.category_scores.items()
            },
            "platform_reviews": [
                {
                    "platform": p.platform,
                    "platform_score": p.platform_score,
                    "caption_score": p.caption_score,
                    "media_score": p.media_score,
                    "cta_score": p.cta_score,
                    "hashtag_score": p.hashtag_score,
                    "language_score": p.language_score,
                    "compliance_score": p.compliance_score,
                    "recommendations": p.recommendations,
                }
                for p in result.platform_reviews
            ],
            "checks": [
                {
                    "check_key": c.check_key,
                    "category": c.category,
                    "status": c.status,
                    "severity": c.severity,
                    "score": c.score,
                    "weight": c.weight,
                    "evidence": c.evidence,
                    "recommendation_key": c.recommendation_key,
                    "recommendation_params": c.recommendation_params,
                }
                for c in result.checks
            ],
            "recommendations": [r.to_dict() for r in result.recommendations],
            "publish_readiness": result.publish_readiness,
            "created_at": result.created_at.isoformat() if result.created_at else None,
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        }
