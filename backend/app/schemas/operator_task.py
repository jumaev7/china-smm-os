from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

TaskSourceType = Literal[
    "telegram_inbox",
    "content",
    "media_request",
    "client_review",
    "manual",
    "sales_agent",
    "sales_assistant",
    "communication_hub",
    "proposal",
    "outreach",
    "sales_playbook",
    "unified_inbox",
    "whatsapp",
    "client_brief",
]
TaskPriority = Literal["high", "medium", "low"]
TaskStatus = Literal["todo", "in_progress", "waiting_client", "done", "canceled"]
TaskCreatedBy = Literal["ai_account_manager", "admin", "system"]


class OperatorTaskCreate(BaseModel):
    client_id: UUID
    source_type: TaskSourceType = "manual"
    source_id: Optional[UUID] = None
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    priority: TaskPriority = "medium"
    status: TaskStatus = "todo"
    due_at: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=100)
    created_by: TaskCreatedBy = "admin"
    linked_content_id: Optional[UUID] = None


class OperatorTaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    due_at: Optional[datetime] = None
    assigned_to: Optional[str] = Field(None, max_length=100)
    linked_content_id: Optional[UUID] = None


class OperatorTaskResponse(BaseModel):
    id: UUID
    client_id: UUID
    company_name: Optional[str] = None
    source_type: TaskSourceType
    source_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    priority: TaskPriority
    status: TaskStatus
    due_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    created_by: TaskCreatedBy
    linked_content_id: Optional[UUID] = None
    execution_status: Optional[str] = None
    execution_result: Optional[dict] = None
    executed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskExecuteResponse(BaseModel):
    ok: bool
    action: str
    message: str
    content_id: Optional[UUID] = None
    suggested_reply: Optional[str] = None
    task: OperatorTaskResponse


class TaskSendReplyRequest(BaseModel):
    reply_text: Optional[str] = Field(None, max_length=4000)


class TaskSendReplyResponse(BaseModel):
    ok: bool
    message: str
    task: OperatorTaskResponse


class OperatorTaskListResponse(BaseModel):
    items: List[OperatorTaskResponse]
    total: int
