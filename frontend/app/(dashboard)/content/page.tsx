"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { contentApi, clientsApi, Client, normalizeList, ContentItem, tenantOnboardingApi } from "@/lib/api";
import { STATUS_CONFIG, PLATFORM_CONFIG, cn } from "@/lib/utils";
import { formatScheduledLocal, LOCAL_TIMEZONE_NOTE } from "@/lib/datetime";
import { Plus, CheckCheck, Trash2, Sparkles, Eye, CalendarPlus, FileText, Filter } from "lucide-react";
import toast from "react-hot-toast";
import Link from "next/link";
import { NewContentModal } from "@/components/content/NewContentModal";
import { ScheduleModal } from "@/components/content/ScheduleModal";
import { GenerateModal } from "@/components/content/GenerateModal";
import { ContentGridSkeleton } from "@/components/ui/Skeleton";
import { ClientReviewStatusBadge } from "@/components/content/ClientReviewStatus";
import { MediaPreview } from "@/components/ui/MediaPreview";
import { EmptyState, ErrorState } from "@/components/ui/PageStates";
import {
  ActionBar,
  FilterBar,
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";

const FILTERS = [
  { label: "All", value: "" },
  { label: "Needs Review", value: "needs_review" },
  { label: "Needs Caption", value: "needs_caption" },
  { label: "Draft", value: "draft" },
  { label: "Ready", value: "ready" },
  { label: "Approved", value: "approved" },
  { label: "Scheduled", value: "scheduled" },
  { label: "Published", value: "published" },
  { label: "Failed", value: "failed" },
  { label: "Telegram", value: "telegram" },
  { label: "Telegram Group", value: "telegram_group" },
];

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  published: "success",
  approved: "success",
  ready: "success",
  scheduled: "info",
  draft: "neutral",
  needs_review: "warning",
  needs_caption: "warning",
  failed: "danger",
  new: "info",
};

