"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  publishingApi,
  clientsApi,
  Client,
  Platform,
  PublishingCalendarItem,
  ContentStatus,
  normalizeList,
} from "@/lib/api";
import { formatScheduledLocal, LOCAL_TIMEZONE_NOTE } from "@/lib/datetime";
import { STATUS_CONFIG, PLATFORM_CONFIG, cn } from "@/lib/utils";
import {
  ChevronLeft,
  ChevronRight,
  CalendarDays,
  Radio,
} from "lucide-react";
import {
  format,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  startOfDay,
  endOfDay,
  eachDayOfInterval,
  addMonths,
  subMonths,
  addWeeks,
  subWeeks,
  addDays,
  subDays,
  isToday,
  getDay,
} from "date-fns";

type ViewMode = "day" | "week" | "month";

const ALL_PLATFORMS: Platform[] = ["instagram", "facebook", "tiktok", "telegram", "linkedin"];

const CALENDAR_STATUSES: { value: string; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "scheduled", label: "Scheduled" },
  { value: "publishing", label: "Publishing" },
  { value: "published", label: "Published" },
  { value: "failed", label: "Failed" },
  { value: "partial_failed", label: "Partial failed" },
];

function toDateParam(d: Date): string {
  return format(d, "yyyy-MM-dd");
}

function calendarEventAt(item: PublishingCalendarItem): Date | null {
  if (item.status === "scheduled" || item.status === "publishing") {
    return item.scheduled_for ? new Date(item.scheduled_for) : null;
  }
  if (item.published_at) return new Date(item.published_at);
  if (item.scheduled_for) return new Date(item.scheduled_for);
  return null;
}

function eventTimeLabel(item: PublishingCalendarItem): string {
  const at = calendarEventAt(item);
  if (!at) return "—";
  return formatScheduledLocal(at.toISOString(), {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function CalendarEventChip({
  item,
  onClick,
  compact,
}: {
  item: PublishingCalendarItem;
  onClick: () => void;
  compact?: boolean;
}) {
  const statusCfg = STATUS_CONFIG[item.status as ContentStatus] ?? STATUS_CONFIG.scheduled;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-md border px-1.5 py-1 transition-all hover:shadow-sm hover:-translate-y-px",
        statusCfg.color,
        compact ? "text-[10px]" : "text-xs",
      )}
    >
      <div className="flex items-center justify-between gap-1">
        <span className="font-bold shrink-0">{eventTimeLabel(item)}</span>
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", statusCfg.dot)} />
      </div>
      <p className="font-medium truncate">{item.company_name}</p>
      {!compact && <p className="truncate opacity-80">{item.title}</p>}
      <div className="flex flex-wrap gap-0.5 mt-0.5">
        {item.platforms.slice(0, compact ? 2 : 4).map((p) => (
          <span
            key={p}
            className={cn(
              "text-[9px] px-1 rounded font-bold",
              PLATFORM_CONFIG[p]?.color ?? "bg-gray-100",
            )}
          >
            {PLATFORM_CONFIG[p]?.icon ?? p}
          </span>
        ))}
      </div>
      <span className="text-[9px] opacity-70">{statusCfg.label}</span>
    </button>
  );
}

