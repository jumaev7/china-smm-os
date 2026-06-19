"""Validate and normalize client Telegram publish destinations."""
from __future__ import annotations

import re

TELEGRAM_PUBLISH_TYPES = frozenset({"channel", "supergroup"})

_CHANNEL_USERNAME_RE = re.compile(r"^@[a-zA-Z][a-zA-Z0-9_]{3,31}$")
_SUPERGROUP_CHAT_RE = re.compile(r"^-100\d{6,}$")


def normalize_telegram_publish_chat_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Telegram publish chat ID is required")
    if raw.startswith("@"):
        return raw
    if raw.startswith("-") or raw.isdigit():
        return raw
    return f"@{raw.lstrip('@')}"


def validate_telegram_publish_chat_id(value: str | None) -> str | None:
    """
    Publish destination may be @channel_username or -100xxxxxxxxxx (supergroup/channel id).
    Returns normalized value or None when empty.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None

    normalized = normalize_telegram_publish_chat_id(raw)

    if normalized.startswith("@"):
        if not _CHANNEL_USERNAME_RE.match(normalized):
            raise ValueError(
                "Invalid channel username. Use format @my_channel (letters, digits, underscore).",
            )
        return normalized

    if _SUPERGROUP_CHAT_RE.match(normalized):
        return normalized

    raise ValueError(
        "Invalid Telegram publish destination. Use @channel_username or -1003980920346.",
    )


def validate_telegram_publish_type(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    lowered = str(value).strip().lower()
    if lowered not in TELEGRAM_PUBLISH_TYPES:
        raise ValueError("telegram_publish_type must be channel or supergroup")
    return lowered
