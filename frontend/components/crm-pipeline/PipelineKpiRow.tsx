"use client";

import {
  Briefcase,
  DollarSign,
  Facebook,
  Percent,
  Radio,
  TrendingUp,
  Users,
} from "lucide-react";
import type { CrmPipelineDashboardKpis, CrmPipelineManagerPerformance } from "@/lib/api";
import { crmPipelineFmtMoney } from "@/lib/crm-pipeline";
import { useTranslation } from "@/lib/I18nProvider";
import { KpiCard } from "@/components/ui/design-system/KpiCard";

export function PipelineKpiRow({
  dashboard,
  managerPerf,
}: {
  dashboard: CrmPipelineDashboardKpis;
  managerPerf: CrmPipelineManagerPerformance;
}) {
  const { t } = useTranslation();
  const activeManagers = managerPerf.managers.filter((m) => m.open_deals > 0).length;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-7 gap-3">
      <KpiCard
        label={t("crmPipeline.kpi.pipelineValue")}
        value={crmPipelineFmtMoney(dashboard.pipeline_value)}
        icon={DollarSign}
        iconClassName="bg-emerald-500/15 text-emerald-600 dark-tenant:text-emerald-400"
      />
      <KpiCard
        label={t("crmPipeline.kpi.weightedRevenue")}
        value={crmPipelineFmtMoney(dashboard.weighted_expected_revenue)}
        icon={TrendingUp}
        iconClassName="bg-violet-500/15 text-violet-600 dark-tenant:text-violet-400"
      />
      <KpiCard
        label={t("crmPipeline.kpi.winRate")}
        value={dashboard.win_rate != null ? `${dashboard.win_rate}%` : "—"}
        icon={Percent}
        iconClassName="bg-sky-500/15 text-sky-600 dark-tenant:text-sky-400"
      />
      <KpiCard
        label={t("crmPipeline.kpi.openDeals")}
        value={dashboard.open_deals_count}
        icon={Briefcase}
        iconClassName="bg-indigo-500/15 text-indigo-600 dark-tenant:text-indigo-400"
        sub={
          dashboard.stale_deals_count > 0
            ? t("crmPipeline.kpi.staleSub", { count: dashboard.stale_deals_count })
            : undefined
        }
      />
      <KpiCard
        label={t("crmPipeline.kpi.publishingClients")}
        value={dashboard.clients_publishing_count}
        icon={Radio}
        iconClassName="bg-teal-500/15 text-teal-600 dark-tenant:text-teal-400"
      />
      <KpiCard
        label={t("crmPipeline.kpi.metaConnected")}
        value={dashboard.clients_connected_to_meta}
        icon={Facebook}
        iconClassName="bg-blue-500/15 text-blue-600 dark-tenant:text-blue-400"
      />
      <KpiCard
        label={t("crmPipeline.kpi.managerPerformance")}
        value={activeManagers}
        icon={Users}
        iconClassName="bg-amber-500/15 text-amber-600 dark-tenant:text-amber-400"
        sub={t("crmPipeline.kpi.activeManagers")}
      />
    </div>
  );
}
