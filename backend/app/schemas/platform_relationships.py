"""Cross-module relationship views for unified platform workflow."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RelatedEntityType = Literal[
    "content", "lead", "buyer", "deal", "proposal", "communication", "customer",
]


class RelatedEntityItem(BaseModel):
    entity_type: RelatedEntityType
    entity_id: UUID
    label: str
    href: str | None = None
    status: str | None = None
    meta: dict | None = None
    updated_at: datetime | None = None


class PlatformRelationshipsResponse(BaseModel):
    entity_type: str
    entity_id: UUID
    related_content: list[RelatedEntityItem] = Field(default_factory=list)
    related_leads: list[RelatedEntityItem] = Field(default_factory=list)
    related_buyers: list[RelatedEntityItem] = Field(default_factory=list)
    related_deals: list[RelatedEntityItem] = Field(default_factory=list)
    related_proposals: list[RelatedEntityItem] = Field(default_factory=list)
    related_communications: list[RelatedEntityItem] = Field(default_factory=list)
    related_customers: list[RelatedEntityItem] = Field(default_factory=list)


class ContentLinksUpdate(BaseModel):
    linked_sales_lead_id: UUID | None = None
    linked_buyer_id: UUID | None = None
    linked_sales_deal_id: UUID | None = None
