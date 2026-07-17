"""Stable error codes for the governed AI platform."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class AIPlatformError(Exception):
    """Base class for governed AI errors with stable machine codes."""

    code: str = "AI_PLATFORM_ERROR"
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


class AIDisabledError(AIPlatformError):
    code = "AI_DISABLED"
    http_status = 503


class AIPolicyBlockedError(AIPlatformError):
    code = "AI_POLICY_BLOCKED"
    http_status = 403


class AIQuotaExceededError(AIPlatformError):
    code = "AI_QUOTA_EXCEEDED"
    http_status = 429


class AIProviderUnavailableError(AIPlatformError):
    code = "AI_PROVIDER_UNAVAILABLE"
    http_status = 503


class AITimeoutError(AIPlatformError):
    code = "AI_TIMEOUT"
    http_status = 504


class AIOutputInvalidError(AIPlatformError):
    code = "AI_OUTPUT_INVALID"
    http_status = 422


class AIFactualValidationFailedError(AIPlatformError):
    code = "AI_FACTUAL_VALIDATION_FAILED"
    http_status = 422


class AISafetyBlockedError(AIPlatformError):
    code = "AI_SAFETY_BLOCKED"
    http_status = 422


class AIIdempotencyConflictError(AIPlatformError):
    code = "AI_IDEMPOTENCY_CONFLICT"
    http_status = 409


class AINotFoundError(AIPlatformError):
    code = "AI_NOT_FOUND"
    http_status = 404


class AISecretInContentError(AIPlatformError):
    code = "AI_SAFETY_BLOCKED"
    http_status = 422
