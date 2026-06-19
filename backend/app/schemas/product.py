from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProductImportSource = Literal["csv", "xlsx", "pdf", "text"]
ProductImportStatus = Literal["pending", "processing", "completed", "failed"]


class ProductCreate(BaseModel):
    client_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    sku: str | None = None
    category: str | None = None
    description: str | None = None
    moq: int | None = Field(None, ge=0)
    unit_price: Decimal | None = Field(None, ge=0)
    currency: str = "USD"
    attributes_json: dict[str, Any] | None = None
    images_json: list[Any] | None = None
    active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    sku: str | None = None
    category: str | None = None
    description: str | None = None
    moq: int | None = Field(None, ge=0)
    unit_price: Decimal | None = Field(None, ge=0)
    currency: str | None = None
    attributes_json: dict[str, Any] | None = None
    images_json: list[Any] | None = None
    active: bool | None = None


class ProductResponse(BaseModel):
    id: UUID
    client_id: UUID
    name: str
    sku: str | None
    category: str | None
    description: str | None
    moq: int | None
    unit_price: Decimal | None
    currency: str
    attributes_json: dict[str, Any] | None
    images_json: list[Any] | None
    active: bool
    created_at: datetime
    company_name: str | None = None

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int


class ProductImportJobResponse(BaseModel):
    id: UUID
    client_id: UUID
    source_type: str
    source_file: str | None
    status: str
    result_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductImportResponse(BaseModel):
    job: ProductImportJobResponse
    imported: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class ProductMatchItem(BaseModel):
    product_id: UUID
    name: str
    sku: str | None
    category: str | None
    unit_price: Decimal | None
    currency: str
    confidence: float = Field(..., ge=0, le=1)
    reason: str


class ProductMatchLeadResponse(BaseModel):
    lead_id: UUID
    lead_name: str
    query_context: str
    matches: list[ProductMatchItem]
    demo_mode: bool = False
