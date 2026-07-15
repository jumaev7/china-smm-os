"""Deterministic scoring engine — weighted, versioned, explainable (no ML/AI)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.intelligence.explanation_engine import ExplanationEngine
from app.services.intelligence.store import IntelligenceStore
from app.services.intelligence.types import (
    SCORE_LOOKBACK_DAYS,
    SCORE_WEIGHTS,
    SCORING_ENGINE_VERSION,
    ScoreResult,
)

# Baseline score when no signal evidence exists.
_NEUTRAL = 70


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


class ScoringEngine:
    """Compute category and overall marketing scores from normalized signals."""

    version = SCORING_ENGINE_VERSION

    @staticmethod
    async def compute_all(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        persist: bool = True,
        record_history: bool = True,
    ) -> list[ScoreResult]:
        since = _utcnow() - timedelta(days=SCORE_LOOKBACK_DAYS)
        counts = await IntelligenceStore.count_signals_by_type(db, tenant_id, since=since)
        results = ScoringEngine.compute_from_counts(counts)
        if persist:
            for result in results:
                await IntelligenceStore.upsert_score(
                    db, tenant_id, result, record_history=record_history,
                )
            # Daily trend bucket for overall score
            overall = next((r for r in results if r.category == "overall"), None)
            if overall is not None:
                now = _utcnow()
                bucket_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                bucket_end = bucket_start + timedelta(days=1)
                await IntelligenceStore.upsert_trend(
                    db,
                    tenant_id=tenant_id,
                    metric_key="score.overall",
                    bucket_start=bucket_start,
                    bucket_end=bucket_end,
                    value=overall.score,
                    sample_count=sum(counts.values()),
                    metadata={"scoring_version": SCORING_ENGINE_VERSION},
                )
        return results

    @staticmethod
    def compute_from_counts(counts: dict[str, int]) -> list[ScoreResult]:
        """Pure function — same counts always produce the same scores."""
        category_scores: dict[str, ScoreResult] = {}

        category_scores["publishing"] = ScoringEngine._score_publishing(counts)
        category_scores["advertising"] = ScoringEngine._score_advertising(counts)
        category_scores["crm"] = ScoringEngine._score_crm(counts)
        category_scores["automation"] = ScoringEngine._score_automation(counts)
        category_scores["workflow"] = ScoringEngine._score_workflow(counts)
        category_scores["customer_success"] = ScoringEngine._score_customer_success(counts)
        category_scores["brand"] = ScoringEngine._score_brand(counts)
        category_scores["content"] = ScoringEngine._score_content(counts)

        # Weighted overall
        weighted_sum = Decimal("0")
        weight_total = Decimal("0")
        evidence_lines: list[str] = []
        for category, weight in SCORE_WEIGHTS.items():
            result = category_scores[category]
            weighted_sum += Decimal(result.score) * weight
            weight_total += weight
            evidence_lines.append(f"{category}={result.score} (weight={weight})")

        overall_score = _clamp(int(round(weighted_sum / weight_total))) if weight_total else _NEUTRAL
        overall = ScoreResult(
            category="overall",
            score=overall_score,
            weight=Decimal("1.0000"),
            scoring_version=SCORING_ENGINE_VERSION,
            explanation=ExplanationEngine.for_score(
                category="overall",
                score=overall_score,
                evidence_lines=evidence_lines,
                reasoning=(
                    f"Overall marketing score is the weighted average of category scores "
                    f"(engine {SCORING_ENGINE_VERSION})."
                ),
                recommendation=(
                    "Review lower category scores and open recommendations."
                    if overall_score < 60
                    else None
                ),
            ),
            evidence={"category_scores": {k: v.score for k, v in category_scores.items()}, "weights": {
                k: str(v) for k, v in SCORE_WEIGHTS.items()
            }},
        )

        return [*category_scores.values(), overall]

    @staticmethod
    def _result(
        category: str,
        score: int,
        *,
        evidence: dict[str, Any],
        evidence_lines: list[str],
        reasoning: str,
        recommendation: str | None = None,
    ) -> ScoreResult:
        return ScoreResult(
            category=category,
            score=_clamp(score),
            weight=SCORE_WEIGHTS.get(category, Decimal("0.1000")),
            scoring_version=SCORING_ENGINE_VERSION,
            explanation=ExplanationEngine.for_score(
                category=category,
                score=_clamp(score),
                evidence_lines=evidence_lines,
                reasoning=reasoning,
                recommendation=recommendation,
            ),
            evidence=evidence,
        )

    @staticmethod
    def _score_publishing(counts: dict[str, int]) -> ScoreResult:
        completed = counts.get("publishing.completed", 0)
        failed = counts.get("publishing.failed", 0)
        partial = counts.get("publishing.partial_failed", 0)
        reviews = counts.get("publishing.review_completed", 0)
        score_low = counts.get("publishing.score_low", 0)
        critical = counts.get("publishing.critical_issue_detected", 0)
        fit_low = counts.get("publishing.platform_fit_low", 0)
        attempts = completed + failed + partial
        if attempts == 0 and reviews == 0:
            score = _NEUTRAL
            reasoning = "No publishing activity in the lookback window; baseline score applied."
        elif attempts == 0:
            review_penalty = min(35, score_low * 6 + critical * 10 + fit_low * 4)
            score = _clamp(72 - review_penalty + min(8, reviews))
            reasoning = (
                f"{reviews} publishing review(s); penalties for {score_low} low scores, "
                f"{critical} critical issues, {fit_low} platform-fit warnings."
            )
        else:
            success_rate = completed / attempts
            fail_penalty = min(40, failed * 8 + partial * 4)
            review_penalty = min(20, score_low * 4 + critical * 6 + fit_low * 3)
            score = _clamp(
                int(round(40 + success_rate * 60 - fail_penalty - review_penalty + min(10, completed)))
            )
            reasoning = (
                f"Success rate {success_rate:.0%} across {attempts} attempts; "
                f"penalty for {failed} failures, {partial} partial failures, "
                f"and {score_low + critical + fit_low} review quality signals."
            )
        return ScoringEngine._result(
            "publishing",
            score,
            evidence={
                "completed": completed,
                "failed": failed,
                "partial_failed": partial,
                "review_completed": reviews,
                "score_low": score_low,
                "critical_issue_detected": critical,
                "platform_fit_low": fit_low,
            },
            evidence_lines=[
                f"{completed} completed publishes",
                f"{failed} failed publishes",
                f"{partial} partial failures",
                f"{reviews} publishing reviews",
                f"{score_low} low publishing scores",
                f"{critical} critical review issues",
            ],
            reasoning=reasoning,
            recommendation=(
                "Review publishing accounts and pre-publish quality."
                if failed >= 2 or critical >= 1
                else None
            ),
        )

    @staticmethod
    def _score_advertising(counts: dict[str, int]) -> ScoreResult:
        started = counts.get("campaign.started", 0)
        stopped = counts.get("campaign.stopped", 0)
        if started == 0 and stopped == 0:
            score = _NEUTRAL
            reasoning = "No campaign signals yet; advertising score remains baseline."
        else:
            score = _clamp(60 + min(25, started * 5) - min(20, stopped * 4))
            reasoning = f"{started} campaigns started, {stopped} stopped in lookback."
        return ScoringEngine._result(
            "advertising",
            score,
            evidence={"campaign_started": started, "campaign_stopped": stopped},
            evidence_lines=[f"{started} started", f"{stopped} stopped"],
            reasoning=reasoning,
        )

    @staticmethod
    def _score_crm(counts: dict[str, int]) -> ScoreResult:
        leads = counts.get("crm.lead_created", 0)
        buyers = counts.get("crm.buyer_created", 0)
        won = counts.get("crm.deal_won", 0)
        lost = counts.get("crm.deal_lost", 0)
        stages = counts.get("crm.deal_stage_changed", 0)
        activity = leads + buyers + stages + won + lost
        if activity == 0:
            score = 55
            reasoning = "No CRM activity detected; below-neutral score encourages pipeline work."
        else:
            score = _clamp(50 + min(25, leads * 3) + min(15, buyers * 3) + won * 8 - lost * 5 + min(10, stages))
            reasoning = (
                f"CRM momentum from {leads} leads, {buyers} buyers, {won} wins, {lost} losses."
            )
        return ScoringEngine._result(
            "crm",
            score,
            evidence={"leads": leads, "buyers": buyers, "won": won, "lost": lost, "stage_changes": stages},
            evidence_lines=[
                f"{leads} leads created",
                f"{buyers} buyers created",
                f"{won} deals won / {lost} lost",
            ],
            reasoning=reasoning,
            recommendation="Increase lead capture and deal progression." if activity < 2 else None,
        )

    @staticmethod
    def _score_automation(counts: dict[str, int]) -> ScoreResult:
        triggered = counts.get("automation.triggered", 0)
        retried = counts.get("automation.retried", 0)
        if triggered == 0 and retried == 0:
            score = 60
            reasoning = "No automation activity; slightly below baseline to encourage setup."
        else:
            score = _clamp(65 + min(30, triggered * 4) - min(25, retried * 6))
            reasoning = f"{triggered} automations triggered, {retried} retries observed."
        return ScoringEngine._result(
            "automation",
            score,
            evidence={"triggered": triggered, "retried": retried},
            evidence_lines=[f"{triggered} triggered", f"{retried} retried"],
            reasoning=reasoning,
            recommendation="Review failing automation jobs." if retried >= 3 else None,
        )

    @staticmethod
    def _score_workflow(counts: dict[str, int]) -> ScoreResult:
        executed = counts.get("workflow.executed", 0)
        # Workflow executions may also surface via automation.triggered until dedicated events exist.
        proxy = counts.get("automation.triggered", 0)
        total = executed + (proxy if executed == 0 else 0)
        if total == 0:
            score = 60
            reasoning = "No workflow execution signals; baseline-below score."
        else:
            score = _clamp(70 + min(25, total * 3))
            reasoning = f"{total} workflow-related executions in lookback."
        return ScoringEngine._result(
            "workflow",
            score,
            evidence={"executed": executed, "automation_proxy": proxy},
            evidence_lines=[f"{executed} workflow executions", f"{proxy} automation triggers"],
            reasoning=reasoning,
        )

    @staticmethod
    def _score_customer_success(counts: dict[str, int]) -> ScoreResult:
        milestones = counts.get("customer_success.milestone", 0)
        ready = counts.get("onboarding.platform_ready", 0)
        steps = counts.get("onboarding.step_completed", 0)
        if milestones == 0 and ready == 0 and steps == 0:
            score = 55
            reasoning = "No customer success / onboarding progress signals."
        else:
            score = _clamp(60 + milestones * 8 + ready * 15 + min(15, steps * 3))
            reasoning = f"{milestones} milestones, {ready} platform-ready, {steps} onboarding steps."
        return ScoringEngine._result(
            "customer_success",
            score,
            evidence={"milestones": milestones, "platform_ready": ready, "steps": steps},
            evidence_lines=[
                f"{milestones} milestones",
                f"{ready} platform-ready events",
                f"{steps} onboarding steps",
            ],
            reasoning=reasoning,
        )

    @staticmethod
    def _score_brand(counts: dict[str, int]) -> ScoreResult:
        # Brand health proxy: successful publishes + content + disconnected integrations (penalty).
        completed = counts.get("publishing.completed", 0)
        content = counts.get("content.created", 0)
        disconnected = counts.get("integration.disconnected", 0)
        score = _clamp(_NEUTRAL + min(20, completed * 2 + content) - disconnected * 12)
        return ScoringEngine._result(
            "brand",
            score,
            evidence={"publishes": completed, "content": content, "disconnected": disconnected},
            evidence_lines=[
                f"{completed} successful publishes",
                f"{content} content created",
                f"{disconnected} integration disconnects",
            ],
            reasoning="Brand score blends publishing presence with integration stability.",
            recommendation="Reconnect disconnected integrations." if disconnected else None,
        )

    @staticmethod
    def _score_content(counts: dict[str, int]) -> ScoreResult:
        created = counts.get("content.created", 0)
        published = counts.get("publishing.completed", 0)
        if created == 0 and published == 0:
            score = 55
            reasoning = "No content creation or publishing activity."
        else:
            score = _clamp(55 + min(30, created * 4) + min(20, published * 3))
            reasoning = f"{created} content items created, {published} published."
        return ScoringEngine._result(
            "content",
            score,
            evidence={"created": created, "published": published},
            evidence_lines=[f"{created} created", f"{published} published"],
            reasoning=reasoning,
        )
