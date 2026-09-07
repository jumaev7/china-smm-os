"""Canonical manual publish-retry eligibility / safety policy (Phase 3C.1A).

Single authority for:
- Operator Workspace ``actions[]`` derivation (should Retry be offered?)
- Operator Workspace / admin manual retry execution (is Retry still allowed?)

Automatic scheduled retries intentionally do NOT use this module.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.services.publish_resilience import (
    AMBIGUOUS_META_FAILURE_CODES,
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    PublishResilienceService,
    is_meta_publish_platform,
    utc_now,
)
from app.services.publishing_destination_registry import (
    DESTINATION_TRUTH,
    META_ACCOUNT_BLOCK_STATUSES,
    facebook_live_smoke_enabled,
    instagram_live_smoke_enabled,
)

logger = logging.getLogger(__name__)

SafetyClass = Literal[
    "SAFE_MANUAL_RETRY",
    "CONDITIONAL_MANUAL_RETRY",
    "OPERATOR_REVIEW",
    "PERMANENT_BLOCK",
]

ConfirmationTier = Literal["low", "medium", "high"]

# Content statuses PublishService will accept for a fresh manual publish.
_PUBLISHABLE_CONTENT_STATUSES = frozenset({
    "approved",
    "scheduled",
    "failed",
    "partial_failed",
})

# Attempt statuses that may proceed past the status gate (still subject to
# failure-code / live-state / budget / platform checks).
_RETRYABLE_ATTEMPT_STATUSES = frozenset({
    STATUS_FAILED,
    STATUS_RETRYING,
    STATUS_EXHAUSTED,
})

# Permanent / repair-required failure codes — never one-click retry.
_PERMANENT_FAILURE_CODES = frozenset({
    "auth_or_permission",
    "credential_decryption_failed",
    "validation_error",
    "unsupported_media",
    "publish_blocked",
    "account_unavailable",
    "stale_after_success",
    "max_attempts_exhausted",
})

# Ambiguous / operator-review outcomes — never one-click, never admin-bypass.
# Phase 3C.1A final gate: Telegram ``rate_limited`` / ``provider_transient`` are
# ALSO here — the publish adapter does not prove a definitive pre-accept /
# provider-rejection boundary for those stored codes (see classify + telegram_publisher).
_OPERATOR_REVIEW_FAILURE_CODES = frozenset({
    "publish_timeout",
    "connection_error",
    "stale_in_progress",
    "provider_outcome_ambiguous",
    "provider_unavailable",  # 5xx — duplicate safety unproven
    "adapter_failure",  # unless proven pre-I/O (not proven in stored rows)
    "concurrent_claim",
    "rate_limited",  # Telegram Bot API 429 is not structured into this code today
    "provider_transient",  # Meta-text path only; never proven safe for Telegram writes
})

# Known failure codes in the publish taxonomy (anything else → unknown → block).
_KNOWN_FAILURE_CODES = (
    _PERMANENT_FAILURE_CODES
    | _OPERATOR_REVIEW_FAILURE_CODES
    | AMBIGUOUS_META_FAILURE_CODES
)

# CONDITIONAL allowlist — EMPTY in 3C.1A after classification evidence review.
# Prefer an empty allowed set over unsafe duplicate-risk retries.
# SAFE_MANUAL_RETRY also stays empty.
_CONDITIONAL_TELEGRAM_CODES: frozenset[str] = frozenset()

_MOCK_PLATFORMS = frozenset({
    platform
    for platform, meta in DESTINATION_TRUTH.items()
    if meta.get("global_status") == "mock"
})


@dataclass(frozen=True)
class ManualRetryLiveState:
    """Optional live projection. Missing fields fail closed when needed to allow."""

    has_live_success: bool | None = None
    content_status: str | None = None
    current_publish_version: str | None = None
    account_status: str | None = None
    now: datetime | None = None


@dataclass(frozen=True)
class ManualRetryEligibility:
    allowed: bool
    reason_code: str
    safety_class: SafetyClass
    confirmation_tier: ConfirmationTier
    external_side_effect: bool
    operator_message: str
    mobile_eligible: bool

    def as_tuple(self) -> tuple[bool, str | None]:
        """Compat shape for older (allowed, reason) callers."""
        if self.allowed:
            return True, None
        return False, self.operator_message


def _deny(
    *,
    reason_code: str,
    safety_class: SafetyClass,
    operator_message: str,
    confirmation_tier: ConfirmationTier = "high",
) -> ManualRetryEligibility:
    return ManualRetryEligibility(
        allowed=False,
        reason_code=reason_code,
        safety_class=safety_class,
        confirmation_tier=confirmation_tier,
        external_side_effect=True,
        operator_message=operator_message,
        mobile_eligible=False,
    )


def _allow_conditional(*, reason_code: str, operator_message: str) -> ManualRetryEligibility:
    return ManualRetryEligibility(
        allowed=True,
        reason_code=reason_code,
        safety_class="CONDITIONAL_MANUAL_RETRY",
        confirmation_tier="high",
        external_side_effect=True,
        operator_message=operator_message,
        mobile_eligible=False,
    )


def _normalize_source(source: str | None) -> str:
    value = (source or "workspace").strip().lower()
    if value in ("web", "workspace", "operator_workspace"):
        return "workspace"
    if value in ("mobile", "admin", "api"):
        return value
    return "workspace"


def _normalize_role(actor_role: str | None) -> str | None:
    if actor_role is None:
        return None
    return actor_role.strip().lower() or None


def _platform_execution_block(platform: str | None) -> ManualRetryEligibility | None:
    plat = (platform or "").strip().lower()
    if not plat:
        return _deny(
            reason_code="platform_execution_unavailable",
            safety_class="PERMANENT_BLOCK",
            operator_message="Publish platform is missing — retry is blocked",
        )
    if plat in _MOCK_PLATFORMS:
        return _deny(
            reason_code="mock_platform",
            safety_class="PERMANENT_BLOCK",
            operator_message=f"{plat.title()} publishing is mock-only — retry is not meaningful",
        )
    if plat == "facebook" and not facebook_live_smoke_enabled():
        return _deny(
            reason_code="platform_execution_unavailable",
            safety_class="PERMANENT_BLOCK",
            operator_message="Facebook live publish is disabled — retry would not create a real post",
        )
    if plat == "instagram" and not instagram_live_smoke_enabled():
        return _deny(
            reason_code="platform_execution_unavailable",
            safety_class="PERMANENT_BLOCK",
            operator_message="Instagram live publish is disabled — retry would not create a real post",
        )
    return None


def _classify_failure_code(
    failure_code: str | None,
    *,
    platform: str | None,
) -> ManualRetryEligibility | None:
    """Return a deny result for non-conditional codes; None if code may be conditional."""
    if failure_code is None or not str(failure_code).strip():
        return _deny(
            reason_code="failure_code_null",
            safety_class="OPERATOR_REVIEW",
            operator_message="Historical failure has no failure code — operator review required",
        )

    code = str(failure_code).strip().lower()

    if code not in _KNOWN_FAILURE_CODES:
        return _deny(
            reason_code="failure_code_unknown",
            safety_class="OPERATOR_REVIEW",
            operator_message=f"Unrecognized failure code ({code}) — operator review required",
        )

    if code in _PERMANENT_FAILURE_CODES:
        messages = {
            "auth_or_permission": "Auth or permission failure — repair the integration before retry",
            "credential_decryption_failed": "Credential decryption failed — repair secrets before retry",
            "validation_error": "Validation failure — fix content before retry",
            "unsupported_media": "Unsupported media — fix media before retry",
            "publish_blocked": "Publish is blocked by configuration — retry is not available",
            "account_unavailable": "Account unavailable until the integration is repaired",
            "stale_after_success": "A live success already exists for this destination",
            "max_attempts_exhausted": "Retry budget exhausted — manual override is not available yet",
        }
        return _deny(
            reason_code=code,
            safety_class="PERMANENT_BLOCK",
            operator_message=messages.get(code, "Permanent publish failure — retry blocked"),
        )

    if code in _OPERATOR_REVIEW_FAILURE_CODES or code in AMBIGUOUS_META_FAILURE_CODES:
        return _deny(
            reason_code="ambiguous_provider_outcome" if code != "stale_in_progress" else code,
            safety_class="OPERATOR_REVIEW",
            operator_message=(
                "Ambiguous provider outcome requires operator verification before retry"
            ),
        )

    # Meta platforms: even "conditional" codes are unproven for duplicate safety.
    if is_meta_publish_platform(platform):
        return _deny(
            reason_code="ambiguous_provider_outcome",
            safety_class="OPERATOR_REVIEW",
            operator_message=(
                "Meta publish outcomes require operator verification before manual retry"
            ),
        )

    plat = (platform or "").strip().lower()
    if plat == "telegram" and code in _CONDITIONAL_TELEGRAM_CODES:
        return None  # proceed to live-state / budget gates

    return _deny(
        reason_code="ambiguous_provider_outcome",
        safety_class="OPERATOR_REVIEW",
        operator_message="Failure class is not proven safe for one-click retry",
    )


def evaluate_manual_retry_eligibility(
    attempt: Any,
    live_state: ManualRetryLiveState | None = None,
    *,
    source: str = "workspace",
    actor_role: str | None = None,
) -> ManualRetryEligibility:
    """Canonical manual retry safety policy.

    ``mobile_eligible`` is always False in Phase 3C.1A.
    ``source=mobile`` is never eligibility authority — always denied.
    Admin/operator roles cannot bypass OPERATOR_REVIEW or PERMANENT_BLOCK.
    """
    del actor_role  # role cannot widen safety; retained for call-site clarity / future tiers
    src = _normalize_source(source)
    live = live_state or ManualRetryLiveState()
    status = getattr(attempt, "status", None)
    platform = getattr(attempt, "platform", None)
    failure_code = getattr(attempt, "failure_code", None)
    attempt_number = int(getattr(attempt, "attempt_number", 1) or 1)
    external_post_id = getattr(attempt, "external_post_id", None)
    next_retry_at = getattr(attempt, "next_retry_at", None)
    publish_version = getattr(attempt, "publish_version", None)

    # ── Source / mobile hard block ──────────────────────────────────────────
    if src == "mobile":
        return _deny(
            reason_code="mobile_retry_not_enabled",
            safety_class="PERMANENT_BLOCK",
            operator_message="Mobile publish retry is not enabled",
        )

    # ── Status gates ────────────────────────────────────────────────────────
    if status == STATUS_OPERATOR_REVIEW:
        return _deny(
            reason_code="operator_review_required",
            safety_class="OPERATOR_REVIEW",
            operator_message="Ambiguous publish outcome requires operator verification before retry",
        )
    if status == STATUS_IN_PROGRESS:
        return _deny(
            reason_code="in_progress",
            safety_class="PERMANENT_BLOCK",
            operator_message="Publish is currently in progress",
        )
    if status == STATUS_SUCCESS and external_post_id:
        return _deny(
            reason_code="live_success_exists",
            safety_class="PERMANENT_BLOCK",
            operator_message="Destination already published — retry would create a duplicate",
        )
    if status == STATUS_SUCCESS:
        return _deny(
            reason_code="live_success_exists",
            safety_class="PERMANENT_BLOCK",
            operator_message="Attempt already succeeded",
        )
    if status not in _RETRYABLE_ATTEMPT_STATUSES:
        return _deny(
            reason_code="status_not_retryable",
            safety_class="PERMANENT_BLOCK",
            operator_message=f"Retry not available for status={status}",
        )

    now = live.now or utc_now()
    if status == STATUS_RETRYING and next_retry_at is not None:
        due_at = next_retry_at
        if getattr(due_at, "tzinfo", None) is None:
            # Treat naive as UTC for comparison safety.
            from datetime import timezone
            due_at = due_at.replace(tzinfo=timezone.utc)
        if due_at > now:
            return _deny(
                reason_code="auto_retry_scheduled",
                safety_class="PERMANENT_BLOCK",
                operator_message=f"Automatic retry already scheduled for {due_at.isoformat()}",
            )

    # ── Retry budget (no unlimited loops; no exhausted override without command model)
    max_attempts = PublishResilienceService.max_attempts()
    if status == STATUS_EXHAUSTED or attempt_number >= max_attempts:
        return _deny(
            reason_code="retry_budget_exhausted",
            safety_class="PERMANENT_BLOCK",
            operator_message=(
                "Retry budget exhausted — begin_attempt would reject with max_attempts_exhausted"
            ),
        )

    # ── Platform / execution availability ───────────────────────────────────
    platform_block = _platform_execution_block(platform)
    if platform_block is not None:
        return platform_block

    account_status = live.account_status
    if account_status is None:
        account = getattr(attempt, "account", None)
        if account is not None:
            account_status = getattr(account, "status", None)
    if account_status and account_status in META_ACCOUNT_BLOCK_STATUSES:
        return _deny(
            reason_code="account_unavailable",
            safety_class="PERMANENT_BLOCK",
            operator_message="Account unavailable until the integration is repaired",
        )

    # ── Failure-code taxonomy (fail closed) ─────────────────────────────────
    code_block = _classify_failure_code(failure_code, platform=platform)
    if code_block is not None:
        return code_block

    # ── Live state revalidation ─────────────────────────────────────────────
    if live.has_live_success is True:
        return _deny(
            reason_code="live_success_exists",
            safety_class="PERMANENT_BLOCK",
            operator_message="Destination already published — retry blocked to prevent duplicates",
        )
    # Unknown live success → fail closed (false-negative omission is acceptable).
    if live.has_live_success is None:
        return _deny(
            reason_code="live_success_unknown",
            safety_class="OPERATOR_REVIEW",
            operator_message="Live publish state could not be confirmed — retry withheld",
        )

    content_status = live.content_status
    if content_status is not None and content_status not in _PUBLISHABLE_CONTENT_STATUSES:
        return _deny(
            reason_code="incompatible_content_state",
            safety_class="PERMANENT_BLOCK",
            operator_message=f"Content status ({content_status}) is incompatible with publishing",
        )

    if (
        live.current_publish_version is not None
        and publish_version is not None
        and live.current_publish_version != publish_version
    ):
        return _deny(
            reason_code="stale_publish_version",
            safety_class="PERMANENT_BLOCK",
            operator_message="Content publish version changed — retry this snapshot is blocked",
        )

    # Conditional path reached only for proven-safe telegram codes with live_success=False.
    result = _allow_conditional(
        reason_code="conditional_manual_retry",
        operator_message="Manual retry allowed under conditional safety policy",
    )
    logger.info(
        "manual_retry_eligibility allowed=true reason=%s safety=%s platform=%s "
        "failure_code=%s status=%s source=%s",
        result.reason_code,
        result.safety_class,
        platform,
        failure_code,
        status,
        src,
    )
    return result


def eligibility_from_attention_metadata(
    *,
    status: str | None,
    metadata: dict | None,
    platform: str | None = None,
    source: str = "workspace",
    actor_role: str | None = None,
) -> ManualRetryEligibility:
    """Snapshot evaluator for Workspace ``actions[]`` (no ORM row required)."""
    meta = metadata or {}
    attempt = _SnapshotAttempt(
        status=status,
        platform=platform or meta.get("platform"),
        failure_code=meta.get("failure_code"),
        attempt_number=int(meta.get("attempt_number") or 1),
        external_post_id=meta.get("external_post_id"),
        publish_version=meta.get("publish_version"),
        next_retry_at=_parse_optional_dt(meta.get("next_retry_at")),
        account_status=meta.get("account_status"),
    )
    has_live = meta.get("has_live_success")
    if has_live is None:
        live_flag: bool | None = None
    else:
        live_flag = bool(has_live)

    live = ManualRetryLiveState(
        has_live_success=live_flag,
        content_status=meta.get("content_status"),
        current_publish_version=meta.get("current_publish_version"),
        account_status=meta.get("account_status"),
    )
    return evaluate_manual_retry_eligibility(
        attempt,
        live,
        source=source,
        actor_role=actor_role,
    )


@dataclass
class _SnapshotAttempt:
    status: str | None
    platform: str | None = None
    failure_code: str | None = None
    attempt_number: int = 1
    external_post_id: str | None = None
    publish_version: str | None = None
    next_retry_at: datetime | None = None
    account_status: str | None = None
    account: Any = None


def _parse_optional_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


async def build_manual_retry_live_state(
    db: Any,
    attempt: Any,
    *,
    content: Any | None = None,
) -> ManualRetryLiveState:
    """Load the live projection used by execution-time revalidation."""
    from app.services.publish_resilience import compute_publish_version

    has_live: bool | None = False
    key = getattr(attempt, "idempotency_key", None)
    if key:
        prior = await PublishResilienceService.find_live_success(db, idempotency_key=key)
        has_live = prior is not None
    else:
        # Without an idempotency key we cannot prove absence of a live success.
        has_live = None

    content_status = getattr(content, "status", None) if content is not None else None
    current_version = None
    if content is not None:
        try:
            current_version = compute_publish_version(content)
        except Exception:
            current_version = None

    account_status = None
    account = getattr(attempt, "account", None)
    if account is not None:
        account_status = getattr(account, "status", None)

    return ManualRetryLiveState(
        has_live_success=has_live,
        content_status=content_status,
        current_publish_version=current_version,
        account_status=account_status,
        now=utc_now(),
    )


def log_manual_retry_denied(
    eligibility: ManualRetryEligibility,
    *,
    attempt_id: Any = None,
    tenant_id: Any = None,
    actor_id: Any = None,
    source: str | None = None,
) -> None:
    """Structured application log for denied manual retries (no secrets)."""
    logger.info(
        "manual_retry_denied attempt_id=%s tenant_id=%s actor_id=%s source=%s "
        "reason_code=%s safety_class=%s",
        attempt_id,
        tenant_id,
        actor_id,
        source,
        eligibility.reason_code,
        eligibility.safety_class,
    )
