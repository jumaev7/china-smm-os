"""Business Matching Center — dashboard, opportunities, buyers, suppliers, AI recommendations."""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.business_matching import (
    OPPORTUNITY_STATUSES,
    OPPORTUNITY_TYPES,
    BusinessMatchingOpportunity,
)
from app.models.buyer_crm import Buyer
from app.models.communication import CommunicationMessage, CommunicationThread
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.factory_profile import FactoryCatalogProduct, FactoryCertificate, FactoryExportMarket
from app.models.sales_crm import SalesDeal, SalesProposal
from app.schemas.business_matching import (
    BusinessMatchingBuyerItem,
    BusinessMatchingBuyerListResponse,
    BusinessMatchingDashboardResponse,
    BusinessMatchingKpis,
    BusinessMatchingOpportunityCreate,
    BusinessMatchingOpportunityItem,
    BusinessMatchingOpportunityListResponse,
    BusinessMatchingOpportunityUpdate,
    BusinessMatchingRecommendation,
    BusinessMatchingSupplierItem,
    BusinessMatchingSupplierListResponse,
)
from app.schemas.buyer_crm import DistributionItem
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.market_intelligence_service import MarketIntelligenceService
from app.services.matching_engine_service import BuyerMatchInput, MatchingContext, MatchingEngineService

logger = logging.getLogger(__name__)
MARKER = "[Business Matching]"

ACTIVE_STATUSES = frozenset({"new", "contacted", "qualified", "negotiation"})
HIGH_VALUE_THRESHOLD = Decimal("50000")

