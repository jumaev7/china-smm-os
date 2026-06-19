from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PageContext(BaseModel):
    pathname: str = ""
    page_type: str = "other"
    summary: Optional[str] = None


class AssistantChatMessage(BaseModel):
    role: str
    content: str


class AssistantChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    page_context: PageContext = Field(default_factory=PageContext)
    client_id: Optional[UUID] = None
    content_id: Optional[UUID] = None
    history: list[AssistantChatMessage] = Field(default_factory=list, max_length=12)
    auto_apply: bool = False


class AssistantChatResponse(BaseModel):
    reply: str
    suggested_patch: Optional[dict[str, Any]] = None
    applied: bool = False


class AssistantApplyRequest(BaseModel):
    content_id: UUID
    patch: dict[str, Any]
    auto: bool = False


class AssistantApplyResponse(BaseModel):
    applied_fields: dict[str, Any]
