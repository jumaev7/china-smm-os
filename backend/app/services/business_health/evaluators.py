"""Domain evaluators — map observed metrics to DomainHealthAssessment.

All evaluators are pure (no I/O). Observation gathering lives in observations.py.
"""
from __future__ import annotations

from typing import Any

from app.services.business_health.aggregator import clamp_score
from app.services.business_health.policy import (
    AD_ANOMALY_CAP,
    AD_ANOMALY_PENALTY,
    AD_DISCONNECTED_CAP,
    AD_DISCONNECTED_PENALTY,
    AD_FATIGUE_CAP,
    AD_FATIGUE_PENALTY,
    AD_NO_ACCOUNTS_UNAVAILABLE,
    AD_PACING_WARNING_CAP,
    AD_PACING_WARNING_PENALTY,
    AD_STALE_CAMPAIGN_CAP,
    AD_STALE_CAMPAIGN_PENALTY,
    AD_WEAK_ATTRIBUTION_PENALTY,
    AD_WEAK_ATTRIBUTION_RATIO,
    AUTOMATION_EXEC_FAILURE_CAP,
    AUTOMATION_EXEC_FAILURE_PENALTY,
    AUTOMATION_FAILED_FLOW_CAP,
    AUTOMATION_FAILED_FLOW_PENALTY,
    AUTOMATION_NO_FLOWS_UNAVAILABLE,
    BILLING_NEAR_LIMIT_PENALTY,
    BILLING_NEAR_LIMIT_RATIO,
    BILLING_NO_SUBSCRIPTION_UNAVAILABLE,
    BILLING_SUSPENDED_PENALTY,
    CAMPAIGN_BLOCKED_CAP,
    CAMPAIGN_BLOCKED_PENALTY,
    CAMPAIGN_NO_ACTIVE_NEUTRAL,
    CAMPAIGN_UNASSIGNED_PENALTY_SCALE,
    CAMPAIGN_UNASSIGNED_RATIO_HIGH,
    CS_USE_OBSERVED_SCORE,
    DOMAIN_LABELS,
    DOMAIN_WEIGHTS,
    INTEGRATION_DISCONNECTED_CAP,
    INTEGRATION_DISCONNECTED_PENALTY,
    INTEGRATION_EXPIRED_CAP,
    INTEGRATION_EXPIRED_PENALTY,
    INTEGRATION_NO_ACCOUNTS_UNAVAILABLE,
    MEASUREMENT_ANOMALY_CAP,
    MEASUREMENT_ANOMALY_PENALTY,
    MEASUREMENT_EMPTY_NEUTRAL,
    MEASUREMENT_STALE_CAP,
    MEASUREMENT_STALE_PENALTY,
    PUBLISHING_FAILED_CAP,
    PUBLISHING_FAILED_PENALTY,
    PUBLISHING_LOW_SUCCESS_PENALTY,
    PUBLISHING_NO_ATTEMPTS_NEUTRAL,
    PUBLISHING_SUCCESS_ATTENTION_PCT,
    PUBLISHING_SUCCESS_HEALTHY_PCT,
    SALES_HEALTHY_HOT_BONUS,
    SALES_HOT_NO_FOLLOWUP_CAP,
    SALES_HOT_NO_FOLLOWUP_PENALTY,
    SALES_INACTIVE_CAP,
    SALES_INACTIVE_PENALTY,
    SALES_NEGLECTED_CAP,
    SALES_NEGLECTED_PENALTY,
    SALES_OVERDUE_TASK_CAP,
    SALES_OVERDUE_TASK_PENALTY,
    SALES_RISK_CAP,
    SALES_RISK_PENALTY,
    SALES_UNANSWERED_CAP,
    SALES_UNANSWERED_PENALTY,
    SALES_UNASSIGNED_CAP,
    SALES_UNASSIGNED_PENALTY,
)
from app.services.business_health.types import DomainHealthAssessment, HealthSignal


