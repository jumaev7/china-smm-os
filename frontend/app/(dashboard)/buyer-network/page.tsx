"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Globe,
  Loader2,
  Network,
  RefreshCw,
  Shield,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  buyerNetworkApi,
  buyersApi,
  BuyerNetworkClassification,
  BuyerNetworkProfileItem,
  BuyerNetworkStatus,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { HorizontalBarChart } from "@/components/analytics/SimpleBarChart";

const CLASSIFICATION_LABELS: Record<BuyerNetworkClassification, string> = {
  strategic: "Strategic",
  high_potential: "High Potential",
  active: "Active",
  growing: "Growing",
  watchlist: "Watchlist",
  underutilized: "Underutilized",
};

const STATUS_STYLES: Record<BuyerNetworkStatus, string> = {
  strategic: "bg-indigo-100 text-indigo-900 border-indigo-200",
  active: "bg-emerald-100 text-emerald-900 border-emerald-200",
  growing: "bg-sky-100 text-sky-900 border-sky-200",
  watchlist: "bg-amber-100 text-amber-900 border-amber-200",
  underutilized: "bg-gray-100 text-gray-700 border-gray-200",
};

function StrengthBadge({ score }: { score: number }) {
  const style =
    score >= 75
      ? "bg-violet-50 text-violet-900 border-violet-200"
      : score >= 50
        ? "bg-emerald-50 text-emerald-800 border-emerald-200"
        : "bg-gray-50 text-gray-700 border-gray-200";
  return (
    <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-semibold tabular-nums", style)}>
      {score}
    </span>
  );
}

