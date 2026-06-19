"""Multi-Agent Sales Team v1 — coordinated advisory agents (read-only)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MultiAgentRecommendation(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    source_agent: Optional[str] = None
    category: Optional[str] = None


class MultiAgentAgentOutput(BaseModel):
    agent_name: str
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    priority: str = "medium"


class MultiAgentConflict(BaseModel):
    topic: str
    agents: list[str] = Field(default_factory=list)
    description: str = ""


class MultiAgentCoordinator(BaseModel):
    combined_summary: str
    top_recommendations: list[MultiAgentRecommendation] = Field(default_factory=list)
    conflicts: list[MultiAgentConflict] = Field(default_factory=list)
    department_health: int = 50
    department_health_label: str = "stable"


class MultiAgentOverviewResponse(BaseModel):
    team_summary: str
    coordinator: MultiAgentCoordinator
    agents: list[MultiAgentAgentOutput] = Field(default_factory=list)
    active_agent_count: int = 5
    safety_notice: str = "Recommendation only — no automatic messaging, CRM, deal, or task execution."
    errors: list[str] = Field(default_factory=list)


class MultiAgentAgentsResponse(BaseModel):
    agents: list[MultiAgentAgentOutput] = Field(default_factory=list)
    total: int = 0
    errors: list[str] = Field(default_factory=list)


class MultiAgentRecommendationsResponse(BaseModel):
    top_recommendations: list[MultiAgentRecommendation] = Field(default_factory=list)
    by_agent: dict[str, list[str]] = Field(default_factory=dict)
    total: int = 0
    errors: list[str] = Field(default_factory=list)


class MultiAgentHealthResponse(BaseModel):
    department_health: int = 50
    department_health_label: str = "stable"
    agent_health: dict[str, int] = Field(default_factory=dict)
    hot_leads: int = 0
    open_risks: int = 0
    overdue_actions: int = 0
    communication_health: float = 50.0
    active_opportunities: int = 0
    top_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    conflicts_count: int = 0
    safety_notice: str = "Recommendation only — no automatic actions."
    errors: list[str] = Field(default_factory=list)


class MultiAgentBriefingRequest(BaseModel):
    client_id: Optional[UUID] = None


class MultiAgentBriefingResponse(BaseModel):
    briefing_title: str = "Multi-Agent Sales Team Briefing"
    combined_summary: str
    agent_summaries: dict[str, str] = Field(default_factory=dict)
    top_recommendations: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    department_health: int = 50
    weekly_priorities: list[str] = Field(default_factory=list)
    source: str = "heuristic"
    generated_at: datetime
    safety_notice: str = "Manual review only — no automatic messaging, CRM, deal, or task execution."
    errors: list[str] = Field(default_factory=list)
