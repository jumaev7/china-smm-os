"""Shadow-mode auto-ack evaluation — audit only, zero alert mutations.

Phase 1: never calls PublishOperatorAlertService.acknowledge / resolve_manual.
Real execution behind OPERATOR_AUTO_ACK_ALERTS_ENABLED is intentionally unimplemented.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.platform_ops import PlatformAuditLog
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.services.operator_auto_ack.comparison import (
    classify_shadow_outcome,
    summarize_outcomes,
)
from app.services.operator_auto_ack.constants import (
    ALLOWLIST_ALERT_TYPES,
    CYCLE_EVENT_TYPE,
    DEDUPE_COOLDOWN_HOURS,
    MAX_ALERTS_PER_CYCLE,
    RESOURCE_TYPE_ALERT,
    SHADOW_ACTION_WOULD_ACK,
    SHADOW_EVENT_TYPE,
)
from app.services.operator_auto_ack.eligibility import (
    AutoAckDecision,
    build_state_fingerprint,
    decision_for_cross_tenant,
    evaluate_auto_ack_candidate,
)
from app.services.platform_audit_service import PlatformAuditService
from app.services.publish_resilience import PublishResilienceService

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def real_auto_ack_enabled() -> bool:
    """Future kill switch. Phase 1 never executes real acknowledge regardless."""
    return bool(getattr(settings, "OPERATOR_AUTO_ACK_ALERTS_ENABLED", False))


def shadow_mode_enabled() -> bool:
    return bool(getattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", False))


class OperatorAutoAckShadowService:
    """Evaluate allowlisted open alerts and record would-acknowledge audits."""

    @classmethod
    async def run_cycle(cls, db: AsyncSession) -> dict[str, Any]:
        """One bounded evaluation cycle. Mutates only PlatformAuditLog (via record)."""
        if not shadow_mode_enabled():
            return {
                "skipped": True,
                "reason": "shadow_disabled",
                "evaluated": 0,
                "eligible": 0,
                "ineligible": 0,
                "would_acknowledge": 0,
                "deduped": 0,
                "errors": 0,
                "audits_written": 0,
            }

        # Fail-closed: real flag must never unlock execution in this module.
        if real_auto_ack_enabled():
            logger.error(
                "[AutoAckShadow] OPERATOR_AUTO_ACK_ALERTS_ENABLED=true but real "
                "execution is not implemented — continuing shadow-only"
            )

        alerts = await cls._load_candidate_alerts(db)
        summary: dict[str, Any] = {
            "skipped": False,
            "evaluated": 0,
            "eligible": 0,
            "ineligible": 0,
            "would_acknowledge": 0,
            "deduped": 0,
            "errors": 0,
            "audits_written": 0,
            "reason_counts": {},
            "real_execution_attempted": False,
        }
        reason_counts: Counter[str] = Counter()

        for alert in alerts:
            try:
                result = await cls.evaluate_and_record(db, alert)
            except Exception:
                summary["errors"] += 1
                logger.exception(
                    "[AutoAckShadow] candidate failed alert_id=%s tenant=%s",
                    getattr(alert, "id", None),
                    getattr(alert, "tenant_id", None),
                )
                continue

            if result.get("deduped"):
                summary["deduped"] += 1
                continue

            summary["evaluated"] += 1
            decision: AutoAckDecision | None = result.get("decision")
            if decision is None:
                continue
            reason_counts[decision.reason_code] += 1
            if decision.eligible:
                summary["eligible"] += 1
            else:
                summary["ineligible"] += 1
            if decision.shadow_action == SHADOW_ACTION_WOULD_ACK:
                summary["would_acknowledge"] += 1
            if result.get("audit_written"):
                summary["audits_written"] += 1

        summary["reason_counts"] = dict(reason_counts)
        return summary

    @classmethod
    async def evaluate_and_record(
        cls,
        db: AsyncSession,
        alert: PublishOperatorAlert,
        *,
        expected_tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Evaluate one alert and optionally write a shadow audit row."""
        if expected_tenant_id is not None and alert.tenant_id != expected_tenant_id:
            decision = decision_for_cross_tenant()
            written = await cls._record_shadow(db, alert, decision, skipped_dedupe=False)
            return {"decision": decision, "deduped": False, "audit_written": written}

        attempt = await cls._load_attempt(db, alert)
        newer_success = await cls._newer_success_exists(db, alert, attempt)
        decision = evaluate_auto_ack_candidate(
            alert,
            attempt=attempt,
            newer_success_exists=newer_success,
        )
        fingerprint = decision.evidence.get("fingerprint") or build_state_fingerprint(
            alert, attempt
        )
        if await cls._should_dedupe(db, alert.id, fingerprint):
            return {"decision": decision, "deduped": True, "audit_written": False}

        written = await cls._record_shadow(db, alert, decision, skipped_dedupe=False)
        return {"decision": decision, "deduped": False, "audit_written": written}

    @classmethod
    async def _load_candidate_alerts(
        cls,
        db: AsyncSession,
        *,
        limit: int = MAX_ALERTS_PER_CYCLE,
    ) -> list[PublishOperatorAlert]:
        """Bounded scan: open + allowlisted types only (scale-safe)."""
        rows = (
            await db.execute(
                select(PublishOperatorAlert)
                .where(
                    PublishOperatorAlert.state == "open",
                    PublishOperatorAlert.alert_type.in_(tuple(ALLOWLIST_ALERT_TYPES)),
                )
                .order_by(
                    PublishOperatorAlert.latest_occurred_at.desc(),
                    PublishOperatorAlert.id.desc(),
                )
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    @classmethod
    async def _load_attempt(
        cls,
        db: AsyncSession,
        alert: PublishOperatorAlert,
    ) -> PublishAttempt | None:
        if alert.attempt_id is None:
            return None
        return await db.get(PublishAttempt, alert.attempt_id)

    @classmethod
    async def _newer_success_exists(
        cls,
        db: AsyncSession,
        alert: PublishOperatorAlert,
        attempt: PublishAttempt | None,
    ) -> bool:
        live = await PublishResilienceService.find_live_success(
            db,
            content_id=alert.content_id,
            platform=alert.platform,
            account_id=alert.account_id,
        )
        if live is None:
            return False
        if attempt is None:
            return True
        if live.id == attempt.id:
            return attempt.status == "success"
        live_at = _aware(live.finished_at) or _aware(live.created_at)
        attempt_at = _aware(attempt.finished_at) or _aware(attempt.created_at)
        if live_at and attempt_at:
            return live_at >= attempt_at
        return True

    @classmethod
    async def _should_dedupe(
        cls,
        db: AsyncSession,
        alert_id: UUID,
        fingerprint: str,
    ) -> bool:
        since = _utc_now() - timedelta(hours=DEDUPE_COOLDOWN_HOURS)
        rows = (
            await db.execute(
                select(PlatformAuditLog)
                .where(
                    PlatformAuditLog.event_type == SHADOW_EVENT_TYPE,
                    PlatformAuditLog.resource_type == RESOURCE_TYPE_ALERT,
                    PlatformAuditLog.resource_id == str(alert_id),
                    PlatformAuditLog.created_at >= since,
                )
                .order_by(PlatformAuditLog.created_at.desc())
                .limit(5)
            )
        ).scalars().all()
        for row in rows:
            details = row.details or {}
            evidence = details.get("evidence") or {}
            prior_fp = evidence.get("fingerprint") or details.get("fingerprint")
            if prior_fp == fingerprint:
                return True
        return False

    @classmethod
    async def _record_shadow(
        cls,
        db: AsyncSession,
        alert: PublishOperatorAlert,
        decision: AutoAckDecision,
        *,
        skipped_dedupe: bool,
    ) -> bool:
        details = {
            **decision.to_audit_dict(),
            "evaluated_at": _utc_now().isoformat(),
            "alert_severity": alert.severity,
            "alert_type": alert.alert_type,
            "client_id": str(alert.client_id) if alert.client_id else None,
            "content_id": str(alert.content_id) if alert.content_id else None,
            "attempt_id": str(alert.attempt_id) if alert.attempt_id else None,
            "platform": alert.platform,
            "dedupe_skipped": skipped_dedupe,
            "mode": "shadow",
            "real_auto_ack_enabled": real_auto_ack_enabled(),
            # Explicit proof fields for tests / operators.
            "acknowledge_called": False,
            "alert_mutated": False,
        }
        try:
            await PlatformAuditService.record(
                db,
                actor_type="system",
                event_type=SHADOW_EVENT_TYPE,
                tenant_id=alert.tenant_id,
                resource_type=RESOURCE_TYPE_ALERT,
                resource_id=str(alert.id),
                details=details,
                commit=True,
            )
            return True
        except Exception:
            logger.warning(
                "[AutoAckShadow] audit failed alert_id=%s",
                alert.id,
                exc_info=True,
            )
            return False

    @classmethod
    async def audit_scheduler_cycle(
        cls,
        db: AsyncSession,
        *,
        cycle: int,
        started_at: datetime,
        completed_at: datetime,
        totals: dict[str, Any],
    ) -> None:
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        errors = int(totals.get("errors") or 0)
        await PlatformAuditService.record(
            db,
            actor_type="system",
            event_type=CYCLE_EVENT_TYPE,
            tenant_id=None,
            resource_type="operator_auto_ack",
            resource_id=f"scheduler:cycle:{cycle}",
            details={
                "trigger": "scheduler",
                "cycle": cycle,
                "mode": "shadow",
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "evaluated": int(totals.get("evaluated") or 0),
                "eligible": int(totals.get("eligible") or 0),
                "ineligible": int(totals.get("ineligible") or 0),
                "would_acknowledge": int(totals.get("would_acknowledge") or 0),
                "deduped": int(totals.get("deduped") or 0),
                "errors": errors,
                "audits_written": int(totals.get("audits_written") or 0),
                "reason_counts": dict(totals.get("reason_counts") or {}),
                "outcome": "error" if errors else "success",
                "shadow_enabled": shadow_mode_enabled(),
                "real_auto_ack_enabled": real_auto_ack_enabled(),
                "acknowledge_called": False,
            },
            commit=True,
        )

    @classmethod
    async def build_metrics(
        cls,
        db: AsyncSession,
        *,
        since: datetime,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Aggregate shadow audits + human comparison outcomes (read-only)."""
        query = select(PlatformAuditLog).where(
            PlatformAuditLog.event_type == SHADOW_EVENT_TYPE,
            PlatformAuditLog.created_at >= since,
        )
        if tenant_id is not None:
            query = query.where(PlatformAuditLog.tenant_id == tenant_id)

        rows = list(
            (
                await db.execute(
                    query.order_by(PlatformAuditLog.created_at.desc())
                )
            ).scalars().all()
        )
        if client_id is not None:
            target = str(client_id)
            rows = [
                r for r in rows
                if (r.details or {}).get("client_id") == target
            ]

        evaluated = len(rows)
        eligible = 0
        would_ack = 0
        reason_counts: Counter[str] = Counter()
        severity_counts: Counter[str] = Counter()
        outcomes: list[str] = []
        alert_cache: dict[UUID, PublishOperatorAlert | None] = {}

        for row in rows:
            details = row.details or {}
            reason_counts[str(details.get("reason_code") or "unknown")] += 1
            sev = details.get("alert_severity")
            if sev:
                severity_counts[str(sev)] += 1
            if details.get("eligible"):
                eligible += 1
            if details.get("shadow_action") == SHADOW_ACTION_WOULD_ACK and details.get(
                "eligible"
            ):
                would_ack += 1
                alert_id = None
                try:
                    alert_id = UUID(str(row.resource_id))
                except (TypeError, ValueError):
                    outcomes.append(classify_shadow_outcome(
                        shadow_details=details,
                        shadow_created_at=row.created_at,
                        alert=None,
                    ))
                    continue
                if alert_id not in alert_cache:
                    alert_cache[alert_id] = await db.get(PublishOperatorAlert, alert_id)
                outcomes.append(
                    classify_shadow_outcome(
                        shadow_details=details,
                        shadow_created_at=row.created_at,
                        alert=alert_cache[alert_id],
                    )
                )

        return {
            "available": True,
            "shadow_enabled": shadow_mode_enabled(),
            "real_auto_ack_enabled": real_auto_ack_enabled(),
            "evaluated": evaluated,
            "eligible": eligible,
            "ineligible": max(0, evaluated - eligible),
            "would_acknowledge": would_ack,
            "reason_counts": dict(reason_counts),
            "severity_counts": dict(severity_counts),
            "outcomes": summarize_outcomes(outcomes),
            "notes": (
                "Shadow recommendations only; never mutates alert state. "
                "Isolated from operator_workspace.action counts."
            ),
        }
