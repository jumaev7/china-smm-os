"""Social Listening — service package.

Read-only observed mentions. No provider mutation methods exist in this package.
Phase 3 adds governed Facebook Page live read-only adapters
(``facebook_page_comments``, ``facebook_page_mentions``) that reuse publishing
account tokens without copying them into listening tables.
"""
from __future__ import annotations

from app.models.listening import (
    DEDUPE_VERSION,
    LISTENING_SCHEMA_VERSION,
    MATCHER_VERSION,
    NORMALIZATION_VERSION,
)

__all__ = [
    "LISTENING_SCHEMA_VERSION",
    "DEDUPE_VERSION",
    "MATCHER_VERSION",
    "NORMALIZATION_VERSION",
]
