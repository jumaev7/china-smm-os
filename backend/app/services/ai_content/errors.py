"""AI content adaptation errors."""
from __future__ import annotations

from app.services.ai_platform.errors import (
    AIDisabledError,
    AIFactualValidationFailedError,
    AIIdempotencyConflictError,
    AINotFoundError,
    AIOutputInvalidError,
    AIPlatformError,
    AIPolicyBlockedError,
    AIProviderUnavailableError,
    AIQuotaExceededError,
    AISafetyBlockedError,
    AISecretInContentError,
    AITimeoutError,
)

__all__ = [
    "AIPlatformError",
    "AIDisabledError",
    "AIPolicyBlockedError",
    "AIQuotaExceededError",
    "AIProviderUnavailableError",
    "AITimeoutError",
    "AIOutputInvalidError",
    "AIFactualValidationFailedError",
    "AISafetyBlockedError",
    "AIIdempotencyConflictError",
    "AINotFoundError",
    "AISecretInContentError",
]
