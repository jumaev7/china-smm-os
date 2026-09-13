from datetime import date, datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

PublishMode = Literal["test_publish", "manual_publish", "scheduled_publish"]

PLATFORMS = ["telegram", "facebook", "instagram", "tiktok", "linkedin"]
ACCOUNT_STATUSES = [
    "connected",
    "disconnected",
    "mock",
    "expired",
    "invalid",
    "missing_permissions",
    "blocked",
]

MOCK_ACCOUNT_LABELS = {
    "telegram": "Telegram Channel Mock",
    "instagram": "Instagram Mock",
    "facebook": "Facebook Page Mock",
    "tiktok": "TikTok Mock",
    "linkedin": "LinkedIn Mock",
}


class PublishingAccountCreate(BaseModel):
    platform: str
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    access_token_encrypted: Optional[str] = None
    status: str = "mock"
    mock: bool = False


class PublishingAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    access_token_encrypted: Optional[str] = None
    status: Optional[str] = None


class PublishingAccountResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    platform: str
    account_name: str
    account_id: str
    status: str
    expires_at: Optional[datetime] = None
    facebook_page_id: Optional[str] = None
    instagram_business_account_id: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    account_metadata: dict = Field(default_factory=dict)
    token_expired: bool = False
    health: Optional[str] = None
    missing_permissions: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PublishingAccountListResponse(BaseModel):
    items: List[PublishingAccountResponse]
    total: int


class PublishContentRequest(BaseModel):
    platforms: Optional[List[str]] = None
    account_id: Optional[UUID] = None
    test: bool = False
    mode: Optional[PublishMode] = None


class PublishAttemptResponse(BaseModel):
    id: UUID
    content_id: UUID
    platform: str
    account_id: Optional[UUID] = None
    account_name: Optional[str] = None
    status: str
    response: Optional[str] = None
    error: Optional[str] = None
    platform_post_id: Optional[str] = None
    post_url: Optional[str] = None
    created_at: datetime
    idempotency_key: Optional[str] = None
    publish_version: Optional[str] = None
    attempt_number: Optional[int] = None
    failure_code: Optional[str] = None
    failure_category: Optional[str] = None
    retryable: Optional[bool] = None
    next_retry_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    external_post_id: Optional[str] = None
    external_post_url: Optional[str] = None
    manual_retry_allowed: Optional[bool] = None
    manual_retry_blocked_reason: Optional[str] = None
    company_name: Optional[str] = None
    content_status: Optional[str] = None
    tenant_id: Optional[UUID] = None


class PublishAttemptListResponse(BaseModel):
    items: List[PublishAttemptResponse]
    total: int
    current_time: Optional[datetime] = None
    counts: dict[str, int] = Field(default_factory=dict)


class PublishAttemptActionResponse(BaseModel):
    ok: bool
    message: str
    attempt_id: UUID
    content_id: UUID
    status: Optional[str] = None
    retry_blocked_reason: Optional[str] = None
    existing_post_id: Optional[str] = None
    publish_result: Optional[dict] = None


class PublishRetryCommandResponse(BaseModel):
    """Safe read model for durable retry commands (no secrets / lease owner)."""

    command_id: UUID
    status: str
    platform: str
    original_attempt_id: UUID
    resulting_attempt_id: Optional[UUID] = None
    content_id: UUID
    client_id: Optional[UUID] = None
    requested_source: str
    reason_code: Optional[str] = None
    provider_outcome: Optional[str] = None
    publish_version: Optional[str] = None
    destination_key: Optional[str] = None
    correlation_id: Optional[str] = None
    created_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    provider_write_started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class StrandedLeaseOwnerView(BaseModel):
    """Historical lease owner only — not current liveness proof."""

    value: Optional[str] = None
    label: str = "historical_only"
    not_current_liveness_proof: bool = True


class StrandedProviderCallStartedAuditView(BaseModel):
    presence: str
    interpretation: str
    meaning: str
    not_proof_of: List[str] = Field(default_factory=list)
    authorizes_replay: bool = False


