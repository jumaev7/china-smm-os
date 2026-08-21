"""Stable integration-health reason taxonomy (Phase 1).

Reason codes are canonical product vocabulary — never raw provider error strings.
"""
from __future__ import annotations

from typing import Any, Literal

HealthStatus = Literal[
    "healthy",
    "degraded",
    "action_required",
    "unavailable",
    "unknown",
]

Severity = Literal["none", "low", "medium", "high", "critical"]
ResponsibleParty = Literal["operator", "client", "provider", "system"]

# Canonical reason codes (stable; prefer reuse over inventing synonyms).
REASON_HEALTHY = "healthy"
REASON_DISCONNECTED = "disconnected"
REASON_EXPIRED_TOKEN = "expired_token"
REASON_INVALID_TOKEN = "invalid_token"
REASON_MISSING_REQUIRED_SCOPE = "missing_required_scope"
REASON_MISSING_OPTIONAL_SCOPE = "missing_optional_scope"
REASON_PROVIDER_UNREACHABLE = "provider_unreachable"
REASON_PROVIDER_RATE_LIMITED = "provider_rate_limited"
REASON_AUTHORIZATION_REQUIRED = "authorization_required"
REASON_WEBHOOK_NOT_CONFIGURED = "webhook_not_configured"
REASON_WEBHOOK_UNHEALTHY = "webhook_unhealthy"
REASON_ACCOUNT_NOT_FOUND = "account_not_found"
REASON_CAPABILITY_UNAVAILABLE = "capability_unavailable"
REASON_APP_REVIEW_REQUIRED = "app_review_required"
REASON_TRANSIENT_PROVIDER_ERROR = "transient_provider_error"
REASON_STALE_CHECK = "stale_check"
REASON_NEVER_CHECKED = "never_checked"
REASON_MOCK_MODE = "mock_mode"
REASON_NOT_CONFIGURED = "not_configured"
REASON_UNSUPPORTED = "unsupported"
REASON_UNKNOWN = "unknown"

REASON_CODES = frozenset({
    REASON_HEALTHY,
    REASON_DISCONNECTED,
    REASON_EXPIRED_TOKEN,
    REASON_INVALID_TOKEN,
    REASON_MISSING_REQUIRED_SCOPE,
    REASON_MISSING_OPTIONAL_SCOPE,
    REASON_PROVIDER_UNREACHABLE,
    REASON_PROVIDER_RATE_LIMITED,
    REASON_AUTHORIZATION_REQUIRED,
    REASON_WEBHOOK_NOT_CONFIGURED,
    REASON_WEBHOOK_UNHEALTHY,
    REASON_ACCOUNT_NOT_FOUND,
    REASON_CAPABILITY_UNAVAILABLE,
    REASON_APP_REVIEW_REQUIRED,
    REASON_TRANSIENT_PROVIDER_ERROR,
    REASON_STALE_CHECK,
    REASON_NEVER_CHECKED,
    REASON_MOCK_MODE,
    REASON_NOT_CONFIGURED,
    REASON_UNSUPPORTED,
    REASON_UNKNOWN,
})