export default function BuyerNetworkPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const {
    data: crmDashboard,
    isLoading: crmLoading,
    isError: crmError,
    refetch: refetchCrm,
  } = useQuery({
    queryKey: ["buyers", "dashboard"],
    queryFn: () => buyersApi.dashboard().then((r) => r.data),
  });

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewError,
    refetch: refetchOverview,
  } = useQuery({
    queryKey: ["buyer-network-overview"],
    queryFn: () => buyerNetworkApi.overview().then((r) => r.data),
  });

  const { data: profilesData, isLoading: profilesLoading } = useQuery({
    queryKey: ["buyer-network-profiles"],
    queryFn: () => buyerNetworkApi.profiles({ limit: 100 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: relationships } = useQuery({
    queryKey: ["buyer-network-relationships"],
    queryFn: () => buyerNetworkApi.relationships({ limit: 100 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: graph } = useQuery({
    queryKey: ["buyer-network-graph", selectedId],
    queryFn: () =>
      buyerNetworkApi.graph({ buyer_id: selectedId ?? undefined, limit: 10 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: insights } = useQuery({
    queryKey: ["buyer-network-insights"],
    queryFn: () => buyerNetworkApi.insights({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: topBuyers } = useQuery({
    queryKey: ["buyer-network-top"],
    queryFn: () => buyerNetworkApi.topBuyers({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
  });

  const recalcMut = useMutation({
    mutationFn: () => buyerNetworkApi.recalculate(),
    onSuccess: (res) => {
      toast.success(res.data.message);
      qc.invalidateQueries({ queryKey: ["buyer-network-overview"] });
      qc.invalidateQueries({ queryKey: ["buyer-network-profiles"] });
      qc.invalidateQueries({ queryKey: ["buyer-network-relationships"] });
      qc.invalidateQueries({ queryKey: ["buyer-network-graph"] });
      qc.invalidateQueries({ queryKey: ["buyer-network-insights"] });
      qc.invalidateQueries({ queryKey: ["buyer-network-top"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const profiles = profilesData?.items ?? [];
  const selected =
    profiles.find((p) => p.id === selectedId) ?? profiles[0] ?? null;

  const integrationDegraded = useMemo(
    () => (overview?.integration_checks ?? []).filter((c) => c.status !== "ok"),
    [overview],
  );

  if (overviewLoading || crmLoading) return <LoadingState label={t("buyerCrm.loading")} />;
  if (overviewError || !overview)
    return <ErrorState message={t("buyerCrm.error")} onRetry={refetchOverview} />;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Network className="w-5 h-5 text-brand-600" />
            {t("buyerCrm.networkTitle")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("buyerCrm.networkSubtitle")}</p>
        </div>
        <div className="flex gap-2">
          <Link href="/buyers" className="btn-primary text-sm">{t("nav.buyers")}</Link>
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
            Recalculate network
          </button>
        </div>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3">{t("buyerCrm.crmDashboard")}</h2>
        {crmError ? (
          <ErrorState message={t("buyerCrm.error")} onRetry={() => refetchCrm()} />
        ) : crmDashboard ? (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
              <KpiCard
                label={t("buyerCrm.totalBuyers")}
                value={crmDashboard.total_buyers}
                href="/buyers"
                icon={Users}
                iconClassName="bg-sky-50 text-sky-600"
              />
              <KpiCard
                label={t("buyerCrm.activeBuyers")}
                value={crmDashboard.active_buyers}
                href="/buyers?status=active_buyer"
                icon={TrendingUp}
                iconClassName="bg-emerald-50 text-emerald-600"
              />
              <KpiCard
                label={t("buyerCrm.newThisMonth")}
                value={crmDashboard.new_buyers_this_month}
                href="/buyers"
                icon={Globe}
                iconClassName="bg-violet-50 text-violet-600"
              />
              <KpiCard
                label={t("buyerCrm.topIndustry")}
                value={crmDashboard.top_industries[0]?.label ?? "—"}
                href="/buyers"
                icon={Target}
                iconClassName="bg-amber-50 text-amber-600"
              />
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div className="card p-4">
                <h3 className="text-xs font-semibold text-gray-700 mb-3">{t("buyerCrm.geographicDistribution")}</h3>
                <HorizontalBarChart
                  data={(crmDashboard.geographic_distribution ?? []).map((d) => ({
                    label: d.label,
                    value: d.count,
                  }))}
                  barClassName="bg-brand-500"
                />
              </div>
              <div className="card p-4">
                <h3 className="text-xs font-semibold text-gray-700 mb-3">{t("buyerCrm.industryDistribution")}</h3>
                <HorizontalBarChart
                  data={(crmDashboard.industry_distribution ?? []).map((d) => ({
                    label: d.label,
                    value: d.count,
                  }))}
                  barClassName="bg-emerald-500"
                />
              </div>
            </div>
          </>
        ) : null}
      </section>

      <div className="flex flex-wrap items-start justify-between gap-4 pt-2 border-t border-gray-100">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">{t("buyerCrm.intelligenceLayer")}</h2>
          <p className="text-xs text-gray-500 mt-1">
            Global buyer intelligence and tenant relationship mapping — no automatic outreach.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 px-4 py-2 flex items-start gap-2 text-xs text-emerald-900">
        <Shield className="w-4 h-4 shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {(overview.errors?.length ?? 0) > 0 && <PartialErrorsBanner errors={overview.errors} />}

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Network Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Profiles</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.total_profiles}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Relationships</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.total_relationships}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Strategic</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.strategic_buyers}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Active</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.active_buyers}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Underutilized</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.underutilized}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Avg opportunity</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.average_opportunity_score}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Avg strength</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.average_network_strength}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Tenants</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.tenants_connected}</p>
          </div>
        </div>
      </section>

      <div className="grid lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Buyer Profiles</h2>
          {profilesLoading ? (
            <LoadingState label="Loading profiles…" />
          ) : profiles.length === 0 ? (
            <EmptyState
              title="No buyer profiles"
              description="Run recalculate to sync from discovery and marketplace data."
            />
          ) : (
            <div className="card overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="text-left p-2">Company</th>
                    <th className="text-left p-2">Market</th>
                    <th className="text-left p-2">Strength</th>
                    <th className="text-left p-2">Links</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((p: BuyerNetworkProfileItem) => (
                    <tr
                      key={p.id}
                      className={cn(
                        "border-t border-gray-100 cursor-pointer hover:bg-gray-50/80",
                        selected?.id === p.id && "bg-brand-50/40",
                      )}
                      onClick={() => setSelectedId(p.id)}
                    >
                      <td className="p-2">
                        <p className="font-medium text-gray-900">{p.company_name}</p>
                        <span
                          className={cn(
                            "text-[10px] px-1.5 py-0.5 rounded border capitalize",
                            STATUS_STYLES[p.buyer_status],
                          )}
                        >
                          {p.buyer_status}
                        </span>
                      </td>
                      <td className="p-2 text-gray-600">
                        {[p.country, p.industry].filter(Boolean).join(" · ") || "—"}
                      </td>
                      <td className="p-2">
                        <StrengthBadge score={p.network_strength} />
                      </td>
                      <td className="p-2 tabular-nums text-gray-600">{p.relationship_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1">
            <TrendingUp className="w-4 h-4" />
            Top Buyers
          </h2>
          <div className="card p-4 space-y-2 text-xs">
            {(topBuyers?.top_buyers ?? []).map((item) => (
              <div key={item.buyer_id} className="flex justify-between gap-2">
                <span className="truncate">
                  {item.rank}. {item.company_name}
                </span>
                <StrengthBadge score={item.network_strength} />
              </div>
            ))}
          </div>
        </section>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
          <Users className="w-4 h-4" />
          Relationship Map
        </h2>
        <div className="card overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 text-gray-500">
              <tr>
                <th className="text-left p-2">Buyer</th>
                <th className="text-left p-2">Tenant</th>
                <th className="text-left p-2">Type</th>
                <th className="text-left p-2">Strength</th>
              </tr>
            </thead>
            <tbody>
              {(relationships?.items ?? []).map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="p-2 font-medium text-gray-900">{r.company_name}</td>
                  <td className="p-2 text-gray-600">{r.tenant_name ?? r.tenant_id.slice(0, 8)}</td>
                  <td className="p-2 capitalize text-gray-600">{r.relationship_type}</td>
                  <td className="p-2">
                    <StrengthBadge score={r.relationship_strength} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(relationships?.items ?? []).length === 0 && (
            <p className="p-4 text-xs text-gray-500">No tenant relationships mapped yet.</p>
          )}
        </div>
      </section>

      <div className="grid md:grid-cols-2 gap-6">
        <section>
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
            <Network className="w-4 h-4" />
            Buyer Graph
            {selected && (
              <span className="text-gray-500 font-normal"> — {selected.company_name}</span>
            )}
          </h2>
          <div className="card p-4 space-y-3 text-xs">
            <p className="text-[10px] uppercase text-gray-400">Related buyers</p>
            <ul className="space-y-2">
              {(graph?.related_buyers ?? []).map((n) => (
                <li key={n.buyer_id} className="flex justify-between gap-2">
                  <span className="text-gray-800">
                    {n.company_name}
                    <span className="text-gray-400 block">{n.link_reason}</span>
                  </span>
                  <StrengthBadge score={n.network_strength} />
                </li>
              ))}
            </ul>
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div>
                <p className="text-[10px] uppercase text-gray-400 mb-1 flex items-center gap-1">
                  <Globe className="w-3 h-3" />
                  Countries
                </p>
                {(graph?.related_countries ?? []).slice(0, 5).map((c) => (
                  <p key={c.label} className="flex justify-between text-gray-700">
                    <span>{c.label}</span>
                    <span>{c.count}</span>
                  </p>
                ))}
              </div>
              <div>
                <p className="text-[10px] uppercase text-gray-400 mb-1">Industries</p>
                {(graph?.related_industries ?? []).slice(0, 5).map((c) => (
                  <p key={c.label} className="flex justify-between text-gray-700 capitalize">
                    <span>{c.label}</span>
                    <span>{c.count}</span>
                  </p>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
            <Target className="w-4 h-4" />
            Network Insights
          </h2>
          <div className="card p-4 grid sm:grid-cols-2 gap-4 text-xs">
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-2">Strongest</p>
              {(insights?.strongest_buyers ?? []).slice(0, 5).map((b) => (
                <p key={b.buyer_id} className="flex justify-between text-gray-700 mb-1">
                  <span className="truncate">{b.company_name}</span>
                  <StrengthBadge score={b.network_strength} />
                </p>
              ))}
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-2">Underutilized</p>
              {(insights?.underutilized_buyers ?? []).slice(0, 5).map((b) => (
                <p key={b.buyer_id} className="text-gray-700 truncate mb-1">
                  {b.company_name}
                </p>
              ))}
            </div>
          </div>
        </section>
      </div>

      {integrationDegraded.length > 0 && (
        <section className="card p-4">
          <h2 className="text-sm font-semibold text-gray-900 mb-2">Integration status</h2>
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
            <Link href="/buyer-discovery" className="text-brand-700 hover:underline">
              Buyer Discovery
            </Link>
            <Link href="/marketplace" className="text-brand-700 hover:underline">
              Marketplace
            </Link>
            <Link href="/buyer-intelligence" className="text-brand-700 hover:underline">
              Buyer Intelligence
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
