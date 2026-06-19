"""Communication Hub dashboard — KPIs, activity, unanswered threads."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.buyer_crm import Buyer
from app.models.communication import (
    CommunicationContact,
    CommunicationFollowUp,
    CommunicationMessage,
    CommunicationThread,
)
from app.models.crm_deal import CrmDeal
from app.models.sales_crm import SalesDeal
from app.schemas.communication_hub import (
    CommunicationActivityItem,
    CommunicationConversationPreview,
    CommunicationDashboardKpis,
    CommunicationDashboardResponse,
)
from app.services.communication_followup_service import CommunicationFollowUpService
from app.services.communication_hub_scope import tenant_client_ids, thread_tenant_filter
from app.services.communication_service import _preview
from app.services.communication_hub_seed_service import CommunicationHubSeedService

logger = logging.getLogger(__name__)
MARKER = "[Communication Hub Dashboard]"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _start_of_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_week(now: datetime) -> datetime:
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _thread_unread(messages: list[CommunicationMessage]) -> int:
    if not messages:
        return 0
    outbound = [m.created_at for m in messages if m.direction == "outbound"]
    last_out = max(outbound) if outbound else None
    if last_out is None:
        return sum(1 for m in messages if m.direction == "inbound")
    return sum(1 for m in messages if m.direction == "inbound" and m.created_at > last_out)


def _is_unanswered(messages: list[CommunicationMessage]) -> bool:
    if not messages:
        return False
    last = messages[-1]
    return last.direction == "inbound" and last.status in ("unanswered", "sent", "delivered", "read")


class CommunicationHubDashboardService:
    @staticmethod
    async def _scoped_threads(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        limit: int = 200,
    ) -> list[CommunicationThread]:
        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        q = (
            select(CommunicationThread)
            .options(
                selectinload(CommunicationThread.messages),
                selectinload(CommunicationThread.contact),
            )
            .order_by(CommunicationThread.last_message_at.desc().nullslast())
            .limit(limit)
        )
        filt = await thread_tenant_filter(tenant_id, client_ids)
        if filt is not None:
            q = q.where(filt)
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    def _thread_preview(thread: CommunicationThread) -> CommunicationConversationPreview:
        messages = thread.messages or []
        last_preview = _preview(messages[-1].message_text) if messages else None
        contact = thread.contact
        return CommunicationConversationPreview(
            id=f"thread:{thread.id}",
            thread_id=thread.id,
            title=thread.title,
            contact_name=contact.name if contact else None,
            channel=thread.channel,
            last_message_preview=last_preview,
            last_message_at=thread.last_message_at,
            status=thread.status,
            unread_count=_thread_unread(messages),
        )

    @staticmethod
    async def dashboard(
        db: AsyncSession,
        tenant_id: UUID | None,
        *,
        seed_if_empty: bool = True,
    ) -> CommunicationDashboardResponse:
        if tenant_id and seed_if_empty:
            await CommunicationHubSeedService.ensure_tenant_demo_data(db, tenant_id)

        now = _utcnow()
        week_start = _start_of_week(now)
        today_start = _start_of_day(now)
        tomorrow_end = today_start + timedelta(days=1)

        client_ids = await tenant_client_ids(db, tenant_id) if tenant_id else []
        thread_filt = await thread_tenant_filter(tenant_id, client_ids)

        msg_q = select(func.count()).select_from(CommunicationMessage).join(CommunicationThread)
        if thread_filt is not None:
            msg_q = msg_q.where(thread_filt)
        total_communications = int((await db.execute(msg_q)).scalar() or 0)

        week_q = (
            select(func.count())
            .select_from(CommunicationMessage)
            .join(CommunicationThread)
            .where(CommunicationMessage.created_at >= week_start)
        )
        if thread_filt is not None:
            week_q = week_q.where(thread_filt)
        communications_this_week = int((await db.execute(week_q)).scalar() or 0)

        threads = await CommunicationHubDashboardService._scoped_threads(db, tenant_id, limit=100)
        unanswered_threads = [t for t in threads if _is_unanswered(t.messages or [])]
        unanswered_conversations = len(unanswered_threads)

        follow_ups_due_today = 0
        if tenant_id:
            fu_q = (
                select(func.count())
                .select_from(CommunicationFollowUp)
                .where(
                    CommunicationFollowUp.tenant_id == tenant_id,
                    CommunicationFollowUp.status == "pending",
                    CommunicationFollowUp.due_date >= today_start,
                    CommunicationFollowUp.due_date < tomorrow_end,
                )
            )
            follow_ups_due_today = int((await db.execute(fu_q)).scalar() or 0)

        active_buyers = 0
        active_negotiations = 0
        if tenant_id:
            active_buyers = int(
                (await db.execute(
                    select(func.count()).select_from(Buyer).where(
                        Buyer.tenant_id == tenant_id,
                        Buyer.status.in_(("active_buyer", "negotiating", "interested")),
                    )
                )).scalar() or 0
            )
            sales_neg = int(
                (await db.execute(
                    select(func.count()).select_from(SalesDeal).where(
                        SalesDeal.tenant_id == tenant_id,
                        SalesDeal.stage == "negotiation",
                    )
                )).scalar() or 0
            )
            if client_ids:
                crm_neg = int(
                    (await db.execute(
                        select(func.count()).select_from(CrmDeal).where(
                            CrmDeal.client_id.in_(client_ids),
                            CrmDeal.status.in_(("negotiation", "proposal_sent", "active")),
                        )
                    )).scalar() or 0
                )
            else:
                crm_neg = 0
            active_negotiations = sales_neg + crm_neg

        kpis = CommunicationDashboardKpis(
            total_communications=total_communications,
            communications_this_week=communications_this_week,
            unanswered_conversations=unanswered_conversations,
            follow_ups_due_today=follow_ups_due_today,
            active_buyers=active_buyers,
            active_negotiations=active_negotiations,
        )

        recent_conversations = [
            CommunicationHubDashboardService._thread_preview(t)
            for t in threads[:8]
        ]
        unanswered = [
            CommunicationHubDashboardService._thread_preview(t)
            for t in unanswered_threads[:6]
        ]

        recent_activity: list[CommunicationActivityItem] = []
        for thread in threads[:12]:
            msgs = list(reversed(thread.messages or []))[:1]
            for msg in msgs:
                recent_activity.append(
                    CommunicationActivityItem(
                        id=str(msg.id),
                        type="message",
                        title=f"{msg.direction.title()} — {thread.title}",
                        subtitle=_preview(msg.message_text, 80),
                        channel=thread.channel,
                        occurred_at=msg.created_at,
                        href=f"/communications/threads/{thread.id}",
                    )
                )
        recent_activity.sort(key=lambda a: a.occurred_at, reverse=True)
        recent_activity = recent_activity[:10]

        follow_ups_due: list[Any] = []
        if tenant_id:
            fu_list = await CommunicationFollowUpService.list_followups(
                db, tenant_id, bucket="today", limit=8,
            )
            follow_ups_due = fu_list.items

        channel_stats: dict[str, int] = {}
        for t in threads:
            channel_stats[t.channel] = channel_stats.get(t.channel, 0) + 1

        logger.info("%s dashboard tenant=%s total=%s", MARKER, tenant_id, total_communications)
        return CommunicationDashboardResponse(
            kpis=kpis,
            recent_conversations=recent_conversations,
            recent_activity=recent_activity,
            follow_ups_due=follow_ups_due,
            unanswered=unanswered,
            statistics={
                "open_threads": sum(1 for t in threads if t.status == "open"),
                "waiting_threads": sum(1 for t in threads if t.status == "waiting"),
                **{f"channel_{k}": v for k, v in channel_stats.items()},
            },
        )
