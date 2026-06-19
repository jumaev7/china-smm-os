from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

BuyerRecommendationType = Literal["partner", "crm_lead", "contact", "industry_segment"]
BUYER_RECOMMENDATION_TYPES = ("partner", "crm_lead", "contact", "industry_segment")


class BuyerRecommendationResponse(BaseModel):
    id: UUID
    client_id: UUID
    product_id: UUID
    recommendation_type: str
    reference_id: Optional[UUID] = None
    name: str
    score: float
    reason: str
    country: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BuyerFinderProductResponse(BaseModel):
    product_id: UUID
    product_name: str
    product_category: Optional[str] = None
    client_id: UUID
    items: list[BuyerRecommendationResponse]
    total: int
    demo_mode: bool = False


class BuyerFinderAnalyzeResponse(BaseModel):
    product_id: UUID
    product_name: str
    analyzed_count: int
    items: list[BuyerRecommendationResponse]
    demo_mode: bool = False


class BuyerOpportunitySummary(BaseModel):
    id: UUID
    product_id: UUID
    product_name: Optional[str] = None
    recommendation_type: str
    reference_id: Optional[UUID] = None
    name: str
    country: Optional[str] = None
    score: float
    reason: str