# Human-readable explanations (backend English; frontend localizes by code).
_REASON_META: dict[str, dict[str, Any]] = {
    REASON_HEALTHY: {
        "status": "healthy",
        "severity": "none",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Connection operational and required capabilities available.",
        "recommended_next_step": "No action required.",
    },
    REASON_DISCONNECTED: {
        "status": "action_required",
        "severity": "high",
        "responsible_party": "operator",
        "requires_operator_action": True,
        "safe_auto_recheck": True,
        "explanation": "Account is disconnected from the platform.",
        "recommended_next_step": "Reconnect the account in Integration Center.",
    },
    REASON_EXPIRED_TOKEN: {
        "status": "action_required",
        "severity": "high",
        "responsible_party": "client",
        "requires_operator_action": True,
        "safe_auto_recheck": True,
        "explanation": "Authorization has expired and must be renewed.",
        "recommended_next_step": "Client or administrator must reconnect the account.",
    },
    REASON_INVALID_TOKEN: {
        "status": "action_required",
        "severity": "high",
        "responsible_party": "client",
        "requires_operator_action": True,
        "safe_auto_recheck": True,
        "explanation": "Access token is invalid or revoked.",
        "recommended_next_step": "Reconnect the account to obtain a valid authorization.",
    },
    REASON_MISSING_REQUIRED_SCOPE: {
        "status": "action_required",
        "severity": "high",
        "responsible_party": "client",
        "requires_operator_action": True,
        "safe_auto_recheck": True,
        "explanation": "Required permissions are missing for this capability.",
        "recommended_next_step": "Reconnect and grant the required permissions.",
    },
    REASON_MISSING_OPTIONAL_SCOPE: {
        "status": "degraded",
        "severity": "medium",
        "responsible_party": "client",
        "requires_operator_action": True,
        "safe_auto_recheck": True,
        "explanation": "Optional capability permissions are missing; core features may still work.",
        "recommended_next_step": "Review capability details and grant optional scopes if needed.",
    },
    REASON_PROVIDER_UNREACHABLE: {
        "status": "unavailable",
        "severity": "medium",
        "responsible_party": "provider",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Provider could not be reached during the health check.",
        "recommended_next_step": "Automatic recheck is scheduled; no operator action yet.",
    },
    REASON_PROVIDER_RATE_LIMITED: {
        "status": "unavailable",
        "severity": "low",
        "responsible_party": "provider",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Provider rate-limited the health check.",
        "recommended_next_step": "Wait for automatic backoff and recheck.",
    },
    REASON_AUTHORIZATION_REQUIRED: {
        "status": "action_required",
        "severity": "high",
        "responsible_party": "client",
        "requires_operator_action": True,
        "safe_auto_recheck": False,
        "explanation": "Interactive authorization or consent is required.",
        "recommended_next_step": "Complete OAuth reconnect / consent in Integration Center.",
    },
    REASON_WEBHOOK_NOT_CONFIGURED: {
        "status": "action_required",
        "severity": "medium",
        "responsible_party": "operator",
        "requires_operator_action": True,
        "safe_auto_recheck": True,
        "explanation": "Webhook is not configured as expected.",
        "recommended_next_step": "Verify webhook configuration with platform ops.",
    },
    REASON_WEBHOOK_UNHEALTHY: {
        "status": "degraded",
        "severity": "medium",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Recent webhook delivery or processing failures were observed.",
        "recommended_next_step": "Review Telegram/webhook diagnostics; automatic recheck continues.",
    },
    REASON_ACCOUNT_NOT_FOUND: {
        "status": "action_required",
        "severity": "high",
        "responsible_party": "operator",
        "requires_operator_action": True,
        "safe_auto_recheck": False,
        "explanation": "Linked provider account or page was not found.",
        "recommended_next_step": "Reconnect and select a valid account/page.",
    },
    REASON_CAPABILITY_UNAVAILABLE: {
        "status": "degraded",
        "severity": "medium",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "A non-critical capability is unavailable.",
        "recommended_next_step": "Review capability details; publishing may still be healthy.",
    },
    REASON_APP_REVIEW_REQUIRED: {
        "status": "degraded",
        "severity": "medium",
        "responsible_party": "operator",
        "requires_operator_action": True,
        "safe_auto_recheck": True,
        "explanation": "Provider App Review / Advanced Access is required for this capability.",
        "recommended_next_step": "Complete Meta App Review for Listening scopes, then reconnect.",
    },
    REASON_TRANSIENT_PROVIDER_ERROR: {
        "status": "degraded",
        "severity": "low",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Temporary provider error during health check.",
        "recommended_next_step": "Automatic recheck scheduled; no operator action yet.",
    },
    REASON_STALE_CHECK: {
        "status": "unknown",
        "severity": "low",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Last health evidence is stale and should not be treated as current.",
        "recommended_next_step": "Wait for the next automatic health check.",
    },
    REASON_NEVER_CHECKED: {
        "status": "unknown",
        "severity": "low",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "No health check has completed yet.",
        "recommended_next_step": "Wait for the first automatic health check.",
    },
    REASON_MOCK_MODE: {
        "status": "degraded",
        "severity": "low",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Integration is in mock/demo mode.",
        "recommended_next_step": "Connect a live account when ready for production use.",
    },
    REASON_NOT_CONFIGURED: {
        "status": "unknown",
        "severity": "none",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Integration is not configured for this tenant/client.",
        "recommended_next_step": "Configure the integration when needed.",
    },
    REASON_UNSUPPORTED: {
        "status": "unknown",
        "severity": "none",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": False,
        "explanation": "Live health probing is not supported for this provider yet.",
        "recommended_next_step": "Rely on local configuration status until probing is available.",
    },
    REASON_UNKNOWN: {
        "status": "unknown",
        "severity": "low",
        "responsible_party": "system",
        "requires_operator_action": False,
        "safe_auto_recheck": True,
        "explanation": "Insufficient evidence to classify integration health.",
        "recommended_next_step": "Re-run health check or inspect Integration Center details.",
    },
}


def reason_meta(reason_code: str) -> dict[str, Any]:
    code = reason_code if reason_code in REASON_CODES else REASON_UNKNOWN
    return dict(_REASON_META[code])


def map_account_status_to_reason(status: str) -> str:
    """Map persisted PublishingAccount.status to a reason code."""
    mapping = {
        "connected": REASON_HEALTHY,
        "mock": REASON_MOCK_MODE,
        "disconnected": REASON_DISCONNECTED,
        "expired": REASON_EXPIRED_TOKEN,
        "invalid": REASON_INVALID_TOKEN,
        "missing_permissions": REASON_MISSING_REQUIRED_SCOPE,
        "blocked": REASON_ACCOUNT_NOT_FOUND,
    }
    return mapping.get(status, REASON_UNKNOWN)


# Transient escalation (deterministic; no LLM).
TRANSIENT_ESCALATION_THRESHOLD = 3
TRANSIENT_WINDOW_SECONDS = 2 * 60 * 60

# Freshness defaults (seconds).
STALE_AFTER_LOCAL_SECONDS = 6 * 60 * 60  # local/config checks
STALE_AFTER_REMOTE_SECONDS = 12 * 60 * 60  # provider remote probes
STALE_AFTER_TELEGRAM_SECONDS = 6 * 60 * 60
STALE_AFTER_ADS_SECONDS = 24 * 60 * 60
STALE_AFTER_LISTENING_SECONDS = 12 * 60 * 60
