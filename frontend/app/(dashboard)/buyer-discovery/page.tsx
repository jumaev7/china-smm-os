"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Globe,
  Loader2,
  MapPin,
  RefreshCw,
  Search,
  Shield,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  buyerDiscoveryApi,
  BuyerDiscoveryCategory,
  BuyerDiscoveryPipelineStage,
  BuyerRegistryItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const CATEGORY_STYLES: Record<BuyerDiscoveryCategory, string> = {
  high_potential: "bg-violet-100 text-violet-900 border-violet-200",
  strategic: "bg-indigo-100 text-indigo-900 border-indigo-200",
  active: "bg-emerald-100 text-emerald-900 border-emerald-200",
  new: "bg-sky-100 text-sky-900 border-sky-200",
  watchlist: "bg-amber-100 text-amber-900 border-amber-200",
};

const CATEGORY_LABELS: Record<BuyerDiscoveryCategory, string> = {
  high_potential: "High Potential",
  strategic: "Strategic",
  active: "Active",
  new: "New",
  watchlist: "Watchlist",
};

const PIPELINE_LABELS: Record<BuyerDiscoveryPipelineStage, string> = {
  discovered: "Discovered",
  researched: "Researched",
  qualified: "Qualified",
  contacted: "Contacted",
  opportunity: "Opportunity",
  customer: "Customer",
};

function formatDt(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "yyyy-MM-dd");
  } catch {
    return iso;
  }
}

