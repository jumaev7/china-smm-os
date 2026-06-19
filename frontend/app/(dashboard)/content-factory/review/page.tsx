"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calendar, Check, X, ExternalLink } from "lucide-react";
import toast from "react-hot-toast";
import { useState } from "react";
import {
  clientsApi,
  contentFactoryApi,
  Client,
  ContentFactoryItem,
  FactoryReviewStatus,
  normalizeList,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { ContentFactoryHeader, ContentFactorySubNav } from "@/components/content-factory/ContentFactorySubNav";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_TABS: { value: FactoryReviewStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "generated", label: "Generated" },
  { value: "needs_review", label: "Needs review" },
  { value: "approved", label: "Approved" },
  { value: "scheduled", label: "Scheduled" },
  { value: "published", label: "Published" },
  { value: "rejected", label: "Rejected" },
];

const STATUS_STYLE: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700 border-gray-200",
  generated: "bg-indigo-50 text-indigo-800 border-indigo-200",
  needs_review: "bg-amber-50 text-amber-800 border-amber-200",
  approved: "bg-emerald-50 text-emerald-800 border-emerald-200",
  scheduled: "bg-sky-50 text-sky-800 border-sky-200",
  published: "bg-teal-50 text-teal-800 border-teal-200",
  rejected: "bg-red-50 text-red-800 border-red-200",
};

function ReviewCard({
  item,
  onApprove,
  onReject,
  onSchedule,
  busy,
}: {
  item: ContentFactoryItem & { company_name?: string | null; source_media_url?: string | null };
  onApprove: () => void;
  onReject: () => void;
  onSchedule: () => void;
  busy: boolean;
}) {
  const scores = item.quality_scores;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-gray-900">{item.title}</p>
          {item.headline && <p className="text-sm text-teal-700">{item.headline}</p>}
          <p className="text-xs text-gray-500 mt-1">{item.theme} · {item.content_type}</p>
        </div>
        <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0", STATUS_STYLE[item.review_status ?? "generated"])}>
          {(item.review_status ?? "generated").replace("_", " ")}
        </span>
      </div>

      {item.source_media_url && (
        <div className="rounded-lg overflow-hidden bg-gray-100 max-h-32">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={item.source_media_url} alt="" className="w-full h-full object-cover max-h-32" />
        </div>
      )}

      {item.preview_caption && (
        <p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-2 line-clamp-3">{item.preview_caption}</p>
      )}

      <div className="flex flex-wrap gap-1">
        {item.platforms.map((p) => (
          <span key={p} className={cn("text-[10px] px-1.5 py-0.5 rounded border", PLATFORM_CONFIG[p]?.color ?? "bg-gray-100")}>
            {PLATFORM_CONFIG[p]?.label ?? p}
          </span>
        ))}
      </div>

      {scores && (
        <div className="grid grid-cols-4 gap-2 text-center">
          {(["quality_score", "readability_score", "engagement_score", "completeness_score"] as const).map((key) => (
            <div key={key} className="rounded bg-gray-50 py-1">
              <p className="text-[10px] text-gray-500 capitalize">{key.replace("_score", "")}</p>
              <p className="text-sm font-bold text-gray-800">{scores[key]}</p>
            </div>
          ))}
        </div>
      )}

      {scores?.recommendations && scores.recommendations.length > 0 && (
        <ul className="text-[11px] text-amber-800 list-disc pl-4">
          {scores.recommendations.map((r) => <li key={r}>{r}</li>)}
        </ul>
      )}

      <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-100">
        <button type="button" className="btn-primary text-xs py-1 flex items-center gap-1" disabled={busy} onClick={onApprove}>
          <Check size={12} /> Approve
        </button>
        <button type="button" className="btn-secondary text-xs py-1 flex items-center gap-1" disabled={busy} onClick={onSchedule}>
          <Calendar size={12} /> Schedule
        </button>
        <button type="button" className="text-xs py-1 px-2 rounded border border-red-200 text-red-700 hover:bg-red-50" disabled={busy} onClick={onReject}>
          <X size={12} className="inline" /> Reject
        </button>
        {item.generated_content_id ? (
          <Link href={`/content/${item.generated_content_id}`} className="text-xs text-brand-700 flex items-center gap-1 ml-auto">
            <ExternalLink size={12} /> Open content
          </Link>
        ) : (
          <button
            type="button"
            className="text-xs text-brand-700 ml-auto"
            disabled={busy}
            onClick={async () => {
              const r = await contentFactoryApi.createDraftFromItem(item.id);
              if (r.data.content_id) window.location.href = `/content/${r.data.content_id}`;
            }}
          >
            Create draft
          </button>
        )}
      </div>
    </div>
  );
}

