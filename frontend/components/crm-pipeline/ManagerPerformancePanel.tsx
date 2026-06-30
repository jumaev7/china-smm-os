"use client";

import type { CrmPipelineManagerInsights } from "@/lib/api";
import { crmPipelineFmtMoney } from "@/lib/crm-pipeline";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

export function ManagerPerformancePanel({
  data,
  className,
}: {
  data: CrmPipelineManagerInsights;
  className?: string;
}) {
  const { t } = useTranslation();
  const rows = [...data.managers];
  if (data.unassigned && data.unassigned.open_deals > 0) {
    rows.push(data.unassigned);
  }

  if (rows.length === 0) return null;

  return (
    <div
      className={cn(
        "rounded-xl border border-gray-200 bg-white overflow-hidden",
        "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card",
        className,
      )}
    >
      <div className="px-4 py-3 border-b border-gray-100 dark-tenant:border-white/[0.06]">
        <h2 className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">
          {t("crmPipeline.managerPerformance")}
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500 border-b border-gray-100 dark-tenant:border-white/[0.06]">
              <th className="px-4 py-2.5 font-medium">{t("crmPipeline.manager")}</th>
              <th className="px-4 py-2.5 font-medium text-right">{t("crmPipeline.openDeals")}</th>
              <th className="px-4 py-2.5 font-medium text-right">{t("crmPipeline.pipelineValue")}</th>
              <th className="px-4 py-2.5 font-medium text-right">{t("crmPipeline.executiveBrief.likelyWins")}</th>
              <th className="px-4 py-2.5 font-medium text-right">{t("crmPipeline.stale")}</th>
              <th className="px-4 py-2.5 font-medium text-right">{t("crmPipeline.executiveBrief.avgResponse")}</th>
              <th className="px-4 py-2.5 font-medium text-right">{t("crmPipeline.executiveBrief.workload")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50 dark-tenant:divide-white/[0.04]">
            {rows.map((row) => (
              <tr
                key={row.owner_id ?? "__unassigned__"}
                className="hover:bg-gray-50/80 dark-tenant:hover:bg-white/[0.02]"
              >
                <td className="px-4 py-2.5 text-gray-800 dark-tenant:text-slate-200">
                  {row.owner_email || t("crmPipeline.unassigned")}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-gray-700 dark-tenant:text-slate-300">
                  {row.open_deals}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums font-medium text-gray-900 dark-tenant:text-slate-100">
                  {crmPipelineFmtMoney(row.pipeline_value)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-emerald-600 dark-tenant:text-emerald-400">
                  {row.likely_wins}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">
                  {row.stale_deals > 0 ? (
                    <span className="text-amber-600 dark-tenant:text-amber-400 font-medium">
                      {row.stale_deals}
                    </span>
                  ) : (
                    <span className="text-gray-400">0</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-gray-600 dark-tenant:text-slate-400">
                  {row.avg_response_time_days != null ? `${row.avg_response_time_days}d` : "—"}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">
                  <span
                    className={cn(
                      "text-xs font-medium px-1.5 py-0.5 rounded",
                      row.workload_score >= 70
                        ? "bg-red-100 text-red-700 dark-tenant:bg-red-500/15 dark-tenant:text-red-300"
                        : row.workload_score >= 40
                          ? "bg-amber-100 text-amber-700 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300"
                          : "bg-gray-100 text-gray-600 dark-tenant:bg-white/5 dark-tenant:text-slate-400",
                    )}
                  >
                    {row.workload_score}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
