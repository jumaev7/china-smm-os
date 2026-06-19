from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ProposalDocumentStatus = Literal["draft", "reviewed", "sent", "accepted", "rejected"]
ProposalType = Literal[
    "short_offer",
    "detailed_commercial_offer",
    "distributor_offer",
    "export_offer",
]
RegenerableSection = Literal[
    "intro",
    "product_summary",
    "pricing",
    "terms",
    "call_to_action",
]


class ProposalGenerateRequest(BaseModel):
    client_id: UUID
    lead_id: UUID | None = None
    deal_id: UUID | None = None
    product_ids: list[UUID] = Field(default_factory=list)
    language: str = "ru"
    proposal_type: ProposalType = "detailed_commercial_offer"
    custom_requirements: str | None = None


class ProposalDocumentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    language: str | None = None
    status: ProposalDocumentStatus | None = None
    proposal_text: str | None = Field(None, min_length=1)
    sections: dict[str, str] | None = None


class ProposalRegenerateSectionRequest(BaseModel):
    section: RegenerableSection
    custom_requirements: str | None = None


class ProposalDealHint(BaseModel):
    deal_id: UUID
    message: str
    current_status: str
    current_expected_value: float | None = None
    suggested_status: str | None = None
    suggested_expected_value: float | None = None


class ProposalDocumentResponse(BaseModel):
    id: UUID
    client_id: UUID
    client_name: str | None = None
    lead_id: UUID | None = None
    lead_name: str | None = None
    deal_id: UUID | None = None
    deal_title: str | None = None
    product_id: UUID | None = None
    product_ids: list[UUID] = Field(default_factory=list)
    title: str
    language: str
    status: ProposalDocumentStatus
    proposal_type: str | None = None
    sections: dict[str, str] = Field(default_factory=dict)
    proposal_text: str
    demo_mode: bool = False
    revenue_hint: dict[str, Any] | None = None
    exported_pdf_path: str | None = None
    exported_docx_path: str | None = None
    last_exported_at: datetime | None = None
    pdf_download_url: str | None = None
    docx_download_url: str | None = None
    sent_at: datetime | None = None
    accepted_at: datetime | None = None
    rejected_at: datetime | None = None
    follow_up_at: datetime | None = None
    buyer_feedback: str | None = None
    deal_hint: ProposalDealHint | None = None
    can_create_deal: bool = False
    created_at: datetime
    updated_at: datetime


class ProposalMarkSentRequest(BaseModel):
    create_follow_up_task: bool = True


class ProposalMarkRejectedRequest(BaseModel):
    buyer_feedback: str | None = None


class ProposalMarkAcceptedRequest(BaseModel):
    create_deal: bool = False
    deal_title: str | None = Field(None, min_length=1, max_length=255)
    expected_value: Decimal | None = None


class ProposalCreateFollowUpRequest(BaseModel):
    due_at: datetime | None = None


class ProposalWorkflowResponse(BaseModel):
    proposal: ProposalDocumentResponse
    follow_up_task_id: UUID | None = None
    deal_created_id: UUID | None = None
    message: str | None = None


class ProposalExportResponse(BaseModel):
    id: UUID
    format: Literal["pdf", "docx"]
    path: str
    last_exported_at: datetime
    download_url: str | None = None


class ProposalDocumentListResponse(BaseModel):
    items: list[ProposalDocumentResponse]
    total: int