class StrandedRetryCommandItem(BaseModel):
    """Phase E1 operator-safe stranded post-barrier observation."""

    command_id: UUID
    tenant_id: UUID
    provider: str
    platform: str
    publishing_account_id: Optional[UUID] = None
    content_id: UUID
    client_id: Optional[UUID] = None
    original_attempt_id: UUID
    resulting_attempt_id: Optional[UUID] = None
    status: str
    provider_write_started_at: datetime
    lease_owner: StrandedLeaseOwnerView
    claimed_at: Optional[datetime] = None
    age_seconds: int
    quiet_period_seconds: int
    quiet_period_elapsed: bool
    last_known_local_step: str
    provider_call_started_audit: StrandedProviderCallStartedAuditView
    external_post_id: Optional[str] = None
    correlation_id: str
    classification: str
    outcome_stance: Optional[str] = None
    recommended_action: str
    phase_e: str = "stranded_post_barrier"
    does_not_prove: List[str] = Field(default_factory=list)
    authorizes_provider_write: bool = False
    authorizes_replay: bool = False


class StrandedQuietPeriodView(BaseModel):
    lease_seconds: int
    drain_seconds: int
    provider_slack_seconds: int
    safety_buffer_seconds: int
    quiet_period_seconds: int
    formula: str
    heuristic_only: bool = True
    authorizes_provider_write: bool = False


class StrandedRetryCommandListResponse(BaseModel):
    items: List[StrandedRetryCommandItem]
    total: int
    page: int
    page_size: int
    quiet_period: StrandedQuietPeriodView
    alert_surfacing_enabled: bool = False
    alerts_created: int = 0
    alerts_updated: int = 0
    phase_e: str = "stranded_post_barrier"
    read_only_commands: bool = True


class PublishRetryCommandResolveRequest(BaseModel):
    """E2-1 MARK_AMBIGUOUS + E2-2 ACKNOWLEDGE_EXTERNAL_SUCCESS.

    Failed-confirm / cancel / no-effect / supersede remain rejected.
    Success evidence fields are required only for ACKNOWLEDGE_EXTERNAL_SUCCESS
    (validated in the service; schema bounds lengths only).

    Confirmation semantics (Pydantic v2 / FastAPI):
    - ACKNOWLEDGE_EXTERNAL_SUCCESS: raw JSON value must be boolean ``true``
      (reject ``"true"``, ``1``, ``false``, ``null``, missing) → API **422**.
    - MARK_AMBIGUOUS: preserves prior coercible-bool behavior; service still
      rejects non-True with **400** if reached with Python ``False``.
    """

    action: Literal["MARK_AMBIGUOUS", "ACKNOWLEDGE_EXTERNAL_SUCCESS"]
    confirm_permanent_resolution: bool
    operator_reason: str = Field(..., min_length=1, max_length=1000)
    evidence_source: Optional[str] = Field(
        None,
        max_length=80,
        description=(
            "Evidence label. Optional for MARK_AMBIGUOUS; required for "
            "ACKNOWLEDGE_EXTERNAL_SUCCESS (operator attestation, not proof)."
        ),
    )
    external_post_id: Optional[str] = Field(
        None,
        max_length=255,
        description="Required for ACKNOWLEDGE_EXTERNAL_SUCCESS (opaque provider id)",
    )
    external_post_url: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional permalink reference; never fetched server-side",
    )
    observed_at: Optional[datetime] = Field(
        None,
        description="Optional operator-observed timestamp (timestamptz)",
    )

    @model_validator(mode="before")
    @classmethod
    def _e2_2_require_explicit_json_true_confirmation(cls, data: Any) -> Any:
        """Action-specific: E2-2 rejects coercible truthy values before bool parse."""
        if not isinstance(data, dict):
            return data
        action = data.get("action")
        if action != "ACKNOWLEDGE_EXTERNAL_SUCCESS":
            return data
        if "confirm_permanent_resolution" not in data:
            raise ValueError(
                "confirm_permanent_resolution is required and must be "
                "JSON boolean true for ACKNOWLEDGE_EXTERNAL_SUCCESS"
            )
        confirm = data.get("confirm_permanent_resolution")
        if confirm is not True:
            raise ValueError(
                "confirm_permanent_resolution must be JSON boolean true "
                "for ACKNOWLEDGE_EXTERNAL_SUCCESS "
                '(rejected non-boolean true such as "true", 1, false, null)'
            )
        return data


