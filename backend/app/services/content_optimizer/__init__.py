"""Deterministic Content Optimizer — immutable, provenance-safe platform variants.

Restructures, shortens, splits, normalizes, selects and reorders *existing*
content into platform/locale/length variants. No LLM, no paraphrasing, no
translation, no invented hashtags/CTAs/facts — identical inputs always produce
identical outputs, and the source content is never mutated during optimization.
"""
from __future__ import annotations

from app.services.content_optimizer.optimizer_service import (
    OPTIMIZER_VERSION,
    ContentOptimizerService,
)
from app.services.content_optimizer.source_fingerprint import SOURCE_FINGERPRINT_VERSION
from app.services.content_optimizer.variant_fingerprint import VARIANT_FINGERPRINT_VERSION

__all__ = [
    "OPTIMIZER_VERSION",
    "SOURCE_FINGERPRINT_VERSION",
    "VARIANT_FINGERPRINT_VERSION",
    "ContentOptimizerService",
]
