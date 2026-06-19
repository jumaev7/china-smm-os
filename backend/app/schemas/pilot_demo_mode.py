"""Pilot Demo Mode — guided demonstration workflow with isolated demo data."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PilotDemoModeStep(BaseModel):
    step: int
    id: str
    title: str
    description: str
    status: str = Field(description="pending | active | complete | blocked")
    completed_at: datetime | None = None
    action_key: str | None = None


class PilotDemoModeKpi(BaseModel):
    key: str
    label: str
    value: str | int | float
    trend: str | None = None


class PilotDemoModeWorkflowDiagram(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class PilotDemoModeOverview(BaseModel):
    workflow_steps: list[PilotDemoModeStep]
    current_step: int
    progress_percent: int
    readiness_status: str
    readiness_score: int
    kpis: list[PilotDemoModeKpi]
    workflow_diagram: PilotDemoModeWorkflowDiagram
    executive_summary: str
    demo_data_present: bool
    demo_brief_id: UUID | None = None
    demo_tenant_id: UUID | None = None
    demo_client_id: UUID | None = None
    safety_notice: str
    refreshed_at: datetime


class PilotDemoModeActionResponse(BaseModel):
    success: bool
    action: str
    message: str
    overview: PilotDemoModeOverview


class PilotDemoModeResetResponse(BaseModel):
    success: bool
    message: str
    deleted_counts: dict[str, int]
    overview: PilotDemoModeOverview
