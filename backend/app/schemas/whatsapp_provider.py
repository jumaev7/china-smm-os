"""WhatsApp Provider v1 — API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WhatsAppProviderType = Literal[
    "meta_cloud_api",
    "whatsapp_business_api",
    "third_party_connector",
    "custom_provider",
]
WhatsAppProviderStatus = Literal["pending", "active", "inactive", "error"]
WhatsAppProviderConfigStatus = Literal["draft", "configured", "validated", "error"]
WhatsAppProviderWebhookEventType = Literal[
    "inbound_message",
    "contact_update",
    "conversation_update",
    "delivery_status_update",
    "template_status_update",
]


class WhatsAppProviderCapabilities(BaseModel):
    contact_sync: bool = False
    conversation_sync: bool = False
    message_send: bool = False
    media_upload: bool = False
    webhook_support: bool = False
    template_messages: bool = False


class WhatsAppProviderResponse(BaseModel):
    id: UUID
    provider_name: str
    provider_type: WhatsAppProviderType
    status: WhatsAppProviderStatus
    capabilities: WhatsAppProviderCapabilities
    created_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppProvidersResponse(BaseModel):
    items: list[WhatsAppProviderResponse]
    total: int


class WhatsAppProviderConfigurationResponse(BaseModel):
    id: UUID
    provider_id: UUID
    provider_name: Optional[str] = None
    tenant_id: Optional[UUID] = None
    config_status: WhatsAppProviderConfigStatus
    phone_number: Optional[str] = None
    business_account_id: Optional[str] = None
    provider_status: str = "pending"
    last_connection_test: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppProviderConfigurationsResponse(BaseModel):
    items: list[WhatsAppProviderConfigurationResponse]
    total: int


class WhatsAppProviderHealthItem(BaseModel):
    provider_id: UUID
    provider_name: str
    provider_type: WhatsAppProviderType
    status: WhatsAppProviderStatus
    config_status: Optional[WhatsAppProviderConfigStatus] = None
    phone_number: Optional[str] = None
    business_account_id: Optional[str] = None
    provider_status: Optional[str] = None
    last_connection_test: Optional[datetime] = None
    connection_ok: bool = False
    message: str = ""


class WhatsAppProviderIntegrationCheck(BaseModel):
    module: str
    status: Literal["ok", "degraded", "unavailable"]
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class WhatsAppProviderWebhookStatusItem(BaseModel):
    event_type: WhatsAppProviderWebhookEventType
    status: str
    processing_enabled: bool = False
    message: str = ""


class WhatsAppProviderHealthResponse(BaseModel):
    providers_total: int = 0
    providers_active: int = 0
    configurations_total: int = 0
    configurations_validated: int = 0
    last_connection_test: Optional[datetime] = None
    overall_status: Literal["ok", "degraded", "unavailable"] = "ok"
    provider_health: list[WhatsAppProviderHealthItem] = Field(default_factory=list)
    integration_checks: list[WhatsAppProviderIntegrationCheck] = Field(default_factory=list)
    webhook_status: list[WhatsAppProviderWebhookStatusItem] = Field(default_factory=list)
    safety: dict[str, bool] = Field(default_factory=dict)


class WhatsAppProviderRegisterRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=255)
    provider_type: WhatsAppProviderType
    tenant_id: Optional[UUID] = None
    phone_number: Optional[str] = None
    business_account_id: Optional[str] = None
    config_json: Optional[dict[str, Any]] = None


class WhatsAppProviderRegisterResponse(BaseModel):
    provider: WhatsAppProviderResponse
    configuration: Optional[WhatsAppProviderConfigurationResponse] = None
    message: str = ""


class WhatsAppProviderTestConnectionRequest(BaseModel):
    provider_id: UUID
    config_json: Optional[dict[str, Any]] = None


class WhatsAppProviderTestConnectionResponse(BaseModel):
    ok: bool
    provider_id: UUID
    provider_name: str
    provider_type: WhatsAppProviderType
    message: str
    latency_ms: int = 0
    config_valid: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
