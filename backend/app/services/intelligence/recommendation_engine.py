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

        score_low = counts.get("publishing.score_low", 0)
        critical_issues = counts.get("publishing.critical_issue_detected", 0)
        fit_low = counts.get("publishing.platform_fit_low", 0)
        if critical_issues >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="publishing.fix_critical_review_issues",
                    category="publishing",
                    title="Fix critical publishing review issues",
                    reason=(
                        f"{critical_issues} critical publishing review issue signal(s) "
                        f"in the last {SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{critical_issues} critical review issues"],
                    evidence={"critical_issue_detected": critical_issues},
                    priority="critical",
                    confidence=Decimal("0.940"),
                    rule_id="rule.publishing_critical_review_issues",
                    action_url="/content",
                    recommendation_text="Open content items with critical pre-publish review failures and resolve blockers.",
                )
            )
        elif score_low >= 2:
            results.append(
                RecommendationEngine._rec(
                    key="publishing.improve_publishing_score",
                    category="publishing",
                    title="Improve publishing quality scores",
                    reason=(
                        f"{score_low} low publishing-score signal(s) detected "
                        f"over {SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{score_low} low publishing scores"],
                    evidence={"score_low": score_low},
                    priority="high",
                    confidence=Decimal("0.900"),
                    rule_id="rule.publishing_score_low",
                    action_url="/content",
                    recommendation_text="Re-run Publishing Intelligence reviews and address caption, CTA, media, or platform-fit warnings.",
                )
            )
        if fit_low >= 2:
            results.append(
                RecommendationEngine._rec(
                    key="publishing.improve_platform_fit",
                    category="publishing",
                    title="Improve platform fit before publishing",
                    reason=(
                        f"{fit_low} platform-fit warning signal(s) in the last "
                        f"{SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{fit_low} platform-fit lows"],
                    evidence={"platform_fit_low": fit_low},
                    priority="medium",
                    confidence=Decimal("0.870"),
                    rule_id="rule.publishing_platform_fit_low",
                    action_url="/content",
                    recommendation_text="Adjust caption length, media, or hashtags for the target platforms.",
                )
            )

        variants_generated = counts.get("publishing.variant_generated", 0)
        variants_declined = counts.get("publishing.variant_score_declined", 0)
        variants_applied = counts.get("publishing.variant_applied", 0)
        optimizer_failed = counts.get("publishing.optimizer_failed", 0)
        if variants_generated >= 1 and variants_applied == 0:
            results.append(
                RecommendationEngine._rec(
                    key="publishing.review_platform_variants",
                    category="publishing",
                    title="Review deterministic platform variants",
                    reason=(
                        f"{variants_generated} platform variant(s) generated "
                        f"without an apply action in the last {SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{variants_generated} variants generated"],
                    evidence={"variant_generated": variants_generated},
                    priority="medium",
                    confidence=Decimal("0.860"),
                    rule_id="rule.publishing_review_platform_variants",
                    action_url="/content",
                    recommendation_text="Compare source and platform variants, then explicitly accept or apply a reviewed variant.",
                )
            )
        if variants_declined >= 2:
            results.append(
                RecommendationEngine._rec(
                    key="publishing.review_lower_scoring_variants",
                    category="publishing",
                    title="Review a lower-scoring platform variant",
                    reason=(
                        f"{variants_declined} variant score-decline signal(s) in the last "
                        f"{SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{variants_declined} score declines"],
                    evidence={"variant_score_declined": variants_declined},
                    priority="low",
                    confidence=Decimal("0.820"),
                    rule_id="rule.publishing_variant_score_declined",
                    action_url="/content",
                    recommendation_text="Lower score is advisory — review transformations and policy fit before applying.",
                )
            )
        if optimizer_failed >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="publishing.add_approved_templates",
                    category="publishing",
                    title="Add an approved CTA template",
                    reason=(
                        f"{optimizer_failed} optimizer failure signal(s) detected "
                        f"over {SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{optimizer_failed} optimizer failures"],
                    evidence={"optimizer_failed": optimizer_failed},
                    priority="medium",
                    confidence=Decimal("0.840"),
                    rule_id="rule.publishing_optimizer_failed",
                    action_url="/content",
                    recommendation_text="Add platform-ready hashtags or an approved CTA template, then regenerate variants after source changes.",
                )
            )

        # Governed AI recommendations (deterministic; never claim engagement improvement).
        ai_failed = counts.get("ai.content_adaptation_failed", 0)
        ai_factual = counts.get("ai.factual_validation_failed", 0)
        ai_quota = counts.get("ai.quota_exceeded", 0)
        ai_declined = counts.get("ai.variant_score_declined", 0)
        ai_applied = counts.get("ai.variant_applied", 0)
        ai_completed = counts.get("ai.content_adaptation_completed", 0)
        brand_published = counts.get("brand.profile_published", 0)

        if ai_factual >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="ai.review_protected_fact_changes",
                    category="publishing",
                    title="Review an AI variant with modified protected facts",
                    reason=(
                        f"{ai_factual} AI factual-validation failure signal(s) in the last "
                        f"{SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{ai_factual} factual validation failures"],
                    evidence={"ai_factual_validation_failed": ai_factual},
                    priority="high",
                    confidence=Decimal("0.900"),
                    rule_id="rule.ai_factual_validation_failed",
                    action_url="/content",
                    recommendation_text="Inspect protected-fact diffs and regenerate only after correcting source facts or Brand Profile claims.",
                )
            )
        if ai_failed >= 1 and brand_published == 0:
            results.append(
                RecommendationEngine._rec(
                    key="ai.publish_brand_profile",
                    category="brand",
                    title="Publish a Brand Profile before requesting AI adaptation",
                    reason="AI adaptation failures occurred without a recent Brand Profile publish signal.",
                    evidence_lines=["AI adaptation without brand.profile_published"],
                    evidence={"ai_failed": ai_failed, "brand_published": brand_published},
                    priority="medium",
                    confidence=Decimal("0.840"),
                    rule_id="rule.ai_brand_profile_required",
                    action_url="/settings/brand-profile",
                    recommendation_text="Publish an immutable Brand Profile version so AI adaptation uses approved tone and claim constraints.",
                )
            )
        if ai_declined >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="ai.review_lower_scoring_variant",
                    category="publishing",
                    title="Review a lower-scoring AI variant",
                    reason=(
                        f"{ai_declined} AI variant score-decline signal(s) in the last "
                        f"{SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{ai_declined} AI score declines"],
                    evidence={"ai_variant_score_declined": ai_declined},
                    priority="low",
                    confidence=Decimal("0.820"),
                    rule_id="rule.ai_variant_score_declined",
                    action_url="/content",
                    recommendation_text="Lower Publishing Score is advisory — review factual validation and hard readiness before applying.",
                )
            )
        if ai_quota >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="ai.resolve_quota_limit",
                    category="publishing",
                    title="Resolve AI quota limit",
                    reason=(
                        f"{ai_quota} AI quota-exceeded signal(s) in the last "
                        f"{SIGNAL_COUNT_LOOKBACK_DAYS} days."
                    ),
                    evidence_lines=[f"{ai_quota} quota blocks"],
                    evidence={"ai_quota_exceeded": ai_quota},
                    priority="medium",
                    confidence=Decimal("0.880"),
                    rule_id="rule.ai_quota_exceeded",
                    action_url="/settings/brand-profile",
                    recommendation_text="Wait for the quota window to reset or adjust tenant AI limits with an administrator.",
                )
            )
        if ai_completed >= 1 and ai_applied == 0:
            results.append(
                RecommendationEngine._rec(
                    key="ai.regenerate_after_source_change",
                    category="publishing",
                    title="Regenerate after source content changed",
                    reason="AI adaptations completed recently without an apply — confirm source fingerprint before applying stale variants.",
                    evidence_lines=[f"{ai_completed} AI completions", f"{ai_applied} AI applies"],
                    evidence={"ai_completed": ai_completed, "ai_applied": ai_applied},
                    priority="low",
                    confidence=Decimal("0.780"),
                    rule_id="rule.ai_stale_or_unapplied",
                    action_url="/content",
                    recommendation_text="If source captions changed, request a new AI adaptation; stale apply returns 409 Conflict.",
                )
            )

        # Campaign Planner recommendations (advisory; never schedule/publish).
        unassigned_high = counts.get("campaign.unassigned_slots_high", 0)
        blocked_slots = counts.get("campaign.conflicts_detected", 0)
        coverage_low = counts.get("campaign.coverage_low", 0)
        readiness_low = counts.get("campaign.readiness_low", 0)
        pillar_imbalance = counts.get("campaign.pillar_imbalance", 0)
        ai_plan_failed = counts.get("campaign.ai_plan_failed", 0)
        plan_generated = counts.get("campaign.plan_generated", 0)
        brand_published_for_campaign = counts.get("brand.profile_published", 0)

        if unassigned_high >= 1 or coverage_low >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="campaign.assign_unfilled_slots",
                    category="content",
                    title="Assign content to unfilled campaign slots",
                    reason=(
                        f"Campaign coverage/unassigned signals detected "
                        f"(unassigned_high={unassigned_high}, coverage_low={coverage_low})."
                    ),
                    evidence_lines=[
                        f"unassigned_slots_high={unassigned_high}",
                        f"coverage_low={coverage_low}",
                    ],
                    evidence={"unassigned_slots_high": unassigned_high, "coverage_low": coverage_low},
                    priority="high",
                    confidence=Decimal("0.880"),
                    rule_id="rule.campaign_unfilled_slots",
                    action_url="/campaign-planner",
                    recommendation_text="Open the campaign plan and assign eligible content or run auto-assign.",
                )
            )
        if blocked_slots >= 1 or readiness_low >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="campaign.resolve_blocked_accounts",
                    category="content",
                    title="Resolve blocked accounts for campaign slots",
                    reason="Campaign readiness/conflict signals indicate blocked or conflicted slots.",
                    evidence_lines=[
                        f"conflicts_detected={blocked_slots}",
                        f"readiness_low={readiness_low}",
                    ],
                    evidence={"conflicts_detected": blocked_slots, "readiness_low": readiness_low},
                    priority="high",
                    confidence=Decimal("0.900"),
                    rule_id="rule.campaign_blocked_accounts",
                    action_url="/integrations",
                    recommendation_text="Reconnect publishing accounts and clear hard readiness blockers before assignment.",
                )
            )
        if pillar_imbalance >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="campaign.balance_pillars",
                    category="content",
                    title="Add content for underrepresented pillar",
                    reason=f"{pillar_imbalance} pillar-imbalance signal(s) in the lookback window.",
                    evidence_lines=[f"pillar_imbalance={pillar_imbalance}"],
                    evidence={"pillar_imbalance": pillar_imbalance},
                    priority="medium",
                    confidence=Decimal("0.820"),
                    rule_id="rule.campaign_pillar_imbalance",
                    action_url="/campaign-planner",
                    recommendation_text="Generate or assign more content for under-weighted pillars.",
                )
            )
        if plan_generated >= 1 and coverage_low >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="campaign.complete_locale_coverage",
                    category="content",
                    title="Complete missing locale coverage",
                    reason="A campaign plan was generated with low coverage — check locale distribution.",
                    evidence_lines=[f"plan_generated={plan_generated}", f"coverage_low={coverage_low}"],
                    evidence={"plan_generated": plan_generated, "coverage_low": coverage_low},
                    priority="medium",
                    confidence=Decimal("0.800"),
                    rule_id="rule.campaign_locale_missing",
                    action_url="/campaign-planner",
                    recommendation_text="Ensure each campaign locale has slots and assignable content.",
                )
            )
        if readiness_low >= 1:
            results.append(
                RecommendationEngine._rec(
                    key="campaign.review_stale_variants",
                    category="content",
                    title="Review stale variants in campaign assignments",
                    reason="Low readiness signals suggest assigned content may be stale or incomplete.",
                    evidence_lines=[f"readiness_low={readiness_low}"],
                    evidence={"readiness_low": readiness_low},
                    priority="low",
                    confidence=Decimal("0.780"),
                    rule_id="rule.campaign_stale_content",
                    action_url="/content",
                    recommendation_text="Re-review assigned variants; Publishing Score is advisory only.",
                )
            )
        if blocked_slots >= 2:
            results.append(
                RecommendationEngine._rec(
                    key="campaign.reduce_same_day_conflicts",
                    category="content",
                    title="Reduce same-day campaign conflicts",
                    reason=f"{blocked_slots} conflict signal(s) detected across campaign plans.",
                    evidence_lines=[f"conflicts_detected={blocked_slots}"],
                    evidence={"conflicts_detected": blocked_slots},
                    priority="medium",
                    confidence=Decimal("0.840"),
                    rule_id="rule.campaign_same_day_conflicts",
                    action_url="/campaign-planner",
                    recommendation_text="Adjust slot times or redistribute same-day posts per platform.",
                )
            )
        if ai_plan_failed >= 1 and brand_published_for_campaign == 0:
            results.append(
                RecommendationEngine._rec(
                    key="campaign.publish_brand_profile_for_ai",
                    category="brand",
                    title="Publish Brand Profile before AI campaign planning",
                    reason="AI campaign plan failures occurred without a recent Brand Profile publish signal.",
                    evidence_lines=["campaign.ai_plan_failed without brand.profile_published"],
                    evidence={"ai_plan_failed": ai_plan_failed, "brand_published": brand_published_for_campaign},
                    priority="medium",
                    confidence=Decimal("0.850"),
                    rule_id="rule.campaign_brand_profile_for_ai",
                    action_url="/settings/brand-profile",
                    recommendation_text="Publish an immutable Brand Profile version, then retry AI plan proposal. Deterministic planning remains available.",
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
