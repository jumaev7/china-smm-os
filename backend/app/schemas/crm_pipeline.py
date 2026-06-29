"""Executive CRM pipeline — 12-stage commercial lifecycle schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PipelineStage = Literal[
    "lead",
    "qualified",
    "contacted",
    "meeting_scheduled",
    "proposal_sent",
    "negotiation",
    "contract_pending",
    "client_active",
    "publishing_active",
    "expansion_upsell",
    "closed_won",
    "closed_lost",
]

StageSource = Literal["manual", "auto", "proposal"]

PipelineEventType = Literal[
    "deal_created",
    "lead_created",
    "status_changed",
    "stage_changed",
    "proposal_sent",
    "proposal_accepted",
    "proposal_rejected",
    "meeting_added",
    "publishing_connected",
    "campaign_launched",
    "client_message",
    "manual_note",
    "ai_recommendation",
    "owner_changed",
    "client_linked",
]

PIPELINE_STAGES: list[PipelineStage] = [
    "lead",
    "qualified",
    "contacted",
    "meeting_scheduled",
    "proposal_sent",
    "negotiation",
    "contract_pending",
    "client_active",
    "publishing_active",
    "expansion_upsell",
    "closed_won",
    "closed_lost",
]

PIPELINE_STAGE_LABELS: dict[str, str] = {
    "lead": "Lead",
    "qualified": "Qualified",
    "contacted": "Contacted",
    "meeting_scheduled": "Meeting Scheduled",
    "proposal_sent": "Proposal Sent",
    "negotiation": "Negotiation",
    "contract_pending": "Contract Pending",
    "client_active": "Client Active",
    "publishing_active": "Publishing Active",
    "expansion_upsell": "Expansion / Upsell",
    "closed_won": "Closed Won",
    "closed_lost": "Closed Lost",
}

DEFAULT_STAGE_PROBABILITY: dict[str, int] = {
    "lead": 5,
    "qualified": 15,
    "contacted": 20,
    "meeting_scheduled": 30,
    "proposal_sent": 40,
    "negotiation": 55,
    "contract_pending": 70,
    "client_active": 85,
    "publishing_active": 90,
    "expansion_upsell": 75,
    "closed_won": 100,
    "closed_lost": 0,
}

TERMINAL_STAGES = frozenset({"closed_won", "closed_lost"})

# Ordered funnel — each stage may advance to the next or skip forward on business events.
# Terminal stages have no forward transitions.
ALLOWED_STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "lead": frozenset({
        "qualified", "contacted", "meeting_scheduled", "proposal_sent",
        "negotiation", "closed_lost",
    }),
    "qualified": frozenset({
        "contacted", "meeting_scheduled", "proposal_sent", "negotiation", "closed_lost",
    }),
    "contacted": frozenset({
        "meeting_scheduled", "proposal_sent", "negotiation", "contract_pending", "closed_lost",
    }),
    "meeting_scheduled": frozenset({
        "proposal_sent", "negotiation", "contract_pending", "closed_lost",
    }),
    "proposal_sent": frozenset({
        "negotiation", "contract_pending", "client_active", "closed_won", "closed_lost",
    }),
    "negotiation": frozenset({
        "contract_pending", "client_active", "closed_won", "closed_lost",
    }),
    "contract_pending": frozenset({
        "client_active", "closed_won", "closed_lost",
    }),
    "client_active": frozenset({
        "publishing_active", "expansion_upsell", "closed_won", "closed_lost",
    }),
    "publishing_active": frozenset({
        "expansion_upsell", "closed_won", "closed_lost",
    }),
    "expansion_upsell": frozenset({
        "closed_won", "closed_lost", "publishing_active",
    }),
    "closed_won": frozenset(),
    "closed_lost": frozenset({"lead", "qualified", "contacted"}),
}

LEGACY_STAGE_MAP: dict[str, str] = {
    "new_lead": "lead",
    "contacted": "contacted",
    "negotiation": "negotiation",
    "proposal_sent": "proposal_sent",
    "won": "closed_won",
    "lost": "closed_lost",
}


class CrmPipelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    event_type: str
    title: str
    description: str | None
    payload: dict | None
    customer_id: UUID | None
    lead_id: UUID | None
    deal_id: UUID | None
    actor: str | None
    created_at: datetime


class CrmPipelineEventListResponse(BaseModel):
    items: list[CrmPipelineEventResponse]
    total: int


class PipelineStageInfo(BaseModel):
    stage: PipelineStage
    label: str
    default_probability: int
    is_terminal: bool


class PipelineStagesResponse(BaseModel):
    stages: list[PipelineStageInfo]


class PipelineStageUpdate(BaseModel):
    stage: PipelineStage
    probability: int | None = Field(None, ge=0, le=100)
    expected_close_date: datetime | None = None
    notes: str | None = None
    stage_override: bool = True


class PipelineNoteCreate(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str = Field(..., min_length=1)


class PipelineMeetingCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    scheduled_at: datetime | None = None
    advance_stage: bool = True


class PipelineDealListResponse(BaseModel):
    items: list[dict]
    total: int
