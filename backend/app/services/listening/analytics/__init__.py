"""Social Listening Phase 2 — evidence-backed market intelligence.

Computed read layer over Phase 1 normalized observations. No provider calls,
no forecasting, no Business Health coupling, no sentiment dependency.
"""
from __future__ import annotations

from app.services.listening.analytics.contracts import (
    ANOMALY_METHOD_VERSION,
    COVERAGE_POLICY_VERSION,
    INSIGHT_METHOD_VERSION,
    SOV_METHOD_VERSION,
    TOPIC_METHOD_VERSION,
    WINDOW_METHOD_VERSION,
)
from app.services.listening.analytics.intelligence_service import ListeningIntelligenceService

__all__ = [
    "ListeningIntelligenceService",
    "COVERAGE_POLICY_VERSION",
    "WINDOW_METHOD_VERSION",
    "SOV_METHOD_VERSION",
    "TOPIC_METHOD_VERSION",
    "ANOMALY_METHOD_VERSION",
    "INSIGHT_METHOD_VERSION",
]
