"""Constants for guarded acknowledge_alert shadow evaluation."""
from __future__ import annotations

# PlatformAuditLog.event_type max length is 50.
SHADOW_EVENT_TYPE = "operator_workspace.auto_ack_shadow"
CYCLE_EVENT_TYPE = "operator_workspace.auto_ack_cycle"

# Distinct from human Workspace actions — never inflate operator_workspace.action counts.
RESOURCE_TYPE_ALERT = "publish_operator_alert"

# Initial allowlist — intentionally tiny. Expand only after shadow observation.
ALLOWLIST_ALERT_TYPES = frozenset({"stale_in_progress"})

EXCLUDED_ALERT_TYPES = frozenset({
    "operator_review",
    "exhausted",
    "terminal_failure",
    "repeated_failure",
    "recovery",
})

EXCLUDED_FAILURE_CODES = frozenset({
    "auth_or_permission",
    "credential_decryption_failed",
    "account_unavailable",
    "publish_blocked",
})

# Meta ambiguous / operator-review paths — never auto-ack candidates.
AMBIGUOUS_FAILURE_CODES = frozenset({
    "publish_timeout",
    "connection_error",
    "stale_in_progress",
})

SAFETY_LEVEL_ALLOWLIST = "A_shadow_bookkeeping"
SAFETY_LEVEL_INELIGIBLE = "ineligible"

SHADOW_ACTION_WOULD_ACK = "would_acknowledge"
SHADOW_ACTION_SKIP = "skip"

# Human comparison outcomes (deterministic; not a correctness judgment of humans).
OUTCOME_MATCH = "MATCH"
OUTCOME_SAFE_NO_ACTION = "SAFE_NO_ACTION"
OUTCOME_DISAGREEMENT = "DISAGREEMENT"
OUTCOME_STALE = "STALE"
OUTCOME_UNKNOWN = "UNKNOWN"
OUTCOME_PENDING = "PENDING"

# Batch / cadence bounds.
MAX_ALERTS_PER_CYCLE = 50
DEDUPE_COOLDOWN_HOURS = 6
COMPARISON_OBSERVATION_HOURS = 168  # 7d
INTERVAL_SECONDS = 60 * 60  # 1 hour
