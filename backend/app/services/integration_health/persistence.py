"""Diagnostic health state in existing PublishingAccount.account_metadata_json.

No migration: reuses the existing TEXT JSON column under key ``integration_health``.
Never stores tokens or secrets.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.models.publishing_account import PublishingAccount

logger = logging.getLogger(__name__)

METADATA_KEY = "integration_health"

# Fields allowed in durable diagnostic snapshots (deny-by-default).
_ALLOWED_KEYS = frozenset({
    "status",
    "severity",
    "reason_code",
    "reason",
    "checked_at",
    "last_success_at",
    "stale_after_seconds",
    "requires_operator_action",
    "responsible_party",
    "recommended_next_step",
    "capabilities",
    "source",
    "never_checked",
    "transient_failure_count",
    "transient_window_started_at",
    "escalated",
    "safe_auto_recheck",
    "provider_error_class",
})


def _loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def read_diagnostic(account: PublishingAccount) -> dict[str, Any]:
    raw_meta = getattr(account, "account_metadata_json", None)
    meta = _loads(raw_meta if isinstance(raw_meta, str) or raw_meta is None else None)
    raw = meta.get(METADATA_KEY)
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in _ALLOWED_KEYS}


def write_diagnostic(account: PublishingAccount, snapshot: dict[str, Any]) -> None:
    """Merge a scrubbed diagnostic snapshot into account_metadata_json."""
    meta = _loads(account.account_metadata_json)
    clean = {k: v for k, v in snapshot.items() if k in _ALLOWED_KEYS}
    # Never persist anything that looks like a secret.
    for banned in ("token", "access_token", "refresh_token", "secret", "password", "authorization"):
        for key in list(clean.keys()):
            if banned in key.lower():
                clean.pop(key, None)
    meta[METADATA_KEY] = clean
    account.account_metadata_json = _dumps(meta)


def clear_transient_state(diag: dict[str, Any]) -> dict[str, Any]:
    out = dict(diag)
    out["transient_failure_count"] = 0
    out.pop("transient_window_started_at", None)
    out["escalated"] = False
    return out


def apply_transient_failure(
    diag: dict[str, Any],
    *,
    now: datetime | None = None,
    window_seconds: int,
    threshold: int,
) -> dict[str, Any]:
    """Deterministic transient failure accounting + escalation flag."""
    now = now or _utc_now()
    out = dict(diag)
    started = _parse_dt(out.get("transient_window_started_at"))
    count = int(out.get("transient_failure_count") or 0)

    if started is None or (now - started).total_seconds() > window_seconds:
        started = now
        count = 1
    else:
        count += 1

    out["transient_window_started_at"] = started.isoformat()
    out["transient_failure_count"] = count
    out["escalated"] = count >= threshold
    return out


def is_stale(
    checked_at: datetime | None,
    *,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> bool:
    if checked_at is None:
        return True
    now = now or _utc_now()
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return (now - checked_at).total_seconds() > stale_after_seconds


def parse_checked_at(diag: dict[str, Any]) -> datetime | None:
    return _parse_dt(diag.get("checked_at"))


def parse_last_success_at(diag: dict[str, Any]) -> datetime | None:
    return _parse_dt(diag.get("last_success_at"))
