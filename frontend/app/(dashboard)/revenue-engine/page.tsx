"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Briefcase,
  Building2,
  CircleDollarSign,
  Factory,
  Loader2,
  RefreshCw,
  Shield,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  revenueEngineApi,
  dealRoomV2Api,
  RevenueEngineDealStage,
  RevenueHealthStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";
import { DashboardSkeleton } from "@/components/ui/Skeleton";
import {
  ExecutiveKpiBar,
  KpiCard,
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";
import { isOverviewLoading } from "@/lib/overview-query-options";
import { revenueStageLabels, translateHealthStatus } from "@/lib/uiLabels";

type Section =
  | "overview"
  | "pipeline"
  | "forecast"
  | "factories"
  | "opportunities"
  | "health"
  | "actions";

const SECTIONS: { id: Section; labelKey: string; icon: typeof CircleDollarSign }[] = [
  { id: "overview", labelKey: "revenue.sectionOverview", icon: CircleDollarSign },
  { id: "pipeline", labelKey: "revenue.sectionPipeline", icon: TrendingUp },
  { id: "forecast", labelKey: "revenue.sectionForecast", icon: Zap },
  { id: "factories", labelKey: "revenue.sectionFactories", icon: Factory },
  { id: "opportunities", labelKey: "revenue.sectionOpportunities", icon: Target },
  { id: "health", labelKey: "revenue.sectionHealth", icon: Shield },
  { id: "actions", labelKey: "revenue.sectionGuidedActions", icon: ArrowRight },
];

const HEALTH_VARIANT: Record<RevenueHealthStatus, "success" | "warning" | "danger"> = {
  healthy: "success",
  warning: "warning",
  critical: "danger",
};

function fmtMoney(val: number | null | undefined, currency = "UZS"): string {
  if (val == null) return "—";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(val)} ${currency}`;
}

export default function RevenueEnginePage() {
  const { t } = useTranslation();
  const stageLabels = useMemo(() => revenueStageLabels(t), [t]);
  const [section, setSection] = useState<Section>("overview");
  const [stageFilter, setStageFilter] = useState<RevenueEngineDealStage | "">("");
  const qc = useQueryClient();

  const {
    data: overview,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["revenue-engine-overview"],
    queryFn: () => revenueEngineApi.overview().then((r) => r.data),
  });

  const { data: dealsData, isLoading: dealsLoading } = useQuery({
    queryKey: ["revenue-engine-deals", stageFilter],
    queryFn: () =>
      revenueEngineApi
        .deals({ stage: stageFilter || undefined, limit: 100 })
        .then((r) => r.data),
    enabled: !!overview && section === "pipeline",
  });

  const { data: forecastData } = useQuery({
    queryKey: ["revenue-engine-forecast"],
    queryFn: () => revenueEngineApi.forecast().then((r) => r.data),
    enabled: !!overview && section === "forecast",
  });

  const { data: factoriesData, isLoading: factoriesLoading } = useQuery({
    queryKey: ["revenue-engine-factories"],
    queryFn: () => revenueEngineApi.factories({ limit: 50 }).then((r) => r.data),
    enabled: !!overview && section === "factories",
  });

  const { data: oppsData, isLoading: oppsLoading } = useQuery({
    queryKey: ["revenue-engine-opportunities"],
    queryFn: () => revenueEngineApi.opportunities().then((r) => r.data),
    enabled: !!overview && section === "opportunities",
  });

  const { data: healthData } = useQuery({
    queryKey: ["revenue-engine-health"],
    queryFn: () => revenueEngineApi.health().then((r) => r.data),
    enabled: !!overview && section === "health",
  });

  const { data: dealRoomPanel } = useQuery({
    queryKey: ["revenue-engine-deal-room-panel"],
    queryFn: () => dealRoomV2Api.dealRevenuePanel().then((r) => r.data),
    enabled: !!overview,
  });

  const refreshMutation = useMutation({
    mutationFn: () => revenueEngineApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(`Assessment refreshed — readiness ${data.readiness_score}%`);
      qc.invalidateQueries({ queryKey: ["revenue-engine"] });
    },
    onError: () => toast.error(t("pilot.refreshFailed")),
  });

  const kpis = useMemo(
    () =>
      overview
        ? [
            { label: t("revenue.pipelineValue"), value: fmtMoney(overview.executive_dashboard.total_pipeline_value) },
            { label: t("revenue.forecasted"), value: fmtMoney(overview.executive_dashboard.forecasted_revenue) },
            { label: t("revenue.wonRevenue"), value: fmtMoney(overview.executive_dashboard.won_revenue) },
            { label: t("revenue.activeDeals"), value: overview.executive_dashboard.active_opportunities },
            { label: t("revenue.readiness"), value: `${overview.readiness_score}%` },
          ]
        : [],
    [overview, t],
  );

  if (isOverviewLoading(overview, isError)) return <DashboardSkeleton />;
  if (isError || !overview) {
    return <ErrorState message={t("revenue.loadError")} onRetry={() => refetch()} />;
  }

  const exec = overview.executive_dashboard;
  const health = overview.health;

  return (
    <PageShell wide>
      <PageHeader
        title={t("revenue.title")}
        subtitle={t("revenue.subtitle")}
        icon={CircleDollarSign}
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary text-sm inline-flex items-center gap-1.5"
              disabled={refreshMutation.isPending}
              onClick={() => refreshMutation.mutate()}
            >
              {refreshMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
              {t("pilot.refresh")}
            </button>
            <Link href="/crm" className="btn-secondary text-sm">
              {t("revenue.crm")}
            </Link>
            <Link href="/revenue-forecast" className="btn-secondary text-sm">
              {t("revenue.revenueForecast")}
            </Link>
          </div>
        }
      />

      <div className="card p-3 border-amber-100 bg-amber-50/50 text-xs text-amber-900 flex items-start gap-2 mb-4">
        <Shield size={14} className="shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      <PartialErrorsBanner errors={overview.errors} />

      <ExecutiveKpiBar items={kpis} />

      {dealRoomPanel && (
        <section className="card p-5 space-y-3 border-violet-100 mb-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Briefcase size={16} className="text-violet-700" />
              {t("buyer.dealRoomIntegration")}
            </p>
            <Link href="/deal-room" className="text-xs text-brand-700 hover:underline">
              {t("revenue.openDealRoom")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-2 text-xs">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2">
              <p className="text-gray-500">{t("revenue.roomReadiness")}</p>
              <p className="font-semibold tabular-nums">{dealRoomPanel.readiness_score}%</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.pipelineValue")}</p>
              <p className="font-medium tabular-nums">
                {dealRoomPanel.total_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.weighted")}</p>
              <p className="font-medium tabular-nums">
                {dealRoomPanel.weighted_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.activeRooms")}</p>
              <p className="font-medium tabular-nums">{dealRoomPanel.active_deal_rooms}</p>
            </div>
          </div>
          {dealRoomPanel.deals.length > 0 && (
            <ul className="text-xs space-y-1">
              {dealRoomPanel.deals.slice(0, 4).map((d) => (
                <li key={d.deal_room_id} className="flex justify-between gap-2">
                  <Link href={`/deal-room?id=${d.deal_room_id}`} className="text-brand-700 hover:underline">
                    {d.deal_name}
                  </Link>
                  <span className="text-gray-500 tabular-nums">
                    {d.expected_revenue.toLocaleString(undefined, { maximumFractionDigits: 0 })}{" "}
                    {dealRoomPanel.currency}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-gray-600">{dealRoomPanel.message}</p>
          <p className="text-[10px] text-gray-400">{dealRoomPanel.safety_notice}</p>
        </section>
      )}

      <div className="flex flex-wrap gap-1.5 mb-4">
        {SECTIONS.map((s) => {
          const Icon = s.icon;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => setSection(s.id)}
              className={cn(
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
                section === s.id
                  ? "bg-brand-50 border-brand-200 text-brand-900"
                  : "bg-white border-gray-200 text-gray-600 hover:border-gray-300",
              )}
            >
              <Icon size={14} />
              {t(s.labelKey)}
            </button>
          );
        })}
      </div>

      {section === "overview" && (
        <div className="space-y-4">
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard label={t("revenue.pipelineValue")} value={fmtMoney(exec.total_pipeline_value)} />
            <KpiCard label={t("revenue.weightedPipeline")} value={fmtMoney(exec.weighted_pipeline_value)} />
            <KpiCard label={t("revenue.forecasted")} value={fmtMoney(exec.forecasted_revenue)} />
            <KpiCard label={t("revenue.dealCount")} value={exec.deal_count} />
          </div>
          <div className="card p-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-gray-900">{t("revenue.revenueHealth")}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Score {health.health_score} · Win rate {health.win_rate}%
              </p>
            </div>
            <StatusBadge variant={HEALTH_VARIANT[health.status]}>
              {translateHealthStatus(t, health.status)}
            </StatusBadge>
          </div>
          {overview.top_opportunities.length > 0 && (
            <div className="card p-4 space-y-3">
              <p className="text-sm font-semibold text-gray-900">{t("revenue.sectionOpportunities")}</p>
              <ul className="space-y-2 text-sm">
                {overview.top_opportunities.slice(0, 6).map((o) => (
                  <li
                    key={o.opportunity_id}
                    className="flex items-center justify-between gap-2 border-b border-gray-50 pb-2"
                  >
                    <div>
                      <p className="font-medium">{o.title}</p>
                      <p className="text-xs text-gray-500">
                        {[o.buyer_name, o.factory_name, o.stage].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <span className="text-xs font-semibold tabular-nums text-emerald-800">
                      {fmtMoney(o.value)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {section === "pipeline" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2 items-center">
            <select
              className="input text-sm max-w-[180px]"
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value as RevenueEngineDealStage | "")}
            >
              <option value="">{t("revenue.allStages")}</option>
              {(Object.keys(stageLabels) as RevenueEngineDealStage[]).map((s) => (
                <option key={s} value={s}>
                  {stageLabels[s]}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
            {overview.pipeline.stages.map((st) => (
              <div key={st.stage} className="card p-3 text-center text-xs">
                <p className="text-gray-500 truncate">{st.label}</p>
                <p className="text-lg font-semibold tabular-nums">{st.count}</p>
                <p className="text-[10px] text-gray-400 tabular-nums">{fmtMoney(st.value)}</p>
              </div>
            ))}
          </div>
          {dealsLoading && <LoadingState message={t("common.loading")} />}
          {dealsData && dealsData.items.length === 0 && (
            <EmptyState message={t("revenue.emptyPipeline")} />
          )}
          {dealsData && dealsData.items.length > 0 && (
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-500">
                  <tr>
                    <th className="text-left p-3">{t("revenue.colDeal")}</th>
                    <th className="text-left p-3">{t("revenue.colBuyer")}</th>
                    <th className="text-left p-3">{t("revenue.colFactory")}</th>
                    <th className="text-left p-3">{t("revenue.colStage")}</th>
                    <th className="text-right p-3">{t("revenue.colValue")}</th>
                    <th className="text-right p-3">{t("revenue.colProb")}</th>
                  </tr>
                </thead>
                <tbody>
                  {dealsData.items.map((d) => (
                    <tr key={d.deal_id} className="border-t border-gray-50">
                      <td className="p-3 font-medium">{d.title}</td>
                      <td className="p-3 text-gray-600">{d.buyer_company || d.buyer_name || "—"}</td>
                      <td className="p-3 text-gray-600">{d.factory_name || "—"}</td>
                      <td className="p-3">
                        <StatusBadge variant="neutral">{d.stage_label}</StatusBadge>
                      </td>
                      <td className="p-3 text-right tabular-nums">{fmtMoney(d.value, d.currency)}</td>
                      <td className="p-3 text-right tabular-nums">{d.probability}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {section === "forecast" && (
        <div className="space-y-4">
          {(forecastData || overview.forecast) && (
            <>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {(() => {
                  const f = forecastData || overview.forecast;
                  return (
                    <>
                      <KpiCard label={t("revenue.pipelineValue")} value={fmtMoney(f.pipeline_value)} />
                      <KpiCard label={t("revenue.weightedPipeline")} value={fmtMoney(f.weighted_pipeline_value)} />
                      <KpiCard label={t("deal.expectedRevenue")} value={fmtMoney(f.expected_revenue)} />
                      <KpiCard label={t("revenue.wonRevenue")} value={fmtMoney(f.won_revenue)} />
                      <KpiCard label={t("revenue.stageLost")} value={fmtMoney(f.lost_revenue)} />
                      <KpiCard label={t("dashboard.forecast")} value={f.forecast_quality} />
                    </>
                  );
                })()}
              </div>
              <p className="text-xs text-gray-500">
                Active: {(forecastData || overview.forecast).active_deals} · Won:{" "}
                {(forecastData || overview.forecast).won_deals} · Lost:{" "}
                {(forecastData || overview.forecast).lost_deals}
              </p>
            </>
          )}
        </div>
      )}

      {section === "factories" && (
        <div className="space-y-4">
          {factoriesLoading && <LoadingState message={t("common.loading")} />}
          {factoriesData && factoriesData.items.length === 0 && (
            <EmptyState message={t("revenue.emptyFactoryRevenue")} />
          )}
          {factoriesData && factoriesData.items.length > 0 && (
            <div className="grid md:grid-cols-2 gap-3">
              {factoriesData.items.map((f) => (
                <div key={f.factory_id} className="card p-4 space-y-2 text-sm">
                  <div className="flex items-center gap-2">
                    <Building2 size={16} className="text-amber-700" />
                    <p className="font-semibold">{f.factory_name}</p>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <p className="text-gray-500">{t("revenue.activeDeals")}</p>
                      <p className="font-medium tabular-nums">{f.active_deals}</p>
                    </div>
                    <div>
                      <p className="text-gray-500">{t("revenue.stageWon")}</p>
                      <p className="font-medium tabular-nums">{f.won_deals}</p>
                    </div>
                    <div>
                      <p className="text-gray-500">{t("revenue.stageLost")}</p>
                      <p className="font-medium tabular-nums">{f.lost_deals}</p>
                    </div>
                  </div>
                  <p className="text-xs text-gray-600">
                    Pipeline {fmtMoney(f.pipeline_value)} · Forecast {fmtMoney(f.expected_revenue)} ·
                    Avg deal {fmtMoney(f.average_deal_size)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {section === "opportunities" && (
        <div className="space-y-4">
          {oppsLoading && <LoadingState message={t("customerPortal.loadingOpportunities")} />}
          {oppsData && (
            <div className="grid lg:grid-cols-3 gap-4">
              {(
                [
                  [t("revenue.sectionOpportunities"), oppsData.top_revenue_opportunities],
                  [t("revenue.colBuyer"), oppsData.highest_value_buyers],
                  [t("revenue.colFactory"), oppsData.highest_value_factories],
                ] as const
              ).map(([title, items]) => (
                <div key={title} className="card p-4 space-y-2">
                  <p className="text-sm font-semibold">{title}</p>
                  <ul className="space-y-2 text-sm">
                    {items.slice(0, 8).map((o) => (
                      <li key={o.opportunity_id} className="flex justify-between gap-2">
                        <span className="truncate">{o.title}</span>
                        <span className="text-xs tabular-nums shrink-0">{fmtMoney(o.value)}</span>
                      </li>
                    ))}
                    {items.length === 0 && (
                      <li className="text-xs text-gray-400">{t("common.nothingHere")}</li>
                    )}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {section === "health" && (
        <div className="space-y-4">
          <div className="card p-4 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">{t("revenue.overallHealth")}</p>
              <p className="text-2xl font-bold tabular-nums">
                {(healthData || health).health_score}%
              </p>
            </div>
            <StatusBadge variant={HEALTH_VARIANT[(healthData || health).status]}>
              {translateHealthStatus(t, (healthData || health).status)}
            </StatusBadge>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {(healthData || health).factors.map((f) => (
              <div key={f.key} className="card p-4 text-sm space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{f.label}</p>
                  <StatusBadge variant={HEALTH_VARIANT[f.status]}>{f.score}</StatusBadge>
                </div>
                <p className="text-xs text-gray-500">{f.message}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === "actions" && (
        <div className="grid sm:grid-cols-2 gap-3">
          {overview.guided_actions.map((a) => (
            <Link
              key={a.key}
              href={a.route}
              className={cn(
                "card p-4 block hover:border-brand-200 transition-colors",
                !a.enabled && "opacity-50 pointer-events-none",
              )}
            >
              <p className="text-sm font-semibold text-gray-900">{a.title}</p>
              <p className="text-xs text-gray-500 mt-1">{a.description}</p>
              <p className="text-xs text-brand-700 mt-2 inline-flex items-center gap-1">
                {t("common.open")} <ArrowRight size={12} />
              </p>
            </Link>
          ))}
        </div>
      )}
    </PageShell>
  );
}
