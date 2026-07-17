"""Optional OpenAI provider adapter — lazy SDK import; never a hard dependency for non-AI paths."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.services.ai_platform.providers.base import AIProvider
from app.services.ai_platform.schemas import (
    AIProviderHealth,
    AIProviderRequest,
    AIProviderResponse,
    AIUsageEstimate,
)

logger = logging.getLogger(__name__)


def _api_key_configured() -> bool:
    key = (settings.AI_OPENAI_API_KEY or settings.OPENAI_API_KEY or "").strip()
    if not key or key.startswith("sk-your") or key == "your-key-here":
        return False
    return key.startswith("sk-")


class OpenAIProvider(AIProvider):
    name = "openai"

    def _resolve_key(self) -> str | None:
        key = (settings.AI_OPENAI_API_KEY or "").strip()
        if key and key.startswith("sk-") and not key.startswith("sk-your"):
            return key
        legacy = (settings.OPENAI_API_KEY or "").strip()
        if legacy and legacy.startswith("sk-") and not legacy.startswith("sk-your"):
            return legacy
        return None

    async def generate_structured(self, request: AIProviderRequest) -> AIProviderResponse:
        started = time.perf_counter()
        now = datetime.now(timezone.utc)
        key = self._resolve_key()
        if not key:
            return AIProviderResponse(
                provider=self.name,
                model=request.resolved_model or "unknown",
                provider_request_id=request.provider_request_id,
                provider_response_id=None,
                status="provider_failed",
                structured_output=None,
                raw_text_hash=None,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                finish_reason="error",
                safety_metadata={},
                created_at=now,
                error_code="AI_PROVIDER_UNAVAILABLE",
                error_message="OpenAI API key not configured",
            )

        try:
            from openai import AsyncOpenAI
        except ImportError:
            return AIProviderResponse(
                provider=self.name,
                model=request.resolved_model or "unknown",
                provider_request_id=request.provider_request_id,
                provider_response_id=None,
                status="provider_failed",
                structured_output=None,
                raw_text_hash=None,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                finish_reason="error",
                safety_metadata={},
                created_at=now,
                error_code="AI_PROVIDER_UNAVAILABLE",
                error_message="OpenAI SDK not installed",
            )

        client = AsyncOpenAI(api_key=key, timeout=request.timeout_seconds)
        model = request.resolved_model or settings.AI_CONTENT_MODEL_STANDARD
        messages = [{"role": "system", "content": request.system_instructions}]
        messages.extend(request.input_messages)

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_output_tokens,
                response_format={"type": "json_object"},
            )
        except TimeoutError:
            return AIProviderResponse(
                provider=self.name,
                model=model,
                provider_request_id=request.provider_request_id,
                provider_response_id=None,
                status="timeout",
                structured_output=None,
                raw_text_hash=None,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                finish_reason="timeout",
                safety_metadata={},
                created_at=now,
                error_code="AI_TIMEOUT",
                error_message="OpenAI request timed out",
            )
        except Exception as exc:  # noqa: BLE001 — normalized provider failure
            # Never log API keys or full response bodies.
            logger.warning("openai_provider_failed code=%s", type(exc).__name__)
            return AIProviderResponse(
                provider=self.name,
                model=model,
                provider_request_id=request.provider_request_id,
                provider_response_id=None,
                status="provider_failed",
                structured_output=None,
                raw_text_hash=None,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                finish_reason="error",
                safety_metadata={},
                created_at=now,
                error_code="AI_PROVIDER_UNAVAILABLE",
                error_message="OpenAI provider request failed",
            )

        choice = response.choices[0] if response.choices else None
        raw_text = (choice.message.content or "") if choice else ""
        structured: dict[str, Any] | None = None
        try:
            structured = json.loads(raw_text) if raw_text else None
        except json.JSONDecodeError:
            structured = None

        usage = response.usage
        in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        return AIProviderResponse(
            provider=self.name,
            model=model,
            provider_request_id=request.provider_request_id,
            provider_response_id=getattr(response, "id", None),
            status="completed" if structured is not None else "invalid_output",
            structured_output=structured,
            raw_text_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else None,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=in_tok + out_tok,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=getattr(choice, "finish_reason", None) if choice else None,
            safety_metadata={},
            created_at=now,
            error_code=None if structured is not None else "AI_OUTPUT_INVALID",
            error_message=None if structured is not None else "OpenAI returned non-JSON output",
        )

    async def health_check(self) -> AIProviderHealth:
        if not _api_key_configured():
            return AIProviderHealth(provider=self.name, available=False, detail="not_configured")
        return AIProviderHealth(provider=self.name, available=True)

    def estimate_usage(self, request: AIProviderRequest) -> AIUsageEstimate:
        est_in = max(1, len(request.system_instructions) // 4)
        for msg in request.input_messages:
            est_in += max(1, len(msg.get("content", "")) // 4)
        est_out = min(request.max_output_tokens, 800)
        from app.services.ai_platform.rate_catalog import estimate_cost_minor

        model = request.resolved_model or settings.AI_CONTENT_MODEL_STANDARD
        cost, currency, _ = estimate_cost_minor(self.name, model, est_in, est_out)
        return AIUsageEstimate(
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
            estimated_total_tokens=est_in + est_out,
            estimated_cost_minor=cost,
            currency=currency,
        )
