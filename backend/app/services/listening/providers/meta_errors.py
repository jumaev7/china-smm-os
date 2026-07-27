"""Sanitize Meta Graph errors for listening — never leak tokens or payloads."""
from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(
    r"(access_token|authorization|bearer|fb_exchange_token)=([^\s&\"']+)",
    re.IGNORECASE,
)
_LONG_HEX_RE = re.compile(r"\b[A-Za-z0-9_-]{40,}\b")

# Public health / failure codes exposed to API/UI (never raw Meta payloads).
SANITIZED_ERROR_CODES = frozenset({
    "missing_scope",
    "insufficient_app_access",
    "page_not_authorized",
    "token_expired_or_revoked",
    "rate_limited",
    "provider_unavailable",
    "unsupported_capability",
    "invalid_configuration",
    "missing_credentials",
    "malformed_provider_response",
    "internal_processing_failure",
})


class MetaListeningError(Exception):
    """Typed Meta listening failure with a safe public code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        provider_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code if code in SANITIZED_ERROR_CODES else "provider_unavailable"
        self.retryable = retryable
        self.http_status = http_status
        self.provider_code = provider_code


def sanitize_error_text(text: str | None) -> str:
    """Redact secrets; never return Meta error payloads to clients."""
    if not text:
        return "provider_error"
    cleaned = _TOKEN_RE.sub(r"\1=[REDACTED]", str(text))
    cleaned = _LONG_HEX_RE.sub("[REDACTED]", cleaned)
    return cleaned[:500]


def public_failure_summary(code: str) -> str:
    """Stable operator-facing summary — no provider message leakage."""
    mapping = {
        "missing_scope": "Required permission is missing on the Page access token",
        "insufficient_app_access": (
            "App lacks Advanced Access / App Review approval for this capability"
        ),
        "page_not_authorized": (
            "Page is not authorized for this capability (Page task or binding)"
        ),
        "token_expired_or_revoked": "Page access token is expired or revoked",
        "rate_limited": "Meta Graph rate limit reached; retry later",
        "provider_unavailable": "Meta Graph is temporarily unavailable",
        "unsupported_capability": "This listening capability is not supported",
        "invalid_configuration": "Listening source configuration is invalid",
        "missing_credentials": "Authorized Page credentials are unavailable",
        "malformed_provider_response": "Meta Graph returned an unexpected response",
        "internal_processing_failure": "Internal listening processing failure",
    }
    return mapping.get(code, "Listening provider failure")


def classify_meta_error(
    *,
    http_status: int | None,
    payload: dict[str, Any] | None,
    fallback: str = "provider_unavailable",
) -> MetaListeningError:
    """Map Meta Graph errors to sanitized codes. Discard raw provider text from clients."""
    error = (payload or {}).get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        error = {}
    provider_code = error.get("code")
    try:
        provider_code_int = int(provider_code) if provider_code is not None else None
    except (TypeError, ValueError):
        provider_code_int = None
    subcode = error.get("error_subcode")
    try:
        subcode_int = int(subcode) if subcode is not None else None
    except (TypeError, ValueError):
        subcode_int = None
    raw_message = str(error.get("message") or "")
    lower = raw_message.lower()
    # Keep a redacted copy for logs only; public summary uses public_failure_summary.
    safe_message = public_failure_summary(fallback)

    # Token expired / revoked / invalid OAuth
    if (
        provider_code_int in {190, 102}
        or http_status == 401
        or subcode_int in {463, 467, 460, 458}
        or "session has expired" in lower
        or "access token" in lower and ("expired" in lower or "revoked" in lower or "invalid" in lower)
    ):
        return MetaListeningError(
            "token_expired_or_revoked",
            public_failure_summary("token_expired_or_revoked"),
            retryable=False,
            http_status=http_status,
            provider_code=provider_code_int,
        )

    # Rate limits (Graph + Page-level)
    if provider_code_int in {4, 17, 32, 613, 80001} or http_status == 429:
        return MetaListeningError(
            "rate_limited",
            public_failure_summary("rate_limited"),
            retryable=True,
            http_status=http_status,
            provider_code=provider_code_int,
        )

    # App access / Advanced Access / App Review (not merely a missing OAuth scope string)
    if (
        "advanced access" in lower
        or "app review" in lower
        or "not been approved" in lower
        or "not approved" in lower
        or "standard access" in lower
        or "access level" in lower
        or (provider_code_int == 10 and "application" in lower)
    ):
        return MetaListeningError(
            "insufficient_app_access",
            public_failure_summary("insufficient_app_access"),
            retryable=False,
            http_status=http_status,
            provider_code=provider_code_int,
        )

    # Page / task authorization (user cannot act on this Page)
    if (
        "pages_read" in lower and "does not have permission" in lower
        or "not authorized" in lower
        or "does not have permission to" in lower and "page" in lower
        or subcode_int in {33}  # page/object unavailable / unsupported get request
        or "unsupported get request" in lower
        or provider_code_int == 210
    ):
        return MetaListeningError(
            "page_not_authorized",
            public_failure_summary("page_not_authorized"),
            retryable=False,
            http_status=http_status,
            provider_code=provider_code_int,
        )

    # Missing OAuth scope on token (permission/scope language without app-review markers)
    if provider_code_int in {200, 283} or (
        http_status == 403 and ("permission" in lower or "scope" in lower)
    ):
        if "permission" in lower or "scope" in lower or provider_code_int == 283:
            return MetaListeningError(
                "missing_scope",
                public_failure_summary("missing_scope"),
                retryable=False,
                http_status=http_status,
                provider_code=provider_code_int,
            )
        return MetaListeningError(
            "page_not_authorized",
            public_failure_summary("page_not_authorized"),
            retryable=False,
            http_status=http_status,
            provider_code=provider_code_int,
        )

    if http_status is not None and http_status >= 500:
        return MetaListeningError(
            "provider_unavailable",
            public_failure_summary("provider_unavailable"),
            retryable=True,
            http_status=http_status,
            provider_code=provider_code_int,
        )

    if provider_code_int == 100:
        return MetaListeningError(
            "malformed_provider_response",
            public_failure_summary("malformed_provider_response"),
            retryable=False,
            http_status=http_status,
            provider_code=provider_code_int,
        )

    # Fall back without exposing provider message text.
    code = fallback if fallback in SANITIZED_ERROR_CODES else "provider_unavailable"
    _ = safe_message  # retained for clarity; public_failure_summary used below
    return MetaListeningError(
        code,
        public_failure_summary(code),
        retryable=http_status is not None and http_status >= 500,
        http_status=http_status,
        provider_code=provider_code_int,
    )


__all__ = [
    "MetaListeningError",
    "SANITIZED_ERROR_CODES",
    "sanitize_error_text",
    "public_failure_summary",
    "classify_meta_error",
]
