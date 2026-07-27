"""Timezone-safe analysis windows for Listening Phase 2 (`listening_windows_v1`)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.listening.analytics.contracts import AnalysisWindow, Granularity
from app.services.listening.errors import ListeningError

MAX_CUSTOM_RANGE_DAYS = 90
SUPPORTED_WINDOW_KEYS = frozenset({"7d", "30d", "90d", "custom"})
SUPPORTED_GRANULARITIES = frozenset({"hour", "day", "week"})


class InvalidAnalysisWindowError(ListeningError):
    code = "listening_invalid_analysis_window"
    http_status = 400


def _ensure_aware(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def resolve_timezone(name: str | None) -> ZoneInfo:
    tz_name = (name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception as exc:
        raise InvalidAnalysisWindowError(
            f"unsupported timezone: {tz_name}",
            details={"timezone": tz_name},
        ) from exc


def choose_granularity(window_key: str, start: datetime, end: datetime, requested: str | None) -> Granularity:
    duration = end - start
    if requested:
        if requested not in SUPPORTED_GRANULARITIES:
            raise InvalidAnalysisWindowError(
                f"unsupported granularity: {requested}",
                details={"granularity": requested},
            )
        if requested == "hour" and duration > timedelta(days=3):
            raise InvalidAnalysisWindowError(
                "hour granularity requires a window of 3 days or less",
                details={"granularity": requested, "duration_hours": duration.total_seconds() / 3600},
            )
        return requested  # type: ignore[return-value]
    if duration <= timedelta(days=2):
        return "hour"
    if duration <= timedelta(days=45):
        return "day"
    return "week"


def build_analysis_window(
    *,
    window_key: str = "30d",
    start: datetime | None = None,
    end: datetime | None = None,
    timezone_name: str | None = "UTC",
    granularity: str | None = None,
    now: datetime | None = None,
) -> AnalysisWindow:
    """Build current + previous equal-duration comparison windows.

    Boundaries are half-open ``[start, end)`` in the requested timezone,
    converted to UTC-aware datetimes for storage/query use.
    """
    if window_key not in SUPPORTED_WINDOW_KEYS:
        raise InvalidAnalysisWindowError(
            f"unsupported window_key: {window_key}",
            details={"window_key": window_key, "allowed": sorted(SUPPORTED_WINDOW_KEYS)},
        )

    tz = resolve_timezone(timezone_name)
    clock = _ensure_aware(now or datetime.now(timezone.utc), tz)

    if window_key == "custom":
        if start is None or end is None:
            raise InvalidAnalysisWindowError(
                "custom window requires start and end",
                details={"window_key": "custom"},
            )
        cur_start = _ensure_aware(start, tz)
        cur_end = _ensure_aware(end, tz)
        if cur_end <= cur_start:
            raise InvalidAnalysisWindowError(
                "end must be after start",
                details={"start": cur_start.isoformat(), "end": cur_end.isoformat()},
            )
        if (cur_end - cur_start) > timedelta(days=MAX_CUSTOM_RANGE_DAYS):
            raise InvalidAnalysisWindowError(
                f"custom window exceeds {MAX_CUSTOM_RANGE_DAYS} days",
                details={"max_days": MAX_CUSTOM_RANGE_DAYS},
            )
    else:
        days = {"7d": 7, "30d": 30, "90d": 90}[window_key]
        cur_end = clock
        cur_start = cur_end - timedelta(days=days)

    duration = cur_end - cur_start
    prev_end = cur_start
    prev_start = prev_end - duration
    gran = choose_granularity(window_key, cur_start, cur_end, granularity)

    # Store as UTC-aware for DB comparisons.
    return AnalysisWindow(
        start=cur_start.astimezone(timezone.utc),
        end=cur_end.astimezone(timezone.utc),
        timezone=str(tz),
        granularity=gran,
        window_key=window_key,
        comparison_start=prev_start.astimezone(timezone.utc),
        comparison_end=prev_end.astimezone(timezone.utc),
        comparison_valid=True,  # validity later gated by coverage
        completeness_status="unavailable",
        freshness_watermark=None,
    )


def iter_buckets(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    *,
    timezone_name: str = "UTC",
) -> list[tuple[datetime, datetime]]:
    """Return half-open ``[bucket_start, bucket_end)`` pairs covering ``[start, end)``."""
    tz = resolve_timezone(timezone_name)
    cursor = _ensure_aware(start, tz).astimezone(tz)
    end_local = _ensure_aware(end, tz).astimezone(tz)

    if granularity == "hour":
        cursor = cursor.replace(minute=0, second=0, microsecond=0)
        step = timedelta(hours=1)
    elif granularity == "day":
        cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        step = timedelta(days=1)
    else:
        # week: Monday 00:00 local
        cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        cursor = cursor - timedelta(days=cursor.weekday())
        step = timedelta(days=7)

    buckets: list[tuple[datetime, datetime]] = []
    # Avoid inventing buckets entirely before the window start once aligned.
    while cursor < end_local:
        nxt = cursor + step
        b_start = max(cursor, _ensure_aware(start, tz).astimezone(tz))
        b_end = min(nxt, end_local)
        if b_end > b_start:
            buckets.append((b_start.astimezone(timezone.utc), b_end.astimezone(timezone.utc)))
        cursor = nxt
        if len(buckets) > 400:
            raise InvalidAnalysisWindowError(
                "too many buckets for requested window/granularity",
                details={"bucket_count": len(buckets)},
            )
    return buckets


def relative_change(current: float, baseline: float) -> tuple[float | None, str]:
    """Return (percentage_or_none, change_kind). Never returns +inf."""
    if baseline > 0:
        return ((current - baseline) / baseline) * 100.0, "percentage"
    if current > 0 and baseline == 0:
        return None, "new_activity"
    if current == 0 and baseline == 0:
        return None, "zero_baseline_zero_current"
    return None, "unavailable"
