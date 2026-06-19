"""Client billing plans and monthly usage from content_items."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.content import ContentItem
from app.schemas.billing import ClientBillingUpdate

logger = logging.getLogger(__name__)

BILLING_STATUSES = frozenset({"active", "unpaid", "paused"})
NEAR_LIMIT_RATIO = 0.8


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_cycle(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or _utc_now()
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    last_day = monthrange(now.year, now.month)[1]
    end = datetime(now.year, now.month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def resolve_billing_cycle(client: Client) -> tuple[datetime, datetime]:
    if client.billing_cycle_start and client.billing_cycle_end:
        start = client.billing_cycle_start
        end = client.billing_cycle_end
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return start, end
    return _default_cycle()


def _posts_remaining(limit: int | None, published: int) -> int | None:
    if limit is None or limit <= 0:
        return None
    return max(0, limit - published)


def _is_near_limit(limit: int | None, published: int) -> bool:
    if limit is None or limit <= 0:
        return False
    return published >= int(limit * NEAR_LIMIT_RATIO)


class BillingService:
    @staticmethod
    async def _usage_counts(
        db: AsyncSession,
        client_id: UUID,
        cycle_start: datetime,
        cycle_end: datetime,
    ) -> tuple[int, int]:
        created = await db.scalar(
            select(func.count())
            .select_from(ContentItem)
            .where(
                ContentItem.client_id == client_id,
                ContentItem.created_at >= cycle_start,
                ContentItem.created_at <= cycle_end,
            )
        )
        published = await db.scalar(
            select(func.count())
            .select_from(ContentItem)
            .where(
                ContentItem.client_id == client_id,
                ContentItem.published_at.isnot(None),
                ContentItem.published_at >= cycle_start,
                ContentItem.published_at <= cycle_end,
            )
        )
        return int(created or 0), int(published or 0)

    @staticmethod
    def _billing_status(client: Client) -> str:
        status = (client.billing_status or "active").lower()
        return status if status in BILLING_STATUSES else "active"

    @staticmethod
    def _monthly_fee(client: Client) -> float | None:
        if client.monthly_fee is None:
            return None
        return float(client.monthly_fee)

    @staticmethod
    async def _build_client_billing(
        db: AsyncSession,
        client: Client,
    ) -> dict[str, Any]:
        cycle_start, cycle_end = resolve_billing_cycle(client)
        created, published = await BillingService._usage_counts(
            db, client.id, cycle_start, cycle_end,
        )
        limit = client.monthly_post_limit
        remaining = _posts_remaining(limit, published)
        near_limit = _is_near_limit(limit, published)
        return {
            "client_id": client.id,
            "company_name": client.company_name,
            "plan_name": client.plan_name,
            "monthly_fee": BillingService._monthly_fee(client),
            "monthly_post_limit": limit,
            "billing_status": BillingService._billing_status(client),
            "billing_cycle_start": client.billing_cycle_start or cycle_start,
            "billing_cycle_end": client.billing_cycle_end or cycle_end,
            "usage": {
                "posts_created_this_cycle": created,
                "posts_published_this_cycle": published,
                "posts_remaining": remaining,
            },
            "near_limit": near_limit,
        }

    @staticmethod
    async def get_client_billing(db: AsyncSession, client_id: UUID) -> dict[str, Any]:
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        return await BillingService._build_client_billing(db, client)

    @staticmethod
    async def update_client_billing(
        db: AsyncSession,
        client_id: UUID,
        data: ClientBillingUpdate,
    ) -> dict[str, Any]:
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")

        updates = data.model_dump(exclude_unset=True)
        if "billing_status" in updates and updates["billing_status"] not in BILLING_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid billing_status")

        for field, value in updates.items():
            setattr(client, field, value)

        await db.commit()
        await db.refresh(client)
        logger.info("[Billing] updated: client=%s fields=%s", client_id, list(updates.keys()))
        return await BillingService._build_client_billing(db, client)

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        result = await db.execute(select(Client).order_by(Client.company_name))
        clients = list(result.scalars().all())

        active_clients = 0
        unpaid_clients = 0
        mrr = 0.0
        total_posts_used = 0
        usage_rows: list[dict[str, Any]] = []

        for client in clients:
            billing_status = BillingService._billing_status(client)
            if billing_status == "active":
                active_clients += 1
                fee = BillingService._monthly_fee(client)
                if fee:
                    mrr += fee
            elif billing_status == "unpaid":
                unpaid_clients += 1

            row = await BillingService._build_client_billing(db, client)
            usage_rows.append({
                "client_id": row["client_id"],
                "company_name": row["company_name"],
                "plan_name": row["plan_name"],
                "billing_status": row["billing_status"],
                "monthly_post_limit": row["monthly_post_limit"],
                "posts_created_this_cycle": row["usage"]["posts_created_this_cycle"],
                "posts_published_this_cycle": row["usage"]["posts_published_this_cycle"],
                "posts_remaining": row["usage"]["posts_remaining"],
                "near_limit": row["near_limit"],
            })
            total_posts_used += row["usage"]["posts_published_this_cycle"]

        near_limit_clients = [r for r in usage_rows if r["near_limit"]]

        return {
            "active_clients": active_clients,
            "unpaid_clients": unpaid_clients,
            "monthly_recurring_revenue": round(mrr, 2),
            "total_posts_used": total_posts_used,
            "clients_near_limit": near_limit_clients,
            "usage_by_client": usage_rows,
        }
