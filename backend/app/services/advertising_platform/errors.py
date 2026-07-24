"""Errors raised by the advertising platform (provider adapter) layer.

These are intentionally lightweight and provider-facing; the higher-level
``app.services.advertising_intelligence.errors`` module maps them onto the
stable HTTP error contract.
"""
from __future__ import annotations

from typing import Any


class AdvertisingProviderError(Exception):
    code: str = "advertising_provider_error"

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}


class ProviderUnavailableError(AdvertisingProviderError):
    code = "provider_unavailable"


class ProviderUnsupportedError(AdvertisingProviderError):
    """Raised when no adapter exists for a requested provider."""

    code = "provider_unsupported"


class ProviderPermissionBlockedError(AdvertisingProviderError):
    code = "provider_permission_blocked"


class ProviderRateLimitedError(AdvertisingProviderError):
    code = "provider_rate_limited"


class WriteOperationForbiddenError(AdvertisingProviderError):
    """Raised if any mutating operation is ever attempted via this layer.

    The advertising domain is strictly read-only; adapters expose no write
    methods, and this error is the hard backstop for that guarantee.
    """

    code = "write_operation_forbidden"


__all__ = [
    "AdvertisingProviderError",
    "ProviderUnavailableError",
    "ProviderUnsupportedError",
    "ProviderPermissionBlockedError",
    "ProviderRateLimitedError",
    "WriteOperationForbiddenError",
]
