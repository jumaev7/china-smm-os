"""Error classification and retry eligibility for automation executions."""
from __future__ import annotations

from typing import Any

from app.models.automation import (
    AUTOMATION_ACTION_TYPES,
    AUTOMATION_ERROR_CATEGORIES,
    MAX_RETRY_ATTEMPTS_BOUND,
)

# error_code -> (category, is_retryable)
_ERROR_CLASSIFICATION: dict[str, tuple[str, bool]] = {
    "invalid_config": ("validation", False),
    "unknown_action": ("configuration", False),
    "no_client": ("configuration", False),
    "crm_error": ("dependency", True),
    "execution_error": ("internal", True),
    "forbidden_action": ("validation", False),
    "tenant_mismatch": ("validation", False),
    "duplicate_superseded": ("conflict", False),
    "stale_payload": ("validation", False),
    "retry_limit": ("conflict", False),
}


def classify_automation_error(
    error_code: str | None,
    error_message: str | None = None,
) -> tuple[str, bool]:
    """Return (error_category, is_retryable) for a failed execution."""
    code = (error_code or "").strip().lower()
    if code in _ERROR_CLASSIFICATION:
        category, retryable = _ERROR_CLASSIFICATION[code]
        return category, retryable

    text = (error_message or "").lower()
    if any(tok in text for tok in ("timeout", "temporarily", "connection reset", "unavailable")):
        return "transient", True
    if any(tok in text for tok in ("invalid", "required", "must ", "validation")):
        return "validation", False
    if any(tok in text for tok in ("permission", "forbidden", "unauthorized")):
        return "configuration", False
    return "internal", True


def safe_error_message(message: str | None, *, max_len: int = 400) -> str | None:
    """Strip stack-trace-like content from client-facing error messages."""
    if not message:
        return None
    text = str(message).strip()
    # Drop traceback bodies while keeping the first line.
    for marker in ("\nTraceback", "\n  File ", "\nFile \""):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text or None


def sanitize_payload_summary(payload: dict[str, Any] | None, *, max_keys: int = 12) -> dict[str, Any] | None:
    """Return a shallow, secret-free summary suitable for API responses."""
    if not payload:
        return None
    forbidden = (
        "token", "secret", "password", "authorization", "api_key", "bearer", "encrypted",
    )
    out: dict[str, Any] = {}
    for key, value in list(payload.items())[:max_keys]:
        lowered = str(key).lower()
        if any(part in lowered for part in forbidden):
            continue
        if isinstance(value, dict):
            out[key] = {"_type": "object", "keys": list(value.keys())[:8]}
        elif isinstance(value, list):
            out[key] = {"_type": "list", "length": len(value)}
        elif isinstance(value, str) and len(value) > 240:
            out[key] = value[:239] + "…"
        else:
            out[key] = value
    return out


def clamp_max_retry_attempts(value: int | None) -> int:
    try:
        n = int(value if value is not None else 1)
    except (TypeError, ValueError):
        n = 1
    return max(0, min(n, MAX_RETRY_ATTEMPTS_BOUND))


def action_type_allowed(action_type: str | None) -> bool:
    return bool(action_type) and action_type in AUTOMATION_ACTION_TYPES


def normalize_error_category(category: str | None) -> str | None:
    if category and category in AUTOMATION_ERROR_CATEGORIES:
        return category
    return None
