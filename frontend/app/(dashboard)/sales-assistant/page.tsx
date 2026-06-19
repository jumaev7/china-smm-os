"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  Loader2,
  RefreshCw,
  Check,
  X,
  CircleCheck,
  ExternalLink,
  ListTodo,
  Inbox,
  Contact,
  Briefcase,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  salesAssistantApi,
  operatorTaskEngineApi,
  SalesAssistantRecommendation,
  SalesAssistantPriority,
  SalesAssistantRecommendationType,
  SalesAssistantStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/ui/PageStates";

const TYPE_LABELS: Record<SalesAssistantRecommendationType, string> = {
  reply_needed: "Reply needed",
  follow_up_needed: "Follow-up",
  proposal_needed: "Proposal",
  lead_link_needed: "Link lead",
  deal_update_needed: "Deal update",
  hot_lead: "Hot lead",
  stalled_deal: "Stalled deal",
  missing_task: "Missing task",
  playbook_recommended: "Playbook",
};

const PRIORITY_STYLES: Record<SalesAssistantPriority, string> = {
  urgent: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

const STATUS_STYLES: Record<SalesAssistantStatus, string> = {
  open: "bg-sky-100 text-sky-800 border-sky-200",
  dismissed: "bg-gray-100 text-gray-500 border-gray-200",
  completed: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

function KpiCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
    </div>
  );
}

function RecommendationRow({
  rec,
  onCreateTask,
  onDismiss,
  onComplete,
  busy,
}: {
  rec: SalesAssistantRecommendation;
  onCreateTask: (id: string) => void;
  onDismiss: (id: string) => void;
  onComplete: (id: string) => void;
  busy: boolean;
}) {
  return (
    <tr className="border-b border-gray-50 hover:bg-gray-50/50">
      <td className="py-3 px-3">
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
            PRIORITY_STYLES[rec.priority],
          )}
        >
          {rec.priority}
        </span>
      </td>
      <td className="py-3 px-3">
        <span className="text-[10px] px-2 py-0.5 rounded-full border bg-indigo-50 text-indigo-800 border-indigo-200 font-medium">
          {TYPE_LABELS[rec.recommendation_type]}
        </span>
      </td>
      <td className="py-3 px-3 min-w-[200px]">
        <p className="text-sm font-medium text-gray-900">{rec.title}</p>
        <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{rec.summary}</p>
      </td>
      <td className="py-3 px-3 text-xs text-gray-600">
        {rec.lead_name && (
          <Link href={`/crm?lead=${rec.lead_id}`} className="text-brand-700 hover:underline block">
            {rec.lead_name}
          </Link>
        )}
        {rec.deal_title && (
          <Link href={`/crm/deals?deal=${rec.deal_id}`} className="text-brand-700 hover:underline block">
            {rec.deal_title}
          </Link>
        )}
        {rec.conversation_id && (
          <Link
            href={`/unified-inbox?conversation=${encodeURIComponent(rec.conversation_id)}`}
            className="text-brand-700 hover:underline block truncate max-w-[140px]"
          >
            Conversation
          </Link>
        )}
        {!rec.lead_name && !rec.deal_title && !rec.conversation_id && "—"}
      </td>
      <td className="py-3 px-3 text-xs text-gray-700 max-w-[200px]">{rec.recommended_action}</td>
      <td className="py-3 px-3">
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
            STATUS_STYLES[rec.status],
          )}
        >
          {rec.status}
        </span>
      </td>
      <td className="py-3 px-3">
        {rec.status === "open" && (
          <div className="flex flex-wrap gap-1">
            {rec.conversation_id && (
              <Link
                href={`/unified-inbox?conversation=${encodeURIComponent(rec.conversation_id)}`}
                className="btn-secondary py-1 px-2 text-[10px] inline-flex items-center gap-0.5"
                title="Open conversation"
              >
                <Inbox size={11} />
              </Link>
            )}
            {rec.lead_id && (
              <Link
                href={`/crm?lead=${rec.lead_id}`}
                className="btn-secondary py-1 px-2 text-[10px] inline-flex items-center gap-0.5"
                title="Open lead"
              >
                <Contact size={11} />
              </Link>
            )}
            {rec.deal_id && (
              <Link
                href={`/crm/deals?deal=${rec.deal_id}`}
                className="btn-secondary py-1 px-2 text-[10px] inline-flex items-center gap-0.5"
                title="Open deal"
              >
                <Briefcase size={11} />
              </Link>
            )}
            <button
              type="button"
              className="btn-primary py-1 px-2 text-[10px] inline-flex items-center gap-0.5"
              disabled={busy || !rec.client_id}
              onClick={() => onCreateTask(rec.id)}
              title="Create Operator Task"
            >
              <ListTodo size={11} />
              <span className="hidden sm:inline">Create Task</span>
            </button>
            <button
              type="button"
              className="btn-secondary py-1 px-2 text-[10px] inline-flex items-center gap-0.5"
              disabled={busy}
              onClick={() => onComplete(rec.id)}
              title="Mark complete"
            >
              <CircleCheck size={11} />
            </button>
            <button
              type="button"
              className="btn-secondary py-1 px-2 text-[10px] inline-flex items-center gap-0.5 text-gray-500"
              disabled={busy}
              onClick={() => onDismiss(rec.id)}
              title="Dismiss"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {rec.linked_task_id && (
          <Link
            href={`/operator-tasks`}
            className="text-[10px] text-brand-600 flex items-center gap-0.5 mt-1"
          >
            Operator task <ExternalLink size={10} />
          </Link>
        )}
      </td>
    </tr>
  );
}

