"""Numeric chat-ID validation and HTML escaping for operator-alert Telegram delivery."""
from __future__ import annotations

import html
import re
from typing import Any

# Telegram user IDs are positive; groups/supergroups/channels are negative integers.
_NUMERIC_CHAT_ID_RE = re.compile(r"^-?\d{5,20}$")


def validate_operator_telegram_chat_id(value: Any) -> int:
    """Accept only a numeric Telegram chat ID. Reject @usernames and free text."""
    if value is None:
        raise ValueError("Telegram chat ID is required")
    if isinstance(value, bool):
        raise ValueError("Telegram chat ID must be a numeric chat ID, not a boolean")
    if isinstance(value, int):
        chat_id = value
    elif isinstance(value, float) and value.is_integer():
        chat_id = int(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("Telegram chat ID is required")
        if raw.startswith("@"):
            raise ValueError(
                "Usernames are not accepted. Configure a numeric Telegram chat ID.",
            )
        if not _NUMERIC_CHAT_ID_RE.match(raw):
            raise ValueError(
                "Invalid Telegram chat ID. Use a numeric ID (e.g. 123456789 or -1001234567890).",
            )
        chat_id = int(raw)
    else:
        raise ValueError("Telegram chat ID must be numeric")

    if chat_id == 0:
        raise ValueError("Telegram chat ID cannot be zero")
    # Reject tiny numbers that are almost certainly typos / not real chat IDs
    if abs(chat_id) < 10_000:
        raise ValueError("Telegram chat ID looks invalid (too short)")
    return chat_id


def normalize_allowed_chat_ids(values: list[Any] | None) -> list[int]:
    if not values:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for item in values:
        chat_id = validate_operator_telegram_chat_id(item)
        if chat_id not in seen:
            seen.add(chat_id)
            out.append(chat_id)
    return out


def mask_chat_id(chat_id: int | None) -> str | None:
    """Mask a chat ID for responses to unauthorized roles (keep last 4 digits)."""
    if chat_id is None:
        return None
    s = str(chat_id)
    if len(s) <= 4:
        return "****"
    return f"{'*' * (len(s) - 4)}{s[-4:]}"


def escape_html(value: str | None) -> str:
    """Escape text for Telegram HTML parse_mode."""
    if not value:
        return ""
    return html.escape(str(value), quote=False)


def safe_plain(value: str | None, *, limit: int = 200) -> str:
    """Strip control chars and truncate for plain / snapshot fields."""
    if not value:
        return ""
    text = str(value).replace("\x00", "").replace("\r", " ").strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text[:limit]
