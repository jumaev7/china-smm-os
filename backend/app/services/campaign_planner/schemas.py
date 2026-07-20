"""Internal (non-ORM, non-HTTP) dataclasses for the Campaign Planner services."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID


PLANNER_VERSION = "1.0.0"
POLICY_VERSION = "1.0.0"

SUPPORTED_PLATFORMS = ("telegram", "facebook", "instagram", "tiktok", "linkedin")
SUPPORTED_LOCALES = ("en", "ru", "uz", "zh")


@dataclass
class PillarSpec:
    key: str          # stable slug used for fingerprinting
    pillar_id: UUID | None
    name: str
    weight: int = 1


@dataclass
class PhaseSpec:
    key: str
    phase_id: UUID | None
    name: str
    start_date: date | None
    end_date: date | None
    weight: int = 1


@dataclass
class PlanSpec:
    """Normalized, deterministic input to the plan generator."""

    start_date: date
    end_date: date
    timezone: str
    primary_locale: str
    locales: list[str]
    platforms: list[str]
    blackout_dates: list[date]
    cadence: dict
    pillars: list[PillarSpec] = field(default_factory=list)
    phases: list[PhaseSpec] = field(default_factory=list)
    planner_version: str = PLANNER_VERSION
    policy_version: str = POLICY_VERSION


@dataclass
class GeneratedSlot:
    index: int
    platform: str
    locale: str
    scheduled_date: date
    scheduled_time: str          # "HH:MM"
    suggested_time_label: str
    pillar_key: str | None
    pillar_id: UUID | None
    phase_key: str | None
    phase_id: UUID | None
    fingerprint: str


@dataclass
class GeneratePlanRequest:
    campaign_id: UUID
    cadence: dict | None = None
    notes: str | None = None
    generation_method: str = "deterministic"
    source_ai_request_id: UUID | None = None
    ai_slot_overlay: list[dict] | None = None
    idempotency_key: str | None = None
