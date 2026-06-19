"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Briefcase,
  Contact,
  FileSignature,
  Inbox,
  LayoutDashboard,
  ListTodo,
  Loader2,
  Sparkles,
  TrendingUp,
  AlertTriangle,
  Lightbulb,
  Workflow,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  executiveCopilotApi,
  salesDepartmentV3Api,
  salesManagerApi,
  salesWorkflowApi,
  dealRoomApi,
  ExecutiveCopilotRecommendation,
  SalesManagerBriefing,
  SalesManagerOpportunity,
  SalesManagerRisk,
  WorkflowRecommendation,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const PRIORITY_STYLES: Record<string, string> = {
  urgent: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-900 border-red-300",
  high: "bg-orange-100 text-orange-900 border-orange-200",
  medium: "bg-amber-100 text-amber-900 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

function KpiCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
    </div>
  );
}

function DealRoomOpportunityLink({ leadId }: { leadId: string }) {
  const router = useRouter();
  const mutation = useMutation({
    mutationFn: () => dealRoomApi.findOrCreate({ crm_lead_id: leadId }).then((r) => r.data),
    onSuccess: (room) => router.push(`/deal-room?id=${room.id}`),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <button
      type="button"
      disabled={mutation.isPending}
      onClick={() => mutation.mutate()}
      className="text-[10px] text-violet-700 hover:underline disabled:opacity-50"
    >
      {mutation.isPending ? "…" : "Deal Room"}
    </button>
  );
}

export default function SalesManagerPage() {
  const [briefing, setBriefing] = useState<SalesManagerBriefing | null>(null);

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-manager-overview"],
    queryFn: () => salesManagerApi.overview().then((r) => r.data),
  });

  const { data: opportunities } = useQuery({
    queryKey: ["sales-manager-opportunities"],
    queryFn: () => salesManagerApi.opportunities({ limit: 50 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: risks } = useQuery({
    queryKey: ["sales-manager-risks"],
    queryFn: () => salesManagerApi.risks({ limit: 50 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: workflowRecs } = useQuery({
    queryKey: ["workflows-recommendations-manager"],
    queryFn: () => salesWorkflowApi.recommendations({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: executiveRecs } = useQuery({
    queryKey: ["executive-copilot-recommendations-sales"],
    queryFn: () => executiveCopilotApi.recommendations({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: departmentRecs } = useQuery({
    queryKey: ["sales-department-v3-recommendations-manager"],
    queryFn: () => salesDepartmentV3Api.recommendations({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const briefingMutation = useMutation({
    mutationFn: () => salesManagerApi.generateBriefing(false).then((r) => r.data),
    onSuccess: (data) => {
      setBriefing(data);
      toast.success("Executive briefing generated");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState message="Loading sales manager…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load sales manager"}
        onRetry={() => refetch()}
      />
    );
  }

  const oppItems = opportunities?.items ?? [];
  const riskItems = risks?.items ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <LayoutDashboard size={22} className="text-violet-600" />
            AI Sales Manager
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Executive sales view — read-only analytics, manual briefing only
          </p>
        </div>
      </div>

      <PartialErrorsBanner errors={overview.errors} />

      {(executiveRecs?.items?.length ?? 0) > 0 && (
        <div className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Executive Recommendations</p>
            <Link href="/executive-copilot" className="text-xs text-brand-700 hover:underline">
              Executive Copilot
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {executiveRecs!.items.slice(0, 6).map((rec: ExecutiveCopilotRecommendation, i) => (
              <li key={i} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{rec.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{rec.description}</p>
                </div>
                <span className="text-[10px] text-gray-400 capitalize shrink-0">{rec.priority}</span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">Business-wide advisory — manual execution only.</p>
        </div>
      )}

      {((departmentRecs?.recommended_actions?.length ?? 0) > 0 ||
        (departmentRecs?.escalation_list?.length ?? 0) > 0) && (
        <div className="card p-4 space-y-3 border-brand-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">AI Department Recommendations</p>
            <Link href="/sales-department-v3" className="text-xs text-brand-700 hover:underline">
              Sales Department v3
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {(departmentRecs?.recommended_actions ?? []).slice(0, 5).map((action) => (
              <li key={action.action_id} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{action.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{action.description}</p>
                </div>
                <span className="text-[10px] text-gray-400 capitalize shrink-0">{action.priority}</span>
              </li>
            ))}
          </ul>
          {(departmentRecs?.escalation_list?.length ?? 0) > 0 && (
            <p className="text-[10px] text-red-600">
              {departmentRecs!.escalation_list.length} escalation(s) require manual review
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            Department OS layer — no automatic messaging, CRM, or task execution.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Leads" value={overview.leads_count} />
        <KpiCard label="Hot leads" value={overview.hot_leads} />
        <KpiCard label="Proposals" value={overview.active_proposals} />
        <KpiCard label="Overdue tasks" value={overview.overdue_tasks} />
        <KpiCard label="Conversations" value={overview.conversations_count} />
        <KpiCard label="Opportunities" value={overview.opportunities_count} />
        <KpiCard label="Workflows" value={overview.workflow_recommendations ?? 0} />
      </div>

      {overview.revenue_performance && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <TrendingUp size={16} className="text-emerald-600" />
              Revenue Performance
            </p>
            <Link href="/revenue-attribution" className="text-xs text-brand-700 hover:underline">
              Revenue Attribution
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
            <div>
              <p className="text-[10px] text-gray-400">Closed revenue</p>
              <p className="font-semibold tabular-nums">
                {Math.round(Number(overview.revenue_performance.total_revenue) || 0).toLocaleString()} UZS
              </p>
            </div>
            <div>
              <p className="text-[10px] text-gray-400">Won deals</p>
              <p className="font-semibold tabular-nums">{overview.revenue_performance.deals_won}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-400">Conversion</p>
              <p className="font-semibold tabular-nums">{overview.revenue_performance.conversion_rate}%</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-400">Best source</p>
              <p className="font-semibold">{overview.revenue_performance.best_source_label ?? "—"}</p>
            </div>
          </div>
          {overview.revenue_performance.insights?.summary && (
            <p className="text-xs text-gray-600">{overview.revenue_performance.insights.summary}</p>
          )}
        </div>
      )}

      {(workflowRecs?.items?.length ?? 0) > 0 && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Workflow size={16} className="text-brand-600" />
              Workflow Recommendations
            </p>
            <Link href="/workflows" className="text-xs text-brand-700 hover:underline">
              Open workflows
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {workflowRecs!.items.slice(0, 6).map((rec: WorkflowRecommendation) => (
              <li key={rec.id} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{rec.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{rec.reason}</p>
                </div>
                <span className="text-[10px] text-gray-400 capitalize shrink-0">{rec.priority}</span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">Recommendation-only — no automatic execution.</p>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card p-4 lg:col-span-2 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <TrendingUp size={16} className="text-emerald-600" />
            Opportunities
          </p>
          {oppItems.length === 0 ? (
            <EmptyState title="No opportunities detected" description="Pipeline looks stable." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                    <th className="py-2 px-2 font-medium">Type</th>
                    <th className="py-2 px-2 font-medium">Source</th>
                    <th className="py-2 px-2 font-medium">Priority</th>
                    <th className="py-2 px-2 font-medium">Classification</th>
                    <th className="py-2 px-2 font-medium">Action</th>
                    <th className="py-2 px-2 font-medium">Deal Room</th>
                  </tr>
                </thead>
                <tbody>
                  {oppItems.map((o: SalesManagerOpportunity, i) => (
                    <tr key={`${o.entity_id ?? o.title}-${i}`} className="border-b border-gray-50">
                      <td className="py-2 px-2 text-xs text-gray-800">{o.title}</td>
                      <td className="py-2 px-2 text-xs text-gray-500 capitalize">{o.source}</td>
                      <td className="py-2 px-2">
                        <span
                          className={cn(
                            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                            PRIORITY_STYLES[o.priority] ?? PRIORITY_STYLES.medium,
                          )}
                        >
                          {o.priority}
                        </span>
                      </td>
                      <td className="py-2 px-2 text-xs text-gray-500 capitalize">
                        {o.classification ? (
                          <Link href="/lead-intelligence" className="text-brand-700 hover:underline">
                            {o.classification}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-2 px-2 text-xs text-gray-600">{o.action}</td>
                      <td className="py-2 px-2 text-xs">
                        {o.lead_id ? (
                          <DealRoomOpportunityLink leadId={o.lead_id} />
                        ) : (
                          <Link href="/deal-room" className="text-[10px] text-gray-400 hover:underline">
                            Open
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-900">Quick actions</p>
          <div className="space-y-1.5">
            {[
              { href: "/crm", label: "Open CRM", icon: Contact },
              { href: "/unified-inbox", label: "Open Inbox", icon: Inbox },
              { href: "/operator-tasks", label: "Open Tasks", icon: ListTodo },
              { href: "/workflows", label: "Open Workflows", icon: Workflow },
              { href: "/proposals", label: "Open Proposals", icon: FileSignature },
              { href: "/deal-room", label: "Deal Room", icon: Briefcase },
              { href: "/revenue-attribution", label: "Revenue Attribution", icon: TrendingUp },
            ].map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-2 text-sm text-gray-700 hover:text-brand-800 px-2 py-2 rounded-lg hover:bg-gray-50"
              >
                <Icon size={14} className="text-gray-400" />
                {label}
              </Link>
            ))}
          </div>
        </div>
      </div>

      <div className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <AlertTriangle size={16} className="text-red-500" />
          Risks
        </p>
        {riskItems.length === 0 ? (
          <p className="text-sm text-gray-400">No risks flagged.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                  <th className="py-2 px-2 font-medium">Issue</th>
                  <th className="py-2 px-2 font-medium">Severity</th>
                  <th className="py-2 px-2 font-medium">Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {riskItems.map((r: SalesManagerRisk, i) => (
                  <tr key={`${r.type}-${i}`} className="border-b border-gray-50">
                    <td className="py-2 px-2 text-xs text-gray-800">{r.issue}</td>
                    <td className="py-2 px-2">
                      <span
                        className={cn(
                          "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                          SEVERITY_STYLES[r.severity] ?? SEVERITY_STYLES.medium,
                        )}
                      >
                        {r.severity}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-xs text-gray-600">{r.recommendation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card p-4 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Sparkles size={16} className="text-violet-600" />
            Executive Briefing
          </p>
          <button
            type="button"
            className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1"
            disabled={briefingMutation.isPending}
            onClick={() => briefingMutation.mutate()}
          >
            {briefingMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Lightbulb size={12} />
            )}
            Generate Briefing
          </button>
        </div>

        {!briefing ? (
          <p className="text-sm text-gray-400">
            Click Generate Briefing for an executive summary (heuristic mode — no AI call unless
            requested via API with use_ai=true).
          </p>
        ) : (
          <>
            <p className="text-sm text-gray-800 leading-relaxed">{briefing.summary}</p>

            {briefing.opportunities.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-emerald-700 mb-1">Opportunities</p>
                <ul className="space-y-1">
                  {briefing.opportunities.map((o, i) => (
                    <li key={i} className="text-sm text-gray-700 flex gap-2">
                      <span className="text-emerald-400">•</span>
                      {o}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {briefing.risks.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-red-700 mb-1">Risks</p>
                <ul className="space-y-1">
                  {briefing.risks.map((r, i) => (
                    <li key={i} className="text-sm text-gray-700 flex gap-2">
                      <span className="text-red-400">•</span>
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {briefing.recommendations.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-brand-700 mb-1">Recommendations</p>
                <ul className="space-y-1">
                  {briefing.recommendations.map((r, i) => (
                    <li key={i} className="text-sm text-gray-700">
                      → {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-[10px] text-gray-400">
              Advisory only — manual actions required. Source: {briefing.source}
            </p>
          </>
        )}
      </div>

      {overview.communication_intelligence &&
        (overview.communication_intelligence.follow_ups_required ?? 0) > 0 && (
        <div className="card p-4 space-y-2 border-teal-100 bg-teal-50/30">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-teal-900">Communication Intelligence</p>
            <Link href="/communication-intelligence" className="text-xs text-brand-700 hover:underline">
              View all →
            </Link>
          </div>
          <p className="text-xs text-gray-700">
            {overview.communication_intelligence.follow_ups_required} follow-up(s) required · avg health{" "}
            {overview.communication_intelligence.avg_health_score ?? 0}/100 ·{" "}
            {overview.communication_intelligence.risk_count ?? 0} comm risk(s) ·{" "}
            {overview.communication_intelligence.opportunity_count ?? 0} comm opportunity(ies)
          </p>
        </div>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-center">
        <div className="card p-3">
          <p className="text-lg font-semibold text-gray-900">{overview.qualified_leads}</p>
          <p className="text-[10px] text-gray-500">Qualified leads</p>
        </div>
        <div className="card p-3">
          <p className="text-lg font-semibold text-amber-700">{overview.neglected_leads}</p>
          <p className="text-[10px] text-gray-500">Neglected leads</p>
        </div>
        <div className="card p-3">
          <p className="text-lg font-semibold text-gray-900">
            {overview.proposal_conversion_rate}%
          </p>
          <p className="text-[10px] text-gray-500">Proposal conversion</p>
        </div>
        <div className="card p-3">
          <p className="text-lg font-semibold text-gray-900">
            {overview.operator_workload.open_tasks}
          </p>
          <p className="text-[10px] text-gray-500">Open operator tasks</p>
        </div>
      </div>
    </div>
  );
}
