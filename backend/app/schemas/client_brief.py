from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

BriefStatus = Literal["new", "reviewing", "changes_requested", "approved", "converted"]
BriefLanguage = Literal["zh", "en", "ru", "uz"]
BriefMediaType = Literal["image", "carousel", "reel", "story", "short_video"]
CampaignGoal = Literal["awareness", "leads", "sales", "brand_trust"]
PlanStatus = Literal["draft", "approved"]


class ClientBriefCreate(BaseModel):
    client_id: Optional[UUID] = None
    product_name: str = Field(..., min_length=1, max_length=255)
    product_description: Optional[str] = None
    target_market: str = Field(..., min_length=1, max_length=255)
    campaign_goal: CampaignGoal
    language: BriefLanguage = "en"
    languages: List[BriefLanguage] = Field(default_factory=list)
    desired_platforms: List[str] = Field(default_factory=list)
    media_urls: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ClientBriefRequestChanges(BaseModel):
    feedback: str = Field(..., min_length=1)


class ClientBriefAddMedia(BaseModel):
    media_urls: List[str] = Field(..., min_length=1)


class BriefPlanItemCaptions(BaseModel):
    ru: str = ""
    uz: str = ""
    en: str = ""
    zh: str = ""


class BriefPlanItem(BaseModel):
    theme: str
    goal: str
    platform: str = "instagram"
    media_type: BriefMediaType = "image"
    captions: BriefPlanItemCaptions = Field(default_factory=BriefPlanItemCaptions)
    hashtags: str = ""
    cta: str = ""
    priority: Literal["high", "medium", "low"] = "medium"


class BriefContentPlan(BaseModel):
    summary: str = ""
    plan_status: PlanStatus = "draft"
    items: List[BriefPlanItem] = Field(default_factory=list)
    source: Literal["ai", "fallback", "manual"] = "ai"


class ClientBriefUpdatePlan(BaseModel):
    plan: BriefContentPlan


class ClientBriefResponse(BaseModel):
    id: UUID
    client_id: UUID
    company_name: Optional[str] = None
    tenant_id: Optional[UUID] = None
    tenant_name: Optional[str] = None
    product_name: str
    product_description: Optional[str] = None
    target_market: str
    campaign_goal: str
    language: str
    languages: List[str] = Field(default_factory=list)
    desired_platforms: List[str] = Field(default_factory=list)
    media_urls: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    status: BriefStatus
    ai_content_plan: Optional[str] = None
    admin_feedback: Optional[str] = None
    submitted_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClientBriefListResponse(BaseModel):
    items: List[ClientBriefResponse]
    total: int


class ClientBriefConvertResponse(BaseModel):
    brief: ClientBriefResponse
    tasks_created: int
    content_items_created: int
