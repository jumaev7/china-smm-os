"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowRightLeft,
  Filter,
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
  ActionBar,
  ExecutiveKpiBar,
  PageHeader,
  PageSection,
  PageShell,
  SectionCard,
  StatTile,
  StatusBadge,
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

const STATUS_VARIANT: Record<
  MarketplaceOpportunityStatus,
  "success" | "warning" | "info" | "neutral"
> = {
  open: "success",
  in_review: "warning",
  claimed: "info",
  closed: "neutral",
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
        subtitle="Discover and exchange high-value buyer opportunities across factory partners — manual participation only."
        icon={Store}
        iconClassName="text-teal-400"
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

      <div className="rounded-xl border border-emerald-200/80 bg-emerald-50/40 px-4 py-3 flex items-start gap-2 text-xs text-emerald-900 dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-200">
        <Shield className="w-4 h-4 shrink-0 mt-0.5 text-emerald-600 dark-tenant:text-emerald-400" />
        <span>{overview.safety_notice}</span>
      </div>

      {(overview.errors?.length ?? 0) > 0 && <PartialErrorsBanner errors={overview.errors} />}

      {integrationDegraded.length > 0 && (
        <p className="text-xs text-amber-800 dark-tenant:text-amber-300">
          {integrationDegraded.length} integration probe(s) degraded — exchange still available.
        </p>
      )}

      {showCreate && (
        <SectionCard title="Register buyer opportunity" icon={Store} iconClassName="text-teal-400">
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
        </SectionCard>
      )}

      <PageSection title="Marketplace pulse" description="Participation and exchange activity at a glance">
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
          <StatTile label="Total" value={overview.total_opportunities} tone="neutral" />
          <StatTile label="Open" value={overview.open_opportunities} tone="success" />
          <StatTile label="In review" value={overview.in_review} tone="warning" />
          <StatTile label="Claimed" value={overview.claimed} tone="violet" />
          <StatTile label="Interests" value={overview.total_interests} tone="sky" />
          <StatTile label="Claims" value={overview.total_claims} tone="info" />
          <StatTile
            label="Avg value"
            value={fmtValue(overview.average_estimated_value)}
            tone="brand"
            className="col-span-2"
          />
        </div>
      </PageSection>

      <div className="grid lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-3">
          <PageSection title="Opportunity feed" description="Browse and filter listed buyer opportunities">
            <ActionBar>
              <Filter size={14} className="text-slate-400 shrink-0" />
              <input
                className="input text-xs min-w-[120px] w-auto"
                placeholder="Country"
                value={filterCountry}
                onChange={(e) => setFilterCountry(e.target.value)}
              />
              <input
                className="input text-xs min-w-[120px] w-auto"
                placeholder="Industry"
                value={filterIndustry}
                onChange={(e) => setFilterIndustry(e.target.value)}
              />
              <select
                className="input text-xs min-w-[140px] w-auto"
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
            </ActionBar>
          </PageSection>

          {oppsLoading ? (
            <LoadingState label="Loading opportunities…" />
          ) : opps.length === 0 ? (
            <EmptyState title="No opportunities" description="List a buyer opportunity to get started." />
          ) : (
            <div className="card-premium overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-gray-50/80 text-gray-500 dark-tenant:bg-surface-dark-elevated/80 dark-tenant:text-slate-400">
                  <tr>
                    <th className="text-left p-2.5 font-medium">Opportunity</th>
                    <th className="text-left p-2.5 font-medium">Market</th>
                    <th className="text-left p-2.5 font-medium">Value</th>
                    <th className="text-left p-2.5 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 dark-tenant:divide-white/[0.04]">
                  {opps.map((o: MarketplaceOpportunityItem) => (
                    <tr
                      key={o.id}
                      className={cn(
                        "cursor-pointer transition-colors hover:bg-gray-50/60 dark-tenant:hover:bg-white/[0.02]",
                        selected?.id === o.id &&
                          "bg-brand-50/40 dark-tenant:bg-violet-500/10",
                      )}
                      onClick={() => setSelectedId(o.id)}
                    >
                      <td className="p-2.5">
                        <p className="font-medium text-gray-900 dark-tenant:text-slate-100">{o.title}</p>
                        <p className="text-gray-500 dark-tenant:text-slate-500">{o.buyer_company}</p>
                      </td>
                      <td className="p-2.5 text-gray-600 dark-tenant:text-slate-400">
                        {[o.country, o.industry, TYPE_LABELS[o.opportunity_type]]
                          .filter(Boolean)
                          .join(" · ")}
                      </td>
                      <td className="p-2.5 tabular-nums text-gray-800 dark-tenant:text-slate-200">
                        {fmtValue(o.estimated_value)}
                      </td>
                      <td className="p-2.5">
                        <StatusBadge variant={STATUS_VARIANT[o.status]} className="capitalize text-[10px]">
                          {o.status.replace("_", " ")}
                        </StatusBadge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <SectionCard title="Opportunity detail" icon={TrendingUp} iconClassName="text-violet-400">
          {!selected ? (
            <EmptyState title="Select an opportunity" />
          ) : (
            <div className="space-y-3 text-sm">
              <p className="font-semibold text-gray-900 dark-tenant:text-slate-100">{selected.title}</p>
              <p className="text-gray-600 dark-tenant:text-slate-400 text-xs">
                {selected.description || "No description."}
              </p>
              <dl className="space-y-2 text-xs">
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-500 dark-tenant:text-slate-500">Buyer</dt>
                  <dd className="font-medium text-gray-900 dark-tenant:text-slate-100 text-right">
                    {selected.buyer_company}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-500 dark-tenant:text-slate-500">Rank score</dt>
                  <dd className="tabular-nums text-gray-900 dark-tenant:text-slate-200">
                    {selected.rank_score}/100
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-500 dark-tenant:text-slate-500">Participation</dt>
                  <dd className="text-gray-700 dark-tenant:text-slate-300 text-right">
                    {selected.view_count} views · {selected.interest_count} interests ·{" "}
                    {selected.claim_count} claims
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-gray-500 dark-tenant:text-slate-500">Updated</dt>
                  <dd className="text-gray-700 dark-tenant:text-slate-300">{fmtDt(selected.updated_at)}</dd>
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
                <p className="text-[10px] text-amber-700 dark-tenant:text-amber-400">
                  Sign in as a factory tenant to express interest or claim manually.
                </p>
              )}
            </div>
          )}
        </SectionCard>
      </div>

      <PageSection title="Opportunity ranking" description="Top-ranked opportunities by strategy">
        <div className="grid md:grid-cols-3 gap-4">
          {(["best_opportunities", "newest_opportunities", "strategic_opportunities"] as const).map(
            (key) => (
              <SectionCard
                key={key}
                title={key.replace(/_/g, " ")}
                icon={TrendingUp}
                iconClassName="text-emerald-400"
                className="capitalize"
              >
                <ul className="space-y-2 text-xs">
                  {(topOpps?.[key] ?? []).slice(0, 5).map((row) => (
                    <li key={row.opportunity_id} className="flex justify-between gap-2">
                      <span className="text-gray-900 dark-tenant:text-slate-200 truncate">{row.title}</span>
                      <span className="text-gray-500 dark-tenant:text-slate-500 shrink-0 tabular-nums">
                        {row.rank_score}
                      </span>
                    </li>
                  ))}
                </ul>
              </SectionCard>
            ),
          )}
        </div>
      </PageSection>

      <div className="grid md:grid-cols-2 gap-6">
        <SectionCard title="Marketplace insights" icon={Globe} iconClassName="text-sky-400">
          <div className="space-y-4 text-xs">
            <div>
              <p className="font-medium text-gray-700 dark-tenant:text-slate-300 mb-1">Top countries</p>
              <ul className="space-y-1">
                {(insights?.top_countries ?? []).slice(0, 5).map((s) => (
                  <li key={s.label} className="flex justify-between text-gray-700 dark-tenant:text-slate-300">
                    <span>{s.label}</span>
                    <span className="text-gray-500 dark-tenant:text-slate-500">{s.count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="font-medium text-gray-700 dark-tenant:text-slate-300 mb-1">Top industries</p>
              <ul className="space-y-1">
                {(insights?.top_industries ?? []).slice(0, 5).map((s) => (
                  <li key={s.label} className="flex justify-between text-gray-700 dark-tenant:text-slate-300">
                    <span>{s.label}</span>
                    <span className="text-gray-500 dark-tenant:text-slate-500">{s.count}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="font-medium text-gray-700 dark-tenant:text-slate-300 mb-1">Most active tenants</p>
              <ul className="space-y-1">
                {(insights?.most_active_tenants ?? []).map((t) => (
                  <li key={t.tenant_id} className="flex justify-between text-gray-700 dark-tenant:text-slate-300">
                    <span>{t.tenant_name}</span>
                    <span className="text-gray-500 dark-tenant:text-slate-500">{t.activity_count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Activity feed" icon={ArrowRightLeft} iconClassName="text-violet-400">
          <div className="max-h-64 overflow-y-auto">
            <ul className="space-y-2 text-xs">
              {(activity?.items ?? []).map((a) => (
                <li
                  key={`${a.activity_type}-${a.id}`}
                  className="border-b border-gray-50 dark-tenant:border-white/[0.04] pb-2"
                >
                  <span className="capitalize font-medium text-gray-800 dark-tenant:text-slate-200">
                    {a.activity_type}
                  </span>
                  <span className="text-gray-600 dark-tenant:text-slate-400"> — {a.opportunity_title}</span>
                  {a.tenant_label && (
                    <span className="text-gray-400 dark-tenant:text-slate-500"> ({a.tenant_label})</span>
                  )}
                  <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500">{fmtDt(a.occurred_at)}</p>
                </li>
              ))}
            </ul>
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Integrations" icon={Handshake} iconClassName="text-brand-600 dark-tenant:text-violet-400">
        <p className="text-[10px] text-gray-500 dark-tenant:text-slate-500 -mt-2 mb-1">Read-only probes</p>
        <div className="flex flex-wrap gap-2">
          {[
            { href: "/buyer-discovery", label: "Buyer Discovery" },
            { href: "/buyer-intelligence", label: "Buyer Intelligence" },
            { href: "/deal-risk", label: "Deal Risk" },
            { href: "/revenue-forecast", label: "Revenue Forecast" },
            { href: "/factory-platform", label: "Factory Platform" },
            { href: "/customer-portal", label: "Customer Portal" },
          ].map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="text-xs text-brand-700 hover:text-brand-900 dark-tenant:text-violet-400 dark-tenant:hover:text-violet-300 px-2 py-1 rounded-lg border border-gray-100 dark-tenant:border-white/[0.06] hover:bg-gray-50 dark-tenant:hover:bg-white/[0.04] transition-colors"
            >
              {label}
            </Link>
          ))}
        </div>
      </SectionCard>
    </PageShell>
  );
}
