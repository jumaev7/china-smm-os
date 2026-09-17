"""Normalized scenario captures for old/new comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID


def _norm_id(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    return value


def normalize_payload(obj: Any) -> Any:
    """Normalize only nondeterministic UUIDs/timestamps; keep identity fields."""
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in {"created_at", "updated_at", "finished_at", "started_at",
                     "claimed_at", "lease_expires_at", "next_retry_at",
                     "approved_at", "published_at"}:
                out[k] = "<ts>" if v is not None else None
            elif k.endswith("_at") and v is not None and not isinstance(v, (bool, int)):
                out[k] = "<ts>"
            else:
                out[k] = normalize_payload(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [normalize_payload(x) for x in obj]
    return str(obj) if not isinstance(obj, (bytes, bytearray)) else obj


@dataclass
class ProviderCallCapture:
    count: int = 0
    platform: str | None = None
    account_id: str | None = None
    payload_identity: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ScenarioCapture:
    scenario_id: str
    side: str  # "old" | "new"
    schema_mode: str  # "A_historical" | "B_old_on_r1" | "C_new_on_r1"
    provider_calls: int = 0
    provider_platform: str | None = None
    provider_account_id: str | None = None
    suppression_decision: str | None = None  # suppress|allow|conflict|n/a
    api_result: dict[str, Any] | None = None
    publish_attempt_status: str | None = None
    retry_command_status: str | None = None
    content_status: str | None = None
    external_post_id: str | None = None
    response_provider_id: str | None = None
    identity_conflict: bool | None = None
    registry_row_count: int = 0
    shadow_reads: int = 0
    shadow_audit_writes: int = 0
    registry_inserts: int = 0
    registry_updates: int = 0
    authority_acquisitions: int = 0
    audit_events: list[str] = field(default_factory=list)
    alert_events: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def comparable(self) -> dict[str, Any]:
        raw = asdict(self)
        raw.pop("side", None)
        raw.pop("error", None)
        return normalize_payload(raw)


def capture_from_prior(
    *,
    scenario_id: str,
    side: str,
    schema_mode: str,
    prior: dict[str, dict],
    platform: str,
    provider_calls: int = 0,
    registry_row_count: int = 0,
    **extra: Any,
) -> ScenarioCapture:
    row = prior.get(platform) or {}
    conflict = bool(row.get("identity_conflict"))
    if not row:
        decision = "allow"
    elif conflict:
        decision = "conflict"
    else:
        decision = "suppress"
    return ScenarioCapture(
        scenario_id=scenario_id,
        side=side,
        schema_mode=schema_mode,
        provider_calls=provider_calls,
        provider_platform=platform,
        suppression_decision=decision,
        api_result=normalize_payload(row) if row else {},
        external_post_id=_norm_id(extra.pop("external_post_id", None)),
        response_provider_id=row.get("platform_post_id")
        or row.get("conflict_response_platform_post_id"),
        identity_conflict=conflict if row else False,
        registry_row_count=registry_row_count,
        extras=normalize_payload(extra) if extra else {},
    )
