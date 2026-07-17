"""Stable, typed errors for the deterministic Content Optimizer.

Every error carries a machine-stable ``code`` plus an HTTP status so routers can
surface a consistent contract. Provenance and profile-support failures are *not*
raised here — they are recorded on the variant so a run can partially succeed.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class ContentOptimizerError(Exception):
    """Base class for optimizer errors with a stable code and HTTP status."""

    code: str = "content_optimizer_error"
    http_status: int = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}

    def to_http(self) -> HTTPException:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return HTTPException(status_code=self.http_status, detail=payload)


class ContentNotFoundError(ContentOptimizerError):
    code = "content_not_found"
    http_status = 404


class OptimizationRunNotFoundError(ContentOptimizerError):
    code = "optimization_run_not_found"
    http_status = 404


class VariantNotFoundError(ContentOptimizerError):
    code = "variant_not_found"
    http_status = 404


class TemplateNotFoundError(ContentOptimizerError):
    code = "template_not_found"
    http_status = 404


class SourceContentInsufficientError(ContentOptimizerError):
    code = "source_content_insufficient"
    http_status = 422


class SourceContentTooLargeError(ContentOptimizerError):
    code = "source_content_too_large"
    http_status = 422


class UnsupportedLocaleError(ContentOptimizerError):
    code = "unsupported_locale"
    http_status = 422


class UnsupportedPlatformError(ContentOptimizerError):
    code = "unsupported_platform"
    http_status = 422


class UnsupportedLengthProfileError(ContentOptimizerError):
    code = "unsupported_length_profile"
    http_status = 422


class OptimizationLimitExceededError(ContentOptimizerError):
    code = "optimization_limit_exceeded"
    http_status = 422


class VariantStateError(ContentOptimizerError):
    code = "variant_invalid_state"
    http_status = 409


class SourceFingerprintMismatchError(ContentOptimizerError):
    code = "source_fingerprint_mismatch"
    http_status = 409


class TemplateValidationError(ContentOptimizerError):
    code = "template_invalid"
    http_status = 422


class TemplateLimitExceededError(ContentOptimizerError):
    code = "template_limit_exceeded"
    http_status = 422


class ProvenanceViolationError(ContentOptimizerError):
    """Raised only by strict internal callers; the run flow records it instead."""

    code = "provenance_violation"
    http_status = 422
