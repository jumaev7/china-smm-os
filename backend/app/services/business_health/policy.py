"""Centralized Business Health v2 scoring policy.

This is a transparent operational heuristic, not a predictive or statistical
model. Thresholds and weights live here so evaluators stay free of scattered
magic numbers.
"""
from __future__ import annotations

from typing import Final

BUSINESS_HEALTH_VERSION: Final[str] = "business_health_v2"

# Base weights before availability normalization. Sum is informative only;
# effective weights are re-normalized across *available* domains.
DOMAIN_WEIGHTS: Final[dict[str, float]] = {
    "sales": 20.0,
    "publishing": 15.0,
    "campaign_planning": 12.0,
    "organic_measurement": 10.0,
    "advertising": 15.0,
    "integration": 10.0,
    "automation": 8.0,
    "customer_success": 5.0,
    "revenue_billing": 5.0,
}

DOMAIN_LABELS: Final[dict[str, str]] = {
    "sales": "Sales Health",
    "publishing": "Publishing Health",
    "campaign_planning": "Campaign Planning Health",
    "organic_measurement": "Organic Measurement Health",
    "advertising": "Advertising Health",
    "integration": "Integration Health",
    "automation": "Automation Health",
    "customer_success": "Customer Success Health",
    "revenue_billing": "Revenue / Billing Health",
}

# Score bands (inclusive lower bound). Keep labels product-stable.
SCORE_BANDS: Final[tuple[tuple[int, str], ...]] = (
    (85, "excellent"),
    (70, "healthy"),
    (50, "needs_attention"),
    (30, "at_risk"),
    (0, "critical"),
)

# --- Sales ---
SALES_OVERDUE_TASK_PENALTY: Final[int] = 4
SALES_OVERDUE_TASK_CAP: Final[int] = 30
SALES_RISK_PENALTY: Final[int] = 3
SALES_RISK_CAP: Final[int] = 25
SALES_NEGLECTED_PENALTY: Final[int] = 2
SALES_NEGLECTED_CAP: Final[int] = 15
SALES_INACTIVE_PENALTY: Final[int] = 1
SALES_INACTIVE_CAP: Final[int] = 10
SALES_UNANSWERED_PENALTY: Final[int] = 3
SALES_UNANSWERED_CAP: Final[int] = 15
SALES_UNASSIGNED_PENALTY: Final[int] = 2
SALES_UNASSIGNED_CAP: Final[int] = 10
SALES_HOT_NO_FOLLOWUP_PENALTY: Final[int] = 5
SALES_HOT_NO_FOLLOWUP_CAP: Final[int] = 10
SALES_HEALTHY_HOT_BONUS: Final[int] = 3  # positive signal only when hot leads exist & no overdue hot followups

# --- Publishing ---
PUBLISHING_SUCCESS_HEALTHY_PCT: Final[float] = 85.0
PUBLISHING_SUCCESS_ATTENTION_PCT: Final[float] = 70.0
PUBLISHING_FAILED_PENALTY: Final[int] = 5
PUBLISHING_FAILED_CAP: Final[int] = 35
PUBLISHING_LOW_SUCCESS_PENALTY: Final[int] = 15
PUBLISHING_NO_ATTEMPTS_NEUTRAL: Final[int] = 70  # configured but idle — not zero

# --- Campaign planning ---
CAMPAIGN_UNASSIGNED_RATIO_HIGH: Final[float] = 0.28
CAMPAIGN_UNASSIGNED_PENALTY_SCALE: Final[int] = 40  # * ratio
CAMPAIGN_BLOCKED_PENALTY: Final[int] = 4
CAMPAIGN_BLOCKED_CAP: Final[int] = 20
CAMPAIGN_NO_ACTIVE_NEUTRAL: Final[int] = 72

# --- Organic measurement ---
MEASUREMENT_STALE_PENALTY: Final[int] = 3
MEASUREMENT_STALE_CAP: Final[int] = 30
MEASUREMENT_ANOMALY_PENALTY: Final[int] = 4
MEASUREMENT_ANOMALY_CAP: Final[int] = 24
MEASUREMENT_EMPTY_NEUTRAL: Final[int] = 68

# --- Advertising ---
AD_STALE_CAMPAIGN_PENALTY: Final[int] = 4
AD_STALE_CAMPAIGN_CAP: Final[int] = 28
AD_PACING_WARNING_PENALTY: Final[int] = 3
AD_PACING_WARNING_CAP: Final[int] = 18
AD_ANOMALY_PENALTY: Final[int] = 4
AD_ANOMALY_CAP: Final[int] = 20
AD_FATIGUE_PENALTY: Final[int] = 2
AD_FATIGUE_CAP: Final[int] = 12
AD_WEAK_ATTRIBUTION_RATIO: Final[float] = 0.5
AD_WEAK_ATTRIBUTION_PENALTY: Final[int] = 8
AD_DISCONNECTED_PENALTY: Final[int] = 6
AD_DISCONNECTED_CAP: Final[int] = 24
AD_NO_ACCOUNTS_UNAVAILABLE: Final[bool] = True  # unused module → unavailable, not zero

# --- Integration ---
INTEGRATION_DISCONNECTED_PENALTY: Final[int] = 8
INTEGRATION_DISCONNECTED_CAP: Final[int] = 40
INTEGRATION_EXPIRED_PENALTY: Final[int] = 6
INTEGRATION_EXPIRED_CAP: Final[int] = 24
INTEGRATION_NO_ACCOUNTS_UNAVAILABLE: Final[bool] = True

# --- Automation ---
AUTOMATION_FAILED_FLOW_PENALTY: Final[int] = 8
AUTOMATION_FAILED_FLOW_CAP: Final[int] = 40
AUTOMATION_EXEC_FAILURE_PENALTY: Final[int] = 2
AUTOMATION_EXEC_FAILURE_CAP: Final[int] = 20
AUTOMATION_NO_FLOWS_UNAVAILABLE: Final[bool] = True

# --- Customer success ---
# Prefer observed CS score when present; otherwise mark unavailable.
CS_USE_OBSERVED_SCORE: Final[bool] = True

# --- Revenue / billing ---
BILLING_NEAR_LIMIT_RATIO: Final[float] = 0.8
BILLING_NEAR_LIMIT_PENALTY: Final[int] = 10
BILLING_SUSPENDED_PENALTY: Final[int] = 25
BILLING_NO_SUBSCRIPTION_UNAVAILABLE: Final[bool] = True

# Explainability caps
TOP_DEDUCTIONS_LIMIT: Final[int] = 8
TOP_POSITIVE_SIGNALS_LIMIT: Final[int] = 6

DISCLAIMER: Final[str] = (
    "Business Health v2 is decision-support only. It does not forecast revenue, "
    "mutate advertising providers, publish content, execute automations, or change billing."
)