export default function ContentFactoryReviewPage() {
  const queryClient = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [statusFilter, setStatusFilter] = useState<FactoryReviewStatus | "all">("all");
  const [scheduleItemId, setScheduleItemId] = useState<string | null>(null);
  const [scheduleDate, setScheduleDate] = useState("");

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => r.data),
  });

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["content-factory-review", clientId, statusFilter],
    queryFn: () =>
      contentFactoryApi.review({
        client_id: clientId || undefined,
        status: statusFilter === "all" ? undefined : statusFilter,
      }).then((r) => r.data),
  });

  const reviewMutation = useMutation({
    mutationFn: ({ itemId, status }: { itemId: string; status: FactoryReviewStatus }) =>
      contentFactoryApi.updateReview(itemId, { review_status: status }).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["content-factory-review"] });
      queryClient.invalidateQueries({ queryKey: ["content-factory-dashboard"] });
      toast.success("Status updated");
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const scheduleMutation = useMutation({
    mutationFn: ({ itemId, scheduled_for }: { itemId: string; scheduled_for: string }) =>
      contentFactoryApi.schedule(itemId, { scheduled_for }).then((r) => r.data),
    onSuccess: () => {
      setScheduleItemId(null);
      setScheduleDate("");
      queryClient.invalidateQueries({ queryKey: ["content-factory-review"] });
      queryClient.invalidateQueries({ queryKey: ["content-factory-dashboard"] });
      toast.success("Scheduled on calendar");
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const clientOptions = normalizeList<Client>(clients);
  const items = data?.items ?? [];
  const busy = reviewMutation.isPending || scheduleMutation.isPending;

  if (isLoading) return <LoadingState label="Loading review queue…" />;
  if (isError) return <ErrorState message="Failed to load review queue" onRetry={() => refetch()} />;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <ContentFactoryHeader
        title="Review & approval"
        description="Draft → Generated → Needs review → Approved → Scheduled → Published"
      />
      <ContentFactorySubNav />

      <div className="flex flex-wrap gap-3 mb-4">
        <select className="input text-sm max-w-xs" value={clientId} onChange={(e) => setClientId(e.target.value)}>
          <option value="">All factories</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
        <div className="flex flex-wrap gap-1">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setStatusFilter(tab.value)}
              className={cn(
                "text-xs px-2.5 py-1 rounded-full border",
                statusFilter === tab.value ? "bg-teal-50 border-teal-300 text-teal-800 font-medium" : "border-gray-200 text-gray-600",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {scheduleItemId && (
        <div className="card p-4 mb-4 flex flex-wrap items-end gap-3">
          <div>
            <label className="text-xs text-gray-600 block mb-1">Schedule for</label>
            <input
              type="datetime-local"
              className="input text-sm"
              value={scheduleDate}
              onChange={(e) => setScheduleDate(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="btn-primary text-sm"
            disabled={!scheduleDate || scheduleMutation.isPending}
            onClick={() =>
              scheduleMutation.mutate({
                itemId: scheduleItemId,
                scheduled_for: new Date(scheduleDate).toISOString(),
              })
            }
          >
            Confirm schedule
          </button>
          <button type="button" className="btn-secondary text-sm" onClick={() => setScheduleItemId(null)}>
            Cancel
          </button>
        </div>
      )}

      {items.length === 0 ? (
        <p className="text-sm text-gray-500 text-center py-12">
          No items in this queue. <Link href="/content-factory/generate" className="text-teal-700 underline">Generate content</Link>
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {items.map((item) => (
            <ReviewCard
              key={item.id}
              item={item}
              busy={busy}
              onApprove={() => reviewMutation.mutate({ itemId: item.id, status: "approved" })}
              onReject={() => reviewMutation.mutate({ itemId: item.id, status: "rejected" })}
              onSchedule={() => setScheduleItemId(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
