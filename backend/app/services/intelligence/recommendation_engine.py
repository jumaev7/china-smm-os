"""Deterministic recommendation engine — rule-based, evidence-backed (no AI)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.intelligence.explanation_engine import ExplanationEngine
from app.services.intelligence.store import IntelligenceStore
from app.services.intelligence.types import (
    RECOMMENDATION_ENGINE_VERSION,
    SIGNAL_COUNT_LOOKBACK_DAYS,
    RecommendationResult,
    ScoreResult,
)

# Thresholds (deterministic rules)
PUBLISH_FAIL_THRESHOLD = 2
INTEGRATION_DISCONNECT_THRESHOLD = 1
LOW_CRM_ACTIVITY_THRESHOLD = 1
AUTOMATION_RETRY_THRESHOLD = 3
LOW_CONTENT_THRESHOLD = 1
LOW_OVERALL_SCORE = 55


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecommendationEngine:
    """Produce explainable recommendations from signal counts and scores."""

    version = RECOMMENDATION_ENGINE_VERSION

    @staticmethod
    async def compute_all(
        db: AsyncSession,
        tenant_id: UUID,
        scores: list[ScoreResult] | None = None,
        *,
        persist: bool = True,
        record_history: bool = True,
    ) -> list[RecommendationResult]:
        since = _utcnow() - timedelta(days=SIGNAL_COUNT_LOOKBACK_DAYS)
        counts = await IntelligenceStore.count_signals_by_type(db, tenant_id, since=since)
        score_map = {s.category: s.score for s in (scores or [])}
        results = RecommendationEngine.compute_from_counts(counts, score_map)

        if persist:
            active_keys = {r.recommendation_key for r in results}
            for result in results:
                await IntelligenceStore.upsert_recommendation(
                    db, tenant_id, result, record_history=record_history,
                )
            await IntelligenceStore.resolve_stale_recommendations(db, tenant_id, active_keys)
        return results

    @staticmethod
    def compute_from_counts(
        counts: dict[str, int],
        score_map: dict[str, int] | None = None,
    ) -> list[RecommendationResult]:
        """Pure function — identical inputs produce identical recommendations."""
        score_map = score_map or {}
        results: list[RecommendationResult] = []

        failed = counts.get("publishing.failed", 0)
        partial = counts.get("publishing.partial_failed", 0)
        fail_total = failed + partial
        if fail_total >= PUBLISH_FAIL_THRESHOLD:
            results.append(
                RecommendationEngine._rec(
                    key="publishing.review_accounts",
                    category="publishing",
                    title="Review publishing accounts",
                    reason=(
                        f"Publishing failures ({fail_total}) exceeded threshold "
                        f"({PUBLISH_FAIL_THRESHOLD}) in the last {SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[
                        f"{failed} full publish failures",
                        f"{partial} partial publish failures",
                        f"threshold={PUBLISH_FAIL_THRESHOLD}",
                    ],
                    evidence={
                        "failed": failed,
                        "partial_failed": partial,
                        "threshold": PUBLISH_FAIL_THRESHOLD,
                    },
                    priority="high" if failed >= 3 else "medium",
                    confidence=Decimal("0.920"),
                    rule_id="rule.publish_failures_gt_threshold",
                    action_url="/publishing",
                    recommendation_text="Verify connected publishing accounts and re-authenticate where needed.",
                )
            )

        disconnected = counts.get("integration.disconnected", 0)
        if disconnected >= INTEGRATION_DISCONNECT_THRESHOLD:
            results.append(
                RecommendationEngine._rec(
                    key="integration.reconnect",
                    category="brand",
                    title="Reconnect disconnected integrations",
                    reason=(
                        f"{disconnected} integration disconnect signal(s) detected "
                        f"(threshold {INTEGRATION_DISCONNECT_THRESHOLD})."
                    ),
                    evidence_lines=[f"{disconnected} disconnection events"],
                    evidence={"disconnected": disconnected},
                    priority="critical" if disconnected >= 2 else "high",
                    confidence=Decimal("0.950"),
                    rule_id="rule.integration_disconnected",
                    action_url="/integrations",
                    recommendation_text="Reconnect the affected platform integrations to restore publishing and CRM sync.",
                )
            )

        crm_activity = (
            counts.get("crm.lead_created", 0)
            + counts.get("crm.buyer_created", 0)
            + counts.get("crm.deal_stage_changed", 0)
            + counts.get("crm.deal_won", 0)
        )
        if crm_activity < LOW_CRM_ACTIVITY_THRESHOLD:
            results.append(
                RecommendationEngine._rec(
                    key="crm.increase_pipeline_activity",
                    category="crm",
                    title="Increase CRM pipeline activity",
                    reason=(
                        f"CRM activity signals ({crm_activity}) are below threshold "
                        f"({LOW_CRM_ACTIVITY_THRESHOLD}) over {SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[
                        f"leads={counts.get('crm.lead_created', 0)}",
                        f"buyers={counts.get('crm.buyer_created', 0)}",
                        f"stage_changes={counts.get('crm.deal_stage_changed', 0)}",
                    ],
                    evidence={"crm_activity": crm_activity, "threshold": LOW_CRM_ACTIVITY_THRESHOLD},
                    priority="medium",
                    confidence=Decimal("0.780"),
                    rule_id="rule.low_crm_activity",
                    action_url="/crm-pipeline",
                    recommendation_text="Create or progress leads and deals to improve CRM health.",
                )
            )

        retried = counts.get("automation.retried", 0)
        if retried >= AUTOMATION_RETRY_THRESHOLD:
            results.append(
                RecommendationEngine._rec(
                    key="automation.review_retries",
                    category="automation",
                    title="Investigate automation retries",
                    reason=(
                        f"Automation retries ({retried}) exceeded threshold "
                        f"({AUTOMATION_RETRY_THRESHOLD})."
                    ),
                    evidence_lines=[f"{retried} automation retries"],
                    evidence={"retried": retried, "threshold": AUTOMATION_RETRY_THRESHOLD},
                    priority="high",
                    confidence=Decimal("0.880"),
                    rule_id="rule.automation_retries_gt_threshold",
                    action_url="/automation",
                    recommendation_text="Inspect failed automation jobs and fix underlying action errors.",
                )
            )

        content = counts.get("content.created", 0) + counts.get("publishing.completed", 0)
        if content < LOW_CONTENT_THRESHOLD:
            results.append(
                RecommendationEngine._rec(
                    key="content.produce_more",
                    category="content",
                    title="Produce and publish more content",
                    reason=(
                        f"Content/publish activity ({content}) is below threshold "
                        f"({LOW_CONTENT_THRESHOLD})."
                    ),
                    evidence_lines=[
                        f"content.created={counts.get('content.created', 0)}",
                        f"publishing.completed={counts.get('publishing.completed', 0)}",
                    ],
                    evidence={"content_activity": content},
                    priority="low",
                    confidence=Decimal("0.750"),
                    rule_id="rule.low_content_activity",
                    action_url="/content",
                    recommendation_text="Create and schedule content to improve content health score.",
                )
            )

        overall = score_map.get("overall")
        if overall is not None and overall < LOW_OVERALL_SCORE:
            results.append(
                RecommendationEngine._rec(
                    key="overall.improve_marketing_health",
                    category="overall",
                    title="Improve overall marketing health",
                    reason=f"Overall marketing score ({overall}) is below {LOW_OVERALL_SCORE}.",
                    evidence_lines=[f"overall_score={overall}", f"threshold={LOW_OVERALL_SCORE}"],
                    evidence={"overall_score": overall, "threshold": LOW_OVERALL_SCORE},
                    priority="high",
                    confidence=Decimal("0.850"),
                    rule_id="rule.low_overall_score",
                    action_url="/marketing-intelligence",
                    recommendation_text="Address high-priority category recommendations first.",
                )
            )

        milestones = counts.get("customer_success.milestone", 0)
        if milestones == 0 and score_map.get("customer_success", 100) < 65:
            results.append(
                RecommendationEngine._rec(
                    key="customer_success.advance_journey",
                    category="customer_success",
                    title="Advance customer success journey",
                    reason="No customer success milestones recorded recently while CS score is low.",
                    evidence_lines=[
                        f"milestones={milestones}",
                        f"customer_success_score={score_map.get('customer_success')}",
                    ],
                    evidence={"milestones": milestones},
                    priority="medium",
                    confidence=Decimal("0.800"),
                    rule_id="rule.no_cs_milestones",
                    action_url="/customer-success",
                    recommendation_text="Complete onboarding and journey milestones.",
                )
            )

        # Stable ordering for determinism
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        results.sort(key=lambda r: (priority_order.get(r.priority, 9), r.recommendation_key))
        return results

    @staticmethod
    def _rec(
        *,
        key: str,
        category: str,
        title: str,
        reason: str,
        evidence_lines: list[str],
        evidence: dict,
        priority: str,
        confidence: Decimal,
        rule_id: str,
        action_url: str | None,
        recommendation_text: str,
    ) -> RecommendationResult:
        return RecommendationResult(
            recommendation_key=key,
            category=category,
            title=title,
            reason=reason,
            evidence=evidence,
            explanation=ExplanationEngine.for_recommendation(
                title=title,
                evidence_lines=evidence_lines,
                reasoning=reason,
                recommendation=recommendation_text,
            ),
            confidence=confidence,
            priority=priority,
            rule_id=rule_id,
            rule_version=RECOMMENDATION_ENGINE_VERSION,
            action_url=action_url,
        )
