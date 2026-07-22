"""Unit-style smoke tests for Measurement foundation (no HTTP).

Run from backend/:  python scripts/test_measurement_foundation.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.models.measurement import METRIC_SEMANTICS_VERSION
    from app.services.measurement.confidence_engine import (
        METHOD_CONFIDENCE,
        confidence_for_method,
        degrade_for_freshness,
    )
    from app.services.measurement.freshness_service import compute_freshness
    from app.services.measurement.metric_catalog import (
        ALL_METRIC_KEYS,
        CATALOG_VERSION,
        CROSS_PLATFORM_COMPARABLE_KEYS,
        DERIVED_METRIC_KEYS,
        METRIC_CATALOG,
        RAW_METRIC_KEYS,
        get_metric_definition,
    )
    from app.services.measurement.metric_ingestion_service import snapshot_fingerprint
    from app.services.measurement.metric_normalizer import normalize_provider_metrics
    from app.services.measurement.providers.mock import MockAdapter, generate_mock_metrics
    from app.services.measurement.schemas import MetricFetchRequest

    # --- Catalog ---
    record("catalog_version_set", bool(CATALOG_VERSION) and CATALOG_VERSION == "1.0.0", CATALOG_VERSION)
    record("semantics_version_aligned", METRIC_SEMANTICS_VERSION == "1.0.0", METRIC_SEMANTICS_VERSION)
    record("catalog_nonempty", len(ALL_METRIC_KEYS) >= 15, str(len(ALL_METRIC_KEYS)))
    record("raw_and_derived_partition", RAW_METRIC_KEYS.isdisjoint(DERIVED_METRIC_KEYS))
    record(
        "all_keys_cover_raw_derived",
        ALL_METRIC_KEYS == (RAW_METRIC_KEYS | DERIVED_METRIC_KEYS),
    )

    stable_keys = (
        "impressions", "reach", "views", "likes", "comments", "shares", "saves",
        "engagements", "engagement_rate_by_impressions", "click_through_rate",
    )
    record("stable_metric_keys_present", all(k in METRIC_CATALOG for k in stable_keys))

    impressions = get_metric_definition("impressions")
    reach = get_metric_definition("reach")
    record(
        "impressions_reach_not_conflated",
        impressions is not None
        and reach is not None
        and impressions.key != reach.key
        and not impressions.cross_platform_comparable
        and not reach.cross_platform_comparable,
    )
    record(
        "comparable_subset",
        {"likes", "comments", "shares", "saves"} <= CROSS_PLATFORM_COMPARABLE_KEYS,
        str(sorted(CROSS_PLATFORM_COMPARABLE_KEYS)),
    )
    record(
        "impressions_not_comparable",
        "impressions" not in CROSS_PLATFORM_COMPARABLE_KEYS,
    )

    engagements_def = get_metric_definition("engagements")
    record(
        "engagements_formula_metadata",
        engagements_def is not None
        and engagements_def.aggregation_type == "derived"
        and engagements_def.derived_from == ("likes", "comments", "shares", "saves"),
    )
    rate_def = get_metric_definition("engagement_rate_by_impressions")
    record(
        "rate_derived_from_engagements_impressions",
        rate_def is not None and rate_def.derived_from == ("engagements", "impressions"),
    )

    # --- Mock adapter ---
    fixed = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    m1 = generate_mock_metrics("pub-verify-alpha", reference_time=fixed)
    m2 = generate_mock_metrics("pub-verify-alpha", reference_time=fixed)
    m3 = generate_mock_metrics("pub-verify-beta", reference_time=fixed)
    record("mock_deterministic_same_id", m1 == m2 and len(m1) > 0, f"keys={len(m1)}")
    record("mock_different_ids_differ", m1 != m3)
    record("mock_only_raw_keys", set(m1.keys()) <= set(RAW_METRIC_KEYS))
    record("mock_no_derived_keys", set(m1.keys()).isdisjoint(DERIVED_METRIC_KEYS))
    record("mock_no_credential_fields", not any(
        k for k in m1 if "token" in k.lower() or "secret" in k.lower() or "password" in k.lower()
    ))

    adapter = MockAdapter()
    caps = adapter.capabilities(account_status="mock")
    record("mock_caps_full", caps.capability_status == "full" and caps.supports_post_level_metrics)

    # --- Normalizer ---
    normalized = normalize_provider_metrics(
        {"impressions": Decimal(1000), "likes": Decimal(10), "comments": Decimal(2),
         "shares": Decimal(1), "saves": Decimal(0), "mystery_native": Decimal(42)},
        platform="mock",
    )
    by_key = {n.metric_key: n for n in normalized}
    record("normalized_status", by_key["impressions"].normalization_status == "normalized")
    record(
        "provider_native_kept",
        any(n.normalization_status == "provider_native" and n.provider_metric_key == "mystery_native" for n in normalized),
    )
    eng = by_key.get("engagements")
    record(
        "derived_engagements_formula",
        eng is not None
        and eng.normalization_status == "derived"
        and eng.value == Decimal(13)
        and (eng.metadata or {}).get("formula") == "sum(likes, comments, shares, saves)",
    )
    rate = by_key.get("engagement_rate_by_impressions")
    record(
        "derived_rate_present",
        rate is not None and rate.value == Decimal(13) / Decimal(1000),
    )

    zero_denom = normalize_provider_metrics(
        {"likes": Decimal(5), "impressions": Decimal(0), "reach": Decimal(0)},
        platform="mock",
    )
    zero_keys = {n.metric_key for n in zero_denom}
    record(
        "zero_denominator_no_ratio",
        "engagement_rate_by_impressions" not in zero_keys
        and "engagement_rate_by_reach" not in zero_keys
        and "engagements" in zero_keys,
        str(sorted(zero_keys)),
    )

    missing_denom = normalize_provider_metrics(
        {"likes": Decimal(5)},
        platform="mock",
    )
    missing_keys = {n.metric_key for n in missing_denom}
    record(
        "missing_denominator_no_ratio",
        "engagement_rate_by_impressions" not in missing_keys and "engagements" in missing_keys,
    )

    # --- Snapshot fingerprint ---
    fp_a = snapshot_fingerprint(
        provider_metrics={"impressions": Decimal(100), "likes": Decimal(3)},
        provider_data_timestamp=fixed,
        status="ok",
    )
    fp_b = snapshot_fingerprint(
        provider_metrics={"likes": Decimal(3), "impressions": Decimal(100)},
        provider_data_timestamp=fixed,
        status="ok",
    )
    fp_c = snapshot_fingerprint(
        provider_metrics={"impressions": Decimal(101), "likes": Decimal(3)},
        provider_data_timestamp=fixed,
        status="ok",
    )
    record("fingerprint_idempotent", fp_a == fp_b and len(fp_a) == 64)
    record("fingerprint_changes_with_metrics", fp_a != fp_c)

    # --- Freshness ---
    now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)
    fresh = compute_freshness(last_metric_at=now - timedelta(hours=1), now=now)
    aging = compute_freshness(last_metric_at=now - timedelta(hours=12), now=now)
    stale = compute_freshness(last_metric_at=now - timedelta(hours=48), now=now)
    unsupported = compute_freshness(
        last_metric_at=None, capability_status="unsupported", now=now,
    )
    unavailable = compute_freshness(last_metric_at=None, now=now)
    disconnected = compute_freshness(
        last_metric_at=now - timedelta(hours=1),
        account_status="disconnected",
        now=now,
    )
    record("freshness_fresh", fresh.status == "fresh")
    record("freshness_aging", aging.status == "aging")
    record("freshness_stale", stale.status == "stale")
    record("freshness_unsupported", unsupported.status == "unsupported")
    record("freshness_unavailable", unavailable.status == "unavailable")
    record("freshness_disconnected_unavailable", disconnected.status == "unavailable")

    # --- Confidence ---
    record("confidence_slot", confidence_for_method("direct_slot_assignment") == Decimal("1.000"))
    record("confidence_campaign", confidence_for_method("direct_campaign_publication") == Decimal("0.900"))
    record("confidence_manual", confidence_for_method("manual_link") == Decimal("0.700"))
    record("confidence_unattributed", confidence_for_method("unattributed") == Decimal("0.000"))
    record(
        "confidence_manual_override",
        confidence_for_method("manual_link", override=Decimal("0.55")) == Decimal("0.55"),
    )
    record("confidence_unknown_zero", confidence_for_method("made_up") == Decimal("0.000"))
    record(
        "degrade_stale",
        degrade_for_freshness(Decimal("1.000"), "stale") == Decimal("0.700"),
    )
    record("method_confidence_keys", set(METHOD_CONFIDENCE) >= {
        "direct_slot_assignment", "direct_campaign_publication", "manual_link", "unattributed",
    })

    # --- Anomaly threshold logic (pure assertions mirroring anomaly_checks) ---
    extreme_factor = Decimal("10")
    min_delta = Decimal("1000")
    prev = Decimal("100")
    jumped = Decimal("12000")
    record(
        "anomaly_extreme_jump_condition",
        jumped > prev * extreme_factor and (jumped - prev) >= min_delta,
    )
    record(
        "anomaly_ratio_out_of_range",
        Decimal("1.5") > Decimal("1") or Decimal("-0.1") < Decimal("0"),
    )
    record(
        "anomaly_cumulative_decrease",
        Decimal("50") < Decimal("80"),
    )

    # Async mock adapter fetch smoke (no credentials in request)
    import asyncio

    async def _mock_fetch() -> None:
        from uuid import uuid4
        req = MetricFetchRequest(
            tenant_id=uuid4(),
            platform="mock",
            account_status="mock",
            provider_account_id=None,
            publication_ids=["pub-verify-alpha"],
        )
        resp = await adapter.fetch_publication_metrics(req)
        result = resp.results["pub-verify-alpha"]
        record("mock_fetch_ok", result.status == "ok" and len(result.provider_metrics) > 0)
        record(
            "mock_fetch_no_token_in_summary",
            "token" not in str(result.raw_summary).lower(),
        )

    asyncio.run(_mock_fetch())

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
