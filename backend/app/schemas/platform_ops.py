"""Schemas for pre-launch platform operations."""
from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PilotFactoryCreate(BaseModel):
    factory_name: str = Field(..., min_length=1, max_length=255)
    country: str = Field(default="", max_length=100)
    industry: str = Field(default="", max_length=100)
    pilot_status: str = Field(default="invited")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    success_score: Optional[int] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None
    tenant_id: Optional[UUID] = None


class PilotFactoryUpdate(BaseModel):
    factory_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    country: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    pilot_status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    success_score: Optional[int] = Field(default=None, ge=0, le=100)
    notes: Optional[str] = None
    tenant_id: Optional[UUID] = None


class PilotFactoryResponse(BaseModel):
    id: UUID
    factory_name: str
    country: str
    industry: str
    pilot_status: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    success_score: Optional[int] = None
    notes: Optional[str] = None
    tenant_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PilotFactoryListResponse(BaseModel):
    items: List[PilotFactoryResponse]
    total: int


class FeedbackCreate(BaseModel):
    feedback_type: str = Field(..., pattern="^(bug|feature_request|suggestion)$")
    category: str
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)


class FeedbackResponse(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    pilot_factory_id: Optional[UUID] = None
    feedback_type: str
    category: str
    title: str
    description: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackListResponse(BaseModel):
    items: List[FeedbackResponse]
    total: int


class HealthComponent(BaseModel):
    key: str
    label: str
    status: str
    message: str
    details: dict[str, Any] = {}


class SystemHealthDashboardResponse(BaseModel):
    overall_status: str
    components: List[HealthComponent]
    refreshed_at: datetime


class AuditLogResponse(BaseModel):
    id: UUID
    actor_type: str
    actor_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    event_type: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int


class ErrorReportCreate(BaseModel):
    source: str = Field(..., pattern="^(frontend|api|integration)$")
    path: Optional[str] = Field(default=None, max_length=500)
    message: str = Field(..., min_length=1)
    stack_trace: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ErrorReportResponse(BaseModel):
    id: UUID
    source: str
    tenant_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    path: Optional[str] = None
    message: str
    stack_trace: Optional[str] = None
    metadata: Optional[dict[str, Any]] = Field(default=None, validation_alias="error_context")
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ErrorReportListResponse(BaseModel):
    items: List[ErrorReportResponse]
    total: int
    in_memory_errors: List[dict[str, Any]] = []
    categories: dict[str, int] = {}


class PilotSuccessMetric(BaseModel):
    key: str
    label: str
    value: str | int | float
    status: str


class PilotSuccessDashboardResponse(BaseModel):
    overall_score: int
    metrics: List[PilotSuccessMetric]
    pilot_factories_active: int
    pilot_factories_total: int
    feedback_open_count: int
    refreshed_at: datetime


class ReadinessComponent(BaseModel):
    key: str
    label: str
    score: int
    weight: int
    status: str
    details: Optional[str] = None


class LaunchReadinessResponse(BaseModel):
    readiness_score: int
    pilot_readiness_score: int
    components: List[ReadinessComponent]
    launch_blockers: List[str]
    recommendations: List[str]
    refreshed_at: datetime
