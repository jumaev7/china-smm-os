"""Factory Partner Portal — onboarding application schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ApplicationStatus = Literal["draft", "submitted", "under_review", "approved", "rejected"]

COMMISSION_MODELS = [
    "revenue_share",
    "fixed_commission",
    "referral_fee",
    "negotiable",
]


class FactoryPartnerDocument(BaseModel):
    name: str = Field(..., max_length=255)
    url: Optional[str] = Field(None, max_length=500)
    doc_type: Optional[str] = Field(None, max_length=50)


class FactoryPartnerApplicationBase(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    contact_name: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=100)
    contact_wechat: Optional[str] = Field(None, max_length=100)
    contact_whatsapp: Optional[str] = Field(None, max_length=100)
    contact_email: Optional[str] = Field(None, max_length=255)
    website: Optional[str] = Field(None, max_length=500)
    industry: Optional[str] = Field(None, max_length=100)
    product_categories: List[str] = Field(default_factory=list)
    company_description: Optional[str] = Field(None, max_length=8000)
    cooperation_terms_accepted: bool = False
    commission_model: Optional[str] = Field(None, max_length=80)
    target_markets: List[str] = Field(default_factory=list)
    documents: List[FactoryPartnerDocument] = Field(default_factory=list)


class FactoryPartnerApplyRequest(FactoryPartnerApplicationBase):
    pass


class FactoryPartnerApplicationUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    contact_name: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=100)
    contact_wechat: Optional[str] = Field(None, max_length=100)
    contact_whatsapp: Optional[str] = Field(None, max_length=100)
    contact_email: Optional[str] = Field(None, max_length=255)
    website: Optional[str] = Field(None, max_length=500)
    industry: Optional[str] = Field(None, max_length=100)
    product_categories: Optional[List[str]] = None
    company_description: Optional[str] = Field(None, max_length=8000)
    cooperation_terms_accepted: Optional[bool] = None
    commission_model: Optional[str] = Field(None, max_length=80)
    target_markets: Optional[List[str]] = None
    documents: Optional[List[FactoryPartnerDocument]] = None
    status: Optional[ApplicationStatus] = None


class FactoryPartnerApplicationResponse(BaseModel):
    id: UUID
    company_name: str
    country: Optional[str] = None
    city: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_wechat: Optional[str] = None
    contact_whatsapp: Optional[str] = None
    contact_email: Optional[str] = None
    website: Optional[str] = None
    industry: Optional[str] = None
    product_categories: List[str] = Field(default_factory=list)
    company_description: Optional[str] = None
    cooperation_terms_accepted: bool
    commission_model: Optional[str] = None
    target_markets: List[str] = Field(default_factory=list)
    documents: List[dict[str, Any]] = Field(default_factory=list)
    status: str
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    created_client_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FactoryPartnerApplicationListResponse(BaseModel):
    items: List[FactoryPartnerApplicationResponse]
    total: int


class FactoryPartnerSummaryWidget(BaseModel):
    pending_review: int
    submitted: int
    under_review: int
    approved: int
    rejected: int
    draft: int
    latest_company_name: Optional[str] = None


class FactoryPartnerCreateClientResponse(BaseModel):
    application_id: UUID
    client_id: UUID
    company_name: str
    message: str


class FactoryPartnerStatusActionResponse(BaseModel):
    application: FactoryPartnerApplicationResponse
    message: str
