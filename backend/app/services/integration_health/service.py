"""Canonical IntegrationHealthService — read-only diagnostics.

Persists diagnostic snapshots in PublishingAccount.account_metadata_json
(key: integration_health). No schema migration. No provider mutations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import get_auth_context
from app.models.publishing_account import PublishingAccount
from app.services.integration_health.checks import (
    evaluate_advertising_accounts,
    evaluate_generic_publishing_account,
    evaluate_listening_sources,
    evaluate_meta_account,
    evaluate_telegram_tenant,
)
from app.services.integration_health.persistence import (
    clear_transient_state,
    read_diagnostic,
    write_diagnostic,
)
from app.services.integration_health.taxonomy import (
    REASON_HEALTHY,
    REASON_MISSING_OPTIONAL_SCOPE,
    REASON_APP_REVIEW_REQUIRED,
    REASON_MOCK_MODE,
)
from app.services.integration_health.types import IntegrationHealthResult
from app.services.platform_audit_service import PlatformAuditService

logger = logging.getLogger(__name__)

META_PLATFORMS = frozenset({"facebook", "instagram"})

# In-process lock to prevent duplicate concurrent checks per integration.
_check_locks: dict[str, Any] = {}
_check_locks_guard = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _lock_for(key: str):
    import asyncio

    global _check_locks_guard
    if _check_locks_guard is None:
        _check_locks_guard = asyncio.Lock()
    async with _check_locks_guard:
        if key not in _check_locks:
            _check_locks[key] = asyncio.Lock()
        return _check_locks[key]


def _tenant_scope(tenant_id: UUID | None) -> UUID | None:
    ctx = get_auth_context()
    if ctx and ctx.is_admin:
        return tenant_id
    if ctx and ctx.tenant_id:
        if tenant_id is not None and tenant_id != ctx.tenant_id:
            raise HTTPException(status_code=404, detail="Not found")
        return ctx.tenant_id
    if tenant_id is not None:
        return tenant_id
    raise HTTPException(status_code=401, detail="Authentication required")


def _client_allowed(client_id: UUID | None) -> None:
    if client_id is None:
        return
    ctx = get_auth_context()
    if not ctx or ctx.is_admin:
        return
    if ctx.client_ids and client_id not in ctx.client_ids:
        raise HTTPException(status_code=404, detail="Not found")


def _result_to_snapshot(result: IntegrationHealthResult) -> dict[str, Any]:
    snap = {
        "status": result.status,
        "severity": result.severity,
        "reason_code": result.reason_code,
        "reason": result.reason,
        "checked_at": result.checked_at.isoformat() if result.checked_at else None,
        "last_success_at": result.last_success_at.isoformat() if result.last_success_at else None,
        "stale_after_seconds": result.stale_after_seconds,
        "requires_operator_action": result.requires_operator_action,
        "responsible_party": result.responsible_party,
        "recommended_next_step": result.recommended_next_step,
        "capabilities": [c.to_dict() for c in result.capabilities],
        "source": result.source,
        "never_checked": result.never_checked,
        "transient_failure_count": result.transient_failure_count,
        "escalated": bool(result.diagnostic.get("escalated")),
        "safe_auto_recheck": result.safe_auto_recheck,
        "provider_error_class": result.diagnostic.get("provider_error_class"),
    }
    if result.reason_code in (
        REASON_HEALTHY,
        REASON_MISSING_OPTIONAL_SCOPE,
        REASON_APP_REVIEW_REQUIRED,
        REASON_MOCK_MODE,
    ) and result.transient_failure_count == 0:
        snap = clear_transient_state(snap)
    return snap


class IntegrationHealthService:
    """Evaluate and list integration health (read-only toward providers)."""

    @classmethod
    async def evaluate_account(
        cls,
        db: AsyncSession,
        account: PublishingAccount,
        *,
        live_check: bool = False,
        persist: bool = True,
    ) -> IntegrationHealthResult:
        lock = await _lock_for(f"account:{account.id}")
        async with lock:
            prior = read_diagnostic(account)
            if account.platform in META_PLATFORMS:
                result = await evaluate_meta_account(
                    account, live_check=live_check, prior_diag=prior
                )
            else:
                result = await evaluate_generic_publishing_account(
                    account, prior_diag=prior
                )

            if persist:
                write_diagnostic(account, _result_to_snapshot(result))
                # Self-heal diagnostic state only — never mutate provider credentials.
                # Optionally sync canonical status for Meta when live check proves a permanent issue.
                if (
                    live_check
                    and account.platform in META_PLATFORMS
                    and result.reason_code
                    in (
                        "expired_token",
                        "invalid_token",
                        "disconnected",
                        "missing_required_scope",
                        "account_not_found",
                    )
                ):
                    status_map = {
                        "expired_token": "expired",
                        "invalid_token": "invalid",
                        "disconnected": "disconnected",
                        "missing_required_scope": "missing_permissions",
                        "account_not_found": "blocked",
                    }
                    new_status = status_map.get(result.reason_code)
                    if new_status and account.status not in ("mock", "disconnected"):
                        if account.status != new_status:
                            account.status = new_status
                elif (
                    live_check
                    and result.reason_code in (REASON_HEALTHY, REASON_MISSING_OPTIONAL_SCOPE, REASON_APP_REVIEW_REQUIRED)
                    and account.status in ("expired", "invalid", "missing_permissions")
                    and result.status in ("healthy", "degraded")
                ):
                    # Diagnostic recovery: clear attention status when live check recovers.
                    account.status = "connected"

            return result

    @classmethod
    async def get_one(
        cls,
        db: AsyncSession,
        integration_id: str,
        *,
        tenant_id: UUID | None = None,
        live_check: bool = False,
    ) -> IntegrationHealthResult:
        scoped = _tenant_scope(tenant_id)

        # Synthetic telegram/listening ids.
        if integration_id.startswith("telegram:"):
            results = await evaluate_telegram_tenant(
                db, tenant_id=scoped, live_webhook=live_check  # type: ignore[arg-type]
            )
            for r in results:
                if r.integration_id == integration_id:
                    _client_allowed(
                        UUID(r.client_id) if r.client_id else None
                    )
                    return r
            raise HTTPException(status_code=404, detail="Not found")

        if integration_id.startswith("listening:"):
            results = await evaluate_listening_sources(db, tenant_id=scoped)  # type: ignore[arg-type]
            for r in results:
                if r.integration_id == integration_id:
                    return r
            raise HTTPException(status_code=404, detail="Not found")

        try:
            account_uuid = UUID(integration_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

        account = (
            await db.execute(
                select(PublishingAccount).where(PublishingAccount.id == account_uuid)
            )
        ).scalar_one_or_none()
        if account is None:
            # Try advertising account id.
            ads = await evaluate_advertising_accounts(db, tenant_id=scoped)  # type: ignore[arg-type]
            for r in ads:
                if r.integration_id == integration_id:
                    return r
            raise HTTPException(status_code=404, detail="Not found")

        if scoped is not None and account.tenant_id != scoped:
            raise HTTPException(status_code=404, detail="Not found")

        result = await cls.evaluate_account(
            db, account, live_check=live_check, persist=True
        )
        if live_check:
            await db.commit()
            await cls._audit(db, result, event="integration_health.check")
        return result

    @classmethod
    async def list_health(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
        platform: str | None = None,
        status: str | None = None,
        requires_action: bool | None = None,
        live_check: bool = False,
        include_telegram: bool = True,
        include_advertising: bool = True,
        include_listening: bool = True,
    ) -> dict[str, Any]:
        scoped = _tenant_scope(tenant_id)
        _client_allowed(client_id)
        if scoped is None:
            raise HTTPException(status_code=400, detail="tenant_id required")

        results: list[IntegrationHealthResult] = []

        query = select(PublishingAccount).where(PublishingAccount.tenant_id == scoped)
        if platform and platform not in ("listening", "telegram", "advertising", "meta"):
            query = query.where(PublishingAccount.platform == platform)
        elif platform == "meta":
            query = query.where(PublishingAccount.platform.in_(tuple(META_PLATFORMS)))

        accounts = list((await db.scalars(query.order_by(PublishingAccount.platform))).all())

        # Sequential per-account evaluation: AsyncSession is not concurrency-safe.
        # Remote HTTP is still bounded by per-account locks + conservative cadence.
        for account in accounts:
            try:
                result = await cls.evaluate_account(
                    db,
                    account,
                    live_check=live_check and account.platform in META_PLATFORMS,
                    persist=True,
                )
                results.append(result)
            except Exception:
                logger.exception(
                    "Health check failed for account=%s platform=%s",
                    account.id,
                    account.platform,
                )

        if include_telegram and (platform is None or platform == "telegram"):
            try:
                tg = await evaluate_telegram_tenant(
                    db, tenant_id=scoped, live_webhook=live_check
                )
                results.extend(tg)
            except Exception:
                logger.exception("Telegram health batch failed tenant=%s", scoped)

        if include_advertising and (platform is None or platform in ("advertising", "meta", "mock")):
            try:
                ads = await evaluate_advertising_accounts(db, tenant_id=scoped)
                if platform in ("meta", "mock"):
                    ads = [a for a in ads if a.provider == platform]
                results.extend(ads)
            except Exception:
                logger.exception("Advertising health batch failed tenant=%s", scoped)

        if include_listening and (platform is None or platform == "listening"):
            try:
                listening = await evaluate_listening_sources(db, tenant_id=scoped)
                results.extend(listening)
            except Exception:
                logger.exception("Listening health batch failed tenant=%s", scoped)

        if client_id is not None:
            results = [
                r for r in results
                if r.client_id is None or r.client_id == str(client_id)
            ]
        if status:
            results = [r for r in results if r.status == status]
        if requires_action is not None:
            results = [
                r for r in results if r.requires_operator_action is requires_action
            ]

        if live_check:
            await db.commit()
            await cls._audit_batch(db, scoped, len(results))

        summary = cls.summarize(results)
        return {
            "items": [r.to_public_dict() for r in results],
            "total": len(results),
            "summary": summary,
            "checked_at": _utc_now().isoformat(),
            "cache_semantics": (
                "live_provider_probe"
                if live_check
                else "local_evaluation_with_persisted_diagnostics"
            ),
            "live_check": live_check,
        }

    @classmethod
    def summarize(cls, results: list[IntegrationHealthResult]) -> dict[str, int]:
        counts = {
            "healthy": 0,
            "degraded": 0,
            "action_required": 0,
            "unavailable": 0,
            "unknown": 0,
            "stale": 0,
            "requires_action": 0,
        }
        for r in results:
            if r.status in counts:
                counts[r.status] += 1
            if r.stale or r.never_checked:
                counts["stale"] += 1
            if r.requires_operator_action:
                counts["requires_action"] += 1
        return counts

    @classmethod
    async def run_periodic_cycle(
        cls,
        db: AsyncSession,
        *,
        tenant_ids: list[UUID] | None = None,
        live_remote: bool = True,
    ) -> dict[str, Any]:
        """Bounded multi-tenant health cycle for the background scheduler."""
        if tenant_ids is None:
            from app.models.tenant import Tenant

            tenant_ids = list(
                (await db.scalars(select(Tenant.id).order_by(Tenant.created_at))).all()
            )

        totals = {"tenants": 0, "checked": 0, "errors": 0}
        for tid in tenant_ids:
            totals["tenants"] += 1
            try:
                # Bypass auth context for system worker by evaluating accounts directly.
                accounts = list(
                    (
                        await db.scalars(
                            select(PublishingAccount).where(
                                PublishingAccount.tenant_id == tid
                            )
                        )
                    ).all()
                )
                for account in accounts:
                    try:
                        live = live_remote and account.platform in META_PLATFORMS
                        await cls.evaluate_account(
                            db, account, live_check=live, persist=True
                        )
                        totals["checked"] += 1
                    except Exception:
                        totals["errors"] += 1
                        logger.exception(
                            "Periodic health failed account=%s", account.id
                        )
                # Local-only companion domains (no aggressive remote).
                await evaluate_telegram_tenant(db, tenant_id=tid, live_webhook=False)
                await evaluate_advertising_accounts(db, tenant_id=tid)
                await evaluate_listening_sources(db, tenant_id=tid)
                await db.commit()
            except Exception:
                totals["errors"] += 1
                logger.exception("Periodic health failed tenant=%s", tid)
                await db.rollback()
        return totals

    @classmethod
    async def _audit(
        cls,
        db: AsyncSession,
        result: IntegrationHealthResult,
        *,
        event: str,
    ) -> None:
        try:
            await PlatformAuditService.record(
                db,
                event_type=event,
                tenant_id=UUID(result.tenant_id) if result.tenant_id else None,
                actor_type="system",
                resource_type="integration_health",
                resource_id=result.integration_id,
                details={
                    "platform": result.platform,
                    "status": result.status,
                    "reason_code": result.reason_code,
                    "requires_operator_action": result.requires_operator_action,
                    "source": result.source,
                },
                commit=False,
            )
        except Exception:
            logger.debug("integration health audit skipped", exc_info=True)

    @classmethod
    async def _audit_batch(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        count: int,
    ) -> None:
        try:
            await PlatformAuditService.record(
                db,
                event_type="integration_health.batch_check",
                tenant_id=tenant_id,
                actor_type="system",
                resource_type="integration_health",
                resource_id=str(tenant_id),
                details={"checked_count": count},
                commit=False,
            )
        except Exception:
            logger.debug("integration health batch audit skipped", exc_info=True)
