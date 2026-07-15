"""Unit tests for Marketing Intelligence — normalization, scoring, recommendations."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    from app.core.events.types import PlatformEvent
    from app.services.intelligence.collectors import collect_signals
    from app.services.intelligence.collectors.publishing import PublishingCollector
    from app.services.intelligence.normalizer import normalize_signal
    from app.services.intelligence.recommendation_engine import RecommendationEngine
    from app.services.intelligence.scoring_engine import ScoringEngine
    from app.services.intelligence.types import SCORING_ENGINE_VERSION

    tenant_id = uuid4()

    # --- Normalizer ---
    signal = normalize_signal(
        tenant_id=tenant_id,
        signal_type="publishing.failed",
        source="publishing",
        severity="error",
        metadata={"token": "secret-value", "ok": True},
        confidence=1.5,
    )
    record("normalizer_clamps_confidence", float(signal.confidence) == 1.0, str(signal.confidence))
    record("normalizer_redacts_secrets", signal.metadata.get("token") == "[redacted]")
    record("normalizer_keeps_safe_fields", signal.metadata.get("ok") is True)

    try:
        normalize_signal(tenant_id=tenant_id, signal_type="unknown.type", source="publishing")
        record("normalizer_rejects_unknown_type", False, "expected ValueError")
    except ValueError:
        record("normalizer_rejects_unknown_type", True)

    # --- Collectors ---
    event = PlatformEvent(
        event_type="tenant.content.publish_failed",
        tenant_id=tenant_id,
        payload={"platform": "instagram"},
        resource_type="content",
        resource_id=str(uuid4()),
        occurred_at=datetime.now(timezone.utc),
    )
    collected = PublishingCollector().collect(event)
    record("publishing_collector_one_signal", len(collected) == 1)
    record(
        "publishing_collector_type",
        collected[0].signal_type == "publishing.failed",
        collected[0].signal_type if collected else "",
    )

    deal_event = PlatformEvent(
        event_type="tenant.crm.deal_stage_changed",
        tenant_id=tenant_id,
        payload={"to_stage": "won"},
        resource_type="deal",
        resource_id=str(uuid4()),
    )
    deal_signals = collect_signals(deal_event)
    types = sorted(s.signal_type for s in deal_signals)
    record(
        "crm_collector_won_derives_two_signals",
        types == ["crm.deal_stage_changed", "crm.deal_won"],
        str(types),
    )

    # --- Scoring determinism ---
    counts = {
        "publishing.completed": 5,
        "publishing.failed": 2,
        "publishing.partial_failed": 1,
        "crm.lead_created": 3,
        "crm.buyer_created": 1,
        "crm.deal_won": 1,
        "automation.triggered": 4,
        "content.created": 2,
        "customer_success.milestone": 1,
    }
    scores_a = ScoringEngine.compute_from_counts(counts)
    scores_b = ScoringEngine.compute_from_counts(counts)
    map_a = {s.category: s.score for s in scores_a}
    map_b = {s.category: s.score for s in scores_b}
    record("score_determinism", map_a == map_b, f"{map_a} vs {map_b}")
    record("score_has_overall", "overall" in map_a)
    record("score_version", all(s.scoring_version == SCORING_ENGINE_VERSION for s in scores_a))
    record(
        "score_explainable",
        all(
            isinstance(s.explanation, dict)
            and "observation" in s.explanation
            and "reasoning" in s.explanation
            for s in scores_a
        ),
    )

    empty_scores = ScoringEngine.compute_from_counts({})
    empty_map = {s.category: s.score for s in empty_scores}
    record("score_empty_is_stable", empty_map == {s.category: s.score for s in ScoringEngine.compute_from_counts({})})

    # Failures should pull publishing below a high-success baseline
    good = {s.category: s.score for s in ScoringEngine.compute_from_counts({"publishing.completed": 10})}
    bad = {
        s.category: s.score
        for s in ScoringEngine.compute_from_counts({"publishing.completed": 1, "publishing.failed": 5})
    }
    record(
        "score_publishing_penalizes_failures",
        bad["publishing"] < good["publishing"],
        f"good={good['publishing']} bad={bad['publishing']}",
    )

    # --- Recommendation determinism ---
    score_map = map_a
    recs_a = RecommendationEngine.compute_from_counts(
        {"publishing.failed": 3, "integration.disconnected": 1},
        score_map,
    )
    recs_b = RecommendationEngine.compute_from_counts(
        {"publishing.failed": 3, "integration.disconnected": 1},
        score_map,
    )
    keys_a = [r.recommendation_key for r in recs_a]
    keys_b = [r.recommendation_key for r in recs_b]
    record("recommendation_determinism", keys_a == keys_b, f"{keys_a}")
    record(
        "recommendation_includes_publish_review",
        "publishing.review_accounts" in keys_a,
        str(keys_a),
    )
    record(
        "recommendation_includes_reconnect",
        "integration.reconnect" in keys_a,
        str(keys_a),
    )
    record(
        "recommendation_explainable",
        all(
            r.explanation
            and r.explanation.get("observation")
            and r.explanation.get("reasoning")
            and r.explanation.get("recommendation")
            for r in recs_a
        ),
    )
    record(
        "recommendation_has_evidence",
        all(isinstance(r.evidence, dict) and r.evidence for r in recs_a),
    )

    # Registry intelligence flag
    from app.core.events.registry import event_registry

    pub_def = event_registry.get("tenant.content.publish_failed")
    record(
        "registry_intelligence_flag",
        pub_def is not None and pub_def.integrations.intelligence is True,
    )

    if failures:
        print(f"\nFAILED {len(failures)} checks")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll intelligence unit checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