def _base(domain: str) -> DomainHealthAssessment:
    return DomainHealthAssessment(
        domain=domain,
        label=DOMAIN_LABELS[domain],
        weight=DOMAIN_WEIGHTS[domain],
    )


def _unavailable(domain: str, reason: str) -> DomainHealthAssessment:
    d = _base(domain)
    d.availability = "unavailable" if reason != "not_configured" else "not_configured"
    if reason == "error":
        d.availability = "error"
    d.unavailable_reason = reason
    d.confidence = 0.0
    d.summary = reason.replace("_", " ")
    return d


def _deduct(
    domain: str,
    code: str,
    *,
    title: str,
    explanation: str,
    impact: int,
    severity: str = "medium",
    observed_value: Any = None,
    threshold: Any = None,
) -> HealthSignal:
    return HealthSignal(
        code=code,
        domain=domain,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        explanation=explanation,
        score_impact=-abs(impact),
        observed_value=observed_value,
        threshold=threshold,
    )


def _positive(
    domain: str,
    code: str,
    *,
    title: str,
    explanation: str,
    impact: int = 0,
    observed_value: Any = None,
) -> HealthSignal:
    return HealthSignal(
        code=code,
        domain=domain,
        severity="positive",
        title=title,
        explanation=explanation,
        score_impact=max(0, impact),
        observed_value=observed_value,
    )


# --------------------------------------------------------------------------- sales
def evaluate_sales(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("sales", "observation_missing")
    if obs.get("error"):
        return _unavailable("sales", "error")

    d = _base("sales")
    d.availability = "available"
    d.freshness = "fresh"
    d.confidence = 0.9

    overdue = int(obs.get("overdue_tasks") or 0)
    risks = int(obs.get("risk_count") or 0)
    neglected = int(obs.get("neglected_leads") or 0)
    inactive = int(obs.get("inactive_leads") or 0)
    unanswered = int(obs.get("unanswered") or 0)
    unassigned = int(obs.get("unassigned_tasks") or 0)
    hot = int(obs.get("hot_leads") or 0)
    hot_no_followup = int(obs.get("hot_no_followup") or 0)
    leads = int(obs.get("leads_count") or 0)

    d.observed_metrics = {
        "overdue_tasks": overdue,
        "risk_count": risks,
        "neglected_leads": neglected,
        "inactive_leads": inactive,
        "unanswered": unanswered,
        "unassigned_tasks": unassigned,
        "hot_leads": hot,
        "hot_no_followup": hot_no_followup,
        "leads_count": leads,
    }

    score = 100.0
    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if overdue:
        impact = min(SALES_OVERDUE_TASK_CAP, overdue * SALES_OVERDUE_TASK_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "sales", "sales.overdue_tasks",
            title=f"{overdue} overdue operator task(s)",
            explanation="Open tasks past due date reduce sales operations health.",
            impact=impact,
            severity="high" if overdue >= 5 else "medium",
            observed_value=overdue,
            threshold=0,
        ))
    if risks:
        impact = min(SALES_RISK_CAP, risks * SALES_RISK_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "sales", "sales.open_risks",
            title=f"{risks} open sales risk(s)",
            explanation="Active CRM/pipeline risks reduce sales health.",
            impact=impact,
            severity="high" if risks >= 5 else "medium",
            observed_value=risks,
        ))
    if neglected:
        impact = min(SALES_NEGLECTED_CAP, neglected * SALES_NEGLECTED_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "sales", "sales.neglected_leads",
            title=f"{neglected} neglected lead(s)",
            explanation="Leads without recent activity need manual follow-up.",
            impact=impact,
            observed_value=neglected,
        ))
    if inactive:
        impact = min(SALES_INACTIVE_CAP, inactive * SALES_INACTIVE_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "sales", "sales.inactive_leads",
            title=f"{inactive} inactive lead(s)",
            explanation="Inactive leads indicate pipeline stagnation.",
            impact=impact,
            observed_value=inactive,
        ))
    if unanswered:
        impact = min(SALES_UNANSWERED_CAP, unanswered * SALES_UNANSWERED_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "sales", "sales.unanswered_inbox",
            title=f"{unanswered} unanswered conversation(s)",
            explanation="Unanswered inbox threads delay buyer response.",
            impact=impact,
            severity="high" if unanswered >= 3 else "medium",
            observed_value=unanswered,
        ))
    if unassigned:
        impact = min(SALES_UNASSIGNED_CAP, unassigned * SALES_UNASSIGNED_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "sales", "sales.unassigned_tasks",
            title=f"{unassigned} unassigned task(s)",
            explanation="Tasks without owners create execution risk.",
            impact=impact,
            observed_value=unassigned,
        ))
    if hot_no_followup:
        impact = min(SALES_HOT_NO_FOLLOWUP_CAP, hot_no_followup * SALES_HOT_NO_FOLLOWUP_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "sales", "sales.hot_lead_no_followup",
            title=f"{hot_no_followup} hot lead(s) without follow-up",
            explanation="High-priority leads without scheduled follow-up.",
            impact=impact,
            severity="critical" if hot_no_followup >= 3 else "high",
            observed_value=hot_no_followup,
        ))

    if hot > 0 and hot_no_followup == 0 and overdue == 0:
        positives.append(_positive(
            "sales", "sales.hot_leads_managed",
            title="Hot leads are being managed",
            explanation="Hot leads present without overdue hot follow-up gaps.",
            impact=SALES_HEALTHY_HOT_BONUS,
            observed_value=hot,
        ))
    if leads == 0 and overdue == 0 and risks == 0:
        positives.append(_positive(
            "sales", "sales.quiet_pipeline",
            title="No active sales backlog",
            explanation="No overdue tasks or open risks in an empty/quiet pipeline.",
            impact=2,
        ))
    elif not deductions:
        positives.append(_positive(
            "sales", "sales.operations_healthy",
            title="Sales operations look healthy",
            explanation="No material overdue, inbox, or ownership deductions.",
            impact=5,
        ))

    d.score = clamp_score(score)
    d.deductions = deductions
    d.positive_signals = positives
    d.summary = (
        f"Sales score {d.score}/100 from pipeline and operator workload observations."
    )
    return d


