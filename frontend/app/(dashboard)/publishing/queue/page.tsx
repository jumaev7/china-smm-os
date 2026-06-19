"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  publishingApi,
  PublishingQueueCategory,
  PublishingQueueItem,
  normalizeList,
} from "@/lib/api";
import { clientTimezone, formatScheduledLocal, LOCAL_TIMEZONE_NOTE } from "@/lib/datetime";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";
import {
  ArrowLeft,
  CalendarClock,
  RefreshCw,
  Send,
} from "lucide-react";
import toast from "react-hot-toast";

const SECTIONS: {
  key: PublishingQueueCategory | "waiting_account" | "future" | "blocked";
  title: string;
  description: string;
  categories: PublishingQueueCategory[];
}[] = [
  {
    key: "ready",
    title: "Ready to publish",
    description: "Due now and passed safety checks — scheduler will publish automatically.",
    categories: ["ready"],
  },
  {
    key: "waiting_client",
    title: "Waiting for client approval",
    description: "Scheduled but blocked until the client approves via Telegram or web review.",
    categories: ["waiting_client"],
  },
  {
    key: "waiting_account",
    title: "Missing publishing account",
    description: "Add or connect a publishing account for the selected platforms.",
    categories: ["waiting_account"],
  },
  {
    key: "future",
    title: "Scheduled time in future",
    description: "Will become eligible when scheduled_for is reached.",
    categories: ["future"],
  },
  {
    key: "stuck_publishing",
    title: "Stuck publishing",
    description: "Status is publishing — cancel schedule or retry after recovery.",
    categories: ["stuck_publishing"],
  },
  {
    key: "failed",
    title: "Failed",
    description: "Last publish attempt failed or partially failed.",
    categories: ["failed"],
  },
  {
    key: "blocked",
    title: "Other blocked",
    description: "Admin approval, media, platforms, or other safety issues.",
    categories: ["blocked"],
  },
];

const CATEGORY_BADGE: Record<string, string> = {
  ready: "bg-emerald-100 text-emerald-800 border-emerald-200",
  waiting_client: "bg-amber-100 text-amber-800 border-amber-200",
  waiting_account: "bg-orange-100 text-orange-800 border-orange-200",
  future: "bg-sky-100 text-sky-800 border-sky-200",
  stuck_publishing: "bg-violet-100 text-violet-800 border-violet-200",
  failed: "bg-red-100 text-red-800 border-red-200",
  blocked: "bg-gray-100 text-gray-700 border-gray-200",
};

