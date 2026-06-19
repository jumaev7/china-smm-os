"""Reusable B2B matching engine — scores buyer/supplier fit from platform data."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.business_matching import MatchScoreResult

_BASE_SCORE = 15


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


@dataclass
class MatchingContext:
    """Factory/supplier-side profile for matching."""

    industries: list[str] = field(default_factory=list)
    product_categories: list[str] = field(default_factory=list)
    export_markets: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)


@dataclass
class BuyerMatchInput:
    industry: str | None = None
    country: str | None = None
    product_interest: str | None = None
    product_categories: list[str] | None = None
    trade_interests: list[str] | None = None
    buyer_score: int = 0
    opportunity_score: int = 0
    deal_count: int = 0
    won_deal_count: int = 0
    proposal_count: int = 0
    communication_count: int = 0


class MatchingEngineService:
    """Rule-based matching engine reused across Business Matching Center modules."""

    @staticmethod
    def compute_match(
        buyer: BuyerMatchInput,
        supplier: MatchingContext,
    ) -> MatchScoreResult:
        factors: dict[str, Any] = {
            "industry_match": 0,
            "product_match": 0,
            "market_match": 0,
            "category_match": 0,
            "trade_interest_match": 0,
            "history_boost": 0,
            "intelligence_boost": 0,
        }
        score = _BASE_SCORE
        reasoning_parts: list[str] = []

        ind = (buyer.industry or "").lower()
        cty = (buyer.country or "").lower()
        interest = (buyer.product_interest or "").lower()
        factory_industries = [t.lower() for t in supplier.industries if t]
        factory_products = [t.lower() for t in supplier.product_categories if t]
        factory_markets = [t.lower() for t in supplier.export_markets if t]

        if ind and factory_industries:
            if any(t in ind or ind in t for t in factory_industries):
                factors["industry_match"] = 25
                score += 25
                reasoning_parts.append(f"Industry alignment: {buyer.industry}")
            else:
                factors["industry_match"] = 8
                score += 8
        elif ind:
            factors["industry_match"] = 10
            score += 10

        if factory_products:
            matched = False
            for prod in factory_products:
                if prod and (prod in interest or prod in ind or interest in prod):
                    matched = True
                    break
            if not matched and buyer.product_categories:
                for cat in buyer.product_categories:
                    cat_l = (cat or "").lower()
                    if any(cat_l in p or p in cat_l for p in factory_products):
                        matched = True
                        break
            if matched:
                factors["product_match"] = 20
                score += 20
                reasoning_parts.append("Product category overlap detected")
            elif interest:
                factors["product_match"] = 8
                score += 8

        if cty and factory_markets:
            if any(t in cty or cty in t for t in factory_markets):
                factors["market_match"] = 25
                score += 25
                reasoning_parts.append(f"Export market fit: {buyer.country}")
            else:
                factors["market_match"] = 8
                score += 8
        elif cty:
            factors["market_match"] = 10
            score += 10

        if factory_products and interest:
            cat_hits = sum(1 for p in factory_products if p in interest)
            if cat_hits:
                factors["category_match"] = min(15, cat_hits * 5)
                score += factors["category_match"]

        if buyer.trade_interests and factory_products:
            trade_hits = sum(
                1 for ti in buyer.trade_interests
                if any((ti or "").lower() in p or p in (ti or "").lower() for p in factory_products)
            )
            if trade_hits:
                factors["trade_interest_match"] = min(12, trade_hits * 4)
                score += factors["trade_interest_match"]
                reasoning_parts.append("Trade interests align with supplier catalog")

        history_boost = 0
        if buyer.communication_count > 0:
            history_boost += min(8, buyer.communication_count * 2)
        if buyer.proposal_count > 0:
            history_boost += min(6, buyer.proposal_count * 3)
        if buyer.deal_count > 0:
            history_boost += min(6, buyer.deal_count * 2)
        if buyer.won_deal_count > 0:
            history_boost += min(10, buyer.won_deal_count * 5)
        factors["history_boost"] = history_boost
        score += history_boost
        if history_boost:
            reasoning_parts.append("Prior engagement history strengthens match")

        intel = int((buyer.buyer_score * 0.1) + (buyer.opportunity_score * 0.1))
        factors["intelligence_boost"] = intel
        score += intel

        match_score = _clamp(score)
        filled_factors = sum(1 for v in factors.values() if isinstance(v, (int, float)) and v > 0)
        confidence = _clamp(int(40 + filled_factors * 8 + min(20, history_boost)))
        if not reasoning_parts:
            reasoning_parts.append("Baseline platform profile compatibility")

        return MatchScoreResult(
            match_score=match_score,
            confidence_score=confidence,
            reasoning="; ".join(reasoning_parts),
            match_factors={k: v for k, v in factors.items() if v},
        )

    @staticmethod
    def compute_supplier_match(
        supplier_industries: list[str],
        supplier_products: list[str],
        supplier_markets: list[str],
        buyer: BuyerMatchInput,
    ) -> MatchScoreResult:
        ctx = MatchingContext(
            industries=supplier_industries,
            product_categories=supplier_products,
            export_markets=supplier_markets,
        )
        return MatchingEngineService.compute_match(buyer, ctx)
