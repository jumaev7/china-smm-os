from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

AiCommandStatus = Literal[
    "draft", "awaiting_confirmation", "executing", "completed", "failed", "canceled",
]
AiCommandActionStatus = Literal["pending", "completed", "failed", "skipped"]
RiskLevel = Literal["low", "medium", "high"]

ALLOWED_ACTION_TYPES = (
    "create_campaign",
    "create_task",
    "create_content_draft",
    "generate_content_studio_drafts",
    "create_crm_lead",
    "create_deal_note",
    "create_follow_up_task",
    "run_audit",
    "run_sales_agent_scan",
    "run_buyer_finder",
    "create_attribution_link",
    "create_landing_page_draft",
    "show_hot_leads",
    "show_neglected_leads",
    "score_all_leads",
)


class AiCommandContextInput(BaseModel):
    current_page: Optional[str] = Field(None, max_length=500)
    entity_type: Optional[str] = Field(None, max_length=50)
    entity_id: Optional[UUID] = None
    selected_items: list[str] = Field(default_factory=list)
    user_context_json: dict[str, Any] = Field(default_factory=dict)


class AiCommandPlanRequest(AiCommandContextInput):
    command: str = Field(..., min_length=3, max_length=4000)


class AiCommandSuggestionsRequest(AiCommandContextInput):
    pass


class AiCommandSuggestionItem(BaseModel):
    label: str
    command: str
    kind: Literal["command", "link"] = "command"
    href: Optional[str] = None


class AiCommandSuggestionsResponse(BaseModel):
    current_page: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    entity_label: Optional[str] = None
    entity_summary: Optional[str] = None
    suggestions: list[AiCommandSuggestionItem] = Field(default_factory=list)


class AiCommandActionPlan(BaseModel):
    action_type: str
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)
    is_critical: bool = False


class AiCommandPlanResponse(BaseModel):
    command_id: UUID
    summary: str
    parsed_intent: str
    actions: list[AiCommandActionPlan]
    risk_level: RiskLevel
    requires_confirmation: bool = True
    unsupported_parts: list[str] = Field(default_factory=list)
    context_summary: Optional[str] = None


class AiCommandActionResult(BaseModel):
    id: UUID
    action_type: str
    label: str
    status: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class AiCommandExecuteResponse(BaseModel):
    command_id: UUID
    status: str
    summary: Optional[str] = None
    actions: list[AiCommandActionResult]
    error: Optional[str] = None


class AiCommandHistoryItem(BaseModel):
    id: UUID
    raw_command: str
    parsed_intent: Optional[str] = None
    status: str
    summary: Optional[str] = None
    action_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    created_at: datetime
    updated_at: datetime


class AiCommandHistoryResponse(BaseModel):
    items: list[AiCommandHistoryItem]
    total: int


class AiCommandDetailResponse(BaseModel):
    id: UUID
    raw_command: str
    parsed_intent: Optional[str] = None
    status: str
    summary: Optional[str] = None
    risk_level: Optional[str] = None
    unsupported_parts: list[str] = Field(default_factory=list)
    actions: list[AiCommandActionResult] = Field(default_factory=list)
    result_json: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