function SectionTable({
  title,
  description,
  items,
  renderActions,
}: {
  title: string;
  description: string;
  items: PublishingQueueItem[];
  renderActions: (item: PublishingQueueItem) => React.ReactNode;
}) {
  if (items.length === 0) return null;

  return (
    <div className="card overflow-hidden mb-5">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
        <h2 className="text-sm font-semibold text-gray-900">
          {title}{" "}
          <span className="text-gray-400 font-normal">({items.length})</span>
        </h2>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-left text-xs text-gray-500">
              <th className="px-4 py-2 font-medium">Client</th>
              <th className="px-4 py-2 font-medium">Status</th>
              <th className="px-4 py-2 font-medium">Scheduled</th>
              <th className="px-4 py-2 font-medium">Platforms</th>
              <th className="px-4 py-2 font-medium">Client review</th>
              <th className="px-4 py-2 font-medium">Block reason</th>
              <th className="px-4 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {items.map((item) => (
              <tr key={item.id} className="hover:bg-gray-50/80">
                <td className="px-4 py-3">
                  <Link
                    href={`/content/${item.id}`}
                    className="text-sm font-medium text-gray-900 hover:text-brand-600"
                  >
                    {item.company_name}
                  </Link>
                </td>
                <td className="px-4 py-3 text-xs capitalize">{item.status}</td>
                <td className="px-4 py-3 text-xs text-gray-600">
                  {item.scheduled_for
                    ? item.local_time || formatScheduledLocal(item.scheduled_for)
                    : "—"}
                  {item.is_due && (
                    <span className="ml-1 text-[10px] text-emerald-700 font-medium">Due</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {item.platforms.map((p) => (
                      <span
                        key={p}
                        className={cn(
                          "text-[10px] px-1.5 py-0.5 rounded",
                          PLATFORM_CONFIG[p]?.color,
                        )}
                      >
                        {PLATFORM_CONFIG[p]?.label ?? p}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-xs">{item.client_review_status ?? "—"}</td>
                <td className="px-4 py-3">
                  <span
                    className={cn(
                      "text-[10px] px-2 py-0.5 rounded-full border font-medium",
                      CATEGORY_BADGE[item.queue_category],
                    )}
                  >
                    {item.block_reason_label || "Ready"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1 justify-end">{renderActions(item)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PublishingQueuePage() {
  const qc = useQueryClient();
  const [busyId, setBusyId] = useState<string | null>(null);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["publishing-queue", clientTimezone()],
    queryFn: () => publishingApi.getQueue(clientTimezone()).then((r) => r.data),
    refetchInterval: 30_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["publishing-queue"] });
    qc.invalidateQueries({ queryKey: ["scheduled-publish-debug"] });
    qc.invalidateQueries({ queryKey: ["publishing-calendar"] });
  };

  const cancelMutation = useMutation({
    mutationFn: (id: string) => publishingApi.cancelQueueItem(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      toast.success(res.data.message);
      invalidate();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Cancel failed");
    },
  });

  const retryMutation = useMutation({
    mutationFn: (id: string) => publishingApi.retryQueueItem(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      if (res.data.ok) toast.success(res.data.message);
      else toast.error(res.data.message || res.data.block_reason || "Retry blocked");
      invalidate();
    },
    onError: () => toast.error("Retry failed"),
  });

  const reviewMutation = useMutation({
    mutationFn: (id: string) => publishingApi.sendClientReviewQueueItem(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      if (res.data.ok) toast.success(res.data.message);
      else toast.error(res.data.message);
      invalidate();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(
        typeof err.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Send preview failed",
      );
    },
  });

  const grouped = useMemo(() => {
    const map = new Map<string, PublishingQueueItem[]>();
    for (const section of SECTIONS) {
      map.set(
        section.key,
        normalizeList(data).filter((i) => section.categories.includes(i.queue_category)),
      );
    }
    return map;
  }, [data]);

  const renderActions = (item: PublishingQueueItem) => {
    const busy = busyId === item.id;
    return (
      <>
        <Link href={`/content/${item.id}`} className="btn-secondary text-[10px] py-1 px-2">
          Open
        </Link>
        <button
          type="button"
          className="btn-secondary text-[10px] py-1 px-2"
          disabled={busy}
          onClick={() => {
            if (confirm("Cancel schedule and remove from queue?")) {
              cancelMutation.mutate(item.id);
            }
          }}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn-primary text-[10px] py-1 px-2"
          disabled={busy}
          onClick={() => retryMutation.mutate(item.id)}
        >
          <RefreshCw size={11} className={busy ? "animate-spin" : ""} />
          Retry
        </button>
        <button
          type="button"
          className="btn-secondary text-[10px] py-1 px-2"
          disabled={busy}
          onClick={() => reviewMutation.mutate(item.id)}
        >
          <Send size={11} />
          Review
        </button>
      </>
    );
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <Link
        href="/publishing"
        className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4"
      >
        <ArrowLeft size={14} /> Publishing
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <CalendarClock size={20} className="text-brand-600" />
            Publishing Queue
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage scheduled posts blocked by client approval, accounts, or timing.{" "}
            <span className="text-gray-400">{LOCAL_TIMEZONE_NOTE}</span>
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary text-xs"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {isLoading ? (
        <p className="text-sm text-gray-400">Loading queue…</p>
      ) : !normalizeList(data).length ? (
        <div className="card p-8 text-center text-sm text-gray-500">
          No items in the publishing queue.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
            {[
              ["ready", "Ready"],
              ["waiting_client", "Client approval"],
              ["failed", "Failed"],
              ["stuck_publishing", "Stuck"],
            ].map(([key, label]) => (
              <div key={key} className="card p-3 text-center">
                <div className="text-2xl font-semibold text-gray-900">
                  {data?.counts?.[key] ?? grouped.get(key)?.length ?? 0}
                </div>
                <div className="text-xs text-gray-500">{label}</div>
              </div>
            ))}
          </div>

          {SECTIONS.map((section) => (
            <SectionTable
              key={section.key}
              title={section.title}
              description={section.description}
              items={grouped.get(section.key) ?? []}
              renderActions={renderActions}
            />
          ))}
        </>
      )}
    </div>
  );
}