# --------------------------------------------------------------------------- publishing
def evaluate_publishing(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("publishing", "observation_missing")
    if obs.get("error"):
        return _unavailable("publishing", "error")
    if obs.get("not_configured"):
        return _unavailable("publishing", "not_configured")

    attempts_total = int(obs.get("attempts_total") or 0)
    attempts_success = int(obs.get("attempts_success") or 0)
    failed_posts = int(obs.get("failed_posts") or 0)
    success_rate = float(obs.get("success_rate") or 0.0)
    scheduled = int(obs.get("scheduled_posts") or 0)
    published = int(obs.get("published_posts") or 0)

    d = _base("publishing")
    d.availability = "available"
    d.freshness = str(obs.get("freshness") or "fresh")  # type: ignore[assignment]
    d.confidence = 0.85 if attempts_total or published or scheduled else 0.55
    d.observed_metrics = {
        "attempts_total": attempts_total,
        "attempts_success": attempts_success,
        "failed_posts": failed_posts,
        "success_rate": success_rate,
        "scheduled_posts": scheduled,
        "published_posts": published,
    }

    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if attempts_total == 0 and published == 0 and failed_posts == 0:
        d.score = PUBLISHING_NO_ATTEMPTS_NEUTRAL
        positives.append(_positive(
            "publishing", "publishing.idle_configured",
            title="Publishing pipeline idle",
            explanation="No recent publish attempts; score held neutral (not penalized as failure).",
            impact=0,
        ))
    else:
        score = 100.0
        if failed_posts:
            impact = min(PUBLISHING_FAILED_CAP, failed_posts * PUBLISHING_FAILED_PENALTY)
            score -= impact
            deductions.append(_deduct(
                "publishing", "publishing.failed_posts",
                title=f"{failed_posts} failed / partial publish(es)",
                explanation="Failed content publications reduce publishing health.",
                impact=impact,
                severity="high" if failed_posts >= 3 else "medium",
                observed_value=failed_posts,
            ))
        if attempts_total > 0 and success_rate < PUBLISHING_SUCCESS_ATTENTION_PCT:
            score -= PUBLISHING_LOW_SUCCESS_PENALTY
            deductions.append(_deduct(
                "publishing", "publishing.low_success_rate",
                title=f"Publish success rate {success_rate:.0f}%",
                explanation="Success rate below attention threshold.",
                impact=PUBLISHING_LOW_SUCCESS_PENALTY,
                severity="high",
                observed_value=success_rate,
                threshold=PUBLISHING_SUCCESS_ATTENTION_PCT,
            ))
        elif attempts_total > 0 and success_rate >= PUBLISHING_SUCCESS_HEALTHY_PCT:
            positives.append(_positive(
                "publishing", "publishing.success_rate_healthy",
                title="Publishing success rate is healthy",
                explanation=f"Observed success rate {success_rate:.0f}% ≥ {PUBLISHING_SUCCESS_HEALTHY_PCT:.0f}%.",
                impact=5,
                observed_value=success_rate,
            ))
        d.score = clamp_score(score)

    d.deductions = deductions
    d.positive_signals = positives
    d.summary = f"Publishing score {d.score}/100 from publish attempts and content status."
    return d


# --------------------------------------------------------------------------- campaign planning
def evaluate_campaign_planning(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("campaign_planning", "observation_missing")
    if obs.get("error"):
        return _unavailable("campaign_planning", "error")
    if obs.get("not_configured") or (int(obs.get("campaign_count") or 0) == 0 and not obs.get("has_slots")):
        return _unavailable("campaign_planning", "not_configured")

    total_slots = int(obs.get("total_slots") or 0)
    unassigned = int(obs.get("unassigned_slots") or 0)
    blocked = int(obs.get("blocked_slots") or 0)
    campaign_count = int(obs.get("campaign_count") or 0)
    active_count = int(obs.get("active_campaign_count") or 0)
    ratio = (unassigned / total_slots) if total_slots else 0.0

    d = _base("campaign_planning")
    d.availability = "available"
    d.freshness = "fresh"
    d.confidence = 0.8 if total_slots else 0.5
    d.observed_metrics = {
        "campaign_count": campaign_count,
        "active_campaign_count": active_count,
        "total_slots": total_slots,
        "unassigned_slots": unassigned,
        "blocked_slots": blocked,
        "unassigned_ratio": round(ratio, 4),
    }

    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if total_slots == 0:
        d.score = CAMPAIGN_NO_ACTIVE_NEUTRAL
        positives.append(_positive(
            "campaign_planning", "campaign.no_slots_yet",
            title="Campaigns without calendar slots",
            explanation="Campaigns exist but no slots to evaluate; held neutral.",
            impact=0,
        ))
    else:
        score = 100.0
        if ratio > 0:
            impact = clamp_score(ratio * CAMPAIGN_UNASSIGNED_PENALTY_SCALE)
            score -= impact
            deductions.append(_deduct(
                "campaign_planning", "campaign.unassigned_slots",
                title=f"{int(round(ratio * 100))}% of campaign slots are unassigned",
                explanation=f"{unassigned} of {total_slots} slots lack assigned content.",
                impact=impact,
                severity="high" if ratio >= CAMPAIGN_UNASSIGNED_RATIO_HIGH else "medium",
                observed_value=round(ratio, 4),
                threshold=CAMPAIGN_UNASSIGNED_RATIO_HIGH,
            ))
        if blocked:
            impact = min(CAMPAIGN_BLOCKED_CAP, blocked * CAMPAIGN_BLOCKED_PENALTY)
            score -= impact
            deductions.append(_deduct(
                "campaign_planning", "campaign.blocked_slots",
                title=f"{blocked} blocked campaign slot(s)",
                explanation="Blocked slots indicate planning decisions that need attention.",
                impact=impact,
                observed_value=blocked,
            ))
        if ratio == 0 and blocked == 0:
            positives.append(_positive(
                "campaign_planning", "campaign.slots_covered",
                title="Campaign calendar slots are assigned",
                explanation="No unassigned or blocked slots observed.",
                impact=5,
            ))
        d.score = clamp_score(score)

    d.deductions = deductions
    d.positive_signals = positives
    d.summary = f"Campaign planning score {d.score}/100 from slot coverage observations."
    return d


# --------------------------------------------------------------------------- organic measurement
def evaluate_organic_measurement(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("organic_measurement", "observation_missing")
    if obs.get("error"):
        return _unavailable("organic_measurement", "error")
    publication_count = int(obs.get("publication_count") or 0)
    if publication_count == 0 and not obs.get("force_available"):
        return _unavailable("organic_measurement", "not_configured")

    stale = int(obs.get("stale_count") or 0)
    aging = int(obs.get("aging_count") or 0)
    fresh = int(obs.get("fresh_count") or 0)
    anomalies = int(obs.get("open_anomaly_count") or 0)

    d = _base("organic_measurement")
    d.availability = "available"
    if stale > fresh:
        d.freshness = "stale"
    elif aging:
        d.freshness = "aging"
    elif fresh:
        d.freshness = "fresh"
    else:
        d.freshness = "unavailable"
    d.confidence = 0.75 if publication_count else 0.4
    d.observed_metrics = {
        "publication_count": publication_count,
        "fresh_count": fresh,
        "aging_count": aging,
        "stale_count": stale,
        "open_anomaly_count": anomalies,
    }

    if publication_count == 0:
        d.score = MEASUREMENT_EMPTY_NEUTRAL
        d.positive_signals = []
        d.deductions = []
        d.summary = "No publications tracked; measurement held neutral."
        return d

    score = 100.0
    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if stale:
        impact = min(MEASUREMENT_STALE_CAP, stale * MEASUREMENT_STALE_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "organic_measurement", "measurement.metrics_stale",
            title=f"{stale} publication(s) with stale metrics",
            explanation="Stale organic metric snapshots reduce measurement health.",
            impact=impact,
            severity="high" if stale >= 5 else "medium",
            observed_value=stale,
        ))
    if anomalies:
        impact = min(MEASUREMENT_ANOMALY_CAP, anomalies * MEASUREMENT_ANOMALY_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "organic_measurement", "measurement.anomaly_open",
            title=f"{anomalies} open measurement anomal(y/ies)",
            explanation="Unresolved measurement anomalies need human review.",
            impact=impact,
            observed_value=anomalies,
        ))
    if fresh and stale == 0 and anomalies == 0:
        positives.append(_positive(
            "organic_measurement", "measurement.fresh_coverage",
            title="Organic metrics look fresh",
            explanation=f"{fresh} publication(s) reporting fresh observations.",
            impact=5,
            observed_value=fresh,
        ))

    d.score = clamp_score(score)
    d.deductions = deductions
    d.positive_signals = positives
    d.summary = f"Organic measurement score {d.score}/100 from freshness and anomalies."
    return d


# --------------------------------------------------------------------------- advertising
def evaluate_advertising(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("advertising", "observation_missing")
    if obs.get("error"):
        return _unavailable("advertising", "error")
    account_count = int(obs.get("account_count") or 0)
    if AD_NO_ACCOUNTS_UNAVAILABLE and account_count == 0:
        return _unavailable("advertising", "not_configured")

    stale = int(obs.get("stale_campaigns") or 0)
    pacing = int(obs.get("pacing_warning_count") or 0)
    anomalies = int(obs.get("open_anomaly_count") or 0)
    fatigue = int(obs.get("fatigue_warning_count") or 0)
    disconnected = int(obs.get("disconnected_accounts") or 0)
    coverage_ratio = obs.get("attribution_coverage_ratio")
    campaign_count = int(obs.get("campaign_count") or 0)

    d = _base("advertising")
    d.availability = "available"
    d.freshness = "stale" if stale else ("aging" if pacing else "fresh")
    d.confidence = 0.85
    d.observed_metrics = {
        "account_count": account_count,
        "campaign_count": campaign_count,
        "stale_campaigns": stale,
        "pacing_warning_count": pacing,
        "open_anomaly_count": anomalies,
        "fatigue_warning_count": fatigue,
        "disconnected_accounts": disconnected,
        "attribution_coverage_ratio": coverage_ratio,
        "read_only": True,
    }

    score = 100.0
    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if disconnected:
        impact = min(AD_DISCONNECTED_CAP, disconnected * AD_DISCONNECTED_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "advertising", "advertising.disconnected_accounts",
            title=f"{disconnected} advertising account(s) disconnected",
            explanation="Disconnected ad data sources weaken paid-media visibility.",
            impact=impact,
            severity="high",
            observed_value=disconnected,
        ))
    if stale:
        impact = min(AD_STALE_CAMPAIGN_CAP, stale * AD_STALE_CAMPAIGN_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "advertising", "advertising.stale_metrics",
            title=f"{stale} advertising campaign(s) have stale metrics",
            explanation="Stale paid-media metrics reduce advertising health.",
            impact=impact,
            severity="high" if stale >= 3 else "medium",
            observed_value=stale,
        ))
    if pacing:
        impact = min(AD_PACING_WARNING_CAP, pacing * AD_PACING_WARNING_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "advertising", "advertising.pacing_warnings",
            title=f"{pacing} pacing warning(s)",
            explanation="Observed underspend/overspend/budget exhaustion warnings.",
            impact=impact,
            observed_value=pacing,
        ))
    if anomalies:
        impact = min(AD_ANOMALY_CAP, anomalies * AD_ANOMALY_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "advertising", "advertising.delivery_anomalies",
            title=f"{anomalies} open delivery anomal(y/ies)",
            explanation="Unresolved advertising delivery anomalies.",
            impact=impact,
            observed_value=anomalies,
        ))
    if fatigue:
        impact = min(AD_FATIGUE_CAP, fatigue * AD_FATIGUE_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "advertising", "advertising.creative_fatigue",
            title=f"{fatigue} creative fatigue warning(s)",
            explanation="Elevated creative frequency observations (advisory).",
            impact=impact,
            severity="low",
            observed_value=fatigue,
        ))
    if (
        coverage_ratio is not None
        and campaign_count > 0
        and float(coverage_ratio) < AD_WEAK_ATTRIBUTION_RATIO
    ):
        score -= AD_WEAK_ATTRIBUTION_PENALTY
        deductions.append(_deduct(
            "advertising", "advertising.weak_attribution",
            title="Weak advertising attribution coverage",
            explanation="Share of campaigns linked for attribution is below threshold.",
            impact=AD_WEAK_ATTRIBUTION_PENALTY,
            observed_value=round(float(coverage_ratio), 4),
            threshold=AD_WEAK_ATTRIBUTION_RATIO,
        ))

    if not deductions:
        positives.append(_positive(
            "advertising", "advertising.diagnostics_clear",
            title="Advertising diagnostics look clear",
            explanation="No stale metrics, pacing, anomaly, or disconnect deductions.",
            impact=5,
        ))

    d.score = clamp_score(score)
    d.deductions = deductions
    d.positive_signals = positives
    d.summary = (
        f"Advertising score {d.score}/100 from Advertising Intelligence read models "
        "(no provider mutations)."
    )
    return d


