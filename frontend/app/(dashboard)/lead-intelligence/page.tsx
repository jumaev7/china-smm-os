"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Brain,
  Contact,
  FileSignature,
  Flame,
  Loader2,
  MessagesSquare,
  RefreshCw,
  Snowflake,
  Sprout,
  Thermometer,
  type LucideIcon,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  leadIntelligenceApi,
  LeadClassification,
  LeadClassificationDetail,
  LeadClassificationListItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const CLASSIFICATION_STYLES: Record<LeadClassification, string> = {
  hot: "bg-red-100 text-red-900 border-red-200",
  qualified: "bg-violet-100 text-violet-900 border-violet-200",
  nurturing: "bg-emerald-100 text-emerald-900 border-emerald-200",
  cold: "bg-sky-100 text-sky-900 border-sky-200",
  inactive: "bg-gray-100 text-gray-700 border-gray-200",
};

const CLASSIFICATION_ICONS: Record<LeadClassification, LucideIcon> = {
  hot: Flame,
  qualified: Thermometer,
  nurturing: Sprout,
  cold: Snowflake,
  inactive: Contact,
};

function KpiCard({
  label,
  value,
  classification,
}: {
  label: string;
  value: number;
  classification: LeadClassification;
}) {
  const Icon = CLASSIFICATION_ICONS[classification];
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
          <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
        </div>
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center border", CLASSIFICATION_STYLES[classification])}>
          <Icon size={18} />
        </div>
      </div>
    </div>
  );
}

function ClassificationBadge({ classification }: { classification: LeadClassification }) {
  return (
    <span
      className={cn(
        "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
        CLASSIFICATION_STYLES[classification],
      )}
    >
      {classification}
    </span>
  );
}

