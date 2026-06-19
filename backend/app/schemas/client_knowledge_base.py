from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

KbSection = Literal[
    "company_profile",
    "products_services",
    "pricing",
    "target_audience",
    "tone_style",
    "faq",
    "past_campaigns",
    "do_not_say",
    "competitors",
    "notes",
]

KbSource = Literal["manual", "telegram", "content", "ai_summary"]
KbImportance = Literal["low", "medium", "high"]


class ClientKnowledgeBaseEntryCreate(BaseModel):
    section: KbSection
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    source: KbSource = "manual"
    importance: KbImportance = "medium"


class ClientKnowledgeBaseEntryUpdate(BaseModel):
    section: Optional[KbSection] = None
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    content: Optional[str] = Field(None, min_length=1)
    source: Optional[KbSource] = None
    importance: Optional[KbImportance] = None


class ClientKnowledgeBaseEntryResponse(BaseModel):
    id: UUID
    client_id: UUID
    section: KbSection
    title: str
    content: str
    source: KbSource
    importance: KbImportance
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClientKnowledgeBaseListResponse(BaseModel):
    items: List[ClientKnowledgeBaseEntryResponse]
    total: int


class ClientKnowledgeBaseAiSummarizeResponse(BaseModel):
    ok: bool
    message: str
    created: int
    updated: int
    items: List[ClientKnowledgeBaseEntryResponse]
