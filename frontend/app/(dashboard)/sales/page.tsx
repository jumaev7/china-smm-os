"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Briefcase,
  Contact,
  DollarSign,
  TrendingUp,
  Users,
} from "lucide-react";
import { salesCrmApi, SALES_DEAL_STAGES, type SalesDealStage } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";

function fmtMoney(value: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function stageLabel(stage: SalesDealStage, t: (k: string) => string) {
  const key = `salesCrm.stage.${stage}`;
  const translated = t(key);
  return translated === key ? stage.replace(/_/g, " ") : translated;
}

export default function SalesDashboardPage() {
  const { t } = useTranslation();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-crm", "dashboard"],
    queryFn: () => salesCrmApi.dashboard().then((r) => r.data),
  });

  if (isLoading) return <LoadingState message={t("salesCrm.loading")} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("salesCrm.error")}
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) return null;

  const { stats, recent_activities } = data;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="page-title flex items-center gap-2">
          <TrendingUp size={22} className="text-brand-600" />
          {t("salesCrm.dashboardTitle")}
        </h1>
        <p className="text-sm text-gray-500 mt-1">{t("salesCrm.dashboardSubtitle")}</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label={t("salesCrm.totalLeads")}
          value={stats.total_leads}
          href="/leads"
          icon={Contact}
          iconClassName="bg-sky-50 text-sky-600"
        />
        <KpiCard
          label={t("salesCrm.pipelineValue")}
          value={fmtMoney(Number(stats.pipeline_value))}
          href="/deals"
          icon={DollarSign}
          iconClassName="bg-emerald-50 text-emerald-600"
        />
        <KpiCard
          label={t("salesCrm.wonDeals")}
          value={stats.won_deals}
          href="/deals"
          icon={Briefcase}
          iconClassName="bg-violet-50 text-violet-600"
        />
        <KpiCard
          label={t("salesCrm.customers")}
          value={stats.total_customers}
          href="/customers"
          icon={Users}
          iconClassName="bg-amber-50 text-amber-600"
        />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <div className="card p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">{t("salesCrm.leadStats")}</h2>
          <div className="space-y-2">
            {Object.entries(stats.leads_by_status).length === 0 ? (
              <p className="text-sm text-gray-400">{t("salesCrm.noData")}</p>
            ) : (
              Object.entries(stats.leads_by_status).map(([status, count]) => (
                <div key={status} className="flex items-center justify-between text-sm">
                  <span className="capitalize text-gray-600">{status}</span>
                  <span className="font-medium text-gray-900">{count}</span>
                </div>
              ))
            )}
          </div>
          <div className="mt-4 pt-4 border-t border-gray-100">
            <h3 className="text-xs font-medium text-gray-500 uppercase mb-2">{t("salesCrm.bySource")}</h3>
            <div className="flex flex-wrap gap-2">
              {Object.entries(stats.leads_by_source).map(([source, count]) => (
                <span key={source} className="status-badge bg-gray-100 text-gray-700 capitalize">
                  {source}: {count}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="card p-4">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">{t("salesCrm.pipelineSummary")}</h2>
          <div className="space-y-2">
            {SALES_DEAL_STAGES.map((stage) => {
              const row = stats.pipeline_by_stage.find((s) => s.stage === stage);
              const count = row?.count ?? 0;
              const value = Number(row?.total_value ?? 0);
              return (
                <div key={stage} className="flex items-center justify-between text-sm gap-2">
                  <span className="text-gray-600 truncate">{stageLabel(stage, t)}</span>
                  <span className="shrink-0 text-gray-500">{count}</span>
                  <span className="shrink-0 font-medium text-gray-900">{fmtMoney(value)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-800">{t("salesCrm.recentActivities")}</h2>
          <Link href="/leads" className="text-xs text-brand-700 hover:underline">
            {t("salesCrm.viewLeads")}
          </Link>
        </div>
        {recent_activities.length === 0 ? (
          <EmptyState title={t("salesCrm.noActivities")} description={t("salesCrm.noActivitiesHint")} />
        ) : (
          <ul className="divide-y divide-gray-100">
            {recent_activities.map((a) => (
              <li key={a.id} className="py-2.5 flex items-start gap-3">
                <span className={cn("status-badge capitalize shrink-0", "bg-brand-50 text-brand-700")}>
                  {a.type}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 truncate">{a.title}</p>
                  {a.description && (
                    <p className="text-xs text-gray-500 truncate">{a.description}</p>
                  )}
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    {format(parseISO(a.activity_date), "MMM d, yyyy HH:mm")}
                    {a.created_by ? ` · ${a.created_by}` : ""}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-wrap gap-3">
        <Link href="/leads" className="btn-primary text-sm">{t("nav.leads")}</Link>
        <Link href="/deals" className="btn-secondary text-sm">{t("nav.deals")}</Link>
        <Link href="/customers" className="btn-secondary text-sm">{t("nav.customers")}</Link>
      </div>
    </div>
  );
}
