"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Save } from "lucide-react";
import toast from "react-hot-toast";
import { ContentStatus, telegramApi, TelegramIngestionSettings } from "@/lib/api";
import { STATUS_CONFIG } from "@/lib/utils";

const STATUS_OPTIONS: ContentStatus[] = [
  "needs_review",
  "needs_caption",
  "new",
  "draft",
  "ready",
  "rejected",
];

export function TelegramIngestionSettingsPanel() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["telegram-ingestion-settings"],
    queryFn: () => telegramApi.getIngestionSettings().then((r) => r.data),
  });

  const mutation = useMutation({
    mutationFn: (payload: Partial<TelegramIngestionSettings>) =>
      telegramApi.updateIngestionSettings(payload).then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["telegram-ingestion-settings"], res);
      toast.success("Telegram ingestion settings saved");
    },
    onError: () => toast.error("Failed to save settings"),
  });

  if (isLoading || !data) {
    return (
      <div className="card p-5 flex items-center gap-2 text-sm text-gray-500">
        <Loader2 size={16} className="animate-spin" /> Loading Telegram settings…
      </div>
    );
  }

  const save = (patch: Partial<TelegramIngestionSettings>) => mutation.mutate(patch);

  return (
    <div className="card p-5">
      <h2 className="text-sm font-semibold text-gray-800 mb-1 flex items-center gap-2">
        <Bot size={16} className="text-sky-600" />
        Telegram ingestion
      </h2>
      <p className="text-xs text-gray-500 mb-4">
        Group content intake, classification, enrichment, and quality checks.
        {!data.env_bot_configured && (
          <span className="block text-amber-700 mt-1">TELEGRAM_BOT_TOKEN is not configured in backend env.</span>
        )}
      </p>

      <div className="space-y-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={data.enabled}
            onChange={(e) => save({ enabled: e.target.checked })}
          />
          Enable Telegram ingestion
        </label>

        <div>
          <label className="text-xs font-medium text-gray-600">Allowed group IDs (comma-separated, empty = all)</label>
          <input
            className="input mt-1 w-full text-sm"
            defaultValue={(data.allowed_group_ids ?? []).join(", ")}
            onBlur={(e) =>
              save({
                allowed_group_ids: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">Default content status</label>
          <select
            className="input mt-1 w-full text-sm"
            value={data.default_status}
            onChange={(e) => save({ default_status: e.target.value as ContentStatus })}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{STATUS_CONFIG[s]?.label ?? s}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">Default target languages</label>
          <input
            className="input mt-1 w-full text-sm"
            defaultValue={(data.default_target_languages ?? []).join(", ")}
            onBlur={(e) =>
              save({
                default_target_languages: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={data.auto_classification}
            onChange={(e) => save({ auto_classification: e.target.checked })}
          />
          Auto-classification on ingest
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={data.auto_enrichment}
            onChange={(e) => save({ auto_enrichment: e.target.checked })}
          />
          Auto-enrichment on ingest
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={data.quality_checks_enabled}
            onChange={(e) => save({ quality_checks_enabled: e.target.checked })}
          />
          Quality checks on ingest
        </label>

        {mutation.isPending && (
          <p className="text-xs text-gray-400 flex items-center gap-1">
            <Save size={12} /> Saving…
          </p>
        )}
      </div>
    </div>
  );
}
