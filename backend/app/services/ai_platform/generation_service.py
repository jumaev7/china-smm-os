"""Governed generation orchestration — provider calls only through adapters."""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.ai_platform.errors import (
    AIDisabledError,
    AIOutputInvalidError,
    AIProviderUnavailableError,
    AITimeoutError,
)
from app.services.ai_platform.provider_registry import get_provider, is_platform_enabled
from app.services.ai_platform.provider_router import route_provider, route_with_optional_fallback
from app.services.ai_platform.rate_catalog import estimate_cost_minor
from app.services.ai_platform.schemas import AIProviderRequest, AIProviderResponse, RoutingDecision
from app.services.ai_platform.structured_output import parse_structured_output
from app.services.ai_platform.usage_meter import inc, observe_latency_ms

logger = logging.getLogger(__name__)


class GenerationService:
    """Routes and invokes providers; never called directly from publishing modules."""

    @staticmethod
    def ensure_enabled() -> None:
        if not settings.AI_PLATFORM_ENABLED:
            raise AIDisabledError("Governed AI platform is disabled")
        # Mock is always usable when enabled; openai needs a key.
        primary = (settings.AI_DEFAULT_PROVIDER or "mock").strip().lower()
        if primary == "openai" and not is_platform_enabled():
            raise AIProviderUnavailableError("OpenAI provider is not configured")

    @staticmethod
    async def generate_structured(
        *,
        tenant_id: str,
        task_type: str,
        model_alias: str,
        system_instructions: str,
        input_messages: list[dict[str, str]],
        output_schema: dict[str, Any],
        temperature: float,
        max_output_tokens: int,
        metadata: dict[str, Any] | None = None,
        allow_fallback: bool = False,
        tenant_allow_fallback: bool = False,
        parse_output: bool = True,
    ) -> tuple[AIProviderResponse, RoutingDecision, Any | None]:
        GenerationService.ensure_enabled()
        routing = route_provider(
            task_type=task_type,
            model_alias=model_alias,
            allow_fallback=allow_fallback,
            tenant_allow_fallback=tenant_allow_fallback,
        )
        provider = get_provider(routing.provider)
        req = AIProviderRequest(
            provider_request_id=str(uuid4()),
            tenant_id=tenant_id,
            task_type=task_type,
            model_alias=model_alias,
            system_instructions=system_instructions,
            input_messages=input_messages,
            output_schema=output_schema,
            temperature=temperature,
            max_output_tokens=min(max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS),
            timeout_seconds=settings.AI_REQUEST_TIMEOUT_SECONDS,
            metadata=metadata or {},
            resolved_model=routing.resolved_model,
        )
        inc("ai_requests_total", provider=routing.provider, task_type=task_type, model_alias=model_alias)
        response = await provider.generate_structured(req)

        if response.status in ("provider_failed", "timeout") and (
            allow_fallback and tenant_allow_fallback and settings.AI_FALLBACK_PROVIDER
        ):
            try:
                fallback_routing = route_with_optional_fallback(
                    task_type=task_type,
                    model_alias=model_alias,
                    primary_failed=True,
                    allow_fallback=allow_fallback,
                    tenant_allow_fallback=tenant_allow_fallback,
                )
            except Exception:
                fallback_routing = None
            if fallback_routing is not None:
                routing = fallback_routing
                provider = get_provider(routing.provider)
                req = AIProviderRequest(
                    provider_request_id=str(uuid4()),
                    tenant_id=tenant_id,
                    task_type=task_type,
                    model_alias=model_alias,
                    system_instructions=system_instructions,
                    input_messages=input_messages,
                    output_schema=output_schema,
                    temperature=temperature,
                    max_output_tokens=min(max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS),
                    timeout_seconds=settings.AI_REQUEST_TIMEOUT_SECONDS,
                    metadata=metadata or {},
                    resolved_model=routing.resolved_model,
                )
                response = await provider.generate_structured(req)

        observe_latency_ms(response.latency_ms, provider=routing.provider, status=response.status)

        if response.status == "timeout" or response.error_code == "AI_TIMEOUT":
            inc("ai_requests_failed_total", provider=routing.provider, status="timeout")
            raise AITimeoutError("AI provider timed out")
        if response.status == "provider_failed":
            inc("ai_requests_failed_total", provider=routing.provider, status="provider_failed")
            raise AIProviderUnavailableError(
                response.error_message or "AI provider unavailable",
            )
        if response.status == "invalid_output" or response.structured_output is None:
            inc("ai_requests_failed_total", provider=routing.provider, status="invalid_output")
            raise AIOutputInvalidError("Provider returned invalid structured output")

        parsed = None
        if parse_output:
            parsed = parse_structured_output(response.structured_output)

        inc("ai_requests_success_total", provider=routing.provider, task_type=task_type)
        inc("ai_input_tokens_total", amount=response.input_tokens)
        inc("ai_output_tokens_total", amount=response.output_tokens)
        cost, _, _ = estimate_cost_minor(
            routing.provider, routing.resolved_model, response.input_tokens, response.output_tokens,
        )
        if cost:
            inc("ai_estimated_cost_minor_total", amount=cost)
        # Never log keys, prompts, or captions.
        logger.info(
            "ai_generation_ok provider=%s model_alias=%s tokens=%s",
            routing.provider,
            model_alias,
            response.total_tokens,
        )
        return response, routing, parsed
