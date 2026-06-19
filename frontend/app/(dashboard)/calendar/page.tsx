"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { contentApi, CalendarEntry, Platform } from "@/lib/api";
import { STATUS_CONFIG, PLATFORM_CONFIG, cn } from "@/lib/utils";
import {
  ChevronLeft, ChevronRight, CheckCircle2, RotateCcw,
  CalendarClock, Trash2, MoreVertical, X
} from "lucide-react";
import {
  format, startOfMonth, endOfMonth, eachDayOfInterval,
  getDay, isSameDay, parseISO, addMonths, subMonths, isToday
} from "date-fns";
import toast from "react-hot-toast";
import { ScheduleModal } from "@/components/content/ScheduleModal";
import { CalendarSkeleton } from "@/components/ui/Skeleton";
import { MediaPreview } from "@/components/ui/MediaPreview";

export default function CalendarPage() {
  const qc = useQueryClient();
  const [current, setCurrent] = useState(new Date());
  const [activeEntry, setActiveEntry] = useState<CalendarEntry | null>(null);
  const [reschedulingEntry, setReschedulingEntry] = useState<CalendarEntry | null>(null);

  const year = current.getFullYear();
  const month = current.getMonth() + 1;

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["calendar", year, month],
    queryFn: () => contentApi.getCalendarMonth(year, month).then((r) => r.data),
  });

  const publishMutation = useMutation({
    mutationFn: (entryId: string) => contentApi.markPublished(entryId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar"] });
      qc.invalidateQueries({ queryKey: ["content"] });
      setActiveEntry(null);
      toast.success("Published to selected platforms ✓");
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Publishing failed");
    },
  });

  const draftMutation = useMutation({
    mutationFn: (entryId: string) => contentApi.moveToDraft(entryId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar"] });
      qc.invalidateQueries({ queryKey: ["content"] });
      setActiveEntry(null);
      toast.success("Moved back to Draft");
    },
    onError: () => toast.error("Failed to move to draft"),
  });

  const deleteMutation = useMutation({
    mutationFn: (entryId: string) => contentApi.deleteCalendarEntry(entryId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["calendar"] });
      qc.invalidateQueries({ queryKey: ["content"] });
      setActiveEntry(null);
      toast.success("Schedule deleted");
    },
    onError: () => toast.error("Failed to delete"),
  });

  const days = eachDayOfInterval({ start: startOfMonth(current), end: endOfMonth(current) });
  const startPad = getDay(startOfMonth(current));

  const entriesForDay = (d: Date): CalendarEntry[] =>
    entries.filter((e) => isSameDay(parseISO(e.scheduled_date), d));

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Content Calendar</h1>
          <p className="text-sm text-gray-500 mt-0.5">{entries.length} post{entries.length !== 1 ? "s" : ""} scheduled</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-secondary py-1" onClick={() => setCurrent(subMonths(current, 1))}>
            <ChevronLeft size={15} />
          </button>
          <span className="text-sm font-medium w-36 text-center">{format(current, "MMMM yyyy")}</span>
          <button className="btn-secondary py-1" onClick={() => setCurrent(addMonths(current, 1))}>
            <ChevronRight size={15} />
          </button>
        </div>
      </div>

      {/* Calendar grid */}
      <div className="card overflow-hidden">
        {/* Weekday headers */}
        <div className="grid grid-cols-7 border-b border-gray-100 bg-gray-50">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
            <div key={d} className="py-2 text-center text-xs font-medium text-gray-400">{d}</div>
          ))}
        </div>

        {/* Day grid */}
        {isLoading ? (
          <CalendarSkeleton />
        ) : (
          <div className="grid grid-cols-7">
            {Array.from({ length: startPad }).map((_, i) => (
              <div key={`pad-${i}`} className="min-h-[110px] border-b border-r border-gray-50 bg-gray-50/40" />
            ))}
            {days.map((day) => {
              const dayEntries = entriesForDay(day);
              const today = isToday(day);
              return (
                <div
                  key={day.toISOString()}
                  className={cn(
                    "min-h-[110px] p-1.5 border-b border-r border-gray-50 transition-colors",
                    today && "bg-brand-50/60"
                  )}
                >
                  <span className={cn(
                    "text-xs font-medium inline-flex items-center justify-center w-5 h-5 rounded-full mb-1.5",
                    today ? "bg-brand-600 text-white" : "text-gray-400"
                  )}>
                    {format(day, "d")}
                  </span>
                  <div className="space-y-1">
                    {dayEntries.map((e) => (
                      <CalendarCard
                        key={e.id}
                        entry={e}
                        onClick={() => setActiveEntry(e)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {entries.length === 0 && !isLoading && (
        <p className="text-center text-sm text-gray-400 mt-6">
          No posts scheduled for {format(current, "MMMM yyyy")}. Go to Content and click Schedule on any item.
        </p>
      )}

      {/* Detail panel / action drawer */}
      {activeEntry && (
        <EntryActionPanel
          entry={activeEntry}
          onClose={() => setActiveEntry(null)}
          onPublish={() => publishMutation.mutate(activeEntry.id)}
          onDraft={() => {
            if (confirm("Move this post back to Draft and remove from calendar?")) {
              draftMutation.mutate(activeEntry.id);
            }
          }}
          onReschedule={() => {
            setReschedulingEntry(activeEntry);
            setActiveEntry(null);
          }}
          onDelete={() => {
            if (confirm("Delete this schedule? Content stays but returns to Draft.")) {
              deleteMutation.mutate(activeEntry.id);
            }
          }}
          isPublishing={publishMutation.isPending}
          isDrafting={draftMutation.isPending}
          isDeleting={deleteMutation.isPending}
        />
      )}

      {/* Reschedule modal */}
      {reschedulingEntry && (
        <ScheduleModal
          contentItemId={reschedulingEntry.content_item_id}
          existingEntryId={reschedulingEntry.id}
          existingDate={reschedulingEntry.scheduled_date}
          existingTime={reschedulingEntry.time_slot}
          existingPlatforms={reschedulingEntry.platforms as Platform[]}
          onClose={() => setReschedulingEntry(null)}
          onSaved={() => {
            setReschedulingEntry(null);
            qc.invalidateQueries({ queryKey: ["calendar"] });
            qc.invalidateQueries({ queryKey: ["content"] });
          }}
        />
      )}
    </div>
  );
}

// ── Small calendar chip ──────────────────────────────────────────────────────

function CalendarCard({ entry, onClick }: { entry: CalendarEntry; onClick: () => void }) {
  const status = entry.content_item?.status ?? "scheduled";
  const statusCfg = STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.scheduled;
  const caption =
    entry.content_item?.caption_short_ru ||
    entry.content_item?.caption_short_en ||
    entry.content_item?.caption_short_uz ||
    entry.note ||
    "Post";

  return (
    <button
      onClick={onClick}
      className="w-full text-left group"
    >
      <div className={cn(
        "rounded-md px-1.5 py-1 text-[10px] leading-snug border transition-all",
        "hover:shadow-sm hover:-translate-y-px",
        statusCfg.color
      )}>
        {/* Time + client */}
        <div className="flex items-center justify-between gap-1 mb-0.5">
          {entry.time_slot && (
            <span className="font-bold">{entry.time_slot}</span>
          )}
          <span className="truncate text-[9px] opacity-70">
            {entry.client?.company_name ?? ""}
          </span>
          <MoreVertical size={9} className="shrink-0 opacity-40 group-hover:opacity-80" />
        </div>
        {/* Thumbnail + caption */}
        <div className="flex items-start gap-1">
          {entry.content_item?.media_url && (
            <div className="w-7 h-7 rounded overflow-hidden shrink-0 bg-gray-100">
              <MediaPreview
                url={entry.content_item.media_url}
                muted
                iconSize={10}
              />
            </div>
          )}
          <span className="truncate opacity-80">{caption}</span>
        </div>
        {/* Platforms */}
        {entry.platforms?.length > 0 && (
          <div className="flex gap-0.5 mt-0.5 flex-wrap">
            {entry.platforms.map((p) => (
              <span key={p} className={cn(
                "text-[8px] font-bold px-0.5 rounded",
                PLATFORM_CONFIG[p]?.color
              )}>
                {PLATFORM_CONFIG[p]?.icon ?? p}
              </span>
            ))}
          </div>
        )}
      </div>
    </button>
  );
}

// ── Action panel (slide-in from right) ──────────────────────────────────────

function EntryActionPanel({
  entry, onClose, onPublish, onDraft, onReschedule, onDelete,
  isPublishing, isDrafting, isDeleting,
}: {
  entry: CalendarEntry;
  onClose: () => void;
  onPublish: () => void;
  onDraft: () => void;
  onReschedule: () => void;
  onDelete: () => void;
  isPublishing: boolean;
  isDrafting: boolean;
  isDeleting: boolean;
}) {
  const status = entry.content_item?.status ?? "scheduled";
  const statusCfg = STATUS_CONFIG[status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.scheduled;
  const caption =
    entry.content_item?.caption_short_ru ||
    entry.content_item?.caption_short_en ||
    entry.note ||
    "Post";

  return (
    <>
      {/* Backdrop */}
      <div
        data-app-modal
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Panel */}
      <div className="fixed right-0 top-0 bottom-0 z-50 w-80 bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Scheduled Post</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Media — always shown; placeholder if no media or broken URL */}
          <div className="h-40 rounded-xl overflow-hidden">
            <MediaPreview
              url={entry.content_item?.media_url}
              controls
              muted={false}
              iconSize={32}
              className="rounded-xl"
            />
          </div>

          {/* Client */}
          {entry.client && (
            <div>
              <p className="text-[10px] text-gray-400 uppercase font-medium tracking-wide">Client</p>
              <p className="text-sm font-medium text-gray-800 mt-0.5">{entry.client.company_name}</p>
            </div>
          )}

          {/* Date & time */}
          <div>
            <p className="text-[10px] text-gray-400 uppercase font-medium tracking-wide">Scheduled</p>
            <p className="text-sm font-medium text-gray-800 mt-0.5">
              {format(parseISO(entry.scheduled_date), "EEEE, MMMM d, yyyy")}
              {entry.time_slot && <span className="text-brand-600 ml-1">at {entry.time_slot}</span>}
            </p>
          </div>

          {/* Status */}
          <div>
            <p className="text-[10px] text-gray-400 uppercase font-medium tracking-wide">Status</p>
            <span className={cn("status-badge mt-1 inline-flex", statusCfg.color)}>
              <span className={cn("w-1.5 h-1.5 rounded-full", statusCfg.dot)} />
              {statusCfg.label}
            </span>
          </div>

          {/* Platforms */}
          {entry.platforms?.length > 0 && (
            <div>
              <p className="text-[10px] text-gray-400 uppercase font-medium tracking-wide mb-1.5">Platforms</p>
              <div className="flex flex-wrap gap-1.5">
                {entry.platforms.map((p) => (
                  <span key={p} className={cn(
                    "text-xs px-2 py-0.5 rounded-full font-medium",
                    PLATFORM_CONFIG[p]?.color
                  )}>
                    {PLATFORM_CONFIG[p]?.label ?? p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Caption */}
          {caption && (
            <div>
              <p className="text-[10px] text-gray-400 uppercase font-medium tracking-wide">Caption</p>
              <p className="text-xs text-gray-600 mt-1 leading-relaxed line-clamp-4">{caption}</p>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="border-t border-gray-100 p-4 space-y-2">
          {status !== "published" && status !== "publishing" && (
            <button
              onClick={onPublish}
              disabled={isPublishing}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 transition-colors disabled:opacity-60"
            >
              <CheckCircle2 size={15} />
              {isPublishing ? "Publishing…" : "Publish now"}
            </button>
          )}
          <button
            onClick={onReschedule}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-purple-200 text-purple-700 bg-purple-50 text-sm font-medium hover:bg-purple-100 transition-colors"
          >
            <CalendarClock size={15} />
            Reschedule
          </button>
          <button
            onClick={onDraft}
            disabled={isDrafting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-gray-200 text-gray-600 text-sm font-medium hover:bg-gray-50 transition-colors disabled:opacity-60"
          >
            <RotateCcw size={15} />
            {isDrafting ? "Moving…" : "Move back to Draft"}
          </button>
          <button
            onClick={onDelete}
            disabled={isDeleting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-red-200 text-red-600 text-sm font-medium hover:bg-red-50 transition-colors disabled:opacity-60"
          >
            <Trash2 size={15} />
            {isDeleting ? "Deleting…" : "Delete Schedule"}
          </button>
        </div>
      </div>
    </>
  );
}
