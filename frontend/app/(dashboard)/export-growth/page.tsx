"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BarChart3,
  Briefcase,
  CheckCircle2,
  Globe,
  Lightbulb,
  Sparkles,
  Target,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import {
  exportGrowthApi,
  type ExportGrowthRecommendationPriority,
} from "@/lib/api";
import { OVERVIEW_WIDGET_QUERY_OPTIONS } from "@/lib/overview-query-options";
import { useDashboardAuthGates } from "@/lib/useDashboardAuthGates";
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

const PRIORITY_STYLES: Record<ExportGrowthRecommendationPriority, string> = {
  urgent: "bg-red-100 text-red-900 border-red-200",
  high: "bg-orange-100 text-orange-900 border-orange-200",
  medium: "bg-sky-100 text-sky-900 border-sky-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

const BUYER_TYPE_LABELS: Record<string, string> = {
  follow_up: "Follow up",
  high_potential: "High potential",
  inactive: "Inactive",
  new_target: "New target",
};

const SALES_TYPE_LABELS: Record<string, string> = {
  at_risk: "At risk",
  fast_close: "Fast close",
  high_value: "High value",
  stalled: "Stalled",
};

export default function ExportGrowthPage() {
  const { t } = useTranslation();
  const { tenantWidgetsEnabled, sharedWidgetsEnabled } = useDashboardAuthGates();
  const [showDetails, setShowDetails] = useState(false);
  const summaryEnabled = tenantWidgetsEnabled || sharedWidgetsEnabled;
  const { data: summary, isError, error, refetch, isPending } = useQuery({
    queryKey: ["export-growth", "summary"],
    queryFn: () => exportGrowthApi.summary().then((r) => r.data),
    enabled: summaryEnabled,
    ...OVERVIEW_WIDGET_QUERY_OPTIONS,
  });
  const detailsQuery = useQuery({
    queryKey: ["export-growth", "dashboard"],
    queryFn: () => exportGrowthApi.dashboard().then((r) => r.data),
    enabled: false,
    ...OVERVIEW_WIDGET_QUERY_OPTIONS,
  });

  if (!summaryEnabled || (isPending && !summary)) {
    return <LoadingState message={t("exportGrowth.loading")} />;
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

  const export_growth_score = summary.export_growth_score;
  const daily_actions = summary.top_actions;
  const demo_mode = summary.demo_mode;
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
            <Globe size={22} className="text-brand-600" />
            {t("exportGrowth.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("exportGrowth.subtitle")}</p>
        </div>
        {demo_mode && (
          <span className="status-badge bg-amber-50 text-amber-800 border border-amber-200">
            {t("exportGrowth.demoMode")}
          </span>
        )}
      </div>

      <section className="card p-4 bg-gradient-to-br from-brand-50/80 to-white border-brand-100">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">
              {t("exportGrowth.exportGrowthScore")}
            </p>
            <p className="text-3xl font-bold text-navy-900 tabular-nums mt-1">
              {export_growth_score.score}
              <span className="text-lg font-normal text-gray-400">/100</span>
            </p>
            <p className="text-sm font-medium text-brand-700 mt-1">{export_growth_score.label}</p>
            <p className="text-xs text-gray-500 mt-1 max-w-xl">{export_growth_score.summary}</p>
          </div>
          <HealthIndicator
            score={export_growth_score.score}
            label={t("exportGrowth.exportGrowthScore")}
            size="lg"
          />
        </div>
        {export_growth_score.factors.length > 0 && (
          <div className="mt-4 pt-4 border-t border-brand-100/80 grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
            {export_growth_score.factors.map((f) => (
              <div key={f.factor} className="text-xs">
                <div className="flex justify-between gap-2 mb-1">
                  <span className="font-medium text-gray-700">{f.factor}</span>
                  <span className="text-gray-500 tabular-nums">{f.weight_pct}%</span>
                </div>
                <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-brand-500 rounded-full"
                    style={{ width: `${f.score}%` }}
                  />
                </div>
                <p className="text-[10px] text-gray-400 mt-1">{f.summary}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-brand-600" />
          {t("exportGrowth.executiveKpis")}
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard
            label="Active opportunities"
            value={summary.active_opportunities}
            href="/deals"
            icon={Briefcase}
            iconClassName="bg-indigo-50 text-indigo-600"
          />
          <KpiCard
            label={t("exportGrowth.expectedRevenue")}
            value={fmtMoney(Number(summary.expected_revenue))}
            href="/deals"
            icon={BarChart3}
            iconClassName="bg-cyan-50 text-cyan-600"
          />
          <KpiCard
            label="High value opportunities"
            value={summary.high_value_opportunities}
            href="/business-matching"
            icon={Target}
            iconClassName="bg-emerald-50 text-emerald-600"
          />
          <KpiCard
            label="Buyers to contact"
            value={summary.buyers_to_contact}
            href="/buyers"
            icon={Users}
            iconClassName="bg-violet-50 text-violet-600"
          />
          <KpiCard
            label="Deals at risk"
            value={summary.deals_at_risk}
            href="/export-growth"
            icon={AlertTriangle}
            iconClassName="bg-red-50 text-red-600"
          />
        </div>
      </section>

      <section className="card p-4 border-l-4 border-l-brand-500">
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Zap className="w-4 h-4 text-brand-600" />
          {t("exportGrowth.dailyActionCenter")}
        </h2>
        <p className="text-xs text-gray-500 mb-4">{t("exportGrowth.dailyActionHint")}</p>
        {daily_actions.length === 0 ? (
          <EmptyState
            title={t("exportGrowth.noActions")}
            description={t("exportGrowth.noActionsHint")}
          />
        ) : (
          <ul className="divide-y divide-gray-100">
            {daily_actions.map((action) => (
              <li key={action.id} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <p className="text-sm font-medium text-gray-900">{action.title}</p>
                  <span
                    className={cn(
                      "text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase shrink-0",
                      PRIORITY_STYLES[action.priority],
                    )}
                  >
                    {action.priority}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{action.reason}</p>
                <p className="text-xs text-brand-700 font-medium mt-1">{action.recommended_action}</p>
                <p className="text-[10px] text-gray-400 mt-1">
                  {t("exportGrowth.expectedImpact")}: {action.expected_impact}
                </p>
                {action.href && (
                  <Link href={action.href} className="text-xs text-brand-600 hover:underline mt-1 inline-block">
                    {t("common.open")} →
                  </Link>
                )}
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
          return <LoadingState message={t("exportGrowth.loading")} />;
        }
        if (detailsQuery.isError) {
          return (
            <ErrorState
              error={detailsQuery.error}
              onRetry={() => detailsQuery.refetch()}
            />
          );
        }
        if (!detailsQuery.data) return null;
        const {
          opportunities,
          market_opportunities,
          buyer_recommendations,
          content_recommendations,
          sales_recommendations,
          strategic_insights,
          growing_markets,
        } = detailsQuery.data;
        return (
          <>
      <div className="grid lg:grid-cols-2 gap-5">
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Target className="w-4 h-4 text-emerald-600" />
            {t("exportGrowth.opportunityEngine")}
          </h2>
          {opportunities.length === 0 ? (
            <EmptyState
              title={t("exportGrowth.noOpportunities")}
              description={t("exportGrowth.noOpportunitiesHint")}
            />
          ) : (
            <div className="space-y-3">
              {opportunities.map((opp) => (
                <div key={opp.id} className="rounded-lg border border-gray-100 p-3 hover:bg-gray-50/80">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{opp.title}</p>
                      <p className="text-xs text-gray-500 capitalize mt-0.5">
                        {opp.category}
                        {opp.country ? ` · ${opp.country}` : ""}
                      </p>
                    </div>
                    <span className="text-sm font-bold text-brand-700 tabular-nums">{opp.opportunity_score}</span>
                  </div>
                  <div className="flex flex-wrap gap-3 mt-2 text-xs text-gray-600">
                    <span>{fmtMoney(Number(opp.estimated_value), opp.currency)}</span>
                    <span>{t("exportGrowth.confidence")}: {opp.confidence_score}%</span>
                  </div>
                  <p className="text-xs text-brand-700 mt-1">{opp.recommended_action}</p>
                  {opp.href && (
                    <Link href={opp.href} className="text-xs text-brand-600 hover:underline mt-1 inline-block">
                      {t("common.open")} →
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Globe className="w-4 h-4 text-brand-600" />
            {t("exportGrowth.marketOpportunities")}
          </h2>
          {market_opportunities.length === 0 ? (
            <EmptyState title={t("exportGrowth.noMarkets")} description={t("exportGrowth.noMarketsHint")} />
          ) : (
            <div className="space-y-2">
              {market_opportunities.map((m) => (
                <div key={m.id} className="flex items-center justify-between gap-3 py-2 border-b border-gray-50 last:border-0">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{m.name}</p>
                    <p className="text-xs text-gray-500 capitalize">
                      {m.type} · {m.data_source === "demo" ? t("exportGrowth.demoData") : m.data_source}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-semibold text-brand-700 tabular-nums">{m.growth_score}</p>
                    <p className="text-[10px] text-gray-400">{fmtMoney(Number(m.estimated_value))}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
          {growing_markets.length > 0 && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <p className="text-xs font-medium text-gray-500 mb-2">{t("exportGrowth.growingMarkets")}</p>
              <HorizontalBarChart
                data={growing_markets.map((i) => ({ label: i.label, value: i.count }))}
              />
            </div>
          )}
        </section>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">{t("exportGrowth.buyerRecommendations")}</h2>
          {buyer_recommendations.length === 0 ? (
            <p className="text-sm text-gray-400">{t("exportGrowth.noBuyers")}</p>
          ) : (
            <ul className="space-y-3">
              {buyer_recommendations.slice(0, 5).map((b) => (
                <li key={b.id} className="text-sm">
                  <div className="flex justify-between gap-2">
                    <span className="font-medium text-gray-900">{b.company_name}</span>
                    <span className="text-xs text-brand-700 tabular-nums">{b.match_score}</span>
                  </div>
                  <span className="text-[10px] uppercase text-gray-400">
                    {BUYER_TYPE_LABELS[b.type] ?? b.type}
                  </span>
                  <p className="text-xs text-gray-500 mt-0.5">{b.reason}</p>
                  {b.href && (
                    <Link href={b.href} className="text-xs text-brand-600 hover:underline">
                      {t("common.open")} →
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">{t("exportGrowth.contentRecommendations")}</h2>
          {content_recommendations.length === 0 ? (
            <p className="text-sm text-gray-400">{t("exportGrowth.noContent")}</p>
          ) : (
            <ul className="space-y-3">
              {content_recommendations.slice(0, 5).map((c) => (
                <li key={c.id} className="text-sm">
                  <p className="font-medium text-gray-900">{c.title}</p>
                  <p className="text-xs text-gray-500">
                    {c.language.toUpperCase()} · {c.platform}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{c.reason}</p>
                  {c.href && (
                    <Link href={c.href} className="text-xs text-brand-600 hover:underline">
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
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            {t("exportGrowth.salesRecommendations")}
          </h2>
          {sales_recommendations.length === 0 ? (
            <p className="text-sm text-gray-400">{t("exportGrowth.noSales")}</p>
          ) : (
            <ul className="space-y-3">
              {sales_recommendations.slice(0, 5).map((s) => (
                <li key={s.id} className="text-sm">
                  <div className="flex justify-between gap-2">
                    <span className="font-medium text-gray-900 truncate">{s.deal_title}</span>
                    <span className="text-xs shrink-0 text-gray-500">
                      {SALES_TYPE_LABELS[s.type] ?? s.type}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500">
                    {fmtMoney(Number(s.value), s.currency)} · {s.probability}%
                  </p>
                  <p className="text-xs text-gray-500">{s.reason}</p>
                  {s.href && (
                    <Link href={s.href} className="text-xs text-brand-600 hover:underline">
                      {t("common.open")} →
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="card p-4">
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-violet-500" />
          {t("exportGrowth.strategicInsights")}
        </h2>
        {strategic_insights.length === 0 ? (
          <EmptyState title={t("exportGrowth.noInsights")} description={t("exportGrowth.noInsightsHint")} />
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {strategic_insights.map((insight) => (
              <div key={insight.id} className="rounded-lg border border-gray-100 p-3 bg-gray-50/50">
                <p className="text-[10px] uppercase tracking-wide text-gray-400">{insight.category}</p>
                <p className="text-sm font-medium text-gray-900 mt-1">{insight.title}</p>
                <p className="text-xs text-gray-600 mt-1">{insight.insight}</p>
                <p className="text-[10px] text-gray-400 mt-2">
                  {t("exportGrowth.confidence")}: {insight.confidence}%
                </p>
                {insight.recommended_action && (
                  <p className="text-xs text-brand-700 mt-1">{insight.recommended_action}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card p-4 bg-gray-50/50">
        <h2 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-amber-500" />
          {t("exportGrowth.executiveQuestions")}
        </h2>
        <ul className="grid sm:grid-cols-2 gap-2 text-xs text-gray-600">
          {[
            t("exportGrowth.q1"),
            t("exportGrowth.q2"),
            t("exportGrowth.q3"),
            t("exportGrowth.q4"),
            t("exportGrowth.q5"),
            t("exportGrowth.q6"),
            t("exportGrowth.q7"),
          ].map((q) => (
            <li key={q} className="flex items-start gap-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
              {q}
            </li>
          ))}
        </ul>
      </section>
          </>
        );
      })()}
    </div>
  );
}
