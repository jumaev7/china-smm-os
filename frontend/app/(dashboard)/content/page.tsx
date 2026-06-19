"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { contentApi, clientsApi, Client, normalizeList, ContentItem } from "@/lib/api";
import { STATUS_CONFIG, PLATFORM_CONFIG, cn } from "@/lib/utils";
import { formatScheduledLocal, LOCAL_TIMEZONE_NOTE } from "@/lib/datetime";
import { Plus, CheckCheck, Trash2, Sparkles, Eye, CalendarPlus } from "lucide-react";
import toast from "react-hot-toast";
import Link from "next/link";
import { NewContentModal } from "@/components/content/NewContentModal";
import { ScheduleModal } from "@/components/content/ScheduleModal";
import { GenerateModal } from "@/components/content/GenerateModal";
import { ContentGridSkeleton } from "@/components/ui/Skeleton";
import { ClientReviewStatusBadge } from "@/components/content/ClientReviewStatus";
import { MediaPreview } from "@/components/ui/MediaPreview";
import { EmptyState, ErrorState } from "@/components/ui/PageStates";

const FILTERS = [
  { label: "All", value: "" },
  { label: "🆕 Needs Review", value: "needs_review" },
  { label: "✏️ Needs Caption", value: "needs_caption" },
  { label: "🟡 Draft", value: "draft" },
  { label: "🟢 Ready", value: "ready" },
  { label: "🔵 Approved", value: "approved" },
  { label: "🟣 Scheduled", value: "scheduled" },
  { label: "✅ Published", value: "published" },
  { label: "🔴 Failed", value: "failed" },
  { label: "📩 Telegram", value: "telegram" },
  { label: "👥 Telegram Group", value: "telegram_group" },
];

export default function ContentPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");   // "telegram" | ""
  const [clientFilter, setClientFilter] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [schedulingItemId, setSchedulingItemId] = useState<string | null>(null);
  const [schedulingItem, setSchedulingItem] = useState<ContentItem | null>(null);
  const [generatingItem, setGeneratingItem] = useState<ContentItem | null>(null);

  // Toggle a filter button — Telegram is a source filter, others are status filters
  const handleFilter = (value: string) => {
    if (value === "telegram" || value === "telegram_group") {
      setSourceFilter((prev) => (prev === value ? "" : value));
      setStatusFilter("");
    } else {
      setStatusFilter((prev) => (prev === value ? "" : value));
      setSourceFilter("");
    }
  };

  const activeFilter = sourceFilter === "telegram" || sourceFilter === "telegram_group"
    ? sourceFilter
    : statusFilter;

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["content", statusFilter, sourceFilter, clientFilter],
    queryFn: () =>
      contentApi.list({
        status: statusFilter || undefined,
        source: sourceFilter || undefined,
        client_id: clientFilter || undefined,
        limit: 100,
      }).then((r) => r.data),
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => contentApi.approve(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["content"] }); toast.success("Approved ✓"); },
    onError: () => toast.error("Failed to approve"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => contentApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["content"] }); toast.success("Deleted"); },
    onError: () => toast.error("Failed to delete"),
  });

  const items = normalizeList<ContentItem>(data);
  const clientMap = Object.fromEntries(clientOptions.map((c) => [c.id, c]));

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Content</h1>
          <p className="text-sm text-gray-500 mt-0.5">{data?.total ?? 0} items</p>
        </div>
        <button className="btn-primary" onClick={() => setShowNew(true)}>
          <Plus size={15} /> New content
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <div className="flex rounded-lg border border-gray-200 overflow-hidden bg-white flex-wrap">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => handleFilter(f.value)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium transition-colors",
                activeFilter === f.value
                  ? "bg-brand-600 text-white"
                  : "text-gray-600 hover:bg-gray-50"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <select
          className="input w-auto text-xs"
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
        >
          <option value="">All clients</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
      </div>

      {/* Content grid */}
      {isLoading ? (
        <ContentGridSkeleton />
      ) : isError ? (
        <ErrorState
          error={error}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="No content yet"
          description="Create your first content item or adjust filters."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) => (
            <ContentCard
              key={item.id}
              item={item}
              clientName={clientMap[item.client_id]?.company_name}
              onApprove={() => approveMutation.mutate(item.id)}
              onDelete={() => { if (confirm("Delete this content?")) deleteMutation.mutate(item.id); }}
              onSchedule={() => { setSchedulingItemId(item.id); setSchedulingItem(item); }}
              onGenerate={() => setGeneratingItem(item)}
            />
          ))}
        </div>
      )}

      {showNew && (
        <NewContentModal
          clients={clientOptions}
          onClose={() => setShowNew(false)}
          onSaved={() => { setShowNew(false); qc.invalidateQueries({ queryKey: ["content"] }); }}
        />
      )}

      {schedulingItemId && schedulingItem && (
        <ScheduleModal
          contentItemId={schedulingItemId}
          currentPlatforms={schedulingItem.platforms}
          onClose={() => { setSchedulingItemId(null); setSchedulingItem(null); }}
          onSaved={() => {
            setSchedulingItemId(null);
            setSchedulingItem(null);
            qc.invalidateQueries({ queryKey: ["content"] });
            qc.invalidateQueries({ queryKey: ["calendar"] });
          }}
        />
      )}

      {generatingItem && clientMap[generatingItem.client_id] && (
        <GenerateModal
          contentItem={generatingItem}
          client={clientMap[generatingItem.client_id]!}
          onClose={() => setGeneratingItem(null)}
          onGenerated={(updated) => {
            setGeneratingItem(null);
            qc.invalidateQueries({ queryKey: ["content"] });
            toast.success(`Captions ready for ${clientMap[updated.client_id]?.company_name ?? "content"}`);
          }}
        />
      )}
    </div>
  );
}

