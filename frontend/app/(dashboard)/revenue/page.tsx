"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DollarSign,
  TrendingUp,
  Clock,
  CheckCircle,
  Sparkles,
  Loader2,
  AlertTriangle,
  Lightbulb,
  type LucideIcon,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  revenueApi,
  RevenueAiInsights,
  RevenueDealRow,
  CommissionStatus,
} from "@/lib/api";
import { HorizontalBarChart } from "@/components/analytics/SimpleBarChart";
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
  icon: Icon,
  color,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  color: string;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
          <p className="text-xl font-semibold text-gray-900 mt-1 tabular-nums leading-tight">{value}</p>
        </div>
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center", color)}>
          <Icon size={18} />
        </div>
      </div>
    </div>
  );
}

const COMMISSION_STATUS_STYLE: Record<CommissionStatus, string> = {
  pending: "bg-amber-100 text-amber-800 border-amber-200",
  approved: "bg-sky-100 text-sky-800 border-sky-200",
  paid: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

function DealRow({
  deal,
  onApprove,
  onMarkPaid,
  loadingId,
}: {
  deal: RevenueDealRow;
  onApprove: (id: string) => void;
  onMarkPaid: (id: string) => void;
  loadingId: string | null;
}) {
  const status = deal.commission_status;
  const busy = loadingId === deal.deal_id;

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3">
        <Link
          href={`/crm/deals/${deal.deal_id}`}
          className="text-sm font-medium text-gray-900 hover:text-brand-700"
        >
          {deal.title}
        </Link>
        <p className="text-[10px] text-gray-400 capitalize">{deal.attribution_source ?? "other"}</p>
      </td>
      <td className="px-4 py-3 text-sm text-gray-700">{deal.client_name ?? "—"}</td>
      <td className="px-4 py-3 text-sm text-gray-900 tabular-nums text-right">
        {formatMoney(deal.deal_amount, deal.currency)}
      </td>
      <td className="px-4 py-3 text-sm text-gray-600 tabular-nums text-right">
        {deal.commission_percent != null ? `${Number(deal.commission_percent)}%` : "—"}
      </td>
      <td className="px-4 py-3 text-sm text-gray-900 tabular-nums text-right">
        {formatMoney(deal.commission_amount, deal.currency)}
      </td>
      <td className="px-4 py-3">
        {status ? (
          <span
            className={cn(
              "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
              COMMISSION_STATUS_STYLE[status],
            )}
          >
            {status}
          </span>
        ) : (
          <span className="text-xs text-gray-400">—</span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex justify-end gap-1">
          {status === "pending" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onApprove(deal.deal_id)}
              className="text-[10px] px-2 py-1 rounded border border-sky-200 bg-sky-50 text-sky-800 disabled:opacity-50"
            >
              {busy ? "…" : "Approve"}
            </button>
          )}
          {(status === "pending" || status === "approved") && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onMarkPaid(deal.deal_id)}
              className="text-[10px] px-2 py-1 rounded border border-emerald-200 bg-emerald-50 text-emerald-800 disabled:opacity-50"
            >
              {busy ? "…" : "Mark paid"}
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function RevenuePage() {
  const queryClient = useQueryClient();
  const [insights, setInsights] = useState<RevenueAiInsights | null>(null);
  const [actionDealId, setActionDealId] = useState<string | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["revenue-overview"],
    queryFn: () => revenueApi.overview().then((r) => r.data),
  });

  const approveMutation = useMutation({
    mutationFn: (dealId: string) => revenueApi.approveCommission(dealId).then((r) => r.data),
    onMutate: (id) => setActionDealId(id),
    onSettled: () => setActionDealId(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["revenue-overview"] });
      toast.success("Commission approved — tracking only, no payment sent");
    },
    onError: (err: Error) => toast.error(err.message || "Approve failed"),
  });

  const paidMutation = useMutation({
    mutationFn: (dealId: string) => revenueApi.markCommissionPaid(dealId).then((r) => r.data),
    onMutate: (id) => setActionDealId(id),
    onSettled: () => setActionDealId(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["revenue-overview"] });
      toast.success("Commission marked paid — manual record only");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const insightsMutation = useMutation({
    mutationFn: () => revenueApi.aiInsights().then((r) => r.data),
    onSuccess: (d) => {
      setInsights(d);
      toast.success("Revenue insights generated");
    },
    onError: (err: Error) => toast.error(err.message || "Insights failed"),
  });

  if (isLoading) {
    return <LoadingState message="Loading revenue…" />;
  }

  if (isError || !data) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load revenue"}
        onRetry={() => refetch()}
      />
    );
  }

  const chartData = data.attribution_breakdown
    .filter((b) => b.deal_count > 0 || Number(b.revenue) > 0)
    .map((b) => ({
      label: b.label,
      value: Number(b.revenue) || 0,
      sublabel: `${b.deal_count} deals`,
    }));

  const displayChart =
    chartData.length > 0
      ? chartData
      : data.attribution_breakdown.slice(0, 5).map((b) => ({
          label: b.label,
          value: 0,
        }));

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <DollarSign size={22} className="text-emerald-600" />
          Revenue
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Attribution tracking and commission — read-only, no automatic payments
        </p>
      </div>

      <PartialErrorsBanner errors={data.errors} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        <KpiCard
          label="Pipeline value"
          value={formatMoney(data.total_pipeline_value)}
          icon={TrendingUp}
          color="bg-indigo-50 text-indigo-600"
        />
        <KpiCard
          label="Closed revenue"
          value={formatMoney(data.total_closed_revenue)}
          icon={CheckCircle}
          color="bg-emerald-50 text-emerald-600"
        />
        <KpiCard
          label="Our commission"
          value={formatMoney(data.our_commission)}
          icon={DollarSign}
          color="bg-violet-50 text-violet-600"
        />
        <KpiCard
          label="Partner commission"
          value={formatMoney(data.partner_commission)}
          icon={DollarSign}
          color="bg-fuchsia-50 text-fuchsia-600"
        />
        <KpiCard
          label="Total earned"
          value={formatMoney(data.total_commission_earned)}
          icon={DollarSign}
          color="bg-sky-50 text-sky-600"
        />
        <KpiCard
          label="Pending"
          value={formatMoney(data.pending_commission)}
          icon={Clock}
          color="bg-amber-50 text-amber-600"
        />
        <KpiCard
          label="Paid"
          value={formatMoney(data.paid_commission)}
          icon={CheckCircle}
          color="bg-emerald-50 text-emerald-600"
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-3">Attribution by source</p>
          <HorizontalBarChart data={displayChart} barClassName="bg-emerald-500" />
          <p className="text-[10px] text-gray-400 mt-2">
            Won deal revenue by lead attribution source
          </p>
        </div>

        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Sparkles size={16} className="text-violet-600" />
              AI revenue insights
            </p>
            <button
              type="button"
              disabled={insightsMutation.isPending}
              onClick={() => insightsMutation.mutate()}
              className="text-xs px-3 py-1.5 rounded-lg border border-violet-200 bg-violet-50 text-violet-800 disabled:opacity-50 flex items-center gap-1"
            >
              {insightsMutation.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Sparkles size={12} />
              )}
              Analyze
            </button>
          </div>

          {!insights && !insightsMutation.isPending && (
            <p className="text-sm text-gray-500">Generate insights on trends, channels, and forecast.</p>
          )}

          {insights && (
            <>
              <p className="text-sm text-gray-800 leading-relaxed">{insights.summary}</p>
              {insights.risks.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-red-800 flex items-center gap-1 mb-1">
                    <AlertTriangle size={12} /> Risks
                  </p>
                  <ul className="text-xs text-gray-700 space-y-0.5">
                    {insights.risks.map((r, i) => (
                      <li key={i}>• {r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {insights.opportunities.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-emerald-800 flex items-center gap-1 mb-1">
                    <Lightbulb size={12} /> Opportunities
                  </p>
                  <ul className="text-xs text-gray-700 space-y-0.5">
                    {insights.opportunities.map((o, i) => (
                      <li key={i}>• {o}</li>
                    ))}
                  </ul>
                </div>
              )}
              {insights.recommendations.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-700 mb-1">Recommendations</p>
                  <ul className="text-xs text-gray-600 space-y-0.5">
                    {insights.recommendations.map((r, i) => (
                      <li key={i}>→ {r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {(data.attribution_links ?? []).length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900">Attribution links</p>
            <p className="text-[10px] text-gray-400 mt-0.5">Clicks → leads → won deals conversion by tracking link</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
                  <th className="px-4 py-2 font-medium">Link</th>
                  <th className="px-4 py-2 font-medium">Channel</th>
                  <th className="px-4 py-2 font-medium text-right">Clicks</th>
                  <th className="px-4 py-2 font-medium text-right">Leads</th>
                  <th className="px-4 py-2 font-medium text-right">Won</th>
                  <th className="px-4 py-2 font-medium text-right">Revenue</th>
                  <th className="px-4 py-2 font-medium text-right">Commission</th>
                  <th className="px-4 py-2 font-medium text-right">Click→Lead</th>
                  <th className="px-4 py-2 font-medium text-right">Lead→Won</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {(data.attribution_links ?? []).map((link) => (
                  <tr key={link.link_id}>
                    <td className="px-4 py-2">
                      <p className="font-medium text-gray-900">{link.title}</p>
                      <p className="text-[10px] text-gray-400">{link.code}</p>
                    </td>
                    <td className="px-4 py-2 capitalize text-gray-600">{link.channel}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{link.clicks_count}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{link.leads_count}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{link.won_deals_count}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatMoney(link.revenue)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatMoney(link.commission)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{link.click_to_lead_rate}%</td>
                    <td className="px-4 py-2 text-right tabular-nums">{link.lead_to_won_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <p className="text-sm font-semibold text-gray-900">Won deals & commission</p>
          <p className="text-xs text-gray-500">
            {data.deals_won} won · {data.deals_lost} lost
          </p>
        </div>
        {data.deals.length === 0 ? (
          <p className="p-6 text-sm text-gray-400 text-center">
            No won deals yet. Mark a deal won from Deal Room with revenue and commission %.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[10px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
                  <th className="px-4 py-2 font-medium">Deal</th>
                  <th className="px-4 py-2 font-medium">Client</th>
                  <th className="px-4 py-2 font-medium text-right">Revenue</th>
                  <th className="px-4 py-2 font-medium text-right">Commission %</th>
                  <th className="px-4 py-2 font-medium text-right">Commission $</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.deals.map((deal) => (
                  <DealRow
                    key={deal.deal_id}
                    deal={deal}
                    onApprove={(id) => approveMutation.mutate(id)}
                    onMarkPaid={(id) => paidMutation.mutate(id)}
                    loadingId={actionDealId}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