export default function SalesAssistantPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<SalesAssistantStatus | "">("open");
  const [priorityFilter, setPriorityFilter] = useState<SalesAssistantPriority | "">("");
  const [typeFilter, setTypeFilter] = useState<SalesAssistantRecommendationType | "">("");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-assistant-recommendations", statusFilter, priorityFilter, typeFilter],
    queryFn: () =>
      salesAssistantApi
        .list({
          status: statusFilter || undefined,
          priority: priorityFilter || undefined,
          type: typeFilter || undefined,
          limit: 100,
        })
        .then((r) => r.data),
  });

  const scanMutation = useMutation({
    mutationFn: () => salesAssistantApi.scan(false).then((r) => r.data),
    onSuccess: (result) => {
      toast.success(`Scan complete: ${result.created} new recommendations`);
      queryClient.invalidateQueries({ queryKey: ["sales-assistant-recommendations"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const createTaskMutation = useMutation({
    mutationFn: (id: string) => operatorTaskEngineApi.fromRecommendation(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Operator task created");
      queryClient.invalidateQueries({ queryKey: ["sales-assistant-recommendations"] });
      queryClient.invalidateQueries({ queryKey: ["operator-task-engine"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => salesAssistantApi.dismiss(id).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sales-assistant-recommendations"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => salesAssistantApi.complete(id).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sales-assistant-recommendations"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const busy =
    scanMutation.isPending ||
    createTaskMutation.isPending ||
    dismissMutation.isPending ||
    completeMutation.isPending;

  const summary = data?.summary;
  const items = data?.items ?? [];

  if (isLoading) return <LoadingState message="Loading sales assistant…" />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load recommendations"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles size={22} className="text-violet-600" />
            Sales Assistant
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Cross-channel sales recommendations — manual scan only, no auto-actions
          </p>
        </div>
        <button
          type="button"
          className="btn-primary flex items-center gap-1.5"
          disabled={scanMutation.isPending}
          onClick={() => scanMutation.mutate()}
        >
          {scanMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Run Sales Scan
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Open recommendations" value={summary?.open_count ?? 0} />
        <KpiCard label="Urgent" value={summary?.urgent_count ?? 0} />
        <KpiCard label="Follow-ups needed" value={summary?.follow_ups_needed ?? 0} />
        <KpiCard label="Proposals needed" value={summary?.proposals_needed ?? 0} />
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <select
          className="input text-sm w-auto"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as SalesAssistantStatus | "")}
        >
          <option value="open">Open</option>
          <option value="">All (except dismissed)</option>
          <option value="completed">Completed</option>
          <option value="dismissed">Dismissed</option>
        </select>
        <select
          className="input text-sm w-auto"
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value as SalesAssistantPriority | "")}
        >
          <option value="">All priorities</option>
          <option value="urgent">Urgent</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select
          className="input text-sm w-auto"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as SalesAssistantRecommendationType | "")}
        >
          <option value="">All types</option>
          {(Object.keys(TYPE_LABELS) as SalesAssistantRecommendationType[]).map((t) => (
            <option key={t} value={t}>
              {TYPE_LABELS[t]}
            </option>
          ))}
        </select>
      </div>

      {items.length === 0 ? (
        <EmptyState
          title="No recommendations yet"
          description='Click "Run Sales Scan" to analyze inbox, CRM, proposals, and outreach.'
        />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                <th className="py-2 px-3 font-medium">Priority</th>
                <th className="py-2 px-3 font-medium">Type</th>
                <th className="py-2 px-3 font-medium">Title</th>
                <th className="py-2 px-3 font-medium">Linked</th>
                <th className="py-2 px-3 font-medium">Action</th>
                <th className="py-2 px-3 font-medium">Status</th>
                <th className="py-2 px-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((rec) => (
                <RecommendationRow
                  key={rec.id}
                  rec={rec}
                  busy={busy}
                  onCreateTask={(id) => createTaskMutation.mutate(id)}
                  onDismiss={(id) => dismissMutation.mutate(id)}
                  onComplete={(id) => completeMutation.mutate(id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
