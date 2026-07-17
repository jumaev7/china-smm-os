"""Model-alias resolution and provider registry."""
from __future__ import annotations

from app.core.config import settings
from app.services.ai_platform.errors import AIDisabledError, AIProviderUnavailableError
from app.services.ai_platform.providers.base import AIProvider
from app.services.ai_platform.providers.mock import MockAIProvider
from app.services.ai_platform.providers.openai_provider import OpenAIProvider
from app.services.ai_platform.schemas import MODEL_ALIASES


_MOCK = MockAIProvider()
_OPENAI = OpenAIProvider()
_REGISTRY: dict[str, AIProvider] = {
    "mock": _MOCK,
    "openai": _OPENAI,
}


def get_mock_provider() -> MockAIProvider:
    return _MOCK


def list_providers() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_provider(name: str) -> AIProvider:
    provider = _REGISTRY.get(name)
    if provider is None:
        raise AIProviderUnavailableError(
            f"Unknown provider: {name}",
            details={"provider": name},
        )
    return provider


def resolve_model_for_alias(provider: str, model_alias: str) -> str:
    if model_alias not in MODEL_ALIASES:
        raise AIDisabledError(
            "Invalid model alias",
            details={"model_alias": model_alias, "allowed": list(MODEL_ALIASES)},
        )
    if provider == "mock":
        return {
            "content_fast": "mock-content-fast",
            "content_standard": "mock-content-standard",
            "content_high_quality": "mock-content-high",
        }[model_alias]
    # openai
    return {
        "content_fast": settings.AI_CONTENT_MODEL_FAST,
        "content_standard": settings.AI_CONTENT_MODEL_STANDARD,
        "content_high_quality": settings.AI_CONTENT_MODEL_HIGH_QUALITY,
    }[model_alias]


def quality_mode_to_alias(quality_mode: str | None) -> str:
    mapping = {
        None: "content_standard",
        "": "content_standard",
        "fast": "content_fast",
        "standard": "content_standard",
        "high": "content_high_quality",
        "high_quality": "content_high_quality",
        "content_fast": "content_fast",
        "content_standard": "content_standard",
        "content_high_quality": "content_high_quality",
    }
    alias = mapping.get((quality_mode or "").strip().lower() if quality_mode else None)
    if alias is None:
        raise AIDisabledError(
            "Unsupported quality mode",
            details={"quality_mode": quality_mode},
        )
    return alias


def is_platform_enabled() -> bool:
    """AI is enabled only when explicitly flagged and a usable default provider exists."""
    if not settings.AI_PLATFORM_ENABLED:
        # Allow mock-driven verification when default provider is mock even if flag false?
        # Spec: secure defaults — AI disabled when no provider configured.
        # For tests, callers set AI_PLATFORM_ENABLED=true or use ensure_policy.
        return False
    provider_name = (settings.AI_DEFAULT_PROVIDER or "").strip().lower()
    if provider_name not in _REGISTRY:
        return False
    if provider_name == "openai":
        key = (settings.AI_OPENAI_API_KEY or settings.OPENAI_API_KEY or "").strip()
        if not key.startswith("sk-") or key.startswith("sk-your"):
            return False
    return True


def platform_enabled_for_tests() -> bool:
    """Test helper: treat mock default as enabled when flag is on OR default is mock."""
    if settings.AI_PLATFORM_ENABLED:
        return is_platform_enabled() or (settings.AI_DEFAULT_PROVIDER or "").lower() == "mock"
    return False
