"""Provider-facing request/response schemas (no ORM objects)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


MODEL_ALIASES = ("content_fast", "content_standard", "content_high_quality")
TASK_AI_CONTENT_ADAPTATION = "ai_content_adaptation"
ROUTING_VERSION_DEFAULT = "1.0.0"


@dataclass(frozen=True)
class AIProviderRequest:
    """Strict provider-facing request — no unrestricted ORM objects."""

    provider_request_id: str
    tenant_id: str
    task_type: str
    model_alias: str
    system_instructions: str
    input_messages: list[dict[str, str]]
    output_schema: dict[str, Any]
    temperature: float = 0.2
    max_output_tokens: int = 2000
    timeout_seconds: float = 45.0
    metadata: dict[str, Any] = field(default_factory=dict)
    resolved_model: str | None = None


@dataclass(frozen=True)
class AIProviderResponse:
    provider: str
    model: str
    provider_request_id: str
    provider_response_id: str | None
    status: str
    structured_output: dict[str, Any] | None
    raw_text_hash: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    finish_reason: str | None
    safety_metadata: dict[str, Any]
    created_at: datetime
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class AIProviderHealth:
    provider: str
    available: bool
    latency_ms: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class AIUsageEstimate:
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_minor: int
    currency: str = "USD"


@dataclass(frozen=True)
class RoutingDecision:
    provider: str
    model_alias: str
    resolved_model: str
    routing_version: str
    fallback_used: bool = False
    reason: str = "configured_default"