function ContentCard({
  item, clientName, onApprove, onDelete, onSchedule, onGenerate,
}: {
  item: ContentItem;
  clientName?: string;
  onApprove: () => void;
  onDelete: () => void;
  onSchedule: () => void;
  onGenerate: () => void;
}) {
  const statusCfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.draft;
  const hasCaption = item.caption_short_ru || item.caption_short_en || item.caption_short_uz;
  const canSchedule = ["draft", "ready", "approved", "failed", "needs_review", "needs_caption", "new"].includes(item.status);
  const canApprove = ["draft", "ready", "needs_review", "needs_caption", "new"].includes(item.status);

  return (
    <div className="card p-4 flex flex-col gap-3">
      {/* Media preview — always shown; placeholder if no media or broken URL */}
      <div className="h-36 rounded-lg overflow-hidden bg-gray-100 relative">
        <MediaPreview
          url={item.media_url}
          fileType={item.media_file_type}
          muted
          className="rounded-lg"
          iconSize={28}
        />
      </div>

      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            {item.source === "telegram" && (
              <span className="text-[10px] bg-sky-100 text-sky-700 px-1.5 py-0.5 rounded font-medium shrink-0">
                📩 Telegram
              </span>
            )}
            {item.source === "telegram_group" && (
              <span className="text-[10px] bg-violet-100 text-violet-700 px-1.5 py-0.5 rounded font-medium shrink-0">
                👥 Telegram Group
              </span>
            )}
            <p className="text-xs text-gray-400 truncate">{clientName ?? "Unknown client"}</p>
          </div>
          {item.source === "telegram_group" && item.telegram_group_title && (
            <p className="text-[10px] text-violet-700 truncate">{item.telegram_group_title}</p>
          )}
          <div className="flex flex-wrap gap-1 mt-1">
            {item.platforms.map((p) => (
              <span key={p} className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", PLATFORM_CONFIG[p]?.color)}>
                {PLATFORM_CONFIG[p]?.label ?? p}
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className={cn("status-badge", statusCfg.color)}>
            <span className={cn("w-1.5 h-1.5 rounded-full", statusCfg.dot)} />
            {statusCfg.label}
          </span>
          {item.client_review_status && (
            <ClientReviewStatusBadge item={item} compact />
          )}
        </div>
      </div>

      {/* Scheduled time — only while waiting for auto-publish */}
      {item.status === "scheduled" && item.scheduled_for && (
        <p className="text-[10px] text-purple-600 font-medium" title={LOCAL_TIMEZONE_NOTE}>
          📅 {formatScheduledLocal(item.scheduled_for, {
            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
          })}
        </p>
      )}

      {/* Caption preview or generate prompt */}
      {hasCaption ? (
        <p className="text-xs text-gray-600 line-clamp-2 leading-relaxed">
          {item.caption_short_ru || item.caption_short_en || item.caption_short_uz}
        </p>
      ) : (item.source === "telegram" || item.source === "telegram_group") && item.internal_notes ? (
        <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed italic">
          &ldquo;{item.internal_notes}&rdquo;
        </p>
      ) : (
        <button
          onClick={onGenerate}
          className="flex items-center gap-1.5 text-xs text-brand-600 hover:text-brand-800 transition-colors font-medium"
        >
          <Sparkles size={12} />
          Generate captions with AI
        </button>
      )}

      {/* Hashtags */}
      {item.hashtags && (
        <p className="text-[10px] text-brand-600 line-clamp-1">{item.hashtags}</p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-1.5 mt-auto pt-1 border-t border-gray-50 flex-wrap">
        <Link
          href={`/content/${item.id}`}
          className="btn-secondary text-xs py-1 flex-1 justify-center min-w-0"
        >
          <Eye size={13} /> View
        </Link>
        <button
          onClick={onGenerate}
          title="Generate AI captions"
          className="p-1.5 text-brand-400 hover:text-brand-600 hover:bg-brand-50 rounded transition-colors border border-brand-100"
        >
          <Sparkles size={14} />
        </button>
        {canApprove && (
          <button
            onClick={onApprove}
            className="btn-primary text-xs py-1 flex-1 justify-center min-w-0"
          >
            <CheckCheck size={13} /> Approve
          </button>
        )}
        {canSchedule && (
          <button
            onClick={onSchedule}
            className="text-xs py-1 px-2 flex items-center gap-1 text-purple-600 hover:bg-purple-50 rounded-lg border border-purple-200 transition-colors font-medium"
          >
            <CalendarPlus size={13} /> Schedule
          </button>
        )}
        <button
          onClick={onDelete}
          className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}
