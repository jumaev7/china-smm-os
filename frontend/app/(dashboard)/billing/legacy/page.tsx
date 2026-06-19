"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  CreditCard,
  Users,
  AlertCircle,
  TrendingUp,
  FileText,
  ArrowLeft,
  type LucideIcon,
} from "lucide-react";
import { billingApi, BillingOverviewClientUsage } from "@/lib/api";
import { BILLING_STATUS_CONFIG, cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";

function StatCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: LucideIcon;
  color: string;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
          <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
        </div>
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center", color)}>
          <Icon size={18} />
        </div>
      </div>
    </div>
  );
}

function UsageRow({ row }: { row: BillingOverviewClientUsage }) {
  const statusCfg = BILLING_STATUS_CONFIG[row.billing_status];
  const limit = row.monthly_post_limit;
  const pct =
    limit && limit > 0
      ? Math.min(100, Math.round((row.posts_published_this_cycle / limit) * 100))
      : null;

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3">
        <Link
          href={`/clients/${row.client_id}`}
          className="text-sm font-medium text-gray-900 hover:text-brand-700"
        >
          {row.company_name}
        </Link>
        {row.plan_name && (
          <p className="text-[11px] text-gray-400 mt-0.5">{row.plan_name}</p>
        )}
      </td>
      <td className="px-4 py-3">
        <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-medium", statusCfg.color)}>
          {statusCfg.label}
        </span>
        {row.near_limit && (
          <span className="ml-1 text-[10px] px-2 py-0.5 rounded-full border font-medium bg-orange-100 text-orange-800 border-orange-200">
            Near limit
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-gray-600 tabular-nums text-right">
        {row.posts_created_this_cycle}
      </td>
      <td className="px-4 py-3 text-xs text-gray-600 tabular-nums text-right">
        {row.posts_published_this_cycle}
      </td>
      <td className="px-4 py-3 text-xs text-gray-600 tabular-nums text-right">
        {row.posts_remaining != null ? row.posts_remaining : "∞"}
      </td>
      <td className="px-4 py-3 min-w-[120px]">
        {pct != null ? (
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full bg-gray-200 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full",
                  row.near_limit ? "bg-orange-500" : "bg-brand-600",
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-[10px] text-gray-500 tabular-nums w-8">{pct}%</span>
          </div>
        ) : (
          <span className="text-[11px] text-gray-300">—</span>
        )}
      </td>
    </tr>
  );
}

export default function LegacyBillingPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["billing-overview"],
    queryFn: () => billingApi.overview().then((r) => r.data),
  });

  if (isLoading) {
    return <LoadingState message="Loading billing…" />;
  }

  if (isError || !data) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load billing"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <Link href="/billing" className="text-xs text-brand-700 hover:underline flex items-center gap-1 mb-4">
        <ArrowLeft size={12} /> Subscription billing
      </Link>
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <CreditCard size={20} className="text-amber-600" />
          Legacy Client Billing
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Client subscription plans and monthly post usage.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <StatCard
          label="MRR"
          value={`$${data.monthly_recurring_revenue.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          icon={TrendingUp}
          color="bg-emerald-50 text-emerald-600"
        />
        <StatCard
          label="Active clients"
          value={data.active_clients}
          icon={Users}
          color="bg-sky-50 text-sky-600"
        />
        <StatCard
          label="Unpaid clients"
          value={data.unpaid_clients}
          icon={AlertCircle}
          color="bg-red-50 text-red-600"
        />
        <StatCard
          label="Posts published (cycle)"
          value={data.total_posts_used}
          icon={FileText}
          color="bg-violet-50 text-violet-600"
        />
      </div>

      {data.clients_near_limit.length > 0 && (
        <div className="card p-4 mb-6 border-orange-200 bg-orange-50/50">
          <h2 className="text-sm font-semibold text-orange-900 mb-2 flex items-center gap-1.5">
            <AlertCircle size={14} /> Clients near limit ({data.clients_near_limit.length})
          </h2>
          <ul className="text-xs text-orange-800 space-y-1">
            {data.clients_near_limit.map((c) => (
              <li key={c.client_id}>
                <Link href={`/clients/${c.client_id}`} className="hover:underline font-medium">
                  {c.company_name}
                </Link>
                {" — "}
                {c.posts_published_this_cycle}
                {c.monthly_post_limit != null ? ` / ${c.monthly_post_limit} posts` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-800">Usage by client</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Client</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Status</th>
                <th className="text-right px-4 py-2.5 text-xs font-medium text-gray-500">Created</th>
                <th className="text-right px-4 py-2.5 text-xs font-medium text-gray-500">Published</th>
                <th className="text-right px-4 py-2.5 text-xs font-medium text-gray-500">Remaining</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Usage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.usage_by_client.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No clients yet.
                  </td>
                </tr>
              ) : (
                data.usage_by_client.map((row) => <UsageRow key={row.client_id} row={row} />)
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
