"""Deterministic auto-ack eligibility — no LLM, inspectable reason codes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.services.operator_auto_ack.constants import (
    ALLOWLIST_ALERT_TYPES,
    AMBIGUOUS_FAILURE_CODES,
    EXCLUDED_ALERT_TYPES,
    EXCLUDED_FAILURE_CODES,
    SAFETY_LEVEL_ALLOWLIST,
    SAFETY_LEVEL_INELIGIBLE,
    SHADOW_ACTION_SKIP,
    SHADOW_ACTION_WOULD_ACK,
)
from app.services.publish_resilience import (
    META_PUBLISH_PLATFORMS,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
)


@dataclass(frozen=True)
class AutoAckDecision:
    eligible: bool
    reason_code: str
    safety_level: str
    shadow_action: str
    blocking_reason: str | None
    human_action_still_required: bool
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reason_code": self.reason_code,
            "safety_level": self.safety_level,
            "shadow_action": self.shadow_action,
            "blocking_reason": self.blocking_reason,
            "human_action_still_required": self.human_action_still_required,
            "evidence": dict(self.evidence),
        }


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


def build_state_fingerprint(
    alert: PublishOperatorAlert,
    attempt: PublishAttempt | None,
) -> str:
    """Stable-enough fingerprint for dedupe: skip identical re-evaluations."""
    attempt_part = "-"
    if attempt is not None:
        attempt_part = (
            f"{attempt.status}|{attempt.failure_code or '-'}|"
            f"{_iso(getattr(attempt, 'finished_at', None) or getattr(attempt, 'created_at', None))}"
        )
    return (
        f"{alert.state}|{alert.alert_type}|{alert.severity}|"
        f"{alert.occurrence_count}|{_iso(alert.latest_occurred_at)}|{attempt_part}"
    )


def evaluate_auto_ack_candidate(
    alert: PublishOperatorAlert,
    *,
    attempt: PublishAttempt | None,
    newer_success_exists: bool = False,
) -> AutoAckDecision:
    """Decide whether this alert would be a safe auto-ack candidate.

    Revalidation inputs (attempt, newer_success_exists) must be loaded from
    canonical DB state — never trust stale alert snapshot alone for eligibility.
    """
    base_evidence: dict[str, Any] = {
        "alert_id": str(alert.id),
        "tenant_id": str(alert.tenant_id),
        "client_id": str(alert.client_id) if alert.client_id else None,
        "alert_type": alert.alert_type,
        "alert_state": alert.state,
        "severity": alert.severity,
        "failure_code": alert.failure_code,
        "attempt_id": str(alert.attempt_id) if alert.attempt_id else None,
        "platform": (alert.platform or "").lower() or None,
        "occurrence_count": alert.occurrence_count,
        "attempt_status_snapshot": alert.attempt_status,
        "attempt_status_live": attempt.status if attempt is not None else None,
        "attempt_failure_code_live": (
            attempt.failure_code if attempt is not None else None
        ),
        "newer_success_exists": newer_success_exists,
        "fingerprint": build_state_fingerprint(alert, attempt),
    }

    def ineligible(reason: str, *, blocking: str | None = None) -> AutoAckDecision:
        return AutoAckDecision(
            eligible=False,
            reason_code=reason,
            safety_level=SAFETY_LEVEL_INELIGIBLE,
            shadow_action=SHADOW_ACTION_SKIP,
            blocking_reason=blocking or reason,
            human_action_still_required=alert.state in ("open", "acknowledged"),
            evidence=base_evidence,
        )

    if alert.state == "resolved":
        return ineligible("already_resolved")
    if alert.state == "acknowledged":
        return ineligible("already_acknowledged")
    if alert.state != "open":
        return ineligible("not_open")

    if (alert.severity or "").lower() == "critical":
        return ineligible("critical_severity")

    alert_type = (alert.alert_type or "").lower()
    if alert_type in EXCLUDED_ALERT_TYPES:
        return ineligible("alert_type_excluded", blocking=f"excluded_type:{alert_type}")
    if alert_type not in ALLOWLIST_ALERT_TYPES:
        return ineligible("allowlist_miss", blocking=f"not_allowlisted:{alert_type}")

    platform = (alert.platform or (attempt.platform if attempt else "") or "").lower()
    if platform in META_PUBLISH_PLATFORMS:
        return ineligible("meta_platform_excluded")

    # Prefer live attempt failure_code; fall back to alert snapshot.
    failure_code = (
        (attempt.failure_code if attempt is not None else None)
        or alert.failure_code
        or ""
    ).lower()
    if failure_code in EXCLUDED_FAILURE_CODES:
        return ineligible("unresolved_auth_or_permission", blocking=failure_code)
    if "credential_decrypt" in failure_code:
        return ineligible("credential_decryption_failed")

    if attempt is None:
        return ineligible("attempt_missing")

    live_status = (attempt.status or "").lower()
    if live_status == STATUS_OPERATOR_REVIEW:
        return ineligible("operator_review_status")
    if live_status == STATUS_IN_PROGRESS:
        return ineligible("attempt_in_progress")
    if live_status == STATUS_SUCCESS or newer_success_exists:
        # System resolve should clear these; do not shadow-ack bookkeeping races.
        return ineligible("underlying_success_stale")

    # Ambiguous Meta codes on a non-Meta path should still be excluded if present.
    if live_status == STATUS_OPERATOR_REVIEW or failure_code in AMBIGUOUS_FAILURE_CODES:
        # stale_in_progress alert with retrying uses publish_timeout on non-Meta —
        # allow only when status is retrying (system already owns recovery).
        if live_status != STATUS_RETRYING:
            return ineligible("ambiguous_meta_outcome", blocking=failure_code or live_status)

    if live_status != STATUS_RETRYING:
        return ineligible(
            "attempt_not_retrying",
            blocking=f"live_status:{live_status}",
        )

    # Allowlist path: warning + stale_in_progress + live retrying + non-Meta.
    if (alert.severity or "").lower() != "warning":
        return ineligible("severity_not_warning")

    return AutoAckDecision(
        eligible=True,
        reason_code="stale_in_progress_retrying_bookkeeping",
        safety_level=SAFETY_LEVEL_ALLOWLIST,
        shadow_action=SHADOW_ACTION_WOULD_ACK,
        blocking_reason=None,
        # Ack does not clear Workspace attention (open|acked both shown).
        human_action_still_required=True,
        evidence=base_evidence,
    )


def decision_for_cross_tenant() -> AutoAckDecision:
    return AutoAckDecision(
        eligible=False,
        reason_code="cross_tenant_denied",
        safety_level=SAFETY_LEVEL_INELIGIBLE,
        shadow_action=SHADOW_ACTION_SKIP,
        blocking_reason="cross_tenant_denied",
        human_action_still_required=False,
        evidence={},
    )
