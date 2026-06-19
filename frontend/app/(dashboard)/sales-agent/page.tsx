"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Loader2,
  RefreshCw,
  Check,
  X,
  CircleCheck,
  ExternalLink,
  Filter,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  salesAgentApi,
  SalesAgentRecommendation,
  SalesAgentPriority,
  SalesAgentRecommendationType,
  SalesAgentStatus,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/ui/PageStates";

const TYPE_LABELS: Record<SalesAgentRecommendationType, string> = {
  follow_up: "Follow-up",
  proposal: "Proposal",
  contract: "Contract",
  invoice: "Invoice",
  payment_reminder: "Payment reminder",
  partner_follow_up: "Partner follow-up",
  risk_warning: "Risk warning",
  opportunity: "Opportunity",
};

const PRIORITY_STYLES: Record<SalesAgentPriority, string> = {
  high: "bg-red-100 text-red-800 border-red-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

const STATUS_STYLES: Record<SalesAgentStatus, string> = {
  new: "bg-sky-100 text-sky-800 border-sky-200",
  accepted: "bg-violet-100 text-violet-800 border-violet-200",
  dismissed: "bg-gray-100 text-gray-500 border-gray-200",
  done: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

function RecommendationCard({
  rec,
  onAccept,
  onDismiss,
  onMarkDone,
  busy,
}: {
  rec: SalesAgentRecommendation;
  onAccept: (id: string) => void;
  onDismiss: (id: string) => void;
  onMarkDone: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div className="card p-4 space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className={cn(
              "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
              PRIORITY_STYLES[rec.priority],
            )}
          >
            {rec.priority}
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-indigo-50 text-indigo-800 border-indigo-200 font-medium">
            {TYPE_LABELS[rec.recommendation_type]}
          </span>
          <span
            className={cn(
              "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
              STATUS_STYLES[rec.status],
            )}
          >
            {rec.status}
          </span>
        </div>
        <p className="text-[10px] text-gray-400">
          {new Date(rec.created_at).toLocaleString()}
        </p>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-900">{rec.title}</h3>
        <p className="text-xs text-gray-500 mt-0.5">
          {rec.client_name && <span>{rec.client_name}</span>}
          {rec.lead_name && <span> · Lead: {rec.lead_name}</span>}
          {rec.deal_title && <span> · Deal: {rec.deal_title}</span>}
          {rec.partner_name && <span> · Partner: {rec.partner_name}</span>}
        </p>
      </div>

      <p className="text-sm text-gray-700 leading-relaxed">{rec.description}</p>

      {rec.suggested_action && (
        <div className="rounded-lg bg-brand-50/60 border border-brand-100 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-brand-600 font-medium mb-0.5">
            Suggested action
          </p>
          <p className="text-sm text-gray-800">{rec.suggested_action}</p>
        </div>
      )}

      {rec.suggested_message && (
        <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
          <p className="text-[10px] uppercase tracking-wide text-gray-500 font-medium mb-0.5">
            Suggested message (review before sending)
          </p>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{rec.suggested_message}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {rec.status === "new" && (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAccept(rec.id)}
              className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50 flex items-center gap-1"
            >
              <Check size={12} />
              Accept → task
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDismiss(rec.id)}
              className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1"
            >
              <X size={12} />
              Dismiss
            </button>
          </>
        )}
        {(rec.status === "new" || rec.status === "accepted") && (
          <button
            type="button"
            disabled={busy}
            onClick={() => onMarkDone(rec.id)}
            className="text-xs px-3 py-1.5 rounded-lg border border-emerald-200 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50 flex items-center gap-1"
          >
            <CircleCheck size={12} />
            Mark done
          </button>
        )}
        {rec.linked_task_id && (
          <Link
            href="/tasks"
            className="text-xs px-3 py-1.5 rounded-lg border border-violet-200 text-violet-700 hover:bg-violet-50 flex items-center gap-1"
          >
            <ExternalLink size={12} />
            View task
          </Link>
        )}
        {rec.lead_id && (
          <Link
            href="/crm"
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 flex items-center gap-1"
          >
            Open lead
          </Link>
        )}
        {rec.deal_id && (
          <Link
            href={`/crm/deals/${rec.deal_id}`}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 flex items-center gap-1"
          >
            Open deal
          </Link>
        )}
        {rec.partner_id && (
          <Link
            href={`/partners/${rec.partner_id}`}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 flex items-center gap-1"
          >
            Open partner
          </Link>
        )}
      </div>
    </div>
  );
}

