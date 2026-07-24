"""Unit-style smoke tests for Advertising Intelligence Phase 1 (no HTTP, no DB).

Pure, deterministic checks over the read-only advertising domain: catalog +
semantics versions, the read-only provider contract (NO write methods anywhere),
the offline mock adapter, deterministic pacing thresholds, currency minor-unit
handling (never silently combine currencies), soft creative-fatigue wording, the
capability catalog's forbidden-write set, and that a permission/capability
surface exists.

Run from backend/:  python scripts/test_advertising_intelligence.py
"""
from __future__ import annotations

import inspect
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


# Verbs/prefixes that would indicate a provider-mutating (write) operation.
_WRITE_PREFIXES = (
    "create_", "update_", "delete_", "pause", "activate", "resume", "archive",
    "set_budget", "update_budget", "set_bid", "update_bid", "set_status",
    "set_targeting", "update_targeting", "upload_creative", "publish", "boost",
)


def _write_like_methods(obj) -> list[str]:
    found: list[str] = []
    for name in dir(obj):
        if name.startswith("__"):
            continue
        attr = getattr(obj, name, None)
        if not callable(attr):
            continue
        lower = name.lower()
        if any(lower.startswith(p) for p in _WRITE_PREFIXES):
            found.append(name)
    return found


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.models.advertising import AD_METRIC_SEMANTICS_VERSION, PACING_STATUSES
    from app.services.advertising_intelligence.metric_catalog import (
        ALL_METRIC_KEYS,
        CATALOG_VERSION,
        CURRENCY_METRIC_KEYS,
        DERIVED_METRIC_KEYS,
        METRIC_CATALOG,
        METRIC_SEMANTICS_VERSION,
        RAW_METRIC_KEYS,
    )
    from app.services.advertising_intelligence.providers import (
        MockAdvertisingAdapter,
        get_adapter,
    )
    from app.services.advertising_intelligence.providers.base import (
        AdvertisingProviderAdapter,
    )
    from app.services.advertising_intelligence.providers.mock import (
        account_currency,
        build_insights,
        build_structure,
    )
    from app.services.advertising_intelligence.schemas import (
        InsightsFetchRequest,
        Money,
    )
    from app.services.advertising_intelligence import account_service, spend_service
    from app.services.advertising_intelligence.errors import AdCurrencyMismatchError
    from app.services.advertising_intelligence.pacing_service import compute_pacing
    from app.services.advertising_intelligence.creative_diagnostics import (
        compute_creative_fatigue,
    )
    from app.services.advertising_platform.capability_catalog import (
        ALLOWED_READ_CAPABILITIES,
        FORBIDDEN_WRITE_CAPABILITIES,
        assert_read_only,
    )
    from app.services.advertising_platform.errors import WriteOperationForbiddenError

    # --- Catalog / semantics versions -------------------------------------
    record("catalog_version_set", CATALOG_VERSION == "1.0.0", CATALOG_VERSION)
    record("semantics_version_set", METRIC_SEMANTICS_VERSION == "1.0.0", METRIC_SEMANTICS_VERSION)
    record(
        "semantics_aligned_with_model",
        METRIC_SEMANTICS_VERSION == AD_METRIC_SEMANTICS_VERSION,
    )
    record("catalog_nonempty", len(ALL_METRIC_KEYS) >= 12, str(len(ALL_METRIC_KEYS)))
    record("raw_derived_partition", RAW_METRIC_KEYS.isdisjoint(DERIVED_METRIC_KEYS))
    record("all_keys_cover_raw_derived", ALL_METRIC_KEYS == (RAW_METRIC_KEYS | DERIVED_METRIC_KEYS))
    record(
        "clicks_and_link_clicks_not_conflated",
        "clicks" in METRIC_CATALOG and "link_clicks" in METRIC_CATALOG,
    )
    record(
        "impressions_reach_distinct",
        "impressions" in METRIC_CATALOG and "reach" in METRIC_CATALOG,
    )
    record(
        "spend_is_currency_minor",
        METRIC_CATALOG["spend_minor"].value_type == "currency_minor"
        and METRIC_CATALOG["spend_minor"].currency_behavior == "currency",
    )
    record(
        "currency_metrics_flagged",
        {"spend_minor", "conversion_value_minor"} <= CURRENCY_METRIC_KEYS,
    )
    record(
        "no_metric_marked_cross_provider_comparable",
        not any(d.cross_provider_comparable for d in METRIC_CATALOG.values()),
    )

    # --- Provider contract: read methods exist, NO write methods ----------
    read_methods = {"capabilities", "health_check", "fetch_structure", "fetch_insights"}
    record(
        "base_read_methods_present",
        read_methods <= set(dir(AdvertisingProviderAdapter)),
    )
    base_writes = _write_like_methods(AdvertisingProviderAdapter)
    record("base_no_write_methods", not base_writes, str(base_writes))

    mock_adapter = MockAdvertisingAdapter()
    record("mock_read_methods_present", read_methods <= set(dir(mock_adapter)))
    mock_writes = _write_like_methods(mock_adapter)
    record("mock_no_write_methods", not mock_writes, str(mock_writes))

    # No async write coroutine hiding anywhere either.
    coro_names = {
        n for n in dir(mock_adapter)
        if not n.startswith("__") and inspect.iscoroutinefunction(getattr(mock_adapter, n, None))
    }
    record(
        "mock_async_methods_are_reads_only",
        coro_names <= {"health_check", "fetch_structure", "fetch_insights"},
        str(sorted(coro_names)),
    )

    # get_adapter returns cached read-only adapters and never raises for unknowns.
    record("get_adapter_mock", get_adapter("mock").provider == "mock")
    unknown = get_adapter("tiktok_unknown_provider")
    record("get_adapter_unknown_no_write", not _write_like_methods(unknown))

    # --- Mock adapter works without network -------------------------------
    acct = "mockacct-smoke-001"
    s1 = build_structure(acct)
    s2 = build_structure(acct)
    record("mock_structure_ok", s1.status == "ok" and s1.account is not None)
    record("mock_structure_full_tree", len(s1.campaigns) >= 2 and len(s1.ads) >= 1 and len(s1.creatives) >= 1,
            f"camp={len(s1.campaigns)} ads={len(s1.ads)} creatives={len(s1.creatives)}")
    record(
        "mock_structure_deterministic",
        [c.provider_campaign_id for c in s1.campaigns] == [c.provider_campaign_id for c in s2.campaigns],
    )
    # Money on budgets is integer minor units + explicit currency.
    budgeted = [c for c in s1.campaigns if c.daily_budget is not None]
    record(
        "mock_budget_money_minor_units",
        bool(budgeted)
        and isinstance(budgeted[0].daily_budget, Money)
        and isinstance(budgeted[0].daily_budget.minor_units, int)
        and bool(budgeted[0].daily_budget.currency),
    )

    from uuid import uuid4
    ins = build_insights(
        InsightsFetchRequest(
            tenant_id=uuid4(), provider="mock", connection_status="mock",
            provider_account_id=acct, level="campaign",
            date_start="2026-06-01", date_stop="2026-06-30",
            provider_entity_ids=[c.provider_campaign_id for c in s1.campaigns],
        )
    )
    record("mock_insights_ok", ins.status == "ok" and len(ins.results) == len(s1.campaigns))
    first = ins.results[0]
    spend_metric = next((m for m in first.metrics if m.provider_metric_key == "spend_minor"), None)
    record(
        "mock_spend_is_currency_minor",
        spend_metric is not None
        and spend_metric.value_type == "currency_minor"
        and spend_metric.currency in ("USD", "CNY")
        and spend_metric.value == spend_metric.value.to_integral_value(),
    )
    record(
        "mock_no_secret_fields",
        not any(
            "token" in (m.provider_metric_key or "").lower()
            or "secret" in (m.provider_metric_key or "").lower()
            for m in first.metrics
        ),
    )

    # --- Currency: minor units + never silently combined ------------------
    same = spend_service.sum_same_currency([(1000, "USD"), (2500, "USD"), (None, "USD")])
    record("same_currency_sum", same == (3500, "USD"), str(same))
    mixed_raised = False
    try:
        spend_service.sum_same_currency([(1000, "USD"), (2500, "CNY")])
    except AdCurrencyMismatchError:
        mixed_raised = True
    record("mixed_currency_rejected", mixed_raised)
    record("money_minor_units_int", isinstance(Money(1234, "USD").minor_units, int))
    # The mock derives currency from the account id (exercises mixed-currency paths).
    currencies = {account_currency(f"acct-{i}") for i in range(20)}
    record("mock_multi_currency", currencies == {"USD", "CNY"}, str(sorted(currencies)))

    # --- Pacing: deterministic thresholds 0.8 / 1.2 -----------------------
    from app.services.advertising_intelligence import pacing_service as _pace
    record("pacing_under_threshold", _pace._UNDER == Decimal("0.8"))
    record("pacing_over_threshold", _pace._OVER == Decimal("1.2"))
    # Daily expected = daily_budget * window_days = 100 * 30 = 3000.
    under = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=1000, window_days=30)
    on_pace = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=2700, window_days=30)
    over = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=5000, window_days=30)
    # Lifetime is a hard cap: spending past it is budget_exhausted, not merely over.
    exhausted = compute_pacing(budget_minor=3000, budget_type="lifetime", spend_minor=3200, window_days=30)
    not_applicable = compute_pacing(budget_minor=None, budget_type="unlimited", spend_minor=10, window_days=30)
    insufficient = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=None, window_days=30)
    paused = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=10, effective_status="paused")
    ended = compute_pacing(budget_minor=100, budget_type="lifetime", spend_minor=10, effective_status="completed")
    record("pacing_under", under["pacing_status"] == "underspending", str(under["pacing_status"]))
    record("pacing_on_pace", on_pace["pacing_status"] == "on_pace", str(on_pace["pacing_status"]))
    record("pacing_over", over["pacing_status"] == "overspending", str(over["pacing_status"]))
    record("pacing_exhausted", exhausted["pacing_status"] == "budget_exhausted", str(exhausted["pacing_status"]))
    record("pacing_not_applicable", not_applicable["pacing_status"] == "not_applicable")
    record("pacing_insufficient", insufficient["pacing_status"] == "insufficient_data")
    record("pacing_paused", paused["pacing_status"] == "paused")
    record("pacing_ended", ended["pacing_status"] == "ended")
    record(
        "pacing_deterministic",
        compute_pacing(budget_minor=100, budget_type="daily", spend_minor=1000, window_days=30) == under,
    )
    record(
        "pacing_statuses_valid",
        {"underspending", "on_pace", "overspending", "budget_exhausted", "paused", "ended", "insufficient_data"}
        <= PACING_STATUSES,
    )

    # --- Fatigue: soft wording, never automatic action --------------------
    insufficient = compute_creative_fatigue(frequency=None)
    no_signal = compute_creative_fatigue(frequency=Decimal("1.2"))
    possible = compute_creative_fatigue(frequency=Decimal("3.0"))
    strong = compute_creative_fatigue(frequency=Decimal("5.0"))
    record("fatigue_insufficient", insufficient["status"] == "insufficient_data")
    record("fatigue_none", no_signal["status"] == "no_signal")
    record("fatigue_possible", possible["status"] == "possible_fatigue")
    record("fatigue_strong", strong["status"] == "strong_fatigue_signal")
    all_msgs = " ".join(r["message"].lower() for r in (insufficient, no_signal, possible, strong))
    record("fatigue_wording_soft", "signal" in all_msgs or "possible" in all_msgs)
    hard_words = ("replace", "immediately", "must ", "turn off", "delete", "pause the")
    record(
        "fatigue_no_action_directive",
        not any(w in all_msgs for w in hard_words),
        all_msgs,
    )

    # --- Capability catalog forbids write capabilities --------------------
    record(
        "capabilities_disjoint",
        not (ALLOWED_READ_CAPABILITIES & FORBIDDEN_WRITE_CAPABILITIES),
    )
    record(
        "forbidden_set_covers_writes",
        {"create_campaign", "update_campaign", "delete_campaign", "pause", "activate",
         "set_budget", "set_bid", "update_targeting"} <= FORBIDDEN_WRITE_CAPABILITIES,
    )
    forbidden_rejected = 0
    for cap in FORBIDDEN_WRITE_CAPABILITIES:
        try:
            assert_read_only(cap)
        except WriteOperationForbiddenError:
            forbidden_rejected += 1
    record(
        "assert_read_only_rejects_all_forbidden",
        forbidden_rejected == len(FORBIDDEN_WRITE_CAPABILITIES),
        f"{forbidden_rejected}/{len(FORBIDDEN_WRITE_CAPABILITIES)}",
    )
    allowed_ok = 0
    for cap in ALLOWED_READ_CAPABILITIES:
        try:
            assert_read_only(cap)
            allowed_ok += 1
        except WriteOperationForbiddenError:
            pass
    record("assert_read_only_allows_reads", allowed_ok == len(ALLOWED_READ_CAPABILITIES))
    unknown_rejected = False
    try:
        assert_read_only("some_unknown_capability")
    except WriteOperationForbiddenError:
        unknown_rejected = True
    record("assert_read_only_rejects_unknown", unknown_rejected)

    # --- permission_check / capabilities surface exists -------------------
    record(
        "account_service_has_permission_surface",
        hasattr(account_service, "permission_summary")
        and hasattr(account_service, "account_capabilities"),
    )
    caps = mock_adapter.capabilities(connection_status="mock")
    record(
        "adapter_reports_capabilities",
        caps.capability_status == "mock_only"
        and caps.supports_structure_import
        and caps.supports_insights,
    )

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
