"""Deterministic Publishing Intelligence — pre-publish review and scoring (no LLM)."""
from __future__ import annotations

from app.services.publishing_intelligence.review_engine import PublishingReviewEngine

REVIEW_ENGINE_VERSION = "1.0.0"
FINGERPRINT_VERSION = "v1"

__all__ = [
    "PublishingReviewEngine",
    "REVIEW_ENGINE_VERSION",
    "FINGERPRINT_VERSION",
]
