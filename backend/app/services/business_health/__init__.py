"""Business Health Score v2 — explainable cross-domain executive health.

Decision support only. Deterministic heuristic. Never mutates providers,
campaigns, CRM entities, billing state, or automation runs.
"""
from __future__ import annotations

from app.services.business_health.engine import assess_business_health
from app.services.business_health.policy import BUSINESS_HEALTH_VERSION

__all__ = [
    "BUSINESS_HEALTH_VERSION",
    "assess_business_health",
]