export default function SalesAgentPage() {
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const [statusFilter, setStatusFilter] = useState<SalesAgentStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<SalesAgentPriority | "">("");
  const [typeFilter, setTypeFilter] = useState<SalesAgentRecommendationType | "">("");

  useEffect(() => {
    const p = searchParams.get("priority") as SalesAgentPriority | null;
    const t = searchParams.get("type") as SalesAgentRecommendationType | null;
    if (p === "high" || p === "medium" || p === "low") setPriorityFilter(p);
    if (t && t in TYPE_LABELS) setTypeFilter(t);
  }, [searchParams]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-agent-recommendations", statusFilter, priorityFilter, typeFilter],
    queryFn: () =>
      salesAgentApi
        .list({
          status: statusFilter || undefined,
          priority: priorityFilter || undefined,
          type: typeFilter || undefined,
        })
        .then((r) => r.data),
  });

  const scanMutation = useMutation({
    mutationFn: () => salesAgentApi.scan().then((r) => r.data),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["sales-agent-recommendations"] });
      queryClient.invalidateQueries({ queryKey: ["sales-agent-summary"] });
      toast.success(
        `Scan complete: ${result.created} new, ${result.skipped_duplicates} duplicates skipped`,
      );
    },
    onError: (err: Error) => toast.error(err.message || "Scan failed"),
  });

  const acceptMutation = useMutation({
    mutationFn: (id: string) => salesAgentApi.accept(id).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sales-agent-recommendations"] });
      queryClient.invalidateQueries({ queryKey: ["sales-agent-summary"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      toast.success("Task created — review and act manually");
    },
    onError: (err: Error) => toast.error(err.message || "Accept failed"),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => salesAgentApi.dismiss(id).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sales-agent-recommendations"] });
      queryClient.invalidateQueries({ queryKey: ["sales-agent-summary"] });
      toast.success("Recommendation dismissed");
    },
    onError: (err: Error) => toast.error(err.message || "Dismiss failed"),
  });

  const doneMutation = useMutation({
    mutationFn: (id: string) => salesAgentApi.markDone(id).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sales-agent-recommendations"] });
      queryClient.invalidateQueries({ queryKey: ["sales-agent-summary"] });
      toast.success("Marked done");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const busy =
    acceptMutation.isPending || dismissMutation.isPending || doneMutation.isPending;
  const items = normalizeList<SalesAgentRecommendation>(data);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Bot size={22} className="text-brand-600" />
            Sales Agent
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Proactive recommendations — accept creates a task, no auto-send
          </p>
        </div>
        <button
          type="button"
          disabled={scanMutation.isPending}
          onClick={() => scanMutation.mutate()}
          className="btn-primary text-sm flex items-center gap-1.5"
        >
          {scanMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )}
          Scan pipeline
        </button>
      </div>

      <div className="card p-3 flex flex-wrap items-center gap-2">
        <Filter size={14} className="text-gray-400" />
        <select
          className="input text-xs py-1.5 w-auto"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as SalesAgentStatus | "")}
        >
          <option value="">All statuses</option>
          <option value="new">New</option>
          <option value="accepted">Accepted</option>
          <option value="done">Done</option>
          <option value="dismissed">Dismissed</option>
        </select>
        <select
          className="input text-xs py-1.5 w-auto"
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value as SalesAgentPriority | "")}
        >
          <option value="">All priorities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select
          className="input text-xs py-1.5 w-auto"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as SalesAgentRecommendationType | "")}
        >
          <option value="">All types</option>
          {(Object.keys(TYPE_LABELS) as SalesAgentRecommendationType[]).map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t]}
            </option>
          ))}
        </select>
        <span className="text-xs text-gray-400 ml-auto">{data?.total ?? 0} total</span>
      </div>

      {isLoading && <LoadingState message="Loading recommendations…" />}

      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load recommendations"}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && !isError && items.length === 0 && (
        <EmptyState
          title="No recommendations yet"
          description="Run a pipeline scan to detect follow-ups, risks, and opportunities."
        />
      )}

      <div className="space-y-3">
        {items.map((rec) => (
          <RecommendationCard
            key={rec.id}
            rec={rec}
            busy={busy}
            onAccept={(id) => acceptMutation.mutate(id)}
            onDismiss={(id) => dismissMutation.mutate(id)}
            onMarkDone={(id) => doneMutation.mutate(id)}
          />
        ))}
      </div>
    </div>
  );
}
