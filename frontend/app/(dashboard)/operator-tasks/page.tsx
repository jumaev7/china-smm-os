"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ListTodo,
  Loader2,
  RefreshCw,
  CheckCircle2,
  X,
  ExternalLink,
  Inbox,
  Contact,
  Briefcase,
  FileSignature,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  executiveCopilotApi,
  dealRiskApi,
  multiAgentTeamApi,
  operatorTaskEngineApi,
  salesDepartmentV3Api,
  salesWorkflowApi,
  ExecutiveCopilotRecommendation,
  MultiAgentRecommendation,
  SalesDeptV3RecommendedAction,
  OperatorTaskEngineItem,
  OperatorEngineActionType,
  WorkflowRecommendation,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";

const ACTION_LABELS: Record<string, string> = {
  reply_to_message: "Reply to message",
  follow_up: "Follow up",
  create_proposal: "Create proposal",
  review_proposal: "Review proposal",
  link_lead: "Link lead",
  update_deal: "Update deal",
  check_payment: "Check payment",
  review_hot_lead: "Review hot lead",
  manual_sales_action: "Manual sales action",
};

const PRIORITY_STYLES: Record<string, string> = {
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

function KpiCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
    </div>
  );
}

function sourceHref(task: OperatorTaskEngineItem): string | null {
  if (task.conversation_id) {
    return `/unified-inbox?conversation=${encodeURIComponent(task.conversation_id)}`;
  }
  if (task.proposal_id) return `/proposals/${task.proposal_id}`;
  if (task.lead_id) return `/crm?lead=${task.lead_id}`;
  if (task.deal_id) return `/crm/deals?deal=${task.deal_id}`;
  if (task.recommendation_id) return `/sales-assistant`;
  return null;
}

function TaskDetailPanel({
  task,
  busy,
  onComplete,
  onDismiss,
}: {
  task: OperatorTaskEngineItem;
  busy: boolean;
  onComplete: () => void;
  onDismiss: () => void;
}) {
  const href = sourceHref(task);
  return (
    <div className="card p-4 space-y-4 sticky top-4">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400">Task detail</p>
        <h2 className="text-lg font-semibold text-gray-900 mt-1">{task.title}</h2>
        <div className="flex flex-wrap gap-2 mt-2">
          <span
            className={cn(
              "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
              PRIORITY_STYLES[task.priority] ?? PRIORITY_STYLES.medium,
            )}
          >
            {task.priority}
          </span>
          {task.action_type && (
            <span className="text-[10px] px-2 py-0.5 rounded-full border bg-indigo-50 text-indigo-800 border-indigo-200">
              {ACTION_LABELS[task.action_type] ?? task.action_type}
            </span>
          )}
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-gray-50 text-gray-600">
            {task.status}
          </span>
          {task.lead_classification && (
            <span className="text-[10px] px-2 py-0.5 rounded-full border bg-red-50 text-red-800 border-red-200 capitalize">
              {task.lead_classification}
              {task.lead_classification_score != null ? ` · ${task.lead_classification_score}` : ""}
            </span>
          )}
        </div>
      </div>

      {task.description && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">Summary</p>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{task.description}</p>
        </div>
      )}

      {task.recommended_action && (
        <div className="rounded-lg border border-brand-100 bg-brand-50/40 p-3">
          <p className="text-[10px] uppercase tracking-wide text-brand-700 mb-1">Recommended action</p>
          <p className="text-sm text-brand-900">{task.recommended_action}</p>
          <p className="text-[10px] text-gray-500 mt-2">Manual workflow only — no auto-send or CRM updates.</p>
        </div>
      )}

      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-2">Linked objects</p>
        <ul className="text-sm space-y-1 text-gray-700">
          {task.company_name && <li>Client: {task.company_name}</li>}
          {task.channel && <li>Channel: {task.channel}</li>}
          {task.lead_name && (
            <li>
              Lead:{" "}
              <Link href={`/crm?lead=${task.lead_id}`} className="text-brand-700 hover:underline">
                {task.lead_name}
              </Link>
            </li>
          )}
          {task.deal_title && (
            <li>
              Deal:{" "}
              <Link href={`/crm/deals?deal=${task.deal_id}`} className="text-brand-700 hover:underline">
                {task.deal_title}
              </Link>
            </li>
          )}
          {task.proposal_title && (
            <li>
              Proposal:{" "}
              <Link href={`/proposals/${task.proposal_id}`} className="text-brand-700 hover:underline">
                {task.proposal_title}
              </Link>
            </li>
          )}
          {task.conversation_id && (
            <li>
              Conversation:{" "}
              <Link
                href={`/unified-inbox?conversation=${encodeURIComponent(task.conversation_id)}`}
                className="text-brand-700 hover:underline"
              >
                Open inbox
              </Link>
            </li>
          )}
          {task.due_at && (
            <li>Due: {format(parseISO(task.due_at), "MMM d, yyyy HH:mm")}</li>
          )}
        </ul>
      </div>

      <div className="flex flex-wrap gap-2">
        {href && (
          <Link href={href} className="btn-secondary py-1.5 px-3 text-xs inline-flex items-center gap-1">
            <ExternalLink size={12} />
            Open source
          </Link>
        )}
        <button
          type="button"
          className="btn-primary py-1.5 px-3 text-xs inline-flex items-center gap-1"
          disabled={busy}
          onClick={onComplete}
        >
          <CheckCircle2 size={12} />
          Complete
        </button>
        <button
          type="button"
          className="btn-secondary py-1.5 px-3 text-xs inline-flex items-center gap-1 text-gray-600"
          disabled={busy}
          onClick={onDismiss}
        >
          <X size={12} />
          Dismiss
        </button>
      </div>
    </div>
  );
}

