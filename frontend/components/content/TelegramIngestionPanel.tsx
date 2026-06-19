"use client";

import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { ContentItem, ContentStatus, contentFactoryApi } from "@/lib/api";
import { STATUS_CONFIG, cn } from "@/lib/utils";
import { AlertTriangle, Factory, Sparkles, Tag } from "lucide-react";

const CLASSIFICATION_LABELS: Record<string, string> = {
  product: "Product",
  factory: "Factory",
  production_process: "Production Process",
  promotion: "Promotion",
  customer_review: "Customer Review",
  company_news: "Company News",
  exhibition_event: "Exhibition / Event",
  educational_content: "Educational Content",
  other: "Other",
};

const EDITABLE_STATUSES: ContentStatus[] = [
  "new",
  "needs_review",
  "needs_caption",
  "ready",
  "rejected",
  "draft",
  "ready_for_approval",
  "approved",
  "scheduled",
  "published",
];

interface Props {
  item: ContentItem;
  onStatusChange: (status: ContentStatus) => void;
  statusSaving?: boolean;
}

export function TelegramIngestionPanel({ item, onStatusChange, statusSaving }: Props) {
  const isTelegramSource =
    item.source_badge === "Telegram" ||
    item.source === "telegram" ||
    item.source === "telegram_group" ||
    item.source === "tg_group_buffer";

  const factoryMutation = useMutation({
    mutationFn: () => contentFactoryApi.fromTelegram(item.id, { number_of_variations: 3 }).then((r) => r.data),
    onSuccess: (factory) => {
      toast.success(`Content Factory: ${factory.items.length} variations ready for review`);
    },
    onError: (err: Error) => toast.error(err.message || "Content Factory failed"),
  });

  if (!isTelegramSource && !item.content_classification && !item.quality_warnings?.length) {
    return null;
  }

  const suggestions = item.suggestions;
  const warnings = item.quality_warnings ?? [];
  const statusCfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.draft;

  return (
    <div className="card p-5 space-y-4 border-sky-100 bg-sky-50/30">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Tag size={15} className="text-sky-600" />
            Telegram ingestion
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Source: {item.source_badge ?? "Telegram"}
            {item.telegram_group_title ? ` · ${item.telegram_group_title}` : ""}
          </p>
        </div>
        <span className={cn("status-badge text-[10px]", statusCfg.color)}>
          <span className={cn("w-1.5 h-1.5 rounded-full", statusCfg.dot)} />
          {statusCfg.label}
        </span>
      </div>

      <div>
        <label className="text-xs font-medium text-gray-600">Workflow status</label>
        <select
          className="input mt-1 w-full text-sm"
          value={item.status}
          disabled={statusSaving}
          onChange={(e) => onStatusChange(e.target.value as ContentStatus)}
        >
          {EDITABLE_STATUSES.map((s) => (
            <option key={s} value={s}>{STATUS_CONFIG[s]?.label ?? s}</option>
          ))}
        </select>
      </div>

      {item.telegram_original_caption && (
        <div>
          <p className="text-xs font-medium text-gray-600 mb-1">Original Telegram caption</p>
          <p className="text-sm text-gray-800 whitespace-pre-wrap bg-white rounded-lg border border-gray-100 p-3">
            {item.telegram_original_caption}
          </p>
        </div>
      )}

      {item.telegram_forward_from && (
        <p className="text-xs text-violet-700">↪ {item.telegram_forward_from}</p>
      )}

      {item.content_classification && (
        <p className="text-sm">
          <span className="text-gray-500 text-xs">Classification: </span>
          <span className="font-medium text-gray-800">
            {CLASSIFICATION_LABELS[item.content_classification] ?? item.content_classification}
          </span>
        </p>
      )}

      {item.campaign_id && (
        <p className="text-xs text-gray-600">
          Linked campaign:{" "}
          <a href={`/campaigns/${item.campaign_id}`} className="text-brand-600 hover:underline">
            Open campaign
          </a>
        </p>
      )}

      {suggestions && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-gray-600 flex items-center gap-1">
            <Sparkles size={12} /> Suggested enrichment
          </p>
          {suggestions.target_platforms && suggestions.target_platforms.length > 0 && (
            <p className="text-xs text-gray-600">
              Suggested platforms: {suggestions.target_platforms.join(", ")}
            </p>
          )}
          {suggestions.title && (
            <p className="text-sm"><span className="text-gray-500">Title:</span> {suggestions.title}</p>
          )}
          {suggestions.short_description && (
            <p className="text-sm text-gray-700">{suggestions.short_description}</p>
          )}
          {suggestions.hashtags && (
            <p className="text-xs text-sky-800 bg-sky-50 rounded px-2 py-1">{suggestions.hashtags}</p>
          )}
          {suggestions.cta && (
            <p className="text-xs text-gray-600">CTA: {suggestions.cta}</p>
          )}
          {suggestions.captions && (
            <div className="grid gap-2 sm:grid-cols-2">
              {(["ru", "uz", "en", "zh"] as const).map((lang) =>
                suggestions.captions?.[lang] ? (
                  <div key={lang} className="text-xs bg-white border rounded p-2">
                    <span className="uppercase font-medium text-gray-400">{lang}</span>
                    <p className="mt-1 text-gray-700 line-clamp-4">{suggestions.captions[lang]}</p>
                  </div>
                ) : null,
              )}
            </div>
          )}
        </div>
      )}

      {isTelegramSource && item.media_file_id && (
        <div className="flex flex-wrap gap-2 pt-1">
          <button
            type="button"
            className="btn-primary text-xs py-1.5 flex items-center gap-1"
            disabled={factoryMutation.isPending}
            onClick={() => factoryMutation.mutate()}
          >
            <Factory size={12} />
            {factoryMutation.isPending ? "Generating…" : "Send to Content Factory"}
          </button>
          <Link href="/content-factory/review" className="btn-secondary text-xs py-1.5">
            Review queue
          </Link>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-medium text-amber-900 flex items-center gap-1 mb-2">
            <AlertTriangle size={13} /> Quality warnings
          </p>
          <ul className="text-xs text-amber-900 space-y-1">
            {warnings.map((w) => (
              <li key={w.id}>• {w.message}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