_AI_RECOMMEND_SYSTEM = (
    "You are a B2B trade matching advisor for Chinese manufacturers and Central Asian buyers. "
    "Return JSON: {\"recommendations\": [{\"category\": \"high_value|opportunity_risk|buyer_contact|"
    "supplier_contact|new_market\", \"priority\": \"urgent|high|medium|low\", \"title\": \"...\", "
    "\"reason\": \"...\", \"recommended_action\": \"...\"}]}. Max 6 items."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _as_str_list(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x]
    return [str(val)]


class BusinessMatchingService:

    @classmethod
    async def _load_supplier_context(cls, db: AsyncSession, tenant_id: UUID) -> MatchingContext:
        profile_r = await db.execute(
            select(FactoryPlatformProfile).where(FactoryPlatformProfile.tenant_id == tenant_id),
        )
        profile = profile_r.scalar_one_or_none()
        products_r = await db.execute(
            select(FactoryCatalogProduct).where(FactoryCatalogProduct.tenant_id == tenant_id),
        )
        products = list(products_r.scalars().all())
        markets_r = await db.execute(
            select(FactoryExportMarket).where(FactoryExportMarket.tenant_id == tenant_id),
        )
        markets = list(markets_r.scalars().all())
        certs_r = await db.execute(
            select(FactoryCertificate).where(FactoryCertificate.tenant_id == tenant_id),
        )
        certs = list(certs_r.scalars().all())

        industries = _as_str_list(profile.industries if profile else None)
        if profile and profile.industry and profile.industry not in industries:
            industries.append(profile.industry)
        product_cats = _as_str_list(profile.product_categories if profile else None)
        for p in products:
            if p.category and p.category not in product_cats:
                product_cats.append(p.category)
            if p.product_name:
                product_cats.append(p.product_name)
        export_markets = _as_str_list(profile.export_regions if profile else None)
        for m in markets:
            if m.country and m.country not in export_markets:
                export_markets.append(m.country)
        if profile and profile.markets:
            export_markets.extend(_as_str_list(profile.markets))

        return MatchingContext(
            industries=industries,
            product_categories=product_cats,
            export_markets=export_markets,
            certifications=[c.certificate_name for c in certs],
        )

    @classmethod
    async def _buyer_history_counts(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        buyer: Buyer,
    ) -> tuple[int, int, int, int]:
        deal_count = 0
        won_count = 0
        proposal_count = 0
        comm_count = 0

        deals_r = await db.execute(
            select(SalesDeal).where(SalesDeal.tenant_id == tenant_id),
        )
        for deal in deals_r.scalars().all():
            deal_count += 1
            if deal.stage == "closed_won":
                won_count += 1

        prop_r = await db.execute(
            select(func.count()).select_from(SalesProposal).where(
                SalesProposal.tenant_id == tenant_id,
            ),
        )
        proposal_count = int(prop_r.scalar() or 0)

        thread_r = await db.execute(
            select(CommunicationThread).where(
                CommunicationThread.tenant_id == tenant_id,
                CommunicationThread.buyer_id == buyer.id,
            ),
        )
        thread_ids = [t.id for t in thread_r.scalars().all()]
        if thread_ids:
            msg_r = await db.execute(
                select(func.count()).select_from(CommunicationMessage).where(
                    CommunicationMessage.thread_id.in_(thread_ids),
                ),
            )
            comm_count = int(msg_r.scalar() or 0)

        return deal_count, won_count, proposal_count, comm_count

    @classmethod
    async def _score_buyer(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        buyer: Buyer,
        supplier_ctx: MatchingContext,
    ) -> tuple[int, int, str, list[str]]:
        deal_count, won_count, proposal_count, comm_count = await cls._buyer_history_counts(
            db, tenant_id, buyer,
        )
        categories = _as_str_list(buyer.product_categories)
        interest = ", ".join(categories) if categories else (buyer.notes or "")

        result = MatchingEngineService.compute_match(
            BuyerMatchInput(
                industry=buyer.industry,
                country=buyer.country,
                product_interest=interest[:500] if interest else None,
                product_categories=categories,
                deal_count=deal_count,
                won_deal_count=won_count,
                proposal_count=proposal_count,
                communication_count=comm_count,
            ),
            supplier_ctx,
        )

        actions: list[str] = []
        if result.match_score >= 70:
            actions.append("Schedule introductory call with buyer")
        elif result.match_score >= 50:
            actions.append("Send product catalog and certification overview")
        else:
            actions.append("Research buyer requirements before outreach")
        if comm_count == 0:
            actions.append("Initiate first communication via Communication Hub")
        if buyer.status == "prospect":
            actions.append("Qualify buyer purchasing timeline and volume")

        return result.match_score, result.confidence_score, result.reasoning, actions

    @classmethod
    async def _similar_buyers(
        cls,
        buyers: list[Buyer],
        target: Buyer,
        limit: int = 3,
    ) -> list[str]:
        scored: list[tuple[int, str]] = []
        for b in buyers:
            if b.id == target.id:
                continue
            score = 0
            if target.industry and b.industry and target.industry.lower() == b.industry.lower():
                score += 3
            if target.country and b.country and target.country.lower() == b.country.lower():
                score += 2
            if score > 0:
                scored.append((score, b.company_name))
        scored.sort(key=lambda x: -x[0])
        return [name for _, name in scored[:limit]]

    @classmethod
    def _opportunity_to_item(
        cls,
        opp: BusinessMatchingOpportunity,
        *,
        buyer_company: str | None = None,
        supplier_company: str | None = None,
        country: str | None = None,
        industry: str | None = None,
    ) -> BusinessMatchingOpportunityItem:
        return BusinessMatchingOpportunityItem(
            id=opp.id,
            title=opp.title,
            opportunity_type=opp.opportunity_type,
            buyer_id=opp.buyer_id,
            buyer_company=buyer_company,
            supplier_tenant_id=opp.supplier_tenant_id,
            supplier_company=supplier_company,
            score=opp.score,
            confidence_score=opp.confidence_score,
            estimated_value=opp.estimated_value,
            status=opp.status,
            notes=opp.notes,
            match_reasoning=opp.match_reasoning,
            country=country,
            industry=industry,
            created_at=opp.created_at,
            updated_at=opp.updated_at,
        )

    @classmethod
    async def _load_opportunities(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
    ) -> list[BusinessMatchingOpportunity]:
        q = select(BusinessMatchingOpportunity).order_by(
            BusinessMatchingOpportunity.score.desc(),
            BusinessMatchingOpportunity.created_at.desc(),
        )
        if tenant_id is not None:
            q = q.where(BusinessMatchingOpportunity.tenant_id == tenant_id)
        return list((await db.execute(q)).scalars().all())

    @classmethod
    async def _enrich_opportunity(
        cls,
        db: AsyncSession,
        opp: BusinessMatchingOpportunity,
    ) -> BusinessMatchingOpportunityItem:
        buyer_company = None
        country = None
        industry = None
        if opp.buyer_id:
            buyer_r = await db.execute(select(Buyer).where(Buyer.id == opp.buyer_id))
            buyer = buyer_r.scalar_one_or_none()
            if buyer:
                buyer_company = buyer.company_name
                country = buyer.country
                industry = buyer.industry
        supplier_company = None
        if opp.supplier_tenant_id:
            prof_r = await db.execute(
                select(FactoryPlatformProfile).where(
                    FactoryPlatformProfile.tenant_id == opp.supplier_tenant_id,
                ),
            )
            prof = prof_r.scalar_one_or_none()
            if prof:
                supplier_company = prof.company_name
        return cls._opportunity_to_item(
            opp,
            buyer_company=buyer_company,
            supplier_company=supplier_company,
            country=country,
            industry=industry,
        )

    @classmethod
    async def _build_kpis(
        cls,
        opportunities: list[BusinessMatchingOpportunity],
    ) -> BusinessMatchingKpis:
        active = [o for o in opportunities if o.status in ACTIVE_STATUSES]
        high_value = [
            o for o in opportunities
            if o.estimated_value and _decimal(o.estimated_value) >= HIGH_VALUE_THRESHOLD
        ]
        pipeline = sum((_decimal(o.estimated_value) for o in active), Decimal("0"))
        avg_score = (
            int(round(sum(o.score for o in opportunities) / len(opportunities)))
            if opportunities else 0
        )
        return BusinessMatchingKpis(
            total_opportunities=len(opportunities),
            high_value_opportunities=len(high_value),
            active_matches=len(active),
            estimated_pipeline_value=pipeline,
            average_match_score=avg_score,
        )

    @classmethod
    async def _generate_ai_recommendations(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        opportunities: list[BusinessMatchingOpportunityItem],
        buyers: list[BusinessMatchingBuyerItem],
        suppliers: list[BusinessMatchingSupplierItem],
    ) -> list[BusinessMatchingRecommendation]:
        recs: list[BusinessMatchingRecommendation] = []

        for opp in opportunities[:3]:
            if opp.score >= 70 and opp.status in ACTIVE_STATUSES:
                recs.append(BusinessMatchingRecommendation(
                    id=f"hv-{opp.id}",
                    category="high_value",
                    priority="high",
                    title=f"High-value opportunity: {opp.title}",
                    reason=f"Match score {opp.score} with estimated value {opp.estimated_value or 'TBD'}",
                    recommended_action="Prioritize outreach and prepare tailored proposal",
                    entity_id=str(opp.id),
                    entity_type="opportunity",
                ))

        for opp in opportunities:
            if opp.status in ("negotiation", "qualified") and opp.score < 50:
                recs.append(BusinessMatchingRecommendation(
                    id=f"risk-{opp.id}",
                    category="opportunity_risk",
                    priority="urgent",
                    title=f"At-risk opportunity: {opp.title}",
                    reason="Low match score during active negotiation stage",
                    recommended_action="Reassess fit and update opportunity status",
                    entity_id=str(opp.id),
                    entity_type="opportunity",
                ))
                break

        for buyer in buyers[:2]:
            recs.append(BusinessMatchingRecommendation(
                id=f"buyer-{buyer.id}",
                category="buyer_contact",
                priority="medium" if buyer.match_score < 70 else "high",
                title=f"Contact buyer: {buyer.company_name}",
                reason=buyer.recommended_actions[0] if buyer.recommended_actions else "Strong match profile",
                recommended_action="Open buyer profile and schedule follow-up",
                entity_id=str(buyer.id),
                entity_type="buyer",
            ))

        for supplier in suppliers[:2]:
            recs.append(BusinessMatchingRecommendation(
                id=f"supplier-{supplier.tenant_id}",
                category="supplier_contact",
                priority="medium",
                title=f"Explore supplier: {supplier.company_name}",
                reason=supplier.match_reasoning or f"Match score {supplier.match_score}",
                recommended_action="Review supplier catalog and certifications",
                entity_id=str(supplier.tenant_id),
                entity_type="supplier",
            ))

        recs.append(BusinessMatchingRecommendation(
            id="market-uz",
            category="new_market",
            priority="medium",
            title="Expand into Uzbekistan retail distribution",
            reason="Central Asia retail segment shows growing import demand",
            recommended_action="Run market intelligence report for Uzbekistan retail",
        ))

        try:
            if not settings.DEMO_MODE and (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                _validate_api_key()
                context = json.dumps({
                    "opportunities": [o.model_dump(mode="json") for o in opportunities[:5]],
                    "buyers": [b.model_dump(mode="json") for b in buyers[:5]],
                }, ensure_ascii=False, default=str)
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _AI_RECOMMEND_SYSTEM},
                        {"role": "user", "content": f"Platform data:\n{context}"},
                    ],
                    temperature=0.3,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                for i, r in enumerate((parsed.get("recommendations") or [])[:3]):
                    recs.append(BusinessMatchingRecommendation(
                        id=f"ai-{i}-{uuid4().hex[:8]}",
                        category=r.get("category", "general"),
                        priority=r.get("priority", "medium"),
                        title=r.get("title", "AI recommendation"),
                        reason=r.get("reason", ""),
                        recommended_action=r.get("recommended_action", "Review details"),
                    ))
        except Exception as exc:
            logger.info("%s AI recommendations fallback: %s", MARKER, exc)

        return recs[:8]

    @classmethod
    async def dashboard(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
    ) -> BusinessMatchingDashboardResponse:
        if tenant_id is None:
            supplier_ctx = MatchingContext()
        else:
            supplier_ctx = await cls._load_supplier_context(db, tenant_id)

        buyers_r = await db.execute(select(Buyer).order_by(Buyer.company_name))
        if tenant_id is not None:
            buyers_r = await db.execute(
                select(Buyer).where(Buyer.tenant_id == tenant_id).order_by(Buyer.company_name),
            )
        buyers_raw = list(buyers_r.scalars().all())

        buyer_items: list[BusinessMatchingBuyerItem] = []
        for buyer in buyers_raw:
            if tenant_id:
                score, conf, reasoning, actions = await cls._score_buyer(
                    db, tenant_id, buyer, supplier_ctx,
                )
            else:
                score, conf, reasoning, actions = 50, 50, "Admin aggregate view", ["Review buyer profile"]
            buyer_items.append(BusinessMatchingBuyerItem(
                id=buyer.id,
                company_name=buyer.company_name,
                country=buyer.country,
                industry=buyer.industry,
                status=buyer.status,
                match_score=score,
                confidence_score=conf,
                recommended_actions=actions,
                similar_buyers=await cls._similar_buyers(buyers_raw, buyer),
                product_categories=_as_str_list(buyer.product_categories),
            ))
        buyer_items.sort(key=lambda b: -b.match_score)

        supplier_items = await cls._list_suppliers_internal(db, tenant_id, supplier_ctx, buyers_raw)

        opportunities_raw = await cls._load_opportunities(db, tenant_id)
        opportunities = [await cls._enrich_opportunity(db, o) for o in opportunities_raw]

        industry_counter: Counter[str] = Counter()
        country_counter: Counter[str] = Counter()
        for b in buyers_raw:
            if b.industry:
                industry_counter[b.industry] += 1
            if b.country:
                country_counter[b.country] += 1
        for o in opportunities:
            if o.industry:
                industry_counter[o.industry] += 1
            if o.country:
                country_counter[o.country] += 1

        kpis = await cls._build_kpis(opportunities_raw)
        trends = await MarketIntelligenceService.get_industry_trends(db, tenant_id)
        recommendations = await cls._generate_ai_recommendations(
            db, tenant_id, opportunities, buyer_items, supplier_items,
        )

        return BusinessMatchingDashboardResponse(
            kpis=kpis,
            top_industries=_top_items(industry_counter),
            top_countries=_top_items(country_counter),
            matching_opportunities=opportunities[:10],
            recommended_buyers=buyer_items[:8],
            recommended_suppliers=supplier_items[:8],
            new_opportunities=[o for o in opportunities if o.status == "new"][:6],
            industry_trends=trends,
            recommendations=recommendations,
        )

    @classmethod
    async def _list_suppliers_internal(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        supplier_ctx: MatchingContext,
        buyers: list[Buyer],
        *,
        min_score: int = 0,
        limit: int = 50,
    ) -> list[BusinessMatchingSupplierItem]:
        q = select(FactoryPlatformProfile).order_by(FactoryPlatformProfile.company_name)
        if tenant_id is not None:
            q = q.where(FactoryPlatformProfile.tenant_id != tenant_id)
        profiles = list((await db.execute(q.limit(limit))).scalars().all())

        representative_buyer = buyers[0] if buyers else None
        buyer_input = BuyerMatchInput(
            industry=representative_buyer.industry if representative_buyer else None,
            country=representative_buyer.country if representative_buyer else "Uzbekistan",
            product_categories=_as_str_list(representative_buyer.product_categories) if representative_buyer else [],
        )

        items: list[BusinessMatchingSupplierItem] = []
        for prof in profiles:
            certs_r = await db.execute(
                select(FactoryCertificate.certificate_name).where(
                    FactoryCertificate.tenant_id == prof.tenant_id,
                ).limit(10),
            )
            certs = [row[0] for row in certs_r.all()]

            ctx = MatchingContext(
                industries=_as_str_list(prof.industries) + ([prof.industry] if prof.industry else []),
                product_categories=_as_str_list(prof.product_categories),
                export_markets=_as_str_list(prof.export_regions),
                certifications=certs,
            )
            result = MatchingEngineService.compute_match(buyer_input, ctx)
            if result.match_score < min_score:
                continue
            items.append(BusinessMatchingSupplierItem(
                tenant_id=prof.tenant_id,
                company_name=prof.company_name,
                industry=prof.industry,
                country=prof.country,
                product_categories=_as_str_list(prof.product_categories),
                certifications=certs,
                contact_email=prof.contact_email,
                contact_phone=prof.contact_phone,
                match_score=result.match_score,
                confidence_score=result.confidence_score,
                match_reasoning=result.reasoning,
            ))
        items.sort(key=lambda s: -s.match_score)
        return items

    @classmethod
    async def list_opportunities(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        country: str | None = None,
        industry: str | None = None,
        product_category: str | None = None,
        min_score: int | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> BusinessMatchingOpportunityListResponse:
        opportunities_raw = await cls._load_opportunities(db, tenant_id)
        items: list[BusinessMatchingOpportunityItem] = []
        for opp in opportunities_raw:
            item = await cls._enrich_opportunity(db, opp)
            if country and (item.country or "").lower() != country.lower():
                continue
            if industry and (item.industry or "").lower() != industry.lower():
                continue
            if min_score is not None and item.score < min_score:
                continue
            if status and item.status != status:
                continue
            if product_category:
                notes_match = product_category.lower() in (item.notes or "").lower()
                title_match = product_category.lower() in item.title.lower()
                if not notes_match and not title_match:
                    continue
            items.append(item)
        total = len(items)
        return BusinessMatchingOpportunityListResponse(
            items=items[skip: skip + limit],
            total=total,
        )

    @classmethod
    async def list_buyers(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        min_score: int = 0,
        skip: int = 0,
        limit: int = 50,
    ) -> BusinessMatchingBuyerListResponse:
        if tenant_id is None:
            supplier_ctx = MatchingContext()
        else:
            supplier_ctx = await cls._load_supplier_context(db, tenant_id)

        q = select(Buyer).order_by(Buyer.company_name)
        if tenant_id is not None:
            q = q.where(Buyer.tenant_id == tenant_id)
        buyers_raw = list((await db.execute(q)).scalars().all())

        items: list[BusinessMatchingBuyerItem] = []
        for buyer in buyers_raw:
            if tenant_id:
                score, conf, _, actions = await cls._score_buyer(db, tenant_id, buyer, supplier_ctx)
            else:
                score, conf, actions = 50, 50, ["Review buyer profile"]
            if score < min_score:
                continue
            items.append(BusinessMatchingBuyerItem(
                id=buyer.id,
                company_name=buyer.company_name,
                country=buyer.country,
                industry=buyer.industry,
                status=buyer.status,
                match_score=score,
                confidence_score=conf,
                recommended_actions=actions,
                similar_buyers=await cls._similar_buyers(buyers_raw, buyer),
                product_categories=_as_str_list(buyer.product_categories),
            ))
        items.sort(key=lambda b: -b.match_score)
        total = len(items)
        return BusinessMatchingBuyerListResponse(items=items[skip: skip + limit], total=total)

    @classmethod
    async def list_suppliers(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        min_score: int = 0,
        skip: int = 0,
        limit: int = 50,
    ) -> BusinessMatchingSupplierListResponse:
        if tenant_id is None:
            supplier_ctx = MatchingContext()
        else:
            supplier_ctx = await cls._load_supplier_context(db, tenant_id)

        buyers_q = select(Buyer)
        if tenant_id is not None:
            buyers_q = buyers_q.where(Buyer.tenant_id == tenant_id)
        buyers_raw = list((await db.execute(buyers_q)).scalars().all())

        items = await cls._list_suppliers_internal(
            db, tenant_id, supplier_ctx, buyers_raw, min_score=min_score, limit=limit + skip,
        )
        total = len(items)
        return BusinessMatchingSupplierListResponse(items=items[skip: skip + limit], total=total)

    @classmethod
    async def create_opportunity(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        data: BusinessMatchingOpportunityCreate,
    ) -> BusinessMatchingOpportunityItem:
        if data.opportunity_type not in OPPORTUNITY_TYPES:
            raise ValueError(f"Invalid opportunity type: {data.opportunity_type}")
        if data.status not in OPPORTUNITY_STATUSES:
            raise ValueError(f"Invalid status: {data.status}")

        opp = BusinessMatchingOpportunity(
            tenant_id=tenant_id,
            title=data.title,
            opportunity_type=data.opportunity_type,
            buyer_id=data.buyer_id,
            supplier_tenant_id=data.supplier_tenant_id,
            score=data.score,
            confidence_score=data.confidence_score,
            estimated_value=data.estimated_value,
            status=data.status,
            notes=data.notes,
            match_reasoning=data.match_reasoning,
        )
        db.add(opp)
        await db.commit()
        await db.refresh(opp)
        return await cls._enrich_opportunity(db, opp)

    @classmethod
    async def update_opportunity(
        cls,
        db: AsyncSession,
        tenant_id: UUID | None,
        opportunity_id: UUID,
        data: BusinessMatchingOpportunityUpdate,
    ) -> BusinessMatchingOpportunityItem:
        q = select(BusinessMatchingOpportunity).where(
            BusinessMatchingOpportunity.id == opportunity_id,
        )
        if tenant_id is not None:
            q = q.where(BusinessMatchingOpportunity.tenant_id == tenant_id)
        opp = (await db.execute(q)).scalar_one_or_none()
        if not opp:
            raise ValueError("Opportunity not found")

        for field, value in data.model_dump(exclude_unset=True).items():
            if field == "opportunity_type" and value not in OPPORTUNITY_TYPES:
                raise ValueError(f"Invalid opportunity type: {value}")
            if field == "status" and value not in OPPORTUNITY_STATUSES:
                raise ValueError(f"Invalid status: {value}")
            setattr(opp, field, value)
        await db.commit()
        await db.refresh(opp)
        return await cls._enrich_opportunity(db, opp)


def _top_items(counter: Counter[str], limit: int = 8) -> list[DistributionItem]:
    return [
        DistributionItem(label=k, count=v)
        for k, v in counter.most_common(limit)
    ]
