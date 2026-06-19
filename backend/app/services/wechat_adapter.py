"""WeChat adapter layer — abstract interface for future WeCom / Official Account / connectors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class WeChatAdapterTestResult:
    ok: bool
    provider: str
    message: str
    latency_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class WeChatAdapterContact:
    external_id: str
    name: str
    wechat_id: str | None = None
    wecom_id: str | None = None
    company: str | None = None
    phone: str | None = None
    country: str | None = None
    preferred_language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WeChatAdapterMessage:
    external_id: str
    direction: str  # inbound only from sync adapters
    sender_name: str
    message_text: str
    sent_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WeChatAdapterConversation:
    external_id: str
    title: str
    channel: str  # wechat | wecom
    external_contact_id: str | None = None
    last_message_at: datetime | None = None
    messages: list[WeChatAdapterMessage] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class WeChatAdapter(ABC):
    """Provider-agnostic WeChat read/sync interface. No message sending."""

    provider_id: str = "abstract"

    @abstractmethod
    async def test_connection(self, account_config: dict[str, Any]) -> WeChatAdapterTestResult:
        ...

    @abstractmethod
    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WeChatAdapterContact]:
        ...

    @abstractmethod
    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WeChatAdapterConversation]:
        ...


class DemoWeChatAdapter(WeChatAdapter):
    """Demo adapter — sample data for integration testing without production credentials."""

    provider_id = "demo"

    async def test_connection(self, account_config: dict[str, Any]) -> WeChatAdapterTestResult:
        account_type = account_config.get("account_type") or "personal_wechat"
        return WeChatAdapterTestResult(
            ok=True,
            provider=self.provider_id,
            message=f"Demo connection OK ({account_type}) — no live API configured",
            latency_ms=12,
            details={"mode": "demo", "send_capable": False},
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WeChatAdapterContact]:
        _ = since
        account_type = account_config.get("account_type") or "personal_wechat"
        prefix = "wxid" if account_type == "personal_wechat" else "wcom"
        return [
            WeChatAdapterContact(
                external_id=f"{prefix}_demo_buyer_01",
                name="Li Wei (Demo Buyer)",
                wechat_id=f"{prefix}_demo_buyer_01" if account_type != "wecom" else None,
                wecom_id=f"{prefix}_demo_buyer_01" if account_type == "wecom" else None,
                company="Shenzhen Import Co.",
                country="CN",
                preferred_language="zh",
            ),
            WeChatAdapterContact(
                external_id=f"{prefix}_demo_buyer_02",
                name="Anna Chen (Demo)",
                wechat_id=f"{prefix}_demo_buyer_02",
                company="Tashkent Trading LLC",
                country="UZ",
                preferred_language="ru",
            ),
        ]

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WeChatAdapterConversation]:
        _ = since
        account_type = account_config.get("account_type") or "personal_wechat"
        channel = "wecom" if account_type == "wecom" else "wechat"
        prefix = "wxid" if channel == "wechat" else "wcom"
        ext_contact = f"{prefix}_demo_buyer_01"
        conv = WeChatAdapterConversation(
            external_id=f"conv_{ext_contact}",
            title="Li Wei — product inquiry (demo)",
            channel=channel,
            external_contact_id=ext_contact,
        )
        if include_messages:
            from datetime import timezone

            now = datetime.now(timezone.utc)
            conv.messages = [
                WeChatAdapterMessage(
                    external_id="msg_demo_01",
                    direction="inbound",
                    sender_name="Li Wei",
                    message_text="Hello, we are interested in your export catalog. MOQ?",
                    sent_at=now,
                ),
            ]
            conv.last_message_at = now
        return [conv]


class WeComApiAdapter(WeChatAdapter):
    """Placeholder for future WeCom API — not implemented in v1."""

    provider_id = "wecom_api"

    async def test_connection(self, account_config: dict[str, Any]) -> WeChatAdapterTestResult:
        _ = account_config
        return WeChatAdapterTestResult(
            ok=False,
            provider=self.provider_id,
            message="WeCom API adapter not configured — register credentials in account config",
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WeChatAdapterContact]:
        _ = account_config, since
        return []

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WeChatAdapterConversation]:
        _ = account_config, since, include_messages
        return []


class OfficialAccountAdapter(WeChatAdapter):
    """Placeholder for future Official Account API — not implemented in v1."""

    provider_id = "official_account"

    async def test_connection(self, account_config: dict[str, Any]) -> WeChatAdapterTestResult:
        _ = account_config
        return WeChatAdapterTestResult(
            ok=False,
            provider=self.provider_id,
            message="Official Account API adapter not configured",
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WeChatAdapterContact]:
        _ = account_config, since
        return []

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WeChatAdapterConversation]:
        _ = account_config, since, include_messages
        return []


class ThirdPartyConnectorAdapter(WeChatAdapter):
    """Placeholder for third-party WeChat connectors — not implemented in v1."""

    provider_id = "third_party"

    async def test_connection(self, account_config: dict[str, Any]) -> WeChatAdapterTestResult:
        _ = account_config
        return WeChatAdapterTestResult(
            ok=False,
            provider=self.provider_id,
            message="Third-party connector not configured",
        )

    async def fetch_contacts(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
    ) -> list[WeChatAdapterContact]:
        _ = account_config, since
        return []

    async def fetch_conversations(
        self,
        account_config: dict[str, Any],
        *,
        since: datetime | None = None,
        include_messages: bool = True,
    ) -> list[WeChatAdapterConversation]:
        _ = account_config, since, include_messages
        return []


_ADAPTERS: dict[str, WeChatAdapter] = {
    "demo": DemoWeChatAdapter(),
    "wecom_api": WeComApiAdapter(),
    "official_account": OfficialAccountAdapter(),
    "third_party": ThirdPartyConnectorAdapter(),
}


def resolve_adapter(provider: str | None, account_type: str) -> WeChatAdapter:
    if provider and provider in _ADAPTERS:
        return _ADAPTERS[provider]
    if account_type == "wecom":
        return _ADAPTERS["wecom_api"]
    if account_type == "official_account":
        return _ADAPTERS["official_account"]
    return _ADAPTERS["demo"]


def list_adapter_providers() -> list[str]:
    return list(_ADAPTERS.keys())
