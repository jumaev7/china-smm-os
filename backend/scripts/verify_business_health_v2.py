"""Verify Business Health Score v2 pure engines (no DB required).

Run from backend/:  python scripts/verify_business_health_v2.py
"""
from __future__ import annotations

import inspect
import sys
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

    from app.services.business_health.aggregator import (
        aggregate_score,
        assemble_assessment,
        band_for_score,
        clamp_score,
        normalize_effective_weights,
        rank_deductions,
    )
    from app.services.business_health.engine import assess_from_observations
    from app.services.business_health.evaluators import (
        evaluate_advertising,
        evaluate_automation,
        evaluate_campaign_planning,
        evaluate_customer_success,
        evaluate_integration,
        evaluate_organic_measurement,
        evaluate_publishing,
        evaluate_revenue_billing,
        evaluate_sales,
    )
    from app.services.business_health.policy import (
        BUSINESS_HEALTH_VERSION,
        DISCLAIMER,
        DOMAIN_WEIGHTS,
    )
    from app.services.business_health.types import DomainHealthAssessment, HealthSignal

    # ------------------------------------------------------------------ clamp / bands
    record("clamp_low", clamp_score(-10) == 0)
    record("clamp_high", clamp_score(150) == 100)
    record("band_excellent", band_for_score(85) == "excellent")
    record("band_healthy", band_for_score(70) == "healthy")
    record("band_attention", band_for_score(50) == "needs_attention")
    record("band_at_risk", band_for_score(30) == "at_risk")
    record("band_critical", band_for_score(0) == "critical")
    record("band_boundary_84", band_for_score(84) == "healthy")
    record("band_boundary_69", band_for_score(69) == "needs_attention")
    record("band_boundary_49", band_for_score(49) == "at_risk")
    record("band_boundary_29", band_for_score(29) == "critical")

    # ------------------------------------------------------------------ missing domains not zero
    sales = evaluate_sales({
        "overdue_tasks": 0, "risk_count": 0, "neglected_leads": 0, "inactive_leads": 0,
        "unanswered": 0, "unassigned_tasks": 0, "hot_leads": 0, "hot_no_followup": 0, "leads_count": 0,
    })
    ads_na = evaluate_advertising({"account_count": 0})
    record("ads_unavailable_not_zero", ads_na.availability == "not_configured" and ads_na.score is None)
    cs_demo = evaluate_customer_success({"is_demo": True, "health_score": 99})
    record("cs_demo_ignored", cs_demo.availability == "not_configured")

    domains = [
        sales,
        evaluate_publishing({"not_configured": True}),
        evaluate_campaign_planning({"not_configured": True}),
        evaluate_organic_measurement({"publication_count": 0}),
        ads_na,
        evaluate_integration({"account_count": 0}),
        evaluate_automation({"flow_count": 0}),
        cs_demo,
        evaluate_revenue_billing({"not_configured": True}),
    ]
    normalized = normalize_effective_weights(domains)
    avail = [d for d in normalized if d.effective_weight > 0]
    record("only_available_weighted", len(avail) == 1 and avail[0].domain == "sales", str([(d.domain, d.effective_weight) for d in normalized]))
    record("effective_weight_sums_1", abs(sum(d.effective_weight for d in normalized) - 1.0) < 1e-9)

    # ------------------------------------------------------------------ deterministic aggregate
    a1 = aggregate_score(domains)
    a2 = aggregate_score(domains)
    record("aggregate_deterministic", a1 == a2 == sales.score, f"{a1}/{a2}/{sales.score}")

    # ------------------------------------------------------------------ deductions ordered
    messy = evaluate_sales({
        "overdue_tasks": 8, "risk_count": 2, "neglected_leads": 1, "inactive_leads": 0,
        "unanswered": 3, "unassigned_tasks": 1, "hot_leads": 2, "hot_no_followup": 2, "leads_count": 10,
    })
    ranked = rank_deductions(messy.deductions)
    impacts = [s.score_impact for s in ranked]
    record("deductions_ordered", impacts == sorted(impacts), str(impacts))
    record("stable_signal_codes", all("." in s.code for s in messy.deductions))
    record("sales_clamped", 0 <= (messy.score or 0) <= 100)

    # ------------------------------------------------------------------ positive signals
    healthy_sales = evaluate_sales({
        "overdue_tasks": 0, "risk_count": 0, "neglected_leads": 0, "inactive_leads": 0,
        "unanswered": 0, "unassigned_tasks": 0, "hot_leads": 3, "hot_no_followup": 0, "leads_count": 5,
    })
    record("positive_signals_present", len(healthy_sales.positive_signals) > 0)

    # ------------------------------------------------------------------ stale measurement
    stale = evaluate_organic_measurement({
        "publication_count": 10, "fresh_count": 1, "aging_count": 0, "stale_count": 6, "open_anomaly_count": 0,
    })
    record("stale_signal", any(s.code == "measurement.metrics_stale" for s in stale.deductions))
    record("stale_freshness", stale.freshness == "stale")

    # ------------------------------------------------------------------ advertising read-only metrics
    ad = evaluate_advertising({
        "account_count": 2,
        "campaign_count": 4,
        "stale_campaigns": 2,
        "pacing_warning_count": 1,
        "open_anomaly_count": 0,
        "fatigue_warning_count": 0,
        "disconnected_accounts": 0,
        "attribution_coverage_ratio": 0.25,
    })
    record("ad_available", ad.availability == "available")
    record("ad_stale_code", any(s.code == "advertising.stale_metrics" for s in ad.deductions))
    record("ad_weak_attr", any(s.code == "advertising.weak_attribution" for s in ad.deductions))
    record("ad_read_only_metric", ad.observed_metrics.get("read_only") is True)

    # ------------------------------------------------------------------ failed evaluator degrades coverage
    obs = {
        "sales": {
            "overdue_tasks": 0, "risk_count": 0, "neglected_leads": 0, "inactive_leads": 0,
            "unanswered": 0, "unassigned_tasks": 0, "hot_leads": 0, "hot_no_followup": 0, "leads_count": 0,
        },
        "publishing": {"error": True},
        "campaign_planning": {"not_configured": True},
        "organic_measurement": {"publication_count": 0},
        "advertising": {"account_count": 0},
        "integration": {"account_count": 0},
        "automation": {"flow_count": 0},
        "customer_success": {"not_configured": True},
        "revenue_billing": {"not_configured": True},
    }
    assessment = assess_from_observations(obs)
    record("version", assessment.methodology_version == BUSINESS_HEALTH_VERSION)
    record("failed_domain_unavailable", any(
        d.domain == "publishing" and d.availability == "error" for d in assessment.domains
    ))
    record("assessment_not_crash", 0 <= assessment.score <= 100)
    record("unsupported_explicit", assessment.domains_unavailable >= 1)
    record("history_absent", assessment.history_available is False and assessment.change is None)
    record("disclaimer", "does not forecast" in DISCLAIMER.lower() or "decision-support" in DISCLAIMER.lower())

    # ------------------------------------------------------------------ fully healthy fixture
    healthy_obs = {
        "sales": {
            "overdue_tasks": 0, "risk_count": 0, "neglected_leads": 0, "inactive_leads": 0,
            "unanswered": 0, "unassigned_tasks": 0, "hot_leads": 2, "hot_no_followup": 0, "leads_count": 8,
        },
        "publishing": {
            "attempts_total": 20, "attempts_success": 19, "failed_posts": 0, "success_rate": 95.0,
            "scheduled_posts": 3, "published_posts": 40,
        },
        "campaign_planning": {
            "campaign_count": 2, "active_campaign_count": 2, "total_slots": 10,
            "unassigned_slots": 0, "blocked_slots": 0, "has_slots": True,
        },
        "organic_measurement": {
            "publication_count": 12, "fresh_count": 12, "aging_count": 0, "stale_count": 0, "open_anomaly_count": 0,
        },
        "advertising": {
            "account_count": 1, "campaign_count": 2, "stale_campaigns": 0, "pacing_warning_count": 0,
            "open_anomaly_count": 0, "fatigue_warning_count": 0, "disconnected_accounts": 0,
            "attribution_coverage_ratio": 1.0,
        },
        "integration": {"account_count": 3, "connected": 3, "disconnected": 0, "expired": 0},
        "automation": {"flow_count": 4, "enabled_count": 3, "failed_flow_count": 0, "execution_failures_24h": 0},
        "customer_success": {"health_score": 88, "churn_risk": "low", "adoption_score": 80},
        "revenue_billing": {"subscription_status": "active", "near_limit_count": 0, "has_usage": True},
    }
    healthy = assess_from_observations(healthy_obs)
    record("fully_healthy_high", healthy.score >= 85, str(healthy.score))
    record("fully_healthy_all_domains", healthy.domains_evaluated == len(DOMAIN_WEIGHTS), str(healthy.domains_evaluated))
    record("positives_in_assessment", len(healthy.positive_signals) > 0)
    record("weights_reconcile", abs(sum(d.effective_weight for d in healthy.domains) - 1.0) < 1e-9)

    # ------------------------------------------------------------------ multiple critical issues
    critical_obs = dict(healthy_obs)
    critical_obs["sales"] = {
        "overdue_tasks": 20, "risk_count": 15, "neglected_leads": 20, "inactive_leads": 20,
        "unanswered": 20, "unassigned_tasks": 20, "hot_leads": 10, "hot_no_followup": 10, "leads_count": 50,
    }
    critical_obs["publishing"] = {
        "attempts_total": 20, "attempts_success": 2, "failed_posts": 18, "success_rate": 10.0,
        "scheduled_posts": 0, "published_posts": 2,
    }
    critical_obs["campaign_planning"] = {
        "campaign_count": 2, "active_campaign_count": 2, "total_slots": 20,
        "unassigned_slots": 18, "blocked_slots": 5, "has_slots": True,
    }
    critical_obs["organic_measurement"] = {
        "publication_count": 20, "fresh_count": 0, "aging_count": 0, "stale_count": 20, "open_anomaly_count": 10,
    }
    critical_obs["advertising"] = {
        "account_count": 3, "campaign_count": 5, "stale_campaigns": 10, "pacing_warning_count": 8,
        "open_anomaly_count": 8, "fatigue_warning_count": 10, "disconnected_accounts": 3,
        "attribution_coverage_ratio": 0.0,
    }
    critical_obs["integration"] = {"account_count": 5, "connected": 0, "disconnected": 4, "expired": 3}
    critical_obs["automation"] = {
        "flow_count": 5, "enabled_count": 5, "failed_flow_count": 5, "execution_failures_24h": 20,
    }
    critical_obs["customer_success"] = {"health_score": 12, "churn_risk": "high", "adoption_score": 10}
    critical_obs["revenue_billing"] = {
        "subscription_status": "suspended", "near_limit_count": 4, "has_usage": True,
    }
    critical = assess_from_observations(critical_obs)
    record("critical_low", critical.score < 50, str(critical.score))
    record("critical_below_healthy", critical.score < healthy.score - 20, f"{critical.score}<{healthy.score}")
    record("top_deductions_impact_order", all(
        critical.deductions[i].score_impact <= critical.deductions[i + 1].score_impact
        for i in range(len(critical.deductions) - 1)
    ) if len(critical.deductions) > 1 else True)

    # ------------------------------------------------------------------ empty org
    empty = assess_from_observations({k: {"not_configured": True} if k != "sales" else {
        "overdue_tasks": 0, "risk_count": 0, "neglected_leads": 0, "inactive_leads": 0,
        "unanswered": 0, "unassigned_tasks": 0, "hot_leads": 0, "hot_no_followup": 0, "leads_count": 0,
    } for k in DOMAIN_WEIGHTS})
    record("empty_org_not_zero_crash", 0 <= empty.score <= 100)

    # ------------------------------------------------------------------ no provider mutation symbols in engine modules
    import app.services.business_health.observations as obs_mod
    import app.services.business_health.engine as engine_mod
    forbidden = (
        "import_service", "create_change_plan", "ensure_demo_accounts",
        "get_connection_summary", "ensure_system_flows", "ensure_default_plans",
    )
    src = inspect.getsource(obs_mod) + inspect.getsource(engine_mod)
    record("no_provider_mutation_imports", not any(f in src for f in forbidden), "found:" + ",".join(f for f in forbidden if f in src))

    # ------------------------------------------------------------------ domain weight policy present
    record("all_domains_in_policy", set(DOMAIN_WEIGHTS) == {
        "sales", "publishing", "campaign_planning", "organic_measurement",
        "advertising", "integration", "automation", "customer_success", "revenue_billing",
    })

    # ------------------------------------------------------------------ assemble keeps codes
    assembled = assemble_assessment([sales, ad, stale])
    record("assembled_score_clamped", 0 <= assembled.score <= 100)
    record("assembled_has_summary", bool(assembled.executive_summary))

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        for f in failures:
            print(" -", f)
        return 1
    print(f"\nAll checks passed ({BUSINESS_HEALTH_VERSION}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