export default function ContentPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [schedulingItemId, setSchedulingItemId] = useState<string | null>(null);
  const [schedulingItem, setSchedulingItem] = useState<ContentItem | null>(null);
  const [generatingItem, setGeneratingItem] = useState<ContentItem | null>(null);

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

  const { data: channelStatus } = useQuery({
    queryKey: ["onboarding-channels-content"],
    queryFn: () => tenantOnboardingApi.channelStatus().then((r) => r.data),
  });
  const telegramConnected = Boolean(
    (channelStatus?.telegram as { connected?: boolean } | undefined)?.connected,
  );

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
    <PageShell>
      <PageHeader
        title="Content Studio"
        subtitle={`${data?.total ?? 0} items in your library`}
        icon={FileText}
        iconClassName="text-violet-400"
        actions={
          <button className="btn-primary" onClick={() => setShowNew(true)}>
            <Plus size={15} /> New content
          </button>
        }
      />

      <ActionBar>
        <Filter size={14} className="text-slate-400 shrink-0" />
        <FilterBar options={FILTERS} value={activeFilter} onChange={handleFilter} />
        <select
          className="input w-auto text-xs min-w-[140px]"
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
        >
          <option value="">All clients</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
      </ActionBar>

      {isLoading ? (
        <ContentGridSkeleton />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          title={activeFilter ? "No matching content" : "No content yet"}
          description={
            activeFilter
              ? "Try a different filter or create content manually."
              : telegramConnected
                ? "Post a photo or video to your linked Telegram group — it will appear here. You can also create content manually."
                : "Connect your Telegram group first (Onboarding → Channels), then post media to the group or upload manually."
          }
          action={
            <div className="flex flex-wrap gap-2 justify-center mt-2">
              {!telegramConnected && (
                <Link href="/onboarding/channels" className="btn-primary text-sm">
                  Connect Telegram
                </Link>
              )}
              <button className="btn-secondary text-sm" onClick={() => setShowNew(true)}>
                <Plus size={14} /> Create manually
              </button>
            </div>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) => (
            <ContentCard
              key={item.id}
              item={item}
              clientName={clientMap[item.client_id]?.company_name}
              onApprove={() => approveMutation.mutate(item.id)}
              onDelete={() => { if (confirm("Delete this content?")) deleteMutation.mutate(item.id); }}
              onSchedule={() => { setSchedulingItemId(item.id); setSchedulingItem(item); }}
              onGenerate={() => {
                if (!clientMap[item.client_id]) {
                  toast.error("Client profile missing — refresh or check client settings");
                  return;
                }
                setGeneratingItem(item);
              }}
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
    </PageShell>
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
  const statusVariant = STATUS_VARIANT[item.status] ?? "neutral";

  return (
    <div className="card-premium p-0 flex flex-col overflow-hidden group transition-all duration-200 hover:border-violet-500/20 dark-tenant:hover:shadow-glow">
      <div className="h-40 overflow-hidden bg-gray-100 dark-tenant:bg-surface-dark-elevated relative">
        <MediaPreview
          url={item.media_url}
          fileType={item.media_file_type}
          muted
          className="rounded-none h-full w-full object-cover"
          iconSize={28}
        />
        <div className="absolute top-2.5 right-2.5">
          <StatusBadge variant={statusVariant} dot className="backdrop-blur-sm bg-white/90 dark-tenant:bg-surface-dark-card/90">
            {statusCfg.label}
          </StatusBadge>
        </div>
      </div>

      <div className="p-4 flex flex-col gap-3 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              {item.source === "telegram" && (
                <span className="text-[10px] bg-sky-500/15 text-sky-400 px-1.5 py-0.5 rounded-md font-medium shrink-0 border border-sky-500/20">
                  Telegram
                </span>
              )}
              {item.source === "telegram_group" && (
                <span className="text-[10px] bg-violet-500/15 text-violet-400 px-1.5 py-0.5 rounded-md font-medium shrink-0 border border-violet-500/20">
                  Telegram Group
                </span>
              )}
              <p className="text-xs text-gray-400 dark-tenant:text-slate-500 truncate">{clientName ?? "Unknown client"}</p>
            </div>
            {item.source === "telegram_group" && item.telegram_group_title && (
              <p className="text-[10px] text-violet-400 truncate mt-0.5">{item.telegram_group_title}</p>
            )}
            <div className="flex flex-wrap gap-1 mt-2">
              {item.platforms.map((p) => (
                <span key={p} className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded-md font-medium border border-transparent",
                  PLATFORM_CONFIG[p]?.color,
                  "dark-tenant:bg-white/[0.04] dark-tenant:text-slate-300 dark-tenant:border-white/[0.06]",
                )}>
                  {PLATFORM_CONFIG[p]?.label ?? p}
                </span>
              ))}
            </div>
          </div>
          {item.client_review_status && (
            <ClientReviewStatusBadge item={item} compact />
          )}
        </div>

        {item.status === "scheduled" && item.scheduled_for && (
          <p className="text-[10px] text-violet-400 font-medium flex items-center gap-1" title={LOCAL_TIMEZONE_NOTE}>
            <CalendarPlus size={10} />
            {formatScheduledLocal(item.scheduled_for, {
              month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
            })}
          </p>
        )}

        {hasCaption ? (
          <p className="text-xs text-gray-600 dark-tenant:text-slate-400 line-clamp-2 leading-relaxed">
            {item.caption_short_ru || item.caption_short_en || item.caption_short_uz}
          </p>
        ) : (item.source === "telegram" || item.source === "telegram_group") && item.internal_notes ? (
          <p className="text-xs text-gray-500 dark-tenant:text-slate-500 line-clamp-2 leading-relaxed italic">
            &ldquo;{item.internal_notes}&rdquo;
          </p>
        ) : (
          <button
            onClick={onGenerate}
            className="flex items-center gap-1.5 text-xs text-violet-500 hover:text-violet-400 transition-colors font-medium"
          >
            <Sparkles size={12} />
            Generate captions with AI
          </button>
        )}

        {item.hashtags && (
          <p className="text-[10px] text-violet-400/80 line-clamp-1">{item.hashtags}</p>
        )}

        <div className="flex items-center gap-1.5 mt-auto pt-3 border-t border-gray-100 dark-tenant:border-white/[0.06] flex-wrap">
          <Link
            href={`/content/${item.id}`}
            className="btn-secondary text-xs py-1.5 flex-1 justify-center min-w-0"
          >
            <Eye size={13} /> View
          </Link>
          <button
            onClick={onGenerate}
            title="Generate AI captions"
            className="p-1.5 text-violet-400 hover:text-violet-300 hover:bg-violet-500/10 rounded-lg transition-colors border border-violet-500/20"
          >
            <Sparkles size={14} />
          </button>
          {canApprove && (
            <button
              onClick={onApprove}
              className="btn-primary text-xs py-1.5 flex-1 justify-center min-w-0"
            >
              <CheckCheck size={13} /> Approve
            </button>
          )}
          {canSchedule && (
            <button
              onClick={onSchedule}
              className="text-xs py-1.5 px-2 flex items-center gap-1 text-violet-400 hover:bg-violet-500/10 rounded-lg border border-violet-500/25 transition-colors font-medium"
            >
              <CalendarPlus size={13} /> Schedule
            </button>
          )}
          <button
            onClick={onDelete}
            className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
