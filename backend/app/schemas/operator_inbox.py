from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

InboxStatus = Literal["new", "used", "ignored"]
InboxPriority = Literal["high", "medium", "low"]


class OperatorInboxMediaPreview(BaseModel):
    buffer_id: UUID
    media_type: str
    url: Optional[str] = None
    text: Optional[str] = None


class OperatorInboxMediaSelection(BaseModel):
    photo_ordinals: List[int] = Field(default_factory=list)
    video_ordinals: List[int] = Field(default_factory=list)
    buffer_ids: List[str] = Field(default_factory=list)
    use_all_media: bool = False
    use_client_text_as_description: bool = True
    summary: Optional[str] = None


OperatorInboxIntent = Literal[
    "create_post",
    "edit_existing",
    "schedule_post",
    "ask_question",
    "unclear",
]


class OperatorInboxAiSuggestion(BaseModel):
    inbox_id: str
    intent: OperatorInboxIntent
    suggested_action: str
    suggested_platforms: List[str] = Field(default_factory=list)
    suggested_schedule: Optional[str] = None
    media_selection: OperatorInboxMediaSelection
    reason: str
    active_content_id: Optional[str] = None
    source: Optional[str] = None
    cached: bool = False
    cached_at: Optional[str] = None


class OperatorInboxItem(BaseModel):
    id: UUID
    client_id: UUID
    company_name: str
    telegram_group_title: Optional[str] = None
    message_text: Optional[str] = None
    media_count: int
    media_previews: List[OperatorInboxMediaPreview] = Field(default_factory=list)
    created_at: datetime
    message_at: datetime
    status: InboxStatus
    linked_content_id: Optional[UUID] = None
    ai_suggestion: Optional[OperatorInboxAiSuggestion] = None
    auto_drafted: bool = False
    ai_summary: Optional[str] = None
    priority: Optional[Literal["high", "medium", "low"]] = None
    suggested_publish_date: Optional[datetime] = None
    suggested_platforms: List[str] = Field(default_factory=list)
    detected_deadline: Optional[str] = None
    detected_offer: Optional[str] = None
    detected_language: Optional[str] = None
    grouped_task_id: Optional[UUID] = None
    is_group_primary: bool = True
    group_message_count: int = 1
    group_media_count: int = 0
    group_inbox_ids: List[UUID] = Field(default_factory=list)
    needs_action: bool = False
    related_to_media_request: bool = False
    account_manager_intent: Optional[str] = None
    account_manager_summary: Optional[str] = None
    account_manager_recommended_action: Optional[str] = None
    account_manager_priority: Optional[InboxPriority] = None
    account_manager_reply_sent: bool = False
    account_manager_reply_text: Optional[str] = None
    account_manager_related_content_id: Optional[UUID] = None
    operator_task_id: Optional[UUID] = None
    operator_task_status: Optional[str] = None
    operator_task_title: Optional[str] = None


class OperatorInboxListResponse(BaseModel):
    items: List[OperatorInboxItem]
    total: int
    counts: dict[str, int] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class OperatorInboxActionResponse(BaseModel):
    ok: bool
    message: str
    inbox_id: UUID
    content_id: Optional[UUID] = None
    status: Optional[InboxStatus] = None


class OperatorInboxAiSuggestResponse(BaseModel):
    suggestion: OperatorInboxAiSuggestion


class OperatorInboxSmartAnalyzeResponse(BaseModel):
    inbox_id: str
    ai_summary: Optional[str] = None
    priority: Optional[InboxPriority] = None
    suggested_publish_date: Optional[str] = None
    suggested_platforms: List[str] = Field(default_factory=list)
    detected_deadline: Optional[str] = None
    detected_offer: Optional[str] = None
    detected_language: Optional[str] = None
    grouped_task_id: Optional[str] = None
    source: Optional[str] = None
    cached: bool = False
    cached_at: Optional[str] = None


class OperatorInboxGroupRequest(BaseModel):
    inbox_ids: List[UUID] = Field(..., min_length=2)


class OperatorInboxGroupResponse(BaseModel):
    ok: bool
    message: str
    grouped_task_id: str
    primary_inbox_id: UUID
    inbox_ids: List[str]
