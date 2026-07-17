"""Governed AI Platform — provider-agnostic, tenant-governed LLM infrastructure.

Publishing, API, frontend, workflow, and optimizer modules must not call
provider SDKs directly. All LLM access goes through GenerationService.
"""
from __future__ import annotations

from app.services.ai_platform.generation_service import GenerationService
from app.services.ai_platform.provider_registry import (
    get_mock_provider,
    get_provider,
    list_providers,
    quality_mode_to_alias,
    resolve_model_for_alias,
)
from app.services.ai_platform.prompt_registry import (
    PROMPT_KEY_PLATFORM_ADAPTATION,
    PROMPT_VERSION_PLATFORM_ADAPTATION,
    get_prompt,
)

__all__ = [
    "GenerationService",
    "get_provider",
    "get_mock_provider",
    "list_providers",
    "quality_mode_to_alias",
    "resolve_model_for_alias",
    "get_prompt",
    "PROMPT_KEY_PLATFORM_ADAPTATION",
    "PROMPT_VERSION_PLATFORM_ADAPTATION",
]
