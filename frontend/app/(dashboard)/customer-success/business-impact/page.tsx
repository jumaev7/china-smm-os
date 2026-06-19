"use client";

import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { customerSuccessApi } from "@/lib/api";
import { isOverviewLoading } from "@/lib/overview-query-options";
import { useTranslation } from "@/lib/I18nProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { HorizontalBarChart } from "@/components/analytics/SimpleBarChart";
import { CustomerSuccessPageHeader } from "@/components/customer-success/CustomerSuccessSubNav";

function fmtMoney(value: number | string, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value));
}

export default function CustomerSuccessBusinessImpactPage() {
  const { t } = useTranslation();
  const { data, isError, error, refetch } = useQuery({
    queryKey: ["customer-success", "business-impact"],
    queryFn: () => customerSuccessApi.businessImpact().then((r) => r.data),
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

  const { business_impact, roi_kpis, top_markets } = data;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <CustomerSuccessPageHeader
        title={t("customerSuccess.businessImpactTitle")}
        subtitle={t("customerSuccess.businessImpactSubtitle")}
      />

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-brand-600" />
          {t("customerSuccess.impactMetrics")}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <KpiCard label={t("customerSuccess.buyersAcquired")} value={business_impact.buyers_acquired} href="/buyers" />
          <KpiCard label={t("customerSuccess.buyersReactivated")} value={business_impact.buyers_reactivated} href="/buyers" />
          <KpiCard label={t("customerSuccess.opportunitiesCreated")} value={business_impact.opportunities_created} href="/deals" />
          <KpiCard label={t("customerSuccess.proposalAcceptance")} value={`${business_impact.proposal_acceptance_rate}%`} href="/proposals" />
          <KpiCard label={t("customerSuccess.avgDealProgression")} value={`${business_impact.average_deal_progression_days}d`} href="/deals" />
          <KpiCard label={t("customerSuccess.wonDealValue")} value={fmtMoney(business_impact.won_deal_value)} href="/deals" />
          <KpiCard label={t("customerSuccess.pipelineCreated")} value={fmtMoney(business_impact.pipeline_created_value)} href="/deals" />
          <KpiCard label={t("customerSuccess.revenueInfluenced")} value={fmtMoney(roi_kpis.estimated_revenue_influenced)} href="/deals" />
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="card-premium p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">{t("customerSuccess.topMarkets")}</h3>
          {top_markets.length === 0 ? (
            <EmptyState title={t("customerSuccess.noMarkets")} description={t("customerSuccess.noMarketsHint")} />
          ) : (
            <HorizontalBarChart
              data={top_markets.map((m) => ({ label: m.label, value: m.count }))}
            />
          )}
        </section>

        <section className="card-premium p-5 space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">{t("customerSuccess.impactSummary")}</h3>
          <ul className="space-y-2 text-sm text-gray-700">
            <li>{t("customerSuccess.impactBullet1", { count: business_impact.buyers_acquired })}</li>
            <li>{t("customerSuccess.impactBullet2", { rate: business_impact.proposal_acceptance_rate })}</li>
            <li>{t("customerSuccess.impactBullet3", { days: business_impact.average_deal_progression_days })}</li>
            <li>{t("customerSuccess.impactBullet4", { value: fmtMoney(business_impact.won_deal_value) })}</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
