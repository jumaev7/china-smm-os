"""Startup validation — database, schema, critical tables, alembic drift."""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.schema_health_service import REQUIRED_TABLES, SchemaHealthService

logger = logging.getLogger(__name__)


class StartupHealthService:
    @staticmethod
    async def run(db: AsyncSession) -> dict:
        logger.info("[SYSTEM STARTUP] Running startup health check")

        db_ok = False
        try:
            await db.execute(text("SELECT 1"))
            db_ok = True
            logger.info("[SYSTEM STARTUP] database connection: ok")
        except Exception as exc:
            logger.error("[SCHEMA ERROR] Database connection failed: %s", exc)
            return {
                "database_connected": False,
                "schema_ok": False,
                "critical_tables_ok": False,
                "migration_drift": True,
                "warnings": [],
                "errors": [f"Database connection failed: {exc}"],
            }

        schema = await SchemaHealthService.check(db)
        errors: list[str] = []
        warnings: list[str] = list(schema.get("warnings") or [])

        if not schema.get("database_connected"):
            errors.append("Schema health reports database disconnected")

        missing_required = [
            t for t in REQUIRED_TABLES
            if t in (schema.get("missing_tables") or [])
        ]
        if missing_required:
            errors.append(f"Critical tables missing: {', '.join(missing_required)}")
            logger.error("[SCHEMA ERROR] Critical tables missing: %s", ", ".join(missing_required))

        if schema.get("missing_columns"):
            msg = f"{len(schema['missing_columns'])} model column(s) missing in database"
            errors.append(msg)
            logger.error("[SCHEMA ERROR] %s", msg)

        if schema.get("migration_drift"):
            msg = "Alembic migration drift detected"
            warnings.append(msg)
            logger.warning("[SCHEMA WARNING] %s (current=%s head=%s)", msg,
                           schema.get("alembic_current_revision"),
                           schema.get("alembic_head_revision"))

        if schema.get("warnings"):
            for w in schema["warnings"]:
                if w not in warnings:
                    warnings.append(w)
                if "missing" in w.lower() or "drift" in w.lower():
                    logger.warning("[SCHEMA WARNING] %s", w)
                else:
                    logger.info("[SYSTEM STARTUP] %s", w)

        schema_ok = not errors and schema.get("ok", False)
        if schema_ok and not warnings:
            logger.info("[SYSTEM STARTUP] schema health: ok")
        elif schema_ok:
            logger.info("[SYSTEM STARTUP] schema health: ok with %s warning(s)", len(warnings))
        else:
            logger.error("[SCHEMA ERROR] schema health check failed with %s error(s)", len(errors))

        return {
            "database_connected": db_ok,
            "schema_ok": schema_ok,
            "critical_tables_ok": not missing_required,
            "migration_drift": bool(schema.get("migration_drift")),
            "schema": schema,
            "warnings": warnings,
            "errors": errors,
        }
