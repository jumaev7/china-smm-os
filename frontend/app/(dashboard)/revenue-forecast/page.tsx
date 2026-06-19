"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CircleDollarSign,
  Loader2,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  revenueForecastApi,
  RevenueForecastGenerateResult,
  RevenueForecastGrowthOpportunity,
  RevenueForecastPeriod,
  RevenueForecastPipelineStage,
  RevenueForecastRiskItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";
import {
  isOverviewLoading,
  OVERVIEW_HEAVY_QUERY_OPTIONS,
  OVERVIEW_SECTION_QUERY_OPTIONS,
  OVERVIEW_WIDGET_QUERY_OPTIONS,
} from "@/lib/overview-query-options";

const PERIOD_LABELS: Record<string, string> = {
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
};

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-900 border-red-300",
  high: "bg-orange-100 text-orange-900 border-orange-200",
  medium: "bg-amber-100 text-amber-900 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function ForecastCard({ row }: { row: RevenueForecastPeriod }) {
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900">{PERIOD_LABELS[row.period] ?? row.period}</p>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
          <p className="text-[10px] text-emerald-700">Best case</p>
          <p className="text-sm font-semibold text-emerald-900 tabular-nums">{fmtMoney(row.best_case)}</p>
        </div>
        <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
          <p className="text-[10px] text-brand-700">Expected</p>
          <p className="text-sm font-semibold text-brand-900 tabular-nums">{fmtMoney(row.expected_case)}</p>
        </div>
        <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
          <p className="text-[10px] text-red-700">Worst case</p>
          <p className="text-sm font-semibold text-red-900 tabular-nums">{fmtMoney(row.worst_case)}</p>
        </div>
      </div>
    </div>
  );
}

export default function RevenueForecastPage() {
  return <RevenueForecastPageContent />;
}

