"""Phase E1 — read-only stranded post-barrier detection + operator surfacing.

Observes PublishRetryCommand rows left in ``provider_write_started`` after the
write barrier. Does NOT mutate command/attempt/content state, call providers,
claim/reclaim, execute, finalize, or create replacement retry commands.

Quiet-period age is a review heuristic only — never proof of orphanhood,
provider outcome, or authorization to write/replay.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform_ops import PlatformAuditLog
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import (
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)

logger = logging.getLogger(__name__)

PROVIDER_CALL_STARTED_EVENT = "publishing.retry_command_provider_call_started"
PHASE_E_CONTEXT_MARKER = "stranded_post_barrier"
STRANDED_DEDUPE_PREFIX = "phase_e:stranded_retry:"

Classification = Literal["still_in_progress", "stranded_review_candidate"]
OutcomeStance = Literal["provider_outcome_ambiguous"]

# Explicit denials — E1 must never emit these labels from time/audit alone.
FORBIDDEN_CLASSIFICATIONS = frozenset({
    "definitely_orphaned",
    "provider_not_called",
    "provider_not_called_proven",
    "provider_success",
    "provider_failure",
})

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class QuietPeriodModel:
    """Documented quiet-period inputs (surfacing heuristic only)."""

    lease_seconds: int
    drain_seconds: int
    provider_slack_seconds: int
    safety_buffer_seconds: int
    quiet_period_seconds: int

    @property
    def formula(self) -> str:
        return (
            "max(lease_seconds, drain_seconds) "
            "+ provider_slack_seconds + safety_buffer_seconds"
        )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_quiet_period_model() -> QuietPeriodModel:
    """Quiet period = max(lease, drain) + generic provider slack + safety buffer.

    Constants (defaults):
    - lease_seconds: PUBLISH_RETRY_COMMAND_LEASE_SECONDS (180)
    - drain_seconds: PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS (60)
    - provider_slack_seconds: PUBLISH_RETRY_STRANDED_PROVIDER_SLACK_SECONDS (300)
      Conservative generic slack when provider-specific budgets are unavailable.
    - safety_buffer_seconds: PUBLISH_RETRY_STRANDED_SAFETY_BUFFER_SECONDS (120)

    Affects classification/surfacing only. Never claim, execution, or provider I/O.
    """
    lease = max(0, int(getattr(settings, "PUBLISH_RETRY_COMMAND_LEASE_SECONDS", 180) or 0))
    drain = max(
        0,
        int(float(getattr(settings, "PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS", 60.0) or 0)),
    )
    slack = max(
        0,
        int(getattr(settings, "PUBLISH_RETRY_STRANDED_PROVIDER_SLACK_SECONDS", 300) or 0),
    )
    buffer = max(
        0,
        int(getattr(settings, "PUBLISH_RETRY_STRANDED_SAFETY_BUFFER_SECONDS", 120) or 0),
    )
    quiet = max(lease, drain) + slack + buffer
    return QuietPeriodModel(
        lease_seconds=lease,
        drain_seconds=drain,
        provider_slack_seconds=slack,
        safety_buffer_seconds=buffer,
        quiet_period_seconds=quiet,
    )


def compute_quiet_period_seconds() -> int:
    return compute_quiet_period_model().quiet_period_seconds


def is_stranded_post_barrier_row(
    *,
    status: str | None,
    provider_write_started_at: datetime | None,
) -> bool:
    """Canonical stranded predicate (observation only).

    status == provider_write_started
    AND provider_write_started_at IS NOT NULL
    AND non-terminal

    Excludes pending, claimed, expired pre-barrier leases, and classic
    PublishAttempt.in_progress staleness (owned by claim/reclaim/resilience).
    """
    if (status or "") != "provider_write_started":
        return False
    if provider_write_started_at is None:
        return False
    if status in RETRY_COMMAND_TERMINAL_STATUSES:
        return False
    return True


def stranded_command_sql_filters():
    """SQLAlchemy WHERE clauses matching the canonical stranded predicate."""
    return (
        PublishRetryCommand.status == "provider_write_started",
        PublishRetryCommand.provider_write_started_at.is_not(None),
        PublishRetryCommand.status.notin_(tuple(RETRY_COMMAND_TERMINAL_STATUSES)),
    )


def classify_by_quiet_period(
    *,
    age_seconds: int,
    quiet_period_seconds: int,
) -> tuple[Classification, OutcomeStance | None]:
    """Map age vs quiet period to non-authoritative observational labels.

    After quiet period without stronger evidence, outcome stance remains
    ``provider_outcome_ambiguous`` — never ``provider_not_called_proven``.
    """
    if age_seconds < max(0, int(quiet_period_seconds)):
        return "still_in_progress", None
    return "stranded_review_candidate", "provider_outcome_ambiguous"


def stranded_dedupe_key(command_id: UUID) -> str:
    return f"{STRANDED_DEDUPE_PREFIX}{command_id}"


def recommended_action_for(
    classification: Classification,
) -> str:
    if classification == "still_in_progress":
        return "monitor_await_quiet_period"
    return "operator_manual_review_no_replay"


def interpret_provider_call_started_audit(present: bool) -> dict[str, Any]:
    """Exact E1 semantics for provider_call_started audit evidence."""
    if present:
        return {
            "presence": "present",
            "interpretation": "intent_evidence",
            "meaning": (
                "provider execution was intended to begin "
                "(audit recorded before/around provider invoke)"
            ),
            "not_proof_of": [
                "network_call_completed",
                "provider_success",
                "provider_failure",
                "provider_not_called",
            ],
            "authorizes_replay": False,
        }
    return {
        "presence": "absent",
        "interpretation": "unknown",
        "meaning": "unknown whether provider execution was intended or audited",
        "not_proof_of": [
            "provider_not_called_proven",
            "provider_success",
            "provider_failure",
            "zero_effect",
        ],
        "authorizes_replay": False,
    }


def _age_seconds(started_at: datetime, now: datetime) -> int:
    ts = started_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ref = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return max(0, int((ref - ts).total_seconds()))


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()


@dataclass
class StrandedCommandObservation:
    """Operator-safe read model for one stranded post-barrier command."""

    command_id: UUID
    tenant_id: UUID
    platform: str
    publishing_account_id: UUID | None
    content_id: UUID
    client_id: UUID | None
    original_attempt_id: UUID
    resulting_attempt_id: UUID | None
    status: str
    provider_write_started_at: datetime
    lease_owner_historical: str | None
    claimed_at: datetime | None
    age_seconds: int
    quiet_period_seconds: int
    quiet_period_elapsed: bool
    last_known_local_step: str
    provider_call_started_audit: dict[str, Any]
    external_post_id: str | None
    correlation_id: str
    classification: Classification
    outcome_stance: OutcomeStance | None
    recommended_action: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "tenant_id": self.tenant_id,
            "provider": self.platform,
            "platform": self.platform,
            "publishing_account_id": self.publishing_account_id,
            "content_id": self.content_id,
            "client_id": self.client_id,
            "original_attempt_id": self.original_attempt_id,
            "resulting_attempt_id": self.resulting_attempt_id,
            "status": self.status,
            "provider_write_started_at": self.provider_write_started_at,
            "lease_owner": {
                "value": self.lease_owner_historical,
                "label": "historical_only",
                "not_current_liveness_proof": True,
            },
            "claimed_at": self.claimed_at,
            "age_seconds": self.age_seconds,
            "quiet_period_seconds": self.quiet_period_seconds,
            "quiet_period_elapsed": self.quiet_period_elapsed,
            "last_known_local_step": self.last_known_local_step,
            "provider_call_started_audit": self.provider_call_started_audit,
            "external_post_id": self.external_post_id,
            "correlation_id": self.correlation_id,
            "classification": self.classification,
            "outcome_stance": self.outcome_stance,
            "recommended_action": self.recommended_action,
            "phase_e": PHASE_E_CONTEXT_MARKER,
            # Explicit non-claims for operators / future tooling.
            "does_not_prove": sorted(FORBIDDEN_CLASSIFICATIONS),
            "authorizes_provider_write": False,
            "authorizes_replay": False,
        }


class PublishRetryCommandStrandedDetector:
    """Read-oriented stranded post-barrier detector (Phase E1).

    Never imports/calls claim, preparation, barrier, executor, finalizer,
    retry worker, or real provider adapters.
    """

    @classmethod
    async def list_stranded(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        now: datetime | None = None,
        create_alerts: bool | None = None,
    ) -> dict[str, Any]:
        """Tenant-scoped stranded observation page (read path).

        Alert rows are the only permissible durable writes, and only when
        alert surfacing is enabled and the candidate is past quiet period.
        """
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        ref_now = now or utc_now()
        quiet = compute_quiet_period_model()

        base = select(PublishRetryCommand).where(
            PublishRetryCommand.tenant_id == tenant_id,
            *stranded_command_sql_filters(),
        )
        total = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(PublishRetryCommand)
                    .where(
                        PublishRetryCommand.tenant_id == tenant_id,
                        *stranded_command_sql_filters(),
                    ),
                )
            ).scalar_one()
            or 0,
        )
        rows = (
            await db.execute(
                base.order_by(PublishRetryCommand.provider_write_started_at.asc())
                .offset((page - 1) * page_size)
                .limit(page_size),
            )
        ).scalars().all()

        attempt_ids = [
            r.resulting_attempt_id for r in rows if r.resulting_attempt_id is not None
        ]
        attempts_by_id: dict[UUID, PublishAttempt] = {}
        if attempt_ids:
            attempt_rows = (
                await db.execute(
                    select(PublishAttempt).where(PublishAttempt.id.in_(attempt_ids)),
                )
            ).scalars().all()
            attempts_by_id = {a.id: a for a in attempt_rows}

        command_ids = [r.id for r in rows]
        audit_present = await cls._provider_call_started_presence(db, command_ids)

        observations: list[StrandedCommandObservation] = []
        alerts_created = 0
        alerts_updated = 0
        alert_enabled = (
            bool(getattr(settings, "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED", False))
            if create_alerts is None
            else bool(create_alerts)
        )

        for cmd in rows:
            obs = cls._observe_command(
                cmd,
                now=ref_now,
                quiet_period_seconds=quiet.quiet_period_seconds,
                attempt=attempts_by_id.get(cmd.resulting_attempt_id)
                if cmd.resulting_attempt_id
                else None,
                audit_present=bool(audit_present.get(cmd.id)),
            )
            observations.append(obs)
            if (
                alert_enabled
                and obs.classification == "stranded_review_candidate"
            ):
                created = await cls._surface_alert(db, obs)
                if created is True:
                    alerts_created += 1
                elif created is False:
                    alerts_updated += 1

        return {
            "items": [o.to_payload() for o in observations],
            "total": total,
            "page": page,
            "page_size": page_size,
            "quiet_period": {
                "lease_seconds": quiet.lease_seconds,
                "drain_seconds": quiet.drain_seconds,
                "provider_slack_seconds": quiet.provider_slack_seconds,
                "safety_buffer_seconds": quiet.safety_buffer_seconds,
                "quiet_period_seconds": quiet.quiet_period_seconds,
                "formula": quiet.formula,
                "heuristic_only": True,
                "authorizes_provider_write": False,
            },
            "alert_surfacing_enabled": alert_enabled,
            "alerts_created": alerts_created,
            "alerts_updated": alerts_updated,
            "phase_e": PHASE_E_CONTEXT_MARKER,
            "read_only_commands": True,
        }

    @classmethod
    def _observe_command(
        cls,
        cmd: PublishRetryCommand,
        *,
        now: datetime,
        quiet_period_seconds: int,
        attempt: PublishAttempt | None,
        audit_present: bool,
    ) -> StrandedCommandObservation:
        started = cmd.provider_write_started_at
        if started is None:
            # Predicate requires timestamp; defensive fallback should not surface.
            raise ValueError("stranded observation requires provider_write_started_at")
        age = _age_seconds(started, now)
        classification, outcome_stance = classify_by_quiet_period(
            age_seconds=age,
            quiet_period_seconds=quiet_period_seconds,
        )
        audit_info = interpret_provider_call_started_audit(audit_present)
        if audit_present:
            last_step = "provider_call_started_audit_recorded"
        else:
            last_step = "barrier_crossed_provider_write_started"

        return StrandedCommandObservation(
            command_id=cmd.id,
            tenant_id=cmd.tenant_id,
            platform=cmd.platform,
            publishing_account_id=cmd.publishing_account_id,
            content_id=cmd.content_id,
            client_id=getattr(cmd, "client_id", None),
            original_attempt_id=cmd.original_attempt_id,
            resulting_attempt_id=cmd.resulting_attempt_id,
            status=cmd.status,
            provider_write_started_at=started,
            lease_owner_historical=cmd.lease_owner,
            claimed_at=cmd.claimed_at,
            age_seconds=age,
            quiet_period_seconds=quiet_period_seconds,
            quiet_period_elapsed=age >= quiet_period_seconds,
            last_known_local_step=last_step,
            provider_call_started_audit=audit_info,
            external_post_id=getattr(attempt, "external_post_id", None) if attempt else None,
            correlation_id=cmd.correlation_id,
            classification=classification,
            outcome_stance=outcome_stance,
            recommended_action=recommended_action_for(classification),
        )

    @classmethod
    async def _provider_call_started_presence(
        cls,
        db: AsyncSession,
        command_ids: list[UUID],
    ) -> dict[UUID, bool]:
        if not command_ids:
            return {}
        id_strs = [str(cid) for cid in command_ids]
        rows = (
            await db.execute(
                select(PlatformAuditLog.resource_id)
                .where(
                    PlatformAuditLog.event_type == PROVIDER_CALL_STARTED_EVENT,
                    PlatformAuditLog.resource_type == "publish_retry_command",
                    PlatformAuditLog.resource_id.in_(id_strs),
                )
                .distinct(),
            )
        ).scalars().all()
        present = {UUID(rid) for rid in rows if rid}
        return {cid: cid in present for cid in command_ids}

    @classmethod
    async def _surface_alert(
        cls,
        db: AsyncSession,
        obs: StrandedCommandObservation,
    ) -> bool | None:
        """Create/update operator_review alert. Never mutates the command.

        Returns True if created, False if updated/deduped, None if skipped.
        """
        # Lazy import keeps alert delivery failures isolated from detection.
        from app.services.publish_operator_alert_service import PublishOperatorAlertService

        try:
            return await PublishOperatorAlertService.upsert_stranded_post_barrier_alert(
                db,
                observation=obs.to_payload(),
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[StrandedDetector] alert surfacing failed command_id=%s",
                obs.command_id,
            )
            return None


# Static import-boundary markers for tests (must remain true).
_E1_FORBIDDEN_IMPORT_MODULES = frozenset({
    "app.services.publish_retry_command_claim_service",
    "app.services.publish_retry_command_preparation_service",
    "app.services.publish_retry_command_barrier_service",
    "app.services.publish_retry_command_executor",
    "app.services.publish_retry_command_finalization_service",
    "app.workers.publish_retry_command_worker",
    "app.services.providers",
    "httpx",
})