function LeadDetailPanel({ detail }: { detail: LeadClassificationDetail }) {
  return (
    <div className="card p-4 space-y-4 sticky top-4">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400">Lead detail</p>
        <h2 className="text-lg font-semibold text-gray-900 mt-1">{detail.name}</h2>
        {detail.company && <p className="text-sm text-gray-500">{detail.company}</p>}
        <div className="flex flex-wrap gap-2 mt-2">
          <ClassificationBadge classification={detail.classification} />
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-orange-50 text-orange-900 border-orange-200 font-semibold tabular-nums">
            {detail.score}/100
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-gray-50 text-gray-600 capitalize">
            {detail.status}
          </span>
        </div>
      </div>

      {detail.reasons.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Reasons</p>
          <ul className="space-y-1">
            {detail.reasons.map((r) => (
              <li key={r} className="text-xs text-gray-600 flex items-start gap-1.5">
                <span className="text-brand-600 mt-0.5">•</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-2">
        <p className="text-xs font-semibold text-gray-900">Recommendations</p>
        <p className="text-xs text-gray-700">{detail.recommendations.next_recommended_action}</p>
        {detail.recommendations.follow_up_recommendation && (
          <p className="text-xs text-gray-500">
            Follow-up: {detail.recommendations.follow_up_recommendation}
          </p>
        )}
        {detail.recommendations.proposal_recommendation && (
          <p className="text-xs text-gray-500">
            Proposal: {detail.recommendations.proposal_recommendation}
          </p>
        )}
        <span className="inline-block text-[10px] px-2 py-0.5 rounded-full border bg-amber-50 text-amber-800 border-amber-200 capitalize">
          Urgency: {detail.recommendations.urgency_level}
        </span>
      </div>

      <div>
        <p className="text-xs font-semibold text-gray-900 mb-1 flex items-center gap-1">
          <Contact size={12} /> Linked CRM
        </p>
        <Link
          href={`/crm?lead=${detail.lead_id}`}
          className="text-xs text-brand-700 hover:underline"
        >
          Open in CRM →
        </Link>
      </div>

      {detail.linked_threads.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1 flex items-center gap-1">
            <MessagesSquare size={12} /> Inbox conversations
          </p>
          <ul className="space-y-1">
            {detail.linked_threads.map((t) => (
              <li key={t.thread_id} className="text-xs text-gray-600">
                {t.title || t.channel || "Thread"} · {t.message_count} msg(s)
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.linked_proposals.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1 flex items-center gap-1">
            <FileSignature size={12} /> Proposals
          </p>
          <ul className="space-y-1">
            {detail.linked_proposals.map((p) => (
              <li key={p.proposal_id}>
                <Link
                  href={`/proposals/${p.proposal_id}`}
                  className="text-xs text-brand-700 hover:underline"
                >
                  {p.title} ({p.status})
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function LeadIntelligencePage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [classificationFilter, setClassificationFilter] = useState<LeadClassification | "">("");
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [activityFilter, setActivityFilter] = useState<"all" | "active" | "stale" | "inactive">("all");

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["lead-intelligence-overview"],
    queryFn: () => leadIntelligenceApi.overview().then((r) => r.data),
  });

  const listParams = useMemo(
    () => ({
      classification: classificationFilter || undefined,
      min_score: minScore ? Number(minScore) : undefined,
      max_score: maxScore ? Number(maxScore) : undefined,
      activity: activityFilter,
      limit: 100,
    }),
    [classificationFilter, minScore, maxScore, activityFilter],
  );

  const { data: leadsData, isLoading: leadsLoading } = useQuery({
    queryKey: ["lead-intelligence-leads", listParams],
    queryFn: () => leadIntelligenceApi.leads(listParams).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: detail } = useQuery({
    queryKey: ["lead-intelligence-detail", selectedId],
    queryFn: () => leadIntelligenceApi.detail(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const recalculateMutation = useMutation({
    mutationFn: () => leadIntelligenceApi.recalculate().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ["lead-intelligence-overview"] });
      queryClient.invalidateQueries({ queryKey: ["lead-intelligence-leads"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState message="Loading lead intelligence…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load lead intelligence"}
        onRetry={() => refetch()}
      />
    );
  }

  const items = leadsData?.items ?? [];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Brain size={22} className="text-brand-600" />
            Lead Intelligence
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Read-only lead classification — no automatic CRM or messaging changes
          </p>
        </div>
        <button
          type="button"
          disabled={recalculateMutation.isPending}
          onClick={() => recalculateMutation.mutate()}
          className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 bg-brand-50 text-brand-800 hover:bg-brand-100 disabled:opacity-50 flex items-center gap-1"
        >
          {recalculateMutation.isPending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <RefreshCw size={12} />
          )}
          Recalculate
        </button>
      </div>

      <PartialErrorsBanner errors={overview.errors} />

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <KpiCard label="Hot" value={overview.hot_leads} classification="hot" />
        <KpiCard label="Qualified" value={overview.qualified_leads} classification="qualified" />
        <KpiCard label="Nurturing" value={overview.nurturing_leads} classification="nurturing" />
        <KpiCard label="Cold" value={overview.cold_leads} classification="cold" />
        <KpiCard label="Inactive" value={overview.inactive_leads} classification="inactive" />
      </div>

      <div className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900">Filters</p>
        <div className="flex flex-wrap gap-3">
          <select
            value={classificationFilter}
            onChange={(e) => setClassificationFilter(e.target.value as LeadClassification | "")}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="">All classifications</option>
            <option value="hot">Hot</option>
            <option value="qualified">Qualified</option>
            <option value="nurturing">Nurturing</option>
            <option value="cold">Cold</option>
            <option value="inactive">Inactive</option>
          </select>
          <input
            type="number"
            min={0}
            max={100}
            placeholder="Min score"
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 w-24"
          />
          <input
            type="number"
            min={0}
            max={100}
            placeholder="Max score"
            value={maxScore}
            onChange={(e) => setMaxScore(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 w-24"
          />
          <select
            value={activityFilter}
            onChange={(e) => setActivityFilter(e.target.value as typeof activityFilter)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="all">All activity</option>
            <option value="active">Active</option>
            <option value="stale">Stale</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">
            Leads ({leadsData?.total ?? 0})
          </p>
          {leadsLoading ? (
            <LoadingState message="Loading leads…" />
          ) : items.length === 0 ? (
            <EmptyState title="No leads match filters" description="Adjust filters or add CRM leads." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                    <th className="py-2 px-2 font-medium">Lead</th>
                    <th className="py-2 px-2 font-medium">Company</th>
                    <th className="py-2 px-2 font-medium">Score</th>
                    <th className="py-2 px-2 font-medium">Classification</th>
                    <th className="py-2 px-2 font-medium">Last Activity</th>
                    <th className="py-2 px-2 font-medium">Recommended Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((lead: LeadClassificationListItem) => (
                    <tr
                      key={lead.lead_id}
                      onClick={() => setSelectedId(lead.lead_id)}
                      className={cn(
                        "border-b border-gray-50 cursor-pointer hover:bg-brand-50/30",
                        selectedId === lead.lead_id && "bg-brand-50/50",
                      )}
                    >
                      <td className="py-2 px-2 text-xs font-medium text-gray-900">{lead.name}</td>
                      <td className="py-2 px-2 text-xs text-gray-500">{lead.company || "—"}</td>
                      <td className="py-2 px-2 text-xs tabular-nums font-semibold text-orange-800">
                        {lead.score}
                      </td>
                      <td className="py-2 px-2">
                        <ClassificationBadge classification={lead.classification} />
                      </td>
                      <td className="py-2 px-2 text-xs text-gray-500">
                        {lead.last_activity_at
                          ? format(parseISO(lead.last_activity_at), "MMM d, yyyy")
                          : "—"}
                      </td>
                      <td className="py-2 px-2 text-xs text-gray-600 max-w-[200px] truncate">
                        {lead.recommended_action}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div>
          {selectedId && detail ? (
            <LeadDetailPanel detail={detail} />
          ) : (
            <div className="card p-4 text-sm text-gray-500">
              Select a lead to view classification detail, reasons, and linked records.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
