"""Read-only ingestion orchestration for Social Listening Phase 1.

Idempotent upsert of observed mentions with deterministic dedupe, matching,
and ingestion-run observability. Never calls provider mutation APIs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listening import (
    DEDUPE_VERSION,
    FRESHNESS_STATUSES,
    TenantListeningIngestionRun,
    TenantListeningProject,
    TenantListeningQuery,
    TenantListeningSource,
    TenantListeningSubject,
    TenantMentionMatch,
    TenantObservedMention,
)
from app.services.listening.errors import (
    ImportValidationError,
    ProjectArchivedError,
    ProjectNotFoundError,
    ProjectPausedError,
    SourceNotFoundError,
    SourceUnsupportedError,
)
from app.services.listening.limits import (
    AGING_MAX_AGE_SECONDS,
    FRESH_MAX_AGE_SECONDS,
    MAX_ITEMS_PER_INGESTION_RUN,
)
from app.services.listening.matching import match_mention_against_queries
from app.services.listening.normalize import normalize_observation, utcnow
from app.services.listening.providers import get_adapter
from app.services.listening.schemas import NormalizedMentionDraft

logger = logging.getLogger(__name__)


def _freshness_status(last_success_at: datetime | None) -> str:
    if last_success_at is None:
        return "unavailable"
    age = (utcnow() - last_success_at).total_seconds()
    if age <= FRESH_MAX_AGE_SECONDS:
        return "fresh"
    if age <= AGING_MAX_AGE_SECONDS:
        return "aging"
    return "stale"


async def _load_project(
    db: AsyncSession, tenant_id: UUID, project_id: UUID,
) -> TenantListeningProject:
    project = (
        await db.execute(
            select(TenantListeningProject).where(
                TenantListeningProject.id == project_id,
                TenantListeningProject.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise ProjectNotFoundError("listening project not found")
    return project


async def _load_queries_and_subjects(
    db: AsyncSession, tenant_id: UUID, project_id: UUID,
) -> tuple[list[TenantListeningQuery], dict[UUID, TenantListeningSubject]]:
    queries = list(
        (
            await db.execute(
                select(TenantListeningQuery).where(
                    TenantListeningQuery.tenant_id == tenant_id,
                    TenantListeningQuery.project_id == project_id,
                    TenantListeningQuery.is_enabled.is_(True),
                )
            )
        ).scalars().all()
    )
    subjects = list(
        (
            await db.execute(
                select(TenantListeningSubject).where(
                    TenantListeningSubject.tenant_id == tenant_id,
                    TenantListeningSubject.project_id == project_id,
                    TenantListeningSubject.is_active.is_(True),
                )
            )
        ).scalars().all()
    )
    return queries, {s.id: s for s in subjects}


async def _find_existing_mention(
    db: AsyncSession,
    tenant_id: UUID,
    draft: NormalizedMentionDraft,
) -> TenantObservedMention | None:
    if draft.provider_external_id:
        existing = (
            await db.execute(
                select(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_id,
                    TenantObservedMention.source_type == draft.source_type,
                    TenantObservedMention.provider_account_ref == draft.provider_account_ref,
                    TenantObservedMention.provider_external_id == draft.provider_external_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    existing = (
        await db.execute(
            select(TenantObservedMention).where(
                TenantObservedMention.tenant_id == tenant_id,
                TenantObservedMention.dedupe_key == draft.dedupe_key,
            )
        )
    ).scalar_one_or_none()
    return existing


def _apply_mutable_updates(mention: TenantObservedMention, draft: NormalizedMentionDraft) -> bool:
    """Update mutable observation fields. Preserve first_observed_at.

    Returns True when any field changed (counts as update, not pure duplicate).
    """
    changed = False
    mention.last_observed_at = draft.observed_at

    # Content edits: update text/fingerprint when provider content changed.
    if draft.content_fingerprint != mention.content_fingerprint:
        mention.content_text = draft.content_text
        mention.content_excerpt = draft.content_excerpt
        mention.content_fingerprint = draft.content_fingerprint
        mention.dedupe_version = draft.dedupe_version or DEDUPE_VERSION
        changed = True

    if draft.canonical_url and draft.canonical_url != mention.canonical_url:
        mention.canonical_url = draft.canonical_url
        changed = True

    if draft.engagement_json is not None and draft.engagement_json != mention.engagement_json:
        mention.engagement_json = draft.engagement_json
        changed = True

    # published_at: fill if previously unknown; never invent; allow provider correction.
    if draft.published_at is not None and mention.published_at != draft.published_at:
        mention.published_at = draft.published_at
        changed = True

    if draft.source_updated_at is not None and mention.source_updated_at != draft.source_updated_at:
        mention.source_updated_at = draft.source_updated_at
        changed = True

    if draft.language and draft.language != mention.language:
        mention.language = draft.language
        changed = True

    if draft.author_display and draft.author_display != mention.author_display:
        mention.author_display = draft.author_display
        changed = True

    # Merge provenance safely (no secrets).
    prov = dict(mention.provenance_json or {})
    prov.update({k: v for k, v in (draft.provenance_json or {}).items() if k != "raw_payload"})
    prov["last_ingestion_run_id"] = draft.provenance_json.get("ingestion_run_id") if draft.provenance_json else None
    mention.provenance_json = prov
    mention.observed_at = draft.observed_at
    return changed


async def _upsert_matches(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    mention_id: UUID,
    evidence_list,
) -> int:
    created = 0
    for evidence in evidence_list:
        existing = (
            await db.execute(
                select(TenantMentionMatch).where(
                    TenantMentionMatch.tenant_id == tenant_id,
                    TenantMentionMatch.mention_id == mention_id,
                    TenantMentionMatch.query_id == evidence.query_id,
                    TenantMentionMatch.matched_term == evidence.matched_term,
                    TenantMentionMatch.match_type == evidence.match_type,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(
            TenantMentionMatch(
                id=uuid4(),
                tenant_id=tenant_id,
                mention_id=mention_id,
                query_id=evidence.query_id,
                subject_id=evidence.subject_id,
                match_type=evidence.match_type,
                matched_term=evidence.matched_term[:255],
                evidence_excerpt=(evidence.evidence_excerpt or "")[:500] or None,
                evidence_start=evidence.evidence_start,
                evidence_end=evidence.evidence_end,
                matcher_version=evidence.matcher_version,
            )
        )
        created += 1
    return created


async def ingest_observations(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    source_type: str,
    trigger_type: str = "manual",
    source_id: UUID | None = None,
    items: list[dict[str, Any]] | None = None,
    cursor: str | None = None,
    created_by_user_id: UUID | None = None,
    allow_paused: bool = False,
) -> TenantListeningIngestionRun:
    """Run a read-only ingestion for a project/source.

    Paused projects reject scheduled ingestion unless ``allow_paused`` (manual
    historical import may still be useful — default False for schedule safety).
    """
    project = await _load_project(db, tenant_id, project_id)
    if project.status == "archived":
        raise ProjectArchivedError("archived listening projects cannot ingest")
    if project.status == "paused" and not allow_paused:
        raise ProjectPausedError("paused listening projects are not scheduled for ingestion")

    source: TenantListeningSource | None = None
    if source_id is not None:
        source = (
            await db.execute(
                select(TenantListeningSource).where(
                    TenantListeningSource.id == source_id,
                    TenantListeningSource.tenant_id == tenant_id,
                    TenantListeningSource.project_id == project_id,
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise SourceNotFoundError("listening source not found")
        source_type = source.source_type

    adapter = get_adapter(source_type)
    caps = adapter.capabilities()
    if caps.capability_status == "unsupported":
        raise SourceUnsupportedError(
            caps.unsupported_reason or f"source '{source_type}' unsupported",
            details={"source_type": source_type},
        )

    run = TenantListeningIngestionRun(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        source_id=source.id if source else None,
        source_type=source_type,
        trigger_type=trigger_type,
        status="running",
        started_at=utcnow(),
        cursor_before=cursor,
        created_by_user_id=created_by_user_id,
    )
    db.add(run)
    await db.flush()

    created = updated = duplicates = rejected = errors = matches = 0
    fatal_error: str | None = None
    page_error: str | None = None
    next_cursor: str | None = None
    provider_request_id: str | None = None
    watermark: datetime | None = None

    try:
        page = await adapter.fetch_observations(
            config=source.config_json if source else None,
            cursor=cursor,
            limit=MAX_ITEMS_PER_INGESTION_RUN,
            items=items,
        )
        next_cursor = page.next_cursor
        provider_request_id = page.provider_request_id
        page_error = page.error_summary
        run.fetched_count = page.fetched_count
        # Malformed items remain in page.items and are counted in the loop below
        # (do not also add page.rejected_count — that would double-count).

        queries, subjects_by_id = await _load_queries_and_subjects(db, tenant_id, project_id)

        for raw in page.items:
            if raw.malformed:
                rejected += 1
                continue
            try:
                draft = normalize_observation(
                    raw,
                    source_type=source_type,
                    observed_at=utcnow(),
                    ingestion_run_id=str(run.id),
                    project_id=str(project_id),
                )
                if draft is None:
                    rejected += 1
                    continue

                existing = await _find_existing_mention(db, tenant_id, draft)
                if existing is None:
                    mention = TenantObservedMention(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        project_id=project_id,
                        source_id=source.id if source else None,
                        source_type=draft.source_type,
                        observation_origin=draft.observation_origin,
                        provider_account_ref=draft.provider_account_ref,
                        provider_external_id=draft.provider_external_id,
                        canonical_url=draft.canonical_url,
                        author_display=draft.author_display,
                        author_external_id=draft.author_external_id,
                        content_text=draft.content_text,
                        content_excerpt=draft.content_excerpt,
                        content_type=draft.content_type,
                        language=draft.language,
                        published_at=draft.published_at,
                        source_updated_at=draft.source_updated_at,
                        observed_at=draft.observed_at,
                        first_observed_at=draft.observed_at,
                        last_observed_at=draft.observed_at,
                        engagement_json=draft.engagement_json,
                        content_fingerprint=draft.content_fingerprint,
                        dedupe_key=draft.dedupe_key,
                        dedupe_version=draft.dedupe_version,
                        normalization_version=draft.normalization_version,
                        review_state="unreviewed",
                        ingestion_run_id=run.id,
                        provenance_json=draft.provenance_json,
                    )
                    db.add(mention)
                    await db.flush()
                    created += 1
                    target = mention
                else:
                    changed = _apply_mutable_updates(existing, draft)
                    existing.ingestion_run_id = run.id
                    if existing.project_id is None:
                        existing.project_id = project_id
                    if changed:
                        updated += 1
                    else:
                        duplicates += 1
                    target = existing

                evidence = match_mention_against_queries(
                    content_text=target.content_text,
                    canonical_url=target.canonical_url,
                    author_display=target.author_display,
                    language=target.language,
                    source_type=target.source_type,
                    queries=queries,
                    subjects_by_id=subjects_by_id,
                )
                matches += await _upsert_matches(
                    db, tenant_id=tenant_id, mention_id=target.id, evidence_list=evidence,
                )
                await db.flush()

                candidate_wm = target.published_at or target.observed_at
                if candidate_wm and (watermark is None or candidate_wm > watermark):
                    watermark = candidate_wm
            except Exception as exc:  # noqa: BLE001 — one bad item must not fail the page
                errors += 1
                logger.warning(
                    "listening_ingest_item_failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "project_id": str(project_id),
                        "source_type": source_type,
                        "run_id": str(run.id),
                        "error": type(exc).__name__,
                    },
                )
    except Exception as exc:  # noqa: BLE001
        fatal_error = type(exc).__name__
        logger.exception(
            "listening_ingest_run_failed",
            extra={
                "tenant_id": str(tenant_id),
                "project_id": str(project_id),
                "source_type": source_type,
                "run_id": str(run.id),
            },
        )

    run.created_count = created
    run.updated_count = updated
    run.duplicate_count = duplicates
    run.rejected_count = rejected
    run.error_count = errors
    run.match_count = matches
    run.completed_at = utcnow()
    run.cursor_after = next_cursor if fatal_error is None else run.cursor_before
    run.provider_request_id = provider_request_id
    run.freshness_watermark = watermark if fatal_error is None else None
    run.checkpoint_json = {
        "advanced": fatal_error is None,
        "dedupe_version": DEDUPE_VERSION,
    }

    summaries = [s for s in (page_error, fatal_error) if s]
    run.error_summary = "; ".join(summaries)[:1000] if summaries else None

    if fatal_error:
        run.status = "failed"
    elif errors or rejected:
        run.status = "partial"
    else:
        run.status = "succeeded"

    if source is not None and fatal_error is None:
        source.last_success_at = run.completed_at
        source.freshness_watermark = watermark
        source.freshness_status = _freshness_status(source.last_success_at)
        if source.freshness_status not in FRESHNESS_STATUSES:
            source.freshness_status = "unavailable"

    await db.flush()
    logger.info(
        "listening_ingest_completed",
        extra={
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "source_type": source_type,
            "run_id": str(run.id),
            "status": run.status,
            "fetched": run.fetched_count,
            "created": created,
            "updated": updated,
            "duplicates": duplicates,
            "rejected": rejected,
            "errors": errors,
            "matches": matches,
            "duration_ms": int(
                ((run.completed_at - run.started_at).total_seconds() * 1000)
                if run.started_at and run.completed_at
                else 0
            ),
        },
    )
    return run


async def run_fixture_ingest(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    source_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
) -> TenantListeningIngestionRun:
    return await ingest_observations(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        source_type="fixture",
        trigger_type="fixture",
        source_id=source_id,
        created_by_user_id=created_by_user_id,
        allow_paused=True,
    )


async def run_manual_import(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    items: list[dict[str, Any]],
    source_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
) -> TenantListeningIngestionRun:
    if not isinstance(items, list):
        raise ImportValidationError("items must be a list")
    if len(items) > MAX_ITEMS_PER_INGESTION_RUN:
        raise ImportValidationError(
            f"at most {MAX_ITEMS_PER_INGESTION_RUN} items per import",
            details={"limit_key": "MAX_ITEMS_PER_INGESTION_RUN"},
        )
    return await ingest_observations(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        source_type="manual_import",
        trigger_type="import",
        source_id=source_id,
        items=items,
        created_by_user_id=created_by_user_id,
        allow_paused=True,
    )


def projects_eligible_for_scheduled_ingestion(status: str) -> bool:
    """Paused/archived projects must not be scheduled for future ingestion."""
    return status == "active"


__all__ = [
    "ingest_observations",
    "run_fixture_ingest",
    "run_manual_import",
    "projects_eligible_for_scheduled_ingestion",
]
