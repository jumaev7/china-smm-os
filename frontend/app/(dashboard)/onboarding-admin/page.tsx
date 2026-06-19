"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, CheckCircle2, RefreshCw, RotateCcw, Users } from "lucide-react";
import toast from "react-hot-toast";
import { tenantOnboardingApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";

export default function OnboardingAdminPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <OnboardingAdminContent />
    </AdminAuthGuard>
  );
}

function OnboardingAdminContent() {
  const qc = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["onboarding-admin-analytics"],
    queryFn: () => tenantOnboardingApi.adminAnalytics().then((r) => r.data),
  });

  const reset = useMutation({
    mutationFn: (tenantId: string) => tenantOnboardingApi.adminReset(tenantId).then((r) => r.data),
    onSuccess: () => {
      toast.success("Onboarding reset");
      qc.invalidateQueries({ queryKey: ["onboarding-admin-analytics"] });
    },
  });

  const complete = useMutation({
    mutationFn: (tenantId: string) => tenantOnboardingApi.adminComplete(tenantId).then((r) => r.data),
    onSuccess: () => {
      toast.success("Marked complete");
      qc.invalidateQueries({ queryKey: ["onboarding-admin-analytics"] });
    },
  });

  if (isLoading) return <LoadingState message="Loading onboarding analytics…" />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load analytics"}
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) return null;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <BarChart3 size={22} className="text-brand-600" />
            Factory Onboarding Analytics
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Completion rates, drop-off points, and tenant setup progress.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Total tenants" value={data.total_tenants} icon={Users} iconClassName="bg-sky-50 text-sky-600" />
        <KpiCard
          label="Completion rate"
          value={`${data.completion_rate_percent}%`}
          icon={CheckCircle2}
          iconClassName="bg-emerald-50 text-emerald-600"
        />
        <KpiCard label="Started" value={data.started_count} icon={BarChart3} iconClassName="bg-violet-50 text-violet-600" />
        <KpiCard label="Demo data used" value={data.demo_data_usage_count} icon={RefreshCw} iconClassName="bg-amber-50 text-amber-600" />
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
        {[
          ["Avg. time to content (h)", data.avg_time_to_first_content_hours],
          ["Avg. time to lead (h)", data.avg_time_to_first_lead_hours],
          ["Avg. time to proposal (h)", data.avg_time_to_first_proposal_hours],
          ["Avg. time to Growth Center (h)", data.avg_time_to_growth_center_hours],
        ].map(([label, val]) => (
          <div key={String(label)} className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-gray-500 text-xs">{label}</p>
            <p className="font-semibold text-gray-900 mt-1">{val ?? "—"}</p>
          </div>
        ))}
      </div>

      {Object.keys(data.drop_off_by_step).length > 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="font-semibold text-gray-900 mb-3">Drop-off by step</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.drop_off_by_step).map(([step, count]) => (
              <span key={step} className="text-xs bg-amber-50 text-amber-900 px-2 py-1 rounded-full">
                {step.replace(/_/g, " ")}: {count}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-gray-500">
            <tr>
              <th className="px-4 py-3">Tenant</th>
              <th className="px-4 py-3">Progress</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Drop-off</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.tenants.map((t) => (
              <tr key={t.tenant_id} className="hover:bg-slate-50/50">
                <td className="px-4 py-3 font-medium text-gray-900">{t.company_name}</td>
                <td className="px-4 py-3 tabular-nums">
                  {t.completed_steps}/{t.total_steps} ({t.progress_percent}%)
                </td>
                <td className="px-4 py-3">
                  <span
                    className={cn(
                      "text-xs px-2 py-0.5 rounded-full",
                      t.status === "completed" && "bg-emerald-100 text-emerald-800",
                      t.status === "in_progress" && "bg-sky-100 text-sky-800",
                      t.status === "not_started" && "bg-gray-100 text-gray-600",
                    )}
                  >
                    {t.status.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {t.drop_off_step?.replace(/_/g, " ") ?? "—"}
                </td>
                <td className="px-4 py-3 text-right space-x-2">
                  <button
                    type="button"
                    onClick={() => reset.mutate(t.tenant_id)}
                    disabled={reset.isPending}
                    className="inline-flex items-center gap-1 text-xs text-gray-600 hover:text-gray-900"
                  >
                    <RotateCcw size={12} /> Reset
                  </button>
                  <button
                    type="button"
                    onClick={() => complete.mutate(t.tenant_id)}
                    disabled={complete.isPending}
                    className="inline-flex items-center gap-1 text-xs text-brand-600 hover:text-brand-800"
                  >
                    <CheckCircle2 size={12} /> Complete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
