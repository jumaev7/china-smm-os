"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowRightLeft,
  Globe,
  Handshake,
  Loader2,
  Shield,
  Store,
  TrendingUp,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  marketplaceApi,
  MarketplaceOpportunityItem,
  MarketplaceOpportunityStatus,
  MarketplaceOpportunityType,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
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
} from "@/components/ui/design-system";

const TYPE_LABELS: Record<MarketplaceOpportunityType, string> = {
  distributor: "Distributor",
  importer: "Importer",
  wholesaler: "Wholesaler",
  retailer: "Retailer",
  project: "Project",
  partnership: "Partnership",
  rfq: "RFQ",
};

const STATUS_STYLES: Record<MarketplaceOpportunityStatus, string> = {
  open: "bg-emerald-100 text-emerald-900 border-emerald-200",
  in_review: "bg-amber-100 text-amber-900 border-amber-200",
  claimed: "bg-indigo-100 text-indigo-900 border-indigo-200",
  closed: "bg-gray-100 text-gray-700 border-gray-200",
};

function fmtDt(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "yyyy-MM-dd HH:mm");
  } catch {
    return iso;
  }
}

function fmtValue(v: number | string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (Number.isNaN(n)) return String(v);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

export default function MarketplacePage() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const defaultTenantId = user?.tenant_id ?? "";
  const [filterCountry, setFilterCountry] = useState("");
  const [filterIndustry, setFilterIndustry] = useState("");
  const [filterType, setFilterType] = useState<MarketplaceOpportunityType | "">("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newCompany, setNewCompany] = useState("");
  const [newCountry, setNewCountry] = useState("");
  const [newIndustry, setNewIndustry] = useState("");
  const [newType, setNewType] = useState<MarketplaceOpportunityType>("distributor");
  const [newValue, setNewValue] = useState("");

  const {
    data: overview,
    isLoading: overviewLoading,
    isError: overviewError,
    refetch: refetchOverview,
  } = useQuery({
    queryKey: ["marketplace-overview"],
    queryFn: () => marketplaceApi.overview().then((r) => r.data),
  });

  const { data: oppsData, isLoading: oppsLoading } = useQuery({
    queryKey: ["marketplace-opportunities", filterCountry, filterIndustry, filterType],
    queryFn: () =>
      marketplaceApi
        .opportunities({
          country: filterCountry || undefined,
          industry: filterIndustry || undefined,
          opportunity_type: filterType || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!overview,
  });

  const { data: topOpps } = useQuery({
    queryKey: ["marketplace-top"],
    queryFn: () => marketplaceApi.topOpportunities({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
  });

  const { data: insights } = useQuery({
    queryKey: ["marketplace-insights"],
    queryFn: () => marketplaceApi.insights().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: activity } = useQuery({
    queryKey: ["marketplace-activity"],
    queryFn: () => marketplaceApi.activity({ limit: 30 }).then((r) => r.data),
    enabled: !!overview,
  });

  const createMut = useMutation({
    mutationFn: () =>
      marketplaceApi.createOpportunity({
        title: newTitle,
        buyer_company: newCompany,
        country: newCountry || undefined,
        industry: newIndustry || undefined,
        opportunity_type: newType,
        estimated_value: newValue ? parseFloat(newValue) : undefined,
        created_by_tenant: defaultTenantId || undefined,
      }),
    onSuccess: (res) => {
      toast.success(res.data.message);
      setShowCreate(false);
      setNewTitle("");
      setNewCompany("");
      qc.invalidateQueries({ queryKey: ["marketplace-overview"] });
      qc.invalidateQueries({ queryKey: ["marketplace-opportunities"] });
      qc.invalidateQueries({ queryKey: ["marketplace-top"] });
      qc.invalidateQueries({ queryKey: ["marketplace-insights"] });
      qc.invalidateQueries({ queryKey: ["marketplace-activity"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const interestMut = useMutation({
    mutationFn: (opportunityId: string) =>
      marketplaceApi.expressInterest({
        opportunity_id: opportunityId,
        tenant_id: defaultTenantId,
      }),
    onSuccess: (res) => {
      toast.success(res.data.message);
      qc.invalidateQueries({ queryKey: ["marketplace-overview"] });
      qc.invalidateQueries({ queryKey: ["marketplace-opportunities"] });
      qc.invalidateQueries({ queryKey: ["marketplace-activity"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const claimMut = useMutation({
    mutationFn: (opportunityId: string) =>
      marketplaceApi.claimOpportunity({
        opportunity_id: opportunityId,
        tenant_id: defaultTenantId,
      }),
    onSuccess: (res) => {
      toast.success(res.data.message);
      qc.invalidateQueries({ queryKey: ["marketplace-overview"] });
      qc.invalidateQueries({ queryKey: ["marketplace-opportunities"] });
      qc.invalidateQueries({ queryKey: ["marketplace-activity"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const opps = oppsData?.items ?? [];
  const selected =
    opps.find((o) => o.id === selectedId) ?? opps[0] ?? null;

  const integrationDegraded = useMemo(
    () => (overview?.integration_checks ?? []).filter((c) => c.status !== "ok"),
    [overview],
  );

  if (overviewLoading) return <DashboardSkeleton />;
  if (overviewError || !overview)
    return <ErrorState message="Failed to load marketplace overview" onRetry={refetchOverview} />;

  return (
    <PageShell wide className="space-y-6">
      <PageHeader
        title="Marketplace & Lead Exchange"
        subtitle="Discover and exchange buyer opportunities across factory partners — manual participation only."
        icon={Store}
        actions={
          <button
            type="button"
            className="btn-primary text-sm"
            onClick={() => setShowCreate((v) => !v)}
          >
            List opportunity
          </button>
        }
      />

      <ExecutiveKpiBar
        items={[
          { label: "Open", value: overview.open_opportunities },
          { label: "In review", value: overview.in_review },
          { label: "Claimed", value: overview.claimed },
          { label: "Total listed", value: overview.total_opportunities },
          { label: "Avg value", value: fmtValue(overview.average_estimated_value) },
        ]}
      />

      <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 px-4 py-2 flex items-start gap-2 text-xs text-emerald-900">
        <Shield className="w-4 h-4 shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {(overview.errors?.length ?? 0) > 0 && <PartialErrorsBanner errors={overview.errors} />}

      {integrationDegraded.length > 0 && (
        <p className="text-xs text-amber-800">
          {integrationDegraded.length} integration probe(s) degraded — exchange still available.
        </p>
      )}

      {showCreate && (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold">Register buyer opportunity</p>
          <div className="grid sm:grid-cols-2 gap-3">
            <input
              className="input text-sm"
              placeholder="Title"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
            />
            <input
              className="input text-sm"
              placeholder="Buyer company"
              value={newCompany}
              onChange={(e) => setNewCompany(e.target.value)}
            />
            <input
              className="input text-sm"
              placeholder="Country"
              value={newCountry}
              onChange={(e) => setNewCountry(e.target.value)}
            />
            <input
              className="input text-sm"
              placeholder="Industry"
              value={newIndustry}
              onChange={(e) => setNewIndustry(e.target.value)}
            />
            <select
              className="input text-sm"
              value={newType}
              onChange={(e) => setNewType(e.target.value as MarketplaceOpportunityType)}
            >
              {(Object.keys(TYPE_LABELS) as MarketplaceOpportunityType[]).map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t]}
                </option>
              ))}
            </select>
            <input
              className="input text-sm"
              placeholder="Estimated value (USD)"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="btn-primary text-sm"
            disabled={!newTitle || !newCompany || createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            {createMut.isPending ? <Loader2 className="w-4 h-4 animate-spin inline" /> : null}
            Create opportunity
          </button>
        </div>
      )}

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Marketplace Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Total</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.total_opportunities}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Open</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.open_opportunities}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">In review</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.in_review}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Claimed</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.claimed}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Interests</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.total_interests}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Claims</p>
            <p className="text-2xl font-semibold tabular-nums">{overview.total_claims}</p>
          </div>
          <div className="card p-4 col-span-2">
            <p className="text-[10px] uppercase text-gray-400">Avg value</p>
            <p className="text-2xl font-semibold tabular-nums">
              {fmtValue(overview.average_estimated_value)}
            </p>
          </div>
        </div>
      </section>

      <div className="grid lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-900">Opportunity Feed</h2>
            <div className="flex flex-wrap gap-2">
              <input
                className="text-xs border border-gray-200 rounded-lg px-2 py-1"
                placeholder="Country"
                value={filterCountry}
                onChange={(e) => setFilterCountry(e.target.value)}
              />
              <input
                className="text-xs border border-gray-200 rounded-lg px-2 py-1"
                placeholder="Industry"
                value={filterIndustry}
                onChange={(e) => setFilterIndustry(e.target.value)}
              />
              <select
                className="text-xs border border-gray-200 rounded-lg px-2 py-1"
                value={filterType}
                onChange={(e) =>
                  setFilterType(e.target.value as MarketplaceOpportunityType | "")
                }
              >
                <option value="">All types</option>
                {(Object.keys(TYPE_LABELS) as MarketplaceOpportunityType[]).map((t) => (
                  <option key={t} value={t}>
                    {TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {oppsLoading ? (
            <LoadingState label="Loading opportunities…" />
          ) : opps.length === 0 ? (
            <EmptyState title="No opportunities" description="List a buyer opportunity to get started." />
          ) : (
            <div className="card overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="text-left p-2">Opportunity</th>
                    <th className="text-left p-2">Market</th>
                    <th className="text-left p-2">Value</th>
                    <th className="text-left p-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {opps.map((o: MarketplaceOpportunityItem) => (
                    <tr
                      key={o.id}
                      className={cn(
                        "border-t border-gray-100 cursor-pointer hover:bg-gray-50/80",
                        selected?.id === o.id && "bg-brand-50/40",
                      )}
                      onClick={() => setSelectedId(o.id)}
                    >
                      <td className="p-2">
                        <p className="font-medium text-gray-900">{o.title}</p>
                        <p className="text-gray-500">{o.buyer_company}</p>
                      </td>
                      <td className="p-2 text-gray-600">
                        {[o.country, o.industry, TYPE_LABELS[o.opportunity_type]]
                          .filter(Boolean)
                          .join(" · ")}
                      </td>
                      <td className="p-2 tabular-nums">{fmtValue(o.estimated_value)}</td>
                      <td className="p-2">
                        <span
                          className={cn(
                            "text-[10px] px-2 py-0.5 rounded-full border capitalize",
                            STATUS_STYLES[o.status],
                          )}
                        >
                          {o.status.replace("_", " ")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Opportunity Detail</h2>
          {!selected ? (
            <EmptyState title="Select an opportunity" />
          ) : (
            <div className="card p-4 space-y-3 text-sm">
              <p className="font-semibold text-gray-900">{selected.title}</p>
              <p className="text-gray-600">{selected.description || "No description."}</p>
              <dl className="space-y-1 text-xs text-gray-600">
                <div className="flex justify-between">
                  <dt>Buyer</dt>
                  <dd className="font-medium text-gray-900">{selected.buyer_company}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Rank score</dt>
                  <dd className="tabular-nums">{selected.rank_score}/100</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Participation</dt>
                  <dd>
                    {selected.view_count} views · {selected.interest_count} interests ·{" "}
                    {selected.claim_count} claims
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt>Updated</dt>
                  <dd>{fmtDt(selected.updated_at)}</dd>
                </div>
              </dl>
              <div className="flex flex-wrap gap-2 pt-2">
                <button
                  type="button"
                  className="btn-secondary text-xs"
                  disabled={!defaultTenantId || interestMut.isPending || selected.status === "closed"}
                  onClick={() => interestMut.mutate(selected.id)}
                >
                  Express interest
                </button>
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={
                    !defaultTenantId ||
                    claimMut.isPending ||
                    selected.status === "claimed" ||
                    selected.status === "closed"
                  }
                  onClick={() => claimMut.mutate(selected.id)}
                >
                  Manual claim
                </button>
              </div>
              {!defaultTenantId && (
                <p className="text-[10px] text-amber-700">
                  Sign in as a factory tenant to express interest or claim manually.
                </p>
              )}
            </div>
          )}
        </section>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
          <TrendingUp size={14} />
          Opportunity Ranking
        </h2>
        <div className="grid md:grid-cols-3 gap-4">
          {(["best_opportunities", "newest_opportunities", "strategic_opportunities"] as const).map(
            (key) => (
              <div key={key} className="card p-4">
                <p className="text-xs font-semibold text-gray-700 mb-2 capitalize">
                  {key.replace(/_/g, " ")}
                </p>
                <ul className="space-y-2 text-xs">
                  {(topOpps?.[key] ?? []).slice(0, 5).map((row) => (
                    <li key={row.opportunity_id} className="flex justify-between gap-2">
                      <span className="text-gray-900 truncate">{row.title}</span>
                      <span className="text-gray-500 shrink-0 tabular-nums">{row.rank_score}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ),
          )}
        </div>
      </section>

      <div className="grid md:grid-cols-2 gap-6">
        <section>
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
            <Globe size={14} />
            Marketplace Insights
          </h2>
          <div className="card p-4 space-y-4 text-xs">
            <div>
              <p className="font-medium text-gray-700 mb-1">Top countries</p>
              <ul className="space-y-1">
                {(insights?.top_countries ?? []).slice(0, 5).map((s) => (
                  <li key={s.label} className="flex justify-between">
                    <span>{s.label}</span>
                    <span className="text-gray-500">{s.count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="font-medium text-gray-700 mb-1">Top industries</p>
              <ul className="space-y-1">
                {(insights?.top_industries ?? []).slice(0, 5).map((s) => (
                  <li key={s.label} className="flex justify-between">
                    <span>{s.label}</span>
                    <span className="text-gray-500">{s.count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="font-medium text-gray-700 mb-1">Most active tenants</p>
              <ul className="space-y-1">
                {(insights?.most_active_tenants ?? []).map((t) => (
                  <li key={t.tenant_id} className="flex justify-between">
                    <span>{t.tenant_name}</span>
                    <span className="text-gray-500">{t.activity_count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        <section>
          <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-1">
            <ArrowRightLeft size={14} />
            Activity Feed
          </h2>
          <div className="card p-4 max-h-64 overflow-y-auto">
            <ul className="space-y-2 text-xs">
              {(activity?.items ?? []).map((a) => (
                <li key={`${a.activity_type}-${a.id}`} className="border-b border-gray-50 pb-2">
                  <span className="capitalize font-medium text-gray-800">{a.activity_type}</span>
                  <span className="text-gray-600"> — {a.opportunity_title}</span>
                  {a.tenant_label && (
                    <span className="text-gray-400"> ({a.tenant_label})</span>
                  )}
                  <p className="text-[10px] text-gray-400">{fmtDt(a.occurred_at)}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </div>

      <section className="card p-4">
        <p className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1">
          <Handshake size={12} />
          Integrations (read-only probes)
        </p>
        <div className="flex flex-wrap gap-2">
          <Link href="/buyer-discovery" className="text-xs text-brand-700 hover:underline">
            Buyer Discovery
          </Link>
          <Link href="/buyer-intelligence" className="text-xs text-brand-700 hover:underline">
            Buyer Intelligence
          </Link>
          <Link href="/deal-risk" className="text-xs text-brand-700 hover:underline">
            Deal Risk
          </Link>
          <Link href="/revenue-forecast" className="text-xs text-brand-700 hover:underline">
            Revenue Forecast
          </Link>
          <Link href="/factory-platform" className="text-xs text-brand-700 hover:underline">
            Factory Platform
          </Link>
          <Link href="/customer-portal" className="text-xs text-brand-700 hover:underline">
            Customer Portal
          </Link>
        </div>
      </section>
    </PageShell>
  );
}
