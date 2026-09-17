"""Exact old-image success-reader algorithms (source-equivalent commit).

Vendored from git show ${OLD_SOURCE_SHA} — do not "improve" these copies.
Blob SHA pins in constants.py must remain in sync.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publish_attempt import PublishAttempt
from app.services.publish_resilience import STATUS_SUCCESS


async def old_prior_live_successes(
    db: AsyncSession,
    content_id: UUID,
    platforms: list[str],
) -> dict[str, dict]:
    """338d3f96 PublishService._prior_live_successes (byte-logic equivalent).

    Response-only: requires non-mock/non-test response.platform_post_id.
    Durable external_post_id alone does NOT suppress.
    """
    if not platforms:
        return {}
    result = await db.execute(
        select(PublishAttempt)
        .where(
            PublishAttempt.content_id == content_id,
            PublishAttempt.platform.in_(platforms),
            PublishAttempt.status == "success",
        )
        .order_by(PublishAttempt.created_at.desc())
    )
    successes: dict[str, dict] = {}
    for attempt in result.scalars().all():
        if attempt.platform in successes or not attempt.response:
            continue
        try:
            payload = json.loads(attempt.response)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("mock") is True or payload.get("test") is True:
            continue
        if not payload.get("platform_post_id"):
            continue
        payload = dict(payload)
        payload["success"] = True
        payload["platform"] = attempt.platform
        payload["deduplicated"] = True
        payload["message"] = (
            payload.get("message") or "Already published; duplicate suppressed"
        )
        successes[attempt.platform] = payload
    return successes


async def old_find_live_success(
    db: AsyncSession,
    *,
    idempotency_key: str | None = None,
    content_id: UUID | None = None,
    platform: str | None = None,
    account_id: UUID | None = None,
) -> PublishAttempt | None:
    """338d3f96 PublishResilienceService.find_live_success.

    Durable external_post_id alone is treated as live success.
    Mock/test is only skipped on the response fallback path — durable ID
    with a mock response still suppresses (pre-F1 common-mode hazard).
    """
    query = select(PublishAttempt).where(
        PublishAttempt.status == STATUS_SUCCESS,
        or_(
            PublishAttempt.external_post_id.isnot(None),
            PublishAttempt.response.isnot(None),
        ),
    ).order_by(PublishAttempt.created_at.desc())
    if idempotency_key:
        query = query.where(PublishAttempt.idempotency_key == idempotency_key)
    else:
        if content_id is None or platform is None:
            return None
        query = query.where(
            PublishAttempt.content_id == content_id,
            PublishAttempt.platform == platform,
        )
        if account_id is not None:
            query = query.where(PublishAttempt.account_id == account_id)
    result = await db.execute(query)
    for attempt in result.scalars().all():
        post_id = attempt.external_post_id
        if not post_id and attempt.response:
            try:
                payload = json.loads(attempt.response)
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if isinstance(payload, dict):
                if payload.get("mock") is True or payload.get("test") is True:
                    continue
                post_id = payload.get("platform_post_id")
        if post_id:
            return attempt
    return None


def old_shape_already_published(
    prior: Any,
    *,
    platform: str,
    account_id: UUID | None,
    account_name: str | None,
) -> dict[str, Any]:
    """338d3f96 claim skip payload (prefers durable, else response id)."""
    post_id = prior.external_post_id
    post_url = prior.external_post_url
    if not post_id and prior.response:
        try:
            payload = json.loads(prior.response)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if isinstance(payload, dict):
            post_id = payload.get("platform_post_id")
            post_url = post_url or payload.get("post_url")
    return {
        "platform": platform,
        "success": True,
        "platform_post_id": post_id,
        "post_url": post_url,
        "mock": False,
        "deduplicated": True,
        "message": "Already published; duplicate suppressed",
        "account_id": str(account_id) if account_id else None,
        "account_name": account_name,
    }
