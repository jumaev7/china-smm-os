from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CountByDay(BaseModel):
    date: date
    count: int


class DailyPublishing(BaseModel):
    date: date
    attempts: int
    success: int
    failed: int


class ClientActivity(BaseModel):
    client_id: UUID
    company_name: str
    post_count: int


class PlatformStat(BaseModel):
    platform: str
    post_count: int
    attempt_count: int
    success_count: int


class AnalyticsOverviewResponse(BaseModel):
    total_posts: int
    scheduled_posts: int
    published_posts: int
    failed_posts: int
    posts_over_time: List[CountByDay]
    publishing_success_rate: float
    publish_attempts_total: int
    publish_attempts_success: int
    most_active_clients: List[ClientActivity]


class AnalyticsPlatformsResponse(BaseModel):
    platforms: List[PlatformStat]


class ActivityFeedItem(BaseModel):
    id: UUID
    content_id: UUID
    company_name: str
    content_title: str
    platform: str
    status: str
    error: Optional[str] = None
    created_at: datetime


class AnalyticsActivityResponse(BaseModel):
    daily_publishing: List[DailyPublishing]
    recent_activity: List[ActivityFeedItem]
