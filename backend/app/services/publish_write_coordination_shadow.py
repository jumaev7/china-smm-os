"""R3 — shadow-only observation of publish write coordination registry.

Compares live publish pre-I/O decisions against what the registry coordination
model would conclude — without affecting execution.

May:
  - read existing registry rows (no FOR UPDATE / no advisory locks)
  - compute advisory classifications
  - emit bounded metrics / disagreement-or-error audits

Must NOT:
  - create registry rows, acquire authority, mutate state
  - mint publication_intent_id
  - block/allow publishes, alter success-reader, call providers
  - change retry / claim / worker behavior

Default-off via ``PUBLISH_WRITE_COORDINATION_SHADOW``.

Deferred (not wired in R3):
  - retry prepare / barrier / executor shadow (live paths still lack
    durable publication_intent_id minting; cannot observe safely without
    dormant-intent semantic changes)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.publish_write_coordination import (
    DestinationIdentity,
    normalize_destination,
    write_coordination_shadow_enabled,
)
from app.services.publish_write_coordination_shadow_metrics import (
    inc as shadow_metric_inc,
)

logger = logging.getLogger(__name__)

# Advisory classifications (task vocabulary; stable string values).
ALLOW_IF_AUTHORITY_WERE_REQUESTED = "ALLOW_IF_AUTHORITY_WERE_REQUESTED"
BLOCK_UNRESOLVED_DESTINATION = "BLOCK_UNRESOLVED_DESTINATION"
BLOCK_SAME_INTENT_SUCCESS = "BLOCK_SAME_INTENT_SUCCESS"
BLOCK_INTENT_SUPERSEDED = "BLOCK_INTENT_SUPERSEDED"
NO_REGISTRY_EVIDENCE = "NO_REGISTRY_EVIDENCE"
INSUFFICIENT_INTENT_CONTEXT = "INSUFFICIENT_INTENT_CONTEXT"
REGISTRY_STATE_DISAGREEMENT = "REGISTRY_STATE_DISAGREEMENT"

ShadowClassification = Literal[
    "ALLOW_IF_AUTHORITY_WERE_REQUESTED",
    "BLOCK_UNRESOLVED_DESTINATION",
    "BLOCK_SAME_INTENT_SUCCESS",
    "BLOCK_INTENT_SUPERSEDED",
    "NO_REGISTRY_EVIDENCE",
    "INSUFFICIENT_INTENT_CONTEXT",
    "REGISTRY_STATE_DISAGREEMENT",
]

LiveDecision = Literal["allow", "block"]

_BLOCK_CLASSIFICATIONS = frozenset(
    {
        BLOCK_UNRESOLVED_DESTINATION,
        BLOCK_SAME_INTENT_SUCCESS,
        BLOCK_INTENT_SUPERSEDED,
    }
)
_ALLOW_CLASSIFICATIONS = frozenset(
    {
        ALLOW_IF_AUTHORITY_WERE_REQUESTED,
        NO_REGISTRY_EVIDENCE,
    }
)

AUDIT_EVENT_DISAGREEMENT = "publishing.write_coordination_shadow_disagreement"
AUDIT_EVENT_ERROR = "publishing.write_coordination_shadow_error"

# Mutation APIs that shadow must never invoke (source/runtime audit surface).
FORBIDDEN_MUTATION_METHODS = frozenset(
    {
        "acquire_write_authority",
        "mark_write_started",
        "record_safe_failure",
        "record_success",
        "record_ambiguous",
        "surface_stranded_write",
        "resolve_ambiguous",
        "supersede_intent",
    }
)

ALLOWED_READ_METHODS = frozenset(
    {
        "destination_has_unresolved_write",
        "same_intent_has_durable_success",
        "get_destination_intent_row",
    }
)


@dataclass(frozen=True)
class ShadowDecision:
    """Pure advisory outcome — never authoritative."""

    classification: ShadowClassification
    would_allow: bool | None
    reason: str

    @property
    def would_block(self) -> bool | None:
        if self.would_allow is None:
            return None
        return not self.would_allow


@dataclass(frozen=True)
class ShadowObservationResult:
    """Bounded result of one shadow evaluation (for tests / logging)."""

    evaluated: bool
    skipped: bool
    classification: ShadowClassification | None
    live_decision: LiveDecision | None
    disagreement: bool
    error: bool
    details: dict[str, Any]


def classify_shadow_decision(
    *,
    publication_intent_id: UUID | None,
    has_unresolved: bool,
    has_same_intent_success: bool = False,
    intent_row_state: str | None = None,
) -> ShadowDecision:
    """Pure decision layer — no I/O.

    Priority:
      1. destination unresolved (WRITE_STARTED / AMBIGUOUS)
      2. missing publication_intent_id
      3. same-intent durable success
      4. SUPERSEDED intent row
      5. non-blocking row present → allow-if-authority-were-requested
      6. no row → no registry evidence
    """
    if has_unresolved:
        return ShadowDecision(
            classification=BLOCK_UNRESOLVED_DESTINATION,
            would_allow=False,
            reason="registry_unresolved_write_started_or_ambiguous",
        )

    if publication_intent_id is None:
        return ShadowDecision(
            classification=INSUFFICIENT_INTENT_CONTEXT,
            would_allow=None,
            reason="publication_intent_id_absent",
        )

    if has_same_intent_success:
        return ShadowDecision(
            classification=BLOCK_SAME_INTENT_SUCCESS,
            would_allow=False,
            reason="same_intent_durable_success",
        )

    if intent_row_state == "SUPERSEDED":
        return ShadowDecision(
            classification=BLOCK_INTENT_SUPERSEDED,
            would_allow=False,
            reason="intent_row_superseded",
        )

    if intent_row_state is None:
        return ShadowDecision(
            classification=NO_REGISTRY_EVIDENCE,
            would_allow=True,
            reason="no_registry_row_for_destination_intent",
        )

    if intent_row_state in (
        "RESERVED",
        "FAILED_SAFE",
        "RESOLVED_FAILED",
        "SUCCEEDED",
        "RESOLVED_SUCCEEDED",
    ):
        # SUCCEEDED / RESOLVED_SUCCEEDED without has_same_intent_success is
        # unexpected (query mismatch) — flag disagreement-class advisory.
        if intent_row_state in ("SUCCEEDED", "RESOLVED_SUCCEEDED"):
            return ShadowDecision(
                classification=REGISTRY_STATE_DISAGREEMENT,
                would_allow=None,
                reason="success_state_without_durable_success_query_hit",
            )
        return ShadowDecision(
            classification=ALLOW_IF_AUTHORITY_WERE_REQUESTED,
            would_allow=True,
            reason=f"intent_row_state_{intent_row_state.lower()}",
        )

    if intent_row_state in ("WRITE_STARTED", "AMBIGUOUS"):
        # Destination unresolved query should have caught these; treat as
        # advisory disagreement if we somehow see them only on the intent row.
        return ShadowDecision(
            classification=REGISTRY_STATE_DISAGREEMENT,
            would_allow=False,
            reason="intent_row_unresolved_but_destination_query_clear",
        )

    return ShadowDecision(
        classification=REGISTRY_STATE_DISAGREEMENT,
        would_allow=None,
        reason=f"unexpected_intent_row_state_{intent_row_state}",
    )


def disagreement_kind(
    live_decision: LiveDecision,
    decision: ShadowDecision,
) -> str | None:
    """Return disagreement dimension or None when aligned / inconclusive."""
    if decision.would_allow is None:
        return None
    shadow_side: LiveDecision = "allow" if decision.would_allow else "block"
    if live_decision == shadow_side:
        return None
    if live_decision == "allow" and shadow_side == "block":
        return "live_allow_shadow_block"
    if live_decision == "block" and shadow_side == "allow":
        return "live_block_shadow_allow"
    return None


async def observe_publish_pre_provider(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    content_id: UUID,
    platform: str,
    account_id: UUID | None,
    publication_intent_id: UUID | None,
    live_decision: LiveDecision,
    live_reason: str | None = None,
    live_prior_success: bool = False,
) -> ShadowObservationResult:
    """Fail-open shadow observation at a PublishService pre-provider point.

    Never raises into the live publish path. Performs zero work when the
    shadow flag is false.
    """
    empty = ShadowObservationResult(
        evaluated=False,
        skipped=True,
        classification=None,
        live_decision=None,
        disagreement=False,
        error=False,
        details={},
    )
    try:
        if not write_coordination_shadow_enabled():
            return empty

        destination = normalize_destination(
            tenant_id=tenant_id,
            content_id=content_id,
            platform=platform,
            account_id=account_id,
        )
        decision, evidence = await _evaluate_against_registry(
            db,
            destination=destination,
            publication_intent_id=publication_intent_id,
        )
        shadow_metric_inc("shadow_evaluations_total")
        if decision.classification == INSUFFICIENT_INTENT_CONTEXT:
            shadow_metric_inc("shadow_no_intent_context_total")
        if decision.classification == BLOCK_UNRESOLVED_DESTINATION:
            shadow_metric_inc("shadow_unresolved_detected_total")
        if decision.classification == BLOCK_SAME_INTENT_SUCCESS:
            shadow_metric_inc("shadow_same_intent_success_total")

        disagree = disagreement_kind(live_decision, decision)
        if disagree is not None:
            shadow_metric_inc("shadow_disagreement_total")
            if disagree == "live_allow_shadow_block":
                shadow_metric_inc(
                    "shadow_disagreement_live_allow_shadow_block_total"
                )
            elif disagree == "live_block_shadow_allow":
                shadow_metric_inc(
                    "shadow_disagreement_live_block_shadow_allow_total"
                )
            await _emit_shadow_audit(
                event_type=AUDIT_EVENT_DISAGREEMENT,
                tenant_id=tenant_id,
                content_id=content_id,
                platform=platform,
                details={
                    "mode": "shadow",
                    "authoritative": False,
                    "disagreement": disagree,
                    "live_decision": live_decision,
                    "live_reason": live_reason,
                    "live_prior_success": live_prior_success,
                    "shadow_classification": decision.classification,
                    "shadow_reason": decision.reason,
                    "shadow_would_allow": decision.would_allow,
                    "has_unresolved": evidence.get("has_unresolved"),
                    "has_same_intent_success": evidence.get(
                        "has_same_intent_success"
                    ),
                    "intent_row_state": evidence.get("intent_row_state"),
                    "publication_intent_present": publication_intent_id
                    is not None,
                },
            )
            logger.info(
                "[WriteCoordShadow] disagreement mode=shadow "
                "live=%s shadow=%s reason=%s platform=%s content=%s",
                live_decision,
                decision.classification,
                decision.reason,
                platform,
                content_id,
            )

        return ShadowObservationResult(
            evaluated=True,
            skipped=False,
            classification=decision.classification,
            live_decision=live_decision,
            disagreement=disagree is not None,
            error=False,
            details={
                "classification": decision.classification,
                "reason": decision.reason,
                "would_allow": decision.would_allow,
                "live_decision": live_decision,
                "live_reason": live_reason,
                "disagreement": disagree,
                **evidence,
            },
        )
    except Exception as exc:  # noqa: BLE001 — fail-open relative to live publish
        shadow_metric_inc("shadow_error_total")
        logger.warning(
            "[WriteCoordShadow] evaluation error mode=shadow "
            "platform=%s content=%s err=%s",
            platform,
            content_id,
            type(exc).__name__,
            exc_info=True,
        )
        try:
            await _emit_shadow_audit(
                event_type=AUDIT_EVENT_ERROR,
                tenant_id=tenant_id,
                content_id=content_id,
                platform=platform,
                details={
                    "mode": "shadow",
                    "authoritative": False,
                    "error_type": type(exc).__name__,
                    "live_decision": live_decision,
                    "live_reason": live_reason,
                    "publication_intent_present": publication_intent_id
                    is not None,
                },
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "[WriteCoordShadow] error audit failed",
                exc_info=True,
            )
        return ShadowObservationResult(
            evaluated=False,
            skipped=False,
            classification=None,
            live_decision=live_decision,
            disagreement=False,
            error=True,
            details={"error_type": type(exc).__name__},
        )


async def _evaluate_against_registry(
    db: AsyncSession,
    *,
    destination: DestinationIdentity,
    publication_intent_id: UUID | None,
) -> tuple[ShadowDecision, dict[str, Any]]:
    """Read-only registry queries + pure classify. No mutation methods."""
    from app.services.publish_write_coordination_registry_service import (
        PublishWriteCoordinationRegistryService as RegistryService,
    )

    has_unresolved = await RegistryService.destination_has_unresolved_write(
        db, destination
    )
    has_same_intent_success = False
    intent_row_state: str | None = None

    if publication_intent_id is not None:
        has_same_intent_success = (
            await RegistryService.same_intent_has_durable_success(
                db,
                destination=destination,
                publication_intent_id=publication_intent_id,
            )
        )
        row = await RegistryService.get_destination_intent_row(
            db, destination, publication_intent_id
        )
        if row is not None:
            intent_row_state = row.state

    decision = classify_shadow_decision(
        publication_intent_id=publication_intent_id,
        has_unresolved=has_unresolved,
        has_same_intent_success=has_same_intent_success,
        intent_row_state=intent_row_state,
    )
    evidence = {
        "has_unresolved": has_unresolved,
        "has_same_intent_success": has_same_intent_success,
        "intent_row_state": intent_row_state,
    }
    return decision, evidence


async def _emit_shadow_audit(
    *,
    event_type: str,
    tenant_id: UUID,
    content_id: UUID,
    platform: str,
    details: dict[str, Any],
) -> None:
    """Best-effort audit in a separate session — never touches publish TX."""
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.platform_audit_service import PlatformAuditService

        payload = dict(details)
        payload.setdefault("mode", "shadow")
        payload.setdefault("authoritative", False)
        payload["platform"] = (platform or "").strip().lower()
        # IDs only in structured details — never Prometheus labels.
        payload["content_id"] = str(content_id)

        async with AsyncSessionLocal() as audit_db:
            await PlatformAuditService.record(
                audit_db,
                actor_type="system",
                actor_id=None,
                tenant_id=tenant_id,
                event_type=event_type,
                resource_type="content_item",
                resource_id=str(content_id),
                details=payload,
                commit=True,
            )
    except Exception:  # noqa: BLE001 — audit must never affect shadow or live path
        logger.debug(
            "[WriteCoordShadow] audit emit failed event=%s",
            event_type,
            exc_info=True,
        )
