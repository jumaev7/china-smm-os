"""Verify Campaign Planner MIP signal mapping + recommendations.

Run from backend/:  python scripts/verify_campaign_signals.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from app.core.events.types import PlatformEvent
    from app.services.intelligence.collectors.campaign import CampaignCollector
    from app.services.intelligence.recommendation_engine import RecommendationEngine
    from app.services.intelligence.scoring_engine import ScoringEngine
    from app.services.intelligence.types import (
        PLATFORM_EVENT_TO_SOURCE,
        RECOMMENDATION_ENGINE_VERSION,
        SCORING_ENGINE_VERSION,
        SIGNAL_TYPES,
    )

    failures = []

    def record(c, ok, d=""):
        print(("OK" if ok else "FAIL") + f" {c}" + (f" — {d}" if d else ""))
        if not ok:
            failures.append(c)

    record("scoring_version", SCORING_ENGINE_VERSION == "1.4.0")
    record("rec_version", RECOMMENDATION_ENGINE_VERSION == "1.4.0")
    record("event_source_map", PLATFORM_EVENT_TO_SOURCE.get("campaign.plan_generated") == "content")
    record("signal_types_registered", "campaign.coverage_low" in SIGNAL_TYPES and "campaign.ai_plan_failed" in SIGNAL_TYPES)

    tenant_id = uuid4()
    now = datetime.now(timezone.utc)
    collector = CampaignCollector()

    event = PlatformEvent(
        event_type="campaign.plan_reviewed",
        occurred_at=now,
        tenant_id=tenant_id,
        resource_type="campaign",
        resource_id=str(uuid4()),
        payload={
            "coverage_low": True,
            "readiness_low": True,
            "unassigned_slots_high": True,
            "pillar_imbalance": True,
            "conflict_count": 2,
            "coverage_score": 40,
            "campaign_id": str(uuid4()),
        },
        title="Plan reviewed",
    )
    signals = collector.collect(event)
    types = {s.signal_type for s in signals}
    record("derived_coverage_low", "campaign.coverage_low" in types)
    record("derived_conflicts", "campaign.conflicts_detected" in types)
    record("derived_unassigned", "campaign.unassigned_slots_high" in types)

    for s in signals:
        payload = (s.metadata or {}).get("payload") or {}
        if "caption" in payload or "prompt" in payload:
            record("no_caption_leak", False)
            break
    else:
        record("no_caption_leak", True)

    counts = {
        "campaign.unassigned_slots_high": 2,
        "campaign.coverage_low": 1,
        "campaign.conflicts_detected": 2,
        "campaign.pillar_imbalance": 1,
        "campaign.readiness_low": 1,
        "campaign.plan_generated": 1,
        "campaign.ai_plan_failed": 1,
    }
    recs = RecommendationEngine.compute_from_counts(counts)
    keys = {r.recommendation_key for r in recs}
    record("rec_unfilled", "campaign.assign_unfilled_slots" in keys)
    record("rec_blocked", "campaign.resolve_blocked_accounts" in keys)
    record("rec_brand_for_ai", "campaign.publish_brand_profile_for_ai" in keys)

    score = ScoringEngine._score_content(counts)
    record("content_score_includes_campaign", "plan_generated" in (score.evidence or {}))

    print()
    if failures:
        print(f"FAILED {len(failures)}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
