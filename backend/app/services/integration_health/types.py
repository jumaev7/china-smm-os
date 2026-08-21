"""Integration health result types (no secrets)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


@dataclass
class CapabilityHealth:
    name: str
    status: str  # healthy | degraded | action_required | unavailable | unknown | not_configured
    reason_code: str
    reason: str
    requires_operator_action: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrationHealthResult:
    integration_id: str
    platform: str
    provider: str
    tenant_id: str | None
    client_id: str | None
    account_name: str | None
    status: str
    severity: str
    reason_code: str
    reason: str
    checked_at: datetime | None
    last_success_at: datetime | None
    stale_after_seconds: int
    stale: bool
    requires_operator_action: bool
    responsible_party: str
    recommended_next_step: str
    deep_link: str
    capabilities: list[CapabilityHealth] = field(default_factory=list)
    source: str = "local"  # local | remote | cached
    never_checked: bool = False
    transient_failure_count: int = 0
    safe_auto_recheck: bool = True
    # Internal-only diagnostics (never tokens); scrubbed for API.
    diagnostic: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        """API-safe payload — no tokens, no raw provider blobs."""
        return {
            "integration_id": self.integration_id,
            "platform": self.platform,
            "provider": self.provider,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "account_name": self.account_name,
            "status": self.status,
            "severity": self.severity,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "checked_at": _iso(self.checked_at),
            "last_success_at": _iso(self.last_success_at),
            "stale_after_seconds": self.stale_after_seconds,
            "stale": self.stale,
            "requires_operator_action": self.requires_operator_action,
            "responsible_party": self.responsible_party,
            "recommended_next_step": self.recommended_next_step,
            "deep_link": self.deep_link,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "source": self.source,
            "never_checked": self.never_checked,
            "transient_failure_count": self.transient_failure_count,
            "safe_auto_recheck": self.safe_auto_recheck,
        }


def parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