# --------------------------------------------------------------------------- integration
def evaluate_integration(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("integration", "observation_missing")
    if obs.get("error"):
        return _unavailable("integration", "error")
    total = int(obs.get("account_count") or 0)
    if INTEGRATION_NO_ACCOUNTS_UNAVAILABLE and total == 0:
        return _unavailable("integration", "not_configured")

    disconnected = int(obs.get("disconnected") or 0)
    expired = int(obs.get("expired") or 0)
    connected = int(obs.get("connected") or 0)

    d = _base("integration")
    d.availability = "available"
    d.freshness = "fresh"
    d.confidence = 0.9
    d.observed_metrics = {
        "account_count": total,
        "connected": connected,
        "disconnected": disconnected,
        "expired": expired,
    }

    score = 100.0
    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if disconnected:
        impact = min(INTEGRATION_DISCONNECTED_CAP, disconnected * INTEGRATION_DISCONNECTED_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "integration", "integration.disconnected",
            title=f"{disconnected} integration(s) disconnected",
            explanation="Disconnected publishing/provider accounts reduce integration health.",
            impact=impact,
            severity="high",
            observed_value=disconnected,
        ))
    if expired:
        impact = min(INTEGRATION_EXPIRED_CAP, expired * INTEGRATION_EXPIRED_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "integration", "integration.expired",
            title=f"{expired} integration(s) expired / invalid",
            explanation="Expired or invalid credentials need reconnection.",
            impact=impact,
            severity="high",
            observed_value=expired,
        ))
    if connected and not deductions:
        positives.append(_positive(
            "integration", "integration.connections_healthy",
            title="Integrations are connected",
            explanation=f"{connected} account(s) reporting connected status.",
            impact=5,
            observed_value=connected,
        ))

    d.score = clamp_score(score)
    d.deductions = deductions
    d.positive_signals = positives
    d.summary = f"Integration score {d.score}/100 from publishing account connection status."
    return d


