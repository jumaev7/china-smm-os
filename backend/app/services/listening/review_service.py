"""Human review workflow for observed mentions (internal state only)."""
from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listening import REVIEW_STATES, TenantMentionReview, TenantObservedMention
from app.services.listening.errors import InvalidReviewStateError, MentionNotFoundError


async def set_review_state(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    mention_id: UUID,
    new_state: str,
    actor_user_id: UUID | None,
    note: str | None = None,
) -> tuple[TenantObservedMention, TenantMentionReview]:
    if new_state not in REVIEW_STATES:
        raise InvalidReviewStateError(f"invalid review state '{new_state}'")

    mention = (
        await db.execute(
            select(TenantObservedMention).where(
                TenantObservedMention.id == mention_id,
                TenantObservedMention.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if mention is None:
        raise MentionNotFoundError("observed mention not found")

    previous = mention.review_state
    mention.review_state = new_state
    review = TenantMentionReview(
        id=uuid4(),
        tenant_id=tenant_id,
        mention_id=mention.id,
        actor_user_id=actor_user_id,
        previous_state=previous,
        new_state=new_state,
        note=(note or "").strip()[:4000] or None,
    )
    db.add(review)
    await db.flush()
    return mention, review


async def list_reviews(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    mention_id: UUID,
    limit: int = 50,
) -> list[TenantMentionReview]:
    mention = (
        await db.execute(
            select(TenantObservedMention.id).where(
                TenantObservedMention.id == mention_id,
                TenantObservedMention.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if mention is None:
        raise MentionNotFoundError("observed mention not found")

    return list(
        (
            await db.execute(
                select(TenantMentionReview)
                .where(
                    TenantMentionReview.tenant_id == tenant_id,
                    TenantMentionReview.mention_id == mention_id,
                )
                .order_by(TenantMentionReview.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )


__all__ = ["set_review_state", "list_reviews"]
