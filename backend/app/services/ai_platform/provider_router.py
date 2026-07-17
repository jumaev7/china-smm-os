"""Deterministic, explainable provider routing (no ML)."""
from __future__ import annotations

from app.core.config import settings
from app.services.ai_platform.errors import AIDisabledError, AIPolicyBlockedError, AIProviderUnavailableError
from app.services.ai_platform.provider_registry import (
    get_provider,
    is_platform_enabled,
    resolve_model_for_alias,
)
from app.services.ai_platform.schemas import ROUTING_VERSION_DEFAULT, RoutingDecision


def route_provider(
    *,
    task_type: str,
    model_alias: str,
    allow_fallback: bool = False,
    tenant_allow_fallback: bool = False,
) -> RoutingDecision:
    """Route ``ai_content_adaptation`` to configured primary provider.

    Does not silently switch providers when tenant policy forbids fallback.
    """
    if not settings.AI_PLATFORM_ENABLED and (settings.AI_DEFAULT_PROVIDER or "").lower() != "mock":
        if not is_platform_enabled():
            raise AIDisabledError("Governed AI platform is disabled")

    # When AI_PLATFORM_ENABLED is false but mock is default, still allow for local/tests
    # only if caller explicitly enabled via settings or mock default with enabled flag.
    primary = (settings.AI_DEFAULT_PROVIDER or "mock").strip().lower()
    if not settings.AI_PLATFORM_ENABLED and primary != "mock":
        raise AIDisabledError("Governed AI platform is disabled")
    if not settings.AI_PLATFORM_ENABLED and primary == "mock":
        # Require explicit enable for production-like paths; tests set AI_PLATFORM_ENABLED.
        # Adaptation service will set enabled via tenant policy + settings check.
        pass

    routing_version = settings.AI_ROUTING_VERSION or ROUTING_VERSION_DEFAULT
    try:
        get_provider(primary)
    except AIProviderUnavailableError:
        raise

    resolved = resolve_model_for_alias(primary, model_alias)
    return RoutingDecision(
        provider=primary,
        model_alias=model_alias,
        resolved_model=resolved,
        routing_version=routing_version,
        fallback_used=False,
        reason="configured_default",
    )


def route_with_optional_fallback(
    *,
    task_type: str,
    model_alias: str,
    primary_failed: bool,
    allow_fallback: bool,
    tenant_allow_fallback: bool,
) -> RoutingDecision | None:
    if not primary_failed:
        return None
    if not allow_fallback or not tenant_allow_fallback:
        raise AIPolicyBlockedError(
            "Fallback provider is not allowed by policy",
            details={"allow_fallback": allow_fallback, "tenant_allow_fallback": tenant_allow_fallback},
        )
    fallback = (settings.AI_FALLBACK_PROVIDER or "").strip().lower()
    if not fallback:
        raise AIProviderUnavailableError("No fallback provider configured")
    get_provider(fallback)
    resolved = resolve_model_for_alias(fallback, model_alias)
    return RoutingDecision(
        provider=fallback,
        model_alias=model_alias,
        resolved_model=resolved,
        routing_version=settings.AI_ROUTING_VERSION or ROUTING_VERSION_DEFAULT,
        fallback_used=True,
        reason="configured_fallback",
    )
