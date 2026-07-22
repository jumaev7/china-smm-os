"""Attribution and aggregation confidence helpers.

Confidence values are explicit and method-bound. This module never invents
probabilistic multi-touch weights.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.measurement import ATTRIBUTION_METHODS

METHOD_CONFIDENCE: dict[str, Decimal] = {
    "direct_slot_assignment": Decimal("1.000"),
    "direct_campaign_publication": Decimal("0.900"),
    "manual_link": Decimal("0.700"),
    "unattributed": Decimal("0.000"),
}


def confidence_for_method(method: str, *, override: Decimal | None = None) -> Decimal:
    if method not in ATTRIBUTION_METHODS:
        return Decimal("0.000")
    if override is not None and method == "manual_link":
        # Manual links may carry a documented user-specified confidence in [0, 1].
        return max(Decimal("0"), min(Decimal("1"), override))
    return METHOD_CONFIDENCE[method]


def degrade_for_freshness(confidence: Decimal, freshness_status: str) -> Decimal:
    """Reduce confidence when data is stale/unavailable — never invent values."""
    if freshness_status in {"fresh"}:
        return confidence
    if freshness_status == "aging":
        return (confidence * Decimal("0.900")).quantize(Decimal("0.001"))
    if freshness_status == "stale":
        return (confidence * Decimal("0.700")).quantize(Decimal("0.001"))
    return Decimal("0.000")


__all__ = ["METHOD_CONFIDENCE", "confidence_for_method", "degrade_for_freshness"]
