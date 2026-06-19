"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleDollarSign,
  Loader2,
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  revenueAttributionApi,
  RevenueAttributionChannelObject,
  RevenueAttributionObject,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

function formatMoney(val: number | string | null | undefined, currency = "UZS"): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n)} ${currency}`;
}

function KpiCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
      {sub && <p className="text-[10px] text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function AttributionTable({
  title,
  rows,
  nameKey,
}: {
  title: string;
  rows: (RevenueAttributionObject | RevenueAttributionChannelObject)[];
  nameKey: "source" | "channel";
}) {
  const active = rows.filter((r) => r.deals > 0 || Number(r.revenue) > 0);
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900">{title}</p>
      {active.length === 0 ? (
        <EmptyState title="No attributed revenue yet" description="Won deals will populate this table." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                <th className="py-2 px-2 font-medium capitalize">{nameKey}</th>
                <th className="py-2 px-2 font-medium text-right">Revenue</th>
                <th className="py-2 px-2 font-medium text-right">Deals</th>
                <th className="py-2 px-2 font-medium text-right">Conversion Rate</th>
              </tr>
            </thead>
            <tbody>
              {active.map((row) => (
                <tr key={String((row as unknown as Record<typeof nameKey, string>)[nameKey])} className="border-b border-gray-50">
                  <td className="py-2 px-2 text-xs font-medium text-gray-900">
                    {row.label || (row as unknown as Record<typeof nameKey, string>)[nameKey]}
                  </td>
                  <td className="py-2 px-2 text-xs text-right tabular-nums text-gray-900">
                    {formatMoney(row.revenue)}
                  </td>
                  <td className="py-2 px-2 text-xs text-right tabular-nums text-gray-600">
                    {row.deals}
                  </td>
                  <td className="py-2 px-2 text-xs text-right tabular-nums text-gray-600">
                    {row.conversion_rate}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function RevenueAttributionPage() {
  const queryClient = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["revenue-attribution-overview"],
    queryFn: () => revenueAttributionApi.overview().then((r) => r.data),
  });

  const { data: sources } = useQuery({
    queryKey: ["revenue-attribution-sources"],
    queryFn: () => revenueAttributionApi.sources().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: channels } = useQuery({
    queryKey: ["revenue-attribution-channels"],
    queryFn: () => revenueAttributionApi.channels().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: insights } = useQuery({
    queryKey: ["revenue-attribution-insights"],
    queryFn: () => revenueAttributionApi.insights().then((r) => r.data),
    enabled: !!overview,
  });

  const recalculateMutation = useMutation({
    mutationFn: () => revenueAttributionApi.recalculate().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ["revenue-attribution-overview"] });
      queryClient.invalidateQueries({ queryKey: ["revenue-attribution-sources"] });
      queryClient.invalidateQueries({ queryKey: ["revenue-attribution-channels"] });
      queryClient.invalidateQueries({ queryKey: ["revenue-attribution-insights"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState message="Loading revenue attribution…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load revenue attribution"}
        onRetry={() => refetch()}
      />
    );
  }

  const currency = overview.currency || "UZS";

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <CircleDollarSign size={22} className="text-emerald-600" />
            Revenue Attribution
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Read-only analytics across CRM, deals, proposals, and channels — no automatic actions
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

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">1. Revenue Overview</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard label="Total Revenue" value={formatMoney(overview.total_revenue, currency)} />
          <KpiCard label="Deals" value={String(overview.deals_won)} />
          <KpiCard label="Avg Deal Size" value={formatMoney(overview.avg_deal_size, currency)} />
          <KpiCard
            label="Conversion Rate"
            value={`${overview.conversion_rate}%`}
            sub={`${overview.total_leads} leads tracked`}
          />
        </div>
      </section>

      <section className="grid lg:grid-cols-2 gap-4">
        <AttributionTable
          title="2. Sources"
          rows={sources?.items ?? []}
          nameKey="source"
        />
        <AttributionTable
          title="3. Channels"
          rows={channels?.items ?? []}
          nameKey="channel"
        />
      </section>

      <section className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900">4. Revenue Insights</p>
        {!insights ? (
          <LoadingState message="Loading insights…" />
        ) : (
          <>
            {insights.summary && (
              <p className="text-sm text-gray-700">{insights.summary}</p>
            )}
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {[
                { key: "best_source", label: "Best source", icon: TrendingUp, tone: "emerald" },
                { key: "best_channel", label: "Best channel", icon: TrendingUp, tone: "sky" },
                { key: "weakest_source", label: "Weakest source", icon: TrendingDown, tone: "amber" },
                { key: "best_proposal_source", label: "Best proposal source", icon: TrendingUp, tone: "violet" },
              ].map(({ key, label, icon: Icon, tone }) => {
                const item = insights[key as keyof typeof insights];
                const insight = item && typeof item === "object" && "label" in item ? item : null;
                return (
                  <div
                    key={key}
                    className={cn(
                      "rounded-lg border px-3 py-3",
                      tone === "emerald" && "border-emerald-100 bg-emerald-50/50",
                      tone === "sky" && "border-sky-100 bg-sky-50/50",
                      tone === "amber" && "border-amber-100 bg-amber-50/50",
                      tone === "violet" && "border-violet-100 bg-violet-50/50",
                    )}
                  >
                    <p className="text-[10px] uppercase tracking-wide text-gray-500 flex items-center gap-1">
                      <Icon size={12} />
                      {label}
                    </p>
                    <p className="text-sm font-semibold text-gray-900 mt-1">
                      {insight?.label ?? "—"}
                    </p>
                    {insight?.value && (
                      <p className="text-[10px] text-gray-500 mt-0.5">{insight.value}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
        <p className="text-[10px] text-gray-400">
          Proposal conversion rate: {overview.proposal_conversion_rate}% ·{" "}
          <Link href="/revenue" className="text-brand-700 hover:underline">
            Commission tracking
          </Link>
        </p>
      </section>
    </div>
  );
}
