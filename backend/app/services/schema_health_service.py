"""Database schema health — model vs PostgreSQL drift detection."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.services.schema_guard import (
    CRM_LEAD_OPTIONAL_ATTRIBUTION,
    OPERATOR_TASK_OPTIONAL_EXECUTION,
    SchemaGuard,
)

logger = logging.getLogger(__name__)

REQUIRED_TABLES: tuple[str, ...] = (
    "clients",
    "crm_leads",
    "crm_deals",
    "operator_tasks",
    "content_items",
    "publish_attempts",
    "communication_contacts",
    "communication_threads",
    "communication_messages",
    "products",
    "campaigns",
    "media_assets",
    "attribution_links",
    "landing_pages",
    "partners",
)


def _alembic_script() -> ScriptDirectory:
    ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    return ScriptDirectory.from_config(Config(str(ini_path)))


class SchemaHealthService:
    @staticmethod
    async def check(db: AsyncSession) -> dict[str, Any]:
        from app.models import (  # noqa: F401 — register all tables on Base.metadata
            ai_command,
            attribution_link,
            buyer_recommendation,
            landing_page,
            publish_attempt,
            publishing_account,
            subscription,
            wechat_provider,
            wechat_sync,
            whatsapp_provider,
            whatsapp_sync,
        )

        database_connected = False
        snapshot: dict[str, Any] = {}

        try:
            conn = await db.connection()
            database_connected = True
        except Exception as exc:
            logger.error("[Schema Health] database connection failed: %s", exc)
            heads = _alembic_script().get_heads()
            head_revision = heads[0] if heads else None
            return {
                "database_connected": False,
                "alembic_current_revision": None,
                "alembic_head_revision": head_revision,
                "migration_drift": True,
                "missing_tables": list(REQUIRED_TABLES),
                "missing_columns": [],
                "checked_models": list(REQUIRED_TABLES),
                "warnings": [f"Database connection failed: {exc}"],
                "ok": False,
            }

        def _inspect(connection) -> None:
            inspector = sa_inspect(connection)
            db_tables = set(inspector.get_table_names())
            missing_tables: list[str] = []
            missing_columns: list[dict[str, str]] = []
            column_cache: dict[str, set[str]] = {}

            for table_name, table in Base.metadata.tables.items():
                if table_name not in db_tables:
                    missing_tables.append(table_name)
                    continue
                db_cols = {c["name"] for c in inspector.get_columns(table_name)}
                column_cache[table_name] = db_cols
                for col in table.columns:
                    if col.name not in db_cols:
                        missing_columns.append({"table": table_name, "column": col.name})

            current_rev = None
            try:
                current_rev = connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar()
            except Exception:
                connection.rollback()

            snapshot["missing_tables"] = sorted(missing_tables)
            snapshot["missing_columns"] = missing_columns
            snapshot["alembic_current"] = current_rev
            snapshot["db_tables"] = sorted(db_tables)
            snapshot["column_cache"] = column_cache

        await conn.run_sync(_inspect)
        SchemaGuard._cache = snapshot.get("column_cache") or {}

        warnings: list[str] = []
        heads = _alembic_script().get_heads()
        current = snapshot.get("alembic_current")
        head_revision = heads[0] if heads else None
        migration_drift = False

        if not current and snapshot.get("db_tables"):
            migration_drift = True
            warnings.append(
                "alembic_version is empty but database tables exist — run alembic upgrade head"
            )
        elif current and heads and current not in heads:
            migration_drift = True
            warnings.append(
                f"alembic revision {current!r} is not at head {heads!r} — pending migrations may be required"
            )

        required_missing = [
            t for t in REQUIRED_TABLES if t not in set(snapshot.get("db_tables") or [])
        ]
        if required_missing:
            warnings.append(
                f"Required tables missing: {', '.join(required_missing)}"
            )

        crm_missing = SchemaGuard.missing_columns(
            "crm_leads",
            set(CRM_LEAD_OPTIONAL_ATTRIBUTION),
        )
        if crm_missing:
            warnings.append(
                f"crm_leads missing optional attribution columns: {', '.join(crm_missing)}"
            )

        task_missing = SchemaGuard.missing_columns(
            "operator_tasks",
            set(OPERATOR_TASK_OPTIONAL_EXECUTION),
        )
        if task_missing:
            warnings.append(
                f"operator_tasks missing execution columns: {', '.join(task_missing)}"
            )

        if snapshot["missing_tables"]:
            warnings.append(f"{len(snapshot['missing_tables'])} model table(s) missing in database")
        if snapshot["missing_columns"]:
            warnings.append(f"{len(snapshot['missing_columns'])} model column(s) missing in database")

        ok = (
            database_connected
            and not snapshot["missing_tables"]
            and not snapshot["missing_columns"]
            and not migration_drift
        )

        logger.info(
            "[Schema Health] ok=%s connected=%s drift=%s missing_tables=%s missing_columns=%s",
            ok,
            database_connected,
            migration_drift,
            len(snapshot["missing_tables"]),
            len(snapshot["missing_columns"]),
        )

        return {
            "ok": ok,
            "database_connected": database_connected,
            "alembic_current_revision": current,
            "alembic_head_revision": head_revision,
            "migration_drift": migration_drift,
            "missing_tables": snapshot["missing_tables"],
            "missing_columns": snapshot["missing_columns"],
            "checked_models": list(REQUIRED_TABLES),
            "warnings": warnings,
        }
