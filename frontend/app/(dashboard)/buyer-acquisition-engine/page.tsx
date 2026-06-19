"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Building2,
  CircleDollarSign,
  Globe,
  Loader2,
  RefreshCw,
  Shield,
  Target,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  buyerAcquisitionEngineApi,
  BuyerEnginePipelineStatus,
  revenueEngineApi,
  dealRoomV2Api,
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
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";
import { buyerPipelineLabels } from "@/lib/uiLabels";

type Section =
  | "overview"
  | "database"
  | "matches"
  | "opportunities"
  | "pipeline"
  | "crm"
  | "actions";

const SECTIONS: { id: Section; labelKey: string; icon: typeof Users }[] = [
  { id: "overview", labelKey: "buyer.sectionOverview", icon: Users },
  { id: "database", labelKey: "buyer.sectionDatabase", icon: Building2 },
  { id: "matches", labelKey: "buyer.sectionMatches", icon: Target },
  { id: "opportunities", labelKey: "buyer.sectionOpportunities", icon: Globe },
  { id: "pipeline", labelKey: "buyer.sectionPipeline", icon: TrendingUp },
  { id: "crm", labelKey: "buyer.sectionCrmSummary", icon: Zap },
  { id: "actions", labelKey: "buyer.sectionGuidedActions", icon: ArrowRight },
];

function MatchBadge({ score }: { score: number }) {
  const variant = score >= 75 ? "info" : score >= 50 ? "success" : "neutral";
  return (
    <StatusBadge variant={variant} className="tabular-nums">
      {score}
    </StatusBadge>
  );
}

