"""Verify Decision Support HTTP surface remains advisory / non-mutating toward providers.

Run from backend/:  python scripts/verify_advertising_decision_support_http.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


_FORBIDDEN_PATH_TOKENS = (
    "apply-to-meta",
    "apply-budget",
    "pause",
    "activate",
    "set-budget",
    "update-budget",
    "set-bid",
    "launch-experiment",
    "launch-on",
    "provider-sync",
    "execute",
)


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.api.v1 import advertising_decision_support as ds_api
    from app.api.v1 import advertising as ad_api

    expected = {
        "/advertising/comparisons",
        "/advertising/simulations",
        "/advertising/simulations/{simulation_id}",
        "/advertising/diagnostics/concentration",
        "/advertising/diagnostics/pacing",
        "/advertising/diagnostics/creative-rotation",
        "/advertising/experiments",
        "/advertising/experiments/{experiment_id}",
        "/advertising/experiments/{experiment_id}/start-observation",
        "/advertising/experiments/{experiment_id}/complete",
        "/advertising/experiments/{experiment_id}/cancel",
        "/advertising/experiments/{experiment_id}/review",
        "/advertising/change-plans",
        "/advertising/change-plans/{plan_id}",
        "/advertising/change-plans/{plan_id}/review",
        "/advertising/change-plans/{plan_id}/dismiss",
    }

    paths = {getattr(r, "path", "") for r in ds_api.router.routes}
    missing = sorted(expected - paths)
    record("expected_routes_present", not missing, str(missing))

    bad = []
    for path in paths:
        for token in _FORBIDDEN_PATH_TOKENS:
            if token in path.lower():
                bad.append(f"{path}::{token}")
    record("no_forbidden_route_tokens", not bad, str(bad))

    # Phase 1 read-only script still applies to combined surface
    from app.services.advertising_intelligence.providers.base import AdvertisingProviderAdapter

    methods = [
        n for n, _ in inspect_callable_methods(AdvertisingProviderAdapter)
        if any(n.startswith(p) for p in ("create_", "update_", "delete_", "pause", "set_budget", "activate"))
    ]
    record("provider_adapter_still_read_only", not methods, str(methods))

    # Ensure Phase 1 router still loads
    record("phase1_router_loads", bool(ad_api.router.routes))

    # Schemas forbid tenant_id from clients on create requests
    from app.schemas.advertising import (
        CreateExperimentRequest,
        CreateSimulationRequest,
        ComparisonRequest,
    )

    for cls in (CreateSimulationRequest, CreateExperimentRequest, ComparisonRequest):
        fields = getattr(cls, "model_fields", {})
        record(f"{cls.__name__}_no_tenant_id", "tenant_id" not in fields)

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


def inspect_callable_methods(cls):
    import inspect
    for name, member in inspect.getmembers(cls, predicate=inspect.isfunction):
        yield name, member
    for name, member in inspect.getmembers(cls, predicate=inspect.ismethod):
        yield name, member


if __name__ == "__main__":
    raise SystemExit(main())
