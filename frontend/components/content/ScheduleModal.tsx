"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { contentApi, Platform } from "@/lib/api";
import {
  LOCAL_TIMEZONE_NOTE,
  localDateTimeToUtcIso,
  utcIsoToLocalDate,
  utcIsoToLocalTime,
} from "@/lib/datetime";
import { X, Calendar } from "lucide-react";
import toast from "react-hot-toast";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";

const ALL_PLATFORMS: Platform[] = ["instagram", "facebook", "tiktok", "telegram", "linkedin"];

interface Props {
  contentItemId: string;
  currentPlatforms?: Platform[];
  existingEntryId?: string;
  existingDate?: string;
  existingTime?: string;
  existingScheduledForUtc?: string;
  existingPlatforms?: Platform[];
  onClose: () => void;
  onSaved: () => void;
}

export function ScheduleModal({
  contentItemId,
  currentPlatforms = [],
  existingEntryId,
  existingDate,
  existingTime,
  existingScheduledForUtc,
  existingPlatforms,
  onClose,
  onSaved,
}: Props) {
  const today = new Date().toISOString().split("T")[0];
  const initialDate = existingScheduledForUtc
    ? utcIsoToLocalDate(existingScheduledForUtc)
    : existingDate || today;
  const initialTime = existingScheduledForUtc
    ? utcIsoToLocalTime(existingScheduledForUtc)
    : existingTime || "09:00";

  const [date, setDate] = useState(initialDate);
  const [time, setTime] = useState(initialTime);
  const [note, setNote] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>(
    existingPlatforms || currentPlatforms || []
  );

  const togglePlatform = (p: Platform) => {
    setPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]
    );
  };

  const buildPayload = () => ({
    scheduled_date: date,
    time_slot: time,
    scheduled_for: localDateTimeToUtcIso(date, time),
    platforms,
  });

  const scheduleMutation = useMutation({
    mutationFn: () =>
      contentApi.schedule({
        content_item_id: contentItemId,
        ...buildPayload(),
        note: note || undefined,
      }),
    onSuccess: () => {
      toast.success("Scheduled!");
      onSaved();
    },
    onError: () => toast.error("Failed to schedule"),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      contentApi.updateCalendarEntry(existingEntryId!, buildPayload()),
    onSuccess: () => {
      toast.success("Rescheduled!");
      onSaved();
    },
    onError: () => toast.error("Failed to reschedule"),
  });

  const isReschedule = !!existingEntryId;
  const isPending = scheduleMutation.isPending || updateMutation.isPending;

  const handleSave = () => {
    if (!date) return;
    if (isReschedule) {
      updateMutation.mutate();
    } else {
      scheduleMutation.mutate();
    }
  };

  return (
    <div
      data-app-modal
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
    >
      <div className="card w-full max-w-sm p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-900">
            <Calendar size={16} className="text-brand-600" />
            {isReschedule ? "Reschedule post" : "Schedule post"}
          </div>
          <button onClick={onClose}><X size={18} className="text-gray-400" /></button>
        </div>

        <p className="text-[11px] text-gray-500 mb-4">{LOCAL_TIMEZONE_NOTE}</p>

        <div className="space-y-4">
          <div>
            <label className="label">Date</label>
            <input
              type="date"
              className="input"
              value={date}
              min={today}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>

          <div>
            <label className="label">Time</label>
            <input
              type="time"
              className="input"
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
          </div>

          <div>
            <label className="label">Platforms</label>
            <div className="grid grid-cols-2 gap-2 mt-1">
              {ALL_PLATFORMS.map((p) => {
                const cfg = PLATFORM_CONFIG[p];
                const selected = platforms.includes(p);
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => togglePlatform(p)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-all",
                      selected
                        ? "border-brand-500 bg-brand-50 text-brand-700"
                        : "border-gray-200 text-gray-500 hover:border-gray-300"
                    )}
                  >
                    <span className={cn("text-[10px] font-bold px-1 py-0.5 rounded", cfg.color)}>
                      {cfg.icon}
                    </span>
                    {cfg.label}
                    {selected && <span className="ml-auto text-brand-500">✓</span>}
                  </button>
                );
              })}
            </div>
          </div>

          {!isReschedule && (
            <div>
              <label className="label">Note (optional)</label>
              <input
                className="input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. Morning post"
              />
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            onClick={handleSave}
            disabled={!date || isPending}
          >
            {isPending ? "Saving…" : isReschedule ? "Reschedule" : "Schedule"}
          </button>
        </div>
      </div>
    </div>
  );
}
