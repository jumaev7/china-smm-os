"""Retry-command eligibility evaluator port (Phase 3C.1C-D2-B2a).

Canonical production default remains ``evaluate_manual_retry_eligibility``
with the EMPTY allowlist unchanged.

Staging synthetic eligibility is constructible ONLY with a verified
``VerifiedRetryCommandStagingContext``. Domain services must not branch on
APP_ENV; only an injected evaluator may widen staging fixture approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.services.manual_retry_eligibility import (
    ManualRetryEligibility,
    ManualRetryLiveState,
    evaluate_manual_retry_eligibility,
)
from app.services.publish_retry_command_staging_identity import (
    VerifiedRetryCommandStagingContext,
    assert_verified_staging_context,
)

# Synthetic fixture markers (no migration). Both required for staging approval.
STAGING_TENANT_NAME_PREFIX = "staging-retry-"
STAGING_CORRELATION_ID_PREFIX = "staging-retry:"


@dataclass(frozen=True, slots=True)
class RetryCommandEligibilityContext:
    """Inputs for command prepare/barrier eligibility evaluation."""

    attempt: Any
    live_state: ManualRetryLiveState | None = None
    source: str = "admin"
    correlation_id: str | None = None
    tenant_company_name: str | None = None
    command_id: UUID | None = None
    tenant_id: UUID | None = None


@runtime_checkable
class RetryCommandEligibilityEvaluator(Protocol):
    """Explicit eligibility policy injected into Preparation/Barrier."""

    def evaluate(
        self,
        ctx: RetryCommandEligibilityContext,
    ) -> ManualRetryEligibility:
        ...


class CanonicalManualRetryEligibility:
    """Default everywhere — wraps evaluate_manual_retry_eligibility."""

    def evaluate(
        self,
        ctx: RetryCommandEligibilityContext,
    ) -> ManualRetryEligibility:
        source = (ctx.source or "admin").strip().lower()
        return evaluate_manual_retry_eligibility(
            ctx.attempt,
            ctx.live_state,
            source=source if source != "api" else "admin",
        )


class StagingSyntheticRetryEligibility:
    """Approve ONLY clearly synthetic staging fixtures.

    Requires VerifiedRetryCommandStagingContext. Does not approve arbitrary
    staging-DB commands merely because the DB identity is staging.
    """

    def __init__(self, staging_context: VerifiedRetryCommandStagingContext) -> None:
        self._staging = assert_verified_staging_context(
            staging_context,
            what="StagingSyntheticRetryEligibility",
        )

    @property
    def staging_context(self) -> VerifiedRetryCommandStagingContext:
        return self._staging

    def evaluate(
        self,
        ctx: RetryCommandEligibilityContext,
    ) -> ManualRetryEligibility:
        tenant_name = (ctx.tenant_company_name or "").strip()
        correlation_id = (ctx.correlation_id or "").strip()

        if not tenant_name.startswith(STAGING_TENANT_NAME_PREFIX):
            return ManualRetryEligibility(
                allowed=False,
                reason_code="staging_fixture_tenant_marker_missing",
                safety_class="PERMANENT_BLOCK",
                confirmation_tier="high",
                external_side_effect=True,
                operator_message=(
                    "Staging eligibility requires tenant name prefix "
                    f"{STAGING_TENANT_NAME_PREFIX!r}"
                ),
                mobile_eligible=False,
            )
        if not correlation_id.startswith(STAGING_CORRELATION_ID_PREFIX):
            return ManualRetryEligibility(
                allowed=False,
                reason_code="staging_fixture_correlation_marker_missing",
                safety_class="PERMANENT_BLOCK",
                confirmation_tier="high",
                external_side_effect=True,
                operator_message=(
                    "Staging eligibility requires correlation_id prefix "
                    f"{STAGING_CORRELATION_ID_PREFIX!r}"
                ),
                mobile_eligible=False,
            )

        return ManualRetryEligibility(
            allowed=True,
            reason_code="staging_synthetic_fixture_allowed",
            safety_class="CONDITIONAL_MANUAL_RETRY",
            confirmation_tier="medium",
            external_side_effect=True,
            operator_message="Staging synthetic fixture approved for fake harness",
            mobile_eligible=False,
        )


def synthetic_tenant_marker(client: Any | None, tenant_name: str | None = None) -> str | None:
    """Resolve synthetic tenant/name marker (client.company_name or tenant name)."""
    if tenant_name and str(tenant_name).strip():
        return str(tenant_name).strip()
    if client is not None:
        name = getattr(client, "company_name", None)
        if name and str(name).strip():
            return str(name).strip()
    return None


def default_eligibility_evaluator() -> CanonicalManualRetryEligibility:
    """Canonical default used by PreparationService / BarrierService."""
    return CanonicalManualRetryEligibility()
