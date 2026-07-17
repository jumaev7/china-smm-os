"""Abstract provider interface for the governed AI platform."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.ai_platform.schemas import (
    AIProviderHealth,
    AIProviderRequest,
    AIProviderResponse,
    AIUsageEstimate,
)


class AIProvider(ABC):
    """Strict provider contract — adapters only; no publishing/API callers."""

    name: str

    @abstractmethod
    async def generate_structured(self, request: AIProviderRequest) -> AIProviderResponse:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> AIProviderHealth:
        raise NotImplementedError

    @abstractmethod
    def estimate_usage(self, request: AIProviderRequest) -> AIUsageEstimate:
        raise NotImplementedError
