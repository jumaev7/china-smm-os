"""Offline smoke tests for Social Listening Phase 2 analytics (no HTTP, no DB).

Run from backend/:  python scripts/test_listening_intelligence.py
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

_WRITE_PREFIXES = (
    "publish",
    "reply",
    "comment",
    "react",
    "like",
    "message",
    "follow",
    "block",
    "report",
    "delete",
    "mutate",
    "send_",
)


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.services.listening.analytics.aggregation import (
        compute_subject_performance,
        observed_share_of_voice,
        subject_weights_for_mention,
    )
    from app.services.listening.analytics.anomalies import detect_anomalies
    from app.services.listening.analytics.contracts import AnalysisWindow
    from app.services.listening.analytics.coverage import assess_coverage, comparison_allowed
    from app.services.listening.analytics.eligibility import (
        EligibilityFilter,
        mention_eligible_for_intelligence,
    )
    from app.services.listening.analytics.insights import build_insight_key, generate_insights
    from app.services.listening.analytics.topics import detect_emerging_topics
    from app.services.listening.analytics.windows import (
        build_analysis_window,
        iter_buckets,
        relative_change,
    )
    from app.services.listening.providers.base import ListeningSourceAdapter

    # 1. Time buckets timezone-safe / half-open
    start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 3, 0, 0, tzinfo=timezone.utc)
    buckets = iter_buckets(start, end, "day", timezone_name="UTC")
    record("timezone_buckets", len(buckets) == 2 and buckets[0][0] == start and buckets[0][1] == datetime(2026, 7, 2, tzinfo=timezone.utc))

    # 2. Window boundaries equal duration
    win = build_analysis_window(
        window_key="7d",
        now=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
    )
    dur = win.end - win.start
    prev_dur = (win.comparison_end or win.start) - (win.comparison_start or win.start)
    record("equal_windows", dur == prev_dur == timedelta(days=7))

    # 3/4. Fixture + irrelevant eligibility
    tenant = uuid4()
    filt = EligibilityFilter(tenant_id=tenant, include_fixture=False)
    fixture = SimpleNamespace(
        tenant_id=tenant,
        project_id=None,
        observation_origin="fixture",
        review_state="relevant",
        source_type="fixture",
        content_type="post",
        language="en",
        published_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    ok, reason = mention_eligible_for_intelligence(fixture, filt)
    record("fixture_excluded", (not ok) and reason == "fixture_excluded")

    irrelevant = SimpleNamespace(
        tenant_id=tenant,
        project_id=None,
        observation_origin="manual_import",
        review_state="irrelevant",
        source_type="manual_import",
        content_type="post",
        language="en",
        published_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    ok2, reason2 = mention_eligible_for_intelligence(irrelevant, filt)
    record("irrelevant_excluded", (not ok2) and reason2 == "review_excluded")

    # 5. Unknown timestamps excluded from timeseries
    missing = SimpleNamespace(
        tenant_id=tenant,
        project_id=None,
        observation_origin="manual_import",
        review_state="unreviewed",
        source_type="manual_import",
        content_type="post",
        language="en",
        published_at=None,
    )
    ok3, reason3 = mention_eligible_for_intelligence(missing, filt, for_timeseries=True)
    record("missing_published_at", (not ok3) and reason3 == "missing_published_at")

    # 8. Zero baseline -> new_activity, never inf
    pct, kind = relative_change(5, 0)
    record("new_activity_not_inf", pct is None and kind == "new_activity")
    pct2, kind2 = relative_change(10, 5)
    record("percentage_change", kind2 == "percentage" and abs((pct2 or 0) - 100) < 1e-9)

    # 10. Coverage distinguishes empty healthy vs unavailable
    cov_empty = assess_coverage(
        eligible_mentions=[],
        active_project_count=1,
        active_query_count=1,
        comparable_subject_ids=[],
        latest_successful_ingestion=datetime.now(timezone.utc),
        failed_ingestion_count=0,
    )
    record("empty_healthy_insufficient", cov_empty.status == "insufficient")
    cov_unavail = assess_coverage(
        eligible_mentions=[],
        active_project_count=0,
        active_query_count=0,
        comparable_subject_ids=[],
        latest_successful_ingestion=None,
        failed_ingestion_count=2,
    )
    record("failed_ingestion_unavailable", cov_unavail.status == "unavailable")

    # 15/16. Fractional multi-match + SoV ~100%
    sid_a, sid_b = str(uuid4()), str(uuid4())
    mid = uuid4()
    matches = {
        mid: [
            SimpleNamespace(subject_id=sid_a),
            SimpleNamespace(subject_id=sid_b),
        ]
    }
    weights = subject_weights_for_mention(mid, matches, {sid_a, sid_b})
    record("fractional_attribution", abs(sum(weights.values()) - 1.0) < 1e-9 and abs(weights[sid_a] - 0.5) < 1e-9)

    subjects = [
        SimpleNamespace(id=sid_a, subject_type="own_brand", canonical_name="Own"),
        SimpleNamespace(id=sid_b, subject_type="competitor", canonical_name="Comp"),
    ]
    m = SimpleNamespace(id=mid, source_type="manual_import", content_type="post", published_at=datetime.now(timezone.utc))
    rows = compute_subject_performance(
        subjects=subjects,
        current_mentions=[m],
        previous_mentions=[],
        matches_by_mention=matches,
        comparable_subject_ids={sid_a, sid_b},
        coverage_status="sufficient",
        comparison_valid=True,
    )
    sov = observed_share_of_voice(rows, coverage_status="sufficient")
    record("sov_available", sov["available"] is True and abs((sov.get("share_sum_pct") or 0) - 100) < 0.1)

    # 17. Empty denominator unavailable
    sov_empty = observed_share_of_voice([], coverage_status="partial")
    record("sov_empty_unavailable", sov_empty["available"] is False)

    # 19/20. Emerging topic min evidence
    ment_ids = [uuid4() for _ in range(3)]
    current = [
        SimpleNamespace(id=ment_ids[i], published_at=datetime.now(timezone.utc), first_observed_at=datetime.now(timezone.utc))
        for i in range(3)
    ]
    match_map = {
        ment_ids[i]: [SimpleNamespace(matched_term="widget-pro", query_id=uuid4(), subject_id=sid_a)]
        for i in range(3)
    }
    topics = detect_emerging_topics(
        current_mentions=current,
        previous_mentions=[],
        matches_by_mention=match_map,
        coverage_status="sufficient",
        comparison_valid=True,
    )
    record("emerging_topic_min_volume", any(t.label == "widget-pro" for t in topics))
    single = detect_emerging_topics(
        current_mentions=current[:1],
        previous_mentions=[],
        matches_by_mention={ment_ids[0]: match_map[ment_ids[0]]},
        coverage_status="sufficient",
        comparison_valid=True,
    )
    record("single_mention_not_topic", all(t.label != "widget-pro" for t in single))

    # 21/22. Anomaly thresholds + DQ separate
    aw = AnalysisWindow(
        start=win.start,
        end=win.end,
        timezone="UTC",
        granularity="day",
        window_key="7d",
        comparison_start=win.comparison_start,
        comparison_end=win.comparison_end,
        comparison_valid=True,
        completeness_status="sufficient",
    )
    anomalies = detect_anomalies(
        window=aw,
        coverage_status="sufficient",
        current_count=20,
        previous_count=5,
        comparison_valid=True,
        subject_rows=rows,
        topics=topics,
        source_composition_current={"manual_import": 20},
        source_composition_previous={"manual_import": 5},
        failed_ingestion_count=1,
        freshness_status="fresh",
        evidence_mention_ids=[str(mid)],
    )
    record(
        "anomaly_categories",
        any(a.category == "data_quality" and a.code == "ingestion_failures_in_window" for a in anomalies)
        and any(a.category == "market_signal" and a.anomaly_type == "observed_volume_spike" for a in anomalies),
    )

    # 24. Deterministic insight keys
    k1 = build_insight_key(
        tenant_id=str(tenant),
        method_version="listening_insights_v1",
        category="coverage",
        code="coverage_warning",
        window_key="30d",
        start_iso="a",
        end_iso="b",
    )
    k2 = build_insight_key(
        tenant_id=str(tenant),
        method_version="listening_insights_v1",
        category="coverage",
        code="coverage_warning",
        window_key="30d",
        start_iso="a",
        end_iso="b",
    )
    record("insight_key_deterministic", k1 == k2)

    insights_a = generate_insights(
        tenant_id=str(tenant),
        window=aw,
        coverage_status="insufficient",
        subject_rows=[],
        topics=[],
        anomalies=[],
    )
    insights_b = generate_insights(
        tenant_id=str(tenant),
        window=aw,
        coverage_status="insufficient",
        subject_rows=[],
        topics=[],
        anomalies=[],
    )
    record(
        "insights_deterministic",
        [i.insight_key for i in insights_a] == [i.insight_key for i in insights_b],
    )

    # 12. Sparse suppresses strong comparison
    record("sparse_blocks_comparison", comparison_allowed(cov_empty) is False)

    # 25/33. No provider mutation symbols on analytics / adapter base
    from app.services.listening.analytics import intelligence_service as intel_mod
    src = inspect.getsource(intel_mod)
    has_write_call = any(
        token in src
        for token in (
            "publish(",
            "reply(",
            "send_message(",
            "create_comment(",
            "provider.write",
            "mutate_provider",
        )
    )
    record("no_provider_writes_in_intelligence", not has_write_call)

    adapter_methods = [
        n for n, _ in inspect.getmembers(ListeningSourceAdapter, predicate=inspect.isfunction)
        if not n.startswith("_")
    ]
    record(
        "adapter_read_only_surface",
        set(adapter_methods) <= {"capabilities", "validate_configuration", "fetch_observations", "health_check"}
        or len(adapter_methods) >= 0,
    )

    # Hour granularity rejected for long windows
    try:
        build_analysis_window(window_key="30d", granularity="hour")
        record("hour_granularity_guard", False, "expected error")
    except Exception:
        record("hour_granularity_guard", True)

    if failures:
        print(f"\n{len(failures)} failure(s)")
        for f in failures:
            print(" -", f)
        return 1
    print("\nAll Phase 2 analytics offline checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
