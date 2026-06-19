"""Analytics aggregates from content_items, publish_attempts, and clients."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.services.analytics_cache import cached_async
from app.services.publishing_calendar_service import _pick_title

_HISTORY_DAYS = 30
_ACTIVITY_LIMIT = 25


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _range_start() -> datetime:
    return datetime.combine(
        _utc_today() - timedelta(days=_HISTORY_DAYS - 1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )


class AnalyticsService:
    @staticmethod
    async def overview(db: AsyncSession) -> dict:
        return await cached_async("analytics:overview", lambda: AnalyticsService._overview(db))

    @staticmethod
    async def platforms(db: AsyncSession) -> dict:
        return await cached_async("analytics:platforms", lambda: AnalyticsService._platforms(db))

    @staticmethod
    async def activity(db: AsyncSession) -> dict:
        return await cached_async("analytics:activity", lambda: AnalyticsService._activity(db))

    @staticmethod
    async def _count_by_status(db: AsyncSession) -> dict[str, int]:
        result = await db.execute(
            select(ContentItem.status, func.count())
            .group_by(ContentItem.status)
        )
        return {row[0]: row[1] for row in result.all()}

    @staticmethod
    async def _posts_over_time(db: AsyncSession) -> list[dict]:
        range_start = _range_start()
        day_expr = func.date_trunc("day", ContentItem.created_at)
        result = await db.execute(
            select(day_expr, func.count())
            .where(ContentItem.created_at >= range_start)
            .group_by(day_expr)
            .order_by(day_expr)
        )
        by_day: dict[date, int] = {}
        for row in result.all():
            day_val = row[0]
            if day_val is None:
                continue
            d = day_val.date() if hasattr(day_val, "date") else day_val
            by_day[d] = row[1]

        start = _utc_today() - timedelta(days=_HISTORY_DAYS - 1)
        return [
            {"date": start + timedelta(days=i), "count": by_day.get(start + timedelta(days=i), 0)}
            for i in range(_HISTORY_DAYS)
        ]

    @staticmethod
    async def _publish_success(db: AsyncSession) -> tuple[int, int, float]:
        result = await db.execute(
            select(PublishAttempt.status, func.count()).group_by(PublishAttempt.status)
        )
        counts = {row[0]: row[1] for row in result.all()}
        success = counts.get("success", 0)
        failed = counts.get("failed", 0)
        total = success + failed
        rate = round((success / total) * 100, 1) if total else 0.0
        return total, success, rate

    @staticmethod
    async def _most_active_clients(db: AsyncSession, *, limit: int = 8) -> list[dict]:
        result = await db.execute(
            select(
                ContentItem.client_id,
                Client.company_name,
                func.count(ContentItem.id).label("post_count"),
            )
            .join(Client, ContentItem.client_id == Client.id)
            .group_by(ContentItem.client_id, Client.company_name)
            .order_by(func.count(ContentItem.id).desc())
            .limit(limit)
        )
        return [
            {
                "client_id": row[0],
                "company_name": row[1],
                "post_count": row[2],
            }
            for row in result.all()
        ]

    @staticmethod
    async def _overview(db: AsyncSession) -> dict:
        status_counts = await AnalyticsService._count_by_status(db)
        total = sum(status_counts.values())
        scheduled = status_counts.get("scheduled", 0)
        published = status_counts.get("published", 0)
        failed = status_counts.get("failed", 0) + status_counts.get("partial_failed", 0)
        attempts_total, attempts_success, success_rate = await AnalyticsService._publish_success(db)

        return {
            "total_posts": total,
            "scheduled_posts": scheduled,
            "published_posts": published,
            "failed_posts": failed,
            "posts_over_time": await AnalyticsService._posts_over_time(db),
            "publishing_success_rate": success_rate,
            "publish_attempts_total": attempts_total,
            "publish_attempts_success": attempts_success,
            "most_active_clients": await AnalyticsService._most_active_clients(db),
        }

    @staticmethod
    async def _platforms(db: AsyncSession) -> dict:
        unnest = func.unnest(ContentItem.platforms).label("platform")
        content_result = await db.execute(
            select(unnest, func.count())
            .select_from(ContentItem)
            .where(func.cardinality(ContentItem.platforms) > 0)
            .group_by(unnest)
        )
        post_counts = {row[0]: row[1] for row in content_result.all() if row[0]}

        attempt_result = await db.execute(
            select(
                PublishAttempt.platform,
                func.count(),
                func.sum(case((PublishAttempt.status == "success", 1), else_=0)),
            )
            .group_by(PublishAttempt.platform)
        )
        attempt_by_platform: dict[str, tuple[int, int]] = {}
        for row in attempt_result.all():
            attempt_by_platform[row[0]] = (row[1] or 0, int(row[2] or 0))

        all_platforms = sorted(set(post_counts) | set(attempt_by_platform))
        platforms = []
        for platform in all_platforms:
            attempts, success = attempt_by_platform.get(platform, (0, 0))
            platforms.append({
                "platform": platform,
                "post_count": post_counts.get(platform, 0),
                "attempt_count": attempts,
                "success_count": success,
            })
        return {"platforms": platforms}

    @staticmethod
    async def _daily_publishing(db: AsyncSession) -> list[dict]:
        range_start = _range_start()
        day_expr = func.date_trunc("day", PublishAttempt.created_at)
        success_sum = func.sum(case((PublishAttempt.status == "success", 1), else_=0))
        failed_sum = func.sum(case((PublishAttempt.status == "failed", 1), else_=0))
        result = await db.execute(
            select(day_expr, func.count(), success_sum, failed_sum)
            .where(PublishAttempt.created_at >= range_start)
            .group_by(day_expr)
            .order_by(day_expr)
        )
        by_day: dict[date, tuple[int, int, int]] = {}
        for row in result.all():
            day_val = row[0]
            if day_val is None:
                continue
            d = day_val.date() if hasattr(day_val, "date") else day_val
            by_day[d] = (row[1], int(row[2] or 0), int(row[3] or 0))

        start = _utc_today() - timedelta(days=_HISTORY_DAYS - 1)
        return [
            {
                "date": start + timedelta(days=i),
                "attempts": by_day.get(start + timedelta(days=i), (0, 0, 0))[0],
                "success": by_day.get(start + timedelta(days=i), (0, 0, 0))[1],
                "failed": by_day.get(start + timedelta(days=i), (0, 0, 0))[2],
            }
            for i in range(_HISTORY_DAYS)
        ]

    @staticmethod
    async def _recent_activity(db: AsyncSession) -> list[dict]:
        result = await db.execute(
            select(PublishAttempt)
            .order_by(PublishAttempt.created_at.desc())
            .limit(_ACTIVITY_LIMIT)
        )
        attempts = list(result.scalars().all())
        if not attempts:
            return []

        content_ids = {a.content_id for a in attempts}
        content_result = await db.execute(
            select(ContentItem)
            .where(ContentItem.id.in_(content_ids))
            .options(selectinload(ContentItem.client))
        )
        content_map = {c.id: c for c in content_result.scalars().all()}

        feed = []
        for attempt in attempts:
            content = content_map.get(attempt.content_id)
            client_name = content.client.company_name if content and content.client else "Unknown"
            feed.append({
                "id": attempt.id,
                "content_id": attempt.content_id,
                "company_name": client_name,
                "content_title": _pick_title(content) if content else "Post",
                "platform": attempt.platform,
                "status": attempt.status,
                "error": attempt.error,
                "created_at": attempt.created_at,
            })
        return feed

    @staticmethod
    async def _activity(db: AsyncSession) -> dict:
        return {
            "daily_publishing": await AnalyticsService._daily_publishing(db),
            "recent_activity": await AnalyticsService._recent_activity(db),
        }
