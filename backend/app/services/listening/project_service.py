"""CRUD for listening projects, subjects, queries, and sources."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listening import (
    PROJECT_STATUSES,
    SOURCE_TYPES,
    SUBJECT_TYPES,
    TenantListeningProject,
    TenantListeningQuery,
    TenantListeningSource,
    TenantListeningSubject,
)
from app.services.listening.errors import (
    InvalidProjectStatusError,
    ProjectNotFoundError,
    QueryNotFoundError,
    SourceNotFoundError,
    SourceUnsupportedError,
    SubjectNotFoundError,
)
from app.services.listening.limits import (
    MAX_ALIASES_PER_SUBJECT,
    MAX_EXCLUDE_TERMS_PER_QUERY,
    MAX_INCLUDE_TERMS_PER_QUERY,
    MAX_PROJECTS_PER_TENANT,
    MAX_QUERIES_PER_PROJECT,
    MAX_SOURCES_PER_PROJECT,
    MAX_SUBJECTS_PER_PROJECT,
)
from app.services.listening.providers import get_adapter


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_str_list(values: list[str] | None, *, limit: int) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        term = str(raw).strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(term[:200])
        if len(out) >= limit:
            break
    return out


async def create_project(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    description: str | None = None,
    client_id: UUID | None = None,
    default_locale: str | None = None,
    created_by_user_id: UUID | None = None,
) -> TenantListeningProject:
    count = (
        await db.execute(
            select(func.count()).select_from(TenantListeningProject).where(
                TenantListeningProject.tenant_id == tenant_id,
                TenantListeningProject.status != "archived",
            )
        )
    ).scalar_one()
    if int(count) >= MAX_PROJECTS_PER_TENANT:
        raise InvalidProjectStatusError(
            f"at most {MAX_PROJECTS_PER_TENANT} active/paused projects per tenant",
            details={"limit_key": "MAX_PROJECTS_PER_TENANT"},
        )

    project = TenantListeningProject(
        id=uuid4(),
        tenant_id=tenant_id,
        client_id=client_id,
        name=name.strip()[:200],
        description=(description or "").strip()[:4000] or None,
        status="active",
        default_locale=(default_locale or "").strip()[:10] or None,
        created_by_user_id=created_by_user_id,
    )
    db.add(project)
    await db.flush()

    # Default sources: manual import + fixture (honest capabilities).
    for source_type, display in (
        ("manual_import", "Manual import"),
        ("fixture", "Fixture / demo observations"),
    ):
        caps = get_adapter(source_type).capabilities()
        db.add(
            TenantListeningSource(
                id=uuid4(),
                tenant_id=tenant_id,
                project_id=project.id,
                source_type=source_type,
                source_key="default",
                display_name=display,
                is_enabled=True,
                capability_status=caps.capability_status,
                freshness_status="unavailable",
            )
        )
    await db.flush()
    return project


async def get_project(
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


async def list_projects(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TenantListeningProject], int]:
    filters = [TenantListeningProject.tenant_id == tenant_id]
    if status:
        filters.append(TenantListeningProject.status == status)
    total = (
        await db.execute(select(func.count()).select_from(TenantListeningProject).where(*filters))
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(TenantListeningProject)
                .where(*filters)
                .order_by(TenantListeningProject.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return rows, int(total)


async def update_project(
    db: AsyncSession,
    tenant_id: UUID,
    project_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    default_locale: str | None = None,
) -> TenantListeningProject:
    project = await get_project(db, tenant_id, project_id)
    if name is not None:
        project.name = name.strip()[:200]
    if description is not None:
        project.description = description.strip()[:4000] or None
    if default_locale is not None:
        project.default_locale = default_locale.strip()[:10] or None
    if status is not None:
        if status not in PROJECT_STATUSES:
            raise InvalidProjectStatusError(f"invalid status '{status}'")
        project.status = status
        if status == "archived":
            project.archived_at = _utcnow()
        elif status in {"active", "paused"}:
            project.archived_at = None
    await db.flush()
    return project


async def create_subject(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    subject_type: str,
    canonical_name: str,
    aliases: list[str] | None = None,
    handle: str | None = None,
    domain: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TenantListeningSubject:
    await get_project(db, tenant_id, project_id)
    if subject_type not in SUBJECT_TYPES:
        raise SubjectNotFoundError(f"invalid subject_type '{subject_type}'")
    count = (
        await db.execute(
            select(func.count()).select_from(TenantListeningSubject).where(
                TenantListeningSubject.tenant_id == tenant_id,
                TenantListeningSubject.project_id == project_id,
            )
        )
    ).scalar_one()
    if int(count) >= MAX_SUBJECTS_PER_PROJECT:
        raise InvalidProjectStatusError(
            f"at most {MAX_SUBJECTS_PER_PROJECT} subjects per project",
            details={"limit_key": "MAX_SUBJECTS_PER_PROJECT"},
        )

    # Strip secrets-like keys from metadata.
    safe_meta = None
    if metadata:
        safe_meta = {
            str(k)[:64]: v
            for k, v in metadata.items()
            if str(k).lower() not in {"token", "secret", "password", "api_key", "access_token"}
            and not isinstance(v, (dict, list))
        }
        safe_meta = {k: (str(v)[:200] if not isinstance(v, (int, float, bool)) else v) for k, v in safe_meta.items()}

    subject = TenantListeningSubject(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        subject_type=subject_type,
        canonical_name=canonical_name.strip()[:200],
        aliases_json=_clean_str_list(aliases, limit=MAX_ALIASES_PER_SUBJECT) or None,
        handle=(handle or "").strip().lstrip("@")[:200] or None,
        domain=(domain or "").strip().lower()[:255] or None,
        is_active=True,
        metadata_json=safe_meta or None,
    )
    db.add(subject)
    await db.flush()
    return subject


async def list_subjects(
    db: AsyncSession, tenant_id: UUID, project_id: UUID,
) -> list[TenantListeningSubject]:
    await get_project(db, tenant_id, project_id)
    return list(
        (
            await db.execute(
                select(TenantListeningSubject)
                .where(
                    TenantListeningSubject.tenant_id == tenant_id,
                    TenantListeningSubject.project_id == project_id,
                )
                .order_by(TenantListeningSubject.created_at.asc())
            )
        ).scalars().all()
    )


async def update_subject(
    db: AsyncSession,
    tenant_id: UUID,
    subject_id: UUID,
    *,
    canonical_name: str | None = None,
    aliases: list[str] | None = None,
    handle: str | None = None,
    domain: str | None = None,
    is_active: bool | None = None,
) -> TenantListeningSubject:
    subject = (
        await db.execute(
            select(TenantListeningSubject).where(
                TenantListeningSubject.id == subject_id,
                TenantListeningSubject.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if subject is None:
        raise SubjectNotFoundError("listening subject not found")
    if canonical_name is not None:
        subject.canonical_name = canonical_name.strip()[:200]
    if aliases is not None:
        subject.aliases_json = _clean_str_list(aliases, limit=MAX_ALIASES_PER_SUBJECT) or None
    if handle is not None:
        subject.handle = handle.strip().lstrip("@")[:200] or None
    if domain is not None:
        subject.domain = domain.strip().lower()[:255] or None
    if is_active is not None:
        subject.is_active = bool(is_active)
    await db.flush()
    return subject


async def create_query(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    name: str,
    include_terms: list[str] | None = None,
    exclude_terms: list[str] | None = None,
    source_filters: list[str] | None = None,
    language_filters: list[str] | None = None,
    subject_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
) -> TenantListeningQuery:
    await get_project(db, tenant_id, project_id)
    if subject_id is not None:
        subject = (
            await db.execute(
                select(TenantListeningSubject).where(
                    TenantListeningSubject.id == subject_id,
                    TenantListeningSubject.tenant_id == tenant_id,
                    TenantListeningSubject.project_id == project_id,
                )
            )
        ).scalar_one_or_none()
        if subject is None:
            raise SubjectNotFoundError("listening subject not found")

    count = (
        await db.execute(
            select(func.count()).select_from(TenantListeningQuery).where(
                TenantListeningQuery.tenant_id == tenant_id,
                TenantListeningQuery.project_id == project_id,
            )
        )
    ).scalar_one()
    if int(count) >= MAX_QUERIES_PER_PROJECT:
        raise InvalidProjectStatusError(
            f"at most {MAX_QUERIES_PER_PROJECT} queries per project",
            details={"limit_key": "MAX_QUERIES_PER_PROJECT"},
        )

    include = _clean_str_list(include_terms, limit=MAX_INCLUDE_TERMS_PER_QUERY)
    exclude = _clean_str_list(exclude_terms, limit=MAX_EXCLUDE_TERMS_PER_QUERY)
    if not include and subject_id is None:
        raise InvalidProjectStatusError("query requires include_terms or subject_id")

    query = TenantListeningQuery(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        subject_id=subject_id,
        name=name.strip()[:200],
        include_terms_json=include or None,
        exclude_terms_json=exclude or None,
        source_filters_json=_clean_str_list(source_filters, limit=20) or None,
        language_filters_json=_clean_str_list(language_filters, limit=20) or None,
        is_enabled=True,
        created_by_user_id=created_by_user_id,
    )
    db.add(query)
    await db.flush()
    return query


async def list_queries(
    db: AsyncSession, tenant_id: UUID, project_id: UUID,
) -> list[TenantListeningQuery]:
    await get_project(db, tenant_id, project_id)
    return list(
        (
            await db.execute(
                select(TenantListeningQuery)
                .where(
                    TenantListeningQuery.tenant_id == tenant_id,
                    TenantListeningQuery.project_id == project_id,
                )
                .order_by(TenantListeningQuery.created_at.asc())
            )
        ).scalars().all()
    )


async def update_query(
    db: AsyncSession,
    tenant_id: UUID,
    query_id: UUID,
    *,
    name: str | None = None,
    include_terms: list[str] | None = None,
    exclude_terms: list[str] | None = None,
    source_filters: list[str] | None = None,
    language_filters: list[str] | None = None,
    is_enabled: bool | None = None,
    subject_id: UUID | None = None,
) -> TenantListeningQuery:
    query = (
        await db.execute(
            select(TenantListeningQuery).where(
                TenantListeningQuery.id == query_id,
                TenantListeningQuery.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if query is None:
        raise QueryNotFoundError("listening query not found")
    if name is not None:
        query.name = name.strip()[:200]
    if include_terms is not None:
        query.include_terms_json = _clean_str_list(include_terms, limit=MAX_INCLUDE_TERMS_PER_QUERY) or None
    if exclude_terms is not None:
        query.exclude_terms_json = _clean_str_list(exclude_terms, limit=MAX_EXCLUDE_TERMS_PER_QUERY) or None
    if source_filters is not None:
        query.source_filters_json = _clean_str_list(source_filters, limit=20) or None
    if language_filters is not None:
        query.language_filters_json = _clean_str_list(language_filters, limit=20) or None
    if is_enabled is not None:
        query.is_enabled = bool(is_enabled)
    if subject_id is not None:
        # Nested resources must stay within the same tenant + project.
        subject = (
            await db.execute(
                select(TenantListeningSubject).where(
                    TenantListeningSubject.id == subject_id,
                    TenantListeningSubject.tenant_id == tenant_id,
                    TenantListeningSubject.project_id == query.project_id,
                )
            )
        ).scalar_one_or_none()
        if subject is None:
            raise SubjectNotFoundError("listening subject not found")
        query.subject_id = subject_id
    await db.flush()
    return query


async def list_sources(
    db: AsyncSession, tenant_id: UUID, project_id: UUID,
) -> list[TenantListeningSource]:
    await get_project(db, tenant_id, project_id)
    return list(
        (
            await db.execute(
                select(TenantListeningSource)
                .where(
                    TenantListeningSource.tenant_id == tenant_id,
                    TenantListeningSource.project_id == project_id,
                )
                .order_by(TenantListeningSource.created_at.asc())
            )
        ).scalars().all()
    )


async def update_source(
    db: AsyncSession,
    tenant_id: UUID,
    source_id: UUID,
    *,
    is_enabled: bool | None = None,
    display_name: str | None = None,
    poll_interval_seconds: int | None = None,
) -> TenantListeningSource:
    from app.services.listening.live_sync_service import clamp_poll_interval

    source = (
        await db.execute(
            select(TenantListeningSource).where(
                TenantListeningSource.id == source_id,
                TenantListeningSource.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise SourceNotFoundError("listening source not found")
    if source.source_type not in SOURCE_TYPES:
        raise SourceUnsupportedError(f"source type '{source.source_type}' unsupported")
    if is_enabled is not None:
        source.is_enabled = bool(is_enabled)
        if not source.is_enabled:
            source.health_status = "paused"
    if display_name is not None:
        source.display_name = display_name.strip()[:200]
    if poll_interval_seconds is not None:
        source.poll_interval_seconds = clamp_poll_interval(poll_interval_seconds)
    await db.flush()
    return source


async def ensure_source_limit(
    db: AsyncSession, tenant_id: UUID, project_id: UUID,
) -> None:
    count = (
        await db.execute(
            select(func.count()).select_from(TenantListeningSource).where(
                TenantListeningSource.tenant_id == tenant_id,
                TenantListeningSource.project_id == project_id,
            )
        )
    ).scalar_one()
    if int(count) >= MAX_SOURCES_PER_PROJECT:
        raise InvalidProjectStatusError(
            f"at most {MAX_SOURCES_PER_PROJECT} sources per project",
            details={"limit_key": "MAX_SOURCES_PER_PROJECT"},
        )


async def create_live_source(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    source_type: str,
    publishing_account_id: UUID,
    display_name: str | None = None,
    poll_interval_seconds: int | None = None,
    source_key: str | None = None,
    enabled_capabilities: dict[str, Any] | None = None,
) -> TenantListeningSource:
    """Bind a live read-only adapter to a tenant-owned publishing account."""
    from app.models.listening import LIVE_SOURCE_TYPES
    from app.services.listening.live_credentials import resolve_facebook_page_credentials
    from app.services.listening.live_sync_service import clamp_poll_interval
    from app.services.listening.providers.meta_errors import MetaListeningError
    from app.services.listening.providers.meta_graph_read import PROVIDER_CAPABILITY_VERSION

    await get_project(db, tenant_id, project_id)
    if source_type not in LIVE_SOURCE_TYPES:
        raise SourceUnsupportedError(f"source type '{source_type}' is not a live adapter")
    await ensure_source_limit(db, tenant_id, project_id)

    try:
        bundle = await resolve_facebook_page_credentials(
            db,
            tenant_id=tenant_id,
            publishing_account_id=publishing_account_id,
        )
    except MetaListeningError as exc:
        raise SourceUnsupportedError(str(exc), details={"error_code": exc.code}) from exc

    adapter = get_adapter(source_type)
    caps = adapter.capabilities()
    runtime_preview = {
        **bundle.public_config_overlay(),
        "granted_permissions": bundle.granted_permissions,
    }
    validation = await adapter.validate_configuration(runtime_preview)
    # Allow create even when missing_scope — surface as degraded health so UI can
    # show reconnect instructions without inventing live data.
    health = "unknown"
    failure_code = None
    failure_summary = None
    if validation:
        if any("missing_scope" in v for v in validation):
            health = "missing_scope"
            failure_code = "missing_scope"
            failure_summary = "; ".join(validation)[:500]
        elif any(v.startswith("integration_status:") for v in validation):
            health = "token_expired_or_revoked"
            failure_code = "token_expired_or_revoked"
            failure_summary = "; ".join(validation)[:500]
        else:
            health = "invalid_configuration"
            failure_code = "invalid_configuration"
            failure_summary = "; ".join(validation)[:500]

    key = (source_key or bundle.page_id or "default").strip()[:80]
    existing = (
        await db.execute(
            select(TenantListeningSource).where(
                TenantListeningSource.tenant_id == tenant_id,
                TenantListeningSource.project_id == project_id,
                TenantListeningSource.source_type == source_type,
                TenantListeningSource.source_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise InvalidProjectStatusError(
            "live source already configured for this page/key",
            details={"source_id": str(existing.id)},
        )

    interval = clamp_poll_interval(poll_interval_seconds)
    name = (display_name or "").strip() or f"{caps.source_type}:{bundle.page_name or bundle.page_id}"
    enabled_caps = enabled_capabilities or {
        "owned_content_comments": caps.owned_content_comments,
        "direct_account_mentions": caps.direct_account_mentions,
        "polling": caps.polling,
    }
    source = TenantListeningSource(
        id=uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        source_type=source_type,
        source_key=key,
        display_name=name[:200],
        is_enabled=True,
        capability_status=caps.capability_status,
        config_json=bundle.public_config_overlay(),
        integration_id=bundle.publishing_account_id,
        provider_resource_ref=bundle.page_id,
        health_status=health,
        last_failure_code=failure_code,
        last_failure_summary=failure_summary,
        last_failure_at=None if health == "unknown" else _utcnow(),
        poll_interval_seconds=interval,
        provider_capability_version=PROVIDER_CAPABILITY_VERSION,
        enabled_capabilities_json=enabled_caps,
        freshness_status="unavailable",
    )
    db.add(source)
    await db.flush()
    return source


async def list_bindable_publishing_accounts(
    db: AsyncSession,
    tenant_id: UUID,
) -> list[dict[str, Any]]:
    """Facebook publishing accounts eligible for live listening binding."""
    from app.models.publishing_account import PublishingAccount

    rows = list(
        (
            await db.execute(
                select(PublishingAccount).where(
                    PublishingAccount.tenant_id == tenant_id,
                    PublishingAccount.platform == "facebook",
                ).order_by(PublishingAccount.created_at.desc())
            )
        ).scalars().all()
    )
    out: list[dict[str, Any]] = []
    for account in rows:
        page_id = (account.facebook_page_id or account.account_id or "").strip()
        out.append({
            "id": account.id,
            "platform": account.platform,
            "account_name": account.account_name,
            "status": account.status,
            "facebook_page_id": page_id or None,
            "has_token": bool(account.access_token_encrypted),
        })
    return out


__all__ = [
    "create_project",
    "get_project",
    "list_projects",
    "update_project",
    "create_subject",
    "list_subjects",
    "update_subject",
    "create_query",
    "list_queries",
    "update_query",
    "list_sources",
    "update_source",
    "create_live_source",
    "list_bindable_publishing_accounts",
    "ensure_source_limit",
]
