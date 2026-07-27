"""Read-side queries for Social Listening Phase 1 (no provider I/O)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listening import (
    LISTENING_SCHEMA_VERSION,
    TenantListeningIngestionRun,
    TenantListeningSource,
    TenantMentionMatch,
    TenantObservedMention,
)
from app.services.listening.errors import IngestionRunNotFoundError, MentionNotFoundError
from app.services.listening.limits import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT
from app.services.listening.providers import list_source_capabilities
from app.services.listening.project_service import list_projects


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIST_LIMIT
    return max(1, min(int(limit), MAX_LIST_LIMIT))


def mention_to_dict(m: TenantObservedMention, *, matches: list[TenantMentionMatch] | None = None) -> dict[str, Any]:
    return {
        "id": m.id,
        "project_id": m.project_id,
        "source_id": m.source_id,
        "source_type": m.source_type,
        "observation_origin": m.observation_origin,
        "provider_account_ref": m.provider_account_ref or None,
        "provider_external_id": m.provider_external_id,
        "canonical_url": m.canonical_url,
        "author_display": m.author_display,
        # author_external_id omitted from list payloads for privacy; detail may include.
        "content_excerpt": m.content_excerpt,
        "content_type": m.content_type,
        "language": m.language,
        "published_at": m.published_at,
        "observed_at": m.observed_at,
        "first_observed_at": m.first_observed_at,
        "last_observed_at": m.last_observed_at,
        "source_updated_at": m.source_updated_at,
        "engagement": m.engagement_json,
        "review_state": m.review_state,
        "dedupe_version": m.dedupe_version,
        "normalization_version": m.normalization_version,
        "ingestion_run_id": m.ingestion_run_id,
        "provenance": m.provenance_json,
        "matches": [match_to_dict(x) for x in (matches or [])],
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }


def mention_detail_dict(m: TenantObservedMention, *, matches: list[TenantMentionMatch]) -> dict[str, Any]:
    base = mention_to_dict(m, matches=matches)
    base["content_text"] = m.content_text
    base["author_external_id"] = m.author_external_id
    base["content_fingerprint"] = m.content_fingerprint
    base["dedupe_key"] = m.dedupe_key
    return base


def match_to_dict(match: TenantMentionMatch) -> dict[str, Any]:
    return {
        "id": match.id,
        "mention_id": match.mention_id,
        "query_id": match.query_id,
        "subject_id": match.subject_id,
        "match_type": match.match_type,
        "matched_term": match.matched_term,
        "evidence_excerpt": match.evidence_excerpt,
        "evidence_start": match.evidence_start,
        "evidence_end": match.evidence_end,
        "matcher_version": match.matcher_version,
        "created_at": match.created_at,
    }


def project_to_dict(p: TenantListeningProject) -> dict[str, Any]:
    return {
        "id": p.id,
        "client_id": p.client_id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "default_locale": p.default_locale,
        "created_by_user_id": p.created_by_user_id,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "archived_at": p.archived_at,
    }


def run_to_dict(run: TenantListeningIngestionRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "source_id": run.source_id,
        "source_type": run.source_type,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "fetched_count": run.fetched_count,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "duplicate_count": run.duplicate_count,
        "rejected_count": run.rejected_count,
        "error_count": run.error_count,
        "match_count": run.match_count,
        "error_summary": run.error_summary,
        "cursor_before": run.cursor_before,
        "cursor_after": run.cursor_after,
        "freshness_watermark": run.freshness_watermark,
        "provider_request_id": run.provider_request_id,
        "created_by_user_id": run.created_by_user_id,
        "created_at": run.created_at,
    }


async def list_mentions(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    project_id: UUID | None = None,
    subject_id: UUID | None = None,
    query_id: UUID | None = None,
    source_type: str | None = None,
    review_state: str | None = None,
    language: str | None = None,
    search: str | None = None,
    matched_term: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    limit = clamp_limit(limit)
    offset = max(0, offset)

    filters = [TenantObservedMention.tenant_id == tenant_id]
    if project_id is not None:
        filters.append(TenantObservedMention.project_id == project_id)
    if source_type:
        filters.append(TenantObservedMention.source_type == source_type)
    if review_state:
        filters.append(TenantObservedMention.review_state == review_state)
    if language:
        filters.append(TenantObservedMention.language == language.lower())
    if published_from is not None:
        filters.append(TenantObservedMention.published_at >= published_from)
    if published_to is not None:
        filters.append(TenantObservedMention.published_at <= published_to)
    if search:
        like = f"%{search.strip()[:200]}%"
        filters.append(
            or_(
                TenantObservedMention.content_text.ilike(like),
                TenantObservedMention.content_excerpt.ilike(like),
                TenantObservedMention.author_display.ilike(like),
            )
        )

    needs_match_join = subject_id is not None or query_id is not None or matched_term
    stmt = select(TenantObservedMention).where(*filters)
    count_stmt = select(func.count()).select_from(TenantObservedMention).where(*filters)

    if needs_match_join:
        match_filters = [
            TenantMentionMatch.tenant_id == tenant_id,
            TenantMentionMatch.mention_id == TenantObservedMention.id,
        ]
        if subject_id is not None:
            match_filters.append(TenantMentionMatch.subject_id == subject_id)
        if query_id is not None:
            match_filters.append(TenantMentionMatch.query_id == query_id)
        if matched_term:
            match_filters.append(TenantMentionMatch.matched_term.ilike(f"%{matched_term.strip()[:200]}%"))
        stmt = (
            select(TenantObservedMention)
            .where(*filters)
            .where(select(TenantMentionMatch.id).where(*match_filters).exists())
        )
        count_stmt = (
            select(func.count())
            .select_from(TenantObservedMention)
            .where(*filters)
            .where(select(TenantMentionMatch.id).where(*match_filters).exists())
        )

    total = int((await db.execute(count_stmt)).scalar_one())
    rows = list(
        (
            await db.execute(
                stmt.order_by(
                    TenantObservedMention.published_at.desc().nullslast(),
                    TenantObservedMention.observed_at.desc(),
                    TenantObservedMention.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )

    mention_ids = [m.id for m in rows]
    matches_by_mention: dict[UUID, list[TenantMentionMatch]] = {mid: [] for mid in mention_ids}
    if mention_ids:
        match_rows = list(
            (
                await db.execute(
                    select(TenantMentionMatch).where(
                        TenantMentionMatch.tenant_id == tenant_id,
                        TenantMentionMatch.mention_id.in_(mention_ids),
                    )
                )
            ).scalars().all()
        )
        for match in match_rows:
            matches_by_mention.setdefault(match.mention_id, []).append(match)

    return [mention_to_dict(m, matches=matches_by_mention.get(m.id, [])) for m in rows], total


async def get_mention(
    db: AsyncSession, tenant_id: UUID, mention_id: UUID,
) -> dict[str, Any]:
    mention = (
        await db.execute(
            select(TenantObservedMention).where(
                TenantObservedMention.id == mention_id,
                TenantObservedMention.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if mention is None:
        raise MentionNotFoundError("observed mention not found")
    matches = list(
        (
            await db.execute(
                select(TenantMentionMatch).where(
                    TenantMentionMatch.tenant_id == tenant_id,
                    TenantMentionMatch.mention_id == mention_id,
                )
            )
        ).scalars().all()
    )
    return mention_detail_dict(mention, matches=matches)


async def list_ingestion_runs(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    project_id: UUID | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    limit = clamp_limit(limit)
    offset = max(0, offset)
    filters = [TenantListeningIngestionRun.tenant_id == tenant_id]
    if project_id is not None:
        filters.append(TenantListeningIngestionRun.project_id == project_id)
    total = int(
        (await db.execute(select(func.count()).select_from(TenantListeningIngestionRun).where(*filters))).scalar_one()
    )
    rows = list(
        (
            await db.execute(
                select(TenantListeningIngestionRun)
                .where(*filters)
                .order_by(TenantListeningIngestionRun.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return [run_to_dict(r) for r in rows], total


async def get_ingestion_run(
    db: AsyncSession, tenant_id: UUID, run_id: UUID,
) -> dict[str, Any]:
    run = (
        await db.execute(
            select(TenantListeningIngestionRun).where(
                TenantListeningIngestionRun.id == run_id,
                TenantListeningIngestionRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise IngestionRunNotFoundError("ingestion run not found")
    return run_to_dict(run)


async def overview(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    projects, project_total = await list_projects(db, tenant_id, limit=50, offset=0)
    mention_total = int(
        (
            await db.execute(
                select(func.count()).select_from(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_id,
                )
            )
        ).scalar_one()
    )
    unreviewed = int(
        (
            await db.execute(
                select(func.count()).select_from(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_id,
                    TenantObservedMention.review_state == "unreviewed",
                )
            )
        ).scalar_one()
    )
    recent, _ = await list_mentions(db, tenant_id, limit=10, offset=0)
    sources = list(
        (
            await db.execute(
                select(TenantListeningSource).where(TenantListeningSource.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    runs, _ = await list_ingestion_runs(db, tenant_id, limit=5, offset=0)

    return {
        "schema_version": LISTENING_SCHEMA_VERSION,
        "coverage_notice": (
            "Coverage is limited to configured supported sources "
            "(manual import and fixture/demo in Phase 1). "
            "This is not whole-market social listening."
        ),
        "live_provider_available": False,
        "project_count": project_total,
        "projects": [project_to_dict(p) for p in projects],
        "mention_total": mention_total,
        "unreviewed_count": unreviewed,
        "recent_mentions": recent,
        "sources": [
            {
                "id": s.id,
                "project_id": s.project_id,
                "source_type": s.source_type,
                "display_name": s.display_name,
                "is_enabled": s.is_enabled,
                "capability_status": s.capability_status,
                "freshness_status": s.freshness_status,
                "freshness_watermark": s.freshness_watermark,
                "last_success_at": s.last_success_at,
            }
            for s in sources
        ],
        "recent_ingestion_runs": runs,
        "source_capabilities": [
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


__all__ = [
    "clamp_limit",
    "mention_to_dict",
    "mention_detail_dict",
    "match_to_dict",
    "project_to_dict",
    "run_to_dict",
    "list_mentions",
    "get_mention",
    "list_ingestion_runs",
    "get_ingestion_run",
    "overview",
]