export default function PublishingCalendarPage() {
  const router = useRouter();
  const [view, setView] = useState<ViewMode>("month");
  const [current, setCurrent] = useState(new Date());
  const [platformFilter, setPlatformFilter] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const range = useMemo(() => {
    if (view === "day") {
      return { start: startOfDay(current), end: endOfDay(current) };
    }
    if (view === "week") {
      return { start: startOfWeek(current), end: endOfWeek(current) };
    }
    return { start: startOfMonth(current), end: endOfMonth(current) };
  }, [view, current]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data, isLoading } = useQuery({
    queryKey: [
      "publishing-calendar",
      view,
      toDateParam(range.start),
      toDateParam(range.end),
      platformFilter,
      clientFilter,
      statusFilter,
    ],
    queryFn: () =>
      publishingApi
        .getCalendar({
          from: toDateParam(range.start),
          to: toDateParam(range.end),
          client_id: clientFilter || undefined,
          platform: (platformFilter as Platform) || undefined,
          status: statusFilter || undefined,
        })
        .then((r) => r.data),
  });

  const items = normalizeList(data);

  const itemsByDay = useMemo(() => {
    const map = new Map<string, PublishingCalendarItem[]>();
    for (const item of items) {
      const at = calendarEventAt(item);
      if (!at) continue;
      const key = format(at, "yyyy-MM-dd");
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    for (const [, list] of map) {
      list.sort((a, b) => {
        const ta = calendarEventAt(a)?.getTime() ?? 0;
        const tb = calendarEventAt(b)?.getTime() ?? 0;
        return ta - tb;
      });
    }
    return map;
  }, [items]);

  const goPrev = () => {
    if (view === "month") setCurrent(subMonths(current, 1));
    else if (view === "week") setCurrent(subWeeks(current, 1));
    else setCurrent(subDays(current, 1));
  };

  const goNext = () => {
    if (view === "month") setCurrent(addMonths(current, 1));
    else if (view === "week") setCurrent(addWeeks(current, 1));
    else setCurrent(addDays(current, 1));
  };

  const goToday = () => setCurrent(new Date());

  const headerLabel =
    view === "month"
      ? format(current, "MMMM yyyy")
      : view === "week"
        ? `${format(startOfWeek(current), "MMM d")} – ${format(endOfWeek(current), "MMM d, yyyy")}`
        : format(current, "EEEE, MMMM d, yyyy");

  const openItem = (id: string) => router.push(`/content/${id}`);

  const monthDays =
    view === "month"
      ? eachDayOfInterval({ start: startOfMonth(current), end: endOfMonth(current) })
      : [];
  const monthStartPad = view === "month" ? getDay(startOfMonth(current)) : 0;

  const weekDays =
    view === "week"
      ? eachDayOfInterval({ start: startOfWeek(current), end: endOfWeek(current) })
      : [];

  const dayItems = itemsByDay.get(format(current, "yyyy-MM-dd")) ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <CalendarDays size={20} className="text-brand-600" />
            <h1 className="text-xl font-semibold text-gray-900">Publishing Calendar</h1>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            Scheduled, published, and failed posts — {data?.total ?? 0} in range
          </p>
          <p className="text-[11px] text-gray-400 mt-1">{LOCAL_TIMEZONE_NOTE}</p>
        </div>
        <Link
          href="/publishing"
          className="btn-secondary text-xs flex items-center gap-1.5"
        >
          <Radio size={14} />
          Publishing accounts
        </Link>
      </div>

      {/* Filters */}
      <div className="card p-4 mb-4 flex flex-wrap gap-3 items-end">
        <div>
          <label className="label">View</label>
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            {(["day", "week", "month"] as ViewMode[]).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                  view === v
                    ? "bg-brand-600 text-white"
                    : "bg-white text-gray-600 hover:bg-gray-50",
                )}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
        <div className="min-w-[140px]">
          <label className="label">Platform</label>
          <select
            className="input text-xs"
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
          >
            <option value="">All platforms</option>
            {ALL_PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_CONFIG[p]?.label ?? p}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[160px]">
          <label className="label">Client</label>
          <select
            className="input text-xs"
            value={clientFilter}
            onChange={(e) => setClientFilter(e.target.value)}
          >
            <option value="">All clients</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.company_name}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[140px]">
          <label className="label">Status</label>
          <select
            className="input text-xs"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            {CALENDAR_STATUSES.map((s) => (
              <option key={s.value || "all"} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Period navigation */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <button type="button" className="btn-secondary py-1" onClick={goPrev}>
            <ChevronLeft size={15} />
          </button>
          <span className="text-sm font-medium min-w-[12rem] text-center">{headerLabel}</span>
          <button type="button" className="btn-secondary py-1" onClick={goNext}>
            <ChevronRight size={15} />
          </button>
        </div>
        <button type="button" className="btn-secondary text-xs" onClick={goToday}>
          Today
        </button>
      </div>

      {isLoading ? (
        <div className="card p-12 animate-pulse text-center text-sm text-gray-400">
          Loading calendar…
        </div>
      ) : view === "day" ? (
        <div className="card p-4">
          {dayItems.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">No posts on this day.</p>
          ) : (
            <div className="space-y-2">
              {dayItems.map((item) => (
                <CalendarEventChip
                  key={item.id}
                  item={item}
                  onClick={() => openItem(item.id)}
                />
              ))}
            </div>
          )}
        </div>
      ) : view === "week" ? (
        <div className="card overflow-hidden">
          <div className="grid grid-cols-7 border-b border-gray-100 bg-gray-50">
            {weekDays.map((d) => (
              <div
                key={d.toISOString()}
                className={cn(
                  "py-2 text-center text-xs font-medium border-r border-gray-100 last:border-r-0",
                  isToday(d) ? "text-brand-700" : "text-gray-400",
                )}
              >
                <div>{format(d, "EEE")}</div>
                <div className={cn("text-sm", isToday(d) && "font-bold")}>{format(d, "d")}</div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 min-h-[280px]">
            {weekDays.map((d) => {
              const key = format(d, "yyyy-MM-dd");
              const dayEvents = itemsByDay.get(key) ?? [];
              return (
                <div
                  key={key}
                  className={cn(
                    "border-r border-gray-100 last:border-r-0 p-1 space-y-1 align-top",
                    isToday(d) && "bg-brand-50/30",
                  )}
                >
                  {dayEvents.map((item) => (
                    <CalendarEventChip
                      key={item.id}
                      item={item}
                      compact
                      onClick={() => openItem(item.id)}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="grid grid-cols-7 border-b border-gray-100 bg-gray-50">
            {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
              <div key={d} className="py-2 text-center text-xs font-medium text-gray-400">
                {d}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7">
            {Array.from({ length: monthStartPad }).map((_, i) => (
              <div key={`pad-${i}`} className="min-h-[88px] border-b border-r border-gray-50 bg-gray-50/50" />
            ))}
            {monthDays.map((d) => {
              const key = format(d, "yyyy-MM-dd");
              const dayEvents = itemsByDay.get(key) ?? [];
              return (
                <div
                  key={key}
                  className={cn(
                    "min-h-[88px] border-b border-r border-gray-100 p-1 space-y-0.5",
                    isToday(d) && "bg-brand-50/40",
                  )}
                >
                  <span
                    className={cn(
                      "text-[10px] font-medium inline-block mb-0.5",
                      isToday(d) ? "text-brand-700" : "text-gray-400",
                    )}
                  >
                    {format(d, "d")}
                  </span>
                  {dayEvents.slice(0, 3).map((item) => (
                    <CalendarEventChip
                      key={item.id}
                      item={item}
                      compact
                      onClick={() => openItem(item.id)}
                    />
                  ))}
                  {dayEvents.length > 3 && (
                    <button
                      type="button"
                      className="text-[9px] text-brand-600 w-full text-left pl-1"
                      onClick={() => {
                        setView("day");
                        setCurrent(d);
                      }}
                    >
                      +{dayEvents.length - 3} more
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mt-4 text-[10px] text-gray-500">
        {(["scheduled", "published", "failed", "partial_failed", "publishing"] as ContentStatus[]).map(
          (s) => {
            const cfg = STATUS_CONFIG[s];
            return (
              <span key={s} className="flex items-center gap-1">
                <span className={cn("w-2 h-2 rounded-full", cfg.dot)} />
                {cfg.label}
              </span>
            );
          },
        )}
      </div>
    </div>
  );
}
