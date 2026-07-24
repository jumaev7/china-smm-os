"""Advertising Intelligence — read-only paid-media measurement domain.

Public entry points mirror the ``app.services.measurement`` package. This domain
never writes to any advertising provider; it imports, normalizes, and analyzes
advertising data and produces deterministic, evidence-backed diagnostics and
recommendations.
"""
from app.services.advertising_intelligence.metric_catalog import (
    ALL_METRIC_KEYS,
    CATALOG_VERSION,
    METRIC_CATALOG,
    METRIC_SEMANTICS_VERSION,
)

__all__ = [
    "ALL_METRIC_KEYS",
    "CATALOG_VERSION",
    "METRIC_CATALOG",
    "METRIC_SEMANTICS_VERSION",
]
