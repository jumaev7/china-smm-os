"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertTriangle,
  Crown,
  Flame,
  Loader2,
  RefreshCw,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  buyerIntelligenceApi,
  BuyerClassification,
  BuyerIntelligenceDetail,
  BuyerListItem,
  BuyerRiskLevel,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const CLASSIFICATION_STYLES: Record<BuyerClassification, string> = {
  hot_buyer: "bg-red-100 text-red-900 border-red-200",
  strategic_buyer: "bg-indigo-100 text-indigo-900 border-indigo-200",
  high_potential_buyer: "bg-violet-100 text-violet-900 border-violet-200",
  active_buyer: "bg-emerald-100 text-emerald-900 border-emerald-200",
  inactive_buyer: "bg-gray-100 text-gray-700 border-gray-200",
  price_sensitive_buyer: "bg-amber-100 text-amber-900 border-amber-200",
  at_risk_buyer: "bg-orange-100 text-orange-900 border-orange-200",
};

const CLASSIFICATION_LABELS: Record<BuyerClassification, string> = {
  hot_buyer: "Hot Buyer",
  strategic_buyer: "Strategic Buyer",
  high_potential_buyer: "High Potential",
  active_buyer: "Active Buyer",
  inactive_buyer: "Inactive Buyer",
  price_sensitive_buyer: "Price Sensitive",
  at_risk_buyer: "At Risk",
};

const RISK_STYLES: Record<BuyerRiskLevel, string> = {
  low: "bg-emerald-50 text-emerald-800 border-emerald-200",
  medium: "bg-amber-50 text-amber-800 border-amber-200",
  high: "bg-orange-50 text-orange-800 border-orange-200",
  critical: "bg-red-50 text-red-900 border-red-300",
};

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function ClassificationBadge({ classification }: { classification: BuyerClassification }) {
  return (
    <span
      className={cn(
        "text-[10px] px-2 py-0.5 rounded-full border font-medium",
        CLASSIFICATION_STYLES[classification],
      )}
    >
      {CLASSIFICATION_LABELS[classification]}
    </span>
  );
}

function KpiCard({
  label,
  value,
  classification,
}: {
  label: string;
  value: number;
  classification: BuyerClassification;
}) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
      <ClassificationBadge classification={classification} />
    </div>
  );
}

