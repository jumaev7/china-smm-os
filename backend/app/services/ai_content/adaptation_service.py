"""AI Content Adaptation Service — governed LLM rewriting via AI platform only.

Dependency direction:
  Publishing / Content Optimizer → AI Content Adaptation → Governed AI Platform → Provider

AI never publishes, schedules, approves, applies, or overwrites source content.
Valid output becomes an immutable proposed content variant.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.content import ContentItem
from app.models.content_optimizer import TenantContentOptimizationRun, TenantContentVariant
from app.models.governed_ai import (
    TenantAIGeneration,
    TenantAIPolicy,
    TenantAIRequest,
    TenantAIUsageDaily,
)
from app.services.ai_content.brand_context import load_published_brand_version
from app.services.ai_content.context_builder import build_adaptation_context
from app.services.ai_content.errors import (
    AIDisabledError,
    AIFactualValidationFailedError,
    AINotFoundError,
    AIOutputInvalidError,
    AIPolicyBlockedError,
    AIProviderUnavailableError,
    AIQuotaExceededError,
    AISafetyBlockedError,
    AISecretInContentError,
)
from app.services.ai_content.factual_guard import validate_factual_consistency
from app.services.ai_content.output_validator import validate_adaptation_output
from app.services.ai_content.schemas import AdaptRequest
from app.services.ai_content.variant_adapter import AI_OPTIMIZER_VERSION, create_ai_variant
from app.services.ai_platform.generation_service import GenerationService
from app.services.ai_platform.prompt_registry import (
    PROMPT_KEY_PLATFORM_ADAPTATION,
    get_prompt,
)
from app.services.ai_platform.provider_registry import quality_mode_to_alias
from app.services.ai_platform.rate_catalog import estimate_cost_minor
from app.services.ai_platform.schemas import TASK_AI_CONTENT_ADAPTATION
from app.services.ai_platform.usage_meter import inc
from app.services.automation_domain_events import emit_domain_event
from app.services.content_optimizer.errors import ContentNotFoundError
from app.services.content_optimizer.length_profiles import is_valid_profile
from app.services.content_optimizer.platform_strategies import is_supported_platform
from app.services.content_optimizer.schemas import (
    LENGTH_PROFILES,
    MAX_LENGTH_PROFILES_PER_RUN,
    MAX_LOCALES_PER_RUN,
    MAX_PLATFORMS_PER_RUN,
    SUPPORTED_LOCALES,
)
from app.services.content_optimizer.source_fingerprint import compute_source_fingerprint
from app.services.content_optimizer.source_normalizer import (
    has_any_sufficient_locale,
    normalize_source,
)
from app.services.publishing_intelligence.platform_policies import (
    POLICY_CATALOG_VERSION,
    get_policy,
)
from app.services.publishing_intelligence.review_engine import PublishingReviewEngine
from app.services.publishing_tenant_scope import tenant_id_for_content

logger = logging.getLogger(__name__)

# zh is supported for AI adaptation in addition to optimizer locales
AI_SUPPORTED_LOCALES = frozenset(SUPPORTED_LOCALES) | {"zh"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIContentAdaptationService:
    """Orchestrates tenant-governed AI content adaptation."""

    @staticmethod
    async def _load_content(db: AsyncSession, tenant_id: UUID, content_id: UUID) -> ContentItem:
        from sqlalchemy.orm import selectinload

        result = await db.execute(
            select(ContentItem)
            .options(selectinload(ContentItem.media_file))
            .where(ContentItem.id == content_id)
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise ContentNotFoundError("Content not found").to_http()
        content_tenant = await tenant_id_for_content(db, item)
        if content_tenant != tenant_id:
            raise ContentNotFoundError("Content not found").to_http()
        return item

    @staticmethod
    async def get_or_create_policy(db: AsyncSession, tenant_id: UUID) -> TenantAIPolicy:
        result = await db.execute(
            select(TenantAIPolicy).where(TenantAIPolicy.tenant_id == tenant_id)
        )
        policy = result.scalar_one_or_none()
        if policy is not None:
            return policy
        policy = TenantAIPolicy(
            id=uuid4(),
            tenant_id=tenant_id,
            is_enabled=True,
            allowed_task_types=[TASK_AI_CONTENT_ADAPTATION],
            allowed_locales=list(AI_SUPPORTED_LOCALES),
            allowed_platforms=["telegram", "facebook", "instagram", "tiktok", "linkedin"],
            allow_provider_processing=True,
            allow_fallback_provider=False,
            store_redacted_inputs=settings.AI_STORE_REDACTED_INPUT,
            store_redacted_outputs=settings.AI_STORE_REDACTED_OUTPUT,
            hourly_request_limit=settings.AI_MAX_REQUESTS_PER_TENANT_PER_HOUR,
            daily_token_limit=settings.AI_MAX_DAILY_TOKENS_PER_TENANT,
        )
        db.add(policy)
        await db.flush()
        return policy

    @classmethod
    async def _check_policy(
        cls,
        policy: TenantAIPolicy,
        *,
        platforms: list[str],
        locales: list[str],
    ) -> None:
        if not settings.AI_PLATFORM_ENABLED:
            raise AIDisabledError("Governed AI platform is disabled").to_http()
        if not policy.is_enabled:
            raise AIPolicyBlockedError("AI is disabled for this tenant").to_http()
        if not policy.allow_provider_processing:
            raise AIPolicyBlockedError("Provider processing is not allowed").to_http()
        allowed_tasks = set(policy.allowed_task_types or [])
        if allowed_tasks and TASK_AI_CONTENT_ADAPTATION not in allowed_tasks:
            raise AIPolicyBlockedError("Task type not allowed").to_http()
        allowed_locales = set(policy.allowed_locales or [])
        for loc in locales:
            if allowed_locales and loc not in allowed_locales:
                raise AIPolicyBlockedError(
                    "Locale not allowed", details={"locale": loc},
                ).to_http()
        allowed_platforms = set(policy.allowed_platforms or [])
        for plat in platforms:
            if allowed_platforms and plat not in allowed_platforms:
                raise AIPolicyBlockedError(
                    "Platform not allowed", details={"platform": plat},
                ).to_http()

    @classmethod
    async def _check_quota(cls, db: AsyncSession, tenant_id: UUID, policy: TenantAIPolicy) -> None:
        hourly_limit = (
            policy.hourly_request_limit
            if policy.hourly_request_limit is not None
            else settings.AI_MAX_REQUESTS_PER_TENANT_PER_HOUR
        )
        daily_token_limit = (
            policy.daily_token_limit
            if policy.daily_token_limit is not None
            else settings.AI_MAX_DAILY_TOKENS_PER_TENANT
        )
        since = _utcnow() - timedelta(hours=1)
        count_result = await db.execute(
            select(func.count())
            .select_from(TenantAIRequest)
            .where(
                TenantAIRequest.tenant_id == tenant_id,
                TenantAIRequest.requested_at >= since,
                TenantAIRequest.request_status.notin_(["cancelled", "policy_blocked", "quota_exceeded"]),
            )
        )
        hourly_count = int(count_result.scalar() or 0)
        if hourly_count >= hourly_limit:
            inc("ai_quota_blocks_total", reason="hourly")
            raise AIQuotaExceededError(
                "Hourly AI request limit exceeded",
                details={"limit": hourly_limit, "count": hourly_count},
            ).to_http()

        today = date.today()
        token_result = await db.execute(
            select(func.coalesce(func.sum(TenantAIUsageDaily.total_tokens), 0)).where(
                TenantAIUsageDaily.tenant_id == tenant_id,
                TenantAIUsageDaily.usage_date == today,
            )
        )
        tokens_today = int(token_result.scalar() or 0)
        if tokens_today >= daily_token_limit:
            inc("ai_quota_blocks_total", reason="daily_tokens")
            raise AIQuotaExceededError(
                "Daily AI token limit exceeded",
                details={"limit": daily_token_limit, "tokens": tokens_today},
            ).to_http()

    @classmethod
    async def _record_usage(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        provider: str,
        model: str,
        task_type: str,
        success: bool,
        input_tokens: int,
        output_tokens: int,
        cost_minor: int,
        currency: str = "USD",
    ) -> None:
        today = date.today()
        result = await db.execute(
            select(TenantAIUsageDaily).where(
                TenantAIUsageDaily.tenant_id == tenant_id,
                TenantAIUsageDaily.usage_date == today,
                TenantAIUsageDaily.provider == provider,
                TenantAIUsageDaily.model == model,
                TenantAIUsageDaily.task_type == task_type,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = TenantAIUsageDaily(
                id=uuid4(),
                tenant_id=tenant_id,
                usage_date=today,
                provider=provider,
                model=model,
                task_type=task_type,
                currency=currency,
            )
            db.add(row)
            await db.flush()
        row.request_count = int(row.request_count or 0) + 1
        if success:
            row.successful_request_count = int(row.successful_request_count or 0) + 1
        else:
            row.failed_request_count = int(row.failed_request_count or 0) + 1
        row.input_tokens = int(row.input_tokens or 0) + input_tokens
        row.output_tokens = int(row.output_tokens or 0) + output_tokens
        row.total_tokens = int(row.total_tokens or 0) + input_tokens + output_tokens
        row.estimated_cost_minor = int(row.estimated_cost_minor or 0) + cost_minor
        row.updated_at = _utcnow()
        await db.flush()

    @staticmethod
    def _idempotency_key(req: AdaptRequest, fingerprint: str, prompt_version: str, model_alias: str) -> str:
        if req.idempotency_key:
            return req.idempotency_key[:128]
        raw = json.dumps(
            {
                "content_id": str(req.content_id),
                "source_fingerprint": fingerprint,
                "brand_profile_version_id": str(req.brand_profile_version_id) if req.brand_profile_version_id else None,
                "platforms": sorted(req.platforms or []),
                "locales": sorted(req.locales or []),
                "length_profiles": sorted(req.length_profiles or []),
                "prompt_version": prompt_version,
                "model_alias": model_alias,
                "templates": sorted(str(t) for t in (req.approved_template_ids or [])),
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    async def adapt(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        request: AdaptRequest,
        *,
        requested_by: UUID | None = None,
    ) -> dict[str, Any]:
        item = await cls._load_content(db, tenant_id, request.content_id)
        policy = await cls.get_or_create_policy(db, tenant_id)

        source = normalize_source(item, tenant_id)
        if not has_any_sufficient_locale(source):
            raise AIPolicyBlockedError("Source content is insufficient for adaptation").to_http()

        platforms = []
        for p in (request.platforms or source.platforms or ["instagram"]):
            key = p.lower()
            if not is_supported_platform(key):
                raise AIPolicyBlockedError(f"Unsupported platform: {p}").to_http()
            if key not in platforms:
                platforms.append(key)
        if len(platforms) > MAX_PLATFORMS_PER_RUN:
            raise AIPolicyBlockedError("Too many platforms").to_http()

        locales = []
        for loc in (request.locales or source.locales or ["en"]):
            key = loc.lower()
            if key not in AI_SUPPORTED_LOCALES:
                raise AIPolicyBlockedError(f"Unsupported locale: {loc}").to_http()
            if key not in locales:
                locales.append(key)
        if len(locales) > MAX_LOCALES_PER_RUN:
            raise AIPolicyBlockedError("Too many locales").to_http()

        profiles = []
        for lp in (request.length_profiles or ["standard"]):
            key = lp.lower()
            if not is_valid_profile(key) and key not in LENGTH_PROFILES:
                raise AIPolicyBlockedError(f"Unsupported length profile: {lp}").to_http()
            if key not in profiles:
                profiles.append(key)
        if len(profiles) > MAX_LENGTH_PROFILES_PER_RUN:
            raise AIPolicyBlockedError("Too many length profiles").to_http()

        combos = len(platforms) * len(locales) * len(profiles)
        if combos > settings.AI_MAX_VARIANTS_PER_REQUEST:
            raise AIPolicyBlockedError(
                "Too many variants for one AI request",
                details={"max": settings.AI_MAX_VARIANTS_PER_REQUEST, "requested": combos},
            ).to_http()

        await cls._check_policy(policy, platforms=platforms, locales=locales)
        await cls._check_quota(db, tenant_id, policy)

        brand_version, brand_dict = await load_published_brand_version(
            db, tenant_id, request.brand_profile_version_id, require=True,
        )
        prompt = get_prompt(PROMPT_KEY_PLATFORM_ADAPTATION)
        model_alias = quality_mode_to_alias(request.quality_mode)
        fingerprint_cfg = {
            "include_existing_cta": True,
            "include_existing_hashtags": True,
            "approved_template_ids": [
                str(x) for x in (request.approved_template_ids or [])
            ],
            "engine": "ai_assisted",
            "quality_mode": request.quality_mode or "standard",
            "brand_profile_version_id": str(request.brand_profile_version_id)
            if request.brand_profile_version_id
            else None,
        }
        source_fp = compute_source_fingerprint(
            source,
            target_platforms=platforms,
            target_locales=locales,
            length_profiles=profiles,
            cta_template_texts=[],
            optimizer_version=AI_OPTIMIZER_VERSION,
            policy_version=POLICY_CATALOG_VERSION,
            configuration=fingerprint_cfg,
        )
        idem_key = cls._idempotency_key(request, source_fp, prompt.prompt_version, model_alias)

        # Idempotency: return existing request
        existing = await db.execute(
            select(TenantAIRequest).where(
                TenantAIRequest.tenant_id == tenant_id,
                TenantAIRequest.idempotency_key == idem_key,
            )
        )
        prior = existing.scalar_one_or_none()
        if prior is not None:
            if prior.request_status in ("queued", "running", "completed", "validation_failed"):
                return await cls.get_request_detail(db, tenant_id, prior.id)
            # Allow retry after provider failure by creating a new attempt only via retry endpoint
            if prior.request_status in ("provider_failed",):
                return await cls.get_request_detail(db, tenant_id, prior.id)

        await emit_domain_event(
            db,
            "ai.content_adaptation_requested",
            tenant_id,
            payload={
                "content_id": str(item.id),
                "task_type": TASK_AI_CONTENT_ADAPTATION,
                "model_alias": model_alias,
                "prompt_version": prompt.prompt_version,
                "brand_profile_version": brand_version.version if brand_version else None,
            },
        )

        run = TenantContentOptimizationRun(
            id=uuid4(),
            tenant_id=tenant_id,
            content_id=item.id,
            source_fingerprint=source_fp,
            optimizer_version=AI_OPTIMIZER_VERSION,
            policy_version=POLICY_CATALOG_VERSION,
            requested_platforms=platforms,
            requested_locales=locales,
            configuration={
                "length_profiles": profiles,
                "engine": "ai_assisted",
                "quality_mode": request.quality_mode or "standard",
                "brand_profile_version_id": str(request.brand_profile_version_id)
                if request.brand_profile_version_id
                else None,
                "configuration": fingerprint_cfg,
            },
            status="generated",
            created_by=requested_by,
        )
        db.add(run)
        await db.flush()

        ai_req = TenantAIRequest(
            id=uuid4(),
            tenant_id=tenant_id,
            task_type=TASK_AI_CONTENT_ADAPTATION,
            entity_type="content",
            entity_id=item.id,
            request_status="running",
            model_alias=model_alias,
            prompt_key=prompt.prompt_key,
            prompt_version=prompt.prompt_version,
            input_fingerprint=source_fp,
            idempotency_key=idem_key,
            brand_profile_version_id=request.brand_profile_version_id,
            optimization_run_id=run.id,
            configuration={
                "platforms": platforms,
                "locales": locales,
                "length_profiles": profiles,
            },
            requested_by=requested_by,
            started_at=_utcnow(),
        )
        db.add(ai_req)
        await db.flush()

        # Baseline source score
        source_score = None
        try:
            src_ctx = PublishingReviewEngine.build_context(item, tenant_id)
            src_review = await PublishingReviewEngine.create_review_from_context(
                db, tenant_id, item.id, src_ctx, created_by=requested_by,
                variant_review=True, emit_signals=False,
            )
            source_score = src_review.overall_score if src_review else None
        except Exception:
            logger.exception("source score failed for AI adapt content=%s", item.id)

        variants_out: list[dict[str, Any]] = []
        validation_summary: dict[str, Any] = {"passed": 0, "failed": 0, "platforms": {}}
        total_in = 0
        total_out = 0
        total_cost = 0
        any_success = False
        last_routing = None
        gen_version = 0

        templates: list[dict[str, Any]] = []
        if request.approved_template_ids:
            from app.models.content_optimizer import TenantContentTemplate

            tres = await db.execute(
                select(TenantContentTemplate).where(
                    TenantContentTemplate.tenant_id == tenant_id,
                    TenantContentTemplate.id.in_(request.approved_template_ids),
                    TenantContentTemplate.is_active.is_(True),
                )
            )
            for tmpl in tres.scalars().all():
                templates.append({
                    "id": str(tmpl.id),
                    "template_type": tmpl.template_type,
                    "locale": tmpl.locale,
                    "content": tmpl.content[:500],
                    "name": tmpl.name,
                })

        for platform in platforms:
            for locale in locales:
                for length_profile in profiles:
                    policy_obj = get_policy(platform)
                    policy_summary = {
                        "platform": platform,
                        "max_caption_length": getattr(policy_obj, "max_caption_length", None),
                        "max_hashtags": getattr(policy_obj, "max_hashtags", None),
                    }
                    ctx = build_adaptation_context(
                        source=source,
                        locale=locale,
                        platform=platform,
                        length_profile=length_profile,
                        brand_profile=brand_dict,
                        templates=templates,
                        platform_policy_summary=policy_summary,
                    )
                    if ctx.metadata.get("secret_blocked"):
                        gen_version += 1
                        await cls._store_failed_generation(
                            db,
                            tenant_id=tenant_id,
                            ai_request_id=ai_req.id,
                            generation_version=gen_version,
                            platform=platform,
                            locale=locale,
                            length_profile=length_profile,
                            redacted_input=ctx.redacted_snapshot if policy.store_redacted_inputs else None,
                            validation_status="safety_blocked",
                            safety_status="blocked",
                            factual=None,
                        )
                        validation_summary["failed"] += 1
                        validation_summary["platforms"][f"{platform}:{locale}:{length_profile}"] = "AI_SAFETY_BLOCKED"
                        continue

                    try:
                        response, routing, parsed = await GenerationService.generate_structured(
                            tenant_id=str(tenant_id),
                            task_type=TASK_AI_CONTENT_ADAPTATION,
                            model_alias=model_alias,
                            system_instructions=prompt.system_template,
                            input_messages=ctx.messages,
                            output_schema=prompt.output_schema,
                            temperature=prompt.temperature,
                            max_output_tokens=prompt.max_output_tokens,
                            metadata=ctx.metadata,
                            allow_fallback=bool(settings.AI_FALLBACK_PROVIDER),
                            tenant_allow_fallback=bool(policy.allow_fallback_provider),
                            parse_output=True,
                        )
                    except (AIProviderUnavailableError, AIOutputInvalidError, AIDisabledError) as exc:
                        gen_version += 1
                        await cls._store_failed_generation(
                            db,
                            tenant_id=tenant_id,
                            ai_request_id=ai_req.id,
                            generation_version=gen_version,
                            platform=platform,
                            locale=locale,
                            length_profile=length_profile,
                            redacted_input=ctx.redacted_snapshot if policy.store_redacted_inputs else None,
                            validation_status="provider_failed",
                            safety_status="n/a",
                            factual=None,
                        )
                        validation_summary["failed"] += 1
                        validation_summary["platforms"][f"{platform}:{locale}:{length_profile}"] = exc.code
                        await cls._record_usage(
                            db,
                            tenant_id=tenant_id,
                            provider=(settings.AI_DEFAULT_PROVIDER or "mock"),
                            model=model_alias,
                            task_type=TASK_AI_CONTENT_ADAPTATION,
                            success=False,
                            input_tokens=0,
                            output_tokens=0,
                            cost_minor=0,
                        )
                        continue

                    last_routing = routing
                    total_in += response.input_tokens
                    total_out += response.output_tokens
                    cost, currency, _ = estimate_cost_minor(
                        routing.provider, routing.resolved_model,
                        response.input_tokens, response.output_tokens,
                    )
                    total_cost += cost
                    ai_req.resolved_provider = routing.provider
                    ai_req.resolved_model = routing.resolved_model
                    ai_req.routing_version = routing.routing_version

                    assert parsed is not None
                    try:
                        validate_adaptation_output(
                            parsed,
                            expected_platform=platform,
                            expected_locale=locale,
                            expected_length_profile=length_profile,
                            protected_facts=ctx.protected_facts,
                            forbidden_terms=(brand_dict or {}).get("forbidden_terms"),
                        )
                    except (AIOutputInvalidError, AISafetyBlockedError) as exc:
                        gen_version += 1
                        await cls._store_failed_generation(
                            db,
                            tenant_id=tenant_id,
                            ai_request_id=ai_req.id,
                            generation_version=gen_version,
                            platform=platform,
                            locale=locale,
                            length_profile=length_profile,
                            redacted_input=ctx.redacted_snapshot if policy.store_redacted_inputs else None,
                            redacted_output=parsed.model_dump() if policy.store_redacted_outputs else None,
                            validation_status="failed",
                            safety_status="blocked" if exc.code == "AI_SAFETY_BLOCKED" else "failed",
                            factual=None,
                            tokens=(response.input_tokens, response.output_tokens, cost, currency),
                            latency_ms=response.latency_ms,
                        )
                        validation_summary["failed"] += 1
                        validation_summary["platforms"][f"{platform}:{locale}:{length_profile}"] = exc.code
                        inc("ai_validation_failures_total", reason="output")
                        await cls._record_usage(
                            db, tenant_id=tenant_id, provider=routing.provider,
                            model=routing.resolved_model, task_type=TASK_AI_CONTENT_ADAPTATION,
                            success=False, input_tokens=response.input_tokens,
                            output_tokens=response.output_tokens, cost_minor=cost, currency=currency,
                        )
                        continue

                    factual = validate_factual_consistency(
                        source_facts=ctx.protected_facts,
                        output=parsed,
                        length_profile=length_profile,
                        approved_urls=list(source.links or []),
                    )
                    gen_version += 1
                    generation = TenantAIGeneration(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        ai_request_id=ai_req.id,
                        generation_version=gen_version,
                        platform=platform,
                        locale=locale,
                        length_profile=length_profile,
                        structured_output=parsed.model_dump() if policy.store_redacted_outputs else None,
                        redacted_input_snapshot=ctx.redacted_snapshot if policy.store_redacted_inputs else None,
                        redacted_output_snapshot=parsed.model_dump() if policy.store_redacted_outputs else None,
                        output_fingerprint=hashlib.sha256(
                            json.dumps(parsed.model_dump(), sort_keys=True).encode()
                        ).hexdigest(),
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        total_tokens=response.total_tokens,
                        estimated_cost_minor=cost,
                        currency=currency,
                        latency_ms=response.latency_ms,
                        finish_reason=response.finish_reason,
                        validation_status=factual.status,
                        safety_status="passed" if not ctx.injection_flagged else "flagged",
                        factual_validation={
                            "status": factual.status,
                            "checks": factual.checks,
                            "errors": factual.errors,
                        },
                        protected_fact_summary={
                            "preserved": factual.preserved[:20],
                            "removed": factual.removed[:20],
                            "modified": factual.modified[:20],
                            "new": factual.new[:20],
                        },
                    )
                    db.add(generation)
                    await db.flush()

                    if factual.status == "failed":
                        generation.validation_status = "failed"
                        await db.flush()
                        validation_summary["failed"] += 1
                        validation_summary["platforms"][f"{platform}:{locale}:{length_profile}"] = "AI_FACTUAL_VALIDATION_FAILED"
                        inc("ai_validation_failures_total", reason="factual")
                        await emit_domain_event(
                            db,
                            "ai.content_validation_failed",
                            tenant_id,
                            payload={
                                "request_id": str(ai_req.id),
                                "generation_id": str(generation.id),
                                "content_id": str(item.id),
                                "platform": platform,
                                "locale": locale,
                                "length_profile": length_profile,
                                "validation_status": "failed",
                                "model_alias": model_alias,
                            },
                        )
                        await cls._record_usage(
                            db, tenant_id=tenant_id, provider=routing.provider,
                            model=routing.resolved_model, task_type=TASK_AI_CONTENT_ADAPTATION,
                            success=False, input_tokens=response.input_tokens,
                            output_tokens=response.output_tokens, cost_minor=cost, currency=currency,
                        )
                        continue

                    variant = await create_ai_variant(
                        db,
                        tenant_id=tenant_id,
                        item=item,
                        run=run,
                        output=parsed,
                        source_fingerprint=source_fp,
                        ai_request_id=ai_req.id,
                        ai_generation_id=generation.id,
                        brand_profile_version_id=request.brand_profile_version_id,
                        prompt_key=prompt.prompt_key,
                        prompt_version=prompt.prompt_version,
                        model_alias=model_alias,
                        resolved_provider=routing.provider,
                        resolved_model=routing.resolved_model,
                        factual=factual,
                        safety_status=generation.safety_status,
                        source_score=source_score,
                        created_by=requested_by,
                    )
                    generation.content_variant_id = variant.id
                    await db.flush()
                    any_success = True
                    validation_summary["passed"] += 1
                    validation_summary["platforms"][f"{platform}:{locale}:{length_profile}"] = "ok"
                    variants_out.append(cls._serialize_variant(variant, generation))

                    await emit_domain_event(
                        db,
                        "ai.variant_generated",
                        tenant_id,
                        payload={
                            "request_id": str(ai_req.id),
                            "generation_id": str(generation.id),
                            "content_id": str(item.id),
                            "variant_id": str(variant.id),
                            "platform": platform,
                            "locale": locale,
                            "length_profile": length_profile,
                            "model_alias": model_alias,
                            "prompt_version": prompt.prompt_version,
                            "brand_profile_version": brand_version.version if brand_version else None,
                            "score_delta": variant.score_delta,
                            "token_usage": response.total_tokens,
                            "estimated_cost_minor": cost,
                        },
                    )
                    await cls._record_usage(
                        db, tenant_id=tenant_id, provider=routing.provider,
                        model=routing.resolved_model, task_type=TASK_AI_CONTENT_ADAPTATION,
                        success=True, input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens, cost_minor=cost, currency=currency,
                    )

        # Finalize request status
        if any_success:
            ai_req.request_status = "completed"
            run.status = "generated" if validation_summary["failed"] == 0 else "partial"
            event_type = "ai.content_adaptation_completed"
        elif validation_summary["failed"] > 0:
            # Distinguish quota already raised; here validation/provider failures
            failed_codes = set(validation_summary["platforms"].values())
            if failed_codes == {"AI_SAFETY_BLOCKED"}:
                ai_req.request_status = "policy_blocked"
                ai_req.failure_code = "AI_SAFETY_BLOCKED"
            elif "AI_FACTUAL_VALIDATION_FAILED" in failed_codes and not any_success:
                ai_req.request_status = "validation_failed"
                ai_req.failure_code = "AI_FACTUAL_VALIDATION_FAILED"
            else:
                ai_req.request_status = "provider_failed"
                ai_req.failure_code = "AI_PROVIDER_UNAVAILABLE"
            run.status = "failed"
            event_type = "ai.content_adaptation_failed"
        else:
            ai_req.request_status = "provider_failed"
            run.status = "failed"
            event_type = "ai.content_adaptation_failed"

        ai_req.completed_at = _utcnow()
        run.completed_at = _utcnow()
        await db.flush()

        await emit_domain_event(
            db,
            event_type,
            tenant_id,
            payload={
                "request_id": str(ai_req.id),
                "content_id": str(item.id),
                "status": ai_req.request_status,
                "model_alias": model_alias,
                "prompt_version": prompt.prompt_version,
                "brand_profile_version": brand_version.version if brand_version else None,
                "token_usage": total_in + total_out,
                "estimated_cost_minor": total_cost,
                "validation_status": ai_req.request_status,
            },
        )

        return await cls.get_request_detail(db, tenant_id, ai_req.id)

    @classmethod
    async def _store_failed_generation(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        ai_request_id: UUID,
        generation_version: int,
        platform: str,
        locale: str,
        length_profile: str,
        redacted_input: dict | None,
        validation_status: str,
        safety_status: str,
        factual: Any,
        redacted_output: dict | None = None,
        tokens: tuple[int, int, int, str] | None = None,
        latency_ms: int | None = None,
    ) -> TenantAIGeneration:
        in_t = out_t = cost = 0
        currency = "USD"
        if tokens:
            in_t, out_t, cost, currency = tokens
        gen = TenantAIGeneration(
            id=uuid4(),
            tenant_id=tenant_id,
            ai_request_id=ai_request_id,
            generation_version=generation_version,
            platform=platform,
            locale=locale,
            length_profile=length_profile,
            redacted_input_snapshot=redacted_input,
            redacted_output_snapshot=redacted_output,
            input_tokens=in_t,
            output_tokens=out_t,
            total_tokens=in_t + out_t,
            estimated_cost_minor=cost,
            currency=currency,
            latency_ms=latency_ms,
            validation_status=validation_status,
            safety_status=safety_status,
            factual_validation=factual,
        )
        db.add(gen)
        await db.flush()
        return gen

    @staticmethod
    def _serialize_variant(variant: TenantContentVariant, generation: TenantAIGeneration | None = None) -> dict[str, Any]:
        return {
            "variant_id": variant.id,
            "id": variant.id,
            "generation_method": variant.generation_method or "ai_assisted",
            "platform": variant.platform,
            "locale": variant.locale,
            "length_profile": variant.length_profile,
            "caption": variant.caption,
            "hashtags": variant.hashtags or [],
            "cta": variant.cta,
            "link": variant.link,
            "status": variant.status,
            "is_stale": variant.status == "stale",
            "ai_request_id": variant.ai_request_id,
            "ai_generation_id": variant.ai_generation_id,
            "model_alias": variant.model_alias,
            "brand_profile_version_id": variant.brand_profile_version_id,
            "prompt_key": variant.prompt_key,
            "prompt_version": variant.prompt_version,
            "factual_validation_status": variant.factual_validation_status,
            "safety_validation_status": variant.safety_validation_status,
            "factual_validation": generation.factual_validation if generation else None,
            "protected_fact_summary": generation.protected_fact_summary if generation else None,
            "source_score": variant.source_score,
            "variant_score": variant.variant_score,
            "score_delta": variant.score_delta,
            "category_deltas": variant.category_deltas or {},
            "publish_readiness": variant.publish_readiness,
            "publishing_review_id": variant.publishing_review_id,
            "source_fingerprint": variant.source_fingerprint,
            "created_at": variant.created_at,
            "warnings": (generation.factual_validation or {}).get("errors", []) if generation else [],
        }

    @classmethod
    async def get_request_detail(cls, db: AsyncSession, tenant_id: UUID, request_id: UUID) -> dict[str, Any]:
        result = await db.execute(
            select(TenantAIRequest).where(
                TenantAIRequest.id == request_id,
                TenantAIRequest.tenant_id == tenant_id,
            )
        )
        req = result.scalar_one_or_none()
        if req is None:
            raise AINotFoundError("AI request not found").to_http()

        gens = await db.execute(
            select(TenantAIGeneration).where(
                TenantAIGeneration.ai_request_id == req.id,
                TenantAIGeneration.tenant_id == tenant_id,
            ).order_by(TenantAIGeneration.generation_version.asc())
        )
        generations = list(gens.scalars().all())
        variants: list[dict[str, Any]] = []
        for gen in generations:
            if gen.content_variant_id is None:
                continue
            vres = await db.execute(
                select(TenantContentVariant).where(
                    TenantContentVariant.id == gen.content_variant_id,
                    TenantContentVariant.tenant_id == tenant_id,
                )
            )
            variant = vres.scalar_one_or_none()
            if variant:
                variants.append(cls._serialize_variant(variant, gen))

        usage = {
            "input_tokens": sum(g.input_tokens or 0 for g in generations),
            "output_tokens": sum(g.output_tokens or 0 for g in generations),
            "total_tokens": sum(g.total_tokens or 0 for g in generations),
            "estimated_cost_minor": sum(g.estimated_cost_minor or 0 for g in generations),
            "currency": generations[0].currency if generations else "USD",
            "note": "Costs are estimates unless reconciled with provider billing.",
        }
        brand_ver = None
        if req.brand_profile_version_id:
            from app.models.governed_ai import TenantBrandProfileVersion
            bv = await db.execute(
                select(TenantBrandProfileVersion).where(
                    TenantBrandProfileVersion.id == req.brand_profile_version_id,
                    TenantBrandProfileVersion.tenant_id == tenant_id,
                )
            )
            bvo = bv.scalar_one_or_none()
            if bvo:
                brand_ver = bvo.version

        return {
            "request_id": req.id,
            "status": req.request_status,
            "content_id": req.entity_id,
            "source_fingerprint": req.input_fingerprint,
            "brand_profile_version": brand_ver,
            "brand_profile_version_id": req.brand_profile_version_id,
            "prompt_key": req.prompt_key,
            "prompt_version": req.prompt_version,
            "model_alias": req.model_alias,
            "resolved_provider": None,  # hide raw provider from API by default
            "routing_version": req.routing_version,
            "variants": variants,
            "generations": [
                {
                    "generation_id": g.id,
                    "generation_version": g.generation_version,
                    "platform": g.platform,
                    "locale": g.locale,
                    "length_profile": g.length_profile,
                    "validation_status": g.validation_status,
                    "safety_status": g.safety_status,
                    "content_variant_id": g.content_variant_id,
                    "input_tokens": g.input_tokens,
                    "output_tokens": g.output_tokens,
                    "estimated_cost_minor": g.estimated_cost_minor,
                    "created_at": g.created_at,
                }
                for g in generations
            ],
            "usage": usage,
            "validation_summary": {
                "passed": sum(1 for v in variants if v.get("factual_validation_status") != "failed"),
                "failed": sum(1 for g in generations if g.validation_status == "failed"),
            },
            "failure_code": req.failure_code,
            "created_at": req.requested_at,
            "completed_at": req.completed_at,
            "configuration": req.configuration or {},
        }

    @classmethod
    async def list_requests_for_content(
        cls, db: AsyncSession, tenant_id: UUID, content_id: UUID
    ) -> list[dict[str, Any]]:
        await cls._load_content(db, tenant_id, content_id)
        result = await db.execute(
            select(TenantAIRequest)
            .where(
                TenantAIRequest.tenant_id == tenant_id,
                TenantAIRequest.entity_id == content_id,
                TenantAIRequest.entity_type == "content",
            )
            .order_by(TenantAIRequest.requested_at.desc())
            .limit(50)
        )
        out = []
        for req in result.scalars().all():
            out.append({
                "request_id": req.id,
                "status": req.request_status,
                "model_alias": req.model_alias,
                "prompt_version": req.prompt_version,
                "created_at": req.requested_at,
                "completed_at": req.completed_at,
                "failure_code": req.failure_code,
            })
        return out

    @classmethod
    async def get_generation(
        cls, db: AsyncSession, tenant_id: UUID, generation_id: UUID
    ) -> dict[str, Any]:
        result = await db.execute(
            select(TenantAIGeneration).where(
                TenantAIGeneration.id == generation_id,
                TenantAIGeneration.tenant_id == tenant_id,
            )
        )
        gen = result.scalar_one_or_none()
        if gen is None:
            raise AINotFoundError("AI generation not found").to_http()
        payload = {
            "generation_id": gen.id,
            "ai_request_id": gen.ai_request_id,
            "generation_version": gen.generation_version,
            "platform": gen.platform,
            "locale": gen.locale,
            "length_profile": gen.length_profile,
            "validation_status": gen.validation_status,
            "safety_status": gen.safety_status,
            "factual_validation": gen.factual_validation,
            "protected_fact_summary": gen.protected_fact_summary,
            "content_variant_id": gen.content_variant_id,
            "input_tokens": gen.input_tokens,
            "output_tokens": gen.output_tokens,
            "total_tokens": gen.total_tokens,
            "estimated_cost_minor": gen.estimated_cost_minor,
            "currency": gen.currency,
            "created_at": gen.created_at,
            # Do not expose raw structured output unless needed — omit full caption dump here
        }
        return payload

    @classmethod
    async def retry_request(
        cls, db: AsyncSession, tenant_id: UUID, request_id: UUID, *, requested_by: UUID | None = None
    ) -> dict[str, Any]:
        result = await db.execute(
            select(TenantAIRequest).where(
                TenantAIRequest.id == request_id,
                TenantAIRequest.tenant_id == tenant_id,
            )
        )
        prior = result.scalar_one_or_none()
        if prior is None:
            raise AINotFoundError("AI request not found").to_http()
        if prior.request_status not in ("provider_failed", "validation_failed"):
            raise AIPolicyBlockedError(
                "Only failed requests can be retried",
                details={"status": prior.request_status},
            ).to_http()
        cfg = prior.configuration or {}
        # New idempotency key suffix for retry
        new_req = AdaptRequest(
            content_id=prior.entity_id,
            platforms=cfg.get("platforms"),
            locales=cfg.get("locales"),
            length_profiles=cfg.get("length_profiles"),
            brand_profile_version_id=prior.brand_profile_version_id,
            quality_mode=None,
            idempotency_key=f"{prior.idempotency_key}:retry:{uuid4().hex[:8]}",
        )
        return await cls.adapt(db, tenant_id, new_req, requested_by=requested_by)

    @classmethod
    async def get_configuration(cls, db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        policy = await cls.get_or_create_policy(db, tenant_id)
        return {
            "ai_enabled": bool(settings.AI_PLATFORM_ENABLED and policy.is_enabled),
            "platform_enabled": bool(settings.AI_PLATFORM_ENABLED),
            "tenant_enabled": bool(policy.is_enabled),
            "allowed_task_types": policy.allowed_task_types or [],
            "allowed_locales": policy.allowed_locales or list(AI_SUPPORTED_LOCALES),
            "allowed_platforms": policy.allowed_platforms or [],
            "quality_modes": ["fast", "standard", "high"],
            "model_aliases": ["content_fast", "content_standard", "content_high_quality"],
            "prompt_key": PROMPT_KEY_PLATFORM_ADAPTATION,
            "prompt_version": get_prompt(PROMPT_KEY_PLATFORM_ADAPTATION).prompt_version,
            "hourly_request_limit": policy.hourly_request_limit or settings.AI_MAX_REQUESTS_PER_TENANT_PER_HOUR,
            "daily_token_limit": policy.daily_token_limit or settings.AI_MAX_DAILY_TOKENS_PER_TENANT,
            "max_variants_per_request": settings.AI_MAX_VARIANTS_PER_REQUEST,
            "notes": [
                "Clients cannot select raw provider models or inject system prompts.",
                "AI output is always a proposed immutable variant.",
                "Publishing Score is advisory; PublishSafetyService remains authoritative.",
            ],
        }

    @classmethod
    async def get_usage(
        cls, db: AsyncSession, tenant_id: UUID, *, days: int = 30
    ) -> dict[str, Any]:
        since = date.today() - timedelta(days=max(1, min(days, 90)))
        result = await db.execute(
            select(TenantAIUsageDaily).where(
                TenantAIUsageDaily.tenant_id == tenant_id,
                TenantAIUsageDaily.usage_date >= since,
            ).order_by(TenantAIUsageDaily.usage_date.desc())
        )
        rows = list(result.scalars().all())
        return {
            "period_days": days,
            "rows": [
                {
                    "usage_date": r.usage_date.isoformat(),
                    "task_type": r.task_type,
                    "model_alias": r.model,  # may be resolved model; OK for summary
                    "request_count": r.request_count,
                    "successful_request_count": r.successful_request_count,
                    "failed_request_count": r.failed_request_count,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "total_tokens": r.total_tokens,
                    "estimated_cost_minor": r.estimated_cost_minor,
                    "currency": r.currency,
                }
                for r in rows
            ],
            "totals": {
                "requests": sum(r.request_count for r in rows),
                "successful_requests": sum(r.successful_request_count for r in rows),
                "failed_requests": sum(r.failed_request_count for r in rows),
                "input_tokens": sum(r.input_tokens for r in rows),
                "output_tokens": sum(r.output_tokens for r in rows),
                "total_tokens": sum(r.total_tokens for r in rows),
                "estimated_cost_minor": sum(r.estimated_cost_minor for r in rows),
            },
            "note": "Costs are estimates unless reconciled with provider billing.",
        }
