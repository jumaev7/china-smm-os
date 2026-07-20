"""Advisory readiness for slot assignments.

This module NEVER redefines hard publish readiness. It reuses:
- ``PublishSafetyService`` — authoritative hard readiness (blockers).
- ``PublishingReviewEngine`` — deterministic advisory Publishing Score.

Readiness here is advisory metadata attached to an assignment. It never schedules,
publishes, or approves content.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem

logger = logging.getLogger(__name__)

READINESS_ENGINE_VERSION = "1.0.0"

_LOCALE_CAPTION_FIELDS = {
    "en": ("caption_long_en", "caption_short_en"),
    "ru": ("caption_long_ru", "caption_short_ru"),
    "uz": ("caption_long_uz", "caption_short_uz"),
    "zh": ("caption_long_en", "caption_short_en"),  # zh falls back to en source captions
}


@dataclass
class ReadinessResult:
    status: str                       # ready | ready_with_warnings | blocked | unknown
    score: int | None = None
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    publishing_review_id: UUID | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _has_locale_caption(item: ContentItem, locale: str) -> bool:
    for field_name in _LOCALE_CAPTION_FIELDS.get(locale, ("caption_long_en", "caption_short_en")):
        if (getattr(item, field_name, None) or "").strip():
            return True
    return False


class ReadinessService:
    @staticmethod
    async def evaluate(
        db: AsyncSession,
        tenant_id: UUID,
        item: ContentItem,
        *,
        platform: str,
        locale: str,
        run_publish_safety: bool = True,
    ) -> ReadinessResult:
        warnings: list[str] = []
        blockers: list[str] = []
        review_id: UUID | None = None
        score: int | None = None

        # --- content-shape checks (advisory)
        if not _has_locale_caption(item, locale):
            warnings.append(f"content_missing_caption_for_locale:{locale}")
        targeted = [p for p in (item.platforms or [])]
        if targeted and platform not in targeted:
            warnings.append(f"content_not_targeted_for_platform:{platform}")

        # --- advisory Publishing Score via deterministic review engine
        try:
            from app.services.publishing_intelligence.review_engine import PublishingReviewEngine

            ctx = PublishingReviewEngine.build_context(item, tenant_id)
            review = await PublishingReviewEngine.create_review_from_context(
                db, tenant_id, item.id, ctx, created_by=None,
                variant_review=True, emit_signals=False,
            )
            if review is not None:
                score = getattr(review, "overall_score", None)
                review_id = getattr(review, "id", None)
        except Exception:  # pragma: no cover - advisory only
            logger.debug("advisory publishing review failed for content=%s", getattr(item, "id", None))

        # --- authoritative hard readiness (PublishSafety) — advisory reporting only
        if run_publish_safety:
            try:
                from app.services.publish_safety_service import PublishSafetyService

                result = await PublishSafetyService.evaluate(
                    db, item, target_platforms=[platform], mode="manual_publish",
                )
                if not result.get("passed", True):
                    for b in (result.get("blockers") or [])[:10]:
                        blockers.append(str(b))
                for w in (result.get("warnings") or [])[:10]:
                    warnings.append(str(w))
            except Exception:  # pragma: no cover - advisory only
                logger.debug("publish safety advisory check failed for content=%s", getattr(item, "id", None))

        if blockers:
            status = "blocked"
        elif warnings:
            status = "ready_with_warnings"
        elif score is not None:
            status = "ready"
        else:
            status = "unknown"

        return ReadinessResult(
            status=status,
            score=score,
            warnings=warnings[:20],
            blockers=blockers[:20],
            publishing_review_id=review_id,
            detail={"engine_version": READINESS_ENGINE_VERSION, "platform": platform, "locale": locale},
        )
