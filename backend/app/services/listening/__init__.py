"""Social Listening Phase 1 — service package.

Read-only observed-mentions foundation. No provider mutation methods exist
in this package. Live social listening providers are not wired in Phase 1;
only ``manual_import`` and ``fixture`` source adapters are supported.
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