class PublishRetryCommandResolveResponse(BaseModel):
    """Safe resolution response — no secrets / content body."""

    command_id: UUID
    resulting_attempt_id: UUID
    status: str
    provider_outcome: str
    attempt_status: str
    resolution: Literal["applied", "already_resolved"]
    finished_at: Optional[datetime] = None
    action: str = "MARK_AMBIGUOUS"
    audit_event_type: Optional[str] = None
    audit_id: Optional[UUID] = None
    correlation_id: Optional[str] = None
    alert_resolved: bool = False
    external_post_id: Optional[str] = None


class ScheduledPublishDebugItem(BaseModel):
    id: UUID
    status: str
    scheduled_for: Optional[datetime] = None
    utc_time: Optional[str] = None
    local_time: Optional[str] = None
    current_time: datetime
    is_due: bool
    approved_at: Optional[datetime] = None
    admin_approved: bool
    client_review_status: Optional[str] = None
    client_approved: bool
    platforms: List[str]
    platforms_count: int
    publishing_accounts_available: dict[str, List[str]]
    selected_accounts: dict[str, Optional[str]]
    has_media: bool
    has_caption: bool
    skip_reason: Optional[str] = None


class ScheduledPublishDebugResponse(BaseModel):
    current_time: datetime
    due_count: int
    items: List[ScheduledPublishDebugItem]


class PublishingCalendarItem(BaseModel):
    id: UUID
    title: str
    client_id: UUID
    company_name: str
    status: str
    scheduled_for: Optional[datetime] = None
    published_at: Optional[datetime] = None
    platforms: List[str] = Field(default_factory=list)


class PublishingCalendarResponse(BaseModel):
    items: List[PublishingCalendarItem]
    total: int
    from_date: date
    to_date: date


class PublishingQueueItem(BaseModel):
    id: UUID
    client_id: UUID
    company_name: str
    status: str
    scheduled_for: Optional[datetime] = None
    local_time: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    client_review_status: Optional[str] = None
    admin_approved: bool
    safety_status: str
    block_reason: Optional[str] = None
    block_reason_label: Optional[str] = None
    queue_category: str
    is_due: bool
    latest_attempt: Optional[dict] = None


class PublishingQueueResponse(BaseModel):
    current_time: datetime
    items: List[PublishingQueueItem]
    total: int
    counts: dict[str, int] = Field(default_factory=dict)


class PublishingQueueActionResponse(BaseModel):
    ok: bool
    message: str
    content_id: UUID
    status: Optional[str] = None
    safety_status: Optional[str] = None
    block_reason: Optional[str] = None


class MetaAccountHealth(BaseModel):
    platform: str
    account_id: str
    account_name: str
    status: str
    health: str
    expires_at: Optional[datetime] = None
    token_expired: bool = False
    facebook_page_id: Optional[str] = None
    instagram_business_account_id: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    missing_permissions: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    blockers: List[str] = Field(default_factory=list)
    publish_ready: bool = False
    implementation: str = "mock"


class MetaConnectionSummaryResponse(BaseModel):
    oauth_configured: bool
    connected: bool
    facebook: Optional[MetaAccountHealth] = None
    instagram: Optional[MetaAccountHealth] = None
    permissions: List[str] = Field(default_factory=list)
    missing_permissions: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    token_expired: bool = False
    health: str
    blockers: List[str] = Field(default_factory=list)
    publish_implementation: str = "mock"


class MetaConnectionHealthResponse(BaseModel):
    oauth_configured: bool
    connected: bool
    health: str
    token_expired: bool = False
    expires_at: Optional[datetime] = None
    permissions: List[str] = Field(default_factory=list)
    missing_permissions: List[str] = Field(default_factory=list)
    facebook: Optional[MetaAccountHealth] = None
    instagram: Optional[MetaAccountHealth] = None
    blockers: List[str] = Field(default_factory=list)
    publish_implementation: str = "mock"


class MetaOAuthStartResponse(BaseModel):
    authorize_url: str = ""
    state: Optional[str] = None
    mode: str
    demo_connect_url: Optional[str] = None


class MetaRefreshResponse(BaseModel):
    ok: bool
    message: str
    accounts: dict[str, str] = Field(default_factory=dict)


class MetaDisconnectResponse(BaseModel):
    ok: bool
    message: str
