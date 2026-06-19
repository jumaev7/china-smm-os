"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertTriangle,
  Briefcase,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Target,
  TrendingUp,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  dealRiskApi,
  DealRiskDetail,
  DealRiskLevel,
  DealRiskListItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const RISK_STYLES: Record<DealRiskLevel, string> = {
  healthy: "bg-emerald-100 text-emerald-900 border-emerald-200",
  watchlist: "bg-amber-100 text-amber-900 border-amber-200",
  at_risk: "bg-orange-100 text-orange-900 border-orange-200",
  critical: "bg-red-100 text-red-900 border-red-300",
  stalled: "bg-gray-100 text-gray-800 border-gray-300",
  lost_probability_high: "bg-red-200 text-red-950 border-red-400",
};

const RISK_LABELS: Record<DealRiskLevel, string> = {
  healthy: "Healthy",
  watchlist: "Watchlist",
  at_risk: "At Risk",
  critical: "Critical",
  stalled: "Stalled",
  lost_probability_high: "Lost Prob. High",
};

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function RiskBadge({ level }: { level: DealRiskLevel }) {
  return (
    <span
      className={cn(
        "text-[10px] px-2 py-0.5 rounded-full border font-medium",
        RISK_STYLES[level],
      )}
    >
      {RISK_LABELS[level]}
    </span>
  );
}

function KpiCard({ label, value, level }: { label: string; value: number; level?: DealRiskLevel }) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
      {level && <RiskBadge level={level} />}
    </div>
  );
}

