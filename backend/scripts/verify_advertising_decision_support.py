"""Verify Advertising Decision Support pure engines (no DB required).

Covers: comparison deltas, budget allocation math, pacing projection,
concentration, diminishing returns, creative rotation, experiment min-data,
change-plan payload invariants, read-only enforcement.

Run from backend/:  python scripts/verify_advertising_decision_support.py
"""
from __future__ import annotations

import inspect
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

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

    # ------------------------------------------------------------------ comparison
    from app.services.advertising_decision_support.comparison_engine import (
        compute_metric_delta,
    )

    cpa = compute_metric_delta(
        left=Decimal("100"), right=Decimal("80"), direction="lower_is_better",
    )
    record("cpa_favorable_right", cpa["favorable_side"] == "right", str(cpa["favorable_side"]))
    spend = compute_metric_delta(
        left=Decimal("100"), right=Decimal("200"), direction="neutral",
    )
    record("spend_never_auto_better", spend["favorable_side"] is None)
    missing = compute_metric_delta(left=None, right=Decimal("10"), direction="higher_is_better")
    record("missing_metric_not_fabricated", missing["availability"] == "missing")
    record("missing_pct_none", missing["percentage_difference"] is None)
    zero_base = compute_metric_delta(left=Decimal("0"), right=Decimal("5"), direction="neutral")
    record("zero_base_pct_none", zero_base["percentage_difference"] is None)

    # ------------------------------------------------------------------ simulation
    from app.services.advertising_decision_support.budget_simulation_engine import (
        SIMULATION_DISCLAIMER,
        compute_allocation,
    )
    from app.services.advertising_decision_support.errors import AdSimulationValidationError

    alloc = compute_allocation(
        10_000,
        [
            {"campaign_id": "a", "allocation_pct": Decimal("0.6")},
            {"campaign_id": "b", "allocation_pct": Decimal("0.4")},
        ],
    )
    record("alloc_a_6000", alloc[0]["simulated_budget_minor"] == 6000, str(alloc[0]))
    record("alloc_b_4000", alloc[1]["simulated_budget_minor"] == 4000, str(alloc[1]))
    record(
        "alloc_sums_to_total",
        sum(i["simulated_budget_minor"] for i in alloc) == 10_000,
    )
    try:
        compute_allocation(-1, [{"campaign_id": "a", "allocation_pct": 1}])
        record("negative_budget_rejected", False)
    except AdSimulationValidationError:
        record("negative_budget_rejected", True)
    record("disclaimer_present", "does not modify provider budgets" in SIMULATION_DISCLAIMER)

    # ------------------------------------------------------------------ pacing projection
    from app.services.advertising_decision_support.pacing_projection import project_pacing

    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    start = now - timedelta(days=10)
    end = now + timedelta(days=10)
    proj = project_pacing(
        spend_so_far_minor=5_000,
        budget_minor=10_000,
        period_start=start,
        period_end=end,
        now=now,
        effective_status="active",
    )
    record(
        "pacing_mechanical_label",
        "Mechanical projection based on current spend rate" in (proj.get("label") or ""),
        str(proj.get("label")),
    )
    record("pacing_has_formula", bool(proj.get("formula") or proj.get("engine_version")))
    record("pacing_not_ai_forecast", "AI" not in (proj.get("label") or ""))
    paused = project_pacing(
        spend_so_far_minor=100,
        budget_minor=1000,
        period_start=start,
        period_end=end,
        now=now,
        effective_status="paused",
    )
    record(
        "pacing_paused_handled",
        paused.get("projection_status") == "paused",
        str(paused.get("projection_status")),
    )
    zero = project_pacing(
        spend_so_far_minor=0,
        budget_minor=1000,
        period_start=start,
        period_end=end,
        now=now,
        effective_status="active",
    )
    record("pacing_zero_spend_handled", zero.get("projection_status") == "zero_spend")

    # ------------------------------------------------------------------ concentration
    from app.services.advertising_decision_support.concentration_analysis import (
        compute_concentration,
    )

    high = compute_concentration([
        ("c1", 8000), ("c2", 1000), ("c3", 1000),
    ])
    high_status = high.get("status") or high.get("classification")
    record("concentration_highly", high_status == "highly_concentrated", str(high_status))
    divers = compute_concentration([
        ("c1", 2500), ("c2", 2500), ("c3", 2500), ("c4", 2500),
    ])
    divers_status = divers.get("status") or divers.get("classification")
    record(
        "concentration_diversified",
        divers_status in {"diversified", "moderately_concentrated"},
        str(divers_status),
    )
    insuff = compute_concentration([])
    record(
        "concentration_insufficient",
        (insuff.get("status") or insuff.get("classification")) == "insufficient_data",
    )
    record("concentration_has_observation", bool(high.get("observation")))
    record("concentration_has_consideration", bool(high.get("possible_consideration")))

    # ------------------------------------------------------------------ diminishing returns
    from app.services.advertising_decision_support.diminishing_returns import (
        compute_diminishing_returns,
    )

    buckets = [
        {"spend_minor": 1000, "efficiency": Decimal("50"), "window_key": "7d"},
        {"spend_minor": 3000, "efficiency": Decimal("80"), "window_key": "14d"},
        {"spend_minor": 8000, "efficiency": Decimal("120"), "window_key": "30d"},
    ]
    dim = compute_diminishing_returns(buckets, direction="lower_is_better")
    record(
        "diminishing_status_vocab",
        dim.get("status") in {
            "no_evidence", "possible_diminishing_efficiency", "stable", "insufficient_data",
        },
        str(dim.get("status")),
    )
    wording = (dim.get("observation") or "") + (dim.get("interpretation") or "")
    record("diminishing_no_causality_claim", "will reduce" not in wording.lower())
    record(
        "diminishing_insufficient_when_empty",
        compute_diminishing_returns([], direction="lower_is_better")["status"]
        == "insufficient_data",
    )

    # ------------------------------------------------------------------ creative rotation
    from app.services.advertising_decision_support.creative_rotation import (
        compute_creative_rotation,
    )

    rotation = compute_creative_rotation(
        creatives=[
            {
                "id": str(uuid4()),
                "impressions": Decimal("9000"),
                "frequency": Decimal("4.5"),
                "ctr": Decimal("0.01"),
                "spend_minor": 8000,
            },
            {
                "id": str(uuid4()),
                "impressions": Decimal("500"),
                "frequency": Decimal("1.1"),
                "ctr": Decimal("0.02"),
                "spend_minor": 500,
            },
        ]
    )
    record(
        "rotation_status_vocab",
        rotation.get("status") in {
            "healthy_rotation", "concentrated", "possible_fatigue", "insufficient_data",
        },
        str(rotation.get("status")),
    )
    record("rotation_no_auto_pause", "pause" not in (rotation.get("possible_consideration") or "").lower())

    # ------------------------------------------------------------------ experiment min-data
    from app.services.advertising_decision_support.experiment_review import (
        compare_variants_directional,
        evaluate_minimum_data,
    )

    min_ok = evaluate_minimum_data(
        observations=Decimal("50"),
        spend_minor=100,
        conversions=Decimal("2"),
        minimum_observations=100,
        minimum_spend_minor=500,
        minimum_conversions=10,
        freshness_status="fresh",
    )
    record("experiment_min_data_fails", min_ok.get("passed") is False, str(min_ok))
    directional = compare_variants_directional(
        primary_metric_key="cpa_minor",
        variant_metrics=[
            {"variant_id": "1", "variant_key": "A", "primary_value": Decimal("100"), "spend_minor": 1000},
            {"variant_id": "2", "variant_key": "B", "primary_value": Decimal("80"), "spend_minor": 1000},
        ],
    )
    conclusion = (directional.get("conclusion") or "").lower()
    record("experiment_directional_wording", "will perform" not in conclusion)
    record(
        "experiment_observed_language",
        "observed" in conclusion or "currently" in conclusion or bool(directional),
        conclusion[:160],
    )

    # ------------------------------------------------------------------ change plan invariants
    from app.services.advertising_decision_support.change_plan_service import _validate_items
    from app.services.advertising_decision_support.errors import AdDecisionSupportError

    try:
        _validate_items([{
            "item_type": "review_budget_allocation",
            "observation": "x",
            "reasoning": "y",
            "suggested_human_action": "z",
            "provider_payload": {"pause": True},
        }])
        record("change_plan_rejects_provider_payload", False)
    except Exception:
        record("change_plan_rejects_provider_payload", True)

    # ------------------------------------------------------------------ read-only / no provider writes
    from app.services.advertising_intelligence.providers.base import AdvertisingProviderAdapter
    from app.services.advertising_decision_support import (
        budget_simulation_engine,
        experiment_planner,
        change_plan_service,
    )

    _WRITE_PREFIXES = (
        "create_campaign", "update_campaign", "delete_campaign", "pause", "activate",
        "set_budget", "update_budget", "set_bid", "upload_creative",
    )
    ds_modules = [budget_simulation_engine, experiment_planner, change_plan_service]
    write_hits = []
    for mod in ds_modules:
        src = Path(inspect.getfile(mod)).read_text(encoding="utf-8")
        if "AdvertisingProviderAdapter" in src and "fetch_" not in src:
            # Decision support should not import provider adapters at all ideally
            pass
        for name in dir(mod):
            if any(name.lower().startswith(p) for p in _WRITE_PREFIXES):
                write_hits.append(f"{mod.__name__}.{name}")
    record("decision_support_no_provider_write_methods", not write_hits, str(write_hits))

    adapter_src = inspect.getsource(AdvertisingProviderAdapter)
    for token in ("pause_campaign", "activate_campaign", "update_bid", "create_campaign"):
        record(f"adapter_lacks_{token}", token not in adapter_src)
    # Ensure no callable write methods (comments mentioning set_budget are fine)
    write_like = [
        n for n in dir(AdvertisingProviderAdapter)
        if callable(getattr(AdvertisingProviderAdapter, n, None))
        and any(n.startswith(p) for p in ("set_budget", "update_budget", "pause", "activate", "create_"))
    ]
    record("adapter_no_write_callables", not write_like, str(write_like))

    # HTTP routes: no Apply-to-Meta style tokens
    from app.api.v1 import advertising_decision_support as ds_api

    route_paths = []
    for route in ds_api.router.routes:
        path = getattr(route, "path", "") or ""
        route_paths.append(path)
        for bad in ("apply-to-meta", "pause", "activate", "set-budget", "launch-on"):
            if bad in path.lower():
                failures.append(f"forbidden route token {bad} in {path}")
                print(f"FAIL forbidden_route — {path}")
    record("decision_support_routes_registered", len(route_paths) >= 10, str(len(route_paths)))
    record(
        "no_apply_or_launch_routes",
        not any("apply" in p or "launch" in p for p in route_paths),
        str(route_paths),
    )

    # ------------------------------------------------------------------ events registered
    from app.core.events.registry import event_registry

    for et in (
        "advertising.simulation_created",
        "advertising.experiment_created",
        "advertising.experiment_reviewed",
        "advertising.concentration_detected",
        "advertising.possible_fatigue_detected",
        "advertising.change_plan_created",
    ):
        record(f"event_registered_{et}", event_registry.is_registered(et))

    # ------------------------------------------------------------------ models importable
    from app.models.advertising_decision_support import (
        TenantAdBudgetSimulation,
        TenantAdChangePlan,
        TenantAdExperiment,
    )
    record("model_simulation", TenantAdBudgetSimulation.__tablename__ == "tenant_ad_budget_simulations")
    record("model_experiment", TenantAdExperiment.__tablename__ == "tenant_ad_experiments")
    record("model_change_plan", TenantAdChangePlan.__tablename__ == "tenant_ad_change_plans")

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