export default function OperatorTasksPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState<OperatorEngineActionType | "">("");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["operator-task-engine", actionFilter],
    queryFn: () =>
      operatorTaskEngineApi
        .list({ action_type: actionFilter || undefined, limit: 100 })
        .then((r) => r.data),
  });

  const { data: executiveRecs } = useQuery({
    queryKey: ["executive-copilot-task-suggestions"],
    queryFn: () => executiveCopilotApi.recommendations({ limit: 8 }).then((r) => r.data),
    retry: 1,
  });

  const { data: workflowRecs } = useQuery({
    queryKey: ["workflows-recommendations-operator"],
    queryFn: () => salesWorkflowApi.recommendations({ limit: 6 }).then((r) => r.data),
    retry: 1,
  });

  const { data: departmentRecs } = useQuery({
    queryKey: ["sales-department-v3-operator-suggestions"],
    queryFn: () => salesDepartmentV3Api.recommendations({ limit: 8 }).then((r) => r.data),
    retry: 1,
  });

  const { data: multiAgentRecs } = useQuery({
    queryKey: ["multi-agent-operator-suggestions"],
    queryFn: () => multiAgentTeamApi.recommendations({ limit: 8 }).then((r) => r.data),
    retry: 1,
  });

  const { data: dealRiskHigh } = useQuery({
    queryKey: ["deal-risk-operator-suggestions"],
    queryFn: () => dealRiskApi.highRisk({ limit: 6 }).then((r) => r.data),
    retry: 1,
  });

  const createTaskMutation = useMutation({
    mutationFn: (id: string) => salesWorkflowApi.createTask(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Task created from workflow suggestion");
      qc.invalidateQueries({ queryKey: ["operator-task-engine"] });
      qc.invalidateQueries({ queryKey: ["workflows-recommendations-operator"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const generateMutation = useMutation({
    mutationFn: () => operatorTaskEngineApi.generate().then((r) => r.data),
    onSuccess: (result) => {
      toast.success(
        `Generated ${result.created} tasks (${result.skipped_duplicates} duplicates skipped)`,
      );
      qc.invalidateQueries({ queryKey: ["operator-task-engine"] });
      qc.invalidateQueries({ queryKey: ["dashboard-overview"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => operatorTaskEngineApi.complete(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Task completed");
      qc.invalidateQueries({ queryKey: ["operator-task-engine"] });
      setSelectedId(null);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => operatorTaskEngineApi.dismiss(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Task dismissed");
      qc.invalidateQueries({ queryKey: ["operator-task-engine"] });
      setSelectedId(null);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const busy =
    generateMutation.isPending ||
    completeMutation.isPending ||
    dismissMutation.isPending ||
    createTaskMutation.isPending;

  const items = data?.items ?? [];
  const summary = data?.summary;
  const selected = useMemo(
    () => items.find((t) => t.id === selectedId) ?? null,
    [items, selectedId],
  );

  const executiveTaskSuggestions = useMemo(() => {
    const all = executiveRecs?.items ?? [];
    if (all.length === 0) return [];
    const taskCategories = new Set([
      "overdue_task_escalation",
      "hot_lead_follow_up",
      "proposal_follow_up",
    ]);
    const filtered = all.filter((rec) => taskCategories.has(rec.category));
    return (filtered.length > 0 ? filtered : all).slice(0, 6);
  }, [executiveRecs?.items]);

  const departmentActionSuggestions = useMemo(() => {
    const actions = [
      ...(departmentRecs?.recommended_actions ?? []),
      ...(departmentRecs?.overdue_actions ?? []),
    ];
    const seen = new Set<string>();
    const unique: SalesDeptV3RecommendedAction[] = [];
    for (const action of actions) {
      if (seen.has(action.action_id)) continue;
      seen.add(action.action_id);
      unique.push(action);
    }
    return unique.slice(0, 6);
  }, [departmentRecs?.recommended_actions, departmentRecs?.overdue_actions]);

  const multiAgentSuggestions = useMemo(
    () => (multiAgentRecs?.top_recommendations ?? []).slice(0, 6),
    [multiAgentRecs?.top_recommendations],
  );

  if (isLoading) return <LoadingState message={t("operatorTasks.loading")} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("operatorTasks.loadError")}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <ListTodo size={22} className="text-violet-600" />
            {t("operatorTasks.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("operatorTasks.subtitle")}</p>
        </div>
        <button
          type="button"
          className="btn-primary flex items-center gap-1.5"
          disabled={generateMutation.isPending}
          onClick={() => generateMutation.mutate()}
        >
          {generateMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )}
          {t("operatorTasks.generate")}
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label={t("operatorTasks.kpiOpen")} value={summary?.open_count ?? 0} />
        <KpiCard label={t("operatorTasks.kpiUrgent")} value={summary?.urgent_count ?? 0} />
        <KpiCard label={t("operatorTasks.kpiOverdue")} value={summary?.overdue_count ?? 0} />
        <KpiCard label={t("operatorTasks.kpiDueToday")} value={summary?.due_today_count ?? 0} />
      </div>

      {executiveTaskSuggestions.length > 0 && (
        <div className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Executive task suggestions</p>
            <Link href="/executive-copilot" className="text-xs text-brand-700 hover:underline">
              Executive Copilot
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {executiveTaskSuggestions.map((rec: ExecutiveCopilotRecommendation, i) => (
              <li key={i} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{rec.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{rec.description}</p>
                </div>
                <span className="text-[10px] text-gray-400 capitalize shrink-0">{rec.priority}</span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">
            Executive-generated suggestions — create tasks manually if needed.
          </p>
        </div>
      )}

      {dealRiskHigh && (dealRiskHigh.items?.length ?? 0) > 0 && (
        <div className="card p-4 space-y-3 border-orange-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Risk-based task suggestions</p>
            <Link href="/deal-risk" className="text-xs text-brand-700 hover:underline">
              Deal Risk
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {dealRiskHigh.items.slice(0, 6).map((row) => (
              <li key={row.deal_id} className="border-b border-gray-50 pb-2">
                <p className="font-medium text-gray-900">{row.title}</p>
                <p className="text-[10px] text-gray-500 mt-0.5 capitalize">
                  {row.risk_level.replace(/_/g, " ")} · health {row.deal_health_score}
                </p>
                <p className="text-[10px] text-orange-700 mt-0.5">
                  {(row.risk_reasons ?? []).slice(0, 2).join(" · ") || "Manual intervention review"}
                </p>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">
            Suggestions only — create operator tasks manually if needed.
          </p>
        </div>
      )}

      {multiAgentSuggestions.length > 0 && (
        <div className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Agent-generated recommendations</p>
            <Link href="/multi-agent" className="text-xs text-brand-700 hover:underline">
              Multi-Agent Team
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {multiAgentSuggestions.map((rec: MultiAgentRecommendation, i) => (
              <li key={i} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{rec.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{rec.source_agent}</p>
                </div>
                <span className="text-[10px] text-gray-400 capitalize shrink-0">{rec.priority}</span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">
            Operations Agent and team coordinator — manual task creation only.
          </p>
        </div>
      )}

      {departmentActionSuggestions.length > 0 && (
        <div className="card p-4 space-y-3 border-brand-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Department-generated action suggestions</p>
            <Link href="/sales-department-v3" className="text-xs text-brand-700 hover:underline">
              Sales Department v3
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {departmentActionSuggestions.map((action: SalesDeptV3RecommendedAction) => (
              <li key={action.action_id} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{action.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{action.description}</p>
                  <p className="text-[10px] text-gray-400 capitalize mt-0.5">
                    {action.source} · {action.category}
                    {action.is_overdue ? " · overdue" : ""}
                  </p>
                </div>
                <span className="text-[10px] text-gray-400 capitalize shrink-0">{action.priority}</span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">
            Sales Department OS recommendations — manual task creation only.
          </p>
        </div>
      )}

      {(workflowRecs?.items?.length ?? 0) > 0 && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Workflow task suggestions</p>
            <Link href="/workflows" className="text-xs text-brand-700 hover:underline">
              View workflows
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {workflowRecs!.items
              .filter((rec: WorkflowRecommendation) => rec.status === "open" && !rec.linked_task_id)
              .slice(0, 5)
              .map((rec: WorkflowRecommendation) => (
                <li
                  key={rec.id}
                  className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2"
                >
                  <div>
                    <p className="font-medium text-gray-900">{rec.title}</p>
                    <p className="text-[10px] text-gray-500 mt-0.5">{rec.reason}</p>
                  </div>
                  <button
                    type="button"
                    disabled={createTaskMutation.isPending}
                    onClick={() => createTaskMutation.mutate(rec.id)}
                    className="btn-secondary py-1 px-2 text-[10px] shrink-0"
                  >
                    Create task
                  </button>
                </li>
              ))}
          </ul>
          <p className="text-[10px] text-gray-400">Manual task creation only — no auto-execution.</p>
        </div>
      )}

      <select
        className="input text-sm w-auto max-w-xs"
        value={actionFilter}
        onChange={(e) => setActionFilter(e.target.value as OperatorEngineActionType | "")}
      >
        <option value="">{t("operatorTasks.allActions")}</option>
        {(Object.keys(ACTION_LABELS) as OperatorEngineActionType[]).map((a) => (
          <option key={a} value={a}>
            {ACTION_LABELS[a]}
          </option>
        ))}
      </select>

      {items.length === 0 ? (
        <EmptyState
          title={t("operatorTasks.emptyTitle")}
          description={t("operatorTasks.emptyDescription")}
        />
      ) : (
        <div className="grid lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 card overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                  <th className="py-2 px-3 font-medium">Priority</th>
                  <th className="py-2 px-3 font-medium">Action</th>
                  <th className="py-2 px-3 font-medium">Title</th>
                  <th className="py-2 px-3 font-medium">Source</th>
                  <th className="py-2 px-3 font-medium">Linked</th>
                  <th className="py-2 px-3 font-medium">Due</th>
                  <th className="py-2 px-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((task) => (
                  <tr
                    key={task.id}
                    className={cn(
                      "border-b border-gray-50 hover:bg-gray-50/50 cursor-pointer",
                      selectedId === task.id && "bg-brand-50/50",
                    )}
                    onClick={() => setSelectedId(task.id)}
                  >
                    <td className="py-3 px-3">
                      <span
                        className={cn(
                          "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                          PRIORITY_STYLES[task.priority] ?? PRIORITY_STYLES.medium,
                        )}
                      >
                        {task.priority}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-xs text-gray-600">
                      {task.action_type ? ACTION_LABELS[task.action_type] ?? task.action_type : "—"}
                    </td>
                    <td className="py-3 px-3 text-sm font-medium text-gray-900 max-w-[200px]">
                      {task.title}
                    </td>
                    <td className="py-3 px-3 text-xs text-gray-500 capitalize">
                      {task.source_type.replace(/_/g, " ")}
                    </td>
                    <td className="py-3 px-3 text-xs">
                      <div className="flex gap-1">
                        {task.lead_id && (
                          <Link href={`/crm?lead=${task.lead_id}`} onClick={(e) => e.stopPropagation()}>
                            <Contact size={12} className="text-brand-600" />
                          </Link>
                        )}
                        {task.deal_id && (
                          <Link
                            href={`/crm/deals?deal=${task.deal_id}`}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Briefcase size={12} className="text-brand-600" />
                          </Link>
                        )}
                        {task.conversation_id && (
                          <Link
                            href={`/unified-inbox?conversation=${encodeURIComponent(task.conversation_id)}`}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Inbox size={12} className="text-brand-600" />
                          </Link>
                        )}
                        {task.proposal_id && (
                          <Link
                            href={`/proposals/${task.proposal_id}`}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <FileSignature size={12} className="text-brand-600" />
                          </Link>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-xs text-gray-500">
                      {task.due_at ? format(parseISO(task.due_at), "MMM d") : "—"}
                    </td>
                    <td className="py-3 px-3 text-xs capitalize text-gray-600">{task.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            {selected ? (
              <TaskDetailPanel
                task={selected}
                busy={busy}
                onComplete={() => completeMutation.mutate(selected.id)}
                onDismiss={() => dismissMutation.mutate(selected.id)}
              />
            ) : (
              <div className="card p-6 text-sm text-gray-500 text-center">
                {t("operatorTasks.selectTask")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
