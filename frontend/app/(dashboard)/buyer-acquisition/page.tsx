"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Globe,
  Layers,
  Network,
  Search,
  Shield,
  Store,
  Target,
  TrendingUp,
  Users,
  Factory,
} from "lucide-react";
import {
  buyerAcquisitionApi,
  BuyerAcquisitionPipelineStage,
  UnifiedBuyerProfile,
  UnifiedOpportunityItem,
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
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";

type Section = "overview" | "buyers" | "opportunities" | "pipeline" | "network" | "insights";

const SECTIONS: { id: Section; label: string; icon: typeof Layers }[] = [
  { id: "overview", label: "Overview", icon: Layers },
  { id: "buyers", label: "Buyers", icon: Users },
  { id: "opportunities", label: "Opportunities", icon: Target },
  { id: "pipeline", label: "Pipeline", icon: TrendingUp },
  { id: "network", label: "Network", icon: Network },
  { id: "insights", label: "Insights", icon: Globe },
];

const PIPELINE_LABELS: Record<BuyerAcquisitionPipelineStage, string> = {
  discovered: "Discovered",
  researched: "Researched",
  qualified: "Qualified",
  contacted: "Contacted",
  opportunity: "Opportunity",
  customer: "Customer",
};

const SOURCE_STYLES: Record<string, string> = {
  marketplace: "bg-emerald-100 text-emerald-900 border-emerald-200",
  discovery: "bg-sky-100 text-sky-900 border-sky-200",
  network: "bg-violet-100 text-violet-900 border-violet-200",
  intelligence: "bg-indigo-100 text-indigo-900 border-indigo-200",
};

function ScoreBadge({ score }: { score: number }) {
  const variant = score >= 75 ? "info" : score >= 50 ? "success" : "neutral";
  return (
    <StatusBadge variant={variant} className="tabular-nums">
      {score}
    </StatusBadge>
  );
}

export default function BuyerAcquisitionPage() {
  const [section, setSection] = useState<Section>("overview");
  const [filterStage, setFilterStage] = useState<BuyerAcquisitionPipelineStage | "">("");
  const [filterSource, setFilterSource] = useState<"" | "marketplace" | "discovery" | "network">("");

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewError,
    refetch: refetchOverview,
  } = useQuery({
    queryKey: ["buyer-acquisition-overview"],
    queryFn: () => buyerAcquisitionApi.overview().then((r) => r.data),
  });

  const { data: buyersData, isLoading: buyersLoading } = useQuery({
    queryKey: ["buyer-acquisition-buyers", filterStage],
    queryFn: () =>
      buyerAcquisitionApi
        .buyers({
          pipeline_stage: filterStage || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!overview && (section === "buyers" || section === "network"),
  });

  const { data: opportunitiesData, isLoading: oppsLoading } = useQuery({
    queryKey: ["buyer-acquisition-opportunities", filterSource],
    queryFn: () =>
      buyerAcquisitionApi
        .opportunities({
          source: filterSource || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!overview && section === "opportunities",
  });

  const { data: pipelineData } = useQuery({
    queryKey: ["buyer-acquisition-pipeline"],
    queryFn: () => buyerAcquisitionApi.pipeline().then((r) => r.data),
    enabled: !!overview && section === "pipeline",
  });

  const { data: insightsData, isLoading: insightsLoading } = useQuery({
    queryKey: ["buyer-acquisition-insights"],
    queryFn: () => buyerAcquisitionApi.insights({ limit: 10 }).then((r) => r.data),
    enabled: !!overview && section === "insights",
  });

  const { data: factoryReadiness } = useQuery({
    queryKey: ["buyer-acquisition-factory-readiness"],
    queryFn: () => buyerAcquisitionApi.factoryReadiness().then((r) => r.data),
    enabled: !!overview && section === "overview",
  });

  const networkBuyers = useMemo(
    () => (buyersData?.items ?? []).filter((b) => b.sources.includes("network")),
    [buyersData],
  );

  if (overviewLoading) return <DashboardSkeleton />;
  if (overviewError || !overview)
    return (
      <ErrorState message="Failed to load buyer acquisition overview" onRetry={refetchOverview} />
    );

  return (
    <PageShell wide>
      <PageHeader
        title="Buyer Acquisition"
        subtitle="Unified workspace — Discovery, Network, Marketplace, and Intelligence aggregated read-only."
        icon={Layers}
        actions={
          <div className="flex flex-wrap gap-2 text-xs">
          <Link href="/buyer-discovery" className="btn-secondary py-1.5 px-2.5">
            Discovery
          </Link>
          <Link href="/buyer-network" className="btn-secondary py-1.5 px-2.5">
            Network
          </Link>
          <Link href="/marketplace" className="btn-secondary py-1.5 px-2.5">
            Marketplace
          </Link>
          <Link href="/buyer-intelligence" className="btn-secondary py-1.5 px-2.5">
            Intelligence
          </Link>
        </div>
        }
      />

      {section === "overview" && (
        <ExecutiveKpiBar
          items={[
            { label: "Total buyers", value: overview.total_buyers },
            { label: "Strategic", value: overview.strategic_buyers },
            { label: "High potential", value: overview.high_potential_buyers },
            { label: "Marketplace", value: overview.marketplace_opportunities },
            { label: "Network", value: overview.network_opportunities },
            { label: "Discovery", value: overview.discovery_buyers },
          ]}
        />
      )}

      <div className="rounded-xl border border-success-200 bg-success-50/50 px-4 py-2.5 flex items-start gap-2 text-xs text-success-800">
        <Shield className="w-4 h-4 shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {(overview.errors?.length ?? 0) > 0 && <PartialErrorsBanner errors={overview.errors} />}

      <nav className="flex flex-wrap gap-2 border-b border-gray-200 pb-2">
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
              section === id
                ? "bg-brand-50 text-brand-800 border border-brand-200"
                : "text-gray-600 hover:bg-gray-50",
            )}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </nav>

      {section === "overview" && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400">Total buyers</p>
              <p className="text-2xl font-semibold tabular-nums">{overview.total_buyers}</p>
            </div>
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400">Strategic</p>
              <p className="text-2xl font-semibold tabular-nums">{overview.strategic_buyers}</p>
            </div>
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400">High potential</p>
              <p className="text-2xl font-semibold tabular-nums">{overview.high_potential_buyers}</p>
            </div>
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400">Marketplace opps</p>
              <p className="text-2xl font-semibold tabular-nums">{overview.marketplace_opportunities}</p>
            </div>
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400">Network opps</p>
              <p className="text-2xl font-semibold tabular-nums">{overview.network_opportunities}</p>
            </div>
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400 flex items-center gap-1">
                <Search className="w-3 h-3" /> Discovery
              </p>
              <p className="text-xl font-semibold tabular-nums mt-1">{overview.discovery_buyers}</p>
            </div>
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400 flex items-center gap-1">
                <Network className="w-3 h-3" /> Network profiles
              </p>
              <p className="text-xl font-semibold tabular-nums mt-1">{overview.network_profiles}</p>
            </div>
            <div className="card p-4">
              <p className="text-[10px] uppercase text-gray-400 flex items-center gap-1">
                <Target className="w-3 h-3" /> Intelligence
              </p>
              <p className="text-xl font-semibold tabular-nums mt-1">{overview.intelligence_buyers}</p>
            </div>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 text-center text-sm">
            <div className="card p-4">
              <p className="text-xs text-gray-500">Avg opportunity score</p>
              <p className="text-lg font-semibold">{overview.average_opportunity_score}/100</p>
            </div>
            <div className="card p-4">
              <p className="text-xs text-gray-500">Avg buyer score</p>
              <p className="text-lg font-semibold">{overview.average_buyer_score}/100</p>
            </div>
            <div className="card p-4">
              <p className="text-xs text-gray-500">Avg network strength</p>
              <p className="text-lg font-semibold">{overview.average_network_strength}/100</p>
            </div>
          </div>
          {factoryReadiness && factoryReadiness.profile_score > 0 && (
            <div className="card p-4 space-y-3 border-amber-100">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                  <Factory size={16} className="text-amber-700" />
                  Factory Readiness
                </p>
                <Link href="/factory-platform" className="text-xs text-brand-700 hover:underline">
                  Factory Platform →
                </Link>
              </div>
              <p className="text-sm text-gray-700">
                Profile score {factoryReadiness.profile_score}/100 · verification:{" "}
                {factoryReadiness.verification_status.replace(/_/g, " ")}
              </p>
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
                {factoryReadiness.indicators.map((ind) => (
                  <div
                    key={ind.label}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-xs",
                      ind.status === "ready"
                        ? "border-emerald-200 bg-emerald-50/50"
                        : "border-amber-200 bg-amber-50/50",
                    )}
                  >
                    <p className="font-medium">{ind.label}</p>
                    <p className="tabular-nums text-gray-600">
                      {ind.score}/{ind.max}
                    </p>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-gray-400">{factoryReadiness.safety_notice}</p>
            </div>
          )}
        </div>
      )}

      {section === "buyers" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2 items-center">
            <label className="text-xs text-gray-500">Pipeline stage</label>
            <select
              className="input text-sm py-1"
              value={filterStage}
              onChange={(e) => setFilterStage(e.target.value as BuyerAcquisitionPipelineStage | "")}
            >
              <option value="">All stages</option>
              {(Object.keys(PIPELINE_LABELS) as BuyerAcquisitionPipelineStage[]).map((s) => (
                <option key={s} value={s}>
                  {PIPELINE_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
          {buyersLoading && <LoadingState message="Loading unified buyers…" />}
          {!buyersLoading && (buyersData?.items.length ?? 0) === 0 && (
            <EmptyState title="No unified buyers" description="Buyers appear when discovery, network, or CRM data exists." />
          )}
          {(buyersData?.items.length ?? 0) > 0 && (
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left text-xs text-gray-500">
                  <tr>
                    <th className="px-4 py-2">Company</th>
                    <th className="px-4 py-2">Scores</th>
                    <th className="px-4 py-2">Pipeline</th>
                    <th className="px-4 py-2">Relationship</th>
                    <th className="px-4 py-2">Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {buyersData!.items.map((b: UnifiedBuyerProfile) => (
                    <tr key={b.unified_key} className="border-t border-gray-100">
                      <td className="px-4 py-2">
                        <p className="font-medium text-gray-900">{b.company_name}</p>
                        <p className="text-xs text-gray-500">
                          {[b.country, b.industry].filter(Boolean).join(" · ")}
                        </p>
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex flex-wrap gap-1">
                          <ScoreBadge score={b.opportunity_score} />
                          {b.buyer_score > 0 && (
                            <span className="text-[10px] text-gray-500">BI {b.buyer_score}</span>
                          )}
                          {b.network_strength > 0 && (
                            <span className="text-[10px] text-gray-500">Net {b.network_strength}</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-xs capitalize">
                        {PIPELINE_LABELS[b.pipeline_stage]}
                      </td>
                      <td className="px-4 py-2 text-xs capitalize">
                        {b.relationship_status.replace(/_/g, " ")}
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex flex-wrap gap-1">
                          {b.sources.map((s) => (
                            <span
                              key={s}
                              className={cn(
                                "text-[10px] px-1.5 py-0.5 rounded border capitalize",
                                SOURCE_STYLES[s] ?? "bg-gray-50 text-gray-700",
                              )}
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {section === "opportunities" && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2 items-center">
            <label className="text-xs text-gray-500">Source</label>
            <select
              className="input text-sm py-1"
              value={filterSource}
              onChange={(e) =>
                setFilterSource(e.target.value as "" | "marketplace" | "discovery" | "network")
              }
            >
              <option value="">All sources</option>
              <option value="marketplace">Marketplace</option>
              <option value="discovery">Discovery</option>
              <option value="network">Network</option>
            </select>
          </div>
          {oppsLoading && <LoadingState message="Loading opportunities…" />}
          {!oppsLoading && (opportunitiesData?.items.length ?? 0) === 0 && (
            <EmptyState title="No opportunities" description="Opportunities aggregate from all acquisition modules." />
          )}
          {(opportunitiesData?.items.length ?? 0) > 0 && (
            <>
              <div className="flex gap-4 text-xs text-gray-500">
                <span>Marketplace: {opportunitiesData!.marketplace_count}</span>
                <span>Discovery: {opportunitiesData!.discovery_count}</span>
                <span>Network: {opportunitiesData!.network_count}</span>
              </div>
              <div className="space-y-2">
                {opportunitiesData!.items.map((o: UnifiedOpportunityItem) => (
                  <div key={`${o.source}-${o.opportunity_id}`} className="card p-4 flex flex-wrap gap-3 justify-between">
                    <div>
                      <p className="font-medium text-gray-900">{o.title}</p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {[o.buyer_company, o.country, o.industry].filter(Boolean).join(" · ")}
                      </p>
                      {o.description && <p className="text-xs text-gray-400 mt-1">{o.description}</p>}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-[10px] px-2 py-0.5 rounded-full border capitalize",
                          SOURCE_STYLES[o.source],
                        )}
                      >
                        {o.source}
                      </span>
                      <ScoreBadge score={o.score} />
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {section === "pipeline" && (
        <div className="space-y-4">
          {!pipelineData && <LoadingState message="Loading pipeline…" />}
          {pipelineData && (
            <>
              <p className="text-sm text-gray-600">{pipelineData.total} buyers in unified pipeline</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                {pipelineData.stages.map((s) => (
                  <div key={s.stage} className="card p-4 text-center">
                    <p className="text-[10px] uppercase text-gray-400">{s.label}</p>
                    <p className="text-2xl font-semibold tabular-nums mt-1">{s.count}</p>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {section === "network" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm text-gray-600">Buyers with network profile data in the unified workspace.</p>
            <Link href="/buyer-network" className="text-xs text-brand-700 hover:underline">
              Open Buyer Network →
            </Link>
          </div>
          {buyersLoading && <LoadingState message="Loading network buyers…" />}
          {!buyersLoading && networkBuyers.length === 0 && (
            <EmptyState title="No network buyers" description="Network profiles sync from Buyer Network module." />
          )}
          {networkBuyers.length > 0 && (
            <div className="grid sm:grid-cols-2 gap-3">
              {networkBuyers.map((b) => (
                <div key={b.unified_key} className="card p-4">
                  <p className="font-medium text-gray-900">{b.company_name}</p>
                  <p className="text-xs text-gray-500">{[b.country, b.industry].filter(Boolean).join(" · ")}</p>
                  <div className="flex gap-2 mt-2">
                    <span className="text-xs">Strength: {b.network_strength}</span>
                    <span className="text-xs">Opp: {b.opportunity_score}</span>
                    <span className="text-xs capitalize">{b.relationship_status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {section === "insights" && (
        <div className="space-y-6">
          {insightsLoading && <LoadingState message="Loading insights…" />}
          {insightsData && (
            <>
              <section className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-900">Top buyers</h3>
                <ol className="space-y-2">
                  {insightsData.top_buyers.map((b) => (
                    <li key={`top-${b.rank}-${b.company_name}`} className="card p-3 flex gap-3 text-sm">
                      <span className="font-bold text-brand-700 w-5">{b.rank}</span>
                      <div>
                        <p className="font-medium">{b.company_name}</p>
                        <p className="text-xs text-gray-500">
                          Score {b.score} · Opp {b.opportunity_score} · Net {b.network_strength}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
              <section className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-900">Strongest relationships</h3>
                <ol className="space-y-2">
                  {insightsData.strongest_relationships.slice(0, 5).map((b) => (
                    <li key={`rel-${b.rank}-${b.company_name}`} className="text-sm flex gap-2">
                      <span className="font-bold text-violet-700">{b.rank}</span>
                      <span>{b.company_name}</span>
                      <span className="text-gray-500">strength {b.network_strength}</span>
                    </li>
                  ))}
                </ol>
              </section>
              <div className="grid sm:grid-cols-2 gap-6">
                <section>
                  <h3 className="text-sm font-semibold text-gray-900 mb-2">Best countries</h3>
                  <ul className="space-y-1 text-sm">
                    {insightsData.best_countries.map((c) => (
                      <li key={c.label} className="flex justify-between">
                        <span>{c.label}</span>
                        <span className="text-gray-500">
                          {c.count} ({c.share_pct}%)
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
                <section>
                  <h3 className="text-sm font-semibold text-gray-900 mb-2">Best industries</h3>
                  <ul className="space-y-1 text-sm">
                    {insightsData.best_industries.map((c) => (
                      <li key={c.label} className="flex justify-between">
                        <span className="capitalize">{c.label}</span>
                        <span className="text-gray-500">
                          {c.count} ({c.share_pct}%)
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </>
          )}
        </div>
      )}
    </PageShell>
  );
}
