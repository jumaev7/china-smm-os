"""Factory Platform v2 — company profile, catalog, certificates, export markets schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.factory_platform import FactoryPlatformTenantRef

FactoryCatalogStatus = Literal["active", "draft", "archived"]
FactoryVerificationStatus = Literal["unverified", "pending", "verified"]


class FactoryCompanyProfile(BaseModel):
    company_name: str
    brand_name: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    founded_year: Optional[int] = None
    employee_count: Optional[int] = None
    industry: Optional[str] = None
    logo_url: Optional[str] = None
    factory_video_url: Optional[str] = None
    updated_at: Optional[datetime] = None


class FactoryProfileUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    brand_name: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    founded_year: Optional[int] = None
    employee_count: Optional[int] = None
    logo_url: Optional[str] = None
    factory_video_url: Optional[str] = None


class FactoryProfileResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    profile: FactoryCompanyProfile
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = "Factory profile — tenant-scoped read-only workspace."


class FactoryCatalogItem(BaseModel):
    product_id: UUID
    product_name: str
    category: Optional[str] = None
    description: Optional[str] = None
    target_markets: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    moq: Optional[int] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = "USD"
    export_available: bool = True
    status: FactoryCatalogStatus = "draft"
    updated_at: Optional[datetime] = None


class FactoryCatalogProductCreate(BaseModel):
    product_name: str
    category: Optional[str] = None
    description: Optional[str] = None
    target_markets: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    moq: Optional[int] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = "USD"
    export_available: bool = True
    status: FactoryCatalogStatus = "draft"


class FactoryCatalogProductUpdate(BaseModel):
    product_name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    target_markets: Optional[List[str]] = None
    image_url: Optional[str] = None
    moq: Optional[int] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = None
    export_available: Optional[bool] = None
    status: Optional[FactoryCatalogStatus] = None


class FactoryCatalogResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    items: List[FactoryCatalogItem] = Field(default_factory=list)
    total: int = 0
    active_count: int = 0
    draft_count: int = 0
    archived_count: int = 0
    errors: List[str] = Field(default_factory=list)


class FactoryCertificateItem(BaseModel):
    certificate_id: UUID
    certificate_name: str
    certificate_type: str
    issuing_authority: Optional[str] = None
    certificate_number: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    document_url: Optional[str] = None
    is_expired: bool = False


class FactoryCertificateCreate(BaseModel):
    certificate_name: str
    certificate_type: str
    issuing_authority: Optional[str] = None
    certificate_number: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    document_url: Optional[str] = None


class FactoryCertificateUpdate(BaseModel):
    certificate_name: Optional[str] = None
    certificate_type: Optional[str] = None
    issuing_authority: Optional[str] = None
    certificate_number: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    document_url: Optional[str] = None


class FactoryCertificatesResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    items: List[FactoryCertificateItem] = Field(default_factory=list)
    total: int = 0
    valid_count: int = 0
    expired_count: int = 0
    errors: List[str] = Field(default_factory=list)


class FactoryExportMarketItem(BaseModel):
    market_id: UUID
    country: str
    market_score: int = 0
    active_buyers: int = 0
    opportunities: int = 0


class FactoryExportMarketCreate(BaseModel):
    country: str
    market_score: int = 50
    active_buyers: int = 0
    opportunities: int = 0


class FactoryExportMarketUpdate(BaseModel):
    country: Optional[str] = None
    market_score: Optional[int] = None
    active_buyers: Optional[int] = None
    opportunities: Optional[int] = None


class FactoryExportMarketsResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    items: List[FactoryExportMarketItem] = Field(default_factory=list)
    total: int = 0
    errors: List[str] = Field(default_factory=list)


class FactoryProfileScoreComponents(BaseModel):
    profile: int = 0
    products: int = 0
    certificates: int = 0
    export_markets: int = 0


class FactoryReadinessBreakdownItem(BaseModel):
    key: str
    label: str
    score: int = 0
    max_score: int = 0
    complete: bool = False
    recommended_action: Optional[str] = None


class FactoryProfileScoreResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    profile_score: int = 0
    components: FactoryProfileScoreComponents
    missing_items: List[str] = Field(default_factory=list)
    breakdown: List[FactoryReadinessBreakdownItem] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class FactoryProfileReadinessResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    profile_score: int = 0
    components: FactoryProfileScoreComponents
    breakdown: List[FactoryReadinessBreakdownItem] = Field(default_factory=list)
    missing_items: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class FactoryMediaItem(BaseModel):
    media_id: UUID
    media_type: str
    title: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    original_filename: Optional[str] = None
    reusable_modules: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class FactoryMediaResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    items: List[FactoryMediaItem] = Field(default_factory=list)
    total: int = 0
    image_count: int = 0
    video_count: int = 0
    pdf_count: int = 0
    errors: List[str] = Field(default_factory=list)


class FactoryPerformanceResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    total_buyers: int = 0
    active_opportunities: int = 0
    marketplace_visibility: int = 0
    buyer_acquisition_score: int = 0
    profile_score: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = "Read-only performance metrics — no automatic actions."


class FactoryVerificationStatusResponse(BaseModel):
    tenant: FactoryPlatformTenantRef
    verification_status: FactoryVerificationStatus = "unverified"
    profile_score: int = 0
    requirements_met: List[str] = Field(default_factory=list)
    requirements_missing: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = "Verification is manual only — no automatic verification."


class FactoryPerformanceSummaryWidget(BaseModel):
    profile_score: int = 0
    catalog_score: int = 0
    certificate_score: int = 0
    export_market_score: int = 0
    media_score: int = 0
    total_buyers: int = 0
    active_opportunities: int = 0
    marketplace_visibility: int = 0
    buyer_acquisition_score: int = 0
    verification_status: FactoryVerificationStatus = "unverified"
    company_name: Optional[str] = None
    missing_items: List[str] = Field(default_factory=list)
    top_recommended_action: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = "Factory performance — tenant workspace metrics."
