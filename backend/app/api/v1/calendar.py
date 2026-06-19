from uuid import UUID
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.content_service import CalendarService
from app.services.publish_service import PublishService
from app.schemas.content import CalendarEntryCreate, CalendarEntryUpdate, CalendarEntryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.post("/schedule", response_model=CalendarEntryResponse, status_code=201)
async def schedule_content(data: CalendarEntryCreate, db: AsyncSession = Depends(get_db)):
    entry = await CalendarService.schedule(db, data)
    return CalendarService.serialize_entry(entry)


@router.get("/month/{year}/{month}", response_model=list[CalendarEntryResponse])
async def get_calendar_month(year: int, month: int, db: AsyncSession = Depends(get_db)):
    entries = await CalendarService.get_month(db, year, month)
    return [CalendarService.serialize_entry(e) for e in entries]


@router.patch("/{entry_id}", response_model=CalendarEntryResponse)
async def update_calendar_entry(
    entry_id: UUID, data: CalendarEntryUpdate, db: AsyncSession = Depends(get_db)
):
    entry = await CalendarService.update_entry(db, entry_id, data)
    return CalendarService.serialize_entry(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_calendar_entry(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    await CalendarService.delete_entry(db, entry_id)


@router.post("/{entry_id}/publish", response_model=CalendarEntryResponse)
async def mark_published(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    logger.info("[Publish] API called: calendar entry_id=%s", entry_id)
    entry = await CalendarService.mark_published(db, entry_id)
    return CalendarService.serialize_entry(entry)


@router.post("/{entry_id}/draft", status_code=204)
async def move_to_draft(entry_id: UUID, db: AsyncSession = Depends(get_db)):
    await CalendarService.move_to_draft(db, entry_id)
