"""Shared types for social publishing adapters."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PublishContext:
    content_id: str
    client_id: str
    company_name: str
    platform: str
    caption: str
    hashtags: str | None
    media_url: str | None
    media_type: str | None
    final_video_url: str | None
    account_id: str | None = None
    account_name: str | None = None
    publishing_account_id: str | None = None
    account_status: str = "mock"
    selected_media: list[dict] = field(default_factory=list)
    facebook_page_id: str | None = None
    page_access_token: str | None = None
    permissions: list[str] = field(default_factory=list)
    token_expired: bool = False
