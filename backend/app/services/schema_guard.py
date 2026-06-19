"""Runtime schema introspection and safe ORM loading when columns are missing."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models.crm_lead import CrmLead

CRM_LEAD_OPTIONAL_ATTRIBUTION = (
    "attribution_source",
    "attribution_campaign",
    "attribution_notes",
    "attributed_by",
    "partner_id",
    "referral_code",
    "attribution_link_id",
)

OPERATOR_TASK_OPTIONAL_EXECUTION = (
    "execution_status",
    "execution_result",
    "executed_at",
)


class SchemaGuard:
    _cache: dict[str, set[str]] = {}

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @classmethod
    async def refresh(cls, db: AsyncSession) -> None:
        conn = await db.connection()

        def _read(connection) -> None:
            from sqlalchemy import inspect as sa_inspect

            inspector = sa_inspect(connection)
            cls._cache = {
                table: {c["name"] for c in inspector.get_columns(table)}
                for table in inspector.get_table_names()
            }

        await conn.run_sync(_read)

    @classmethod
    async def table_columns(cls, db: AsyncSession, table: str) -> set[str]:
        if table not in cls._cache:
            await cls.refresh(db)
        return set(cls._cache.get(table, set()))

    @classmethod
    async def table_exists(cls, db: AsyncSession, table: str) -> bool:
        if not cls._cache:
            await cls.refresh(db)
        return table in cls._cache

    @classmethod
    def missing_columns(cls, table: str, expected: set[str]) -> list[str]:
        existing = cls._cache.get(table, set())
        return sorted(expected - existing)

    @classmethod
    async def crm_lead_attribution_available(cls, db: AsyncSession) -> bool:
        cols = await cls.table_columns(db, "crm_leads")
        return "attribution_link_id" in cols

    @classmethod
    async def crm_lead_load_options(cls, db: AsyncSession) -> Any:
        available = await cls.table_columns(db, "crm_leads")
        if not available:
            return None
        mapped = []
        for col in CrmLead.__table__.columns:
            if col.name in available:
                mapped.append(getattr(CrmLead, col.name))
        if not mapped:
            return None
        return load_only(*mapped)

    @classmethod
    def lead_attr(cls, lead: CrmLead, name: str, available: set[str]) -> Any:
        if name not in available:
            return None
        return lead.__dict__.get(name)

    @classmethod
    async def apply_crm_lead_query_options(cls, db: AsyncSession, query):
        opts = await cls.crm_lead_load_options(db)
        if opts is not None:
            return query.options(opts)
        return query
