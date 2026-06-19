"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Users } from "lucide-react";
import { customerSuccessApi } from "@/lib/api";
import { isOverviewLoading } from "@/lib/overview-query-options";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { ScoreCard } from "@/components/ui/design-system/ScoreCard";
import { CustomerSuccessPageHeader } from "@/components/customer-success/CustomerSuccessSubNav";

export default function CustomerSuccessAdoptionPage() {
  const { t } = useTranslation();
  const { data, isError, error, refetch } = useQuery({
    queryKey: ["customer-success", "adoption"],
    queryFn: () => customerSuccessApi.adoption().then((r) => r.data),
  });

  if (isOverviewLoading(data, isError)) {
    return <LoadingState message={t("customerSuccess.loading")} />;
  }
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("customerSuccess.error")}
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) return null;

  const { adoption, health_score } = data;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <CustomerSuccessPageHeader
        title={t("customerSuccess.adoptionTitle")}
        subtitle={t("customerSuccess.adoptionSubtitle")}
      />

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ScoreCard
          title={t("customerSuccess.engagementScore")}
          score={adoption.engagement_score}
          subtitle={t("customerSuccess.platformEngagement")}
          metrics={[
            { label: t("customerSuccess.activeUsers"), value: adoption.active_users },
            { label: t("customerSuccess.totalUsers"), value: adoption.total_users },
          ]}
        />
        <div className="lg:col-span-2 card-premium p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Users className="w-4 h-4 text-brand-600" />
            {t("customerSuccess.userActivity")}
          </h3>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-center">
              <p className="text-2xl font-bold tabular-nums text-brand-700">{adoption.user_logins_30d}</p>
              <p className="text-xs text-gray-500 mt-1">{t("customerSuccess.logins30d")}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-center">
              <p className="text-2xl font-bold tabular-nums">{adoption.active_users}</p>
              <p className="text-xs text-gray-500 mt-1">{t("customerSuccess.activeUsers")}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-center">
              <p className="text-2xl font-bold tabular-nums">{adoption.total_users}</p>
              <p className="text-xs text-gray-500 mt-1">{t("customerSuccess.totalUsers")}</p>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Activity className="w-4 h-4 text-brand-600" />
          {t("customerSuccess.adoptionMetrics")}
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {adoption.metrics.map((metric) => (
            <div key={metric.key} className="card-premium p-4 space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{metric.label}</p>
                  <p className="text-2xl font-bold tabular-nums mt-1">{metric.count}</p>
                  {metric.period_count !== metric.count && (
                    <p className="text-xs text-gray-400">{metric.period_count} this period</p>
                  )}
                </div>
                <span className={cn(
                  "text-xs font-semibold px-2 py-0.5 rounded-full",
                  metric.score >= 70 ? "bg-emerald-100 text-emerald-800" :
                  metric.score >= 45 ? "bg-amber-100 text-amber-800" :
                  "bg-red-100 text-red-800",
                )}>
                  {metric.score}%
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                <div
                  className="h-full rounded-full bg-brand-500 transition-all"
                  style={{ width: `${metric.score}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="card-premium p-5">
        <p className="text-sm text-gray-600">
          {t("customerSuccess.adoptionHealthNote")} {health_score.label} ({health_score.score}/100).
        </p>
      </section>
    </div>
  );
}