function CategoryBadge({ category }: { category: BuyerDiscoveryCategory }) {
  return (
    <span
      className={cn(
        "text-[10px] px-2 py-0.5 rounded-full border font-medium",
        CATEGORY_STYLES[category],
      )}
    >
      {CATEGORY_LABELS[category]}
    </span>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const style =
    score >= 75
      ? "bg-violet-50 text-violet-900 border-violet-200"
      : score >= 50
        ? "bg-emerald-50 text-emerald-800 border-emerald-200"
        : "bg-gray-50 text-gray-700 border-gray-200";
  return (
    <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-semibold tabular-nums", style)}>
      {score}/100
    </span>
  );
}

export default function BuyerDiscoveryPage() {
  const qc = useQueryClient();
  const [filterCategory, setFilterCategory] = useState<BuyerDiscoveryCategory | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewError,
    refetch: refetchOverview,
  } = useQuery({
    queryKey: ["buyer-discovery-overview"],
    queryFn: () => buyerDiscoveryApi.overview().then((r) => r.data),
  });

  const { data: buyersData, isLoading: buyersLoading } = useQuery({
    queryKey: ["buyer-discovery-buyers", filterCategory],
    queryFn: () =>
      buyerDiscoveryApi
        .buyers({
          category: filterCategory || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!overview,
  });

  const { data: topOpps } = useQuery({
    queryKey: ["buyer-discovery-top"],
    queryFn: () => buyerDiscoveryApi.topOpportunities({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: pipeline } = useQuery({
    queryKey: ["buyer-discovery-pipeline"],
    queryFn: () => buyerDiscoveryApi.pipeline().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: market } = useQuery({
    queryKey: ["buyer-discovery-market"],
    queryFn: () => buyerDiscoveryApi.marketInsights().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: executive } = useQuery({
    queryKey: ["buyer-discovery-executive"],
    queryFn: () => buyerDiscoveryApi.executiveInsights({ limit: 5 }).then((r) => r.data),
    enabled: !!overview,
  });

  const recalcMut = useMutation({
    mutationFn: () => buyerDiscoveryApi.recalculate(),
    onSuccess: (res) => {
      toast.success(res.data.message);
      qc.invalidateQueries({ queryKey: ["buyer-discovery-overview"] });
      qc.invalidateQueries({ queryKey: ["buyer-discovery-buyers"] });
      qc.invalidateQueries({ queryKey: ["buyer-discovery-top"] });
      qc.invalidateQueries({ queryKey: ["buyer-discovery-pipeline"] });
      qc.invalidateQueries({ queryKey: ["buyer-discovery-market"] });
      qc.invalidateQueries({ queryKey: ["buyer-discovery-executive"] });
    },
    onError: (e: Error) => toast.error(e.message || "Recalculate failed"),
  });

  const buyers = buyersData?.items ?? [];
  const selected =
    buyers.find((b) => b.id === selectedId) ?? buyers[0] ?? null;

  const integrationDegraded = useMemo(
    () => (overview?.integration_checks ?? []).filter((c) => c.status !== "ok"),
    [overview],
  );

  if (overviewLoading) return <LoadingState label="Loading buyer discovery…" />;
  if (overviewError || !overview)
    return <ErrorState message="Failed to load buyer discovery overview" onRetry={refetchOverview} />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Search className="w-5 h-5 text-brand-600" />
            Export Buyer Discovery
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Identify and rank potential export buyers for factory partners — intelligence only.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary flex items-center gap-2 text-sm"
          disabled={recalcMut.isPending}
          onClick={() => recalcMut.mutate()}
        >
          {recalcMut.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          Recalculate scores
        </button>
      </div>

      <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 px-4 py-2 flex items-start gap-2 text-xs text-emerald-900">
        <Shield className="w-4 h-4 shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {(overview.errors?.length ?? 0) > 0 && <PartialErrorsBanner errors={overview.errors} />}

      {/* 1. Buyer Overview */}
      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Buyer Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Total buyers</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.total_buyers}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Avg score</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.average_opportunity_score}</p>
          </div>
          {(Object.keys(CATEGORY_LABELS) as BuyerDiscoveryCategory[]).map((cat) => (
            <div key={cat} className="card p-4">
              <p className="text-[10px] uppercase text-gray-400">{CATEGORY_LABELS[cat]}</p>
              <p className="text-2xl font-semibold tabular-nums">
                {cat === "high_potential"
                  ? overview.high_potential
                  : cat === "strategic"
                    ? overview.strategic
                    : cat === "active"
                      ? overview.active
                      : cat === "new"
                        ? overview.new_buyers
                        : overview.watchlist}
              </p>
              <CategoryBadge category={cat} />
            </div>
          ))}
        </div>
      </section>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* 2. Buyer Registry */}
        <section className="lg:col-span-2 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-900">Buyer Registry</h2>
            <select
              className="text-xs border border-gray-200 rounded-lg px-2 py-1"
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value as BuyerDiscoveryCategory | "")}
            >
              <option value="">All categories</option>
              {(Object.keys(CATEGORY_LABELS) as BuyerDiscoveryCategory[]).map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_LABELS[c]}
                </option>
              ))}
            </select>
          </div>
          {buyersLoading ? (
            <LoadingState label="Loading registry…" />
          ) : buyers.length === 0 ? (
            <EmptyState
              title="No buyers in registry"
              description="Run recalculate to sync from CRM leads or seed demo buyers."
            />
          ) : (
            <div className="card overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="text-left p-2">Company</th>
                    <th className="text-left p-2">Market</th>
                    <th className="text-left p-2">Score</th>
                    <th className="text-left p-2">Stage</th>
                  </tr>
                </thead>
                <tbody>
                  {buyers.map((b: BuyerRegistryItem) => (
                    <tr
                      key={b.id}
                      className={cn(
                        "border-t border-gray-100 cursor-pointer hover:bg-gray-50/80",
                        selected?.id === b.id && "bg-brand-50/40",
                      )}
                      onClick={() => setSelectedId(b.id)}
                    >
                      <td className="p-2">
                        <p className="font-medium text-gray-900">{b.company_name}</p>
                        <CategoryBadge category={b.category} />
                      </td>
                      <td className="p-2 text-gray-600">
                        {[b.country, b.industry].filter(Boolean).join(" · ") || "—"}
                      </td>
                      <td className="p-2">
                        <ScoreBadge score={b.opportunity_score} />
                      </td>
                      <td className="p-2 text-gray-600 capitalize">
                        {PIPELINE_LABELS[b.pipeline_stage]}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selected && (
            <div className="card p-4 text-xs space-y-2">
              <p className="font-semibold text-gray-900">{selected.company_name}</p>
              <p className="text-gray-500">
                Source: {selected.source} · Contact: {selected.contact_status} · Discovered{" "}
                {formatDt(selected.discovered_at)}
              </p>
              {selected.website && (
                <a href={selected.website} className="text-brand-700 hover:underline" target="_blank" rel="noreferrer">
                  {selected.website}
                </a>
              )}
              {selected.crm_lead_id && (
                <Link href="/crm" className="text-brand-700 hover:underline inline-block">
                  View linked CRM lead
                </Link>
              )}
            </div>
          )}
        </section>

        {/* 3. Opportunity Ranking */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1">
            <TrendingUp className="w-4 h-4" />
            Opportunity Ranking
          </h2>
          <div className="card p-4 space-y-3">
            <p className="text-[10px] uppercase text-gray-400">Top buyers</p>
            {(topOpps?.top_buyers ?? []).length === 0 ? (
              <p className="text-xs text-gray-500">No rankings yet.</p>
            ) : (
              <ul className="space-y-2">
                {(topOpps?.top_buyers ?? []).map((item) => (
                  <li key={item.buyer_id} className="flex justify-between gap-2 text-xs">
                    <span className="text-gray-800 truncate">
                      {item.rank}. {item.company_name}
                    </span>
                    <ScoreBadge score={item.opportunity_score} />
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[10px] uppercase text-gray-400 pt-2">Strategic buyers</p>
            <ul className="space-y-1">
              {(topOpps?.strategic_buyers ?? []).slice(0, 5).map((item) => (
                <li key={item.buyer_id} className="text-xs text-gray-600 truncate">
                  {item.company_name}
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* 4. Buyer Pipeline */}
        <section>
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
            <Users className="w-4 h-4" />
            Buyer Pipeline
          </h2>
          <div className="card p-4 space-y-2">
            {(pipeline?.stages ?? []).map((s) => (
              <div key={s.stage} className="flex items-center gap-3">
                <span className="text-xs text-gray-600 w-28 shrink-0">{s.label}</span>
                <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-brand-500 rounded-full"
                    style={{
                      width: `${pipeline?.total ? Math.max(4, (100 * s.count) / pipeline.total) : 0}%`,
                    }}
                  />
                </div>
                <span className="text-xs font-semibold tabular-nums w-6 text-right">{s.count}</span>
              </div>
            ))}
          </div>
        </section>

        {/* 5. Market Insights */}
        <section>
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
            <Globe className="w-4 h-4" />
            Market Insights
          </h2>
          <div className="card p-4 grid sm:grid-cols-3 gap-4 text-xs">
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-2 flex items-center gap-1">
                <MapPin className="w-3 h-3" />
                Top countries
              </p>
              <ul className="space-y-1">
                {(market?.top_countries ?? []).slice(0, 6).map((c) => (
                  <li key={c.label} className="flex justify-between text-gray-700">
                    <span>{c.label}</span>
                    <span className="tabular-nums text-gray-500">{c.count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-2">Top industries</p>
              <ul className="space-y-1">
                {(market?.top_industries ?? []).slice(0, 6).map((c) => (
                  <li key={c.label} className="flex justify-between text-gray-700">
                    <span className="capitalize">{c.label}</span>
                    <span className="tabular-nums text-gray-500">{c.count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-2">Buyer segments</p>
              <ul className="space-y-1">
                {(market?.top_buyer_segments ?? []).map((c) => (
                  <li key={c.label} className="flex justify-between text-gray-700 capitalize">
                    <span>{CATEGORY_LABELS[c.label as BuyerDiscoveryCategory] ?? c.label}</span>
                    <span className="tabular-nums text-gray-500">{c.share_pct}%</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      </div>

      {/* 6. Executive Recommendations */}
      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
          <Target className="w-4 h-4" />
          Executive Recommendations
        </h2>
        <div className="card p-4 grid md:grid-cols-3 gap-4 text-xs">
          <div>
            <p className="text-[10px] uppercase text-gray-400 mb-2">Best markets</p>
            <ul className="space-y-1">
              {(executive?.best_markets ?? []).slice(0, 5).map((c) => (
                <li key={c.label} className="flex justify-between text-gray-700">
                  <span>{c.label}</span>
                  <span className="tabular-nums text-gray-500">{c.share_pct}%</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400 mb-2">Highest potential buyers</p>
            <ul className="space-y-1">
              {(executive?.highest_potential_buyers ?? []).slice(0, 5).map((b) => (
                <li key={b.buyer_id} className="flex justify-between gap-2 text-gray-700">
                  <span className="truncate">{b.company_name}</span>
                  <ScoreBadge score={b.opportunity_score} />
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400 mb-2">Acquisition opportunities</p>
            <ul className="space-y-1">
              {(executive?.acquisition_opportunities ?? []).slice(0, 5).map((b) => (
                <li key={b.buyer_id} className="text-gray-700 truncate">
                  {b.company_name} · {b.country ?? "—"}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {integrationDegraded.length > 0 && (
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-1">
            <Target className="w-4 h-4" />
            Integration status
          </h2>
          <ul className="space-y-1 text-xs">
            {(overview.integration_checks ?? []).map((c) => (
              <li key={c.module} className="flex items-center gap-2">
                <span
                  className={cn(
                    "w-2 h-2 rounded-full",
                    c.status === "ok" ? "bg-emerald-500" : "bg-amber-500",
                  )}
                />
                <span className="font-medium capitalize">{c.module.replace(/_/g, " ")}</span>
                <span className="text-gray-500 truncate">{c.message}</span>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-3 mt-3 text-xs">
            <Link href="/buyer-intelligence" className="text-brand-700 hover:underline">
              Buyer Intelligence
            </Link>
            <Link href="/deal-risk" className="text-brand-700 hover:underline">
              Deal Risk
            </Link>
            <Link href="/revenue-forecast" className="text-brand-700 hover:underline">
              Revenue Forecast
            </Link>
            <Link href="/factory-platform" className="text-brand-700 hover:underline">
              Factory Platform
            </Link>
            <Link href="/executive-copilot" className="text-brand-700 hover:underline">
              Executive Copilot
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
