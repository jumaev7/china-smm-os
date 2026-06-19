"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Briefcase,
  CheckCircle2,
  Contact,
  FileText,
  Lightbulb,
  MessageSquare,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import {
  customerSuccessApi,
  type CustomerSuccessHealthStatus,
  type CustomerSuccessInsightCategory,
} from "@/lib/api";
import { isOverviewLoading } from "@/lib/overview-query-options";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
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

const HEALTH_STYLES: Record<CustomerSuccessHealthStatus, string> = {
  healthy: "bg-emerald-50 text-emerald-800 border-emerald-200",
  needs_attention: "bg-amber-50 text-amber-800 border-amber-200",
  at_risk: "bg-red-50 text-red-800 border-red-200",
};

const INSIGHT_STYLES: Record<CustomerSuccessInsightCategory, string> = {
  working: "border-emerald-200 bg-emerald-50/50",
  not_working: "border-red-200 bg-red-50/50",
  market: "border-sky-200 bg-sky-50/50",
  buyer: "border-amber-200 bg-amber-50/50",
  activity: "border-violet-200 bg-violet-50/50",
};

export default function CustomerSuccessPage() {
  const { t } = useTranslation();
  const [showDetails, setShowDetails] = useState(false);
  const { data: summary, isError, error, refetch } = useQuery({
    queryKey: ["customer-success", "summary"],
    queryFn: () => customerSuccessApi.summary().then((r) => r.data),
  });
  const detailsQuery = useQuery({
    queryKey: ["customer-success", "dashboard"],
    queryFn: () => customerSuccessApi.dashboard().then((r) => r.data),
    enabled: false,
  });

  if (isOverviewLoading(summary, isError)) {
    return <LoadingState message={t("customerSuccess.loading")} />;
  }
  if (isError) {
    return (
      <ErrorState
        error={error}
        onRetry={() => refetch()}
      />
    );
  }
  if (!summary) return null;

  const health_score = summary.customer_health_score;
  const roi = summary.roi_estimate;
  const is_demo = summary.is_demo;
  const openDetails = () => {
    setShowDetails(true);
    if (!detailsQuery.data && !detailsQuery.isFetching) {
      void detailsQuery.refetch();
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <CustomerSuccessPageHeader
        title={t("customerSuccess.title")}
        subtitle={t("customerSuccess.subtitle")}
      />

      {is_demo && (
        <div className="rounded-lg border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-800">
          {t("customerSuccess.demoBanner")}
        </div>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ScoreCard
          title={t("customerSuccess.healthScore")}
          score={health_score.score}
          subtitle={health_score.label}
          metrics={[
            { label: t("customerSuccess.engagement"), value: `${summary.adoption_score}%` },
            { label: t("customerSuccess.estimatedRoi"), value: `${roi.estimated_roi_pct.toFixed(0)}%` },
          ]}
        />
        <div className="lg:col-span-2 card-premium p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">{t("customerSuccess.roiSummary")}</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.subscriptionCost")}</p>
              <p className="text-sm font-semibold tabular-nums">{fmtMoney(roi.subscription_cost)}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.valueGenerated")}</p>
              <p className="text-sm font-semibold tabular-nums">{fmtMoney(roi.value_generated)}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.revenueInfluenced")}</p>
              <p className="text-sm font-semibold tabular-nums">{fmtMoney(roi.revenue_influenced)}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.roiLabel")}</p>
              <p className="text-sm font-semibold text-brand-700">{roi.roi_label}</p>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-brand-600" />
          {t("customerSuccess.factoryRoi")}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <KpiCard label={t("customerSuccess.estimatedRoi")} value={`${roi.estimated_roi_pct.toFixed(0)}%`} href="/customer-success/roi" icon={TrendingUp} iconClassName="bg-brand-50 text-brand-600" />
          <KpiCard label="Active users" value={summary.active_users} href="/settings" icon={Users} iconClassName="bg-violet-50 text-violet-600" />
          <KpiCard label="Content activity" value={summary.content_activity} href="/content-factory" icon={FileText} iconClassName="bg-pink-50 text-pink-600" />
          <KpiCard label="CRM activity" value={summary.crm_activity} href="/sales" icon={Briefcase} iconClassName="bg-indigo-50 text-indigo-600" />
          <KpiCard label="Churn risk" value={summary.churn_risk.replace(/_/g, " ")} href="/customer-success" icon={AlertTriangle} iconClassName="bg-amber-50 text-amber-600" />
        </div>
      </section>

      <section className="card-premium p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-amber-500" />
          {t("customerSuccess.aiInsights")}
        </h2>
        {summary.top_insights.length === 0 ? (
          <EmptyState title={t("customerSuccess.noInsights")} description={t("customerSuccess.noInsightsHint")} />
        ) : (
          <div className="space-y-3">
            {summary.top_insights.map((insight) => (
              <div key={insight.id} className={cn("rounded-lg border p-4", INSIGHT_STYLES[insight.category])}>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{insight.title}</p>
                    <p className="text-xs text-gray-600 mt-1">{insight.detail}</p>
                  </div>
                  {insight.href && (
                    <Link href={insight.href} className="text-xs text-brand-600 hover:underline shrink-0">
                      {t("customerSuccess.viewDetails")}
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="flex justify-center">
        <button type="button" className="btn-secondary text-sm" onClick={openDetails}>
          {showDetails ? "Refresh details" : "Load details"}
        </button>
      </section>

      {showDetails && (() => {
        if (detailsQuery.isLoading || detailsQuery.isFetching) {
          return <LoadingState message={t("customerSuccess.loading")} />;
        }
        if (detailsQuery.isError) {
          return (
            <ErrorState
              message={detailsQuery.error instanceof Error ? detailsQuery.error.message : t("customerSuccess.error")}
              onRetry={() => detailsQuery.refetch()}
            />
          );
        }
        if (!detailsQuery.data) return null;
        const { health_score, business_impact, insights } = detailsQuery.data;
        return (
          <>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="card-premium p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">{t("customerSuccess.healthFactors")}</h2>
          <div className="space-y-3">
            {health_score.factors.map((f) => (
              <div key={f.factor} className="flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800">{f.label}</p>
                  <p className="text-xs text-gray-500">{f.summary}</p>
                </div>
                <span className={cn("text-xs font-semibold px-2 py-0.5 rounded-full border", HEALTH_STYLES[
                  f.score >= 70 ? "healthy" : f.score >= 45 ? "needs_attention" : "at_risk"
                ])}>
                  {f.score}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="card-premium p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">{t("customerSuccess.businessImpactSummary")}</h2>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.buyersAcquired")}</p>
              <p className="text-lg font-semibold tabular-nums">{business_impact.buyers_acquired}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.buyersReactivated")}</p>
              <p className="text-lg font-semibold tabular-nums">{business_impact.buyers_reactivated}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.proposalAcceptance")}</p>
              <p className="text-lg font-semibold tabular-nums">{business_impact.proposal_acceptance_rate}%</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase text-gray-400">{t("customerSuccess.avgDealProgression")}</p>
              <p className="text-lg font-semibold tabular-nums">{business_impact.average_deal_progression_days}d</p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href="/customer-success/roi" className="btn-secondary text-xs">{t("customerSuccess.nav.roi")}</Link>
            <Link href="/customer-success/adoption" className="btn-secondary text-xs">{t("customerSuccess.nav.adoption")}</Link>
            <Link href="/customer-success/business-impact" className="btn-secondary text-xs">{t("customerSuccess.nav.businessImpact")}</Link>
          </div>
        </section>
      </div>

      <section className="card-premium p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-amber-500" />
          {t("customerSuccess.aiInsights")}
        </h2>
        {insights.length === 0 ? (
          <EmptyState title={t("customerSuccess.noInsights")} description={t("customerSuccess.noInsightsHint")} />
        ) : (
          <div className="space-y-3">
            {insights.map((insight) => (
              <div
                key={insight.id}
                className={cn("rounded-lg border p-4", INSIGHT_STYLES[insight.category])}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{insight.title}</p>
                    <p className="text-xs text-gray-600 mt-1">{insight.detail}</p>
                  </div>
                  {insight.href && (
                    <Link href={insight.href} className="text-xs text-brand-600 hover:underline shrink-0">
                      {t("customerSuccess.viewDetails")}
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
          </>
        );
      })()}
    </div>
  );
}
