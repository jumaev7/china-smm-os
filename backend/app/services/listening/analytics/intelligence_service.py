"""Listening Phase 2 intelligence orchestration (computed read layer).

Queries Phase 1 normalized observations. Never calls providers.
"""
from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listening import (
    TenantListeningIngestionRun,
    TenantListeningProject,
    TenantListeningQuery,
    TenantListeningSubject,
    TenantMentionMatch,
    TenantObservedMention,
)
from app.services.listening.analytics.aggregation import (
    build_time_series,
    compute_subject_performance,
    observed_share_of_voice,
)
from app.services.listening.analytics.anomalies import detect_anomalies
from app.services.listening.analytics.contracts import (
    ELIGIBILITY_POLICY_VERSION,
    INSIGHT_METHOD_VERSION,
    AnalysisWindow,
    ReviewPolicy,
)
from app.services.listening.analytics.coverage import (
    assess_coverage,
    comparison_allowed,
)
from app.services.listening.analytics.eligibility import (
    EligibilityFilter,
)
from app.services.listening.analytics.insights import generate_insights
from app.services.listening.analytics.topics import detect_emerging_topics
from app.services.listening.analytics.windows import build_analysis_window
from app.services.listening.errors import ListeningError, ProjectNotFoundError

logger = logging.getLogger(__name__)

MAX_EVIDENCE = 8
MAX_ANALYTICS_MENTIONS = 5000


class InsightNotFoundError(ListeningError):
    code = "listening_insight_not_found"
    http_status = 404


