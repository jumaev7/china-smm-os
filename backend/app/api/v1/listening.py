"""Tenant-scoped Social Listening Phase 1 APIs.

Prefix: /listening. Read-only toward external providers — this surface NEVER
publishes, replies, DMs, likes, follows, blocks, or mutates provider content.
Writes are limited to:
  * listening configuration (projects/subjects/queries/sources),
  * internal human review state,
  * manual import / fixture ingestion (local observation only).

Tenant is always derived from auth; cross-tenant access resolves to 404.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.endpoint_guard import run_guarded
from app.core.tenant_access import get_current_tenant_user, require_role
from app.schemas.listening import (
    FixtureIngestRequest,
    IngestionRunListResponse,
    IngestionRunResponse,
    ManualImportRequest,
    MentionListResponse,
    MentionResponse,
    OverviewResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
    QueryCreateRequest,
    QueryResponse,
    QueryUpdateRequest,
    ReviewResponse,
    ReviewUpdateRequest,
    SourceResponse,
    SourceUpdateRequest,
    SubjectCreateRequest,
    SubjectResponse,
    SubjectUpdateRequest,
)
from app.services.listening.errors import ListeningError
from app.services.listening.ingestion_service import (
    fixture_ingest_allowed,
    run_fixture_ingest,
    run_manual_import,
)
from app.services.listening.limits import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from app.services.listening import project_service, read_service, review_service
from app.services.listening.providers import list_source_capabilities
from app.services.tenant_auth_service import CurrentTenantUser

router = APIRouter(prefix="/listening", tags=["listening"])


async def _guarded(coro, *, label: str):
    try:
        return await run_guarded(coro, label=label)
    except ListeningError as exc:
        raise exc.to_http() from exc


def _subject_dict(s) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "subject_type": s.subject_type,
        "canonical_name": s.canonical_name,
        "aliases": list(s.aliases_json or []),
        "handle": s.handle,
        "domain": s.domain,
        "is_active": bool(s.is_active),
        "metadata": s.metadata_json,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def _query_dict(q) -> dict:
    return {
        "id": q.id,
        "project_id": q.project_id,
        "subject_id": q.subject_id,
        "name": q.name,
        "include_terms": list(q.include_terms_json or []),
        "exclude_terms": list(q.exclude_terms_json or []),
        "source_filters": list(q.source_filters_json or []),
        "language_filters": list(q.language_filters_json or []),
        "is_enabled": bool(q.is_enabled),
        "created_by_user_id": q.created_by_user_id,
        "created_at": q.created_at,
        "updated_at": q.updated_at,
    }


def _source_dict(s) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "source_type": s.source_type,
        "source_key": s.source_key,
        "display_name": s.display_name,
        "is_enabled": bool(s.is_enabled),
        "capability_status": s.capability_status,
        "freshness_status": s.freshness_status,
        "freshness_watermark": s.freshness_watermark,
        "last_success_at": s.last_success_at,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


# ---------------------------------------------------------------------------
# Overview / capabilities
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    return await _guarded(
        read_service.overview(db, user.tenant_id),
        label="listening.overview",
    )


@router.get("/capabilities")
async def get_capabilities(
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    _ = user
    fixture_ok = fixture_ingest_allowed()
    return {
        "live_provider_available": False,
        "fixture_ingest_available": fixture_ok,
        "coverage_notice": (
            "Coverage is limited to configured supported sources "
            "(manual_import"
            + (" and fixture" if fixture_ok else "")
            + "). No live social listening provider is connected."
        ),
        "provider_writes_supported": False,
        "items": [
            {
                "source_type": c.source_type,
                "capability_status": c.capability_status,
                "supports_keyword_search": c.supports_keyword_search,
                "supports_account_feed": c.supports_account_feed,
                "supports_historical_window": c.supports_historical_window,
                "pagination_type": c.pagination_type,
                "engagement_fields_available": c.engagement_fields_available,
                "author_fields_available": c.author_fields_available,
                "deletion_signals_available": c.deletion_signals_available,
                "notes": c.notes,
                "unsupported_reason": c.unsupported_reason,
            }
            for c in list_source_capabilities()
        ],
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/projects", response_model=ProjectListResponse)
async def api_list_projects(
    status: str | None = Query(None),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    items, total = await _guarded(
        project_service.list_projects(
            db, user.tenant_id, status=status, limit=limit, offset=offset,
        ),
        label="listening.projects.list",
    )
    return {
        "items": [read_service.project_to_dict(p) for p in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/projects", response_model=ProjectResponse)
async def api_create_project(
    body: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    project = await _guarded(
        project_service.create_project(
            db,
            tenant_id=user.tenant_id,
            name=body.name,
            description=body.description,
            client_id=body.client_id,
            default_locale=body.default_locale,
            created_by_user_id=user.id,
        ),
        label="listening.projects.create",
    )
    await db.commit()
    return read_service.project_to_dict(project)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def api_get_project(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    project = await _guarded(
        project_service.get_project(db, user.tenant_id, project_id),
        label="listening.projects.get",
    )
    return read_service.project_to_dict(project)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def api_update_project(
    project_id: UUID,
    body: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    project = await _guarded(
        project_service.update_project(
            db,
            user.tenant_id,
            project_id,
            name=body.name,
            description=body.description,
            status=body.status,
            default_locale=body.default_locale,
        ),
        label="listening.projects.update",
    )
    await db.commit()
    return read_service.project_to_dict(project)


# ---------------------------------------------------------------------------
# Subjects / queries / sources
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/subjects", response_model=list[SubjectResponse])
async def api_list_subjects(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    rows = await _guarded(
        project_service.list_subjects(db, user.tenant_id, project_id),
        label="listening.subjects.list",
    )
    return [_subject_dict(s) for s in rows]


@router.post("/projects/{project_id}/subjects", response_model=SubjectResponse)
async def api_create_subject(
    project_id: UUID,
    body: SubjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    subject = await _guarded(
        project_service.create_subject(
            db,
            tenant_id=user.tenant_id,
            project_id=project_id,
            subject_type=body.subject_type,
            canonical_name=body.canonical_name,
            aliases=body.aliases,
            handle=body.handle,
            domain=body.domain,
            metadata=body.metadata,
        ),
        label="listening.subjects.create",
    )
    await db.commit()
    return _subject_dict(subject)


@router.patch("/subjects/{subject_id}", response_model=SubjectResponse)
async def api_update_subject(
    subject_id: UUID,
    body: SubjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    subject = await _guarded(
        project_service.update_subject(
            db,
            user.tenant_id,
            subject_id,
            canonical_name=body.canonical_name,
            aliases=body.aliases,
            handle=body.handle,
            domain=body.domain,
            is_active=body.is_active,
        ),
        label="listening.subjects.update",
    )
    await db.commit()
    return _subject_dict(subject)


@router.get("/projects/{project_id}/queries", response_model=list[QueryResponse])
async def api_list_queries(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    rows = await _guarded(
        project_service.list_queries(db, user.tenant_id, project_id),
        label="listening.queries.list",
    )
    return [_query_dict(q) for q in rows]


@router.post("/projects/{project_id}/queries", response_model=QueryResponse)
async def api_create_query(
    project_id: UUID,
    body: QueryCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    query = await _guarded(
        project_service.create_query(
            db,
            tenant_id=user.tenant_id,
            project_id=project_id,
            name=body.name,
            include_terms=body.include_terms,
            exclude_terms=body.exclude_terms,
            source_filters=body.source_filters,
            language_filters=body.language_filters,
            subject_id=body.subject_id,
            created_by_user_id=user.id,
        ),
        label="listening.queries.create",
    )
    await db.commit()
    return _query_dict(query)


@router.patch("/queries/{query_id}", response_model=QueryResponse)
async def api_update_query(
    query_id: UUID,
    body: QueryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    query = await _guarded(
        project_service.update_query(
            db,
            user.tenant_id,
            query_id,
            name=body.name,
            include_terms=body.include_terms,
            exclude_terms=body.exclude_terms,
            source_filters=body.source_filters,
            language_filters=body.language_filters,
            is_enabled=body.is_enabled,
            subject_id=body.subject_id,
        ),
        label="listening.queries.update",
    )
    await db.commit()
    return _query_dict(query)


@router.get("/projects/{project_id}/sources", response_model=list[SourceResponse])
async def api_list_sources(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    rows = await _guarded(
        project_service.list_sources(db, user.tenant_id, project_id),
        label="listening.sources.list",
    )
    return [_source_dict(s) for s in rows]


@router.patch("/sources/{source_id}", response_model=SourceResponse)
async def api_update_source(
    source_id: UUID,
    body: SourceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    source = await _guarded(
        project_service.update_source(
            db,
            user.tenant_id,
            source_id,
            is_enabled=body.is_enabled,
            display_name=body.display_name,
        ),
        label="listening.sources.update",
    )
    await db.commit()
    return _source_dict(source)


# ---------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------


@router.get("/mentions", response_model=MentionListResponse)
async def api_list_mentions(
    project_id: UUID | None = Query(None),
    subject_id: UUID | None = Query(None),
    query_id: UUID | None = Query(None),
    source_type: str | None = Query(None),
    review_state: str | None = Query(None),
    language: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    matched_term: str | None = Query(None, max_length=200),
    published_from: datetime | None = Query(None),
    published_to: datetime | None = Query(None),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    items, total = await _guarded(
        read_service.list_mentions(
            db,
            user.tenant_id,
            project_id=project_id,
            subject_id=subject_id,
            query_id=query_id,
            source_type=source_type,
            review_state=review_state,
            language=language,
            search=search,
            matched_term=matched_term,
            published_from=published_from,
            published_to=published_to,
            limit=limit,
            offset=offset,
        ),
        label="listening.mentions.list",
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/mentions/{mention_id}", response_model=MentionResponse)
async def api_get_mention(
    mention_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    return await _guarded(
        read_service.get_mention(db, user.tenant_id, mention_id),
        label="listening.mentions.get",
    )


@router.post("/mentions/{mention_id}/review", response_model=ReviewResponse)
async def api_review_mention(
    mention_id: UUID,
    body: ReviewUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager", "operator")),
):
    _, review = await _guarded(
        review_service.set_review_state(
            db,
            tenant_id=user.tenant_id,
            mention_id=mention_id,
            new_state=body.review_state,
            actor_user_id=user.id,
            note=body.note,
        ),
        label="listening.mentions.review",
    )
    await db.commit()
    return {
        "id": review.id,
        "mention_id": review.mention_id,
        "actor_user_id": review.actor_user_id,
        "previous_state": review.previous_state,
        "new_state": review.new_state,
        "note": review.note,
        "created_at": review.created_at,
    }


@router.get("/mentions/{mention_id}/reviews", response_model=list[ReviewResponse])
async def api_list_mention_reviews(
    mention_id: UUID,
    limit: int = Query(50, ge=1, le=MAX_LIST_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    rows = await _guarded(
        review_service.list_reviews(
            db, tenant_id=user.tenant_id, mention_id=mention_id, limit=limit,
        ),
        label="listening.mentions.reviews",
    )
    return [
        {
            "id": r.id,
            "mention_id": r.mention_id,
            "actor_user_id": r.actor_user_id,
            "previous_state": r.previous_state,
            "new_state": r.new_state,
            "note": r.note,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Ingestion (read-only import / fixture)
# ---------------------------------------------------------------------------


@router.get("/ingestion-runs", response_model=IngestionRunListResponse)
async def api_list_runs(
    project_id: UUID | None = Query(None),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    items, total = await _guarded(
        read_service.list_ingestion_runs(
            db, user.tenant_id, project_id=project_id, limit=limit, offset=offset,
        ),
        label="listening.runs.list",
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/ingestion-runs/{run_id}", response_model=IngestionRunResponse)
async def api_get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(get_current_tenant_user),
):
    return await _guarded(
        read_service.get_ingestion_run(db, user.tenant_id, run_id),
        label="listening.runs.get",
    )


@router.post("/projects/{project_id}/import", response_model=IngestionRunResponse)
async def api_manual_import(
    project_id: UUID,
    body: ManualImportRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    run = await _guarded(
        run_manual_import(
            db,
            tenant_id=user.tenant_id,
            project_id=project_id,
            items=body.items,
            source_id=body.source_id,
            created_by_user_id=user.id,
        ),
        label="listening.import",
    )
    await db.commit()
    return read_service.run_to_dict(run)


@router.post("/projects/{project_id}/fixture-ingest", response_model=IngestionRunResponse)
async def api_fixture_ingest(
    project_id: UUID,
    body: FixtureIngestRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentTenantUser = Depends(require_role("owner", "manager")),
):
    body = body or FixtureIngestRequest()
    run = await _guarded(
        run_fixture_ingest(
            db,
            tenant_id=user.tenant_id,
            project_id=project_id,
            source_id=body.source_id,
            created_by_user_id=user.id,
        ),
        label="listening.fixture_ingest",
    )
    await db.commit()
    return read_service.run_to_dict(run)
