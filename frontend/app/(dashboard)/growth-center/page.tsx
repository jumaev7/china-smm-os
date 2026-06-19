"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertTriangle,
  BarChart3,
  Briefcase,
  CheckCircle2,
  Contact,
  Download,
  FileSpreadsheet,
  FileText,
  Globe,
  Lightbulb,
  MessageSquare,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  growthCenterApi,
  type GrowthCenterExportFormat,
  type GrowthCenterHealthStatus,
  type GrowthCenterRecommendationPriority,
} from "@/lib/api";
import { isOverviewLoading } from "@/lib/overview-query-options";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { HealthIndicator } from "@/components/ui/design-system/HealthIndicator";
import { HorizontalBarChart } from "@/components/analytics/SimpleBarChart";

function fmtMoney(value: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

const HEALTH_STYLES: Record<GrowthCenterHealthStatus, string> = {
  healthy: "bg-emerald-50 text-emerald-800 border-emerald-200",
  warning: "bg-amber-50 text-amber-800 border-amber-200",
  critical: "bg-red-50 text-red-800 border-red-200",
};

const PRIORITY_STYLES: Record<GrowthCenterRecommendationPriority, string> = {
  urgent: "bg-red-100 text-red-900 border-red-200",
  high: "bg-orange-100 text-orange-900 border-orange-200",
  medium: "bg-sky-100 text-sky-900 border-sky-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

function TrendChart({ points, label }: { points: Array<{ period: string; count: number }>; label: string }) {
  const max = Math.max(...points.map((p) => p.count), 1);
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <div className="flex items-end gap-2 h-24">
        {points.map((p) => (
          <div key={p.period} className="flex-1 flex flex-col items-center gap-1 min-w-0">
            <span className="text-[10px] font-semibold text-gray-700 tabular-nums">{p.count}</span>
            <div
              className="w-full rounded-t bg-brand-500/80 min-h-[4px] transition-all"
              style={{ height: `${Math.max(8, (p.count / max) * 100)}%` }}
              title={`${p.period}: ${p.count}`}
            />
            <span className="text-[9px] text-gray-400 truncate w-full text-center">
              {p.period.slice(5)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function GrowthCenterPage() {
  const { t } = useTranslation();
  const [showDetails, setShowDetails] = useState(false);
  const { data: summary, isError, error, refetch } = useQuery({
    queryKey: ["growth-center", "summary"],
    queryFn: () => growthCenterApi.summary().then((r) => r.data),
  });
  const detailsQuery = useQuery({
    queryKey: ["growth-center", "dashboard"],
    queryFn: () => growthCenterApi.dashboard().then((r) => r.data),
    enabled: false,
  });

  const exportMut = useMutation({
    mutationFn: (format: GrowthCenterExportFormat) =>
      growthCenterApi.exportReport(format, { locale: "en" }).then((r) => r.data),
    onSuccess: (res) => {
      if (res.status === "ready" && res.download_url) {
        toast.success(t("growthCenter.exportReady"));
      } else {
        toast(res.message, { icon: "ℹ️" });
      }
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isOverviewLoading(summary, isError)) return <LoadingState message={t("growthCenter.loading")} />;
  if (isError) {
    return (
      <ErrorState
        error={error}
        onRetry={() => refetch()}
      />
    );
  }
  if (!summary) return null;

  const openDetails = () => {
    setShowDetails(true);
    if (!detailsQuery.data && !detailsQuery.isFetching) {
      void detailsQuery.refetch();
    }
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <BarChart3 size={22} className="text-brand-600" />
            {t("growthCenter.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("growthCenter.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary text-sm flex items-center gap-2"
            disabled={exportMut.isPending}
            onClick={() => exportMut.mutate("pdf")}
          >
            <FileText className="w-4 h-4" />
            {t("growthCenter.exportPdf")}
          </button>
          <button
            type="button"
            className="btn-secondary text-sm flex items-center gap-2"
            disabled={exportMut.isPending}
            onClick={() => exportMut.mutate("excel")}
          >
            <FileSpreadsheet className="w-4 h-4" />
            {t("growthCenter.exportExcel")}
          </button>
        </div>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-brand-600" />
          {t("growthCenter.executiveOverview")}
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          <KpiCard label={t("growthCenter.totalLeads")} value={summary.total_leads} href="/leads" icon={Contact} iconClassName="bg-sky-50 text-sky-600" />
          <KpiCard label={t("growthCenter.totalBuyers")} value={summary.total_buyers} href="/buyers" icon={Users} iconClassName="bg-violet-50 text-violet-600" />
          <KpiCard label={t("growthCenter.activeBuyers")} value={summary.active_buyers} href="/buyers" icon={CheckCircle2} iconClassName="bg-emerald-50 text-emerald-600" />
          <KpiCard label={t("growthCenter.totalDeals")} value={summary.total_deals} href="/deals" icon={Briefcase} iconClassName="bg-indigo-50 text-indigo-600" />
          <KpiCard label={t("growthCenter.pipelineValue")} value={fmtMoney(Number(summary.pipeline_value))} href="/deals" icon={TrendingUp} iconClassName="bg-brand-50 text-brand-600" />
          <KpiCard label={t("growthCenter.totalProposalValue")} value={fmtMoney(Number(summary.proposal_value))} href="/proposals" icon={FileText} iconClassName="bg-amber-50 text-amber-600" />
          <KpiCard label={t("growthCenter.followUpsDue")} value={summary.followups_due} href="/communications/followups" icon={MessageSquare} iconClassName="bg-orange-50 text-orange-600" />
          <KpiCard label="Growth score" value={`${summary.growth_score}/100`} href="/growth-center" icon={Target} iconClassName="bg-green-50 text-green-600" />
        </div>
      </section>

      <section className="card p-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-amber-500" />
          {t("growthCenter.aiRecommendations")}
        </h2>
        {summary.top_recommendations.length === 0 ? (
          <EmptyState title={t("growthCenter.noRecommendations")} description={t("growthCenter.noRecommendationsHint")} />
        ) : (
          <ul className="divide-y divide-gray-100">
            {summary.top_recommendations.map((rec) => (
              <li key={rec.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <p className="text-sm font-medium text-gray-900">{rec.title}</p>
                  <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase shrink-0", PRIORITY_STYLES[rec.priority])}>
                    {rec.priority}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mb-1">{rec.reason}</p>
                <p className="text-xs text-brand-700 font-medium">{rec.recommended_action}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex justify-center">
        <button type="button" className="btn-secondary text-sm" onClick={openDetails}>
          {showDetails ? "Refresh details" : "Load details"}
        </button>
      </section>

      {showDetails && (() => {
        if (detailsQuery.isLoading || detailsQuery.isFetching) {
          return <LoadingState message={t("growthCenter.loading")} />;
        }
        if (detailsQuery.isError) {
          return (
            <ErrorState
              message={detailsQuery.error instanceof Error ? detailsQuery.error.message : t("growthCenter.error")}
              onRetry={() => detailsQuery.refetch()}
            />
          );
        }
        if (!detailsQuery.data) return null;
        const { market_insights, health_scores, recommendations, opportunities, timeline } = detailsQuery.data;
        return (
          <>
      <div className="grid lg:grid-cols-2 gap-5">
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Globe className="w-4 h-4 text-brand-600" />
            {t("growthCenter.marketInsights")}
          </h2>
          <div className="space-y-5">
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">{t("growthCenter.buyersByCountry")}</p>
              {market_insights.buyers_by_country.length === 0 ? (
                <p className="text-sm text-gray-400">{t("growthCenter.noData")}</p>
              ) : (
                <HorizontalBarChart
                  data={market_insights.buyers_by_country.map((i) => ({
                    label: i.label,
                    value: i.count,
                  }))}
                />
              )}
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500 mb-2">{t("growthCenter.buyersByIndustry")}</p>
              {market_insights.buyers_by_industry.length === 0 ? (
                <p className="text-sm text-gray-400">{t("growthCenter.noData")}</p>
              ) : (
                <HorizontalBarChart
                  data={market_insights.buyers_by_industry.map((i) => ({
                    label: i.label,
                    value: i.count,
                  }))}
                />
              )}
            </div>
            <div className="grid sm:grid-cols-2 gap-4 pt-2 border-t border-gray-100">
              <div>
                <p className="text-xs font-medium text-gray-500 mb-2">{t("growthCenter.leadsBySource")}</p>
                <div className="flex flex-wrap gap-2">
                  {market_insights.leads_by_source.map((i) => (
                    <span key={i.label} className="status-badge bg-gray-100 text-gray-700 capitalize">
                      {i.label}: {i.count}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">{t("growthCenter.proposalAcceptanceRate")}</p>
                <p className="text-2xl font-semibold text-navy-900 tabular-nums">
                  {market_insights.proposal_acceptance_rate.toFixed(1)}%
                </p>
              </div>
            </div>
            <TrendChart points={market_insights.buyer_growth_trend} label={t("growthCenter.buyerGrowthTrend")} />
          </div>
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">{t("growthCenter.salesHealth")}</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            {(
              [
                health_scores.lead_health,
                health_scores.buyer_health,
                health_scores.deal_health,
                health_scores.communication_health,
              ] as const
            ).map((h) => (
              <div key={h.label} className="rounded-lg border border-gray-100 p-3 bg-gray-50/50">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <HealthIndicator score={h.score} label={h.label} size="sm" showBar={false} />
                  <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase", HEALTH_STYLES[h.status])}>
                    {t(`growthCenter.health.${h.status}`)}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{h.summary}</p>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Lightbulb className="w-4 h-4 text-amber-500" />
            {t("growthCenter.aiRecommendations")}
          </h2>
          {recommendations.length === 0 ? (
            <EmptyState title={t("growthCenter.noRecommendations")} description={t("growthCenter.noRecommendationsHint")} />
          ) : (
            <ul className="divide-y divide-gray-100">
              {recommendations.map((rec) => (
                <li key={rec.id} className="py-3 first:pt-0 last:pb-0">
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <p className="text-sm font-medium text-gray-900">{rec.title}</p>
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase shrink-0", PRIORITY_STYLES[rec.priority])}>
                      {rec.priority}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mb-1">{rec.reason}</p>
                  <p className="text-xs text-brand-700 font-medium">{rec.recommended_action}</p>
                  <p className="text-[10px] text-gray-400 mt-1">{t("growthCenter.expectedImpact")}: {rec.expected_impact}</p>
                  {rec.href && (
                    <Link href={rec.href} className="text-xs text-brand-600 hover:underline mt-1 inline-block">
                      {t("common.open")} →
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Target className="w-4 h-4 text-emerald-600" />
            {t("growthCenter.opportunityCenter")}
          </h2>
          {opportunities.length === 0 ? (
            <EmptyState title={t("growthCenter.noOpportunities")} description={t("growthCenter.noOpportunitiesHint")} />
          ) : (
            <div className="overflow-x-auto -mx-4 px-4">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wide text-gray-500 border-b border-gray-100">
                    <th className="pb-2 pr-3 font-medium">{t("growthCenter.colBuyer")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("growthCenter.colCountry")}</th>
                    <th className="pb-2 pr-3 font-medium text-right">{t("growthCenter.colValue")}</th>
                    <th className="pb-2 pr-3 font-medium">{t("growthCenter.colStage")}</th>
                    <th className="pb-2 font-medium text-right">{t("growthCenter.colProbability")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {opportunities.map((opp) => (
                    <tr key={opp.id} className="hover:bg-gray-50/80">
                      <td className="py-2.5 pr-3 font-medium text-gray-900 truncate max-w-[140px]">{opp.buyer}</td>
                      <td className="py-2.5 pr-3 text-gray-600">{opp.country ?? "—"}</td>
                      <td className="py-2.5 pr-3 text-right font-medium tabular-nums">{fmtMoney(Number(opp.potential_value), opp.currency)}</td>
                      <td className="py-2.5 pr-3 capitalize text-gray-600">{opp.deal_stage.replace(/_/g, " ")}</td>
                      <td className="py-2.5 text-right tabular-nums">{opp.probability}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <section className="card p-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Download className="w-4 h-4 text-gray-500" />
          {t("growthCenter.executiveTimeline")}
        </h2>
        {timeline.length === 0 ? (
          <EmptyState title={t("growthCenter.noTimeline")} description={t("growthCenter.noTimelineHint")} />
        ) : (
          <ul className="relative border-l border-gray-200 ml-2 space-y-4">
            {timeline.map((item) => (
              <li key={item.id} className="pl-4 relative">
                <span className="absolute -left-[5px] top-1.5 w-2 h-2 rounded-full bg-brand-500 ring-2 ring-white" />
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  {item.href ? (
                    <Link href={item.href} className="text-sm font-medium text-gray-900 hover:text-brand-700">
                      {item.title}
                    </Link>
                  ) : (
                    <p className="text-sm font-medium text-gray-900">{item.title}</p>
                  )}
                  <time className="text-[10px] text-gray-400 tabular-nums">
                    {format(parseISO(item.occurred_at), "MMM d, HH:mm")}
                  </time>
                </div>
                {item.subtitle && (
                  <p className="text-xs text-gray-500 mt-0.5 capitalize">{item.subtitle}</p>
                )}
                <span className="text-[10px] text-gray-400 uppercase">{item.type.replace(/_/g, " ")}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
          </>
        );
      })()}
    </div>
  );
}
