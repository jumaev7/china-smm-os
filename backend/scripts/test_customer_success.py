"""Validation tests for Customer Success & Factory ROI Center."""
from decimal import Decimal

from app.schemas.customer_success import (
    AdoptionDashboard,
    AdoptionMetric,
    BusinessImpactMetrics,
    CustomerSuccessDashboardResponse,
    CustomerSuccessHealthScore,
    FactoryRoiKpis,
    HealthScoreFactor,
    RoiCalculation,
    RoiConfigWeights,
)
from app.services.customer_success_service import CustomerSuccessService, _health_status


def test_roi_kpis_defaults():
    kpis = FactoryRoiKpis()
    assert kpis.total_leads_generated == 0
    assert kpis.pipeline_value == Decimal("0")


def test_health_status_thresholds():
    assert _health_status(75) == "healthy"
    assert _health_status(55) == "needs_attention"
    assert _health_status(30) == "at_risk"


def test_roi_calculation_positive():
    roi = CustomerSuccessService._compute_roi(
        leads=[1, 2, 3],
        deals=[],
        proposals=[],
        subscription_cost=Decimal("99"),
    )
    assert roi.leads_generated == 3
    assert roi.subscription_cost == Decimal("99")
    assert isinstance(roi.estimated_roi_pct, float)


def test_roi_config_weights():
    cfg = RoiConfigWeights(pipeline_weight=0.5, proposal_weight=0.3, won_deals_weight=0.2)
    assert cfg.pipeline_weight == 0.5
    assert cfg.lead_value_multiplier == 500.0


def test_health_score_structure():
    adoption = AdoptionDashboard(
        metrics=[
            AdoptionMetric(key="logins", label="User Logins", count=5, score=80),
            AdoptionMetric(key="content", label="Content", count=10, score=70),
            AdoptionMetric(key="crm", label="CRM", count=8, score=75),
            AdoptionMetric(key="buyers", label="Buyers", count=6, score=65),
            AdoptionMetric(key="communication", label="Comms", count=20, score=85),
            AdoptionMetric(key="proposals", label="Proposals", count=3, score=60),
        ],
        engagement_score=72,
    )
    health = CustomerSuccessService._build_health_score(adoption)
    assert 0 <= health.score <= 100
    assert health.status in ("healthy", "needs_attention", "at_risk")
    assert len(health.factors) == 6


def test_business_impact_empty():
    impact = CustomerSuccessService._build_business_impact([], [], [], [])
    assert impact.buyers_acquired == 0
    assert impact.proposal_acceptance_rate == 0.0


def test_demo_dashboard():
    demo = CustomerSuccessService._demo_dashboard()
    assert demo.is_demo is True
    assert demo.roi_kpis.total_leads_generated > 0
    assert demo.roi.estimated_roi_pct > 0
    assert len(demo.insights) >= 1


def test_dashboard_response_minimal():
    from datetime import datetime, timezone

    kpis = FactoryRoiKpis(total_leads_generated=10, total_buyers_added=5)
    health = CustomerSuccessHealthScore(
        score=70,
        status="healthy",
        label="Healthy",
        summary="ok",
        factors=[
            HealthScoreFactor(factor="adoption", label="Adoption", score=70, weight_pct=20, summary="ok"),
        ],
    )
    dash = CustomerSuccessDashboardResponse(
        roi_kpis=kpis,
        roi=RoiCalculation(),
        health_score=health,
        adoption_summary=AdoptionDashboard(metrics=[], engagement_score=70),
        business_impact=BusinessImpactMetrics(),
        insights=[],
        generated_at=datetime.now(timezone.utc),
    )
    assert dash.roi_kpis.total_leads_generated == 10


if __name__ == "__main__":
    test_roi_kpis_defaults()
    test_health_status_thresholds()
    test_roi_calculation_positive()
    test_roi_config_weights()
    test_health_score_structure()
    test_business_impact_empty()
    test_demo_dashboard()
    test_dashboard_response_minimal()
    print("All customer success tests passed.")