function BuyerDetailPanel({ detail }: { detail: BuyerIntelligenceDetail }) {
  return (
    <div className="card p-4 space-y-4 sticky top-4">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400">Buyer detail</p>
        <h2 className="text-lg font-semibold text-gray-900 mt-1">{detail.name}</h2>
        {detail.company && <p className="text-sm text-gray-500">{detail.company}</p>}
        <div className="flex flex-wrap gap-2 mt-2">
          <ClassificationBadge classification={detail.classification} />
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-orange-50 text-orange-900 border-orange-200 font-semibold tabular-nums">
            {detail.buyer_score}/100
          </span>
          <span className={cn("text-[10px] px-2 py-0.5 rounded-full border capitalize", RISK_STYLES[detail.risk_level])}>
            Risk: {detail.risk_level}
          </span>
        </div>
        {(detail.country || detail.industry) && (
          <p className="text-xs text-gray-500 mt-1">
            {[detail.country, detail.industry].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-2">
          <p className="text-[10px] text-gray-500">Annual potential</p>
          <p className="font-semibold tabular-nums">{fmtMoney(detail.potential.expected_annual_revenue)}</p>
        </div>
        <div className="rounded-lg border border-gray-100 bg-gray-50/50 p-2">
          <p className="text-[10px] text-gray-500">Deal size</p>
          <p className="font-semibold tabular-nums">{fmtMoney(detail.potential.expected_deal_size)}</p>
        </div>
      </div>

      {detail.insights.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Insights</p>
          <ul className="space-y-1">
            {detail.insights.map((r) => (
              <li key={r} className="text-xs text-gray-600 flex items-start gap-1.5">
                <span className="text-brand-600 mt-0.5">•</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.risks.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Risks</p>
          <ul className="space-y-1">
            {detail.risks.map((r) => (
              <li key={r} className="text-xs text-orange-800 capitalize">
                {r.replace(/_/g, " ")}
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
              <li key={r} className="text-xs text-gray-700">
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.linked_deals.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Linked deals</p>
          <ul className="space-y-1">
            {detail.linked_deals.map((d) => (
              <li key={d.deal_id} className="text-xs text-gray-600">
                {d.title} <span className="text-gray-400">({d.status})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.linked_proposals.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Linked proposals</p>
          <ul className="space-y-1">
            {detail.linked_proposals.map((p) => (
              <li key={p.proposal_id} className="text-xs text-gray-600">
                {p.title} <span className="text-gray-400">({p.status})</span>
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

      <Link href={`/crm?lead=${detail.buyer_id}`} className="text-xs text-brand-700 hover:underline">
        Open in CRM →
      </Link>
    </div>
  );
}

export default function BuyerIntelligencePage() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filterClass, setFilterClass] = useState<BuyerClassification | "">("");

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["buyer-intelligence-overview"],
    queryFn: () => buyerIntelligenceApi.overview().then((r) => r.data),
  });

  const { data: buyers } = useQuery({
    queryKey: ["buyer-intelligence-buyers", filterClass],
    queryFn: () =>
      buyerIntelligenceApi
        .buyers({
          classification: filterClass || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!overview,
  });

  const { data: topBuyers } = useQuery({
    queryKey: ["buyer-intelligence-top"],
    queryFn: () => buyerIntelligenceApi.topBuyers({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: risks } = useQuery({
    queryKey: ["buyer-intelligence-risks"],
    queryFn: () => buyerIntelligenceApi.risks({ limit: 20 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: detail } = useQuery({
    queryKey: ["buyer-intelligence-detail", selectedId],
    queryFn: () => buyerIntelligenceApi.detail(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const recalcMutation = useMutation({
    mutationFn: () => buyerIntelligenceApi.recalculate().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["buyer-intelligence"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const selectedRow = useMemo(
    () => buyers?.items.find((b) => b.buyer_id === selectedId),
    [buyers?.items, selectedId],
  );

  if (isLoading) return <LoadingState message="Loading buyer intelligence…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load buyer intelligence"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Users size={22} className="text-brand-600" />
            Buyer Intelligence
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Read-only buyer scoring — no automatic CRM, deal, or messaging actions
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
      <p className="text-xs text-gray-500">{overview.safety_notice}</p>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">1. Buyer Overview</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Hot Buyers" value={overview.hot_buyers} classification="hot_buyer" />
          <KpiCard label="Strategic Buyers" value={overview.strategic_buyers} classification="strategic_buyer" />
          <KpiCard label="High Potential" value={overview.high_potential_buyers} classification="high_potential_buyer" />
          <KpiCard label="At Risk" value={overview.at_risk_buyers} classification="at_risk_buyer" />
        </div>
        <p className="text-xs text-gray-500">
          {overview.total_buyers} buyers evaluated · avg score {overview.average_buyer_score}/100
        </p>
      </section>

      <div className="grid lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">2. Buyer Table</p>
            <select
              value={filterClass}
              onChange={(e) => setFilterClass(e.target.value as BuyerClassification | "")}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1"
            >
              <option value="">All classifications</option>
              {(Object.keys(CLASSIFICATION_LABELS) as BuyerClassification[]).map((c) => (
                <option key={c} value={c}>
                  {CLASSIFICATION_LABELS[c]}
                </option>
              ))}
            </select>
          </div>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80 text-left text-[10px] uppercase tracking-wide text-gray-500">
                  <th className="px-3 py-2">Buyer</th>
                  <th className="px-3 py-2 hidden sm:table-cell">Country</th>
                  <th className="px-3 py-2 hidden md:table-cell">Industry</th>
                  <th className="px-3 py-2">Score</th>
                  <th className="px-3 py-2">Class</th>
                  <th className="px-3 py-2 hidden lg:table-cell">Potential</th>
                  <th className="px-3 py-2">Risk</th>
                </tr>
              </thead>
              <tbody>
                {(buyers?.items ?? []).map((row: BuyerListItem) => (
                  <tr
                    key={row.buyer_id}
                    onClick={() => setSelectedId(row.buyer_id)}
                    className={cn(
                      "border-b border-gray-50 cursor-pointer hover:bg-brand-50/30",
                      selectedId === row.buyer_id && "bg-brand-50/50",
                    )}
                  >
                    <td className="px-3 py-2">
                      <p className="font-medium text-gray-900">{row.name}</p>
                      {row.company && <p className="text-[10px] text-gray-500">{row.company}</p>}
                    </td>
                    <td className="px-3 py-2 hidden sm:table-cell text-xs text-gray-600">
                      {row.country || "—"}
                    </td>
                    <td className="px-3 py-2 hidden md:table-cell text-xs text-gray-600 capitalize">
                      {row.industry || "—"}
                    </td>
                    <td className="px-3 py-2 font-semibold tabular-nums">{row.buyer_score}</td>
                    <td className="px-3 py-2">
                      <ClassificationBadge classification={row.classification} />
                    </td>
                    <td className="px-3 py-2 hidden lg:table-cell text-xs tabular-nums">
                      {fmtMoney(row.annual_potential)}
                    </td>
                    <td className="px-3 py-2">
                      <span className={cn("text-[10px] px-1.5 py-0.5 rounded border capitalize", RISK_STYLES[row.risk_level])}>
                        {row.risk_level}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(buyers?.items?.length ?? 0) === 0 && (
              <EmptyState title="No buyers" description="Add CRM leads to evaluate buyer intelligence." />
            )}
          </div>
        </section>

        <section>
          <p className="text-sm font-semibold text-gray-900 mb-3">3. Buyer Detail</p>
          {detail ? (
            <BuyerDetailPanel detail={detail} />
          ) : selectedRow ? (
            <LoadingState message="Loading buyer…" />
          ) : (
            <div className="card p-4 text-sm text-gray-500">Select a buyer from the table</div>
          )}
        </section>
      </div>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Crown size={16} className="text-amber-600" />
          4. Top Buyers
        </p>
        <div className="grid md:grid-cols-3 gap-4">
          {(["top_buyers", "fastest_growing", "highest_revenue"] as const).map((key) => (
            <div key={key} className="card p-4 space-y-2">
              <p className="text-xs font-semibold text-gray-700 capitalize">
                {key.replace(/_/g, " ")}
              </p>
              {(topBuyers?.[key] ?? []).length === 0 ? (
                <p className="text-xs text-gray-400">No data</p>
              ) : (
                <ol className="space-y-2">
                  {topBuyers![key].map((r) => (
                    <li key={r.buyer_id} className="flex items-start gap-2 text-xs">
                      <span className="font-bold text-brand-700 w-4">{r.rank}</span>
                      <div>
                        <button
                          type="button"
                          onClick={() => setSelectedId(r.buyer_id)}
                          className="font-medium text-gray-900 hover:text-brand-700 text-left"
                        >
                          {r.name}
                        </button>
                        <p className="text-gray-500">
                          Score {r.buyer_score} · {fmtMoney(r.annual_potential)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <AlertTriangle size={16} className="text-orange-600" />
          5. Buyer Risks
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          {(risks?.items ?? []).map((r) => (
            <button
              key={r.buyer_id}
              type="button"
              onClick={() => setSelectedId(r.buyer_id)}
              className="card p-3 text-left hover:ring-1 hover:ring-orange-200 transition-shadow"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-gray-900">{r.name}</p>
                <span className={cn("text-[10px] px-1.5 py-0.5 rounded border capitalize shrink-0", RISK_STYLES[r.risk_level])}>
                  {r.risk_level}
                </span>
              </div>
              <p className="text-xs text-gray-600 mt-1">{r.description}</p>
              <div className="flex flex-wrap gap-1 mt-2">
                <ClassificationBadge classification={r.classification} />
                <span className="text-[10px] text-gray-400">Score {r.buyer_score}</span>
              </div>
            </button>
          ))}
        </div>
        {(risks?.items?.length ?? 0) === 0 && (
          <p className="text-sm text-gray-500">No elevated buyer risks flagged.</p>
        )}
      </section>
    </div>
  );
}
