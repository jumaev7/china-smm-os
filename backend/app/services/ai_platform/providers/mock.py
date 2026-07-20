"""Deterministic mock provider — no network; supports full test suite."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.ai_platform.providers.base import AIProvider
from app.services.ai_platform.schemas import (
    AIProviderHealth,
    AIProviderRequest,
    AIProviderResponse,
    AIUsageEstimate,
)


class MockAIProvider(AIProvider):
    name = "mock"

    def __init__(self) -> None:
        self.call_count = 0
        self.last_request: AIProviderRequest | None = None
        self._force_unavailable = False
        self._force_timeout = False
        self._force_invalid = False
        self._custom_output: dict[str, Any] | None = None

    def reset_test_hooks(self) -> None:
        self._force_unavailable = False
        self._force_timeout = False
        self._force_invalid = False
        self._custom_output = None
        self.call_count = 0
        self.last_request = None

    def set_unavailable(self, value: bool = True) -> None:
        self._force_unavailable = value

    def set_timeout(self, value: bool = True) -> None:
        self._force_timeout = value

    def set_invalid_output(self, value: bool = True) -> None:
        self._force_invalid = value

    def set_custom_output(self, output: dict[str, Any] | None) -> None:
        self._custom_output = output

    async def generate_structured(self, request: AIProviderRequest) -> AIProviderResponse:
        self.call_count += 1
        self.last_request = request
        started = time.perf_counter()
        now = datetime.now(timezone.utc)

        if self._force_unavailable:
            return AIProviderResponse(
                provider=self.name,
                model=request.resolved_model or "mock-content-standard",
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
                error_message="Mock provider unavailable",
            )

        if self._force_timeout:
            return AIProviderResponse(
                provider=self.name,
                model=request.resolved_model or "mock-content-standard",
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
                error_message="Mock provider timeout",
            )

        meta = request.metadata or {}
        platform = str(meta.get("platform") or "instagram")
        locale = str(meta.get("locale") or "en")
        length_profile = str(meta.get("length_profile") or "standard")
        source_caption = str(meta.get("source_caption") or "Adapted content")
        source_hashtags = list(meta.get("source_hashtags") or [])
        source_cta = meta.get("source_cta")
        source_link = meta.get("source_link")
        protected = list(meta.get("protected_fact_tokens") or [])

        # Preserve protected tokens verbatim in mock caption.
        caption = source_caption.strip()
        if length_profile == "short" and len(caption) > 180:
            caption = caption[:177].rstrip() + "..."
        for token in protected:
            if token and token not in caption:
                caption = f"{caption} {token}".strip()

        if self._force_invalid:
            output: dict[str, Any] = {"invalid": True}
        elif self._custom_output is not None:
            output = dict(self._custom_output)
        elif request.task_type == "campaign_plan_proposal":
            platforms = list((meta.get("platforms") if isinstance(meta.get("platforms"), list) else None) or ["instagram", "telegram"])
            locales = list((meta.get("locales") if isinstance(meta.get("locales"), list) else None) or ["en"])
            output = {
                "summary": "Rule-based campaign cadence proposal for the configured platforms and locales.",
                "cadence_suggestions": {
                    "posts_per_week": 3,
                    "max_posts_per_day_per_platform": 2,
                    "min_spacing_minutes": 120,
                    "include_weekends": True,
                },
                "pillar_notes": ["Balance educational and promotional pillars evenly."],
                "phase_notes": ["Keep launch phase denser than sustain phase."],
                "slot_hints": [
                    {
                        "platform": platforms[0],
                        "locale": locales[0],
                        "day_offset": 0,
                        "suggested_time": "10:00",
                        "pillar_key": None,
                        "note": "rule-based suggested time",
                    }
                ],
                "warnings": [],
                "disclaimers": [
                    "Suggested times are rule-based, not engagement-optimal.",
                    "No performance or ROI claims are made.",
                ],
            }
        else:
            claims = []
            for i, token in enumerate(protected[:5]):
                claims.append({
                    "text": token,
                    "source_reference": f"source:protected:{i}",
                })
            if not claims and caption:
                claims.append({
                    "text": caption[:80],
                    "source_reference": "source:sentence:0",
                })
            output = {
                "platform": platform,
                "locale": locale,
                "length_profile": length_profile,
                "caption": caption,
                "hashtags": [h if str(h).startswith("#") else f"#{h}" for h in source_hashtags[:10]],
                "cta": source_cta,
                "link": source_link,
                "transformations": [
                    {
                        "type": "rewrite_for_platform",
                        "reason": "platform_style",
                        "source_sections": ["paragraph:0"],
                    }
                ],
                "claims": claims,
                "warnings": [],
            }

        raw = json.dumps(output, ensure_ascii=False, sort_keys=True)
        est_in = max(1, len(request.system_instructions) // 4 + sum(len(m.get("content", "")) for m in request.input_messages) // 4)
        est_out = max(1, len(raw) // 4)
        return AIProviderResponse(
            provider=self.name,
            model=request.resolved_model or f"mock-{request.model_alias}",
            provider_request_id=request.provider_request_id,
            provider_response_id=f"mock-{uuid4()}",
            status="completed",
            structured_output=output,
            raw_text_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            input_tokens=est_in,
            output_tokens=est_out,
            total_tokens=est_in + est_out,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason="stop",
            safety_metadata={"mock": True},
            created_at=now,
        )

    async def health_check(self) -> AIProviderHealth:
        if self._force_unavailable:
            return AIProviderHealth(provider=self.name, available=False, detail="forced_unavailable")
        return AIProviderHealth(provider=self.name, available=True, latency_ms=1)

    def estimate_usage(self, request: AIProviderRequest) -> AIUsageEstimate:
        est_in = max(1, len(request.system_instructions) // 4)
        est_out = min(request.max_output_tokens, 500)
        return AIUsageEstimate(
            estimated_input_tokens=est_in,
            estimated_output_tokens=est_out,
            estimated_total_tokens=est_in + est_out,
            estimated_cost_minor=0,
            currency="USD",
        )