class ListeningIntelligenceService:
    """Tenant-scoped market intelligence over Phase 1 observations."""

    @staticmethod
    async def _ensure_project(db: AsyncSession, tenant_id: UUID, project_id: UUID | None) -> None:
        if project_id is None:
            return
        row = (
            await db.execute(
                select(TenantListeningProject.id).where(
                    TenantListeningProject.tenant_id == tenant_id,
                    TenantListeningProject.id == project_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise ProjectNotFoundError("listening project not found")

    @staticmethod
    def _mention_filters_sql(
        tenant_id: UUID,
        filt: EligibilityFilter,
    ) -> list[Any]:
        clauses: list[Any] = [TenantObservedMention.tenant_id == tenant_id]
        if filt.project_id is not None:
            clauses.append(TenantObservedMention.project_id == filt.project_id)
        origins = sorted(filt.allowed_origins())
        clauses.append(TenantObservedMention.observation_origin.in_(origins))
        clauses.append(TenantObservedMention.review_state.in_(sorted(filt.allowed_review_states())))
        if filt.source_types:
            clauses.append(TenantObservedMention.source_type.in_(sorted(filt.source_types)))
        if filt.content_types:
            clauses.append(TenantObservedMention.content_type.in_(sorted(filt.content_types)))
        if filt.languages:
            # language stored as primary or full tag; match primary subtag via lower prefix.
            lang_clauses = []
            for lang in filt.languages:
                primary = lang.split("-")[0].lower()
                lang_clauses.append(func.lower(TenantObservedMention.language).like(f"{primary}%"))
            clauses.append(or_(*lang_clauses))
        return clauses

    @staticmethod
    async def _load_mentions_for_window(
        db: AsyncSession,
        filt: EligibilityFilter,
        *,
        start: datetime,
        end: datetime,
    ) -> list[TenantObservedMention]:
        clauses = ListeningIntelligenceService._mention_filters_sql(filt.tenant_id, filt)
        # Time-series eligibility requires published_at inside [start, end).
        clauses.extend([
            TenantObservedMention.published_at.is_not(None),
            TenantObservedMention.published_at >= start,
            TenantObservedMention.published_at < end,
        ])
        stmt: Select[Any] = (
            select(TenantObservedMention)
            .where(and_(*clauses))
            .order_by(
                TenantObservedMention.published_at.desc(),
                TenantObservedMention.id.desc(),
            )
            .limit(MAX_ANALYTICS_MENTIONS)
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def _load_quality_inventory(
        db: AsyncSession,
        filt: EligibilityFilter,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        """Counts for data-quality reporting (includes missing published_at)."""
        base = ListeningIntelligenceService._mention_filters_sql(filt.tenant_id, filt)
        # Window membership for inventory: published_at in range OR
        # (published_at IS NULL AND observed_at in range) — counted as missing_ts separately.
        window_clause = or_(
            and_(
                TenantObservedMention.published_at.is_not(None),
                TenantObservedMention.published_at >= start,
                TenantObservedMention.published_at < end,
            ),
            and_(
                TenantObservedMention.published_at.is_(None),
                TenantObservedMention.observed_at >= start,
                TenantObservedMention.observed_at < end,
            ),
        )
        rows = (
            await db.execute(
                select(
                    TenantObservedMention.observation_origin,
                    TenantObservedMention.review_state,
                    TenantObservedMention.published_at,
                ).where(and_(*base, window_clause))
            )
        ).all()
        missing = sum(1 for r in rows if r.published_at is None)
        return {
            "scoped_count": len(rows),
            "missing_timestamp_count": missing,
        }

    @staticmethod
    async def _load_matches(
        db: AsyncSession,
        tenant_id: UUID,
        mention_ids: list[UUID],
        *,
        subject_ids: set[UUID] | None = None,
        query_ids: set[UUID] | None = None,
    ) -> dict[UUID, list[TenantMentionMatch]]:
        if not mention_ids:
            return {}
        clauses = [
            TenantMentionMatch.tenant_id == tenant_id,
            TenantMentionMatch.mention_id.in_(mention_ids),
        ]
        if subject_ids:
            clauses.append(TenantMentionMatch.subject_id.in_(list(subject_ids)))
        if query_ids:
            clauses.append(TenantMentionMatch.query_id.in_(list(query_ids)))
        rows = list(
            (await db.execute(select(TenantMentionMatch).where(and_(*clauses)))).scalars().all()
        )
        by_mention: dict[UUID, list[TenantMentionMatch]] = defaultdict(list)
        for row in rows:
            by_mention[row.mention_id].append(row)
        return by_mention

    @staticmethod
    async def _load_subjects(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        project_id: UUID | None,
        subject_ids: set[UUID] | None = None,
    ) -> list[TenantListeningSubject]:
        clauses = [
            TenantListeningSubject.tenant_id == tenant_id,
            TenantListeningSubject.is_active.is_(True),
        ]
        if project_id is not None:
            clauses.append(TenantListeningSubject.project_id == project_id)
        if subject_ids:
            clauses.append(TenantListeningSubject.id.in_(list(subject_ids)))
        return list(
            (await db.execute(select(TenantListeningSubject).where(and_(*clauses)))).scalars().all()
        )

    @staticmethod
    async def _project_query_counts(
        db: AsyncSession,
        tenant_id: UUID,
        project_id: UUID | None,
    ) -> tuple[int, int]:
        p_clauses = [
            TenantListeningProject.tenant_id == tenant_id,
            TenantListeningProject.status == "active",
        ]
        q_clauses = [
            TenantListeningQuery.tenant_id == tenant_id,
            TenantListeningQuery.is_enabled.is_(True),
        ]
        if project_id is not None:
            p_clauses.append(TenantListeningProject.id == project_id)
            q_clauses.append(TenantListeningQuery.project_id == project_id)
        projects = (
            await db.execute(select(func.count()).select_from(TenantListeningProject).where(and_(*p_clauses)))
        ).scalar_one()
        queries = (
            await db.execute(select(func.count()).select_from(TenantListeningQuery).where(and_(*q_clauses)))
        ).scalar_one()
        return int(projects or 0), int(queries or 0)

    @staticmethod
    async def _ingestion_stats(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        project_id: UUID | None,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        clauses = [
            TenantListeningIngestionRun.tenant_id == tenant_id,
            TenantListeningIngestionRun.created_at >= start,
            TenantListeningIngestionRun.created_at < end,
        ]
        if project_id is not None:
            clauses.append(TenantListeningIngestionRun.project_id == project_id)
        # Exclude fixture-trigger runs from production coverage signals when possible —
        # still count failed non-fixture runs.
        rows = list(
            (await db.execute(select(TenantListeningIngestionRun).where(and_(*clauses)))).scalars().all()
        )
        failed = sum(1 for r in rows if r.status == "failed" and r.source_type != "fixture")
        partial = sum(1 for r in rows if r.status == "partial" and r.source_type != "fixture")
        succeeded = [
            r for r in rows
            if r.status == "succeeded" and r.source_type != "fixture"
        ]
        latest = None
        for r in succeeded:
            ts = r.completed_at or r.freshness_watermark or r.created_at
            if ts is not None and (latest is None or ts > latest):
                latest = ts
        # Also consider latest success outside window for freshness watermark.
        latest_any_stmt = select(TenantListeningIngestionRun).where(
            TenantListeningIngestionRun.tenant_id == tenant_id,
            TenantListeningIngestionRun.status == "succeeded",
            TenantListeningIngestionRun.source_type != "fixture",
            *(
                [TenantListeningIngestionRun.project_id == project_id]
                if project_id is not None
                else []
            ),
        ).order_by(TenantListeningIngestionRun.completed_at.desc().nullslast()).limit(1)
        latest_row = (await db.execute(latest_any_stmt)).scalar_one_or_none()
        if latest_row is not None:
            ts = latest_row.completed_at or latest_row.freshness_watermark or latest_row.created_at
            if ts is not None and (latest is None or ts > latest):
                latest = ts
        return {
            "failed_ingestion_count": failed,
            "partial_ingestion_count": partial,
            "latest_successful_ingestion": latest,
        }

    @staticmethod
    def _build_filter(
        *,
        tenant_id: UUID,
        project_id: UUID | None,
        subject_ids: list[UUID] | None,
        query_ids: list[UUID] | None,
        source_types: list[str] | None,
        content_types: list[str] | None,
        languages: list[str] | None,
        review_policy: ReviewPolicy,
        include_fixture: bool,
        window: AnalysisWindow,
    ) -> EligibilityFilter:
        return EligibilityFilter(
            tenant_id=tenant_id,
            project_id=project_id,
            subject_ids=frozenset(subject_ids) if subject_ids else None,
            query_ids=frozenset(query_ids) if query_ids else None,
            source_types=frozenset(source_types) if source_types else None,
            content_types=frozenset(content_types) if content_types else None,
            languages=frozenset(languages) if languages else None,
            review_policy=review_policy,
            include_fixture=include_fixture,
            window_start=window.start,
            window_end=window.end,
        )

    @staticmethod
    async def _compute_bundle(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        project_id: UUID | None = None,
        subject_ids: list[UUID] | None = None,
        query_ids: list[UUID] | None = None,
        source_types: list[str] | None = None,
        content_types: list[str] | None = None,
        languages: list[str] | None = None,
        review_policy: ReviewPolicy = "default_exclude_irrelevant",
        include_fixture: bool = False,
        window_key: str = "30d",
        start: datetime | None = None,
        end: datetime | None = None,
        timezone_name: str | None = "UTC",
        granularity: str | None = None,
        insight_reviews: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter()
        await ListeningIntelligenceService._ensure_project(db, tenant_id, project_id)

        window = build_analysis_window(
            window_key=window_key,
            start=start,
            end=end,
            timezone_name=timezone_name,
            granularity=granularity,
        )
        filt = ListeningIntelligenceService._build_filter(
            tenant_id=tenant_id,
            project_id=project_id,
            subject_ids=subject_ids,
            query_ids=query_ids,
            source_types=source_types,
            content_types=content_types,
            languages=languages,
            review_policy=review_policy,
            include_fixture=include_fixture,
            window=window,
        )

        current_mentions = await ListeningIntelligenceService._load_mentions_for_window(
            db, filt, start=window.start, end=window.end,
        )
        previous_mentions: list[TenantObservedMention] = []
        if window.comparison_start and window.comparison_end:
            prev_filt = EligibilityFilter(
                tenant_id=filt.tenant_id,
                project_id=filt.project_id,
                subject_ids=filt.subject_ids,
                query_ids=filt.query_ids,
                source_types=filt.source_types,
                content_types=filt.content_types,
                languages=filt.languages,
                review_policy=filt.review_policy,
                include_fixture=filt.include_fixture,
                window_start=window.comparison_start,
                window_end=window.comparison_end,
            )
            previous_mentions = await ListeningIntelligenceService._load_mentions_for_window(
                db, prev_filt, start=window.comparison_start, end=window.comparison_end,
            )

        # Optional subject/query post-filter via matches.
        all_ids = [m.id for m in current_mentions] + [m.id for m in previous_mentions]
        matches = await ListeningIntelligenceService._load_matches(
            db, tenant_id, all_ids,
            subject_ids=set(subject_ids) if subject_ids else None,
            query_ids=set(query_ids) if query_ids else None,
        )

        if subject_ids or query_ids:
            def _keep(m: TenantObservedMention) -> bool:
                rows = matches.get(m.id) or []
                if not rows:
                    return False
                if subject_ids:
                    wanted = {str(x) for x in subject_ids}
                    if not any(r.subject_id and str(r.subject_id) in wanted for r in rows):
                        return False
                if query_ids:
                    wanted_q = {str(x) for x in query_ids}
                    if not any(r.query_id and str(r.query_id) in wanted_q for r in rows):
                        return False
                return True

            current_mentions = [m for m in current_mentions if _keep(m)]
            previous_mentions = [m for m in previous_mentions if _keep(m)]

        subjects = await ListeningIntelligenceService._load_subjects(
            db, tenant_id, project_id=project_id, subject_ids=set(subject_ids) if subject_ids else None,
        )
        # Comparable subjects: same project scope; own_brand + competitor preferred,
        # but include all active subjects in the project when comparing.
        if project_id is not None:
            comparable_subjects = [s for s in subjects if s.project_id == project_id]
        else:
            # Cross-project aggregation still requires subjects from loaded set;
            # prevent mixing by grouping on project when no project filter — use all loaded.
            comparable_subjects = list(subjects)

        # If subject_ids filter provided, those are the comparison set (must be same project).
        if subject_ids:
            comparable_subjects = [s for s in comparable_subjects if s.id in set(subject_ids)]
            project_ids = {s.project_id for s in comparable_subjects}
            if len(project_ids) > 1:
                comparable_subjects = []

        comparable_ids = {str(s.id) for s in comparable_subjects}

        active_projects, active_queries = await ListeningIntelligenceService._project_query_counts(
            db, tenant_id, project_id,
        )
        ingestion = await ListeningIntelligenceService._ingestion_stats(
            db, tenant_id, project_id=project_id, start=window.start, end=window.end,
        )
        inventory = await ListeningIntelligenceService._load_quality_inventory(
            db, filt, start=window.start, end=window.end,
        )

        coverage = assess_coverage(
            eligible_mentions=current_mentions,
            all_scoped_mentions=current_mentions,
            active_project_count=active_projects,
            active_query_count=active_queries,
            comparable_subject_ids=sorted(comparable_ids),
            latest_successful_ingestion=ingestion["latest_successful_ingestion"],
            failed_ingestion_count=ingestion["failed_ingestion_count"],
            partial_ingestion_count=ingestion["partial_ingestion_count"],
            window_start=window.start,
            window_end=window.end,
            include_fixture=include_fixture,
        )
        # Fold inventory missing timestamps into coverage limitations if needed.
        if inventory["missing_timestamp_count"] and coverage.missing_timestamp_count == 0:
            coverage = assess_coverage(
                eligible_mentions=current_mentions,
                all_scoped_mentions=current_mentions,
                active_project_count=active_projects,
                active_query_count=active_queries,
                comparable_subject_ids=sorted(comparable_ids),
                latest_successful_ingestion=ingestion["latest_successful_ingestion"],
                failed_ingestion_count=ingestion["failed_ingestion_count"],
                partial_ingestion_count=ingestion["partial_ingestion_count"],
                window_start=window.start,
                window_end=window.end,
                include_fixture=include_fixture,
            )

        cmp_ok = comparison_allowed(coverage) and bool(window.comparison_valid)
        # Both windows must meet minimum coverage for comparison metrics.
        if cmp_ok and len(previous_mentions) == 0 and coverage.status == "sufficient":
            # Zero previous with healthy current is valid (new_activity paths).
            pass
        if coverage.status in {"unavailable", "insufficient"}:
            cmp_ok = False

        window = AnalysisWindow(
            start=window.start,
            end=window.end,
            timezone=window.timezone,
            granularity=window.granularity,
            window_key=window.window_key,
            comparison_start=window.comparison_start,
            comparison_end=window.comparison_end,
            comparison_valid=cmp_ok,
            completeness_status=coverage.status,
            freshness_watermark=coverage.freshness_watermark,
        )

        matches_map: dict[Any, list[Any]] = {mid: rows for mid, rows in matches.items()}

        series = build_time_series(
            window=window,
            mentions=current_mentions,
            matches_by_mention=matches_map,
            comparable_subject_ids=comparable_ids,
        )
        subject_rows = compute_subject_performance(
            subjects=comparable_subjects,
            current_mentions=current_mentions,
            previous_mentions=previous_mentions if cmp_ok else None,
            matches_by_mention=matches_map,
            comparable_subject_ids=comparable_ids,
            coverage_status=coverage.status,
            comparison_valid=cmp_ok,
            evidence_limit=MAX_EVIDENCE,
        )
        sov = observed_share_of_voice(subject_rows, coverage_status=coverage.status)

        topics: list[Any] = []
        anomalies: list[Any] = []
        insights: list[Any] = []
        suppressed: list[str] = []

        try:
            topics = detect_emerging_topics(
                current_mentions=current_mentions,
                previous_mentions=previous_mentions if cmp_ok else [],
                matches_by_mention=matches_map,
                coverage_status=coverage.status,
                comparison_valid=cmp_ok,
                evidence_limit=MAX_EVIDENCE,
            )
        except Exception:
            logger.exception(
                "listening_topics_failed tenant=%s project=%s",
                tenant_id,
                project_id,
            )
            suppressed.append("topics_detector_error")

        source_cur: Counter[str] = Counter(
            str(m.source_type) for m in current_mentions
        )
        source_prev: Counter[str] = Counter(
            str(m.source_type) for m in previous_mentions
        ) if cmp_ok else Counter()

        evidence_ids = [str(m.id) for m in current_mentions[:MAX_EVIDENCE]]
        try:
            anomalies = detect_anomalies(
                window=window,
                coverage_status=coverage.status,
                current_count=len(current_mentions),
                previous_count=len(previous_mentions) if cmp_ok else None,
                comparison_valid=cmp_ok,
                subject_rows=subject_rows,
                topics=topics,
                source_composition_current=dict(source_cur),
                source_composition_previous=dict(source_prev) if cmp_ok else None,
                failed_ingestion_count=ingestion["failed_ingestion_count"],
                freshness_status=coverage.freshness_status,
                evidence_mention_ids=evidence_ids,
            )
        except Exception:
            logger.exception(
                "listening_anomalies_failed tenant=%s project=%s",
                tenant_id,
                project_id,
            )
            suppressed.append("anomaly_detector_error")

        try:
            insights = generate_insights(
                tenant_id=str(tenant_id),
                window=window,
                coverage_status=coverage.status,
                subject_rows=subject_rows,
                topics=topics,
                anomalies=anomalies,
                review_states=insight_reviews,
            )
        except Exception:
            logger.exception(
                "listening_insights_failed tenant=%s project=%s",
                tenant_id,
                project_id,
            )
            suppressed.append("insights_generator_error")

        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "listening_intelligence_computed tenant=%s project=%s window=%s "
            "eligible=%s coverage=%s duration_ms=%s anomalies=%s topics=%s "
            "suppressed=%s eligibility=%s",
            tenant_id,
            project_id,
            window.window_key,
            len(current_mentions),
            coverage.status,
            duration_ms,
            len(anomalies),
            len(topics),
            suppressed,
            ELIGIBILITY_POLICY_VERSION,
        )

        return {
            "schema_version": "listening_intelligence_v1",
            "eligibility_policy_version": ELIGIBILITY_POLICY_VERSION,
            "window": window.to_dict(),
            "coverage": coverage.to_dict(),
            "eligible_mention_count": len(current_mentions),
            "previous_eligible_mention_count": len(previous_mentions) if cmp_ok else None,
            "comparison_valid": cmp_ok,
            "time_series": [b.to_dict() for b in series],
            "subjects": [s.to_dict() for s in subject_rows],
            "observed_share_of_voice": sov,
            "emerging_topics": [t.to_dict() for t in topics],
            "anomalies": [a.to_dict() for a in anomalies],
            "insights": [i.to_dict() for i in insights],
            "sentiment": {
                "available": False,
                "status": "deferred",
                "reason": "Sentiment classification is not implemented in Phase 2.",
            },
            "limitations": list(coverage.limitations) + [
                "Analytics are deterministic and descriptive — not forecasts.",
                "No provider writes or autonomous actions are performed.",
                "Business Health scoring and domain weights are unchanged.",
            ],
            "suppressed_sections": suppressed,
            "calculation_duration_ms": duration_ms,
            "include_fixture": include_fixture,
            "review_policy": review_policy,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ---- Public read API helpers ----

    @staticmethod
    async def intelligence_overview(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        from app.services.listening.analytics.insight_review_service import load_review_state_map

        reviews = await load_review_state_map(db, tenant_id)
        bundle = await ListeningIntelligenceService._compute_bundle(
            db, tenant_id=tenant_id, insight_reviews=reviews, **kwargs,
        )
        return {
            "schema_version": bundle["schema_version"],
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            "eligible_mention_count": bundle["eligible_mention_count"],
            "previous_eligible_mention_count": bundle["previous_eligible_mention_count"],
            "comparison_valid": bundle["comparison_valid"],
            "top_subjects": bundle["subjects"][:10],
            "observed_share_of_voice": bundle["observed_share_of_voice"],
            "notable_anomalies": [
                a for a in bundle["anomalies"] if a.get("category") == "market_signal"
            ][:5],
            "data_quality_anomalies": [
                a for a in bundle["anomalies"] if a.get("category") == "data_quality"
            ][:5],
            "emerging_topics": bundle["emerging_topics"][:5],
            "insights": bundle["insights"][:10],
            "sentiment": bundle["sentiment"],
            "limitations": bundle["limitations"],
            "suppressed_sections": bundle["suppressed_sections"],
            "generated_at": bundle["generated_at"],
            "include_fixture": bundle["include_fixture"],
            "review_policy": bundle["review_policy"],
        }

    @staticmethod
    async def time_series(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        bundle = await ListeningIntelligenceService._compute_bundle(db, tenant_id=tenant_id, **kwargs)
        return {
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            "comparison_valid": bundle["comparison_valid"],
            "buckets": bundle["time_series"],
            "textual_summary": _series_summary(bundle),
            "limitations": bundle["limitations"],
        }

    @staticmethod
    async def subject_comparison(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        bundle = await ListeningIntelligenceService._compute_bundle(db, tenant_id=tenant_id, **kwargs)
        return {
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            "comparison_valid": bundle["comparison_valid"],
            "subjects": bundle["subjects"],
            "observed_share_of_voice": bundle["observed_share_of_voice"],
            "limitations": bundle["limitations"],
        }

    @staticmethod
    async def share_of_voice(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        bundle = await ListeningIntelligenceService._compute_bundle(db, tenant_id=tenant_id, **kwargs)
        return {
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            **bundle["observed_share_of_voice"],
        }

    @staticmethod
    async def emerging_topics(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        bundle = await ListeningIntelligenceService._compute_bundle(db, tenant_id=tenant_id, **kwargs)
        return {
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            "topics": bundle["emerging_topics"],
            "limitations": bundle["limitations"],
        }

    @staticmethod
    async def anomalies(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        bundle = await ListeningIntelligenceService._compute_bundle(db, tenant_id=tenant_id, **kwargs)
        return {
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            "market_signal": [a for a in bundle["anomalies"] if a.get("category") == "market_signal"],
            "data_quality": [a for a in bundle["anomalies"] if a.get("category") == "data_quality"],
            "limitations": bundle["limitations"],
        }

    @staticmethod
    async def insights(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        from app.services.listening.analytics.insight_review_service import load_review_state_map

        reviews = await load_review_state_map(db, tenant_id)
        bundle = await ListeningIntelligenceService._compute_bundle(
            db, tenant_id=tenant_id, insight_reviews=reviews, **kwargs,
        )
        return {
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            "insights": bundle["insights"],
            "limitations": bundle["limitations"],
        }

    @staticmethod
    async def insight_detail(
        db: AsyncSession,
        tenant_id: UUID,
        insight_key: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from app.services.listening.analytics.insight_review_service import load_review_state_map

        reviews = await load_review_state_map(db, tenant_id)
        bundle = await ListeningIntelligenceService._compute_bundle(
            db, tenant_id=tenant_id, insight_reviews=reviews, **kwargs,
        )
        match = next((i for i in bundle["insights"] if i.get("insight_key") == insight_key), None)
        if match is None:
            raise InsightNotFoundError("insight not found")
        evidence_ids = [UUID(x) for x in (match.get("evidence_mention_ids") or []) if x]
        evidence = []
        if evidence_ids:
            rows = list(
                (
                    await db.execute(
                        select(TenantObservedMention).where(
                            TenantObservedMention.tenant_id == tenant_id,
                            TenantObservedMention.id.in_(evidence_ids),
                        )
                    )
                ).scalars().all()
            )
            by_id = {r.id: r for r in rows}
            for eid in evidence_ids:
                row = by_id.get(eid)
                if row is None:
                    continue
                evidence.append({
                    "id": str(row.id),
                    "project_id": str(row.project_id) if row.project_id else None,
                    "content_excerpt": row.content_excerpt,
                    "canonical_url": row.canonical_url,
                    "published_at": row.published_at.isoformat() if row.published_at else None,
                    "observation_origin": row.observation_origin,
                    "source_type": row.source_type,
                    "review_state": row.review_state,
                })
        return {
            "insight": match,
            "evidence": evidence,
            "coverage": bundle["coverage"],
            "window": bundle["window"],
            "methodology_version": INSIGHT_METHOD_VERSION,
            "limitations": bundle["limitations"],
        }

    @staticmethod
    async def coverage(db: AsyncSession, tenant_id: UUID, **kwargs: Any) -> dict[str, Any]:
        bundle = await ListeningIntelligenceService._compute_bundle(db, tenant_id=tenant_id, **kwargs)
        return {
            "window": bundle["window"],
            "coverage": bundle["coverage"],
            "freshness_watermark": bundle["coverage"].get("freshness_watermark"),
            "limitations": bundle["limitations"],
        }


def _series_summary(bundle: dict[str, Any]) -> str:
    buckets = bundle.get("time_series") or []
    total = bundle.get("eligible_mention_count") or 0
    prev = bundle.get("previous_eligible_mention_count")
    cov = (bundle.get("coverage") or {}).get("status")
    if not buckets:
        return f"No time-series buckets available (coverage={cov})."
    nonempty = sum(1 for b in buckets if (b.get("total_observed_mentions") or 0) > 0)
    parts = [
        f"Observed {total} eligible mentions across {len(buckets)} {bundle['window']['granularity']} buckets "
        f"({nonempty} non-empty).",
    ]
    if bundle.get("comparison_valid") and prev is not None:
        parts.append(f"Previous comparable window had {prev} eligible mentions.")
    elif not bundle.get("comparison_valid"):
        parts.append("Previous-period comparison is unavailable.")
    return " ".join(parts)
