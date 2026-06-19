from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

WorkflowType = Literal[
    "follow_up_workflow",
    "proposal_workflow",
    "re_engagement_workflow",
    "crm_cleanup_workflow",
    "hot_lead_workflow",
]

WorkflowActionType = Literal[
    "create_task",
    "schedule_follow_up",
    "review_proposal",
    "review_lead",
    "link_crm",
    "update_next_action",
]

WorkflowPriority = Literal["urgent", "high", "medium", "low"]
WorkflowStatus = Literal["open", "dismissed", "completed"]


class WorkflowAction(BaseModel):
    action: WorkflowActionType
    label: str
    description: str


class WorkflowTemplate(BaseModel):
    workflow_type: WorkflowType
    name: str
    description: str
    typical_actions: list[WorkflowActionType]


class WorkflowRecommendation(BaseModel):
    id: UUID
    client_id: UUID | None = None
    client_name: str | None = None
    lead_id: UUID | None = None
    lead_name: str | None = None
    deal_id: UUID | None = None
    proposal_id: UUID | None = None
    conversation_id: str | None = None
    channel: str | None = None
    workflow_type: WorkflowType
    detection_type: str
    priority: WorkflowPriority
    title: str
    reason: str
    recommended_actions: list[WorkflowAction]
    status: WorkflowStatus
    linked_task_id: UUID | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowOverview(BaseModel):
    active_recommendations: int = 0
    high_priority: int = 0
    follow_up_workflows: int = 0
    proposal_workflows: int = 0
    crm_cleanup_workflows: int = 0
    hot_lead_workflows: int = 0
    re_engagement_workflows: int = 0
    errors: list[str] = Field(default_factory=list)


class WorkflowRecommendationListResponse(BaseModel):
    items: list[WorkflowRecommendation]
    total: int
    overview: WorkflowOverview


class WorkflowTemplateListResponse(BaseModel):
    items: list[WorkflowTemplate]


class WorkflowGenerateRequest(BaseModel):
    client_id: UUID | None = None


class WorkflowGenerateResponse(BaseModel):
    scanned: int
    created: int
    skipped_duplicates: int


class WorkflowCreateTaskResponse(BaseModel):
    recommendation: WorkflowRecommendation
    task_id: UUID
    suggested: bool = True
