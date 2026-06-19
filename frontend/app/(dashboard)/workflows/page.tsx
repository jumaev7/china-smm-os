"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch,
  Loader2,
  ListTodo,
  RefreshCw,
  Workflow,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  salesWorkflowApi,
  WorkflowPriority,
  WorkflowRecommendation,
  WorkflowType,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const WORKFLOW_LABELS: Record<WorkflowType, string> = {
  follow_up_workflow: "Follow-up",
  proposal_workflow: "Proposal",
  re_engagement_workflow: "Re-engagement",
  crm_cleanup_workflow: "CRM Cleanup",
  hot_lead_workflow: "Hot Lead",
};

const PRIORITY_STYLES: Record<WorkflowPriority, string> = {
  urgent: "bg-red-100 text-red-800 border-red-200",
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

function ActionsList({ actions }: { actions: WorkflowRecommendation["recommended_actions"] }) {
  if (!actions.length) return <span className="text-xs text-gray-400">—</span>;
  return (
    <ul className="space-y-1">
      {actions.map((a) => (
        <li key={a.action} className="text-xs text-gray-700">
          <span className="font-medium capitalize">{a.label}</span>
          <span className="text-gray-500"> — {a.description}</span>
        </li>
      ))}
    </ul>
  );
}

export default function WorkflowsPage() {
  const qc = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["workflows-overview"],
    queryFn: () => salesWorkflowApi.overview().then((r) => r.data),
  });

  const { data: recommendations, isLoading: recLoading } = useQuery({
    queryKey: ["workflows-recommendations"],
    queryFn: () => salesWorkflowApi.recommendations({ limit: 100 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: templates } = useQuery({
    queryKey: ["workflows-templates"],
    queryFn: () => salesWorkflowApi.templates().then((r) => r.data),
  });

  const generateMutation = useMutation({
    mutationFn: () => salesWorkflowApi.generate().then((r) => r.data),
    onSuccess: (result) => {
      toast.success(
        `Generated ${result.created} workflow(s) (${result.skipped_duplicates} duplicates skipped)`,
      );
      qc.invalidateQueries({ queryKey: ["workflows-overview"] });
      qc.invalidateQueries({ queryKey: ["workflows-recommendations"] });
      qc.invalidateQueries({ queryKey: ["sales-manager-summary"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const createTaskMutation = useMutation({
    mutationFn: (id: string) => salesWorkflowApi.createTask(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Task suggestion created — review in Operator Tasks");
      qc.invalidateQueries({ queryKey: ["workflows-recommendations"] });
      qc.invalidateQueries({ queryKey: ["operator-task-engine"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState message="Loading workflows…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load workflows"}
        onRetry={() => refetch()}
      />
    );
  }

  const items = recommendations?.items ?? [];
  const templateItems = templates?.items ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Workflow size={22} className="text-brand-600" />
            Sales Workflow Automation
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Workflow recommendations only — no automatic messaging, CRM changes, or execution
          </p>
        </div>
        <button
          type="button"
          disabled={generateMutation.isPending}
          onClick={() => generateMutation.mutate()}
          className="btn-primary flex items-center gap-2 text-sm"
        >
          {generateMutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <RefreshCw size={16} />
          )}
          Generate Workflows
        </button>
      </div>

      <PartialErrorsBanner errors={overview.errors} />

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-900">Workflow Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <KpiCard label="Active Recommendations" value={overview.active_recommendations} />
          <KpiCard label="High Priority" value={overview.high_priority} />
          <KpiCard label="Follow-ups" value={overview.follow_up_workflows} />
          <KpiCard label="Proposal Workflows" value={overview.proposal_workflows} />
          <KpiCard label="CRM Cleanup" value={overview.crm_cleanup_workflows} />
        </div>
      </section>

      <section className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Recommendations</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {recommendations?.total ?? 0} workflow recommendation(s)
          </p>
        </div>
        {recLoading ? (
          <div className="p-8 flex justify-center">
            <Loader2 size={24} className="animate-spin text-gray-400" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            message="No workflow recommendations yet"
            hint='Click "Generate Workflows" to scan CRM, inbox, proposals, and tasks.'
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                  <th className="py-2 px-3 font-medium">Workflow</th>
                  <th className="py-2 px-3 font-medium">Priority</th>
                  <th className="py-2 px-3 font-medium">Reason</th>
                  <th className="py-2 px-3 font-medium">Recommended Actions</th>
                  <th className="py-2 px-3 font-medium">Links</th>
                  <th className="py-2 px-3 font-medium">Task</th>
                </tr>
              </thead>
              <tbody>
                {items.map((rec) => (
                  <tr key={rec.id} className="border-b border-gray-50 hover:bg-gray-50/50 align-top">
                    <td className="py-3 px-3">
                      <p className="text-sm font-medium text-gray-900">{rec.title}</p>
                      <span className="text-[10px] px-2 py-0.5 rounded-full border bg-indigo-50 text-indigo-800 border-indigo-200 font-medium mt-1 inline-block">
                        {WORKFLOW_LABELS[rec.workflow_type] ?? rec.workflow_type}
                      </span>
                    </td>
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
                    <td className="py-3 px-3 text-xs text-gray-700 max-w-[220px]">{rec.reason}</td>
                    <td className="py-3 px-3 max-w-[280px]">
                      <ActionsList actions={rec.recommended_actions} />
                    </td>
                    <td className="py-3 px-3 text-xs space-y-1">
                      {rec.lead_id && (
                        <Link href={`/crm?lead=${rec.lead_id}`} className="text-brand-700 hover:underline block">
                          {rec.lead_name ?? "Lead"}
                        </Link>
                      )}
                      {rec.conversation_id && (
                        <Link
                          href={`/unified-inbox?conversation=${encodeURIComponent(rec.conversation_id)}`}
                          className="text-brand-700 hover:underline block"
                        >
                          Inbox
                        </Link>
                      )}
                      {rec.proposal_id && (
                        <Link href="/proposals" className="text-brand-700 hover:underline block">
                          Proposal
                        </Link>
                      )}
                      {!rec.lead_id && !rec.conversation_id && !rec.proposal_id && "—"}
                    </td>
                    <td className="py-3 px-3">
                      {rec.status === "open" && !rec.linked_task_id && (
                        <button
                          type="button"
                          disabled={createTaskMutation.isPending}
                          onClick={() => createTaskMutation.mutate(rec.id)}
                          className="btn-secondary py-1 px-2 text-[10px] inline-flex items-center gap-1"
                          title="Create task suggestion (manual)"
                        >
                          <ListTodo size={11} />
                          Suggest task
                        </button>
                      )}
                      {rec.linked_task_id && (
                        <Link
                          href="/operator-tasks"
                          className="text-[10px] text-emerald-700 hover:underline"
                        >
                          Task linked
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <GitBranch size={16} className="text-brand-600" />
          Templates
        </h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {templateItems.map((tpl) => (
            <div key={tpl.workflow_type} className="card p-4 space-y-2">
              <p className="text-sm font-semibold text-gray-900">{tpl.name}</p>
              <p className="text-xs text-gray-600">{tpl.description}</p>
              <div className="flex flex-wrap gap-1">
                {tpl.typical_actions.map((action) => (
                  <span
                    key={action}
                    className="text-[10px] px-2 py-0.5 rounded-full border bg-gray-50 text-gray-600 capitalize"
                  >
                    {action.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
