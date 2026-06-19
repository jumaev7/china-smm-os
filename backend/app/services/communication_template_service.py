"""Communication Hub message template CRUD."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import TEMPLATE_CATEGORIES, CommunicationMessageTemplate
from app.schemas.communication_hub import (
    MessageTemplateCreate,
    MessageTemplateListResponse,
    MessageTemplateResponse,
    MessageTemplateUpdate,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CommunicationTemplateService:
    @staticmethod
    def _to_response(row: CommunicationMessageTemplate) -> MessageTemplateResponse:
        return MessageTemplateResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            category=row.category,
            content=row.content,
            language=row.language,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    async def _load(
        db: AsyncSession,
        template_id: UUID,
        tenant_id: UUID,
    ) -> CommunicationMessageTemplate:
        row = (
            await db.execute(
                select(CommunicationMessageTemplate).where(
                    CommunicationMessageTemplate.id == template_id,
                    CommunicationMessageTemplate.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found")
        return row

    @staticmethod
    async def list_templates(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        category: str | None = None,
        language: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> MessageTemplateListResponse:
        q = (
            select(CommunicationMessageTemplate)
            .where(CommunicationMessageTemplate.tenant_id == tenant_id)
            .order_by(CommunicationMessageTemplate.category, CommunicationMessageTemplate.name)
        )
        count_q = (
            select(func.count())
            .select_from(CommunicationMessageTemplate)
            .where(CommunicationMessageTemplate.tenant_id == tenant_id)
        )
        if category:
            q = q.where(CommunicationMessageTemplate.category == category)
            count_q = count_q.where(CommunicationMessageTemplate.category == category)
        if language:
            q = q.where(CommunicationMessageTemplate.language == language)
            count_q = count_q.where(CommunicationMessageTemplate.language == language)
        if search:
            like = f"%{search.strip()}%"
            q = q.where(
                CommunicationMessageTemplate.name.ilike(like)
                | CommunicationMessageTemplate.content.ilike(like)
            )
            count_q = count_q.where(
                CommunicationMessageTemplate.name.ilike(like)
                | CommunicationMessageTemplate.content.ilike(like)
            )

        total = int((await db.execute(count_q)).scalar() or 0)
        rows = list((await db.execute(q.offset(skip).limit(limit))).scalars().all())
        return MessageTemplateListResponse(
            items=[CommunicationTemplateService._to_response(r) for r in rows],
            total=total,
        )

    @staticmethod
    async def create_template(
        db: AsyncSession,
        tenant_id: UUID,
        data: MessageTemplateCreate,
    ) -> MessageTemplateResponse:
        if data.category not in TEMPLATE_CATEGORIES:
            raise HTTPException(status_code=422, detail="Invalid template category")
        row = CommunicationMessageTemplate(
            tenant_id=tenant_id,
            name=data.name.strip(),
            category=data.category,
            content=data.content.strip(),
            language=data.language.strip().lower() or "en",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return CommunicationTemplateService._to_response(row)

    @staticmethod
    async def update_template(
        db: AsyncSession,
        tenant_id: UUID,
        template_id: UUID,
        data: MessageTemplateUpdate,
    ) -> MessageTemplateResponse:
        row = await CommunicationTemplateService._load(db, template_id, tenant_id)
        if data.name is not None:
            row.name = data.name.strip()
        if data.category is not None:
            if data.category not in TEMPLATE_CATEGORIES:
                raise HTTPException(status_code=422, detail="Invalid template category")
            row.category = data.category
        if data.content is not None:
            row.content = data.content.strip()
        if data.language is not None:
            row.language = data.language.strip().lower() or "en"
        row.updated_at = _utcnow()
        await db.commit()
        await db.refresh(row)
        return CommunicationTemplateService._to_response(row)

    @staticmethod
    async def delete_template(
        db: AsyncSession,
        tenant_id: UUID,
        template_id: UUID,
    ) -> None:
        row = await CommunicationTemplateService._load(db, template_id, tenant_id)
        await db.delete(row)
        await db.commit()

    @staticmethod
    async def ensure_default_templates(db: AsyncSession, tenant_id: UUID) -> None:
        existing = int(
            (await db.execute(
                select(func.count()).select_from(CommunicationMessageTemplate).where(
                    CommunicationMessageTemplate.tenant_id == tenant_id,
                )
            )).scalar() or 0
        )
        if existing:
            return
        defaults = [
            ("First contact — EN", "first_contact", "en",
             "Hello {{name}}, thank you for your interest in our products. "
             "I would be happy to share our catalog and discuss your requirements."),
            ("Follow-up — EN", "follow_up", "en",
             "Hi {{name}}, I wanted to follow up on our previous conversation. "
             "Please let me know if you have any questions or would like updated pricing."),
            ("Proposal follow-up — EN", "proposal_follow_up", "en",
             "Dear {{name}}, I am following up regarding the commercial proposal we sent. "
             "We are ready to adjust terms based on your feedback."),
            ("Negotiation — EN", "negotiation", "en",
             "Thank you for sharing your target price and MOQ. "
             "We can review options and propose a revised offer."),
            ("Re-engagement — EN", "re_engagement", "en",
             "Hello {{name}}, it has been a while since we last spoke. "
             "We have new products and promotions that may interest you."),
            ("Customer support — EN", "customer_support", "en",
             "Thank you for reaching out. We have received your message and will respond shortly."),
        ]
        for name, category, language, content in defaults:
            db.add(CommunicationMessageTemplate(
                tenant_id=tenant_id,
                name=name,
                category=category,
                content=content,
                language=language,
            ))
        await db.commit()
