"""Deterministic Content Optimizer orchestration (caller owns the transaction).

Generates immutable platform/locale/length variants from a source content item
using only allowlisted, wording-preserving transformations. The source content is
never mutated during optimization; variants are point-in-time snapshots validated
against a no-invention provenance check. Accept/reject/apply are explicit human
actions — applying copies a variant into the content item but never publishes,
schedules or approves it.

All mutating methods flush but never commit; emitted domain events use
``commit=False`` so the caller's outer transaction stays authoritative.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.content_optimizer import (
    TEMPLATE_TYPES,
    TenantContentOptimizationRun,
    TenantContentTemplate,
    TenantContentVariant,
    TenantContentVariantTransformation,
)
from app.services.automation_domain_events import emit_domain_event
from app.services.content_optimizer import hashtag_optimizer as ht
from app.services.content_optimizer.errors import (
    ContentNotFoundError,
    OptimizationLimitExceededError,
    OptimizationRunNotFoundError,
    SourceContentInsufficientError,
    SourceContentTooLargeError,
    SourceFingerprintMismatchError,
    TemplateLimitExceededError,
    TemplateNotFoundError,
    TemplateValidationError,
    UnsupportedLengthProfileError,
    UnsupportedLocaleError,
    UnsupportedPlatformError,
    VariantNotFoundError,
    VariantStateError,
)
from app.services.content_optimizer.length_profiles import (
    build_pipeline,
    get_effective_profiles,
    is_valid_profile,
)
from app.services.content_optimizer.platform_strategies import (
    get_effective_strategies,
    get_strategy,
    is_supported_platform,
)
from app.services.content_optimizer.provenance import build_corpus, validate_variant
from app.services.content_optimizer.schemas import (
    LENGTH_PROFILES,
    LOCALE_CAPTION_FIELDS,
    MAX_HASHTAGS,
    MAX_LENGTH_PROFILES_PER_RUN,
    MAX_LOCALES_PER_RUN,
    MAX_PLATFORMS_PER_RUN,
    MAX_SOURCE_TEXT_LENGTH,
    MAX_TEMPLATE_COUNT,
    MAX_TEMPLATE_LENGTH,
    MAX_VARIANTS_PER_RUN,
    SUPPORTED_LOCALES,
    NormalizedSource,
    OptimizeRequest,
    VariantBuildResult,
    VariantDraft,
)
from app.services.content_optimizer.source_fingerprint import (
    SOURCE_FINGERPRINT_VERSION,
    compute_source_fingerprint,
)
from app.services.content_optimizer.source_normalizer import (
    has_any_sufficient_locale,
    is_locale_sufficient,
    normalize_source,
    total_source_length,
)
from app.services.content_optimizer.transformation_engine import (
    OperationContext,
    list_operations,
    run_pipeline,
)
from app.services.content_optimizer.variant_fingerprint import (
    VARIANT_FINGERPRINT_VERSION,
    compute_variant_fingerprint,
)
from app.services.publishing_intelligence.platform_policies import (
    POLICY_CATALOG_VERSION,
    get_policy,
)
from app.services.publishing_intelligence.review_engine import PublishingReviewEngine
from app.services.publishing_tenant_scope import tenant_id_for_content

logger = logging.getLogger(__name__)

OPTIMIZER_VERSION = "1.0.0"

_ACTIVE_VARIANT_STATUSES = ("generated", "accepted")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentOptimizerService:
    """Deterministic content optimizer — caller-owned transactions, no LLM."""

    version = OPTIMIZER_VERSION

    # ------------------------------------------------------------------ loaders

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
            # Do not leak cross-tenant existence.
            raise ContentNotFoundError("Content not found").to_http()
        return item

    @staticmethod
    async def _load_run(
        db: AsyncSession, tenant_id: UUID, run_id: UUID
    ) -> TenantContentOptimizationRun:
        result = await db.execute(
            select(TenantContentOptimizationRun).where(
                TenantContentOptimizationRun.id == run_id,
                TenantContentOptimizationRun.tenant_id == tenant_id,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise OptimizationRunNotFoundError("Optimization run not found").to_http()
        return run

    @staticmethod
    async def _load_variant(
        db: AsyncSession, tenant_id: UUID, variant_id: UUID
    ) -> TenantContentVariant:
        result = await db.execute(
            select(TenantContentVariant).where(
                TenantContentVariant.id == variant_id,
                TenantContentVariant.tenant_id == tenant_id,
            )
        )
        variant = result.scalar_one_or_none()
        if variant is None:
            raise VariantNotFoundError("Variant not found").to_http()
        return variant

    # ------------------------------------------------------------------ targets

    @staticmethod
    def _resolve_platforms(source: NormalizedSource, requested: list[str] | None) -> list[str]:
        pool = requested if requested else source.platforms
        if not pool:
            raise UnsupportedPlatformError(
                "No target platforms available", details={"requested": requested},
            ).to_http()
        resolved: list[str] = []
        for platform in pool:
            key = platform.lower()
            if not is_supported_platform(key):
                raise UnsupportedPlatformError(
                    f"Unsupported platform: {platform}", details={"platform": platform},
                ).to_http()
            if key not in resolved:
                resolved.append(key)
        if len(resolved) > MAX_PLATFORMS_PER_RUN:
            raise OptimizationLimitExceededError(
                "Too many platforms for one run",
                details={"max": MAX_PLATFORMS_PER_RUN, "requested": len(resolved)},
            ).to_http()
        return resolved

    @staticmethod
    def _resolve_locales(source: NormalizedSource, requested: list[str] | None) -> list[str]:
        pool = requested if requested else source.locales
        resolved: list[str] = []
        for locale in pool:
            key = locale.lower()
            if key not in SUPPORTED_LOCALES:
                raise UnsupportedLocaleError(
                    f"Unsupported locale: {locale}", details={"locale": locale},
                ).to_http()
            if key not in resolved:
                resolved.append(key)
        resolved = [loc for loc in resolved if source.has_locale(loc)]
        if not resolved:
            raise SourceContentInsufficientError(
                "No source captions available for the requested locales",
                details={"requested": requested, "available": source.locales},
            ).to_http()
        if len(resolved) > MAX_LOCALES_PER_RUN:
            raise OptimizationLimitExceededError(
                "Too many locales for one run",
                details={"max": MAX_LOCALES_PER_RUN, "requested": len(resolved)},
            ).to_http()
        return resolved

    @staticmethod
    def _resolve_profiles(requested: list[str] | None) -> list[str]:
        pool = requested if requested else list(LENGTH_PROFILES)
        resolved: list[str] = []
        for profile in pool:
            key = profile.lower()
            if not is_valid_profile(key):
                raise UnsupportedLengthProfileError(
                    f"Unsupported length profile: {profile}",
                    details={"length_profile": profile},
                ).to_http()
            if key not in resolved:
                resolved.append(key)
        if len(resolved) > MAX_LENGTH_PROFILES_PER_RUN:
            raise OptimizationLimitExceededError(
                "Too many length profiles for one run",
                details={"max": MAX_LENGTH_PROFILES_PER_RUN, "requested": len(resolved)},
            ).to_http()
        return resolved

    # ------------------------------------------------------------------ templates

    @staticmethod
    async def _approved_template_texts(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        approved_template_ids: list[UUID] | None = None,
        platform: str | None = None,
    ) -> tuple[list[str], dict[str, list[str]], list[TenantContentTemplate]]:
        """Return (all active template texts, cta texts per locale, raw rows).

        When ``approved_template_ids`` is provided, only those templates are used.
        When ``platform`` is set, CTA templates whose ``allowed_platforms`` is
        non-empty must include that platform.
        """
        conditions = [
            TenantContentTemplate.tenant_id == tenant_id,
            TenantContentTemplate.is_active.is_(True),
        ]
        if approved_template_ids:
            conditions.append(TenantContentTemplate.id.in_(approved_template_ids))
        result = await db.execute(select(TenantContentTemplate).where(*conditions))
        rows = list(result.scalars().all())
        all_texts: list[str] = []
        cta_by_locale: dict[str, list[str]] = {}
        for row in rows:
            content = (row.content or "").strip()
            if not content:
                continue
            all_texts.append(content)
            if row.template_type == "cta":
                allowed = list(row.allowed_platforms or [])
                if platform and allowed and platform not in allowed:
                    continue
                cta_by_locale.setdefault(row.locale, []).append(content)
        return all_texts, cta_by_locale, rows

    @staticmethod
    def _parse_optimize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
        cfg = dict(raw or {})
        include_cta = cfg.get("include_existing_cta", True)
        include_hashtags = cfg.get("include_existing_hashtags", True)
        template_ids_raw = cfg.get("approved_template_ids") or []
        template_ids: list[UUID] = []
        for value in template_ids_raw:
            try:
                template_ids.append(UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return {
            "include_existing_cta": bool(include_cta),
            "include_existing_hashtags": bool(include_hashtags),
            "approved_template_ids": template_ids or None,
        }

    # ------------------------------------------------------------------ optimize

    @classmethod
    async def optimize(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        request: OptimizeRequest,
    ) -> dict[str, Any]:
        item = await cls._load_content(db, tenant_id, request.content_id)
        source = normalize_source(item, tenant_id)

        if total_source_length(source) > MAX_SOURCE_TEXT_LENGTH:
            raise SourceContentTooLargeError(
                "Source content exceeds maximum length",
                details={"max": MAX_SOURCE_TEXT_LENGTH, "length": total_source_length(source)},
            ).to_http()
        if not has_any_sufficient_locale(source):
            raise SourceContentInsufficientError(
                "Source content is insufficient to optimize",
            ).to_http()
        if len(source.hashtags) > MAX_HASHTAGS:
            raise OptimizationLimitExceededError(
                "Source has too many hashtags",
                details={"max": MAX_HASHTAGS, "count": len(source.hashtags)},
            ).to_http()

        platforms = cls._resolve_platforms(source, request.platforms)
        locales = cls._resolve_locales(source, request.locales)
        profiles = cls._resolve_profiles(request.length_profiles)
        opt_cfg = cls._parse_optimize_config(request.configuration)

        combos = [
            (p, loc, prof)
            for p in platforms
            for loc in locales
            for prof in profiles
            if is_locale_sufficient(source, loc)
        ]
        if not combos:
            raise SourceContentInsufficientError(
                "No optimizable platform/locale/profile combinations",
            ).to_http()
        if len(combos) > MAX_VARIANTS_PER_RUN:
            raise OptimizationLimitExceededError(
                "Requested combination exceeds variant limit",
                details={"max": MAX_VARIANTS_PER_RUN, "requested": len(combos)},
            ).to_http()

        all_template_texts, _, _ = await cls._approved_template_texts(
            db,
            tenant_id,
            approved_template_ids=opt_cfg["approved_template_ids"],
        )
        # Fingerprint only explicitly selected templates so adding an unrelated
        # tenant template does not invalidate existing unapplied variants.
        fingerprint_templates = (
            all_template_texts if opt_cfg["approved_template_ids"] else []
        )

        source_fingerprint = compute_source_fingerprint(
            source,
            target_platforms=platforms,
            target_locales=locales,
            length_profiles=profiles,
            cta_template_texts=fingerprint_templates,
            optimizer_version=OPTIMIZER_VERSION,
            policy_version=POLICY_CATALOG_VERSION,
            configuration={
                "include_existing_cta": opt_cfg["include_existing_cta"],
                "include_existing_hashtags": opt_cfg["include_existing_hashtags"],
                "approved_template_ids": [
                    str(x) for x in (opt_cfg["approved_template_ids"] or [])
                ],
            },
        )

        now = _utcnow()
        await cls._supersede_stale_runs(
            db, tenant_id, request.content_id, source_fingerprint, now=now,
        )

        run = TenantContentOptimizationRun(
            id=uuid4(),
            tenant_id=tenant_id,
            content_id=request.content_id,
            source_fingerprint=source_fingerprint,
            optimizer_version=OPTIMIZER_VERSION,
            policy_version=POLICY_CATALOG_VERSION,
            requested_platforms=platforms,
            requested_locales=locales,
            configuration={
                "length_profiles": profiles,
                "configuration": {
                    "include_existing_cta": opt_cfg["include_existing_cta"],
                    "include_existing_hashtags": opt_cfg["include_existing_hashtags"],
                    "approved_template_ids": [
                        str(x) for x in (opt_cfg["approved_template_ids"] or [])
                    ],
                },
            },
            status="generated",
            created_by=request.created_by,
            created_at=now,
        )
        db.add(run)
        await db.flush()

        await emit_domain_event(
            db,
            "tenant.publishing.optimization_requested",
            tenant_id,
            payload={
                "content_id": str(request.content_id),
                "optimization_run_id": str(run.id),
                "source_fingerprint": source_fingerprint,
                "platforms": platforms,
                "locales": locales,
                "length_profiles": profiles,
                "variant_target_count": len(combos),
                "optimizer_version": OPTIMIZER_VERSION,
                "policy_version": POLICY_CATALOG_VERSION,
            },
            actor_id=request.created_by,
            resource_type="content_optimization_run",
            resource_id=str(run.id),
            title="Content optimization requested",
        )

        source_score, source_categories = await cls._source_baseline(
            db, tenant_id, request.content_id, created_by=request.created_by,
        )

        generated = 0
        failed = 0
        variant_summaries: list[dict[str, Any]] = []
        cta_cache: dict[str, dict[str, list[str]]] = {}
        for platform, locale, profile in combos:
            if platform not in cta_cache:
                _, cta_by_locale, _ = await cls._approved_template_texts(
                    db,
                    tenant_id,
                    approved_template_ids=opt_cfg["approved_template_ids"],
                    platform=platform,
                )
                cta_cache[platform] = cta_by_locale
            build = cls._build_variant(
                source,
                platform,
                locale,
                profile,
                cta_cache[platform],
                include_existing_cta=opt_cfg["include_existing_cta"],
                include_existing_hashtags=opt_cfg["include_existing_hashtags"],
            )
            variant = await cls._persist_variant(
                db,
                tenant_id=tenant_id,
                item=item,
                run=run,
                source=source,
                source_fingerprint=source_fingerprint,
                build=build,
                source_score=source_score,
                source_categories=source_categories,
                created_by=request.created_by,
                now=now,
            )
            if variant.status == "generated":
                generated += 1
            else:
                failed += 1
            variant_summaries.append(
                await cls._variant_summary_with_transformations(db, tenant_id, variant)
            )

        run.completed_at = _utcnow()
        if generated == 0:
            run.status = "failed"
            run.failure_code = "no_variants_generated"
            run.failure_metadata = {"attempted": len(combos), "failed": failed}
            await emit_domain_event(
                db,
                "tenant.publishing.optimization_failed",
                tenant_id,
                payload={
                    "content_id": str(request.content_id),
                    "optimization_run_id": str(run.id),
                    "failure_code": run.failure_code,
                    "attempted": len(combos),
                },
                actor_id=request.created_by,
                resource_type="content_optimization_run",
                resource_id=str(run.id),
                title="Content optimization failed",
            )
        elif failed > 0:
            run.status = "partial"
        else:
            run.status = "generated"
        await db.flush()

        return {
            "run": cls._run_summary(run, generated=generated, failed=failed),
            "variants": variant_summaries,
        }

    @staticmethod
    async def _supersede_stale_runs(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
        source_fingerprint: str,
        *,
        now: datetime,
    ) -> None:
        result = await db.execute(
            select(TenantContentOptimizationRun.id).where(
                TenantContentOptimizationRun.tenant_id == tenant_id,
                TenantContentOptimizationRun.content_id == content_id,
                TenantContentOptimizationRun.status.in_(("generated", "partial")),
                TenantContentOptimizationRun.source_fingerprint != source_fingerprint,
            )
        )
        stale_run_ids = [row[0] for row in result.all()]
        if not stale_run_ids:
            return

        await db.execute(
            update(TenantContentOptimizationRun)
            .where(TenantContentOptimizationRun.id.in_(stale_run_ids))
            .values(status="superseded", superseded_at=now)
        )

        variants_result = await db.execute(
            select(TenantContentVariant).where(
                TenantContentVariant.tenant_id == tenant_id,
                TenantContentVariant.optimization_run_id.in_(stale_run_ids),
                TenantContentVariant.status.in_(_ACTIVE_VARIANT_STATUSES),
            )
        )
        for variant in variants_result.scalars().all():
            variant.status = "stale"
            await emit_domain_event(
                db,
                "tenant.publishing.variant_stale",
                tenant_id,
                payload={
                    "content_id": str(content_id),
                    "optimization_run_id": str(variant.optimization_run_id),
                    "variant_id": str(variant.id),
                    "platform": variant.platform,
                    "locale": variant.locale,
                    "length_profile": variant.length_profile,
                    "variant_fingerprint": variant.variant_fingerprint,
                },
                resource_type="content_variant",
                resource_id=str(variant.id),
                title="Content variant became stale",
            )

    @staticmethod
    async def _source_baseline(
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
        *,
        created_by: UUID | None,
    ) -> tuple[int | None, dict[str, int]]:
        latest = await PublishingReviewEngine.get_latest(
            db, tenant_id, content_id, refresh_stale=False,
        )
        if latest is None or latest.is_stale or latest.status != "completed":
            latest = await PublishingReviewEngine.create_review(
                db, tenant_id, content_id, created_by=created_by,
            )
        categories = {
            key: cs.score
            for key, cs in latest.category_scores.items()
            if cs.applicable
        }
        return latest.overall_score, categories

    # ------------------------------------------------------------------ build

    @staticmethod
    def _build_variant(
        source: NormalizedSource,
        platform: str,
        locale: str,
        profile: str,
        cta_by_locale: dict[str, list[str]],
        *,
        include_existing_cta: bool = True,
        include_existing_hashtags: bool = True,
    ) -> VariantBuildResult:
        strategy = get_strategy(platform)
        policy = get_policy(platform) or {}
        locale_source = source.locale_sources[locale]

        link = None
        if strategy and strategy.allow_links and source.links:
            link = source.links[0]

        draft = VariantDraft(
            platform=platform,
            locale=locale,
            length_profile=profile,
            paragraphs=list(locale_source.paragraphs),
            hashtags=list(source.hashtags) if include_existing_hashtags else [],
            cta=None,
            link=link,
        )

        cta_templates = cta_by_locale.get(locale, []) if include_existing_cta else []
        ctx = OperationContext(
            source_text=locale_source.text,
            cta_templates=cta_templates,
            policy=policy,
            disclosure=locale_source.disclosure,
        )
        steps = build_pipeline(strategy, profile, policy)
        if not include_existing_cta:
            steps = [(k, p) for k, p in steps if k != "select_existing_cta"]
        if not include_existing_hashtags:
            steps = [
                (k, p)
                for k, p in steps
                if k
                not in (
                    "deduplicate_exact_hashtags",
                    "move_hashtags_to_end",
                    "limit_hashtag_count",
                    "remove_unsupported_hashtags",
                )
            ]
        final_draft, records = run_pipeline(draft, steps, ctx)

        caption = final_draft.caption_text()
        fingerprint = compute_variant_fingerprint(
            platform=platform,
            locale=locale,
            length_profile=profile,
            caption=caption,
            hashtags=final_draft.hashtags,
            cta=final_draft.cta,
            link=final_draft.link,
            optimizer_version=OPTIMIZER_VERSION,
            policy_version=POLICY_CATALOG_VERSION,
        )

        status = "generated"
        unsupported_reason: str | None = None
        provenance_ok = True

        if not any(c.isalnum() for c in caption):
            status = "failed"
            unsupported_reason = "empty_after_transform"
        else:
            corpus_texts = [locale_source.text]
            if include_existing_cta:
                corpus_texts.extend(cta_by_locale.get(locale, []))
            if include_existing_hashtags:
                corpus_texts.extend(ht.render_hashtag(t) for t in source.hashtags)
            corpus_texts.extend(source.links)
            corpus = build_corpus(corpus_texts)
            provenance = validate_variant(
                caption=caption,
                hashtags=final_draft.hashtags,
                cta=final_draft.cta,
                link=final_draft.link,
                corpus=corpus,
            )
            provenance_ok = provenance.ok
            if not provenance.ok:
                status = "failed"
                unsupported_reason = "provenance_violation"

        return VariantBuildResult(
            platform=platform,
            locale=locale,
            length_profile=profile,
            caption=caption,
            hashtags=final_draft.hashtags,
            cta=final_draft.cta,
            link=final_draft.link,
            variant_fingerprint=fingerprint,
            transformations=records,
            status=status,
            provenance_ok=provenance_ok,
            unsupported_reason=unsupported_reason,
        )

    @classmethod
    async def _persist_variant(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        item: ContentItem,
        run: TenantContentOptimizationRun,
        source: NormalizedSource,
        source_fingerprint: str,
        build: VariantBuildResult,
        source_score: int | None,
        source_categories: dict[str, int],
        created_by: UUID | None,
        now: datetime,
    ) -> TenantContentVariant:
        variant = TenantContentVariant(
            id=uuid4(),
            tenant_id=tenant_id,
            optimization_run_id=run.id,
            content_id=run.content_id,
            platform=build.platform,
            locale=build.locale,
            length_profile=build.length_profile,
            variant_version=1,
            caption=build.caption,
            hashtags=build.hashtags,
            cta=build.cta,
            link=build.link,
            source_fingerprint=source_fingerprint,
            variant_fingerprint=build.variant_fingerprint,
            status=build.status,
            unsupported_reason=build.unsupported_reason,
            source_score=source_score,
            created_at=now,
        )
        db.add(variant)
        await db.flush()

        for record in build.transformations:
            db.add(
                TenantContentVariantTransformation(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    content_variant_id=variant.id,
                    sequence=record.sequence,
                    operation_key=record.operation_key,
                    category=record.category,
                    source_excerpt_hash=record.source_excerpt_hash,
                    source_position=record.source_position,
                    result_excerpt_hash=record.result_excerpt_hash,
                    reason_key=record.reason_key,
                    reason_params=record.reason_params,
                    policy_key=record.policy_key,
                    policy_version=record.policy_version or POLICY_CATALOG_VERSION,
                    result_summary=record.result_summary,
                    created_at=now,
                )
            )
        await db.flush()

        if build.status != "generated":
            return variant

        review = await cls._score_variant(
            db,
            tenant_id=tenant_id,
            item=item,
            source=source,
            build=build,
            created_by=created_by,
        )
        if review is not None:
            variant.publishing_review_id = review.review_id
            variant.variant_score = review.overall_score
            if source_score is not None:
                variant.score_delta = review.overall_score - source_score
            variant.category_deltas = {
                key: cs.score - source_categories.get(key, cs.score)
                for key, cs in review.category_scores.items()
                if cs.applicable and key in source_categories
            }
            variant.publish_readiness = review.publish_readiness
            await db.flush()

        await emit_domain_event(
            db,
            "tenant.publishing.variant_generated",
            tenant_id,
            payload={
                "content_id": str(run.content_id),
                "optimization_run_id": str(run.id),
                "variant_id": str(variant.id),
                "platform": variant.platform,
                "locale": variant.locale,
                "length_profile": variant.length_profile,
                "variant_fingerprint": variant.variant_fingerprint,
                "variant_score": variant.variant_score,
                "source_score": variant.source_score,
                "score_delta": variant.score_delta,
                "transformation_count": len(build.transformations),
                "publish_readiness": variant.publish_readiness,
            },
            actor_id=created_by,
            resource_type="content_variant",
            resource_id=str(variant.id),
            title="Content variant generated",
        )
        return variant

    @staticmethod
    async def _score_variant(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        item: ContentItem,
        source: NormalizedSource,
        build: VariantBuildResult,
        created_by: UUID | None,
    ):
        base_ctx = PublishingReviewEngine.build_context(item, tenant_id)
        variant_ctx = replace(
            base_ctx,
            platforms=[build.platform],
            captions={build.locale: build.caption},
            primary_language=build.locale,
            hashtags=[ht.normalize_tag(t).casefold() for t in build.hashtags],
            hashtags_raw=" ".join(ht.render_hashtag(t) for t in build.hashtags),
            link=build.link,
            cta_hint=build.cta,
        )
        try:
            return await PublishingReviewEngine.create_review_from_context(
                db,
                tenant_id,
                source.content_id,
                variant_ctx,
                created_by=created_by,
                variant_review=True,
                emit_signals=False,
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception(
                "variant scoring failed for content=%s platform=%s locale=%s",
                source.content_id, build.platform, build.locale,
            )
            return None

    # ------------------------------------------------------------------ lifecycle

    @classmethod
    async def accept_variant(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        *,
        accepted_by: UUID | None = None,
    ) -> dict[str, Any]:
        variant = await cls._load_variant(db, tenant_id, variant_id)
        if variant.status != "generated":
            raise VariantStateError(
                "Only generated variants can be accepted",
                details={"status": variant.status},
            ).to_http()
        now = _utcnow()
        variant.status = "accepted"
        variant.accepted_by = accepted_by
        variant.accepted_at = now
        await db.flush()
        await cls._emit_lifecycle(db, tenant_id, variant, "variant_accepted", accepted_by)
        return cls._variant_summary(variant)

    @classmethod
    async def reject_variant(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        *,
        rejected_by: UUID | None = None,
    ) -> dict[str, Any]:
        variant = await cls._load_variant(db, tenant_id, variant_id)
        if variant.status not in _ACTIVE_VARIANT_STATUSES:
            raise VariantStateError(
                "Only generated or accepted variants can be rejected",
                details={"status": variant.status},
            ).to_http()
        now = _utcnow()
        variant.status = "rejected"
        variant.rejected_by = rejected_by
        variant.rejected_at = now
        await db.flush()
        await cls._emit_lifecycle(db, tenant_id, variant, "variant_rejected", rejected_by)
        return cls._variant_summary(variant)

    @classmethod
    async def apply_variant(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        variant_id: UUID,
        *,
        expected_source_fingerprint: str,
        applied_by: UUID | None = None,
    ) -> dict[str, Any]:
        variant = await cls._load_variant(db, tenant_id, variant_id)
        if variant.status not in _ACTIVE_VARIANT_STATUSES:
            raise VariantStateError(
                "Only generated or accepted variants can be applied",
                details={"status": variant.status},
            ).to_http()
        if variant.locale not in LOCALE_CAPTION_FIELDS:
            raise VariantStateError(
                "Variant locale cannot be written back to content",
                details={"locale": variant.locale},
            ).to_http()
        if expected_source_fingerprint != variant.source_fingerprint:
            raise SourceFingerprintMismatchError(
                "Source fingerprint does not match this variant",
                details={
                    "expected": expected_source_fingerprint,
                    "variant": variant.source_fingerprint,
                },
            ).to_http()

        item = await cls._load_content(db, tenant_id, variant.content_id)

        # Ensure the live source still matches the fingerprint the variant was built
        # against; otherwise the snapshot is stale and must not be applied blindly.
        current_fp = await cls._current_source_fingerprint(db, tenant_id, item, variant)
        if current_fp is not None and current_fp != variant.source_fingerprint:
            now = _utcnow()
            variant.status = "stale"
            await cls._emit_lifecycle(db, tenant_id, variant, "variant_stale", applied_by)
            await db.flush()
            raise SourceFingerprintMismatchError(
                "Source content changed since this variant was generated",
                details={"current": current_fp, "variant": variant.source_fingerprint},
            ).to_http()

        _short_attr, long_attr = LOCALE_CAPTION_FIELDS[variant.locale]
        setattr(item, long_attr, variant.caption)
        item.hashtags = " ".join(ht.render_hashtag(t) for t in (variant.hashtags or []))

        now = _utcnow()
        variant.status = "applied"
        variant.applied_by = applied_by
        variant.applied_at = now
        await db.flush()

        # Content changed — invalidate prior (non-variant) publishing reviews.
        await PublishingReviewEngine.mark_stale_if_fingerprint_mismatch(
            db, tenant_id, variant.content_id,
        )

        await cls._emit_lifecycle(db, tenant_id, variant, "variant_applied", applied_by)
        return cls._variant_summary(variant)

    @staticmethod
    async def _current_source_fingerprint(
        db: AsyncSession,
        tenant_id: UUID,
        item: ContentItem,
        variant: TenantContentVariant,
    ) -> str | None:
        run_result = await db.execute(
            select(TenantContentOptimizationRun).where(
                TenantContentOptimizationRun.id == variant.optimization_run_id,
                TenantContentOptimizationRun.tenant_id == tenant_id,
            )
        )
        run = run_result.scalar_one_or_none()
        if run is None:
            return None
        source = normalize_source(item, tenant_id)
        config = run.configuration or {}
        opt_cfg = ContentOptimizerService._parse_optimize_config(
            config.get("configuration") or {},
        )
        all_template_texts, _, _ = await ContentOptimizerService._approved_template_texts(
            db,
            tenant_id,
            approved_template_ids=opt_cfg["approved_template_ids"],
        )
        fingerprint_templates = (
            all_template_texts if opt_cfg["approved_template_ids"] else []
        )
        return compute_source_fingerprint(
            source,
            target_platforms=list(run.requested_platforms or []),
            target_locales=list(run.requested_locales or []),
            length_profiles=list(config.get("length_profiles") or []),
            cta_template_texts=fingerprint_templates,
            optimizer_version=run.optimizer_version,
            policy_version=run.policy_version,
            configuration=config.get("configuration") or {},
        )

    @staticmethod
    async def _emit_lifecycle(
        db: AsyncSession,
        tenant_id: UUID,
        variant: TenantContentVariant,
        event_suffix: str,
        actor_id: UUID | None,
    ) -> None:
        await emit_domain_event(
            db,
            f"tenant.publishing.{event_suffix}",
            tenant_id,
            payload={
                "content_id": str(variant.content_id),
                "optimization_run_id": str(variant.optimization_run_id),
                "variant_id": str(variant.id),
                "platform": variant.platform,
                "locale": variant.locale,
                "length_profile": variant.length_profile,
                "variant_fingerprint": variant.variant_fingerprint,
                "status": variant.status,
            },
            actor_id=actor_id,
            resource_type="content_variant",
            resource_id=str(variant.id),
            title=f"Content {event_suffix.replace('_', ' ')}",
        )
        # Mirror accept/reject/apply for AI-assisted variants (safe payload, no caption).
        if (
            (variant.generation_method or "") == "ai_assisted"
            and event_suffix in ("variant_accepted", "variant_rejected", "variant_applied")
        ):
            await emit_domain_event(
                db,
                f"ai.{event_suffix}",
                tenant_id,
                payload={
                    "content_id": str(variant.content_id),
                    "variant_id": str(variant.id),
                    "ai_request_id": str(variant.ai_request_id) if variant.ai_request_id else None,
                    "ai_generation_id": str(variant.ai_generation_id) if variant.ai_generation_id else None,
                    "platform": variant.platform,
                    "locale": variant.locale,
                    "model_alias": variant.model_alias,
                    "score_delta": variant.score_delta,
                },
                actor_id=actor_id,
                resource_type="content_variant",
                resource_id=str(variant.id),
                title=f"AI {event_suffix.replace('_', ' ')}",
            )

    # ------------------------------------------------------------------ reads

    @classmethod
    async def get_run(
        cls, db: AsyncSession, tenant_id: UUID, run_id: UUID
    ) -> dict[str, Any]:
        run = await cls._load_run(db, tenant_id, run_id)
        result = await db.execute(
            select(TenantContentVariant)
            .where(
                TenantContentVariant.tenant_id == tenant_id,
                TenantContentVariant.optimization_run_id == run_id,
            )
            .order_by(
                TenantContentVariant.platform,
                TenantContentVariant.locale,
                TenantContentVariant.length_profile,
            )
        )
        variants = list(result.scalars().all())
        generated = sum(1 for v in variants if v.status == "generated")
        failed = sum(1 for v in variants if v.status == "failed")
        summaries = [
            await cls._variant_summary_with_transformations(db, tenant_id, v)
            for v in variants
        ]
        return {
            "run": cls._run_summary(run, generated=generated, failed=failed),
            "variants": summaries,
        }

    @classmethod
    async def mark_stale_for_content_edit(
        cls,
        db: AsyncSession,
        content_id: UUID,
        *,
        tenant_id: UUID | None = None,
    ) -> int:
        """Mark active unapplied variants stale after a source content edit.

        Caller owns the transaction. Returns the number of variants marked stale.
        """
        if tenant_id is None:
            item_result = await db.execute(
                select(ContentItem).where(ContentItem.id == content_id)
            )
            item = item_result.scalar_one_or_none()
            if item is None:
                return 0
            tenant_id = await tenant_id_for_content(db, item)
            if tenant_id is None:
                return 0

        now = _utcnow()
        run_result = await db.execute(
            select(TenantContentOptimizationRun).where(
                TenantContentOptimizationRun.tenant_id == tenant_id,
                TenantContentOptimizationRun.content_id == content_id,
                TenantContentOptimizationRun.status.in_(("generated", "partial")),
            )
        )
        runs = list(run_result.scalars().all())
        if not runs:
            return 0

        for run in runs:
            run.status = "superseded"
            run.superseded_at = now

        variants_result = await db.execute(
            select(TenantContentVariant).where(
                TenantContentVariant.tenant_id == tenant_id,
                TenantContentVariant.content_id == content_id,
                TenantContentVariant.status.in_(_ACTIVE_VARIANT_STATUSES),
            )
        )
        marked = 0
        for variant in variants_result.scalars().all():
            variant.status = "stale"
            marked += 1
            await emit_domain_event(
                db,
                "tenant.publishing.variant_stale",
                tenant_id,
                payload={
                    "content_id": str(content_id),
                    "optimization_run_id": str(variant.optimization_run_id),
                    "variant_id": str(variant.id),
                    "platform": variant.platform,
                    "locale": variant.locale,
                    "length_profile": variant.length_profile,
                    "variant_fingerprint": variant.variant_fingerprint,
                },
                resource_type="content_variant",
                resource_id=str(variant.id),
                title="Content variant became stale",
            )
        await db.flush()
        return marked

    @classmethod
    async def _variant_summary_with_transformations(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        variant: TenantContentVariant,
    ) -> dict[str, Any]:
        summary = cls._variant_summary(variant, include_content=True)
        result = await db.execute(
            select(TenantContentVariantTransformation)
            .where(
                TenantContentVariantTransformation.tenant_id == tenant_id,
                TenantContentVariantTransformation.content_variant_id == variant.id,
            )
            .order_by(TenantContentVariantTransformation.sequence)
        )
        summary["transformations"] = [
            {
                "sequence": t.sequence,
                "operation_key": t.operation_key,
                "category": t.category,
                "reason_key": t.reason_key,
                "reason_params": t.reason_params,
                "result_summary": t.result_summary,
                "policy_key": t.policy_key,
                "policy_version": t.policy_version,
            }
            for t in result.scalars().all()
        ]
        return summary

    @classmethod
    async def list_runs(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        content_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        await cls._load_content(db, tenant_id, content_id)
        count_result = await db.execute(
            select(func.count())
            .select_from(TenantContentOptimizationRun)
            .where(
                TenantContentOptimizationRun.tenant_id == tenant_id,
                TenantContentOptimizationRun.content_id == content_id,
            )
        )
        total = int(count_result.scalar_one())
        result = await db.execute(
            select(TenantContentOptimizationRun)
            .where(
                TenantContentOptimizationRun.tenant_id == tenant_id,
                TenantContentOptimizationRun.content_id == content_id,
            )
            .order_by(TenantContentOptimizationRun.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        rows = list(result.scalars().all())
        return [cls._run_summary(r) for r in rows], total

    @classmethod
    async def get_variant(
        cls, db: AsyncSession, tenant_id: UUID, variant_id: UUID
    ) -> dict[str, Any]:
        variant = await cls._load_variant(db, tenant_id, variant_id)
        result = await db.execute(
            select(TenantContentVariantTransformation)
            .where(
                TenantContentVariantTransformation.tenant_id == tenant_id,
                TenantContentVariantTransformation.content_variant_id == variant_id,
            )
            .order_by(TenantContentVariantTransformation.sequence)
        )
        transformations = [
            {
                "sequence": t.sequence,
                "operation_key": t.operation_key,
                "category": t.category,
                "reason_key": t.reason_key,
                "reason_params": t.reason_params,
                "result_summary": t.result_summary,
                "policy_key": t.policy_key,
                "policy_version": t.policy_version,
            }
            for t in result.scalars().all()
        ]
        summary = cls._variant_summary(variant, include_content=True)
        summary["transformations"] = transformations
        return summary

    # ------------------------------------------------------------------ templates CRUD

    @staticmethod
    def _validate_template_fields(
        *, template_type: str, locale: str, content: str
    ) -> str:
        if template_type not in TEMPLATE_TYPES:
            raise TemplateValidationError(
                "Unsupported template type", details={"template_type": template_type},
            ).to_http()
        if locale not in SUPPORTED_LOCALES:
            raise TemplateValidationError(
                "Unsupported template locale", details={"locale": locale},
            ).to_http()
        cleaned = (content or "").strip()
        if not cleaned:
            raise TemplateValidationError("Template content cannot be empty").to_http()
        if len(cleaned) > MAX_TEMPLATE_LENGTH:
            raise TemplateValidationError(
                "Template content too long",
                details={"max": MAX_TEMPLATE_LENGTH, "length": len(cleaned)},
            ).to_http()
        return cleaned

    @classmethod
    async def create_template(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        template_type: str,
        name: str,
        locale: str,
        content: str,
        allowed_platforms: list[str] | None = None,
        created_by: UUID | None = None,
    ) -> dict[str, Any]:
        cleaned = cls._validate_template_fields(
            template_type=template_type, locale=locale, content=content,
        )
        count_result = await db.execute(
            select(func.count())
            .select_from(TenantContentTemplate)
            .where(
                TenantContentTemplate.tenant_id == tenant_id,
                TenantContentTemplate.is_active.is_(True),
            )
        )
        if int(count_result.scalar_one()) >= MAX_TEMPLATE_COUNT:
            raise TemplateLimitExceededError(
                "Template limit reached", details={"max": MAX_TEMPLATE_COUNT},
            ).to_http()

        platforms = [p for p in (allowed_platforms or []) if is_supported_platform(p)]
        template = TenantContentTemplate(
            id=uuid4(),
            tenant_id=tenant_id,
            template_type=template_type,
            name=(name or "").strip()[:120] or template_type,
            locale=locale,
            content=cleaned,
            allowed_platforms=platforms or None,
            is_active=True,
            created_by=created_by,
        )
        db.add(template)
        await db.flush()
        return cls._template_summary(template)

    @staticmethod
    async def _load_template(
        db: AsyncSession, tenant_id: UUID, template_id: UUID
    ) -> TenantContentTemplate:
        result = await db.execute(
            select(TenantContentTemplate).where(
                TenantContentTemplate.id == template_id,
                TenantContentTemplate.tenant_id == tenant_id,
            )
        )
        template = result.scalar_one_or_none()
        if template is None:
            raise TemplateNotFoundError("Template not found").to_http()
        return template

    @classmethod
    async def get_template(
        cls, db: AsyncSession, tenant_id: UUID, template_id: UUID
    ) -> dict[str, Any]:
        template = await cls._load_template(db, tenant_id, template_id)
        return cls._template_summary(template)

    @classmethod
    async def list_templates(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        *,
        template_type: str | None = None,
        locale: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        conditions = [TenantContentTemplate.tenant_id == tenant_id]
        if template_type:
            conditions.append(TenantContentTemplate.template_type == template_type)
        if locale:
            conditions.append(TenantContentTemplate.locale == locale)
        if active_only:
            conditions.append(TenantContentTemplate.is_active.is_(True))
        result = await db.execute(
            select(TenantContentTemplate)
            .where(*conditions)
            .order_by(TenantContentTemplate.created_at.desc())
        )
        return [cls._template_summary(t) for t in result.scalars().all()]

    @classmethod
    async def update_template(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        template_id: UUID,
        *,
        name: str | None = None,
        content: str | None = None,
        locale: str | None = None,
        allowed_platforms: list[str] | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        template = await cls._load_template(db, tenant_id, template_id)
        new_locale = locale if locale is not None else template.locale
        new_content = content if content is not None else template.content
        cleaned = cls._validate_template_fields(
            template_type=template.template_type, locale=new_locale, content=new_content,
        )
        if name is not None:
            template.name = name.strip()[:120] or template.template_type
        template.locale = new_locale
        template.content = cleaned
        if allowed_platforms is not None:
            platforms = [p for p in allowed_platforms if is_supported_platform(p)]
            template.allowed_platforms = platforms or None
        if is_active is not None:
            template.is_active = is_active
        await db.flush()
        return cls._template_summary(template)

    @classmethod
    async def delete_template(
        cls, db: AsyncSession, tenant_id: UUID, template_id: UUID
    ) -> None:
        template = await cls._load_template(db, tenant_id, template_id)
        await db.delete(template)
        await db.flush()

    # ------------------------------------------------------------------ config

    @staticmethod
    def get_configuration() -> dict[str, Any]:
        """Read-only effective optimizer configuration."""
        return {
            "optimizer_version": OPTIMIZER_VERSION,
            "source_fingerprint_version": SOURCE_FINGERPRINT_VERSION,
            "variant_fingerprint_version": VARIANT_FINGERPRINT_VERSION,
            "policy_catalog_version": POLICY_CATALOG_VERSION,
            "supported_locales": list(SUPPORTED_LOCALES),
            "length_profiles": list(LENGTH_PROFILES),
            "profiles": get_effective_profiles(),
            "platform_strategies": get_effective_strategies(),
            "limits": {
                "max_source_text_length": MAX_SOURCE_TEXT_LENGTH,
                "max_hashtags": MAX_HASHTAGS,
                "max_platforms_per_run": MAX_PLATFORMS_PER_RUN,
                "max_locales_per_run": MAX_LOCALES_PER_RUN,
                "max_length_profiles_per_run": MAX_LENGTH_PROFILES_PER_RUN,
                "max_variants_per_run": MAX_VARIANTS_PER_RUN,
                "max_template_length": MAX_TEMPLATE_LENGTH,
                "max_template_count": MAX_TEMPLATE_COUNT,
            },
            "guarantees": [
                "No LLM, paraphrasing, translation, or invented content.",
                "Deterministic: identical inputs produce identical outputs.",
                "Source content is never mutated during optimization.",
                "Variants are immutable snapshots validated for provenance.",
            ],
        }

    @staticmethod
    def list_operations() -> list[dict[str, str]]:
        return list_operations()

    # ------------------------------------------------------------------ serializers

    @staticmethod
    def _run_summary(
        run: TenantContentOptimizationRun,
        *,
        generated: int | None = None,
        failed: int | None = None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "id": str(run.id),
            "content_id": str(run.content_id),
            "source_fingerprint": run.source_fingerprint,
            "optimizer_version": run.optimizer_version,
            "policy_version": run.policy_version,
            "requested_platforms": list(run.requested_platforms or []),
            "requested_locales": list(run.requested_locales or []),
            "configuration": run.configuration or {},
            "status": run.status,
            "failure_code": run.failure_code,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
        if generated is not None:
            summary["generated_count"] = generated
        if failed is not None:
            summary["failed_count"] = failed
        return summary

    @staticmethod
    def _variant_summary(
        variant: TenantContentVariant, *, include_content: bool = True
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "id": str(variant.id),
            "optimization_run_id": str(variant.optimization_run_id),
            "content_id": str(variant.content_id),
            "platform": variant.platform,
            "locale": variant.locale,
            "length_profile": variant.length_profile,
            "status": variant.status,
            "variant_fingerprint": variant.variant_fingerprint,
            "source_fingerprint": variant.source_fingerprint,
            "source_score": variant.source_score,
            "variant_score": variant.variant_score,
            "score_delta": variant.score_delta,
            "category_deltas": variant.category_deltas or {},
            "publish_readiness": variant.publish_readiness,
            "publishing_review_id": (
                str(variant.publishing_review_id) if variant.publishing_review_id else None
            ),
            "unsupported_reason": variant.unsupported_reason,
            "hashtags": list(variant.hashtags or []),
            "created_at": variant.created_at.isoformat() if variant.created_at else None,
            "accepted_at": variant.accepted_at.isoformat() if variant.accepted_at else None,
            "rejected_at": variant.rejected_at.isoformat() if variant.rejected_at else None,
            "applied_at": variant.applied_at.isoformat() if variant.applied_at else None,
        }
        if include_content:
            summary["caption"] = variant.caption
            summary["cta"] = variant.cta
            summary["link"] = variant.link
        return summary

    @staticmethod
    def _template_summary(template: TenantContentTemplate) -> dict[str, Any]:
        return {
            "id": str(template.id),
            "template_type": template.template_type,
            "name": template.name,
            "locale": template.locale,
            "content": template.content,
            "allowed_platforms": list(template.allowed_platforms or []),
            "is_active": template.is_active,
            "created_at": template.created_at.isoformat() if template.created_at else None,
            "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        }
