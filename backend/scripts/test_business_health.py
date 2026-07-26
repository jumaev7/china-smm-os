"""Unit-style checks for Business Health v2 schemas and aggregation."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.executive_copilot import (
    BusinessHealthAssessmentResponse,
    DomainHealthAssessmentResponse,
    ExecutiveCopilotSummaryWidget,
)
from app.services.business_health.aggregator import assemble_assessment, clamp_score
from app.services.business_health.evaluators import evaluate_sales
from app.services.business_health.policy import BUSINESS_HEALTH_VERSION


def test_clamp_score():
    assert clamp_score(-1) == 0
    assert clamp_score(101) == 100


def test_sales_evaluator_stable_codes():
    domain = evaluate_sales({
        "overdue_tasks": 2,
        "risk_count": 0,
        "neglected_leads": 0,
        "inactive_leads": 0,
        "unanswered": 0,
        "unassigned_tasks": 0,
        "hot_leads": 0,
        "hot_no_followup": 0,
        "leads_count": 1,
    })
    assert domain.availability == "available"
    assert any(d.code == "sales.overdue_tasks" for d in domain.deductions)


def test_summary_widget_schema_accepts_business_health():
    assessment = assemble_assessment([
        evaluate_sales({
            "overdue_tasks": 0, "risk_count": 0, "neglected_leads": 0, "inactive_leads": 0,
            "unanswered": 0, "unassigned_tasks": 0, "hot_leads": 0, "hot_no_followup": 0, "leads_count": 0,
        }),
    ])
    payload = assessment.to_dict()
    widget = ExecutiveCopilotSummaryWidget(
        business_health_score=payload["score"],
        business_health=BusinessHealthAssessmentResponse(**payload),
    )
    assert widget.business_health is not None
    assert widget.business_health.methodology_version == BUSINESS_HEALTH_VERSION
    assert isinstance(widget.business_health.domains[0], DomainHealthAssessmentResponse)


if __name__ == "__main__":
    test_clamp_score()
    test_sales_evaluator_stable_codes()
    test_summary_widget_schema_accepts_business_health()
    print("OK test_business_health")