function DealDetailPanel({ detail }: { detail: DealRiskDetail }) {
  return (
    <div className="card p-4 space-y-4 sticky top-4">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400">Deal detail</p>
        <h2 className="text-lg font-semibold text-gray-900 mt-1">{detail.title}</h2>
        {(detail.buyer_name || detail.buyer_company) && (
          <p className="text-sm text-gray-500">
            {[detail.buyer_name, detail.buyer_company].filter(Boolean).join(" · ")}
          </p>
        )}
        <div className="flex flex-wrap gap-2 mt-2">
          <RiskBadge level={detail.risk_level} />
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-orange-50 text-orange-900 border-orange-200 font-semibold tabular-nums">
            Health {detail.deal_health_score}/100
          </span>
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-sky-50 text-sky-900 border-sky-200 font-semibold tabular-nums">
            Close {detail.close_probability}%
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-2">
          <p className="text-[10px] text-gray-500">Expected close</p>
          <p className="font-semibold">
            {detail.expected_close_date
              ? format(parseISO(detail.expected_close_date), "MMM d, yyyy")
              : "—"}
          </p>
        </div>
        <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-2">
          <p className="text-[10px] text-gray-500">Revenue</p>
          <p className="font-semibold tabular-nums">{fmtMoney(detail.expected_value)}</p>
        </div>
      </div>

      {detail.risk_factors.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Health factors</p>
          <ul className="space-y-1">
            {detail.risk_factors.map((r) => (
              <li key={r} className="text-xs text-gray-600 flex items-start gap-1.5">
                <span className="text-brand-600 mt-0.5">•</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.risk_reasons.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Risk factors</p>
          <ul className="space-y-1">
            {detail.risk_reasons.map((r) => (
              <li key={r} className="text-xs text-orange-800 flex items-start gap-1.5 capitalize">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.recommendations.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Recommendations</p>
          <ul className="space-y-1">
            {detail.recommendations.map((r) => (
              <li key={r} className="text-xs text-violet-800 flex items-start gap-1.5">
                <span className="text-violet-600 mt-0.5">→</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.linked_buyer_intelligence && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Buyer intelligence</p>
          <p className="text-xs text-gray-600">
            Score {detail.linked_buyer_intelligence.buyer_score}/100 ·{" "}
            {detail.linked_buyer_intelligence.classification?.replace(/_/g, " ")}
          </p>
          <Link href="/buyer-intelligence" className="text-xs text-brand-700 hover:underline">
            Open Buyer Intelligence →
          </Link>
        </div>
      )}

      {detail.linked_proposals.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Proposals</p>
          <ul className="space-y-1">
            {detail.linked_proposals.map((p) => (
              <li key={p.proposal_id} className="text-xs text-gray-600">
                {p.title} ({p.status})
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.linked_communications.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Communications</p>
          <ul className="space-y-1">
            {detail.linked_communications.map((c) => (
              <li key={c.thread_id} className="text-xs text-gray-600">
                {c.title || c.channel || "Thread"} ({c.message_count} msgs)
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.linked_tasks.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Tasks</p>
          <ul className="space-y-1">
            {detail.linked_tasks.map((t) => (
              <li key={t.task_id} className="text-xs text-gray-600">
                {t.title} ({t.status})
                {t.is_overdue && <span className="text-red-600 ml-1">overdue</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Link href={`/crm/deals/${detail.deal_id}`} className="text-xs text-brand-700 hover:underline">
        Open in CRM →
      </Link>
    </div>
  );
}

export default function DealRiskPage() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filterRisk, setFilterRisk] = useState<DealRiskLevel | "">("");

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["deal-risk-overview"],
    queryFn: () => dealRiskApi.overview().then((r) => r.data),
  });

  const { data: deals } = useQuery({
    queryKey: ["deal-risk-deals", filterRisk],
    queryFn: () =>
      dealRiskApi
        .deals({ risk_level: filterRisk || undefined, limit: 100 })
        .then((r) => r.data),
    enabled: !!overview,
  });

  const { data: highRisk } = useQuery({
    queryKey: ["deal-risk-high"],
    queryFn: () => dealRiskApi.highRisk({ limit: 10 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: opportunities } = useQuery({
    queryKey: ["deal-risk-opportunities"],
    queryFn: () => dealRiskApi.opportunities({ limit: 10 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: detail } = useQuery({
    queryKey: ["deal-risk-detail", selectedId],
    queryFn: () => dealRiskApi.detail(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const recalcMutation = useMutation({
    mutationFn: () => dealRiskApi.recalculate().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["deal-risk"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const selectedRow = useMemo(
    () => deals?.items.find((d) => d.deal_id === selectedId),
    [deals?.items, selectedId],
  );

  if (isLoading) return <LoadingState message="Loading deal risk intelligence…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load deal risk"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <ShieldAlert size={22} className="text-orange-600" />
            Deal Risk Engine
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Read-only deal health intelligence — no automatic CRM, messaging, or task actions
          </p>
        </div>
        <button
          type="button"
          onClick={() => recalcMutation.mutate()}
          disabled={recalcMutation.isPending}
          className="btn-secondary text-sm flex items-center gap-1.5"
        >
          {recalcMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )}
          Recalculate
        </button>
      </div>

      <PartialErrorsBanner errors={overview.errors} />

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">1. Risk Overview</p>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard label="Healthy Deals" value={overview.healthy_deals} level="healthy" />
          <KpiCard
            label="At Risk Deals"
            value={overview.at_risk_deals + overview.critical_deals}
            level="at_risk"
          />
          <KpiCard label="Critical Deals" value={overview.critical_deals} level="critical" />
          <KpiCard
            label="High Close Probability"
            value={overview.high_close_probability_deals}
            level="healthy"
          />
        </div>
        <p className="text-xs text-gray-500">
          Avg health {overview.average_health_score}/100 · At-risk revenue{" "}
          {fmtMoney(overview.total_at_risk_revenue)} UZS
        </p>
      </section>

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <section className="card p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                <Briefcase size={16} className="text-brand-600" />
                2. Deal Table
              </p>
              <select
                className="input text-xs w-40"
                value={filterRisk}
                onChange={(e) => setFilterRisk(e.target.value as DealRiskLevel | "")}
              >
                <option value="">All risk levels</option>
                {(Object.keys(RISK_LABELS) as DealRiskLevel[]).map((k) => (
                  <option key={k} value={k}>
                    {RISK_LABELS[k]}
                  </option>
                ))}
              </select>
            </div>
            {!deals?.items.length ? (
              <EmptyState title="No deals" description="Active CRM deals will appear here." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-gray-500 border-b border-gray-100">
                      <th className="pb-2 pr-2">Deal</th>
                      <th className="pb-2 pr-2">Buyer</th>
                      <th className="pb-2 pr-2">Health</th>
                      <th className="pb-2 pr-2">Risk</th>
                      <th className="pb-2 pr-2">Close %</th>
                      <th className="pb-2 pr-2">Expected Close</th>
                      <th className="pb-2">Revenue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deals.items.map((row: DealRiskListItem) => (
                      <tr
                        key={row.deal_id}
                        onClick={() => setSelectedId(row.deal_id)}
                        className={cn(
                          "border-b border-gray-50 cursor-pointer hover:bg-brand-50/40",
                          selectedId === row.deal_id && "bg-brand-50/60",
                        )}
                      >
                        <td className="py-2 pr-2 font-medium text-gray-900">{row.title}</td>
                        <td className="py-2 pr-2 text-gray-600">{row.buyer_name ?? "—"}</td>
                        <td className="py-2 pr-2 tabular-nums font-semibold">{row.deal_health_score}</td>
                        <td className="py-2 pr-2">
                          <RiskBadge level={row.risk_level} />
                        </td>
                        <td className="py-2 pr-2 tabular-nums">{row.close_probability}%</td>
                        <td className="py-2 pr-2">
                          {row.expected_close_date
                            ? format(parseISO(row.expected_close_date), "MMM d")
                            : "—"}
                        </td>
                        <td className="py-2 tabular-nums">{fmtMoney(row.revenue)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <AlertTriangle size={16} className="text-red-600" />
              4. High Risk Deals
            </p>
            {!highRisk?.items.length ? (
              <EmptyState title="No high-risk deals" description="Pipeline risk is manageable." />
            ) : (
              <ol className="space-y-2">
                {highRisk.items.map((row) => (
                  <li
                    key={row.deal_id}
                    className="flex items-start gap-2 text-sm border-b border-gray-50 pb-2 cursor-pointer hover:bg-gray-50/80 rounded px-1"
                    onClick={() => setSelectedId(row.deal_id)}
                  >
                    <span className="font-bold text-red-700 w-5">{row.rank}</span>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-gray-900">{row.title}</p>
                      <p className="text-xs text-gray-500">
                        Health {row.deal_health_score} · Close {row.close_probability}% ·{" "}
                        {fmtMoney(row.revenue)} UZS
                      </p>
                      <RiskBadge level={row.risk_level} />
                    </div>
                  </li>
                ))}
              </ol>
            )}
            {highRisk && highRisk.largest_at_risk_revenue != null && (
              <p className="text-[10px] text-gray-400">
                Largest at-risk revenue: {fmtMoney(highRisk.largest_at_risk_revenue)} ·{" "}
                {highRisk.requiring_intervention} requiring intervention
              </p>
            )}
          </section>

          <section className="card p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <TrendingUp size={16} className="text-emerald-600" />
              5. Opportunities
            </p>
            {!opportunities?.items.length ? (
              <EmptyState title="No high-probability deals" description="No deals above 70% close probability." />
            ) : (
              <ol className="space-y-2">
                {opportunities.items.map((row) => (
                  <li
                    key={row.deal_id}
                    className="flex items-start gap-2 text-sm border-b border-gray-50 pb-2 cursor-pointer hover:bg-gray-50/80 rounded px-1"
                    onClick={() => setSelectedId(row.deal_id)}
                  >
                    <span className="font-bold text-emerald-700 w-5">{row.rank}</span>
                    <div>
                      <p className="font-medium text-gray-900">{row.title}</p>
                      <p className="text-xs text-gray-500">
                        Close {row.close_probability}% · Health {row.deal_health_score} ·{" "}
                        {fmtMoney(row.revenue)} UZS
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
            {opportunities && (
              <p className="text-[10px] text-gray-400">
                {opportunities.likely_close_this_month} deal(s) likely to close this month
              </p>
            )}
          </section>
        </div>

        <div>
          <p className="text-sm font-semibold text-gray-900 mb-3">3. Deal Detail</p>
          {detail ? (
            <DealDetailPanel detail={detail} />
          ) : selectedRow ? (
            <div className="card p-4">
              <LoadingState message="Loading deal detail…" />
            </div>
          ) : (
            <div className="card p-4">
              <EmptyState
                title="Select a deal"
                description="Click a row in the deal table to view risk analysis."
              />
            </div>
          )}
        </div>
      </div>

      <p className="text-[10px] text-gray-400">{overview.safety_notice}</p>
    </div>
  );
}
