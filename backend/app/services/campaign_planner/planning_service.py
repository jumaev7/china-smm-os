"""Deterministic campaign plan generator.

Given a normalized :class:`PlanSpec` and a :class:`ResolvedCadence`, produce a
stable, reproducible list of calendar slots. The same inputs always produce the
same ordered output (verified via fingerprints).

Guarantees:
- respects the campaign date range, IANA timezone, and blackout dates
- never emits two slots with the same (platform, date, time)
- distributes pillars by weight and phases by date window
- enforces minimum same-platform spacing and max posts/day/platform
- stable tie-breaking; output ordering is deterministic
- times are labeled as rule-based *suggested* times (never "optimal")
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign_planner import (
    TenantCampaignCalendarSlot,
    TenantCampaignPhase,
    TenantCampaignPillar,
    TenantCampaignPlanVersion,
    TenantContentPillar,
    TenantMarketingCampaign,
)
from app.services.campaign_planner import limits
from app.services.campaign_planner.cadence_engine import ResolvedCadence, resolve_cadence
from app.services.campaign_planner.errors import PlanConfigurationError
from app.services.campaign_planner.plan_fingerprint import (
    compute_plan_fingerprint,
    compute_plan_output_fingerprint,
    compute_slot_fingerprint,
)
from app.services.campaign_planner.schemas import (
    PLANNER_VERSION,
    POLICY_VERSION,
    GeneratedSlot,
    PhaseSpec,
    PillarSpec,
    PlanSpec,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _eligible_dates(spec: PlanSpec, include_weekends: bool) -> list[date]:
    blackout = set(spec.blackout_dates or [])
    out: list[date] = []
    cur = spec.start_date
    while cur <= spec.end_date:
        if cur not in blackout and (include_weekends or cur.weekday() < 5):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _weighted_sequence(items: list[tuple[str, int]], length: int) -> list[str]:
    """Deterministic weighted round-robin (Bresenham-style) allocation.

    Produces a list of ``length`` keys whose frequency approximates the given
    weights, with stable tie-breaking by key ordering.
    """
    if not items or length <= 0:
        return []
    total_weight = sum(max(0, w) for _, w in items)
    if total_weight <= 0:
        # Equal weight fallback.
        items = [(k, 1) for k, _ in items]
        total_weight = len(items)
    # Sort by key for stable order.
    ordered = sorted(items, key=lambda x: x[0])
    accumulators = {k: 0.0 for k, _ in ordered}
    weights = {k: max(0, w) if max(0, w) > 0 else 1 for k, w in ordered}
    result: list[str] = []
    for _ in range(length):
        # Increase each accumulator by its weight, pick the highest; tie-break by key.
        best_key = None
        best_val = None
        for k, _w in ordered:
            accumulators[k] += weights[k] / total_weight
            val = accumulators[k]
            if best_val is None or val > best_val + 1e-12 or (
                abs(val - best_val) <= 1e-12 and (best_key is None or k < best_key)
            ):
                best_val = val
                best_key = k
        assert best_key is not None
        accumulators[best_key] -= 1.0
        result.append(best_key)
    return result


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(hour=int(hh), minute=int(mm))


def _times_for_day(
    suggested: list[tuple[str, str]],
    count: int,
    min_spacing_minutes: int,
) -> list[tuple[time, str]]:
    """Return ``count`` (time, label) pairs for one day, spaced >= min_spacing."""
    picked: list[tuple[time, str]] = []
    base = [(_parse_hhmm(t), label) for t, label in suggested]
    # Filter suggested list so consecutive picks satisfy spacing.
    for t, label in base:
        if len(picked) >= count:
            break
        if not picked:
            picked.append((t, label))
            continue
        last = picked[-1][0]
        delta = (t.hour * 60 + t.minute) - (last.hour * 60 + last.minute)
        if delta >= min_spacing_minutes:
            picked.append((t, label))
    # If we still need more, extend by adding min_spacing after the last picked time.
    while len(picked) < count:
        last = picked[-1][0] if picked else time(9, 0)
        total = last.hour * 60 + last.minute + min_spacing_minutes
        if total >= 24 * 60:
            # Cannot fit more distinct spaced times in a single day.
            break
        picked.append((time(total // 60, total % 60), "suggested"))
    return picked[:count]


def generate_slots(spec: PlanSpec, cadence: ResolvedCadence) -> list[GeneratedSlot]:
    """Pure deterministic slot generator."""
    if spec.end_date < spec.start_date:
        raise PlanConfigurationError(
            "end_date must be on or after start_date",
            details={"field": "date_range"},
        ).to_http()
    duration = (spec.end_date - spec.start_date).days + 1
    if duration > limits.MAX_CAMPAIGN_DURATION_DAYS:
        raise PlanConfigurationError(
            "Campaign duration exceeds maximum",
            details={"max_days": limits.MAX_CAMPAIGN_DURATION_DAYS, "days": duration},
        ).to_http()
    if not spec.platforms:
        raise PlanConfigurationError("At least one platform is required", details={"field": "platforms"}).to_http()

    days = _eligible_dates(spec, cadence.hard.include_weekends)
    if not days:
        raise PlanConfigurationError(
            "No eligible posting dates in range after blackout/weekend filtering",
            details={"field": "date_range"},
        ).to_http()

    weeks = max(1, (len(days) + 6) // 7)
    locales = spec.locales or [spec.primary_locale]

    # Build a preliminary set of (platform, date) placements respecting max/day.
    per_platform_daycount: dict[tuple[str, date], int] = {}
    placements: list[tuple[str, date]] = []  # ordered by (date, platform)
    for platform in sorted(spec.platforms):
        pref = cadence.preferences.get(platform)
        posts_per_week = pref.posts_per_week if pref else 3
        target_total = min(
            posts_per_week * weeks,
            cadence.hard.max_posts_per_day_per_platform * len(days),
        )
        target_total = max(0, target_total)
        placed = 0
        i = 0
        # Even spread across days; overflow rolls forward deterministically.
        while placed < target_total:
            # deterministic day index via even stride over the full range
            day_index = (i * len(days)) // max(1, target_total)
            attempts = 0
            while attempts < len(days):
                d = days[day_index % len(days)]
                key = (platform, d)
                if per_platform_daycount.get(key, 0) < cadence.hard.max_posts_per_day_per_platform:
                    per_platform_daycount[key] = per_platform_daycount.get(key, 0) + 1
                    placements.append((platform, d))
                    placed += 1
                    break
                day_index += 1
                attempts += 1
            else:
                # Every day is full for this platform.
                break
            i += 1

    # Order placements deterministically by (date, platform).
    placements.sort(key=lambda x: (x[1], x[0]))
    if len(placements) > limits.MAX_SLOTS_PER_PLAN:
        placements = placements[: limits.MAX_SLOTS_PER_PLAN]

    # Assign concrete times per (platform, date) group.
    from collections import defaultdict

    grouped: dict[tuple[str, date], int] = defaultdict(int)
    for platform, d in placements:
        grouped[(platform, d)] += 1

    day_time_map: dict[tuple[str, date], list[tuple[time, str]]] = {}
    for (platform, d), cnt in grouped.items():
        pref = cadence.preferences.get(platform)
        suggested = pref.suggested_times if pref else [("09:00", "morning")]
        day_time_map[(platform, d)] = _times_for_day(suggested, cnt, cadence.hard.min_spacing_minutes)

    # Now materialize slots with times, pillars, phases, locales.
    pillar_seq = _weighted_sequence(
        [(p.key, p.weight) for p in spec.pillars],
        len(placements),
    ) if spec.pillars else []
    pillar_by_key = {p.key: p for p in spec.pillars}

    # Deterministic locale rotation per (platform) to guarantee coverage.
    platform_locale_counter: dict[str, int] = defaultdict(int)

    # Track consumed time index per (platform, date).
    consumed: dict[tuple[str, date], int] = defaultdict(int)
    seen: set[tuple[str, str, str]] = set()  # (platform, date_iso, time_iso)

    slots: list[GeneratedSlot] = []
    for idx, (platform, d) in enumerate(placements):
        times = day_time_map[(platform, d)]
        ti = consumed[(platform, d)]
        if ti >= len(times):
            continue
        consumed[(platform, d)] += 1
        slot_time, label = times[ti]
        dedup_key = (platform, d.isoformat(), slot_time.strftime("%H:%M"))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # locale rotation
        loc = locales[platform_locale_counter[platform] % len(locales)]
        platform_locale_counter[platform] += 1

        # pillar
        pillar_key = pillar_seq[idx] if idx < len(pillar_seq) else None
        pillar_spec = pillar_by_key.get(pillar_key) if pillar_key else None

        # phase (first phase whose window contains d; else None)
        phase_key = None
        phase_id = None
        for ph in sorted(spec.phases, key=lambda p: (p.start_date or spec.start_date, p.key)):
            s = ph.start_date or spec.start_date
            e = ph.end_date or spec.end_date
            if s <= d <= e:
                phase_key = ph.key
                phase_id = ph.phase_id
                break

        slot_dict = {
            "platform": platform,
            "locale": loc,
            "date": d.isoformat(),
            "time": slot_time.strftime("%H:%M"),
            "pillar_key": pillar_key,
            "phase_key": phase_key,
            "index": idx,
        }
        fingerprint = compute_slot_fingerprint(slot_dict)
        slots.append(
            GeneratedSlot(
                index=idx,
                platform=platform,
                locale=loc,
                scheduled_date=d,
                scheduled_time=slot_time.strftime("%H:%M"),
                suggested_time_label=label,
                pillar_key=pillar_key,
                pillar_id=pillar_spec.pillar_id if pillar_spec else None,
                phase_key=phase_key,
                phase_id=phase_id,
                fingerprint=fingerprint,
            )
        )

    # Final deterministic ordering.
    slots.sort(key=lambda s: (s.scheduled_date, s.scheduled_time, s.platform, s.locale))
    for i, s in enumerate(slots):
        s.index = i
    return slots


class PlanningService:
    """Persists deterministic (and AI-overlaid) plan versions for a campaign."""

    @staticmethod
    async def _build_spec(
        db: AsyncSession,
        campaign: TenantMarketingCampaign,
        *,
        cadence_override: dict | None,
    ) -> tuple[PlanSpec, ResolvedCadence]:
        if campaign.start_date is None or campaign.end_date is None:
            raise PlanConfigurationError(
                "Campaign start_date and end_date are required to generate a plan",
                details={"field": "date_range"},
            ).to_http()

        platforms = [p for p in (campaign.platforms or []) if p in _PLATFORMS]
        if not platforms:
            raise PlanConfigurationError(
                "Campaign has no supported platforms configured",
                details={"field": "platforms"},
            ).to_http()
        locales = [loc for loc in (campaign.locales or [campaign.primary_locale]) if loc in _LOCALES]
        if not locales:
            locales = [campaign.primary_locale if campaign.primary_locale in _LOCALES else "en"]

        # Pillars (with weights) joined to reusable pillar defs.
        link_rows = (
            await db.execute(
                select(TenantCampaignPillar, TenantContentPillar)
                .join(TenantContentPillar, TenantContentPillar.id == TenantCampaignPillar.pillar_id)
                .where(
                    TenantCampaignPillar.tenant_id == campaign.tenant_id,
                    TenantCampaignPillar.campaign_id == campaign.id,
                )
                .order_by(TenantCampaignPillar.sort_order.asc(), TenantContentPillar.slug.asc())
            )
        ).all()
        pillars = [
            PillarSpec(key=cp.slug, pillar_id=cp.id, name=cp.name, weight=int(link.weight or 1))
            for link, cp in link_rows
        ]

        phase_rows = (
            await db.execute(
                select(TenantCampaignPhase)
                .where(
                    TenantCampaignPhase.tenant_id == campaign.tenant_id,
                    TenantCampaignPhase.campaign_id == campaign.id,
                )
                .order_by(TenantCampaignPhase.sort_order.asc(), TenantCampaignPhase.name.asc())
            )
        ).scalars().all()
        phases = [
            PhaseSpec(
                key=str(ph.sort_order) + ":" + (ph.name or ""),
                phase_id=ph.id,
                name=ph.name,
                start_date=ph.start_date,
                end_date=ph.end_date,
                weight=int(ph.weight or 1),
            )
            for ph in phase_rows
        ]

        blackout: list[date] = []
        for raw in (campaign.blackout_dates or []):
            try:
                blackout.append(date.fromisoformat(str(raw)[:10]))
            except ValueError:
                continue

        cadence_cfg = cadence_override if cadence_override is not None else (campaign.cadence or {})
        spec = PlanSpec(
            start_date=campaign.start_date,
            end_date=campaign.end_date,
            timezone=campaign.timezone or "UTC",
            primary_locale=campaign.primary_locale or "en",
            locales=locales,
            platforms=platforms,
            blackout_dates=blackout,
            cadence=cadence_cfg,
            pillars=pillars,
            phases=phases,
            planner_version=PLANNER_VERSION,
            policy_version=POLICY_VERSION,
        )
        resolved = resolve_cadence(platforms, cadence_cfg)
        return spec, resolved

    @staticmethod
    def _spec_to_fingerprint_dict(spec: PlanSpec) -> dict:
        return {
            "planner_version": spec.planner_version,
            "policy_version": spec.policy_version,
            "start_date": spec.start_date.isoformat(),
            "end_date": spec.end_date.isoformat(),
            "timezone": spec.timezone,
            "primary_locale": spec.primary_locale,
            "locales": list(spec.locales),
            "platforms": list(spec.platforms),
            "blackout_dates": [d.isoformat() for d in spec.blackout_dates],
            "cadence": spec.cadence or {},
            "pillars": [{"key": p.key, "weight": p.weight} for p in spec.pillars],
            "phases": [
                {
                    "key": p.key,
                    "start": p.start_date.isoformat() if p.start_date else None,
                    "end": p.end_date.isoformat() if p.end_date else None,
                    "weight": p.weight,
                }
                for p in spec.phases
            ],
        }

    @classmethod
    async def generate_plan(
        cls,
        db: AsyncSession,
        campaign: TenantMarketingCampaign,
        *,
        cadence_override: dict | None = None,
        generation_method: str = "deterministic",
        source_ai_request_id: UUID | None = None,
        parent_version_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> tuple[TenantCampaignPlanVersion, list[TenantCampaignCalendarSlot]]:
        spec, resolved = await cls._build_spec(db, campaign, cadence_override=cadence_override)
        generated = generate_slots(spec, resolved)

        fp_dict = cls._spec_to_fingerprint_dict(spec)
        plan_fp = compute_plan_fingerprint(fp_dict)
        output_fp = compute_plan_output_fingerprint(
            [
                {
                    "platform": s.platform,
                    "locale": s.locale,
                    "date": s.scheduled_date.isoformat(),
                    "time": s.scheduled_time,
                    "pillar_key": s.pillar_key,
                    "phase_key": s.phase_key,
                    "index": s.index,
                }
                for s in generated
            ]
        )

        # Next version number.
        existing_versions = (
            await db.execute(
                select(TenantCampaignPlanVersion.version).where(
                    TenantCampaignPlanVersion.tenant_id == campaign.tenant_id,
                    TenantCampaignPlanVersion.campaign_id == campaign.id,
                )
            )
        ).scalars().all()
        next_version = (max(existing_versions) + 1) if existing_versions else 1
        limits.enforce(next_version, limits.MAX_PLAN_VERSIONS_PER_CAMPAIGN, "plan_versions_per_campaign")

        pillar_summary: dict[str, int] = {}
        platform_summary: dict[str, int] = {}
        locale_summary: dict[str, int] = {}
        for s in generated:
            platform_summary[s.platform] = platform_summary.get(s.platform, 0) + 1
            locale_summary[s.locale] = locale_summary.get(s.locale, 0) + 1
            if s.pillar_key:
                pillar_summary[s.pillar_key] = pillar_summary.get(s.pillar_key, 0) + 1

        plan = TenantCampaignPlanVersion(
            id=uuid4(),
            tenant_id=campaign.tenant_id,
            campaign_id=campaign.id,
            version=next_version,
            status="draft",
            generation_method=generation_method,
            plan_fingerprint=plan_fp,
            planner_version=PLANNER_VERSION,
            policy_version=POLICY_VERSION,
            parameters={
                "spec": fp_dict,
                "cadence": resolved.to_dict(),
            },
            summary={
                "slot_count": len(generated),
                "platforms": platform_summary,
                "locales": locale_summary,
                "pillars": pillar_summary,
                "output_fingerprint": output_fp,
                "suggested_time_note": "Times are rule-based suggested times, not engagement-optimal predictions.",
            },
            source_ai_request_id=source_ai_request_id,
            parent_version_id=parent_version_id,
            slot_count=len(generated),
            created_by=created_by,
        )
        db.add(plan)
        await db.flush()

        slot_rows: list[TenantCampaignCalendarSlot] = []
        for s in generated:
            row = TenantCampaignCalendarSlot(
                id=uuid4(),
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                plan_version_id=plan.id,
                slot_index=s.index,
                platform=s.platform,
                locale=s.locale,
                pillar_id=s.pillar_id,
                phase_id=s.phase_id,
                scheduled_date=s.scheduled_date,
                scheduled_time=_parse_hhmm(s.scheduled_time),
                suggested_time_label=s.suggested_time_label,
                status="unassigned",
                slot_fingerprint=s.fingerprint,
            )
            db.add(row)
            slot_rows.append(row)
        await db.flush()
        return plan, slot_rows

    # ---------------------------------------------------------- lifecycle
    @classmethod
    async def generate(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        *,
        cadence_override: dict | None = None,
        created_by: UUID | None = None,
    ) -> TenantCampaignPlanVersion:
        from app.services.automation_domain_events import emit_domain_event
        from app.services.campaign_planner.campaign_service import CampaignService

        campaign = await CampaignService.load_campaign(db, tenant_id, campaign_id)
        CampaignService._assert_mutable(campaign)
        plan, slots = await cls.generate_plan(
            db, campaign, cadence_override=cadence_override, created_by=created_by,
        )
        campaign.current_plan_version_id = plan.id
        if campaign.status == "draft":
            campaign.status = "planning"
        await db.flush()

        await emit_domain_event(
            db, "campaign.plan_generated", tenant_id,
            payload={
                "campaign_id": str(campaign.id),
                "plan_version_id": str(plan.id),
                "version": plan.version,
                "generation_method": plan.generation_method,
                "slot_count": plan.slot_count,
                "plan_fingerprint": plan.plan_fingerprint,
                "planner_version": plan.planner_version,
            },
            resource_type="campaign", resource_id=str(campaign.id),
            title="Campaign plan generated",
        )
        return plan

    @classmethod
    async def publish(
        cls, db: AsyncSession, tenant_id: UUID, campaign_id: UUID, plan_id: UUID, *, published_by: UUID | None = None,
    ) -> TenantCampaignPlanVersion:
        from app.services.automation_domain_events import emit_domain_event
        from app.services.campaign_planner.calendar_service import CalendarService
        from app.services.campaign_planner.campaign_service import CampaignService
        from app.services.campaign_planner.errors import PlanImmutableError

        campaign = await CampaignService.load_campaign(db, tenant_id, campaign_id)
        plan = await CalendarService.load_plan(db, tenant_id, campaign_id, plan_id)
        if plan.status == "published":
            return plan
        if plan.status in ("superseded", "archived"):
            raise PlanImmutableError(
                "Cannot publish a superseded or archived plan version",
                details={"status": plan.status},
            ).to_http()

        now = _utcnow()
        # Supersede any currently published plan for this campaign.
        prev = (
            await db.execute(
                select(TenantCampaignPlanVersion).where(
                    TenantCampaignPlanVersion.tenant_id == tenant_id,
                    TenantCampaignPlanVersion.campaign_id == campaign_id,
                    TenantCampaignPlanVersion.status == "published",
                )
            )
        ).scalars().all()
        for row in prev:
            row.status = "superseded"
            row.superseded_at = now

        plan.status = "published"
        plan.published_at = now
        campaign.published_plan_version_id = plan.id
        campaign.current_plan_version_id = plan.id
        if campaign.status in ("draft", "planning"):
            campaign.status = "approved"
        await db.flush()

        await emit_domain_event(
            db, "campaign.plan_published", tenant_id,
            payload={
                "campaign_id": str(campaign.id),
                "plan_version_id": str(plan.id),
                "version": plan.version,
                "slot_count": plan.slot_count,
                "plan_fingerprint": plan.plan_fingerprint,
            },
            resource_type="campaign", resource_id=str(campaign.id),
            title="Campaign plan published",
        )
        return plan

    @classmethod
    async def clone(
        cls, db: AsyncSession, tenant_id: UUID, campaign_id: UUID, plan_id: UUID, *, created_by: UUID | None = None,
    ) -> TenantCampaignPlanVersion:
        from app.services.campaign_planner.calendar_service import CalendarService
        from app.services.campaign_planner.campaign_service import CampaignService

        campaign = await CampaignService.load_campaign(db, tenant_id, campaign_id)
        CampaignService._assert_mutable(campaign)
        source = await CalendarService.load_plan(db, tenant_id, campaign_id, plan_id)
        source_slots = await CalendarService.list_slots(db, tenant_id, plan_id)

        existing_versions = (
            await db.execute(
                select(TenantCampaignPlanVersion.version).where(
                    TenantCampaignPlanVersion.tenant_id == tenant_id,
                    TenantCampaignPlanVersion.campaign_id == campaign_id,
                )
            )
        ).scalars().all()
        next_version = (max(existing_versions) + 1) if existing_versions else 1
        limits.enforce(next_version, limits.MAX_PLAN_VERSIONS_PER_CAMPAIGN, "plan_versions_per_campaign")

        clone = TenantCampaignPlanVersion(
            id=uuid4(),
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            version=next_version,
            status="draft",
            generation_method=source.generation_method,
            plan_fingerprint=source.plan_fingerprint,
            planner_version=source.planner_version,
            policy_version=source.policy_version,
            parameters=source.parameters,
            summary=source.summary,
            notes=source.notes,
            parent_version_id=source.id,
            slot_count=source.slot_count,
            created_by=created_by,
        )
        db.add(clone)
        await db.flush()

        for s in source_slots:
            db.add(TenantCampaignCalendarSlot(
                id=uuid4(), tenant_id=tenant_id, campaign_id=campaign_id, plan_version_id=clone.id,
                slot_index=s.slot_index, platform=s.platform, locale=s.locale,
                pillar_id=s.pillar_id, phase_id=s.phase_id,
                scheduled_date=s.scheduled_date, scheduled_time=s.scheduled_time,
                suggested_time_label=s.suggested_time_label, status="unassigned",
                slot_fingerprint=s.slot_fingerprint, notes=s.notes,
            ))
        campaign.current_plan_version_id = clone.id
        await db.flush()
        return clone

    @classmethod
    async def review(
        cls, db: AsyncSession, tenant_id: UUID, campaign_id: UUID, plan_id: UUID, *, created_by: UUID | None = None,
    ):
        from app.services.campaign_planner.calendar_service import CalendarService
        from app.services.campaign_planner.campaign_service import CampaignService
        from app.services.campaign_planner.review_engine import CampaignReviewEngine

        campaign = await CampaignService.load_campaign(db, tenant_id, campaign_id)
        plan = await CalendarService.load_plan(db, tenant_id, campaign_id, plan_id)
        review = await CampaignReviewEngine.review_plan(db, tenant_id, campaign, plan, created_by=created_by)
        if plan.status == "draft":
            plan.status = "reviewed"
            plan.reviewed_at = _utcnow()
            await db.flush()
        return review


_PLATFORMS = frozenset({"telegram", "facebook", "instagram", "tiktok", "linkedin"})
_LOCALES = frozenset({"en", "ru", "uz", "zh"})
