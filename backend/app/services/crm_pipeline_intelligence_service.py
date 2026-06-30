"""Executive AI Sales Assistant — deterministic rule engine (no LLM)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm_pipeline_event import CrmPipelineEvent
from app.models.publishing_account import PublishingAccount
from app.models.sales_crm import (
    DEFAULT_STAGE_PROBABILITY,
    SalesCustomer,
    SalesDeal,
    SalesLead,
    SalesProposal,
    TERMINAL_STAGES,
)
from app.models.tenant import TenantUser
from app.schemas.crm_pipeline import (
    RECOMMENDATION_CATEGORY_LABELS,
    CrmPipelineDashboardKpis,
    CrmPipelineIntelligenceRecommendation,
    CrmPipelineIntelligenceResponse,
    CrmPipelineManagerInsightRow,
    CrmPipelineManagerInsightsResponse,
    CrmPipelineMorningBrief,
    CrmPipelinePublishingHealthSummary,
    CrmPipelineRevenueForecastResponse,
    RecommendationCategory,
    RecommendationSeverity,
)
from app.services.crm_pipeline_dashboard_service import CrmPipelineDashboardService
from app.services.meta_graph_client import token_is_expired
from app.services.publishing_account_service import PublishingAccountService

_FOLLOW_UP_DAYS = 7
_STALE_DEAL_DAYS = 14
_PROPOSAL_EXPIRING_DAYS = 7
_PROPOSAL_WAITING_DAYS = 14
_INACTIVE_CUSTOMER_DAYS = 30
_HIGH_VALUE_THRESHOLD = Decimal("10000")
_MANAGER_OVERLOAD_DEALS = 8
_LIKELY_TO_CLOSE_PROB = 70
_LIKELY_TO_CLOSE_DAYS = 30
_LATE_STAGES = frozenset({
    "negotiation", "contract_pending", "client_active",
    "publishing_active", "expansion_upsell",
})
_EARLY_STAGES = frozenset({
    "lead", "qualified", "contacted", "meeting_scheduled",
})
_META_PLATFORMS = frozenset({"facebook", "instagram"})
_META_USABLE_STATUSES = frozenset({"connected", "mock"})
_RISK_CATEGORIES: frozenset[str] = frozenset({
    "deal_at_risk", "stale_deal", "proposal_expiring",
    "proposal_waiting_too_long", "inactive_customer", "manager_overload",
})
_OPPORTUNITY_CATEGORIES: frozenset[str] = frozenset({
    "likely_to_close", "high_value_lead", "upsell_opportunity",
    "publishing_opportunity", "meta_connection_opportunity",
})
_SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


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


def _is_open_deal(deal: SalesDeal) -> bool:
    return deal.stage not in TERMINAL_STAGES


def _days_since(dt: datetime | None, now: datetime) -> float | None:
    aware_dt = _aware(dt)
    if aware_dt is None:
        return None
    return (now - aware_dt).total_seconds() / 86400


def _priority_score(
    severity: RecommendationSeverity,
    confidence: int,
    value: Decimal | None = None,
) -> int:
    sev = _SEVERITY_RANK.get(severity, 3)
    val_bonus = min(int(_decimal(value) / Decimal("1000")), 50)
    return (4 - sev) * 1000 + confidence * 10 + val_bonus


def _dedup_key(rec: CrmPipelineIntelligenceRecommendation) -> tuple:
    return (
        rec.rule_id,
        rec.deal_id,
        rec.customer_id,
        rec.lead_id,
        rec.proposal_id,
        rec.owner_id,
    )


def _make_rec(
    *,
    rule_id: str,
    category: RecommendationCategory,
    severity: RecommendationSeverity,
    confidence: int,
    business_reason: str,
    recommended_action: str,
    now: datetime,
    deal: SalesDeal | None = None,
    customer: SalesCustomer | None = None,
    lead: SalesLead | None = None,
    proposal: SalesProposal | None = None,
    owner_email: str | None = None,
    deal_value: Decimal | None = None,
) -> CrmPipelineIntelligenceRecommendation:
    value = deal_value or (deal.value if deal else None)
    return CrmPipelineIntelligenceRecommendation(
        rule_id=rule_id,
        category=category,
        category_label=RECOMMENDATION_CATEGORY_LABELS[category],
        severity=severity,
        confidence=confidence,
        business_reason=business_reason,
        recommended_action=recommended_action,
        deal_id=deal.id if deal else None,
        deal_title=deal.title if deal else None,
        customer_id=customer.id if customer else (deal.customer_id if deal else None),
        customer_name=customer.name if customer else None,
        lead_id=lead.id if lead else (deal.lead_id if deal else None),
        lead_name=lead.name if lead else None,
        proposal_id=proposal.id if proposal else None,
        proposal_title=proposal.title if proposal else None,
        owner_id=deal.owner_id if deal else None,
        owner_email=owner_email,
        priority_score=_priority_score(severity, confidence, value),
        generated_at=now,
    )


class CrmPipelineIntelligenceService:
    @classmethod
    async def _load_deals(cls, db: AsyncSession, tenant_id: UUID) -> list[SalesDeal]:
        q = select(SalesDeal).where(SalesDeal.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_customers(cls, db: AsyncSession, tenant_id: UUID) -> list[SalesCustomer]:
        q = select(SalesCustomer).where(SalesCustomer.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_leads(cls, db: AsyncSession, tenant_id: UUID) -> list[SalesLead]:
        q = select(SalesLead).where(SalesLead.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_proposals(cls, db: AsyncSession, tenant_id: UUID) -> list[SalesProposal]:
        q = select(SalesProposal).where(SalesProposal.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _load_accounts(
        cls, db: AsyncSession, tenant_id: UUID,
    ) -> list[PublishingAccount]:
        accounts, _ = await PublishingAccountService.list_all(db, tenant_id)
        return accounts

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
    async def _last_event_by_deal(
        cls, db: AsyncSession, tenant_id: UUID, deal_ids: set[UUID],
    ) -> dict[UUID, datetime]:
        if not deal_ids:
            return {}
        q = (
            select(
                CrmPipelineEvent.deal_id,
                func.max(CrmPipelineEvent.created_at).label("last_at"),
            )
            .where(
                CrmPipelineEvent.tenant_id == tenant_id,
                CrmPipelineEvent.deal_id.in_(tuple(deal_ids)),
            )
            .group_by(CrmPipelineEvent.deal_id)
        )
        rows = (await db.execute(q)).all()
        return {row.deal_id: _aware(row.last_at) for row in rows if row.deal_id and row.last_at}

    @classmethod
    def _meta_connected_customers(
        cls,
        customers: list[SalesCustomer],
        accounts: list[PublishingAccount],
    ) -> set[UUID]:
        meta_ids = {
            a.id for a in accounts
            if a.platform in _META_PLATFORMS
            and a.status in _META_USABLE_STATUSES
            and not token_is_expired(a.expires_at)
            and a.status != "disconnected"
        }
        return {
            c.id for c in customers
            if c.primary_publishing_account_id in meta_ids
        }

    @classmethod
    def _deduplicate(
        cls, recs: list[CrmPipelineIntelligenceRecommendation],
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        seen: set[tuple] = set()
        unique: list[CrmPipelineIntelligenceRecommendation] = []
        for rec in sorted(recs, key=lambda r: -r.priority_score):
            key = _dedup_key(rec)
            if key in seen:
                continue
            seen.add(key)
            unique.append(rec)
        unique.sort(key=lambda r: (-r.priority_score, r.category))
        return unique

    @classmethod
    def _rule_follow_up_required(
        cls,
        deals: list[SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for deal in deals:
            if not _is_open_deal(deal):
                continue
            days = _days_since(deal.updated_at or deal.created_at, now)
            if days is None:
                continue
            if _FOLLOW_UP_DAYS <= days < _STALE_DEAL_DAYS:
                recs.append(_make_rec(
                    rule_id="R01_FOLLOW_UP_REQUIRED",
                    category="follow_up_required",
                    severity="medium",
                    confidence=min(90, 50 + int(days * 3)),
                    business_reason=(
                        f"Deal '{deal.title}' has had no activity for {int(days)} days "
                        f"(follow-up threshold: {_FOLLOW_UP_DAYS} days)."
                    ),
                    recommended_action="Schedule a follow-up call or send a status email today.",
                    now=now,
                    deal=deal,
                    owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
                ))
        return recs

    @classmethod
    def _rule_likely_to_close(
        cls,
        deals: list[SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for deal in deals:
            if not _is_open_deal(deal):
                continue
            prob = _deal_probability(deal)
            close_days = _days_since(deal.expected_close_date, now)
            in_late_stage = deal.stage in _LATE_STAGES
            high_prob = prob >= _LIKELY_TO_CLOSE_PROB
            close_soon = (
                deal.expected_close_date is not None
                and close_days is not None
                and 0 <= close_days <= _LIKELY_TO_CLOSE_DAYS
            )
            if not (high_prob or (in_late_stage and close_soon)):
                continue
            confidence = min(95, prob + (10 if close_soon else 0))
            recs.append(_make_rec(
                rule_id="R02_LIKELY_TO_CLOSE",
                category="likely_to_close",
                severity="medium",
                confidence=confidence,
                business_reason=(
                    f"Deal '{deal.title}' at {deal.stage.replace('_', ' ')} stage "
                    f"with {prob}% probability"
                    + (f", expected close in {int(close_days)} days." if close_soon and close_days is not None else ".")
                ),
                recommended_action="Prioritize closing activities — confirm terms and schedule contract signing.",
                now=now,
                deal=deal,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_deal_at_risk(
        cls,
        deals: list[SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for deal in deals:
            if not _is_open_deal(deal):
                continue
            days = _days_since(deal.updated_at or deal.created_at, now)
            if days is None:
                continue
            late_stale = deal.stage in _LATE_STAGES and days >= _STALE_DEAL_DAYS
            high_value_stale = (
                _decimal(deal.value) >= _HIGH_VALUE_THRESHOLD
                and days >= _FOLLOW_UP_DAYS
                and deal.stage in ("proposal_sent", "negotiation", "contract_pending")
            )
            if not (late_stale or high_value_stale):
                continue
            confidence = min(95, 60 + int(days))
            recs.append(_make_rec(
                rule_id="R03_DEAL_AT_RISK",
                category="deal_at_risk",
                severity="critical",
                confidence=confidence,
                business_reason=(
                    f"High-value or late-stage deal '{deal.title}' inactive for {int(days)} days "
                    f"at {deal.stage.replace('_', ' ')}."
                ),
                recommended_action="Escalate immediately — contact decision-maker and reassess deal viability.",
                now=now,
                deal=deal,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_proposal_expiring(
        cls,
        proposals: list[SalesProposal],
        deals_by_id: dict[UUID, SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for prop in proposals:
            if prop.status not in ("sent", "viewed"):
                continue
            valid = _aware(prop.valid_until)
            if valid is None:
                continue
            days_left = (valid - now).total_seconds() / 86400
            if days_left < 0 or days_left > _PROPOSAL_EXPIRING_DAYS:
                continue
            deal = deals_by_id.get(prop.deal_id) if prop.deal_id else None
            confidence = min(95, 70 + int((_PROPOSAL_EXPIRING_DAYS - days_left) * 4))
            recs.append(_make_rec(
                rule_id="R04_PROPOSAL_EXPIRING",
                category="proposal_expiring",
                severity="high",
                confidence=confidence,
                business_reason=(
                    f"Proposal '{prop.title}' ({prop.proposal_number}) expires in "
                    f"{max(0, int(days_left))} day(s)."
                ),
                recommended_action="Follow up with the client before the proposal validity window closes.",
                now=now,
                deal=deal,
                proposal=prop,
                owner_email=emails.get(deal.owner_id) if deal and deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_proposal_waiting(
        cls,
        proposals: list[SalesProposal],
        deals_by_id: dict[UUID, SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for prop in proposals:
            if prop.status not in ("sent", "viewed"):
                continue
            sent = _aware(prop.sent_at) or _aware(prop.updated_at)
            if sent is None:
                continue
            days = (now - sent).total_seconds() / 86400
            if days < _PROPOSAL_WAITING_DAYS:
                continue
            deal = deals_by_id.get(prop.deal_id) if prop.deal_id else None
            recs.append(_make_rec(
                rule_id="R05_PROPOSAL_WAITING_TOO_LONG",
                category="proposal_waiting_too_long",
                severity="medium",
                confidence=min(90, 50 + int(days)),
                business_reason=(
                    f"Proposal '{prop.title}' has been awaiting response for {int(days)} days."
                ),
                recommended_action="Send a reminder and offer to address questions or revise terms.",
                now=now,
                deal=deal,
                proposal=prop,
                owner_email=emails.get(deal.owner_id) if deal and deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_publishing_opportunity(
        cls,
        deals: list[SalesDeal],
        customers_by_id: dict[UUID, SalesCustomer],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for deal in deals:
            if deal.stage != "client_active":
                continue
            customer = customers_by_id.get(deal.customer_id) if deal.customer_id else None
            if customer and customer.primary_publishing_account_id:
                continue
            recs.append(_make_rec(
                rule_id="R06_PUBLISHING_OPPORTUNITY",
                category="publishing_opportunity",
                severity="low",
                confidence=75,
                business_reason=(
                    f"Active client deal '{deal.title}' has no publishing account linked."
                ),
                recommended_action="Connect a publishing account and advance to publishing_active stage.",
                now=now,
                deal=deal,
                customer=customer,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_meta_connection(
        cls,
        deals: list[SalesDeal],
        customers: list[SalesCustomer],
        customers_by_id: dict[UUID, SalesCustomer],
        meta_connected: set[UUID],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        target_stages = frozenset({"client_active", "publishing_active"})
        for deal in deals:
            if deal.stage not in target_stages:
                continue
            if not deal.customer_id or deal.customer_id in meta_connected:
                continue
            customer = customers_by_id.get(deal.customer_id)
            recs.append(_make_rec(
                rule_id="R07_META_CONNECTION_OPPORTUNITY",
                category="meta_connection_opportunity",
                severity="low",
                confidence=80,
                business_reason=(
                    f"Client for deal '{deal.title}' is not connected to Meta (Facebook/Instagram)."
                ),
                recommended_action="Initiate Meta OAuth connection for the client's publishing account.",
                now=now,
                deal=deal,
                customer=customer,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_upsell(
        cls,
        deals: list[SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for deal in deals:
            if deal.stage != "publishing_active":
                continue
            recs.append(_make_rec(
                rule_id="R08_UPSELL_OPPORTUNITY",
                category="upsell_opportunity",
                severity="low",
                confidence=70,
                business_reason=(
                    f"Client '{deal.title}' is publishing-active — ready for expansion or upsell."
                ),
                recommended_action="Review account performance and propose expansion package.",
                now=now,
                deal=deal,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_inactive_customer(
        cls,
        deals: list[SalesDeal],
        customers_by_id: dict[UUID, SalesCustomer],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        active_stages = frozenset({"client_active", "publishing_active"})
        for deal in deals:
            if deal.stage not in active_stages:
                continue
            days = _days_since(deal.updated_at or deal.created_at, now)
            if days is None or days < _INACTIVE_CUSTOMER_DAYS:
                continue
            customer = customers_by_id.get(deal.customer_id) if deal.customer_id else None
            recs.append(_make_rec(
                rule_id="R09_INACTIVE_CUSTOMER",
                category="inactive_customer",
                severity="medium",
                confidence=min(90, 55 + int(days / 2)),
                business_reason=(
                    f"Active client deal '{deal.title}' has had no activity for {int(days)} days."
                ),
                recommended_action="Schedule a check-in call to ensure client satisfaction and retention.",
                now=now,
                deal=deal,
                customer=customer,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_high_value_lead(
        cls,
        deals: list[SalesDeal],
        leads: list[SalesLead],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for deal in deals:
            if not _is_open_deal(deal):
                continue
            if deal.stage not in _EARLY_STAGES:
                continue
            if _decimal(deal.value) < _HIGH_VALUE_THRESHOLD:
                continue
            recs.append(_make_rec(
                rule_id="R10_HIGH_VALUE_LEAD",
                category="high_value_lead",
                severity="medium",
                confidence=85,
                business_reason=(
                    f"Early-stage deal '{deal.title}' valued at {_decimal(deal.value):,.0f} "
                    f"requires executive attention."
                ),
                recommended_action="Assign senior manager and accelerate qualification process.",
                now=now,
                deal=deal,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        for lead in leads:
            if lead.status in ("converted", "lost"):
                continue
            if lead.priority != "high":
                continue
            recs.append(_make_rec(
                rule_id="R10_HIGH_VALUE_LEAD",
                category="high_value_lead",
                severity="medium",
                confidence=75,
                business_reason=f"High-priority lead '{lead.name}' requires prompt engagement.",
                recommended_action="Contact the lead within 24 hours and qualify for pipeline entry.",
                now=now,
                lead=lead,
            ))
        return recs

    @classmethod
    def _rule_stale_deal(
        cls,
        deals: list[SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for deal in deals:
            if not _is_open_deal(deal):
                continue
            days = _days_since(deal.updated_at or deal.created_at, now)
            if days is None or days < _STALE_DEAL_DAYS:
                continue
            recs.append(_make_rec(
                rule_id="R11_STALE_DEAL",
                category="stale_deal",
                severity="high",
                confidence=min(95, 60 + int(days)),
                business_reason=(
                    f"Deal '{deal.title}' has been inactive for {int(days)} days "
                    f"(stale threshold: {_STALE_DEAL_DAYS} days)."
                ),
                recommended_action="Re-engage or close the deal — update stage or archive.",
                now=now,
                deal=deal,
                owner_email=emails.get(deal.owner_id) if deal.owner_id else None,
            ))
        return recs

    @classmethod
    def _rule_manager_overload(
        cls,
        deals: list[SalesDeal],
        emails: dict[UUID, str],
        now: datetime,
    ) -> list[CrmPipelineIntelligenceRecommendation]:
        by_owner: dict[UUID | None, list[SalesDeal]] = defaultdict(list)
        for deal in deals:
            if _is_open_deal(deal):
                by_owner[deal.owner_id].append(deal)

        if not by_owner:
            return []

        open_counts = {oid: len(ds) for oid, ds in by_owner.items() if oid is not None}
        if not open_counts:
            return []

        avg_count = sum(open_counts.values()) / len(open_counts)
        recs: list[CrmPipelineIntelligenceRecommendation] = []
        for owner_id, owner_deals in by_owner.items():
            if owner_id is None:
                continue
            count = len(owner_deals)
            if count < _MANAGER_OVERLOAD_DEALS and count <= avg_count * 1.5:
                continue
            pipeline = sum((_decimal(d.value) for d in owner_deals), Decimal("0"))
            confidence = min(95, 50 + count * 5)
            recs.append(_make_rec(
                rule_id="R12_MANAGER_OVERLOAD",
                category="manager_overload",
                severity="high",
                confidence=confidence,
                business_reason=(
                    f"Manager {emails.get(owner_id, str(owner_id))} has {count} open deals "
                    f"(pipeline {_decimal(pipeline):,.0f}), above workload threshold."
                ),
                recommended_action="Redistribute deals or add support resources to prevent bottlenecks.",
                now=now,
                owner_email=emails.get(owner_id),
                deal_value=pipeline,
            ))
        return recs

    @classmethod
    async def generate_recommendations(
        cls, db: AsyncSession, tenant_id: UUID,
    ) -> CrmPipelineIntelligenceResponse:
        now = _utcnow()
        deals = await cls._load_deals(db, tenant_id)
        customers = await cls._load_customers(db, tenant_id)
        leads = await cls._load_leads(db, tenant_id)
        proposals = await cls._load_proposals(db, tenant_id)
        accounts = await cls._load_accounts(db, tenant_id)

        owner_ids = {d.owner_id for d in deals if d.owner_id}
        emails = await cls._owner_emails(db, tenant_id, owner_ids)

        customers_by_id = {c.id: c for c in customers}
        deals_by_id = {d.id: d for d in deals}
        meta_connected = cls._meta_connected_customers(customers, accounts)

        all_recs: list[CrmPipelineIntelligenceRecommendation] = []
        all_recs.extend(cls._rule_follow_up_required(deals, emails, now))
        all_recs.extend(cls._rule_likely_to_close(deals, emails, now))
        all_recs.extend(cls._rule_deal_at_risk(deals, emails, now))
        all_recs.extend(cls._rule_proposal_expiring(proposals, deals_by_id, emails, now))
        all_recs.extend(cls._rule_proposal_waiting(proposals, deals_by_id, emails, now))
        all_recs.extend(cls._rule_publishing_opportunity(deals, customers_by_id, emails, now))
        all_recs.extend(cls._rule_meta_connection(
            deals, customers, customers_by_id, meta_connected, emails, now,
        ))
        all_recs.extend(cls._rule_upsell(deals, emails, now))
        all_recs.extend(cls._rule_inactive_customer(deals, customers_by_id, emails, now))
        all_recs.extend(cls._rule_high_value_lead(deals, leads, emails, now))
        all_recs.extend(cls._rule_stale_deal(deals, emails, now))
        all_recs.extend(cls._rule_manager_overload(deals, emails, now))

        unique = cls._deduplicate(all_recs)
        return CrmPipelineIntelligenceResponse(
            recommendations=unique,
            total=len(unique),
            generated_at=now,
        )

    @classmethod
    def _workload_score(cls, open_deals: int, stale: int, pipeline: Decimal) -> int:
        score = min(100, open_deals * 8 + stale * 12)
        if pipeline >= _HIGH_VALUE_THRESHOLD * 3:
            score = min(100, score + 15)
        return score

    @classmethod
    async def manager_insights(
        cls, db: AsyncSession, tenant_id: UUID,
    ) -> CrmPipelineManagerInsightsResponse:
        now = _utcnow()
        deals = await cls._load_deals(db, tenant_id)
        owner_ids = {d.owner_id for d in deals if d.owner_id}
        emails = await cls._owner_emails(db, tenant_id, owner_ids)

        open_deal_ids = {d.id for d in deals if _is_open_deal(d)}
        last_events = await cls._last_event_by_deal(db, tenant_id, open_deal_ids)

        def _insight_row(owner_id: UUID | None) -> CrmPipelineManagerInsightRow:
            scoped = [d for d in deals if d.owner_id == owner_id]
            open_deals = [d for d in scoped if _is_open_deal(d)]
            won = sum(1 for d in scoped if d.stage == "closed_won")
            lost = sum(1 for d in scoped if d.stage == "closed_lost")
            stale = CrmPipelineDashboardService._stale_open_deals(scoped, now=now)
            likely = sum(
                1 for d in open_deals
                if _deal_probability(d) >= _LIKELY_TO_CLOSE_PROB
                or d.stage in ("negotiation", "contract_pending")
            )
            pipeline = CrmPipelineDashboardService._pipeline_value_for_deals(scoped)
            weighted = CrmPipelineDashboardService._weighted_revenue_for_deals(scoped)

            touch_days: list[float] = []
            for d in open_deals:
                last = last_events.get(d.id) or _aware(d.updated_at) or _aware(d.created_at)
                if last:
                    touch_days.append((now - last).total_seconds() / 86400)
            avg_response = round(sum(touch_days) / len(touch_days), 1) if touch_days else None

            total_closed = won + lost
            win_rate = round(won / total_closed * 100, 1) if total_closed else None

            return CrmPipelineManagerInsightRow(
                owner_id=owner_id,
                owner_email=emails.get(owner_id) if owner_id else None,
                open_deals=len(open_deals),
                pipeline_value=pipeline,
                weighted_expected_revenue=weighted,
                stale_deals=stale,
                likely_wins=likely,
                workload_score=cls._workload_score(len(open_deals), stale, pipeline),
                avg_response_time_days=avg_response,
                deals_won=won,
                deals_lost=lost,
                win_rate=win_rate,
            )

        managers = [_insight_row(oid) for oid in sorted(owner_ids, key=str)]
        managers.sort(key=lambda m: (-m.workload_score, m.owner_email or ""))

        unassigned_deals = [d for d in deals if d.owner_id is None]
        unassigned = _insight_row(None) if unassigned_deals else None

        return CrmPipelineManagerInsightsResponse(
            managers=managers,
            unassigned=unassigned,
            generated_at=now,
        )

    @classmethod
    async def morning_brief(
        cls, db: AsyncSession, tenant_id: UUID,
    ) -> CrmPipelineMorningBrief:
        now = _utcnow()
        intel = await cls.generate_recommendations(db, tenant_id)
        recs = intel.recommendations

        priorities = [r for r in recs if r.severity in ("critical", "high")][:10]
        if len(priorities) < 5:
            extras = [r for r in recs if r not in priorities][:10 - len(priorities)]
            priorities.extend(extras)

        risks = [r for r in recs if r.category in _RISK_CATEGORIES][:10]
        opportunities = [r for r in recs if r.category in _OPPORTUNITY_CATEGORIES][:10]

        pipeline_health = await CrmPipelineDashboardService.dashboard(db, tenant_id)
        revenue_forecast = await CrmPipelineDashboardService.revenue_forecast(db, tenant_id)
        manager_workload = await cls.manager_insights(db, tenant_id)
        publishing_health = pipeline_health.publishing_health

        return CrmPipelineMorningBrief(
            todays_priorities=priorities,
            top_risks=risks,
            top_opportunities=opportunities,
            revenue_forecast=revenue_forecast,
            pipeline_health=pipeline_health,
            manager_workload=manager_workload,
            publishing_health=publishing_health,
            meta_health=publishing_health,
            all_recommendations=recs,
            generated_at=now,
        )
