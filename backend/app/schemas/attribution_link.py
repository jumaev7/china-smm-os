from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

AttributionLinkChannel = Literal["telegram", "whatsapp", "wechat", "website", "manual"]

ATTRIBUTION_LINK_CHANNELS = ("telegram", "whatsapp", "wechat", "website", "manual")

CHANNEL_LABELS: dict[str, str] = {
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "wechat": "WeChat",
    "website": "Website",
    "manual": "Manual",
}


class AttributionLinkCreate(BaseModel):
    client_id: UUID
    channel: AttributionLinkChannel
    destination_url: str = Field(..., min_length=1, max_length=2000)
    title: str = Field(..., min_length=1, max_length=255)
    campaign_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    description: Optional[str] = None


class AttributionLinkResponse(BaseModel):
    id: UUID
    client_id: UUID
    campaign_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    channel: str
    code: str
    destination_url: str
    title: str
    description: Optional[str] = None
    clicks_count: int
    leads_count: int
    tracking_url: str
    client_name: Optional[str] = None
    campaign_name: Optional[str] = None
    product_name: Optional[str] = None
    partner_name: Optional[str] = None
    conversion_rate: float = 0.0
    linked_revenue: Decimal = Decimal("0")
    linked_commission: Decimal = Decimal("0")
    won_deals_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class AttributionLinkListResponse(BaseModel):
    items: list[AttributionLinkResponse]
    total: int


class AttributionLinkStatsItem(BaseModel):
    link_id: UUID
    title: str
    code: str
    channel: str
    clicks_count: int
    leads_count: int
    won_deals_count: int
    revenue: Decimal
    commission: Decimal
    click_to_lead_rate: float
    lead_to_won_rate: float
