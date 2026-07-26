"""Deterministic decision-support recommendations.

Structure: Observation, Evidence, Reasoning, Recommendation, Confidence, Limitations.
Forbidden wording includes performance promises and automatic action directives.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdCampaign
from app.models.advertising_decision_support import RECOMMENDATION_ENGINE_VERSION
from app.services.advertising_decision_support.change_plan_service import create_change_plan
from app.services.advertising_decision_support.concentration_analysis import (
    analyze_campaign_concentration,
)
from app.services.advertising_decision_support.creative_rotation import (
    analyze_creative_rotation,
)
from app.services.advertising_decision_support.pacing_projection import (
    project_campaign_pacing,
)

_FORBIDDEN_PHRASES = (
    "move %",
    "increase roas",
    "pause this ad",
    "pause this campaign",
    "guaranteed",
    "will improve",
    "apply to meta",
    "automatically reallocate",
)


def _rec(
    *,
    key: str,
    observation: str,
    evidence: dict[str, Any],
    reasoning: str,
    recommendation: str,
    confidence: Decimal,
    limitations: list[str],
    item_type: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    risk: str | None = None,
) -> dict[str, Any]:
    text_blob = " ".join([observation, reasoning, recommendation]).lower()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase in text_blob:
            raise ValueError(f"forbidden recommendation wording detected: {phrase}")
    return {
        "recommendation_key": key,
        "observation": observation,
        "evidence": evidence,
        "reasoning": reasoning,
        "recommendation": recommendation,
        "confidence": confidence,
        "limitations": limitations,
        "item_type": item_type,
        "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id else None,
        "risk": risk,
        "engine_version": RECOMMENDATION_ENGINE_VERSION,
        "read_only": True,
        "kind": "ADVISORY",
    }


async def generate_recommendations(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Build deterministic recommendations from concentration, pacing, rotation."""
    recs: list[dict[str, Any]] = []

    concentration = await analyze_campaign_concentration(
        db, tenant_id, account_id=account_id,
    )
    if concentration["status"] in {"highly_concentrated", "moderately_concentrated"}:
        top = (concentration.get("ranked") or [{}])[0]
        top_id = top.get("entity_id")
        share = concentration.get("top1_share")
        share_pct = f"{float(Decimal(share)) * 100:.1f}%" if share else "a large share"
        recs.append(
            _rec(
                key="advertising.review_budget_concentration",
                observation=(
                    f"One campaign represents {share_pct} of measured spend "
                    f"(HHI={concentration.get('hhi')})."
                ),
                evidence={
                    "status": concentration["status"],
                    "top1_share": concentration.get("top1_share"),
                    "top3_share": concentration.get("top3_share"),
                    "hhi": concentration.get("hhi"),
                    "ranked": concentration.get("ranked"),
                },
                reasoning=(
                    "Concentration diagnostics summarize observed spend distribution; "
                    "they do not imply that concentration is necessarily harmful."
                ),
                recommendation=(
                    "Consider reviewing whether this concentration matches your intended strategy."
                ),
                confidence=Decimal("0.850"),
                limitations=[
                    "Based on observed spend only; ignores strategic intent and learning phases.",
                    "Does not prescribe budget moves or predict ROAS impact.",
                ],
                item_type="review_budget_allocation",
                entity_type="campaign",
                entity_id=UUID(top_id) if top_id else None,
                risk="medium" if concentration["status"] == "highly_concentrated" else "low",
            )
        )

    filters = [TenantAdCampaign.tenant_id == tenant_id]
    if account_id is not None:
        filters.append(TenantAdCampaign.advertising_account_id == account_id)
    campaigns = list(
        (await db.execute(select(TenantAdCampaign).where(*filters))).scalars().all()
    )
    for campaign in campaigns[:20]:
        pacing = await project_campaign_pacing(db, tenant_id, campaign.id)
        status = pacing.get("projection_status")
        if status in {"projected"}:
            projected = pacing.get("projected_end_spend_minor")
            budget = pacing.get("budget_minor")
            if projected is not None and budget and projected > int(budget) * 1.2:
                recs.append(
                    _rec(
                        key="advertising.review_pacing_projection",
                        observation=(
                            f"Mechanical projection for campaign '{campaign.name}' "
                            f"suggests end-of-period spend {projected} vs budget {budget}."
                        ),
                        evidence={
                            "projection_status": status,
                            "projected_end_spend_minor": projected,
                            "budget_minor": budget,
                            "elapsed_fraction": pacing.get("elapsed_fraction"),
                            "daily_spend_rate_minor": pacing.get("daily_spend_rate_minor"),
                            "label": pacing.get("label"),
                        },
                        reasoning=(
                            "Projection is a linear extrapolation of the current spend rate, "
                            "not an AI forecast or performance guarantee."
                        ),
                        recommendation=(
                            "Consider reviewing pacing and budget settings with the team."
                        ),
                        confidence=Decimal("0.750"),
                        limitations=[
                            "Assumes roughly constant spend rate; ignores dayparting and pacing controls.",
                            "Stale or incomplete data reduces reliability.",
                        ],
                        item_type="review_pacing",
                        entity_type="campaign",
                        entity_id=campaign.id,
                        risk="medium",
                    )
                )

    rotation = await analyze_creative_rotation(db, tenant_id, account_id=account_id)
    if rotation["status"] in {"possible_fatigue", "concentrated"}:
        recs.append(
            _rec(
                key="advertising.review_creative_rotation",
                observation=rotation.get("observation", "Creative rotation signal detected."),
                evidence=rotation.get("evidence") or {},
                reasoning=rotation.get("interpretation") or (
                    "Rotation analysis combines exposure concentration and frequency heuristics."
                ),
                recommendation=rotation.get("possible_consideration") or (
                    "Consider testing additional creative variants under human review."
                ),
                confidence=Decimal("0.700"),
                limitations=[
                    "Frequency heuristics are possible signals, not proof of fatigue causation.",
                    "No automatic pause or creative replacement is implied.",
                ],
                item_type="review_creative_rotation",
                risk="medium" if rotation["status"] == "possible_fatigue" else "low",
            )
        )

    return recs


async def generate_draft_change_plan(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
    user_id: UUID | None = None,
    title: str | None = None,
) -> dict[str, Any] | None:
    """Materialize current recommendations into a draft change plan (or None)."""
    recs = await generate_recommendations(db, tenant_id, account_id=account_id)
    if not recs:
        return None
    items = []
    for rec in recs:
        items.append({
            "item_type": rec["item_type"],
            "entity_type": rec.get("entity_type"),
            "entity_id": rec.get("entity_id"),
            "observation": rec["observation"],
            "evidence_json": rec["evidence"],
            "reasoning": rec["reasoning"],
            "suggested_human_action": rec["recommendation"],
            "risk": rec.get("risk"),
            "confidence": rec["confidence"],
            "supporting_metrics": {
                "limitations": rec["limitations"],
                "recommendation_key": rec["recommendation_key"],
            },
        })
    return await create_change_plan(
        db,
        tenant_id,
        title=title or "Decision support draft change plan",
        items=items,
        source="recommendation_engine",
        summary=(
            f"{len(items)} advisory item(s) derived from concentration, "
            "pacing projection, and creative rotation."
        ),
        evidence_json={"recommendation_count": len(items)},
        user_id=user_id,
    )


__all__ = [
    "generate_recommendations",
    "generate_draft_change_plan",
]