# --------------------------------------------------------------------------- automation
def evaluate_automation(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("automation", "observation_missing")
    if obs.get("error"):
        return _unavailable("automation", "error")
    flow_count = int(obs.get("flow_count") or 0)
    if AUTOMATION_NO_FLOWS_UNAVAILABLE and flow_count == 0:
        return _unavailable("automation", "not_configured")

    failed_flows = int(obs.get("failed_flow_count") or 0)
    exec_failures = int(obs.get("execution_failures_24h") or 0)
    enabled = int(obs.get("enabled_count") or 0)

    d = _base("automation")
    d.availability = "available"
    d.freshness = "fresh"
    d.confidence = 0.8
    d.observed_metrics = {
        "flow_count": flow_count,
        "enabled_count": enabled,
        "failed_flow_count": failed_flows,
        "execution_failures_24h": exec_failures,
    }

    score = 100.0
    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if failed_flows:
        impact = min(AUTOMATION_FAILED_FLOW_CAP, failed_flows * AUTOMATION_FAILED_FLOW_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "automation", "automation.failed_flows",
            title=f"{failed_flows} automation flow(s) in failed state",
            explanation="Failed enabled flows need operator review.",
            impact=impact,
            severity="high",
            observed_value=failed_flows,
        ))
    if exec_failures:
        impact = min(AUTOMATION_EXEC_FAILURE_CAP, exec_failures * AUTOMATION_EXEC_FAILURE_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "automation", "automation.execution_failures",
            title=f"{exec_failures} automation execution failure(s) (24h)",
            explanation="Recent execution failures reduce automation reliability.",
            impact=impact,
            observed_value=exec_failures,
        ))
    if enabled and not deductions:
        positives.append(_positive(
            "automation", "automation.operating_normally",
            title="Automation jobs are operating normally",
            explanation="No failed flows or recent execution failures observed.",
            impact=5,
            observed_value=enabled,
        ))

    d.score = clamp_score(score)
    d.deductions = deductions
    d.positive_signals = positives
    d.summary = f"Automation score {d.score}/100 from flow and execution observations."
    return d


