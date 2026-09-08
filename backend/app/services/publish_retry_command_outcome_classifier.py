"""Provider-agnostic outcome classifier for retry-command D2-A.

Normalizes fake/provider port results into exactly three post-barrier outcomes:

  SUCCESS | DEFINITIVE_FAILURE | AMBIGUOUS

There is no RETRY / RETRYING / TRANSIENT_RETRY outcome after the write barrier.
Success without an authoritative ``external_post_id`` is AMBIGUOUS.
Unknown / malformed / exception inputs are AMBIGUOUS (fail closed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.services.publish_retry_command_provider_port import ProviderExecutionResult

NormalizedOutcome = Literal["SUCCESS", "DEFINITIVE_FAILURE", "AMBIGUOUS"]

# Command-path failure codes (forensic; not auto-retry selectors).
FAILURE_CODE_AMBIGUOUS = "retry_command_provider_ambiguous"
FAILURE_CODE_DEFINITIVE = "retry_command_provider_failed"
FAILURE_CODE_MISSING_EXTERNAL_ID = "retry_command_success_missing_external_id"
FAILURE_CODE_MALFORMED = "retry_command_provider_malformed"
FAILURE_CODE_EXCEPTION = "retry_command_provider_exception"
FAILURE_CODE_TIMEOUT = "retry_command_provider_timeout"
FAILURE_CODE_FINALIZE_FAILED = "retry_command_post_provider_finalize_failed"


@dataclass(frozen=True)
class ClassifiedProviderOutcome:
    """Authoritative post-barrier classification for finalization."""

    outcome: NormalizedOutcome
    external_post_id: str | None = None
    external_post_url: str | None = None
    failure_code: str | None = None
    safe_message: str | None = None
    reason_code: str | None = None


def classify_provider_result(raw: Any) -> ClassifiedProviderOutcome:
    """Classify a provider port result. Never returns a retryable outcome."""
    if not isinstance(raw, ProviderExecutionResult):
        return ClassifiedProviderOutcome(
            outcome="AMBIGUOUS",
            failure_code=FAILURE_CODE_MALFORMED,
            safe_message="Provider returned a malformed result",
            reason_code="malformed_provider_result",
        )

    if raw.outcome == "success":
        epid = (raw.external_post_id or "").strip() or None
        if epid is None:
            return ClassifiedProviderOutcome(
                outcome="AMBIGUOUS",
                external_post_url=raw.external_post_url,
                failure_code=FAILURE_CODE_MISSING_EXTERNAL_ID,
                safe_message=(
                    raw.safe_message
                    or "Provider success missing authoritative external_post_id"
                ),
                reason_code="success_missing_external_post_id",
            )
        return ClassifiedProviderOutcome(
            outcome="SUCCESS",
            external_post_id=epid,
            external_post_url=raw.external_post_url,
            safe_message=raw.safe_message or "Provider success",
            reason_code="provider_success",
        )

    if raw.outcome == "definitive_failure":
        return ClassifiedProviderOutcome(
            outcome="DEFINITIVE_FAILURE",
            failure_code=raw.failure_code or FAILURE_CODE_DEFINITIVE,
            safe_message=raw.safe_message or "Provider definitive failure",
            reason_code="provider_definitive_failure",
        )

    # ambiguous or any unexpected outcome string
    return ClassifiedProviderOutcome(
        outcome="AMBIGUOUS",
        failure_code=raw.failure_code or FAILURE_CODE_AMBIGUOUS,
        safe_message=raw.safe_message or "Provider ambiguous result",
        reason_code="provider_ambiguous",
    )


def classify_provider_exception(exc: BaseException) -> ClassifiedProviderOutcome:
    """Any exception after barrier defaults to AMBIGUOUS (never safe-failed)."""
    from app.services.publish_retry_command_provider_port import (
        FakeProviderTimeoutError,
    )

    if isinstance(exc, (TimeoutError, FakeProviderTimeoutError)):
        return ClassifiedProviderOutcome(
            outcome="AMBIGUOUS",
            failure_code=FAILURE_CODE_TIMEOUT,
            safe_message="Provider timed out after write barrier",
            reason_code="provider_timeout",
        )
    return ClassifiedProviderOutcome(
        outcome="AMBIGUOUS",
        failure_code=FAILURE_CODE_EXCEPTION,
        safe_message="Provider raised after write barrier",
        reason_code="provider_exception",
    )
