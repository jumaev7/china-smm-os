"""Marketing Intelligence Platform service package.

Architecture (Phase 1 — deterministic, no LLM):

  Platform Events → Collectors → Normalizer → Knowledge Store
       → Scoring Engine → Recommendation Engine → Explanation Engine
       → Future AI Copilot

Prediction engine and LLM integrations are intentionally deferred.
"""
from __future__ import annotations

from app.services.intelligence.service import IntelligenceService

__all__ = ["IntelligenceService"]
