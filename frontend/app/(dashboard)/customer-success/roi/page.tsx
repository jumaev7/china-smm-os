"use client";

import { useQuery } from "@tanstack/react-query";
import { DollarSign, TrendingUp } from "lucide-react";
import { customerSuccessApi } from "@/lib/api";
import { isOverviewLoading } from "@/lib/overview-query-options";
import { useTranslation } from "@/lib/I18nProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { ScoreCard } from "@/components/ui/design-system/ScoreCard";
import { CustomerSuccessPageHeader } from "@/components/customer-success/CustomerSuccessSubNav";

function fmtMoney(value: number | string, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value));
}

export default function CustomerSuccessRoiPage() {
  const { t } = useTranslation();
  const { data, isError, error, refetch } = useQuery({
    queryKey: ["customer-success", "roi"],
    queryFn: () => customerSuccessApi.roi().then((r) => r.data),
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

  const { roi_kpis, roi, health_score } = data;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <CustomerSuccessPageHeader
        title={t("customerSuccess.roiTitle")}
        subtitle={t("customerSuccess.roiSubtitle")}
      />

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ScoreCard
          title={t("customerSuccess.estimatedRoi")}
          score={Math.min(100, Math.max(0, roi.estimated_roi_pct > 100 ? 100 : roi.estimated_roi_pct))}
          subtitle={roi.roi_label}
          metrics={[
            { label: t("customerSuccess.actualRoi"), value: `${roi.estimated_roi_pct.toFixed(1)}%` },
            { label: t("customerSuccess.subscriptionCost"), value: fmtMoney(roi.subscription_cost) },
          ]}
        />
        <div className="card-premium p-5 space-y-4">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <DollarSign className="w-4 h-4 text-brand-600" />
            {t("customerSuccess.roiBreakdown")}
          </h3>
          <div className="space-y-3">
            {[
              { label: t("customerSuccess.pipelineValue"), value: roi.pipeline_value, weight: roi.config.pipeline_weight },
              { label: t("customerSuccess.proposalValue"), value: roi.proposal_value, weight: roi.config.proposal_weight },
              { label: t("customerSuccess.wonRevenue"), value: roi.won_revenue, weight: roi.config.won_deals_weight },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm text-gray-800">{row.label}</p>
                  <p className="text-xs text-gray-400">Weight: {(row.weight * 100).toFixed(0)}%</p>
                </div>
                <p className="text-sm font-semibold tabular-nums">{fmtMoney(row.value)}</p>
              </div>
            ))}
            <div className="border-t border-gray-100 pt-3 flex items-center justify-between">
              <p className="text-sm font-semibold text-gray-900">{t("customerSuccess.valueGenerated")}</p>
              <p className="text-sm font-bold text-brand-700 tabular-nums">{fmtMoney(roi.value_generated)}</p>
            </div>
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-gray-900">{t("customerSuccess.revenueInfluenced")}</p>
              <p className="text-sm font-bold text-emerald-700 tabular-nums">{fmtMoney(roi.revenue_influenced)}</p>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-brand-600" />
          {t("customerSuccess.roiInputs")}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <KpiCard label={t("customerSuccess.totalLeads")} value={roi.leads_generated} href="/leads" />
          <KpiCard label={t("customerSuccess.dealsCreated")} value={roi.deals_created} href="/deals" />
          <KpiCard label={t("customerSuccess.pipelineValue")} value={fmtMoney(roi.pipeline_value)} href="/deals" />
          <KpiCard label={t("customerSuccess.proposalValue")} value={fmtMoney(roi.proposal_value)} href="/proposals" />
          <KpiCard label={t("customerSuccess.dealsWon")} value={roi_kpis.deals_won} href="/deals" />
        </div>
      </section>

      <section className="card-premium p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-2">{t("customerSuccess.roiEngineNote")}</h3>
        <p className="text-sm text-gray-600">{t("customerSuccess.roiEngineDescription")}</p>
        <p className="text-xs text-gray-400 mt-2">
          {t("customerSuccess.healthScore")}: {health_score.score}/100 ({health_score.label})
        </p>
      </section>
    </div>
  );
}
