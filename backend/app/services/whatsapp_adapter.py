"""WhatsApp adapter layer — abstract interface for Cloud API / Business API / connectors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WhatsAppAdapterTestResult:
    ok: bool
    provider: str
    message: str
    latency_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class WhatsAppAdapterContact:
    external_id: str
    name: str
    phone: str | None = None
    company: str | None = None
    country: str | None = None
    preferred_language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WhatsAppAdapterMessage:
    external_id: str
    direction: str  # inbound only from sync adapters
    sender_name: str
    message_text: str
    sent_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WhatsAppAdapterConversation:
    external_id: str
    title: str
    channel: str = "whatsapp"
    external_contact_id: str | None = None
    phone: str | None = None
    last_message_at: datetime | None = None
    messages: list[WhatsAppAdapterMessage] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class WhatsAppAdapter(ABC):
    """Provider-agnostic WhatsApp read/sync interface. No message sending."""

    provider_id: str = "abstract"

    @abstractmethod
    async def test_connection(self, account_config: dict[str, Any]) -> WhatsAppAdapterTestResult:
        ...

    @abstractmethod
    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WhatsAppAdapterContact]:
        ...

    @abstractmethod
    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WhatsAppAdapterConversation]:
        ...


class DemoWhatsAppAdapter(WhatsAppAdapter):
    """Demo adapter — sample data for integration testing without production credentials."""

    provider_id = "demo"

    async def test_connection(self, account_config: dict[str, Any]) -> WhatsAppAdapterTestResult:
        account_type = account_config.get("account_type") or "whatsapp_cloud_api"
        return WhatsAppAdapterTestResult(
            ok=True,
            provider=self.provider_id,
            message=f"Demo connection OK ({account_type}) — no live API configured",
            latency_ms=15,
            details={"mode": "demo", "send_capable": False},
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WhatsAppAdapterContact]:
        _ = since, account_config
        return [
            WhatsAppAdapterContact(
                external_id="wa_demo_buyer_01",
                name="Ahmed Karimov (Demo)",
                phone="+998901234501",
                company="Tashkent Trading LLC",
                country="UZ",
                preferred_language="ru",
            ),
            WhatsAppAdapterContact(
                external_id="wa_demo_buyer_02",
                name="Li Wei (Demo)",
                phone="+8613800138501",
                company="Guangzhou Export Co.",
                country="CN",
                preferred_language="zh",
            ),
        ]

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WhatsAppAdapterConversation]:
        _ = since, account_config
        from datetime import timezone

        now = datetime.now(timezone.utc)
        conv = WhatsAppAdapterConversation(
            external_id="wa_conv_demo_buyer_01",
            title="Ahmed Karimov — catalog inquiry (demo)",
            external_contact_id="wa_demo_buyer_01",
            phone="+998901234501",
            last_message_at=now,
        )
        if include_messages:
            conv.messages = [
                WhatsAppAdapterMessage(
                    external_id="wa_msg_demo_01",
                    direction="inbound",
                    sender_name="Ahmed Karimov",
                    message_text="Hello, please send your export price list and MOQ.",
                    sent_at=now,
                ),
            ]
        return [conv]


class MetaCloudApiAdapter(WhatsAppAdapter):
    """Placeholder for Meta WhatsApp Cloud API — not implemented in v1."""

    provider_id = "meta_cloud_api"

    async def test_connection(self, account_config: dict[str, Any]) -> WhatsAppAdapterTestResult:
        _ = account_config
        return WhatsAppAdapterTestResult(
            ok=False,
            provider=self.provider_id,
            message="Meta WhatsApp Cloud API adapter not configured — add credentials in account config",
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WhatsAppAdapterContact]:
        _ = account_config, since
        return []

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WhatsAppAdapterConversation]:
        _ = account_config, since, include_messages
        return []


class WhatsAppBusinessApiAdapter(WhatsAppAdapter):
    """Placeholder for WhatsApp Business API — not implemented in v1."""

    provider_id = "whatsapp_business_api"

    async def test_connection(self, account_config: dict[str, Any]) -> WhatsAppAdapterTestResult:
        _ = account_config
        return WhatsAppAdapterTestResult(
            ok=False,
            provider=self.provider_id,
            message="WhatsApp Business API adapter not configured",
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WhatsAppAdapterContact]:
        _ = account_config, since
        return []

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WhatsAppAdapterConversation]:
        _ = account_config, since, include_messages
        return []


class ThirdPartyConnectorAdapter(WhatsAppAdapter):
    """Placeholder for third-party WhatsApp connectors — not implemented in v1."""

    provider_id = "third_party"

    async def test_connection(self, account_config: dict[str, Any]) -> WhatsAppAdapterTestResult:
        _ = account_config
        return WhatsAppAdapterTestResult(
            ok=False,
            provider=self.provider_id,
            message="Third-party connector not configured",
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WhatsAppAdapterContact]:
        _ = account_config, since
        return []

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WhatsAppAdapterConversation]:
        _ = account_config, since, include_messages
        return []


class ManualImportAdapter(WhatsAppAdapter):
    """Placeholder for manual CSV/import connector — not implemented in v1."""

    provider_id = "manual_import"

    async def test_connection(self, account_config: dict[str, Any]) -> WhatsAppAdapterTestResult:
        _ = account_config
        return WhatsAppAdapterTestResult(
            ok=False,
            provider=self.provider_id,
            message="Manual import connector not configured — upload via operator workflow",
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WhatsAppAdapterContact]:
        _ = account_config, since
        return []

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WhatsAppAdapterConversation]:
        _ = account_config, since, include_messages
        return []


_ADAPTERS: dict[str, WhatsAppAdapter] = {
    "demo": DemoWhatsAppAdapter(),
    "meta_cloud_api": MetaCloudApiAdapter(),
    "whatsapp_business_api": WhatsAppBusinessApiAdapter(),
    "third_party": ThirdPartyConnectorAdapter(),
    "manual_import": ManualImportAdapter(),
}


def resolve_adapter(provider: str | None, account_type: str) -> WhatsAppAdapter:
    if provider and provider in _ADAPTERS:
        return _ADAPTERS[provider]
    if account_type == "whatsapp_cloud_api":
        return _ADAPTERS["meta_cloud_api"]
    if account_type == "whatsapp_business_api":
        return _ADAPTERS["whatsapp_business_api"]
    if account_type == "third_party_connector":
        return _ADAPTERS["third_party"]
    if account_type == "manual_import":
        return _ADAPTERS["manual_import"]
    return _ADAPTERS["demo"]


def list_adapter_providers() -> list[str]:
    return list(_ADAPTERS.keys())
