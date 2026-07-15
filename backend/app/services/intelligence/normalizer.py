"""Normalize and validate marketing signals before persistence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.models.intelligence import SIGNAL_SEVERITIES, SIGNAL_SOURCES
from app.services.intelligence.types import (
    DEFAULT_SIGNAL_CONFIDENCE,
    SIGNAL_TYPES,
    NormalizedSignal,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_confidence(value: Any) -> Decimal:
    try:
        conf = Decimal(str(value))
    except Exception:
        return DEFAULT_SIGNAL_CONFIDENCE
    if conf < Decimal("0"):
        return Decimal("0.000")
    if conf > Decimal("1"):
        return Decimal("1.000")
    return conf.quantize(Decimal("0.001"))


def _sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Strip secrets / oversized values; keep signal payloads inspectable."""
    if not metadata:
        return {}
    out: dict[str, Any] = {}
    blocked = {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "secret",
        "authorization",
        "private_key",
    }
    for key, value in metadata.items():
        key_l = str(key).lower()
        if any(b in key_l for b in blocked):
            out[str(key)] = "[redacted]"
            continue
        if isinstance(value, str) and len(value) > 2000:
            out[str(key)] = value[:2000] + "…"
        elif isinstance(value, (dict, list)):
            # Shallow copy only — collectors should not embed nested secrets.
            out[str(key)] = deepcopy(value)
        else:
            out[str(key)] = value
    return out


def normalize_signal(
    *,
    tenant_id: UUID,
    signal_type: str,
    source: str,
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: str | None = None,
    occurred_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    confidence: Any = None,
    signal_id: UUID | None = None,
    platform_event_id: UUID | None = None,
    platform_event_type: str | None = None,
) -> NormalizedSignal:
    """Validate and produce an immutable NormalizedSignal."""
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"Unknown signal_type: {signal_type}")
    if source not in SIGNAL_SOURCES:
        raise ValueError(f"Unknown signal source: {source}")
    if severity not in SIGNAL_SEVERITIES:
        severity = "info"

    ts = occurred_at or _utcnow()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return NormalizedSignal(
        signal_id=signal_id or platform_event_id or uuid4(),
        tenant_id=tenant_id,
        signal_type=signal_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        occurred_at=ts,
        metadata=_sanitize_metadata(metadata),
        source=source,
        severity=severity,
        confidence=_clamp_confidence(confidence if confidence is not None else DEFAULT_SIGNAL_CONFIDENCE),
        platform_event_id=platform_event_id,
        platform_event_type=platform_event_type,
    )
