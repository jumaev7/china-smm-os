"""Analyst review persistence for computed MarketInsight identities."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listening import TenantListeningInsightReview
from app.services.listening.analytics.contracts import INSIGHT_REVIEW_STATES
from app.services.listening.errors import InvalidReviewStateError, ListeningError


class InsightReviewNotFoundError(ListeningError):
    code = "listening_insight_review_not_found"
    http_status = 404


async def load_review_state_map(db: AsyncSession, tenant_id: UUID) -> dict[str, str]:
    """Return latest review state per insight_key for the tenant."""
    rows = list(
        (
            await db.execute(
                select(TenantListeningInsightReview)
                .where(TenantListeningInsightReview.tenant_id == tenant_id)
                .order_by(
                    TenantListeningInsightReview.insight_key.asc(),
                    TenantListeningInsightReview.created_at.desc(),
                )
            )
        ).scalars().all()
    )
    latest: dict[str, str] = {}
    for row in rows:
        if row.insight_key not in latest:
            latest[row.insight_key] = row.new_state
    return latest


async def get_latest_review(
    db: AsyncSession,
    tenant_id: UUID,
    insight_key: str,
) -> TenantListeningInsightReview | None:
    return (
        await db.execute(
            select(TenantListeningInsightReview)
            .where(
                TenantListeningInsightReview.tenant_id == tenant_id,
                TenantListeningInsightReview.insight_key == insight_key,
            )
            .order_by(TenantListeningInsightReview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def set_insight_review_state(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    insight_key: str,
    new_state: str,
    actor_user_id: UUID | None,
    note: str | None = None,
    window_json: dict[str, Any] | None = None,
    methodology_version: str | None = None,
) -> TenantListeningInsightReview:
    if new_state not in INSIGHT_REVIEW_STATES:
        raise InvalidReviewStateError(
            f"invalid insight review state: {new_state}",
            details={"allowed": sorted(INSIGHT_REVIEW_STATES)},
        )
    if not insight_key or len(insight_key) > 80:
        raise InvalidReviewStateError("invalid insight_key")

    latest = await get_latest_review(db, tenant_id, insight_key)
    previous = latest.new_state if latest is not None else "unreviewed"
    if previous == new_state and not (note or "").strip():
        return latest  # type: ignore[return-value]

    row = TenantListeningInsightReview(
        id=uuid4(),
        tenant_id=tenant_id,
        insight_key=insight_key,
        actor_user_id=actor_user_id,
        previous_state=previous,
        new_state=new_state,
        note=(note or None),
        window_json=window_json,
        methodology_version=methodology_version,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def list_insight_reviews(
    db: AsyncSession,
    tenant_id: UUID,
    insight_key: str,
    *,
    limit: int = 25,
) -> list[TenantListeningInsightReview]:
    return list(
        (
            await db.execute(
                select(TenantListeningInsightReview)
                .where(
                    TenantListeningInsightReview.tenant_id == tenant_id,
                    TenantListeningInsightReview.insight_key == insight_key,
                )
                .order_by(TenantListeningInsightReview.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )
