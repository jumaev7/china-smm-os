"""Executive CRM pipeline dashboard — tenant-scoped KPIs, forecast, manager metrics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publishing_account import PublishingAccount
from app.models.sales_crm import (
    DEFAULT_STAGE_PROBABILITY,
    SalesCustomer,
    SalesDeal,
    TERMINAL_STAGES,
)
from app.models.tenant import TenantUser
from app.schemas.crm_pipeline import (
    CrmPipelineDashboardKpis,
    CrmPipelineForecastRow,
    CrmPipelineManagerPerformanceResponse,
    CrmPipelineManagerPerformanceRow,
    CrmPipelinePublishingHealthSummary,
    CrmPipelineRevenueForecastResponse,
)
from app.services.meta_graph_client import token_is_expired
from app.services.publishing_account_service import PublishingAccountService

OPEN_DEAL_STAGES = frozenset({
    "lead", "qualified", "contacted", "meeting_scheduled",
    "proposal_sent", "negotiation", "contract_pending",
    "client_active", "publishing_active", "expansion_upsell",
})
_STALE_DEAL_DAYS = 14
_META_PLATFORMS = frozenset({"facebook", "instagram"})
_META_USABLE_STATUSES = frozenset({"connected", "mock"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _decimal(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _deal_probability(deal: SalesDeal) -> int:
    if deal.probability is not None:
        return int(deal.probability)
    return int(DEFAULT_STAGE_PROBABILITY.get(deal.stage, 0))


def _weighted_revenue(deal: SalesDeal) -> Decimal:
    value = _decimal(deal.value)
    prob = Decimal(_deal_probability(deal))
    return value * prob / Decimal("100")


def _month_key(dt: datetime | None) -> str:
    aware_dt = _aware(dt) or _utcnow()
    return aware_dt.strftime("%Y-%m")


def _win_rate(won: int, lost: int) -> float | None:
    total = won + lost
    if total == 0:
        return None
    return round(won / total * 100, 1)


class CrmPipelineDashboardService:
    @classmethod
    async def _load_deals(cls, db: AsyncSession, tenant_id: UUID) -> list[SalesDeal]:
        q = select(SalesDeal).where(SalesDeal.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_publishing_accounts(
        cls, db: AsyncSession, tenant_id: UUID,
    ) -> list[PublishingAccount]:
        accounts, _ = await PublishingAccountService.list_all(db, tenant_id)
        return accounts

    @classmethod
    def _is_open_deal(cls, deal: SalesDeal) -> bool:
        return deal.stage not in TERMINAL_STAGES

    @classmethod
    def _pipeline_value_for_deals(cls, deals: list[SalesDeal]) -> Decimal:
        return sum(
            (_decimal(d.value) for d in deals if cls._is_open_deal(d)),
            Decimal("0"),
        )

    @classmethod
    def _weighted_revenue_for_deals(cls, deals: list[SalesDeal]) -> Decimal:
        return sum(
            (_weighted_revenue(d) for d in deals if cls._is_open_deal(d)),
            Decimal("0"),
        )

    @classmethod
    def _average_deal_time_days(cls, deals: list[SalesDeal]) -> float | None:
        durations: list[float] = []
        for deal in deals:
            if deal.stage not in TERMINAL_STAGES:
                continue
            closed = _aware(deal.closed_at)
            created = _aware(deal.created_at)
            if closed and created:
                durations.append((closed - created).total_seconds() / 86400)
        if not durations:
            return None
        return round(sum(durations) / len(durations), 1)

    @classmethod
    def _stale_open_deals(cls, deals: list[SalesDeal], *, now: datetime) -> int:
        cutoff = now - timedelta(days=_STALE_DEAL_DAYS)
        count = 0
        for deal in deals:
            if not cls._is_open_deal(deal):
                continue
            updated = _aware(deal.updated_at) or _aware(deal.created_at)
            if updated and updated <= cutoff:
                count += 1
        return count

    @classmethod
    def _clients_at_stage(cls, deals: list[SalesDeal], stage: str) -> int:
        customer_ids = {
            d.customer_id for d in deals
            if d.stage == stage and d.customer_id is not None
        }
        return len(customer_ids)

    @classmethod
    async def _clients_connected_to_meta(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        accounts: list[PublishingAccount],
    ) -> int:
        meta_account_ids = {
            a.id for a in accounts
            if a.platform in _META_PLATFORMS and a.status in _META_USABLE_STATUSES
        }
        if not meta_account_ids:
            return 0
        q = (
            select(SalesCustomer.id)
            .where(
                SalesCustomer.tenant_id == tenant_id,
                SalesCustomer.primary_publishing_account_id.in_(tuple(meta_account_ids)),
            )
            .distinct()
        )
        return len(list((await db.execute(q)).scalars().all()))

    @classmethod
    def _publishing_health_summary(
        cls,
        accounts: list[PublishingAccount],
    ) -> CrmPipelinePublishingHealthSummary:
        by_platform: dict[str, int] = defaultdict(int)
        by_health: dict[str, int] = defaultdict(int)
        healthy = warning = disconnected = mock = meta_connected = 0

        for account in accounts:
            by_platform[account.platform] += 1
            serialized = PublishingAccountService._serialize(account)
            health = serialized.get("health") or account.status
            by_health[str(health)] += 1

            if account.status == "mock":
                mock += 1
            elif health == "healthy":
                healthy += 1
            elif health in ("expired", "missing_permissions", "unhealthy"):
                warning += 1
            elif health == "disconnected" or account.status == "disconnected":
                disconnected += 1

            if (
                account.platform in _META_PLATFORMS
                and account.status in _META_USABLE_STATUSES
                and not token_is_expired(account.expires_at)
                and account.status != "disconnected"
            ):
                meta_connected += 1

        return CrmPipelinePublishingHealthSummary(
            total_accounts=len(accounts),
            meta_connected_count=meta_connected,
            healthy_count=healthy,
            warning_count=warning,
            disconnected_count=disconnected,
            mock_count=mock,
            by_platform=dict(by_platform),
            by_health=dict(by_health),
        )

    @classmethod
    async def dashboard(cls, db: AsyncSession, tenant_id: UUID) -> CrmPipelineDashboardKpis:
        now = _utcnow()
        deals = await cls._load_deals(db, tenant_id)
        accounts = await cls._load_publishing_accounts(db, tenant_id)

        open_deals = [d for d in deals if cls._is_open_deal(d)]
        won = sum(1 for d in deals if d.stage == "closed_won")
        lost = sum(1 for d in deals if d.stage == "closed_lost")

        publishing_health = cls._publishing_health_summary(accounts)
        clients_meta = await cls._clients_connected_to_meta(db, tenant_id, accounts)

        return CrmPipelineDashboardKpis(
            pipeline_value=cls._pipeline_value_for_deals(deals),
            weighted_expected_revenue=cls._weighted_revenue_for_deals(deals),
            win_rate=_win_rate(won, lost),
            average_deal_time_days=cls._average_deal_time_days(deals),
            open_deals_count=len(open_deals),
            stale_deals_count=cls._stale_open_deals(deals, now=now),
            clients_active_count=cls._clients_at_stage(deals, "client_active"),
            clients_publishing_count=cls._clients_at_stage(deals, "publishing_active"),
            clients_connected_to_meta=clients_meta,
            deals_won_count=won,
            deals_lost_count=lost,
            publishing_health=publishing_health,
            generated_at=now,
        )

    @classmethod
    async def revenue_forecast(
        cls, db: AsyncSession, tenant_id: UUID,
    ) -> CrmPipelineRevenueForecastResponse:
        now = _utcnow()
        deals = await cls._load_deals(db, tenant_id)
        buckets: dict[tuple[str, str], dict[str, Decimal | int]] = defaultdict(
            lambda: {"deal_count": 0, "pipeline_value": Decimal("0"), "weighted_revenue": Decimal("0")},
        )

        for deal in deals:
            if not cls._is_open_deal(deal):
                continue
            month = _month_key(deal.expected_close_date or deal.created_at)
            key = (month, deal.stage)
            buckets[key]["deal_count"] = int(buckets[key]["deal_count"]) + 1
            buckets[key]["pipeline_value"] = _decimal(buckets[key]["pipeline_value"]) + _decimal(deal.value)
            buckets[key]["weighted_revenue"] = _decimal(buckets[key]["weighted_revenue"]) + _weighted_revenue(deal)

        rows = [
            CrmPipelineForecastRow(
                month=month,
                stage=stage,
                deal_count=int(vals["deal_count"]),
                pipeline_value=_decimal(vals["pipeline_value"]),
                weighted_revenue=_decimal(vals["weighted_revenue"]),
            )
            for (month, stage), vals in sorted(buckets.items())
        ]
        total_weighted = sum((r.weighted_revenue for r in rows), Decimal("0"))

        return CrmPipelineRevenueForecastResponse(
            rows=rows,
            total_weighted_revenue=total_weighted,
            generated_at=now,
        )

    @classmethod
    async def _owner_emails(
        cls, db: AsyncSession, tenant_id: UUID, owner_ids: set[UUID],
    ) -> dict[UUID, str]:
        if not owner_ids:
            return {}
        q = select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.id.in_(tuple(owner_ids)),
        )
        users = (await db.execute(q)).scalars().all()
        return {u.id: u.email for u in users}

    @classmethod
    def _manager_row_from_deals(
        cls,
        deals: list[SalesDeal],
        *,
        owner_id: UUID | None,
        owner_email: str | None,
        now: datetime,
    ) -> CrmPipelineManagerPerformanceRow:
        scoped = [d for d in deals if d.owner_id == owner_id]
        open_deals = [d for d in scoped if cls._is_open_deal(d)]
        won = sum(1 for d in scoped if d.stage == "closed_won")
        lost = sum(1 for d in scoped if d.stage == "closed_lost")

        return CrmPipelineManagerPerformanceRow(
            owner_id=owner_id,
            owner_email=owner_email,
            open_deals=len(open_deals),
            pipeline_value=cls._pipeline_value_for_deals(scoped),
            weighted_expected_revenue=cls._weighted_revenue_for_deals(scoped),
            deals_won=won,
            deals_lost=lost,
            win_rate=_win_rate(won, lost),
            stale_deals=cls._stale_open_deals(scoped, now=now),
        )

    @classmethod
    async def manager_performance(
        cls, db: AsyncSession, tenant_id: UUID,
    ) -> CrmPipelineManagerPerformanceResponse:
        now = _utcnow()
        deals = await cls._load_deals(db, tenant_id)
        owner_ids = {d.owner_id for d in deals if d.owner_id is not None}
        emails = await cls._owner_emails(db, tenant_id, owner_ids)

        managers = [
            cls._manager_row_from_deals(
                deals,
                owner_id=oid,
                owner_email=emails.get(oid),
                now=now,
            )
            for oid in sorted(owner_ids, key=str)
        ]
        managers.sort(key=lambda m: (-_decimal(m.pipeline_value), m.owner_email or ""))

        unassigned_deals = [d for d in deals if d.owner_id is None]
        unassigned = None
        if unassigned_deals:
            unassigned = cls._manager_row_from_deals(
                deals,
                owner_id=None,
                owner_email=None,
                now=now,
            )

        return CrmPipelineManagerPerformanceResponse(
            managers=managers,
            unassigned=unassigned,
            generated_at=now,
        )
