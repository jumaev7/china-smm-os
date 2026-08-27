"""Compare shadow would-ack recommendations to later human/system outcomes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.models.publish_operator_alert import PublishOperatorAlert
from app.services.operator_auto_ack.constants import (
    COMPARISON_OBSERVATION_HOURS,
    OUTCOME_DISAGREEMENT,
    OUTCOME_MATCH,
    OUTCOME_PENDING,
    OUTCOME_SAFE_NO_ACTION,
    OUTCOME_STALE,
    OUTCOME_UNKNOWN,
    SHADOW_ACTION_WOULD_ACK,
)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def classify_shadow_outcome(
    *,
    shadow_details: dict[str, Any],
    shadow_created_at: datetime,
    alert: PublishOperatorAlert | None,
    now: datetime | None = None,
    observation_hours: int = COMPARISON_OBSERVATION_HOURS,
) -> str:
    """Deterministic outcome category for a prior shadow would-ack event.

    Does not judge whether the human was "correct" — only how state evolved
    relative to the shadow recommendation.
    """
    now = now or datetime.now(timezone.utc)
    shadow_at = _aware(shadow_created_at) or now
    action = (shadow_details or {}).get("shadow_action")
    eligible = bool((shadow_details or {}).get("eligible"))

    if action != SHADOW_ACTION_WOULD_ACK or not eligible:
        return OUTCOME_UNKNOWN

    if alert is None:
        return OUTCOME_UNKNOWN

    state = (alert.state or "").lower()
    ack_at = _aware(alert.acknowledged_at)
    resolved_at = _aware(alert.resolved_at)
    system_resolved = bool(alert.resolved_by_system)

    # State changed away from open before any ack — often system path or race.
    if state == "resolved":
        if system_resolved and (resolved_at is None or resolved_at >= shadow_at):
            return OUTCOME_SAFE_NO_ACTION
        if resolved_at and resolved_at >= shadow_at:
            # Human (or non-system) resolved instead of acknowledging.
            if ack_at and ack_at >= shadow_at and ack_at <= resolved_at:
                return OUTCOME_MATCH
            return OUTCOME_DISAGREEMENT
        return OUTCOME_STALE

    if state == "acknowledged":
        if ack_at and ack_at >= shadow_at:
            # System never auto-acks today — treat as human match.
            return OUTCOME_MATCH
        return OUTCOME_STALE

    if state == "open":
        deadline = shadow_at + timedelta(hours=observation_hours)
        if now < deadline:
            return OUTCOME_PENDING
        return OUTCOME_UNKNOWN

    return OUTCOME_UNKNOWN


def summarize_outcomes(outcomes: list[str]) -> dict[str, int]:
    counts = {
        OUTCOME_MATCH: 0,
        OUTCOME_SAFE_NO_ACTION: 0,
        OUTCOME_DISAGREEMENT: 0,
        OUTCOME_STALE: 0,
        OUTCOME_UNKNOWN: 0,
        OUTCOME_PENDING: 0,
    }
    for o in outcomes:
        if o in counts:
            counts[o] += 1
        else:
            counts[OUTCOME_UNKNOWN] += 1
    return counts