export default function BuyerAcquisitionEnginePage() {
  const { t } = useTranslation();
  const pipelineLabels = useMemo(() => buyerPipelineLabels(t), [t]);
  const [section, setSection] = useState<Section>("overview");
  const [pipelineFilter, setPipelineFilter] = useState<BuyerEnginePipelineStatus | "">("");
  const qc = useQueryClient();

  const {
    data: overview,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["buyer-acquisition-engine-overview"],
    queryFn: () => buyerAcquisitionEngineApi.overview().then((r) => r.data),
  });

  const { data: buyersData, isLoading: buyersLoading } = useQuery({
    queryKey: ["buyer-acquisition-engine-buyers", pipelineFilter],
    queryFn: () =>
      buyerAcquisitionEngineApi
        .buyers({
          pipeline_status: pipelineFilter || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!overview && section === "database",
  });

  const { data: matchesData, isLoading: matchesLoading } = useQuery({
    queryKey: ["buyer-acquisition-engine-matches"],
    queryFn: () => buyerAcquisitionEngineApi.matches({ limit: 50 }).then((r) => r.data),
    enabled: !!overview && section === "matches",
  });

  const { data: oppsData, isLoading: oppsLoading } = useQuery({
    queryKey: ["buyer-acquisition-engine-opportunities"],
    queryFn: () => buyerAcquisitionEngineApi.opportunities().then((r) => r.data),
    enabled: !!overview && section === "opportunities",
  });

  const { data: pipelineData } = useQuery({
    queryKey: ["buyer-acquisition-engine-pipeline"],
    queryFn: () => buyerAcquisitionEngineApi.pipeline().then((r) => r.data),
    enabled: !!overview && section === "pipeline",
  });

  const { data: crmSummary } = useQuery({
    queryKey: ["buyer-acquisition-engine-summary"],
    queryFn: () => buyerAcquisitionEngineApi.summary().then((r) => r.data),
    enabled: !!overview && section === "crm",
  });

  const { data: revenueImpact } = useQuery({
    queryKey: ["buyer-acquisition-engine-revenue-impact"],
    queryFn: () => revenueEngineApi.revenueImpactPanel().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: dealRoomPanel } = useQuery({
    queryKey: ["buyer-acquisition-engine-deal-room-panel"],
    queryFn: () => dealRoomV2Api.dealAcquisitionPanel().then((r) => r.data),
    enabled: !!overview,
  });

  const refreshMutation = useMutation({
    mutationFn: () => buyerAcquisitionEngineApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(`Assessment refreshed — readiness ${data.readiness_score}%`);
      qc.invalidateQueries({ queryKey: ["buyer-acquisition-engine"] });
    },
    onError: () => toast.error(t("pilot.refreshFailed")),
  });

  const kpis = useMemo(
    () =>
      overview
        ? [
            { label: t("buyer.totalBuyersKpi"), value: overview.total_buyers },
            { label: t("buyer.highMatch"), value: overview.high_match_buyers },
            { label: t("buyer.activePipelineKpi"), value: overview.active_pipeline_leads },
            { label: t("buyer.avgMatch"), value: `${overview.average_match_score}%` },
            { label: t("buyer.readinessKpi"), value: `${overview.readiness_score}%` },
          ]
        : [],
    [overview, t],
  );

  if (isLoading) return <DashboardSkeleton />;
  if (isError || !overview) {
    return (
      <ErrorState message={t("buyer.loadError")} onRetry={() => refetch()} />
    );
  }

  const crm = overview.crm_summary;

  return (
    <PageShell wide>
      <PageHeader
        title={t("buyer.title")}
        subtitle={t("buyer.subtitle")}
        icon={Target}
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
            <Link href="/buyer-acquisition" className="btn-secondary text-sm">
              {t("buyer.unifiedAcquisition")}
            </Link>
            <Link href="/crm" className="btn-secondary text-sm">
              {t("buyer.crm")}
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
              <Target size={16} className="text-violet-700" />
              {t("buyer.dealRoomIntegration")}
            </p>
            <Link href="/deal-room" className="text-xs text-brand-700 hover:underline">
              {t("buyer.openDealRoom")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-3 gap-2 text-xs">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2">
              <p className="text-gray-500">{t("buyer.activeDealRooms")}</p>
              <p className="font-semibold tabular-nums">{dealRoomPanel.active_deal_rooms}</p>
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
              <p className="text-gray-500">{t("buyer.connectedDeals")}</p>
              <p className="font-medium tabular-nums">{dealRoomPanel.deals.length}</p>
            </div>
          </div>
          {dealRoomPanel.deals.length > 0 && (
            <ul className="text-xs space-y-1">
              {dealRoomPanel.deals.slice(0, 4).map((d) => (
                <li key={d.deal_room_id} className="flex justify-between gap-2">
                  <Link href={`/deal-room?id=${d.deal_room_id}`} className="text-brand-700 hover:underline">
                    {d.deal_name}
                  </Link>
                  <span className="text-gray-500 capitalize">{d.relationship_strength}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-gray-600">{dealRoomPanel.message}</p>
          <p className="text-[10px] text-gray-400">{dealRoomPanel.safety_notice}</p>
        </section>
      )}

      {revenueImpact && (
        <section className="card p-5 space-y-3 border-emerald-100 mb-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CircleDollarSign size={16} className="text-emerald-700" />
              {t("buyer.revenueImpact")}
            </p>
            <Link href="/revenue-engine" className="text-xs text-brand-700 hover:underline">
              {t("buyer.openRevenueEngine")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-2 text-xs">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2">
              <p className="text-gray-500">{t("buyer.readinessKpi")}</p>
              <p className="font-semibold tabular-nums text-emerald-900">
                {revenueImpact.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.pipelineValue")}</p>
              <p className="font-medium tabular-nums">
                {revenueImpact.total_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.forecasted")}</p>
              <p className="font-medium tabular-nums">
                {revenueImpact.forecasted_revenue.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.activeDeals")}</p>
              <p className="font-medium tabular-nums">{revenueImpact.active_deals}</p>
            </div>
          </div>
          <p className="text-xs text-gray-600">{revenueImpact.message}</p>
          <p className="text-[10px] text-gray-400">{revenueImpact.safety_notice}</p>
        </section>
      )}

      <div className="flex flex-wrap gap-2 mb-6">
        {SECTIONS.map(({ id, labelKey, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors",
              section === id
                ? "bg-brand-700 text-white border-brand-700"
                : "bg-white text-gray-600 border-gray-200 hover:border-brand-300",
            )}
          >
            <Icon size={12} />
            {t(labelKey)}
          </button>
        ))}
      </div>

      {section === "overview" && (
        <div className="space-y-6">
          <PageSection title={t("buyer.factoryBuyerView")}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <KpiCard label={t("buyer.topBuyers")} value={overview.factory_view.top_buyers.length} />
              <KpiCard label={t("buyer.highMatch")} value={overview.factory_view.best_matches.length} />
              <KpiCard
                label={t("factory.activeOpportunities")}
                value={overview.factory_view.active_opportunities}
              />
              <KpiCard label={t("buyer.activePipelineKpi")} value={overview.active_pipeline_leads} />
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h3 className="text-sm font-semibold mb-3">{t("buyer.topBuyers")}</h3>
                {overview.factory_view.top_buyers.length === 0 ? (
                  <EmptyState message={t("buyer.emptyBuyers")} />
                ) : (
                  <ul className="space-y-2">
                    {overview.factory_view.top_buyers.map((b) => (
                      <li
                        key={b.buyer_id}
                        className="flex items-center justify-between text-sm border-b border-gray-50 pb-2"
                      >
                        <span>{b.company_name}</span>
                        <MatchBadge score={b.match_score} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="card p-4">
                <h3 className="text-sm font-semibold mb-3">{t("buyer.leadCountsByStage")}</h3>
                <ul className="space-y-1 text-sm">
                  {Object.entries(overview.factory_view.lead_counts).map(([st, count]) => (
                    <li key={st} className="flex justify-between">
                      <span className="text-gray-600">
                        {pipelineLabels[st as BuyerEnginePipelineStatus] ?? st}
                      </span>
                      <span className="font-medium tabular-nums">{count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </PageSection>

          <PageSection title={t("buyer.crmSnapshot")}>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <KpiCard label={t("buyer.totalLeads")} value={crm.total_leads} />
              <KpiCard label={t("buyer.activeLeads")} value={crm.active_leads} />
              <KpiCard label={t("buyer.wonDeals")} value={crm.won_deals} />
              <KpiCard label={t("buyer.lostDeals")} value={crm.lost_deals} />
              <KpiCard
                label={t("revenue.pipelineValue")}
                value={crm.pipeline_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              />
            </div>
          </PageSection>
        </div>
      )}

      {section === "database" && (
        <PageSection title={t("buyer.sectionDatabase")}>
          <div className="flex gap-2 mb-4">
            <select
              className="input text-sm"
              value={pipelineFilter}
              onChange={(e) => setPipelineFilter(e.target.value as BuyerEnginePipelineStatus | "")}
            >
              <option value="">{t("buyer.allPipelineStages")}</option>
              {(Object.keys(pipelineLabels) as BuyerEnginePipelineStatus[]).map((st) => (
                <option key={st} value={st}>
                  {pipelineLabels[st]}
                </option>
              ))}
            </select>
          </div>
          {buyersLoading && <LoadingState label={t("buyer.loadingDatabase")} />}
          {buyersData && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-500">
                    <th className="p-2">{t("buyer.colCompany")}</th>
                    <th className="p-2">{t("buyer.colCountry")}</th>
                    <th className="p-2">{t("buyer.colIndustry")}</th>
                    <th className="p-2">{t("buyer.colEmail")}</th>
                    <th className="p-2">{t("buyer.colPhone")}</th>
                    <th className="p-2">{t("buyer.colWhatsapp")}</th>
                    <th className="p-2">{t("buyer.colWechat")}</th>
                    <th className="p-2">{t("buyer.colStatus")}</th>
                    <th className="p-2">{t("buyer.colMatch")}</th>
                  </tr>
                </thead>
                <tbody>
                  {buyersData.items.map((b) => (
                    <tr key={b.buyer_id} className="border-b hover:bg-gray-50/80">
                      <td className="p-2 font-medium">{b.company_name}</td>
                      <td className="p-2">{b.country ?? "—"}</td>
                      <td className="p-2">{b.industry ?? "—"}</td>
                      <td className="p-2 text-xs">{b.email ?? "—"}</td>
                      <td className="p-2 text-xs">{b.phone ?? "—"}</td>
                      <td className="p-2 text-xs">{b.whatsapp ?? "—"}</td>
                      <td className="p-2 text-xs">{b.wechat ?? "—"}</td>
                      <td className="p-2">
                        <StatusBadge variant="neutral">{b.status}</StatusBadge>
                      </td>
                      <td className="p-2">
                        <MatchBadge score={b.match_score} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {buyersData.items.length === 0 && (
                <EmptyState message="No buyers match the current filters" />
              )}
            </div>
          )}
        </PageSection>
      )}

      {section === "matches" && (
        <PageSection title={t("buyer.sectionMatches")}>
          {matchesLoading && <LoadingState label={t("common.loading")} />}
          {matchesData && (
            <>
              <div className="grid md:grid-cols-3 gap-3 mb-4 text-xs text-gray-600">
                <div className="card p-3">
                  <span className="font-medium">Factory industries:</span>{" "}
                  {matchesData.factory_industries.join(", ") || "—"}
                </div>
                <div className="card p-3">
                  <span className="font-medium">Products:</span>{" "}
                  {matchesData.factory_products.slice(0, 8).join(", ") || "—"}
                </div>
                <div className="card p-3">
                  <span className="font-medium">Export markets:</span>{" "}
                  {matchesData.export_markets.join(", ") || "—"}
                </div>
              </div>
              <p className="text-xs text-gray-500 mb-3">
                Average match score: {matchesData.average_match_score}/100
              </p>
              <div className="space-y-2">
                {matchesData.items.map((m) => (
                  <div
                    key={m.buyer_id}
                    className="card p-3 flex flex-wrap items-center justify-between gap-2"
                  >
                    <div>
                      <p className="font-medium text-sm">{m.company_name}</p>
                      <p className="text-xs text-gray-500">
                        {[m.country, m.industry].filter(Boolean).join(" · ") || "—"}
                      </p>
                    </div>
                    <MatchBadge score={m.match_score} />
                  </div>
                ))}
                {matchesData.items.length === 0 && (
                  <EmptyState message="No buyer matches above threshold" />
                )}
              </div>
            </>
          )}
        </PageSection>
      )}

      {section === "opportunities" && (
        <PageSection title={t("buyer.sectionOpportunities")}>
          {oppsLoading && <LoadingState label={t("customerPortal.loadingOpportunities")} />}
          {oppsData && (
            <div className="grid lg:grid-cols-3 gap-4">
              {(
                [
                  [t("buyer.oppBuyer"), oppsData.buyer_opportunities],
                  [t("buyer.oppCountry"), oppsData.country_opportunities],
                  [t("buyer.oppIndustry"), oppsData.industry_opportunities],
                ] as const
              ).map(([title, items]) => (
                <div key={title} className="card p-4">
                  <h3 className="text-sm font-semibold mb-3">{title}</h3>
                  <ul className="space-y-2">
                    {items.slice(0, 8).map((o) => (
                      <li key={o.opportunity_id} className="text-sm border-b border-gray-50 pb-2">
                        <div className="flex justify-between gap-2">
                          <span className="font-medium">{o.title}</span>
                          <MatchBadge score={o.score} />
                        </div>
                        {o.subtitle && (
                          <p className="text-xs text-gray-500">{o.subtitle}</p>
                        )}
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
        </PageSection>
      )}

      {section === "pipeline" && pipelineData && (
        <PageSection title={t("buyer.sectionPipeline")}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <KpiCard label={t("buyer.totalLeads")} value={pipelineData.total} />
            <KpiCard label={t("buyer.activeLeads")} value={pipelineData.active_count} />
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {pipelineData.stages.map((s) => (
              <div key={s.status} className="card p-3 text-center">
                <p className="text-2xl font-bold tabular-nums">{s.count}</p>
                <p className="text-xs text-gray-600 mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        </PageSection>
      )}

      {section === "crm" && crmSummary && (
        <PageSection title={t("buyer.sectionCrmSummary")}>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <KpiCard label={t("buyer.totalLeads")} value={crmSummary.total_leads} />
            <KpiCard label={t("buyer.activeLeads")} value={crmSummary.active_leads} />
            <KpiCard label={t("buyer.wonDeals")} value={crmSummary.won_deals} />
            <KpiCard label={t("buyer.lostDeals")} value={crmSummary.lost_deals} />
            <KpiCard
              label={t("revenue.pipelineValue")}
              value={crmSummary.pipeline_value.toLocaleString(undefined, {
                maximumFractionDigits: 0,
              })}
            />
            <KpiCard label={t("buyer.avgMatch")} value={`${crmSummary.average_match_score}%`} />
          </div>
          <p className="text-xs text-gray-400 mt-4">{crmSummary.safety_notice}</p>
        </PageSection>
      )}

      {section === "actions" && (
        <PageSection title={t("buyer.sectionGuidedActions")}>
          <p className="text-xs text-gray-500 mb-4">{t("deal.hintsOnly")}</p>
          <div className="grid md:grid-cols-2 gap-3">
            {overview.guided_actions.map((a) => (
              <Link
                key={a.key}
                href={a.route}
                className={cn(
                  "card p-4 block hover:border-brand-300 transition-colors",
                  !a.enabled && "opacity-50 pointer-events-none",
                )}
              >
                <p className="font-medium text-sm">{a.title}</p>
                <p className="text-xs text-gray-500 mt-1">{a.description}</p>
                <span className="text-xs text-brand-700 mt-2 inline-flex items-center gap-1">
                  {t("common.open")} <ArrowRight size={12} />
                </span>
              </Link>
            ))}
          </div>
        </PageSection>
      )}
    </PageShell>
  );
}
