"""Tenant-scoped Deterministic Content Optimizer APIs (Phase 2A).

No LLM. Clients cannot inject tenant IDs, optimizer/policy versions, scores,
raw transformations, or output content.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user
from app.schemas.content_optimizer import (
    ApplyVariantRequest,
    OptimizationRunDetailResponse,
    OptimizationRunListResponse,
    OptimizationRunResponse,
    OptimizeContentRequest,
    OperationsCatalogResponse,
    OptimizerConfigurationResponse,
    TemplateCreateRequest,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdateRequest,
    TransformationResponse,
    VariantResponse,
)
from app.services.content_optimizer import ContentOptimizerService
from app.services.content_optimizer.platform_strategies import get_effective_strategies
from app.services.content_optimizer.schemas import (
    LENGTH_PROFILES,
    MAX_SOURCE_TEXT_LENGTH,
    MAX_VARIANTS_PER_RUN,
    OptimizeRequest,
    SUPPORTED_LOCALES,
)
from app.services.publishing_intelligence.platform_policies import (
    POLICY_CATALOG_VERSION,
    SUPPORTED_PLATFORMS,
)
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/content-optimizer", tags=["content-optimizer"])


def _normalize_variant(raw: dict[str, Any], *, include_content: bool = False) -> VariantResponse:
    vid = raw.get("id")
    status = raw.get("status") or "generated"
    payload = {
        "variant_id": vid,
        "id": vid,
        "optimization_run_id": raw.get("optimization_run_id"),
        "content_id": raw.get("content_id"),
        "platform": raw.get("platform"),
        "locale": raw.get("locale"),
        "length_profile": raw.get("length_profile"),
        "status": status,
        "hashtags": list(raw.get("hashtags") or []),
        "source_fingerprint": raw.get("source_fingerprint"),
        "variant_fingerprint": raw.get("variant_fingerprint"),
        "source_score": raw.get("source_score"),
        "variant_score": raw.get("variant_score"),
        "score_delta": raw.get("score_delta"),
        "category_deltas": raw.get("category_deltas") or {},
        "publish_readiness": raw.get("publish_readiness"),
        "publishing_review_id": raw.get("publishing_review_id"),
        "unsupported_reason": raw.get("unsupported_reason"),
        "is_stale": status == "stale",
        "created_at": raw.get("created_at"),
        "accepted_at": raw.get("accepted_at"),
        "rejected_at": raw.get("rejected_at"),
        "applied_at": raw.get("applied_at"),
        "transformations": [
            TransformationResponse(**t) for t in (raw.get("transformations") or [])
        ],
    }
    if include_content or raw.get("caption") is not None:
        payload["caption"] = raw.get("caption")
        payload["cta"] = raw.get("cta")
        payload["link"] = raw.get("link")
    return VariantResponse(**payload)


def _normalize_run(raw: dict[str, Any], variants: list[dict[str, Any]] | None = None) -> OptimizationRunResponse:
    rid = raw.get("id")
    return OptimizationRunResponse(
        run_id=rid,
        id=rid,
        content_id=raw["content_id"],
        source_fingerprint=raw["source_fingerprint"],
        optimizer_version=raw["optimizer_version"],
        policy_version=raw["policy_version"],
        status=raw["status"],
        requested_platforms=list(raw.get("requested_platforms") or []),
        requested_locales=list(raw.get("requested_locales") or []),
        configuration=raw.get("configuration") or {},
        generated_count=raw.get("generated_count"),
        failed_count=raw.get("failed_count"),
        failure_code=raw.get("failure_code"),
        variants=[_normalize_variant(v) for v in (variants or raw.get("variants") or [])],
        created_at=raw.get("created_at"),
        completed_at=raw.get("completed_at"),
    )


@router.post(
    "/content/{content_id}/optimize",
    response_model=OptimizationRunDetailResponse,
)
async def optimize_content(
    content_id: UUID,
    body: OptimizeContentRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    configuration: dict[str, Any] = {
        "include_existing_cta": body.include_existing_cta,
        "include_existing_hashtags": body.include_existing_hashtags,
    }
    if body.approved_template_ids:
        configuration["approved_template_ids"] = [str(x) for x in body.approved_template_ids]

    result = await run_guarded(
        ContentOptimizerService.optimize(
            db,
            user.tenant_id,
            OptimizeRequest(
                content_id=content_id,
                platforms=body.platforms,
                locales=body.locales,
                length_profiles=body.length_profiles,
                configuration=configuration,
                created_by=user.id,
            ),
        ),
        label="content_optimizer.optimize",
    )
    await db.commit()
    run_raw = result.get("run") or result
    variants_raw = result.get("variants") or []
    return OptimizationRunDetailResponse(
        run=_normalize_run(run_raw, variants_raw),
        variants=[_normalize_variant(v, include_content=True) for v in variants_raw],
    )


@router.get(
    "/content/{content_id}/runs",
    response_model=OptimizationRunListResponse,
)
async def list_optimization_runs(
    content_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await run_guarded(
        ContentOptimizerService.list_runs(
            db,
            user.tenant_id,
            content_id,
            page=page,
            page_size=page_size,
        ),
        label="content_optimizer.list_runs",
    )
    return OptimizationRunListResponse(
        items=[_normalize_run(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/runs/{run_id}",
    response_model=OptimizationRunDetailResponse,
)
async def get_optimization_run(
    run_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        ContentOptimizerService.get_run(db, user.tenant_id, run_id),
        label="content_optimizer.get_run",
    )
    return OptimizationRunDetailResponse(
        run=_normalize_run(result["run"], result.get("variants")),
        variants=[
            _normalize_variant(v, include_content=True)
            for v in result.get("variants") or []
        ],
    )


@router.get(
    "/variants/{variant_id}",
    response_model=VariantResponse,
)
async def get_variant(
    variant_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        ContentOptimizerService.get_variant(db, user.tenant_id, variant_id),
        label="content_optimizer.get_variant",
    )
    return _normalize_variant(result, include_content=True)


@router.post(
    "/variants/{variant_id}/accept",
    response_model=VariantResponse,
)
async def accept_variant(
    variant_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        ContentOptimizerService.accept_variant(
            db, user.tenant_id, variant_id, accepted_by=user.id,
        ),
        label="content_optimizer.accept",
    )
    await db.commit()
    return _normalize_variant(result)


@router.post(
    "/variants/{variant_id}/reject",
    response_model=VariantResponse,
)
async def reject_variant(
    variant_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        ContentOptimizerService.reject_variant(
            db, user.tenant_id, variant_id, rejected_by=user.id,
        ),
        label="content_optimizer.reject",
    )
    await db.commit()
    return _normalize_variant(result)


@router.post(
    "/variants/{variant_id}/apply",
    response_model=VariantResponse,
)
async def apply_variant(
    variant_id: UUID,
    body: ApplyVariantRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        ContentOptimizerService.apply_variant(
            db,
            user.tenant_id,
            variant_id,
            expected_source_fingerprint=body.expected_source_fingerprint,
            applied_by=user.id,
        ),
        label="content_optimizer.apply",
    )
    await db.commit()
    return _normalize_variant(result)


@router.get(
    "/configuration",
    response_model=OptimizerConfigurationResponse,
)
async def get_optimizer_configuration(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user  # auth required; config is not tenant-secret
    cfg = ContentOptimizerService.get_configuration()
    strategies = get_effective_strategies()
    return OptimizerConfigurationResponse(
        optimizer_version=cfg["optimizer_version"],
        source_fingerprint_version=cfg.get("source_fingerprint_version"),
        fingerprint_version=cfg.get("source_fingerprint_version"),
        variant_fingerprint_version=cfg.get("variant_fingerprint_version"),
        policy_catalog_version=cfg.get("policy_catalog_version") or POLICY_CATALOG_VERSION,
        platform_policy_version=cfg.get("policy_catalog_version") or POLICY_CATALOG_VERSION,
        supported_platforms=list(SUPPORTED_PLATFORMS),
        supported_locales=list(cfg.get("supported_locales") or SUPPORTED_LOCALES),
        supported_length_profiles=list(cfg.get("length_profiles") or LENGTH_PROFILES),
        length_profiles=list(cfg.get("length_profiles") or LENGTH_PROFILES),
        available_operations=ContentOptimizerService.list_operations(),
        maximum_input_length=MAX_SOURCE_TEXT_LENGTH,
        maximum_variants_per_run=MAX_VARIANTS_PER_RUN,
        limits=cfg.get("limits") or {},
        guarantees=list(cfg.get("guarantees") or []),
        profiles=cfg.get("profiles") or {},
        platform_strategies=strategies if isinstance(strategies, dict) else cfg.get("platform_strategies") or {},
    )


@router.get(
    "/operations",
    response_model=OperationsCatalogResponse,
)
async def list_optimizer_operations(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user
    return OperationsCatalogResponse(operations=ContentOptimizerService.list_operations())


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await run_guarded(
        ContentOptimizerService.list_templates(db, user.tenant_id, active_only=False),
        label="content_optimizer.list_templates",
    )
    return TemplateListResponse(
        items=[TemplateResponse(**r) for r in rows],
        total=len(rows),
    )


@router.post("/templates", response_model=TemplateResponse)
async def create_template(
    body: TemplateCreateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        ContentOptimizerService.create_template(
            db,
            user.tenant_id,
            template_type=body.template_type,
            name=body.name,
            locale=body.locale,
            content=body.content,
            allowed_platforms=body.allowed_platforms,
            created_by=user.id,
        ),
        label="content_optimizer.create_template",
    )
    await db.commit()
    return TemplateResponse(**result)


@router.patch("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: UUID,
    body: TemplateUpdateRequest,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    result = await run_guarded(
        ContentOptimizerService.update_template(
            db,
            user.tenant_id,
            template_id,
            name=body.name,
            content=body.content,
            allowed_platforms=body.allowed_platforms,
            is_active=body.is_active,
        ),
        label="content_optimizer.update_template",
    )
    await db.commit()
    return TemplateResponse(**result)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: UUID,
    user: CurrentTenantUser = Depends(get_current_tenant_user),
    db: AsyncSession = Depends(get_db),
):
    await run_guarded(
        ContentOptimizerService.delete_template(db, user.tenant_id, template_id),
        label="content_optimizer.delete_template",
    )
    await db.commit()
    return {"ok": True}
