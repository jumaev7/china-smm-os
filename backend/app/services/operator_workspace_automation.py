"""Deterministic automation candidate classification for Operator Workspace.

Advisory only — does NOT enable autonomous execution. Safety levels and scores
are code/config driven (never LLM-decided).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AutomationLevel = Literal["A", "B", "C", "D"]

# Levels:
# A — SAFE AUTO (very low side-effect; still not enabled)
# B — AUTO WITH GUARDS (needs eligibility / rate limits / idempotency)
# C — HUMAN CONFIRMATION (recommend + explicit confirm)
# D — MANUAL ONLY (never autonomous)


@dataclass(frozen=True)
class AutomationCandidate:
    action_key: str
    level: AutomationLevel
    rationale: str
    external_side_effects: str
    idempotency: str
    duplicate_risk: str
    tenant_security_risk: str
    rollback: str
    prerequisites: tuple[str, ...]
    # Scoring weights (inspectable); higher = more automation-ready within level.
    base_score: int


# Explicit matrix — keep inspectable and complete for Phase 1 + foreseeable actions.
AUTOMATION_CANDIDATES: tuple[AutomationCandidate, ...] = (
    AutomationCandidate(
        action_key="acknowledge_alert",
        level="A",
        rationale=(
            "Internal state transition only; no provider write, no publish, "
            "no client impersonation. Already idempotent when already acknowledged."
        ),
        external_side_effects="None (operator alert row only)",
        idempotency="Safe to re-run; acknowledged → acknowledged is a no-op",
        duplicate_risk="None",
        tenant_security_risk="Low — tenant/client scoped alert row",
        rollback="Re-open not automatic; low impact (ack is informational)",
        prerequisites=(
            "Kill switch flag",
            "Rate limit per tenant",
            "Only open→acknowledged",
            "Stable success rate in metrics window",
        ),
        base_score=92,
    ),
    AutomationCandidate(
        action_key="resolve_alert",
        level="C",
        rationale=(
            "Removes item from the attention queue permanently; false resolve "
            "hides real incidents. Prefer human confirmation until false-positive "
            "rate is proven low."
        ),
        external_side_effects="None to providers; mutates alert lifecycle",
        idempotency="Resolved → resolved is idempotent",
        duplicate_risk="None",
        tenant_security_risk="Low",
        rollback="Can re-open via domain tools; not automatic",
        prerequisites=(
            "Human confirmation UI retained",
            "Optional auto-resolve only when linked publish succeeds (already exists)",
        ),
        base_score=55,
    ),
    AutomationCandidate(
        action_key="retry_publish_known_safe",
        level="B",
        rationale=(
            "Transient/exhausted failures with deterministic eligibility may eventually "
            "auto-retry with guards. Must never cover operator_review, in_progress, "
            "or live success."
        ),
        external_side_effects="Provider publish attempt (external write)",
        idempotency="Guarded by idempotency_key + live-success check",
        duplicate_risk="Medium — mitigated by live-success / external_post_id guards",
        tenant_security_risk="Medium — wrong-tenant retry would be severe (must keep scope)",
        rollback="Cannot unpublish automatically; recovery is operator_review / manual",
        prerequisites=(
            "Workspace eligibility unchanged (failed|exhausted|due retrying only)",
            "Failure-code allowlist (transient only)",
            "Idempotency + live-success guard",
            "Per-destination rate limit / cooldown",
            "Kill switch",
            "Metrics: high success, low duplicate incidents",
        ),
        base_score=70,
    ),
    AutomationCandidate(
        action_key="retry_publish_exhausted",
        level="B",
        rationale=(
            "Exhausted retries often need a deliberate operator decision; still "
            "eligible for guarded auto-retry after cooldown if failure is known-safe."
        ),
        external_side_effects="Provider publish attempt",
        idempotency="Same as known-safe retry",
        duplicate_risk="Medium",
        tenant_security_risk="Medium",
        rollback="Weak — cannot unpublish",
        prerequisites=(
            "Cooldown after exhaustion",
            "Failure-code allowlist",
            "Same guards as retry_publish_known_safe",
        ),
        base_score=62,
    ),
    AutomationCandidate(
        action_key="operator_review_retry",
        level="D",
        rationale=(
            "Ambiguous Meta outcomes require human verification. Workspace already "
            "blocks one-click retry; must remain non-auto forever."
        ),
        external_side_effects="Provider publish — duplicate risk if already live",
        idempotency="Ambiguous — outcome may already be published",
        duplicate_risk="High",
        tenant_security_risk="High if wrong decision",
        rollback="Weak",
        prerequisites=("Never automate",),
        base_score=5,
    ),
    AutomationCandidate(
        action_key="approve_content",
        level="C",
        rationale=(
            "Starts client review / may send Telegram preview. Not client approval, "
            "but still a meaningful workflow transition that operators should confirm."
        ),
        external_side_effects="May send Telegram client preview",
        idempotency="Already-approved is idempotent",
        duplicate_risk="Low for status; medium for duplicate Telegram preview",
        tenant_security_risk="Medium — wrong content approval",
        rollback="Status can be walked back manually; Telegram preview cannot be unsent",
        prerequisites=(
            "Human confirmation",
            "Never bypass client_review",
            "No auto-approve from drafts without policy",
        ),
        base_score=48,
    ),
    AutomationCandidate(
        action_key="automation_failed_job_requeue",
        level="B",
        rationale=(
            "Requeue of failed (non dead-letter) jobs can be guarded if error category "
            "is transient and attempt budget remains."
        ),
        external_side_effects="Depends on automation flow (may trigger downstream work)",
        idempotency="Requeue creates a new job with generation tracking",
        duplicate_risk="Medium — duplicate side effects if flow is not idempotent",
        tenant_security_risk="Medium",
        rollback="Cancel new job if still scheduled",
        prerequisites=(
            "Error-category allowlist",
            "Max requeue generation",
            "Tenant scope",
            "Kill switch",
        ),
        base_score=58,
    ),
    AutomationCandidate(
        action_key="automation_dead_letter_replay",
        level="D",
        rationale="Dead-letter implies repeated failure; replay must stay manual.",
        external_side_effects="Depends on flow — potentially high",
        idempotency="Weak without careful payload inspection",
        duplicate_risk="High",
        tenant_security_risk="High",
        rollback="Weak",
        prerequisites=("Never automate", "Manual investigation required"),
        base_score=8,
    ),
    AutomationCandidate(
        action_key="integration_health_refresh",
        level="A",
        rationale="Read/refresh health checks have no credential mutation and low risk.",
        external_side_effects="Provider read-only health/token introspection at most",
        idempotency="Safe",
        duplicate_risk="None",
        tenant_security_risk="Low",
        rollback="N/A",
        prerequisites=("Read-only provider calls only", "Rate limit"),
        base_score=88,
    ),
    AutomationCandidate(
        action_key="integration_health_local_recovery",
        level="A",
        rationale=(
            "Clearing stale/degraded diagnostic state after a successful read check "
            "only mutates local health metadata, never provider credentials."
        ),
        external_side_effects="None (local diagnostic state only)",
        idempotency="Safe",
        duplicate_risk="None",
        tenant_security_risk="Low",
        rollback="N/A",
        prerequisites=("Successful read-only health check",),
        base_score=90,
    ),
    AutomationCandidate(
        action_key="integration_provider_read_retry",
        level="A",
        rationale=(
            "Retrying a timed-out/read-failed provider health probe is safe when "
            "bounded by backoff and concurrency limits."
        ),
        external_side_effects="Provider read-only API call",
        idempotency="Safe",
        duplicate_risk="Low (rate-limit aware)",
        tenant_security_risk="Low",
        rollback="N/A",
        prerequisites=("Exponential backoff", "Per-integration lock", "No writes"),
        base_score=82,
    ),
    AutomationCandidate(
        action_key="oauth_reconnect",
        level="D",
        rationale="Credential/OAuth changes require human consent and interactive flows.",
        external_side_effects="OAuth credential mutation",
        idempotency="Interactive",
        duplicate_risk="N/A",
        tenant_security_risk="Critical",
        rollback="Revoke tokens manually",
        prerequisites=("Never automate",),
        base_score=2,
    ),
    AutomationCandidate(
        action_key="permission_grant",
        level="D",
        rationale="Permission/scope grants require interactive user consent.",
        external_side_effects="OAuth consent / provider permission change",
        idempotency="Interactive",
        duplicate_risk="N/A",
        tenant_security_risk="Critical",
        rollback="Revoke permissions manually",
        prerequisites=("Never automate",),
        base_score=2,
    ),
    AutomationCandidate(
        action_key="webhook_mutation",
        level="D",
        rationale="Webhook URL/secret changes alter inbound traffic routing; keep manual.",
        external_side_effects="Provider webhook configuration mutation",
        idempotency="Weak without careful verification",
        duplicate_risk="High (missed or duplicated events)",
        tenant_security_risk="High",
        rollback="Restore previous webhook config",
        prerequisites=("Never automate in Phase 1", "Human confirmation later"),
        base_score=5,
    ),
    AutomationCandidate(
        action_key="credential_rotation",
        level="D",
        rationale="Credential rotation mutates secrets and requires human authorization.",
        external_side_effects="Token/secret mutation",
        idempotency="Interactive",
        duplicate_risk="N/A",
        tenant_security_risk="Critical",
        rollback="Restore prior credential out-of-band",
        prerequisites=("Never automate",),
        base_score=1,
    ),
    AutomationCandidate(
        action_key="telegram_failed_event_replay",
        level="C",
        rationale=(
            "Replaying failed webhook events can create duplicate CRM/content side "
            "effects; recommend + confirm only."
        ),
        external_side_effects="May create/update domain records from Telegram payload",
        idempotency="Depends on ingestion handlers",
        duplicate_risk="Medium–High",
        tenant_security_risk="Medium (platform-global events; admin-only today)",
        rollback="Weak",
        prerequisites=("Human confirmation", "Dedup keys", "Admin-only"),
        base_score=35,
    ),
    AutomationCandidate(
        action_key="schedule_correction",
        level="C",
        rationale="Correcting schedules changes when content goes live; needs confirmation.",
        external_side_effects="May trigger future publish",
        idempotency="Last-write wins on scheduled_for",
        duplicate_risk="Low if publish still gated",
        tenant_security_risk="Medium",
        rollback="Reschedule again",
        prerequisites=("Human confirmation", "Preserve approval gates"),
        base_score=40,
    ),
    AutomationCandidate(
        action_key="client_approval",
        level="D",
        rationale="Operators must never impersonate client legal/approval consent.",
        external_side_effects="Marks client approval; may unblock publish",
        idempotency="Status transition",
        duplicate_risk="N/A",
        tenant_security_risk="Critical — consent/legal",
        rollback="Weak legally even if status reverted",
        prerequisites=("Never automate", "Never operator-impersonate"),
        base_score=0,
    ),
    AutomationCandidate(
        action_key="social_provider_publishing",
        level="D",
        rationale="Autonomous social sends are explicitly out of scope permanently.",
        external_side_effects="Live social posts",
        idempotency="Provider-dependent",
        duplicate_risk="Critical",
        tenant_security_risk="Critical",
        rollback="Cannot unpublish reliably",
        prerequisites=("Never automate from Workspace",),
        base_score=0,
    ),
    AutomationCandidate(
        action_key="deletes",
        level="D",
        rationale="Destructive; permanent data loss risk.",
        external_side_effects="Data destruction / provider deletes",
        idempotency="Destructive",
        duplicate_risk="N/A",
        tenant_security_risk="Critical",
        rollback="Often impossible",
        prerequisites=("Never automate",),
        base_score=0,
    ),
    AutomationCandidate(
        action_key="billing_payment_actions",
        level="D",
        rationale="Financial mutations must remain human-controlled.",
        external_side_effects="Payment / subscription changes",
        idempotency="Provider-dependent",
        duplicate_risk="High financial",
        tenant_security_risk="Critical",
        rollback="Refunds/chargebacks only",
        prerequisites=("Never automate from Workspace",),
        base_score=0,
    ),
)

_BY_KEY = {c.action_key: c for c in AUTOMATION_CANDIDATES}

# Workspace Phase 1 action_id → candidate key(s) for scoring UI.
WORKSPACE_ACTION_CANDIDATE_KEYS: dict[str, str] = {
    "acknowledge_alert": "acknowledge_alert",
    "resolve_alert": "resolve_alert",
    "retry_publish": "retry_publish_known_safe",
    "approve_content": "approve_content",
}

# Hard rules that must never become auto-candidates regardless of score.
NEVER_AUTO_ACTION_KEYS = frozenset({
    "operator_review_retry",
    "oauth_reconnect",
    "automation_dead_letter_replay",
    "client_approval",
    "social_provider_publishing",
    "deletes",
    "billing_payment_actions",
})


def get_candidate(action_key: str) -> AutomationCandidate | None:
    return _BY_KEY.get(action_key)


def list_candidates() -> list[AutomationCandidate]:
    return list(AUTOMATION_CANDIDATES)


def is_never_auto(action_key: str) -> bool:
    return action_key in NEVER_AUTO_ACTION_KEYS


def score_candidate(
    action_key: str,
    *,
    frequency: int = 0,
    success_rate: float | None = None,
    evidence_count: int = 0,
) -> dict:
    """Deterministic advisory score. Does not enable automation.

    Factors (additive, capped 0–100):
      + base_score from matrix
      + min(frequency, 20)  (operator use)
      + success_rate bonus (0–10) when evidence_count >= 10
      − 40 if NEVER_AUTO
      − 15 if level D
      − 5 if evidence_count < 5 (insufficient history)
    """
    cand = get_candidate(action_key)
    if cand is None:
        return {
            "action_key": action_key,
            "level": None,
            "score": None,
            "available": False,
            "reason": "unknown_action",
        }

    score = float(cand.base_score)
    score += min(max(frequency, 0), 20)

    if evidence_count >= 10 and success_rate is not None:
        # Map 0..1 → 0..10
        score += max(0.0, min(1.0, success_rate)) * 10.0
    elif evidence_count < 5:
        score -= 5.0

    if is_never_auto(action_key) or cand.level == "D":
        score = min(score, 15.0)
        score -= 40.0 if is_never_auto(action_key) else 15.0

    score = max(0.0, min(100.0, score))
    return {
        "action_key": action_key,
        "level": cand.level,
        "score": round(score, 1),
        "available": True,
        "auto_eligible": False,  # never true in this task
        "never_auto": is_never_auto(action_key),
        "rationale": cand.rationale,
        "prerequisites": list(cand.prerequisites),
        "evidence_count": evidence_count,
        "frequency": frequency,
        "success_rate": success_rate,
    }


def rank_candidates(
    action_stats: dict[str, dict] | None = None,
) -> list[dict]:
    """Rank all candidates by advisory score (desc), then action_key."""
    action_stats = action_stats or {}
    ranked: list[dict] = []
    for cand in AUTOMATION_CANDIDATES:
        stats = action_stats.get(cand.action_key) or action_stats.get(
            WORKSPACE_ACTION_CANDIDATE_KEYS.get(cand.action_key, ""),
        ) or {}
        # Map workspace action stats onto candidate keys.
        if not stats:
            # retry_publish maps to known_safe candidate for scoring display
            for ws_action, key in WORKSPACE_ACTION_CANDIDATE_KEYS.items():
                if key == cand.action_key and ws_action in action_stats:
                    stats = action_stats[ws_action]
                    break
        ranked.append(
            score_candidate(
                cand.action_key,
                frequency=int(stats.get("total") or 0),
                success_rate=stats.get("success_rate"),
                evidence_count=int(stats.get("total") or 0),
            ),
        )
    ranked.sort(key=lambda r: (-(r.get("score") or 0), r["action_key"]))
    return ranked
