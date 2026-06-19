from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

LandingPageStatus = Literal["draft", "published", "archived"]
LANDING_PAGE_STATUSES = ("draft", "published", "archived")


class LandingPageCreate(BaseModel):
    client_id: UUID
    slug: str = Field(..., min_length=2, max_length=120)
    title: str = Field(..., min_length=1, max_length=255)
    subtitle: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    hero_image_url: Optional[str] = Field(None, max_length=2000)
    cta_text: str = Field(default="Get in touch", max_length=120)
    campaign_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    attribution_link_id: Optional[UUID] = None
    status: LandingPageStatus = "draft"


class LandingPageUpdate(BaseModel):
    slug: Optional[str] = Field(None, min_length=2, max_length=120)
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    subtitle: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    hero_image_url: Optional[str] = Field(None, max_length=2000)
    cta_text: Optional[str] = Field(None, max_length=120)
    campaign_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    attribution_link_id: Optional[UUID] = None
    status: Optional[LandingPageStatus] = None


class LandingPageResponse(BaseModel):
    id: UUID
    client_id: UUID
    campaign_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    attribution_link_id: Optional[UUID] = None
    slug: str
    title: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    hero_image_url: Optional[str] = None
    cta_text: str
    status: str
    public_url: str
    client_name: Optional[str] = None
    campaign_name: Optional[str] = None
    product_name: Optional[str] = None
    leads_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LandingPageListResponse(BaseModel):
    items: list[LandingPageResponse]
    total: int


class PublicLandingProductInfo(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None


class PublicLandingCampaignInfo(BaseModel):
    name: str
    objective: Optional[str] = None


class PublicLandingPageResponse(BaseModel):
    slug: str
    title: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    hero_image_url: Optional[str] = None
    cta_text: str
    product: Optional[PublicLandingProductInfo] = None
    campaign: Optional[PublicLandingCampaignInfo] = None


class PublicLandingLeadSubmit(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    telegram: Optional[str] = Field(None, max_length=100)
    whatsapp: Optional[str] = Field(None, max_length=100)
    wechat: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    message: Optional[str] = Field(None, max_length=4000)


class PublicLandingLeadResponse(BaseModel):
    ok: bool = True
    message: str = "Thank you. We will contact you soon."