# --------------------------------------------------------------------------- customer success
def evaluate_customer_success(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("customer_success", "observation_missing")
    if obs.get("error"):
        return _unavailable("customer_success", "error")
    if obs.get("not_configured") or obs.get("is_demo"):
        # Demo-fabricated CS scores must not drive executive health.
        return _unavailable("customer_success", "not_configured")

    score_obs = obs.get("health_score")
    if score_obs is None or not CS_USE_OBSERVED_SCORE:
        return _unavailable("customer_success", "not_configured")

    d = _base("customer_success")
    d.availability = "available"
    d.freshness = "fresh"
    d.confidence = float(obs.get("confidence") or 0.7)
    d.score = clamp_score(int(score_obs))
    d.observed_metrics = {
        "health_score": d.score,
        "churn_risk": obs.get("churn_risk"),
        "adoption_score": obs.get("adoption_score"),
    }
    d.deductions = []
    d.positive_signals = []
    if d.score >= 70:
        d.positive_signals.append(_positive(
            "customer_success", "cs.healthy",
            title="Customer success health is solid",
            explanation=f"Observed CS health score {d.score}/100.",
            impact=3,
            observed_value=d.score,
        ))
    elif d.score < 50:
        impact = 50 - d.score
        d.deductions.append(_deduct(
            "customer_success", "cs.low_health",
            title=f"Customer success health is {d.score}/100",
            explanation="Observed CS health below attention threshold.",
            impact=min(25, impact),
            severity="high" if d.score < 30 else "medium",
            observed_value=d.score,
            threshold=50,
        ))
        # Keep domain score as observed CS score (already set).
    d.summary = f"Customer success score {d.score}/100 from adoption/ROI observations."
    return d


# --------------------------------------------------------------------------- revenue / billing
def evaluate_revenue_billing(obs: dict[str, Any] | None) -> DomainHealthAssessment:
    if obs is None:
        return _unavailable("revenue_billing", "observation_missing")
    if obs.get("error"):
        return _unavailable("revenue_billing", "error")
    status = obs.get("subscription_status")
    if BILLING_NO_SUBSCRIPTION_UNAVAILABLE and not status and not obs.get("has_usage"):
        return _unavailable("revenue_billing", "not_configured")

    d = _base("revenue_billing")
    d.availability = "available"
    d.freshness = "fresh"
    d.confidence = 0.75

    near_limit_count = int(obs.get("near_limit_count") or 0)
    d.observed_metrics = {
        "subscription_status": status,
        "monthly_price": obs.get("monthly_price"),
        "near_limit_count": near_limit_count,
        "mrr": obs.get("mrr"),
    }

    score = 100.0
    deductions: list[HealthSignal] = []
    positives: list[HealthSignal] = []

    if status in {"suspended", "cancelled", "expired"}:
        score -= BILLING_SUSPENDED_PENALTY
        deductions.append(_deduct(
            "revenue_billing", "billing.subscription_unhealthy",
            title=f"Subscription status is {status}",
            explanation="Unhealthy subscription status reduces billing health.",
            impact=BILLING_SUSPENDED_PENALTY,
            severity="critical",
            observed_value=status,
        ))
    if near_limit_count:
        impact = min(30, near_limit_count * BILLING_NEAR_LIMIT_PENALTY)
        score -= impact
        deductions.append(_deduct(
            "revenue_billing", "billing.near_plan_limit",
            title=f"{near_limit_count} usage metric(s) near plan limit",
            explanation=f"Usage ≥ {int(BILLING_NEAR_LIMIT_RATIO * 100)}% of plan limit.",
            impact=impact,
            severity="medium",
            observed_value=near_limit_count,
            threshold=BILLING_NEAR_LIMIT_RATIO,
        ))
    if status in {"active", "trial"} and not deductions:
        positives.append(_positive(
            "revenue_billing", "billing.subscription_healthy",
            title="Subscription billing looks healthy",
            explanation=f"Subscription status {status} without near-limit pressure.",
            impact=4,
            observed_value=status,
        ))

    d.score = clamp_score(score)
    d.deductions = deductions
    d.positive_signals = positives
    d.summary = f"Revenue/billing score {d.score}/100 from subscription and usage observations."
    return d


EVALUATORS = {
    "sales": evaluate_sales,
    "publishing": evaluate_publishing,
    "campaign_planning": evaluate_campaign_planning,
    "organic_measurement": evaluate_organic_measurement,
    "advertising": evaluate_advertising,
    "integration": evaluate_integration,
    "automation": evaluate_automation,
    "customer_success": evaluate_customer_success,
    "revenue_billing": evaluate_revenue_billing,
}
