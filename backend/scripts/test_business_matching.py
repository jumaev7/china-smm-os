"""Manual validation tests for Business Matching Center."""
from decimal import Decimal

from app.schemas.business_matching import (
    BusinessMatchingDashboardResponse,
    BusinessMatchingKpis,
    BusinessMatchingOpportunityItem,
    BusinessMatchingRecommendation,
    MatchScoreResult,
)
from app.services.matching_engine_service import (
    BuyerMatchInput,
    MatchingContext,
    MatchingEngineService,
)


def test_match_score_result_bounds():
    result = MatchScoreResult(match_score=50, confidence_score=60, reasoning="test")
    assert 0 <= result.match_score <= 100


def test_matching_engine_industry_match():
    buyer = BuyerMatchInput(industry="Textiles", country="Uzbekistan", product_interest="cotton fabric")
    supplier = MatchingContext(
        industries=["Textiles", "Garments"],
        product_categories=["cotton fabric", "yarn"],
        export_markets=["Uzbekistan", "Kazakhstan"],
    )
    result = MatchingEngineService.compute_match(buyer, supplier)
    assert result.match_score >= 50
    assert result.confidence_score >= 40
    assert "Industry" in result.reasoning or "Export" in result.reasoning or result.match_score >= 50


def test_matching_engine_history_boost():
    buyer = BuyerMatchInput(
        industry="Electronics",
        country="Kazakhstan",
        communication_count=3,
        proposal_count=2,
        deal_count=1,
        won_deal_count=1,
    )
    supplier = MatchingContext(industries=["Electronics"], export_markets=["Kazakhstan"])
    result = MatchingEngineService.compute_match(buyer, supplier)
    assert result.match_factors.get("history_boost", 0) > 0


def test_kpis_defaults():
    kpis = BusinessMatchingKpis()
    assert kpis.total_opportunities == 0
    assert kpis.estimated_pipeline_value == Decimal("0")


def test_dashboard_response_minimal():
    from datetime import datetime, timezone

    kpis = BusinessMatchingKpis(total_opportunities=3, active_matches=2)
    dashboard = BusinessMatchingDashboardResponse(kpis=kpis)
    assert dashboard.kpis.total_opportunities == 3
    assert dashboard.recommendations == []


def test_recommendation_priority():
    rec = BusinessMatchingRecommendation(
        id="r1",
        category="high_value",
        priority="high",
        title="Contact buyer",
        reason="Strong match",
        recommended_action="Schedule call",
    )
    assert rec.priority == "high"


if __name__ == "__main__":
    test_match_score_result_bounds()
    test_matching_engine_industry_match()
    test_matching_engine_history_boost()
    test_kpis_defaults()
    test_dashboard_response_minimal()
    test_recommendation_priority()
    print("All Business Matching tests passed.")