function RevenueForecastPageContent() {
  const { t } = useTranslation();
  const [generated, setGenerated] = useState<RevenueForecastGenerateResult | null>(null);
  const [activePeriod, setActivePeriod] = useState<string>("30d");

  const {
    data: summaryWidget,
    isError: widgetError,
    error: widgetErr,
    refetch: refetchWidget,
  } = useQuery({
    queryKey: ["revenue-forecast-summary-widget"],
    queryFn: () => revenueForecastApi.summaryWidget().then((r) => r.data),
    ...OVERVIEW_WIDGET_QUERY_OPTIONS,
  });

  const { data: overview, isError: overviewError } = useQuery({
    queryKey: ["revenue-forecast-overview"],
    queryFn: () => revenueForecastApi.overview().then((r) => r.data),
    enabled: !!summaryWidget,
    ...OVERVIEW_HEAVY_QUERY_OPTIONS,
  });

  const { data: pipeline, isError: pipelineError } = useQuery({
    queryKey: ["revenue-forecast-pipeline"],
    queryFn: () => revenueForecastApi.pipeline().then((r) => r.data),
    enabled: !!summaryWidget,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: risks, isError: risksError } = useQuery({
    queryKey: ["revenue-forecast-risks"],
    queryFn: () => revenueForecastApi.risks().then((r) => r.data),
    enabled: !!summaryWidget,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: executive, isError: executiveError } = useQuery({
    queryKey: ["revenue-forecast-executive"],
    queryFn: () => revenueForecastApi.executive().then((r) => r.data),
    enabled: !!summaryWidget,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const generateMutation = useMutation({
    mutationFn: () => revenueForecastApi.generateForecast().then((r) => r.data),
    onSuccess: (data) => {
      setGenerated(data);
      toast.success("Forecast generated");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isOverviewLoading(summaryWidget, widgetError)) {
    return <LoadingState message="Loading revenue forecast…" />;
  }
  if (widgetError || !summaryWidget) {
    return <ErrorState error={widgetErr} onRetry={() => refetchWidget()} />;
  }

  const forecasts: RevenueForecastPeriod[] = overview?.forecasts ?? [
    {
      period: "30d",
      best_case: summaryWidget.best_case_30d,
      expected_case: summaryWidget.expected_30d,
      worst_case: summaryWidget.worst_case_30d,
      currency: summaryWidget.currency,
    },
  ];
  const activeForecast = forecasts.find((f) => f.period === activePeriod) ?? forecasts[0];
  const exec = executive?.executive;
  const allRisks: RevenueForecastRiskItem[] = risks
    ? [
        ...(risks.inactive_deals ?? []),
        ...(risks.overdue_opportunities ?? []),
        ...(risks.proposals_at_risk ?? []),
        ...(risks.communication_risks ?? []),
      ]
    : summaryWidget.top_risks.map((r, i) => ({
        risk_id: `widget-${i}`,
        title: r.title,
        description: "",
        severity: r.severity,
        category: r.category,
      }));

  const partialErrors = [
    ...(overviewError ? [t("errors.sectionUnavailable")] : []),
    ...(overview?.errors ?? []),
    ...(summaryWidget.errors ?? []),
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <TrendingUp size={22} className="text-emerald-600" />
            AI Revenue Forecast
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Heuristic revenue prediction from CRM, deals, proposals, and sales intelligence. Read-only.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary flex items-center gap-1.5"
          disabled={generateMutation.isPending}
          onClick={() => generateMutation.mutate()}
        >
          {generateMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Sparkles size={14} />
          )}
          Generate forecast
        </button>
      </div>

      <PartialErrorsBanner errors={partialErrors} />
      {overview?.safety_notice && (
        <p className="text-[10px] text-gray-400">{overview.safety_notice}</p>
      )}

      <section className="card p-4 grid sm:grid-cols-4 gap-3 text-center text-xs">
        <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
          <p className="text-[10px] text-brand-700">Expected (30d)</p>
          <p className="text-lg font-semibold tabular-nums">{fmtMoney(summaryWidget.expected_30d)}</p>
        </div>
        <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
          <p className="text-[10px] text-emerald-700">Best case (30d)</p>
          <p className="text-lg font-semibold tabular-nums">{fmtMoney(summaryWidget.best_case_30d)}</p>
        </div>
        <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
          <p className="text-[10px] text-red-700">Worst case (30d)</p>
          <p className="text-lg font-semibold tabular-nums">{fmtMoney(summaryWidget.worst_case_30d)}</p>
        </div>
        <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
          <p className="text-[10px] text-violet-700">Pipeline forecast</p>
          <p className="text-lg font-semibold tabular-nums">{fmtMoney(summaryWidget.pipeline_forecast)}</p>
        </div>
      </section>

      {(overview?.inputs_summary?.buyer_contributions as Array<{
        buyer_id: string;
        name: string;
        buyer_score: number;
        classification: string;
      }> | undefined)?.length ? (
        <section className="card p-4 space-y-2 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Buyer contribution</p>
            <Link href="/buyer-intelligence" className="text-xs text-brand-700 hover:underline">
              Buyer Intelligence →
            </Link>
          </div>
          <ul className="text-xs text-gray-600 space-y-1">
            {(
              overview!.inputs_summary.buyer_contributions as Array<{
                name: string;
                buyer_score: number;
                classification: string;
              }>
            )
              .slice(0, 5)
              .map((b, i) => (
                <li key={i}>
                  {b.name} — score {b.buyer_score} ({b.classification.replace(/_/g, " ")})
                </li>
              ))}
          </ul>
        </section>
      ) : null}

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">1. Revenue Forecast</p>
        <div className="flex flex-wrap gap-2">
          {forecasts.map((f) => (
            <button
              key={f.period}
              type="button"
              onClick={() => setActivePeriod(f.period)}
              className={cn(
                "text-xs px-3 py-1.5 rounded-full border font-medium capitalize",
                activePeriod === f.period
                  ? "bg-brand-600 text-white border-brand-600"
                  : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50",
              )}
            >
              {PERIOD_LABELS[f.period] ?? f.period}
            </button>
          ))}
          <span className="text-[10px] text-gray-400 self-center ml-2">
            Confidence: {overview?.confidence ?? summaryWidget.confidence}
          </span>
        </div>
        {activeForecast ? (
          <ForecastCard row={activeForecast} />
        ) : (
          <EmptyState title="No forecast" description="Select a period." />
        )}
        <div className="grid md:grid-cols-3 gap-3">
          {forecasts.map((f) => (
            <ForecastCard key={f.period} row={f} />
          ))}
        </div>
        {overviewError && (
          <p className="text-xs text-amber-700">{t("errors.sectionUnavailable")}</p>
        )}
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">2. Pipeline Forecast</p>
        <div className="card p-4 overflow-x-auto">
          {pipelineError ? (
            <p className="text-sm text-gray-500">{t("errors.sectionUnavailable")}</p>
          ) : (pipeline?.stages?.length ?? 0) === 0 ? (
            <EmptyState title="No pipeline data" description="CRM pipeline is empty." />
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                  <th className="py-2 px-2 font-medium">Stage</th>
                  <th className="py-2 px-2 font-medium">Count</th>
                  <th className="py-2 px-2 font-medium">Forecast revenue</th>
                  <th className="py-2 px-2 font-medium">Win %</th>
                </tr>
              </thead>
              <tbody>
                {pipeline!.stages.map((s: RevenueForecastPipelineStage) => (
                  <tr key={s.stage} className="border-b border-gray-50">
                    <td className="py-2 px-2 text-xs capitalize font-medium text-gray-800">{s.stage}</td>
                    <td className="py-2 px-2 text-xs tabular-nums">{s.count}</td>
                    <td className="py-2 px-2 text-xs tabular-nums">{fmtMoney(s.forecast_revenue)}</td>
                    <td className="py-2 px-2 text-xs tabular-nums">{Math.round(s.win_probability * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {pipeline && (
            <p className="text-[10px] text-gray-500 mt-3">
              Total pipeline forecast: {fmtMoney(pipeline.total_pipeline_forecast)} {pipeline.currency}
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <AlertTriangle size={16} className="text-orange-600" />
          3. Revenue Risks
        </p>
        <div className="card p-4 space-y-2">
          {risksError ? (
            <p className="text-sm text-gray-500">{t("errors.sectionUnavailable")}</p>
          ) : allRisks.length === 0 ? (
            <EmptyState title="No risks flagged" description="Forecast risk profile looks stable." />
          ) : (
            allRisks.map((r) => (
              <div
                key={r.risk_id}
                className="flex items-start justify-between gap-3 border-b border-gray-50 pb-2 last:border-0"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{r.title}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{r.description}</p>
                  <p className="text-[10px] text-gray-400 capitalize">{r.category}</p>
                </div>
                <span
                  className={cn(
                    "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize shrink-0",
                    SEVERITY_STYLES[r.severity] ?? SEVERITY_STYLES.medium,
                  )}
                >
                  {r.severity}
                </span>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <CircleDollarSign size={16} className="text-emerald-600" />
          4. Growth Opportunities
        </p>
        <div className="card p-4 space-y-2">
          {executiveError ? (
            <p className="text-sm text-gray-500">{t("errors.sectionUnavailable")}</p>
          ) : (exec?.top_growth_opportunities?.length ?? summaryWidget.top_growth.length) === 0 ? (
            <EmptyState title="No opportunities" description="Run lead and deal intelligence scans." />
          ) : (
            (exec?.top_growth_opportunities ??
              summaryWidget.top_growth.map((g, i) => ({
                opportunity_id: `widget-${i}`,
                title: g.title,
                description: "",
                expected_impact: g.expected_impact,
                priority: g.priority,
                source: "summary",
              }))
            ).map((g: RevenueForecastGrowthOpportunity) => (
              <div key={g.opportunity_id} className="border-b border-gray-50 pb-2 last:border-0">
                <p className="text-sm font-medium text-gray-900">{g.title}</p>
                <p className="text-xs text-gray-500 mt-0.5">{g.description}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">
                  Impact {fmtMoney(g.expected_impact)} · {g.priority} · {g.source}
                </p>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">5. Executive Forecast</p>
        <div className="card p-4 space-y-3">
          {executiveError ? (
            <p className="text-sm text-gray-500">{t("errors.sectionUnavailable")}</p>
          ) : exec ? (
            <>
              <p className="text-sm text-gray-700">{exec.forecast_summary}</p>
              {(exec.top_revenue_risks?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-800 mb-1">Top revenue risks</p>
                  <ul className="text-xs text-gray-600 space-y-1">
                    {exec.top_revenue_risks.slice(0, 4).map((r) => (
                      <li key={r.risk_id}>• {r.title}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <EmptyState title="Executive forecast unavailable" />
          )}
          <p className="text-[10px] text-gray-400">
            Sources:{" "}
            <Link href="/crm" className="text-brand-700 hover:underline">
              CRM
            </Link>
            ,{" "}
            <Link href="/sales-department-v3" className="text-brand-700 hover:underline">
              Sales Department v3
            </Link>
            ,{" "}
            <Link href="/revenue-attribution" className="text-brand-700 hover:underline">
              Revenue Attribution
            </Link>
            ,{" "}
            <Link href="/multi-agent" className="text-brand-700 hover:underline">
              Multi-Agent Team
            </Link>
          </p>
        </div>
      </section>

      {generated && (
        <section className="card p-4 space-y-2 border-emerald-100">
          <p className="text-sm font-semibold text-gray-900">Generated forecast snapshot</p>
          <p className="text-xs text-gray-600">{generated.executive.forecast_summary}</p>
          <p className="text-[10px] text-gray-400">{generated.safety_notice}</p>
        </section>
      )}
    </div>
  );
}
