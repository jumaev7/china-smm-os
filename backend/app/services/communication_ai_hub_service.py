"""Communication Hub AI integration layer — extensible stubs for future assistant hooks."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.communication_hub import CommunicationAiCapabilitiesResponse

logger = logging.getLogger(__name__)
MARKER = "[Communication AI Hub]"


class CommunicationAiHubService:
    """Architecture-ready service surface for AI Assistant integration.

    Future implementations will call OpenAI / assistant_service without changing API contracts.
    """

    @staticmethod
    def capabilities() -> CommunicationAiCapabilitiesResponse:
        return CommunicationAiCapabilitiesResponse(
            notes=[
                "Conversation analysis delegates to communication_intelligence_service.",
                "Reply recommendations available via CommunicationCrmService.suggest_reply.",
                "Follow-up suggestions route through CommunicationFollowUpService.",
                "No autonomous outbound messaging — operator approval required.",
            ],
        )

    @staticmethod
    async def analyze_conversation(
        db: AsyncSession,
        thread_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        from app.services.communication_service import CommunicationHubService
        logger.info("%s analyze_conversation thread=%s tenant=%s", MARKER, thread_id, tenant_id)
        result = await CommunicationHubService.ai_summary(db, thread_id)
        return {"thread_id": str(thread_id), "analysis": result, "source": "communication_hub_ai"}

    @staticmethod
    async def recommend_response(
        db: AsyncSession,
        thread_id: UUID,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        from app.services.communication_crm_service import CommunicationCrmService
        logger.info("%s recommend_response thread=%s tenant=%s", MARKER, thread_id, tenant_id)
        result = await CommunicationCrmService.suggest_reply(db, thread_id)
        return {"thread_id": str(thread_id), "recommendation": result, "source": "communication_hub_ai"}

    @staticmethod
    async def detect_inactive_leads(
        db: AsyncSession,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        from app.services.communication_intelligence_service import CommunicationIntelligenceService
        logger.info("%s detect_inactive_leads tenant=%s", MARKER, tenant_id)
        overview = await CommunicationIntelligenceService.overview(db)
        stale = overview.get("stale_conversations", []) if isinstance(overview, dict) else []
        return {
            "tenant_id": str(tenant_id) if tenant_id else None,
            "inactive_signals": stale[:20],
            "source": "communication_intelligence",
        }

    @staticmethod
    async def detect_high_potential_buyers(
        db: AsyncSession,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        from app.services.communication_intelligence_service import CommunicationIntelligenceService
        logger.info("%s detect_high_potential_buyers tenant=%s", MARKER, tenant_id)
        overview = await CommunicationIntelligenceService.overview(db)
        hot = overview.get("high_priority_threads", []) if isinstance(overview, dict) else []
        return {
            "tenant_id": str(tenant_id) if tenant_id else None,
            "high_potential": hot[:20],
            "source": "communication_intelligence",
        }

    @staticmethod
    async def suggest_follow_up_actions(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        from app.services.communication_followup_service import CommunicationFollowUpService
        logger.info("%s suggest_follow_up_actions tenant=%s", MARKER, tenant_id)
        overdue = await CommunicationFollowUpService.list_followups(db, tenant_id, bucket="overdue", limit=10)
        today = await CommunicationFollowUpService.list_followups(db, tenant_id, bucket="today", limit=10)
        return {
            "tenant_id": str(tenant_id),
            "overdue": [f.model_dump() for f in overdue.items],
            "due_today": [f.model_dump() for f in today.items],
            "source": "communication_followup_service",
        }
