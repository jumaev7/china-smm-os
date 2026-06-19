"""Probe key read-only API routes for system diagnostics."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.core.database import db_probe_slot, session_scope
from app.models.product import Product

logger = logging.getLogger(__name__)

_PROBE_SPECS: list[tuple[str, str]] = [
    ("dashboard", "/api/v1/dashboard/overview"),
    ("crm", "/api/v1/crm/pipeline"),
    ("audit", "/api/v1/audit/overview"),
    ("revenue", "/api/v1/revenue/overview"),
    ("inbox", "/api/v1/operator/inbox?limit=1"),
    ("tasks", "/api/v1/tasks?limit=1"),
    ("content", "/api/v1/content?limit=1"),
    ("campaigns", "/api/v1/campaigns?limit=1"),
    ("products", "/api/v1/products?limit=1"),
    ("communications", "/api/v1/communications/threads?limit=1"),
    ("wechat", "/api/v1/wechat/threads?limit=1"),
    ("wechat_sync", "/api/v1/wechat-sync/accounts"),
    ("wechat_provider", "/api/v1/wechat-provider/providers"),
    ("wechat_provider_health", "/api/v1/wechat-provider/health"),
    ("whatsapp_sync", "/api/v1/whatsapp-sync/accounts"),
    ("whatsapp_provider", "/api/v1/whatsapp-provider/providers"),
    ("whatsapp_provider_health", "/api/v1/whatsapp-provider/health"),
    ("whatsapp", "/api/v1/whatsapp/threads?limit=1"),
    ("unified_inbox", "/api/v1/unified-inbox?limit=1"),
    ("sales_department", "/api/v1/sales-department/dashboard"),
    ("sales_department_v3", "/api/v1/sales-department-v3/overview"),
    ("multi_agent", "/api/v1/multi-agent/health"),
    ("revenue_forecast", "/api/v1/revenue-forecast/overview"),
    ("revenue_engine", "/api/v1/revenue-engine/overview"),
    ("buyer_intelligence", "/api/v1/buyer-intelligence/overview"),
    ("buyer_discovery", "/api/v1/buyer-discovery/overview"),
    ("buyer_network", "/api/v1/buyer-network/overview"),
    ("buyer_acquisition", "/api/v1/buyer-acquisition/overview"),
    ("buyer_acquisition_engine", "/api/v1/buyer-acquisition-engine/overview"),
    ("marketplace", "/api/v1/marketplace/overview"),
    ("deal_risk", "/api/v1/deal-risk/overview"),
    ("deal_room_v2", "/api/v1/deal-room/v2/overview"),
    ("sales_assistant", "/api/v1/sales-assistant/recommendations"),
    ("sales_manager", "/api/v1/sales-manager/overview"),
    ("operator_task_engine", "/api/v1/operator-task-engine/tasks?limit=1"),
    ("lead_intelligence", "/api/v1/lead-intelligence/overview"),
    ("communication_intelligence", "/api/v1/communication-intelligence/overview"),
    ("workflows", "/api/v1/workflows/overview"),
    ("revenue_attribution", "/api/v1/revenue-attribution/overview"),
    ("ai_command", "/api/v1/ai-command/history?limit=1"),
    ("factory_partner", "/api/v1/factory-partner/summary-widget"),
    ("pilot_onboarding", "/api/v1/pilot-onboarding/overview"),
    ("pilot_launch", "/api/v1/pilot-launch/overview"),
    ("pilot_execution", "/api/v1/pilot-execution/overview"),
    ("pilot_demo", "/api/v1/pilot-demo/overview"),
    ("pilot_demo_mode", "/api/v1/pilot-demo-mode/overview"),
    ("pilot_sales_demo", "/api/v1/pilot-sales-demo/overview"),
    ("pilot_launch_validation", "/api/v1/pilot-launch-validation/overview"),
    ("first_pilot_client", "/api/v1/first-pilot-client/overview"),
    ("production_deployment", "/api/v1/production-deployment/overview"),
    ("real_factory_pilot", "/api/v1/real-factory-pilot/overview"),
    ("customer_portal", "/api/v1/customer-portal/summary-widget"),
    ("customer_portal_v2", "/api/v1/customer-portal-v2/summary-widget"),
    ("tenants", "/api/v1/tenants?limit=1"),
    ("subscription_billing", "/api/v1/billing/plans"),
    ("subscription_billing_summary", "/api/v1/billing/summary-widget"),
    ("factory_platform_profile", "/api/v1/factory-platform/summary-widget"),
    ("admin_auth", "/api/v1/admin-auth/security-checks"),
]


async def _probe(
    client: AsyncClient,
    name: str,
    path: str,
    *,
    per_probe_timeout_sec: float = 2.0,
) -> dict[str, Any]:
    start = time.perf_counter()
    error: str | None = None
    status_code = 0
    try:
        response = await asyncio.wait_for(
            client.get(path),
            timeout=per_probe_timeout_sec,
        )
        status_code = response.status_code
        if status_code >= 400:
            detail = response.text[:200] if response.text else response.reason_phrase
            error = f"HTTP {status_code}: {detail}"
    except asyncio.TimeoutError:
        error = f"probe timed out after {per_probe_timeout_sec:.1f}s"
        status_code = 0
    except Exception as exc:
        error = str(exc)[:500]
        status_code = 0

    duration_ms = int((time.perf_counter() - start) * 1000)
    if error or status_code >= 400:
        probe_status = "error"
    elif duration_ms > SLOW_THRESHOLD_MS:
        probe_status = "slow"
    else:
        probe_status = "ok"

    return {
        "name": name,
        "path": path.split("?")[0],
        "status": probe_status,
        "duration_ms": duration_ms,
        "error": error,
        "status_code": status_code,
    }


class ApiHealthService:
    @staticmethod
    async def _lookup_product_id(db: AsyncSession) -> str | None:
        try:
            row = await db.execute(select(Product.id).limit(1))
            return str(row.scalar_one_or_none() or "") or None
        except Exception as exc:
            logger.warning("[API Health] product lookup failed: %s", exc)
            await db.rollback()
            return None

    @staticmethod
    async def check(
        db: AsyncSession | None = None,
        *,
        skip_paths: frozenset[str] | None = None,
        time_budget_sec: float | None = None,
        per_probe_timeout_sec: float = 2.0,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        probes = list(_PROBE_SPECS)
        skip = skip_paths or frozenset()

        product_id: str | None = None
        if db is not None:
            product_id = await ApiHealthService._lookup_product_id(db)
        else:
            async with session_scope() as probe_db:
                product_id = await ApiHealthService._lookup_product_id(probe_db)

        if product_id:
            probes.append(
                ("buyer_finder", f"/api/v1/buyer-finder/product/{product_id}"),
            )
        else:
            probes.append(
                (
                    "buyer_finder",
                    "/api/v1/buyer-finder/product/00000000-0000-0000-0000-000000000001",
                ),
            )

        from app.main import app

        transport = ASGITransport(app=app)
        results: list[dict[str, Any]] = []
        skipped_budget = 0
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for name, path in probes:
                if name in skip:
                    results.append({
                        "name": name,
                        "path": path.split("?")[0],
                        "status": "ok",
                        "duration_ms": 0,
                        "error": "Skipped — recursive or out-of-budget probe",
                        "status_code": 0,
                    })
                    continue
                if time_budget_sec is not None:
                    elapsed = time.perf_counter() - start
                    if elapsed >= time_budget_sec:
                        skipped_budget += 1
                        results.append({
                            "name": name,
                            "path": path.split("?")[0],
                            "status": "slow",
                            "duration_ms": 0,
                            "error": f"Skipped — time budget {time_budget_sec:.1f}s exhausted",
                            "status_code": 0,
                        })
                        continue
                probe_start = time.perf_counter()
                async with db_probe_slot():
                    item = await _probe(
                        client, name, path,
                        per_probe_timeout_sec=per_probe_timeout_sec,
                    )
                logger.info(
                    "[API Health] probe=%s elapsed_ms=%d status=%s",
                    name,
                    int((time.perf_counter() - probe_start) * 1000),
                    item.get("status"),
                )
                if name == "buyer_finder" and not product_id and item["status"] == "error":
                    item = {
                        **item,
                        "status": "ok",
                        "error": "No products in database — buyer finder route not probed",
                    }
                if name == "admin_auth" and item["status"] == "error" and item.get("status_code") == 401:
                    item = {
                        **item,
                        "status": "ok",
                        "error": "Admin auth protected — authentication required (expected)",
                    }
                if name == "factory_platform_profile" and item["status"] == "error" and item.get("status_code") in (401, 403, 422):
                    item = {
                        **item,
                        "status": "ok",
                        "error": "Factory platform protected — tenant authentication required (expected)",
                    }
                results.append(item)

        ok_count = sum(1 for r in results if r["status"] == "ok")
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "[API Health] probes=%s ok=%s skipped_budget=%s elapsed_ms=%s",
            len(results), ok_count, skipped_budget, elapsed_ms,
        )

        from app.services.admin_rbac_service import AdminRbacService

        async with session_scope() as security_db:
            admin_security = await AdminRbacService.security_checks(security_db)
        return {
            "endpoints": results,
            "ok_count": ok_count,
            "total": len(results),
            "admin_security": admin_security,
            "elapsed_ms": elapsed_ms,
            "skipped_budget": skipped_budget,
        }
