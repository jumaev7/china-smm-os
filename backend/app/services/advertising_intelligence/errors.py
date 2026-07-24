"""Stable, typed errors for the Advertising Intelligence services.

Mirrors ``app.services.measurement.errors``: every error carries a
machine-stable ``code`` plus an HTTP status so the API surface is consistent.

Two invariants worth calling out:
- Cross-tenant access always resolves to 404 (``AdCrossTenantReferenceError``)
  so callers can never distinguish "not found" from "not yours".
- This domain is strictly read-only. Any attempt to route a mutating operation
  through it raises ``AdReadOnlyOperationError`` (409).
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class AdvertisingError(Exception):
    code: str = "advertising_error"
    http_status: int = 400

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}

    def to_http(self) -> HTTPException:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return HTTPException(status_code=self.http_status, detail=payload)


# ---------------------------------------------------------------------------
# Feature gating (403)
# ---------------------------------------------------------------------------


class AdvertisingDisabledError(AdvertisingError):
    code = "ADVERTISING_DISABLED"
    http_status = 403


class AdPermissionBlockedError(AdvertisingError):
    code = "AD_PERMISSION_BLOCKED"
    http_status = 403


class AdReadOnlyOperationError(AdvertisingError):
    """Raised if any mutating/provider-write path is ever attempted."""

    code = "AD_READ_ONLY_OPERATION"
    http_status = 409


# ---------------------------------------------------------------------------
# Not-found family (404) — cross-tenant collapses to 404 here
# ---------------------------------------------------------------------------


class AdAccountNotFoundError(AdvertisingError):
    code = "AD_ACCOUNT_NOT_FOUND"
    http_status = 404


class AdCrossTenantReferenceError(AdvertisingError):
    """Cross-tenant references are indistinguishable from not-found (404)."""

    code = "AD_CROSS_TENANT_REFERENCE"
    http_status = 404


class AdAttributionUnavailableError(AdvertisingError):
    code = "AD_ATTRIBUTION_UNAVAILABLE"
    http_status = 404


# ---------------------------------------------------------------------------
# Connection / state (409)
# ---------------------------------------------------------------------------


class AdAccountDisconnectedError(AdvertisingError):
    code = "AD_ACCOUNT_DISCONNECTED"
    http_status = 409


class AdImportAlreadyRunningError(AdvertisingError):
    code = "AD_IMPORT_ALREADY_RUNNING"
    http_status = 409


class AdLinkConflictError(AdvertisingError):
    code = "AD_LINK_CONFLICT"
    http_status = 409


# ---------------------------------------------------------------------------
# Provider availability / support (409 / 422 / 503)
# ---------------------------------------------------------------------------


class AdProviderUnavailableError(AdvertisingError):
    code = "AD_PROVIDER_UNAVAILABLE"
    http_status = 503


class AdProviderUnsupportedError(AdvertisingError):
    code = "AD_PROVIDER_UNSUPPORTED"
    http_status = 422


class AdMetricsUnsupportedError(AdvertisingError):
    code = "AD_METRICS_UNSUPPORTED"
    http_status = 422


# ---------------------------------------------------------------------------
# Import / ingestion outcomes
# ---------------------------------------------------------------------------


class AdImportPartialError(AdvertisingError):
    code = "AD_IMPORT_PARTIAL"
    http_status = 409


class AdImportFailedError(AdvertisingError):
    code = "AD_IMPORT_FAILED"
    http_status = 502


# ---------------------------------------------------------------------------
# Freshness (409)
# ---------------------------------------------------------------------------


class AdMetricsStaleError(AdvertisingError):
    code = "AD_METRICS_STALE"
    http_status = 409


# ---------------------------------------------------------------------------
# Rate limiting (429)
# ---------------------------------------------------------------------------


class AdRefreshRateLimitedError(AdvertisingError):
    code = "AD_REFRESH_RATE_LIMITED"
    http_status = 429


# ---------------------------------------------------------------------------
# Validation (422)
# ---------------------------------------------------------------------------


class AdInvalidDateRangeError(AdvertisingError):
    code = "AD_INVALID_DATE_RANGE"
    http_status = 422


class AdInvalidBreakdownError(AdvertisingError):
    code = "AD_INVALID_BREAKDOWN"
    http_status = 422


class AdCurrencyMismatchError(AdvertisingError):
    code = "AD_CURRENCY_MISMATCH"
    http_status = 422


# ---------------------------------------------------------------------------
# Registry mapping code -> class (stable contract for API layer)
# ---------------------------------------------------------------------------

ERROR_CODE_TO_CLASS: dict[str, type[AdvertisingError]] = {
    cls.code: cls
    for cls in (
        AdvertisingDisabledError,
        AdAccountNotFoundError,
        AdAccountDisconnectedError,
        AdPermissionBlockedError,
        AdProviderUnavailableError,
        AdProviderUnsupportedError,
        AdImportAlreadyRunningError,
        AdImportPartialError,
        AdImportFailedError,
        AdMetricsUnsupportedError,
        AdMetricsStaleError,
        AdRefreshRateLimitedError,
        AdInvalidDateRangeError,
        AdInvalidBreakdownError,
        AdCurrencyMismatchError,
        AdAttributionUnavailableError,
        AdLinkConflictError,
        AdCrossTenantReferenceError,
        AdReadOnlyOperationError,
    )
}


__all__ = [
    "AdvertisingError",
    "AdvertisingDisabledError",
    "AdAccountNotFoundError",
    "AdAccountDisconnectedError",
    "AdPermissionBlockedError",
    "AdProviderUnavailableError",
    "AdProviderUnsupportedError",
    "AdImportAlreadyRunningError",
    "AdImportPartialError",
    "AdImportFailedError",
    "AdMetricsUnsupportedError",
    "AdMetricsStaleError",
    "AdRefreshRateLimitedError",
    "AdInvalidDateRangeError",
    "AdInvalidBreakdownError",
    "AdCurrencyMismatchError",
    "AdAttributionUnavailableError",
    "AdLinkConflictError",
    "AdCrossTenantReferenceError",
    "AdReadOnlyOperationError",
    "ERROR_CODE_TO_CLASS",
]
