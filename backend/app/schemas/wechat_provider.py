"""WeChat Provider v1 — API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WeChatProviderType = Literal[
    "wecom_api",
    "official_account_api",
    "third_party_connector",
    "custom_provider",
]
WeChatProviderStatus = Literal["pending", "active", "inactive", "error"]
WeChatProviderConfigStatus = Literal["draft", "configured", "validated", "error"]
WeChatProviderWebhookEventType = Literal[
    "inbound_message",
    "contact_update",
    "conversation_update",
]


class WeChatProviderCapabilities(BaseModel):
    contact_sync: bool = False
    conversation_sync: bool = False
    message_send: bool = False
    media_upload: bool = False
    webhook_support: bool = False


class WeChatProviderResponse(BaseModel):
    id: UUID
    provider_name: str
    provider_type: WeChatProviderType
    status: WeChatProviderStatus
    capabilities: WeChatProviderCapabilities
    created_at: datetime

    model_config = {"from_attributes": True}


class WeChatProvidersResponse(BaseModel):
    items: list[WeChatProviderResponse]
    total: int


class WeChatProviderConfigurationResponse(BaseModel):
    id: UUID
    provider_id: UUID
    provider_name: Optional[str] = None
    tenant_id: Optional[UUID] = None
    config_status: WeChatProviderConfigStatus
    last_connection_test: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WeChatProviderConfigurationsResponse(BaseModel):
    items: list[WeChatProviderConfigurationResponse]
    total: int


class WeChatProviderHealthItem(BaseModel):
    provider_id: UUID
    provider_name: str
    provider_type: WeChatProviderType
    status: WeChatProviderStatus
    config_status: Optional[WeChatProviderConfigStatus] = None
    last_connection_test: Optional[datetime] = None
    connection_ok: bool = False
    message: str = ""


class WeChatProviderIntegrationCheck(BaseModel):
    module: str
    status: Literal["ok", "degraded", "unavailable"]
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class WeChatProviderWebhookStatusItem(BaseModel):
    event_type: WeChatProviderWebhookEventType
    status: str
    processing_enabled: bool = False
    message: str = ""


class WeChatProviderHealthResponse(BaseModel):
    providers_total: int = 0
    providers_active: int = 0
    configurations_total: int = 0
    configurations_validated: int = 0
    last_connection_test: Optional[datetime] = None
    overall_status: Literal["ok", "degraded", "unavailable"] = "ok"
    provider_health: list[WeChatProviderHealthItem] = Field(default_factory=list)
    integration_checks: list[WeChatProviderIntegrationCheck] = Field(default_factory=list)
    webhook_status: list[WeChatProviderWebhookStatusItem] = Field(default_factory=list)
    safety: dict[str, bool] = Field(default_factory=dict)


class WeChatProviderRegisterRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=255)
    provider_type: WeChatProviderType
    tenant_id: Optional[UUID] = None
    config_json: Optional[dict[str, Any]] = None


class WeChatProviderRegisterResponse(BaseModel):
    provider: WeChatProviderResponse
    configuration: Optional[WeChatProviderConfigurationResponse] = None
    message: str = ""


class WeChatProviderTestConnectionRequest(BaseModel):
    provider_id: UUID
    config_json: Optional[dict[str, Any]] = None


class WeChatProviderTestConnectionResponse(BaseModel):
    ok: bool
    provider_id: UUID
    provider_name: str
    provider_type: WeChatProviderType
    message: str
    latency_ms: int = 0
    config_valid: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
