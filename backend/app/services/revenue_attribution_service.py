"""Revenue Attribution Automation v1 — read-only analytics across CRM, deals, proposals, channels."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.models.attribution_link import AttributionLink
from app.models.communication import CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.proposal_document import ProposalDocument

logger = logging.getLogger(__name__)

MARKER = "[Revenue Attribution]"

REVENUE_SOURCES: dict[str, str] = {
    "wechat": "WeChat",
    "whatsapp": "WhatsApp",
    "website": "Website",
    "referral": "Referral",
    "manual": "Manual",
    "unknown": "Unknown",
}

CHANNEL_LABELS: dict[str, str] = {
    "wechat": "WeChat",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "website": "Website",
    "referral": "Referral",
    "manual": "Manual",
    "email": "Email",
    "phone": "Phone",
    "unknown": "Unknown",
}

_SOURCE_ALIASES: dict[str, str] = {
    "wechat": "wechat",
    "whatsapp": "whatsapp",
    "website": "website",
    "web": "website",
    "landing": "website",
    "landing_page": "website",
    "referral": "referral",
    "partner": "referral",
    "manual": "manual",
    "instagram": "unknown",
    "facebook": "unknown",
    "telegram": "unknown",
    "other": "unknown",
}

_cache: dict[str, Any] | None = None
_cache_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 2)


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_revenue_source(raw: str | None, *, partner_id: UUID | None = None) -> str:
    key = str(raw or "").lower().strip()
    if partner_id and key not in ("referral",):
        return "referral"
    if key in _SOURCE_ALIASES:
        return _SOURCE_ALIASES[key]
    if key in REVENUE_SOURCES:
        return key
    return "unknown"


def resolve_revenue_source(lead: CrmLead) -> tuple[str, str]:
    raw = lead.attribution_source or lead.source
    key = normalize_revenue_source(raw, partner_id=lead.partner_id)
    return key, REVENUE_SOURCES.get(key, "Unknown")


def resolve_channel(
    lead: CrmLead,
    *,
    link_channel: str | None = None,
    comm_channel: str | None = None,
) -> tuple[str, str]:
    if link_channel:
        key = str(link_channel).lower().strip()
    elif comm_channel:
        key = str(comm_channel).lower().strip()
    else:
        raw = lead.attribution_source or lead.source or "unknown"
        key = normalize_revenue_source(raw, partner_id=lead.partner_id)
        if key == "unknown" and raw:
            key = str(raw).lower().strip()
    if key not in CHANNEL_LABELS:
        key = "unknown"
    return key, CHANNEL_LABELS.get(key, key.title())


class RevenueAttributionService:
    @staticmethod
    async def _load_snapshot(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        link_map: dict[UUID, AttributionLink] = {}
        link_rows = await db.execute(select(AttributionLink))
        for link in link_rows.scalars().all():
            link_map[link.id] = link

        lead_q = select(CrmLead)
        if client_id:
            lead_q = lead_q.where(CrmLead.client_id == client_id)
        lead_rows = await db.execute(lead_q)
        leads = list(lead_rows.scalars().all())
        lead_by_id = {l.id: l for l in leads}

        comm_channels: dict[UUID, str] = {}
        if leads:
            thread_q = (
                select(CommunicationThread.lead_id, CommunicationThread.channel)
                .where(
                    CommunicationThread.lead_id.in_([l.id for l in leads]),
                    CommunicationThread.lead_id.isnot(None),
                )
                .order_by(CommunicationThread.last_message_at.desc().nullslast())
            )
            for lead_id, channel in (await db.execute(thread_q)).all():
                if lead_id and lead_id not in comm_channels and channel:
                    comm_channels[lead_id] = channel

        deal_q = (
            select(CrmDeal)
            .options(selectinload(CrmDeal.lead))
            .where(CrmDeal.status == "won")
        )
        if client_id:
            deal_q = deal_q.where(CrmDeal.client_id == client_id)
        won_deals = list((await db.execute(deal_q)).scalars().all())

        total_leads = len(leads)
        leads_by_source: dict[str, int] = {k: 0 for k in REVENUE_SOURCES}
        leads_by_channel: dict[str, int] = {k: 0 for k in CHANNEL_LABELS}

        for lead in leads:
            src_key, _ = resolve_revenue_source(lead)
            leads_by_source[src_key] = leads_by_source.get(src_key, 0) + 1
            link = link_map.get(lead.attribution_link_id) if lead.attribution_link_id else None
            ch_key, _ = resolve_channel(
                lead,
                link_channel=link.channel if link else None,
                comm_channel=comm_channels.get(lead.id),
            )
            leads_by_channel[ch_key] = leads_by_channel.get(ch_key, 0) + 1

        source_stats: dict[str, dict[str, Any]] = {
            k: {"source": k, "label": v, "revenue": Decimal("0"), "deals": 0, "leads": leads_by_source.get(k, 0)}
            for k, v in REVENUE_SOURCES.items()
        }
        channel_stats: dict[str, dict[str, Any]] = {
            k: {"channel": k, "label": v, "revenue": Decimal("0"), "deals": 0, "leads": leads_by_channel.get(k, 0)}
            for k, v in CHANNEL_LABELS.items()
        }

        total_revenue = Decimal("0")
        for deal in won_deals:
            lead = deal.lead or lead_by_id.get(deal.lead_id)
            if not lead:
                continue
            amount = Decimal(str(deal.deal_amount or 0))
            total_revenue += amount
            src_key, src_label = resolve_revenue_source(lead)
            bucket = source_stats.setdefault(src_key, {
                "source": src_key, "label": src_label, "revenue": Decimal("0"), "deals": 0, "leads": 0,
            })
            bucket["revenue"] += amount
            bucket["deals"] += 1

            link = link_map.get(lead.attribution_link_id) if lead.attribution_link_id else None
            ch_key, ch_label = resolve_channel(
                lead,
                link_channel=link.channel if link else None,
                comm_channel=comm_channels.get(lead.id),
            )
            ch_bucket = channel_stats.setdefault(ch_key, {
                "channel": ch_key, "label": ch_label, "revenue": Decimal("0"), "deals": 0, "leads": 0,
            })
            ch_bucket["revenue"] += amount
            ch_bucket["deals"] += 1

        def _finalize_rows(rows: dict[str, dict[str, Any]], *, key_field: str) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for row in rows.values():
                deals = int(row["deals"])
                leads_count = int(row.get("leads") or 0)
                revenue = _quantize(Decimal(str(row["revenue"])))
                avg = _quantize(revenue / deals) if deals else Decimal("0")
                out.append({
                    key_field: row[key_field],
                    "label": row["label"],
                    "revenue": revenue,
                    "deals": deals,
                    "conversion_rate": _rate(deals, leads_count),
                    "avg_deal_size": avg,
                })
            out.sort(key=lambda x: x["revenue"], reverse=True)
            return out

        sources = _finalize_rows(source_stats, key_field="source")
        channels = _finalize_rows(channel_stats, key_field="channel")

        deals_won = len(won_deals)
        avg_deal_size = _quantize(total_revenue / deals_won) if deals_won else Decimal("0")
        conversion_rate = _rate(deals_won, total_leads)

        prop_q = select(func.count()).select_from(ProposalDocument).where(
            ProposalDocument.status.in_(("sent", "accepted", "rejected")),
        )
        won_prop_q = select(func.count()).select_from(CrmDeal).where(
            CrmDeal.status == "won",
            CrmDeal.lead_id.in_(
                select(ProposalDocument.lead_id).where(
                    ProposalDocument.status.in_(("sent", "accepted")),
                    ProposalDocument.lead_id.isnot(None),
                ),
            ),
        )
        if client_id:
            prop_q = prop_q.where(ProposalDocument.client_id == client_id)
            won_prop_q = won_prop_q.where(CrmDeal.client_id == client_id)
        sent_proposals = int(await db.scalar(prop_q) or 0)
        won_from_proposals = int(await db.scalar(won_prop_q) or 0)
        proposal_conversion_rate = _rate(won_from_proposals, sent_proposals)

        proposal_source_stats: dict[str, dict[str, Any]] = {}
        if sent_proposals:
            prop_rows = await db.execute(
                select(ProposalDocument, CrmLead)
                .join(CrmLead, ProposalDocument.lead_id == CrmLead.id)
                .where(
                    ProposalDocument.status.in_(("sent", "accepted", "rejected")),
                    ProposalDocument.lead_id.isnot(None),
                ),
            )
            for prop, lead in prop_rows.all():
                src_key, src_label = resolve_revenue_source(lead)
                bucket = proposal_source_stats.setdefault(src_key, {
                    "source": src_key, "label": src_label, "sent": 0, "won": 0,
                })
                bucket["sent"] += 1
                if lead.status == "won":
                    bucket["won"] += 1

        conversions = [
            {"metric": "lead_to_won", "label": "Lead → Won deal", "numerator": deals_won, "denominator": total_leads, "rate": conversion_rate},
            {"metric": "proposal_to_won", "label": "Proposal → Won deal", "numerator": won_from_proposals, "denominator": sent_proposals, "rate": proposal_conversion_rate},
        ]

        total_clicks = sum(l.clicks_count for l in link_map.values())
        total_link_leads = sum(l.leads_count for l in link_map.values())
        link_won = sum(1 for d in won_deals if d.lead and d.lead.attribution_link_id)
        conversions.extend([
            {"metric": "click_to_lead", "label": "Attribution click → Lead", "numerator": total_link_leads, "denominator": total_clicks, "rate": _rate(total_link_leads, total_clicks)},
            {"metric": "link_lead_to_won", "label": "Attribution lead → Won", "numerator": link_won, "denominator": total_link_leads, "rate": _rate(link_won, total_link_leads)},
        ])

        insights = RevenueAttributionService._build_insights(sources, channels, proposal_source_stats)

        return {
            "overview": {
                "total_revenue": _quantize(total_revenue),
                "deals_won": deals_won,
                "avg_deal_size": avg_deal_size,
                "conversion_rate": conversion_rate,
                "proposal_conversion_rate": proposal_conversion_rate,
                "total_leads": total_leads,
                "currency": "UZS",
            },
            "sources": sources,
            "channels": channels,
            "conversions": conversions,
            "insights": insights,
            "proposal_source_stats": proposal_source_stats,
        }

    @staticmethod
    def _build_insights(
        sources: list[dict[str, Any]],
        channels: list[dict[str, Any]],
        proposal_source_stats: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        active_sources = [s for s in sources if s["deals"] > 0 or s["revenue"] > 0]
        active_channels = [c for c in channels if c["deals"] > 0 or c["revenue"] > 0]

        best_source = max(active_sources, key=lambda x: x["revenue"], default=None)
        weakest = None
        if active_sources:
            with_leads = [s for s in sources if s.get("conversion_rate", 0) >= 0 and (s["deals"] > 0 or s["revenue"] > 0)]
            if with_leads:
                weakest = min(with_leads, key=lambda x: (x["revenue"], x["conversion_rate"]))

        best_channel = max(active_channels, key=lambda x: x["revenue"], default=None)

        best_proposal_source = None
        if proposal_source_stats:
            ranked = sorted(
                proposal_source_stats.values(),
                key=lambda x: _rate(x["won"], x["sent"]),
                reverse=True,
            )
            top = ranked[0]
            best_proposal_source = {
                "key": top["source"],
                "label": top["label"],
                "value": f"{_rate(top['won'], top['sent'])}% proposal conversion",
                "metric": "proposal_conversion",
                "conversion_rate": _rate(top["won"], top["sent"]),
            }

        def _insight(row: dict[str, Any] | None, *, kind: str) -> dict[str, Any] | None:
            if not row:
                return None
            key = row.get("source") or row.get("channel") or ""
            label = row.get("label") or key
            return {
                "key": key,
                "label": label,
                "value": f"{row['revenue']} UZS · {row['deals']} deal(s) · {row['conversion_rate']}% conversion",
                "metric": kind,
                "revenue": row["revenue"],
                "conversion_rate": row["conversion_rate"],
            }

        summary_parts: list[str] = []
        if best_source:
            summary_parts.append(f"Top source: {best_source['label']} ({best_source['revenue']} UZS)")
        if best_channel:
            summary_parts.append(f"Top channel: {best_channel['label']}")
        if weakest:
            summary_parts.append(f"Weakest source: {weakest['label']}")
        if best_proposal_source:
            summary_parts.append(f"Best proposal source: {best_proposal_source['label']}")

        return {
            "best_source": _insight(best_source, kind="revenue"),
            "best_channel": _insight(best_channel, kind="revenue"),
            "weakest_source": _insight(weakest, kind="conversion"),
            "best_proposal_source": best_proposal_source,
            "summary": ". ".join(summary_parts) if summary_parts else "No won deals yet — attribution will populate as deals close.",
        }

    @staticmethod
    def _from_cache(client_id: UUID | None) -> dict[str, Any] | None:
        global _cache, _cache_at
        if _cache is None:
            return None
        cache_client = _cache.get("client_id")
        if cache_client != client_id:
            return None
        return _cache

    @staticmethod
    async def _get_data(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        if not force:
            cached = RevenueAttributionService._from_cache(client_id)
            if cached:
                return cached

        errors: list[str] = []
        data = await safe_section(
            "snapshot",
            RevenueAttributionService._load_snapshot(db, client_id=client_id),
            default={
                "overview": {
                    "total_revenue": Decimal("0"),
                    "deals_won": 0,
                    "avg_deal_size": Decimal("0"),
                    "conversion_rate": 0.0,
                    "proposal_conversion_rate": 0.0,
                    "total_leads": 0,
                    "currency": "UZS",
                },
                "sources": [],
                "channels": [],
                "conversions": [],
                "insights": RevenueAttributionService._build_insights([], [], {}),
                "proposal_source_stats": {},
            },
            errors=errors,
            db=db,
        )
        data["errors"] = errors
        data["client_id"] = client_id
        data["recalculated_at"] = _now()
        return data

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        data = await RevenueAttributionService._get_data(db, client_id=client_id)
        ov = {**data["overview"], "recalculated_at": data.get("recalculated_at"), "errors": data.get("errors") or []}
        return ov

    @staticmethod
    async def sources(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        data = await RevenueAttributionService._get_data(db, client_id=client_id)
        items = data.get("sources") or []
        return {"items": items, "total": len(items), "errors": data.get("errors") or []}

    @staticmethod
    async def channels(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        data = await RevenueAttributionService._get_data(db, client_id=client_id)
        items = data.get("channels") or []
        return {"items": items, "total": len(items), "errors": data.get("errors") or []}

    @staticmethod
    async def conversions(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        data = await RevenueAttributionService._get_data(db, client_id=client_id)
        ov = data.get("overview") or {}
        return {
            "items": data.get("conversions") or [],
            "proposal_conversion_rate": ov.get("proposal_conversion_rate", 0.0),
            "errors": data.get("errors") or [],
        }

    @staticmethod
    async def insights(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        data = await RevenueAttributionService._get_data(db, client_id=client_id)
        result = dict(data.get("insights") or {})
        result["errors"] = data.get("errors") or []
        return result

    @staticmethod
    async def recalculate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        global _cache, _cache_at
        data = await RevenueAttributionService._get_data(db, client_id=client_id, force=True)
        _cache = data
        _cache_at = data.get("recalculated_at")
        logger.info("%s recalculated client=%s deals=%s", MARKER, client_id, data["overview"]["deals_won"])
        ov = {**data["overview"], "recalculated_at": data.get("recalculated_at"), "errors": data.get("errors") or []}
        return {
            "overview": ov,
            "sources_count": len(data.get("sources") or []),
            "channels_count": len(data.get("channels") or []),
            "message": "Revenue attribution recalculated — analytics only, no CRM changes",
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        data = await RevenueAttributionService._get_data(db, client_id=client_id)
        ov = data.get("overview") or {}
        ins = data.get("insights") or {}
        best_src = ins.get("best_source") or {}
        best_ch = ins.get("best_channel") or {}
        return {
            "total_revenue": ov.get("total_revenue", Decimal("0")),
            "deals_won": ov.get("deals_won", 0),
            "conversion_rate": ov.get("conversion_rate", 0.0),
            "best_source": best_src.get("key"),
            "best_source_label": best_src.get("label"),
            "best_channel": best_ch.get("key"),
            "best_channel_label": best_ch.get("label"),
        }

    @staticmethod
    async def lead_attribution(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        result = await db.execute(
            select(CrmLead)
            .options(selectinload(CrmLead.client))
            .where(CrmLead.id == lead_id),
        )
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        link_channel = None
        if lead.attribution_link_id:
            link_r = await db.execute(
                select(AttributionLink.channel).where(AttributionLink.id == lead.attribution_link_id),
            )
            link_channel = link_r.scalar_one_or_none()

        comm_r = await db.execute(
            select(CommunicationThread.channel)
            .where(CommunicationThread.lead_id == lead.id)
            .order_by(CommunicationThread.last_message_at.desc().nullslast())
            .limit(1),
        )
        comm_channel = comm_r.scalar_one_or_none()

        src_key, src_label = resolve_revenue_source(lead)
        ch_key, ch_label = resolve_channel(lead, link_channel=link_channel, comm_channel=comm_channel)

        deal_r = await db.execute(
            select(func.count(), func.coalesce(func.sum(CrmDeal.deal_amount), 0))
            .select_from(CrmDeal)
            .where(CrmDeal.lead_id == lead.id, CrmDeal.status == "won"),
        )
        deal_count, won_revenue = deal_r.one()

        return {
            "lead_id": lead.id,
            "source": src_key,
            "source_label": src_label,
            "channel": ch_key,
            "channel_label": ch_label,
            "campaign": lead.attribution_campaign,
            "attribution_link_id": lead.attribution_link_id,
            "won_revenue": _quantize(Decimal(str(won_revenue or 0))) if deal_count else None,
            "deal_count": int(deal_count or 0),
        }

    @staticmethod
    async def deal_room_attribution(db: AsyncSession, lead: CrmLead | None) -> dict[str, Any] | None:
        if not lead:
            return None
        return await RevenueAttributionService.lead_attribution(db, lead.id)
