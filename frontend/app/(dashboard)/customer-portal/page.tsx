"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Briefcase,
  Building2,
  FileText,
  LayoutDashboard,
  Target,
  TrendingUp,
  Users,
  CreditCard,
  Layers,
  Clapperboard,
} from "lucide-react";
import {
  customerPortalApi,
  buyerAcquisitionApi,
  firstPilotClientApi,
  buyerNetworkApi,
  marketplaceApi,
  CustomerPortalAccount,
  CustomerPortalBuyerItem,
  CustomerPortalDealItem,
  CustomerPortalProposalItem,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

type Section =
  | "dashboard"
  | "buyers"
  | "buyer-acquisition"
  | "buyer-opportunities"
  | "network-insights"
  | "deals"
  | "proposals"
  | "reports"
  | "billing";

const SECTIONS: { id: Section; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "buyers", label: "Buyers", icon: Users },
  { id: "buyer-acquisition", label: "Buyer Acquisition", icon: Layers },
  { id: "buyer-opportunities", label: "Buyer Opportunities", icon: Target },
  { id: "network-insights", label: "Network Insights", icon: Target },
  { id: "deals", label: "Deals", icon: Briefcase },
  { id: "proposals", label: "Proposals", icon: FileText },
  { id: "reports", label: "Reports", icon: TrendingUp },
  { id: "billing", label: "Billing", icon: CreditCard },
];

const RISK_STYLES: Record<string, string> = {
  healthy: "bg-emerald-100 text-emerald-900 border-emerald-200",
  watchlist: "bg-amber-100 text-amber-900 border-amber-200",
  at_risk: "bg-orange-100 text-orange-900 border-orange-200",
  critical: "bg-red-100 text-red-900 border-red-300",
  stalled: "bg-gray-100 text-gray-800 border-gray-300",
  lost_probability_high: "bg-red-200 text-red-950 border-red-400",
};

const CUSTOMER_JOURNEY_PREVIEW = [
  { title: "Customer Dashboard", route: "/customer-portal-v2" },
  { title: "Opportunities", route: "/customer-portal-v2" },
  { title: "Deals", route: "/customer-portal-v2" },
  { title: "Reports", route: "/customer-portal-v2" },
  { title: "Billing", route: "/customer-portal-v2" },
  { title: "Factory Snapshot", route: "/customer-portal-v2" },
] as const;

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function KpiCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
    </div>
  );
}

export default function CustomerPortalPage() {
  const [section, setSection] = useState<Section>("dashboard");
  const [accountId, setAccountId] = useState<string>("");

  const { data: accountsData, isLoading: accountsLoading } = useQuery({
    queryKey: ["customer-portal-accounts"],
    queryFn: () =>
      customerPortalApi.listAccounts({ portal_status: "active", limit: 100 }).then((r) => r.data),
  });

  const accounts = useMemo(
    () => normalizeList(accountsData?.items ?? accountsData) as CustomerPortalAccount[],
    [accountsData],
  );

  useEffect(() => {
    if (!accountId && accounts.length > 0) {
      const stored = typeof window !== "undefined" ? localStorage.getItem("customerPortalAccountId") : null;
      const pick = stored && accounts.some((a) => a.id === stored) ? stored : accounts[0].id;
      setAccountId(pick);
    }
  }, [accounts, accountId]);

  useEffect(() => {
    if (accountId && typeof window !== "undefined") {
      localStorage.setItem("customerPortalAccountId", accountId);
    }
  }, [accountId]);

  const { data: dashboard, isLoading: dashLoading, isError: dashError, error: dashErr, refetch: refetchDash } = useQuery({
    queryKey: ["customer-portal-dashboard", accountId],
    queryFn: () => customerPortalApi.dashboard(accountId).then((r) => r.data),
    enabled: !!accountId && section === "dashboard",
  });

  const { data: buyers, isLoading: buyersLoading, isError: buyersError, error: buyersErr, refetch: refetchBuyers } = useQuery({
    queryKey: ["customer-portal-buyers", accountId],
    queryFn: () => customerPortalApi.buyers(accountId, { limit: 100 }).then((r) => r.data),
    enabled: !!accountId && section === "buyers",
  });

  const { data: acquisitionOverview, isLoading: acquisitionLoading } = useQuery({
    queryKey: ["customer-portal-buyer-acquisition"],
    queryFn: () => buyerAcquisitionApi.overview().then((r) => r.data),
    enabled: section === "buyer-acquisition",
  });

  const { data: acquisitionInsights } = useQuery({
    queryKey: ["customer-portal-buyer-acquisition-insights"],
    queryFn: () => buyerAcquisitionApi.insights({ limit: 8 }).then((r) => r.data),
    enabled: section === "buyer-acquisition",
  });

  const { data: marketplaceOpps, isLoading: marketplaceLoading } = useQuery({
    queryKey: ["customer-portal-marketplace"],
    queryFn: () => marketplaceApi.opportunities({ limit: 50 }).then((r) => r.data),
    enabled: section === "buyer-opportunities",
  });

  const { data: networkInsights, isLoading: networkInsightsLoading } = useQuery({
    queryKey: ["customer-portal-network-insights"],
    queryFn: () => buyerNetworkApi.insights({ limit: 12 }).then((r) => r.data),
    enabled: section === "network-insights",
  });

  const { data: launchReadiness } = useQuery({
    queryKey: ["first-pilot-client-portal-indicator"],
    queryFn: () => firstPilotClientApi.summaryWidget().then((r) => r.data),
  });

  const { data: deals, isLoading: dealsLoading, isError: dealsError, error: dealsErr, refetch: refetchDeals } = useQuery({
    queryKey: ["customer-portal-deals", accountId],
    queryFn: () => customerPortalApi.deals(accountId, { limit: 100 }).then((r) => r.data),
    enabled: !!accountId && section === "deals",
  });

  const { data: proposals, isLoading: proposalsLoading, isError: proposalsError, error: proposalsErr, refetch: refetchProposals } = useQuery({
    queryKey: ["customer-portal-proposals", accountId],
    queryFn: () => customerPortalApi.proposals(accountId, { limit: 100 }).then((r) => r.data),
    enabled: !!accountId && section === "proposals",
  });

  const { data: reports, isLoading: reportsLoading, isError: reportsError, error: reportsErr, refetch: refetchReports } = useQuery({
    queryKey: ["customer-portal-reports", accountId],
    queryFn: () => customerPortalApi.reports(accountId).then((r) => r.data),
    enabled: !!accountId && section === "reports",
  });

  const { data: billing, isLoading: billingLoading, isError: billingError, error: billingErr, refetch: refetchBilling } = useQuery({
    queryKey: ["customer-portal-billing", accountId],
    queryFn: () => customerPortalApi.billing(accountId).then((r) => r.data),
    enabled: !!accountId && section === "billing",
  });

  const { data: factorySnapshot } = useQuery({
    queryKey: ["customer-portal-factory-snapshot"],
    queryFn: () => customerPortalApi.factorySnapshot().then((r) => r.data),
    enabled: section === "dashboard",
  });

  const selectedAccount = accounts.find((a) => a.id === accountId);

  if (accountsLoading) return <LoadingState message="Loading portal accounts…" />;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Building2 size={22} className="text-teal-600" />
            Customer Portal
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Factory partner view — your company data only (read-only)
          </p>
        </div>
        <Link
          href="/customer-portal-v2"
          className="text-xs font-medium text-teal-800 bg-teal-50 border border-teal-200 rounded-lg px-3 py-2 hover:bg-teal-100 self-start"
        >
          Upgrade to Customer Portal v2 →
        </Link>
        {accounts.length > 0 && (
          <select
            className="input max-w-xs text-sm"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.company_name}
              </option>
            ))}
          </select>
        )}
      </div>

      {launchReadiness && (
        <section className="card p-4 space-y-2 border-teal-200 bg-teal-50/30">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Launch Readiness Indicator</p>
            <Link href="/first-pilot-client" className="text-xs text-brand-700 hover:underline">
              First pilot client →
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
            <div className="rounded-lg border border-teal-100 bg-white px-2 py-2">
              <p className="text-[10px] text-teal-700">Readiness</p>
              <p className="text-lg font-semibold tabular-nums">{launchReadiness.readiness_score}%</p>
            </div>
            <div className="rounded-lg border border-red-100 bg-white px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold tabular-nums">{launchReadiness.blocker_count}</p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-white px-2 py-2">
              <p className="text-[10px] text-emerald-700">Launch</p>
              <p className="text-lg font-semibold tabular-nums">
                {launchReadiness.launch_ready ? "Ready" : "Pending"}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 bg-white px-2 py-2">
              <p className="text-[10px] text-gray-600">Client</p>
              <p className="text-sm font-medium truncate">
                {launchReadiness.company_name ?? "—"}
              </p>
            </div>
          </div>
          <p className="text-[10px] text-gray-400">{launchReadiness.safety_notice}</p>
        </section>
      )}

      <section className="card p-4 space-y-2 border-teal-100 bg-teal-50/20">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Clapperboard size={16} className="text-teal-700" />
            Preview Customer Journey
          </p>
          <Link href="/customer-portal-v2" className="text-xs text-brand-700 hover:underline">
            Open Portal v2 →
          </Link>
        </div>
        <p className="text-xs text-gray-500">
          Customer-facing demo path after factory onboarding — read-only portal views.
        </p>
        <ol className="flex flex-wrap gap-2 text-xs">
          {CUSTOMER_JOURNEY_PREVIEW.map((s) => (
            <li key={s.title}>
              <Link
                href={s.route}
                className="inline-flex rounded-full border border-gray-200 bg-white px-2 py-1 text-gray-700 hover:border-teal-200"
              >
                {s.title}
              </Link>
            </li>
          ))}
        </ol>
      </section>

      {accounts.length === 0 ? (
        <EmptyState
          title="No portal accounts"
          description="Approve a factory application, create a client, then create a portal account from Factory Partners admin."
          action={
            <Link href="/factory-partners" className="btn-primary text-sm">
              Factory Partners admin
            </Link>
          }
        />
      ) : (
        <>
          {selectedAccount && (
            <div className="card p-3 text-xs text-gray-600 flex flex-wrap gap-x-4 gap-y-1">
              <span>
                <strong>Company:</strong> {selectedAccount.company_name}
              </span>
              <span>
                <strong>Status:</strong> {selectedAccount.portal_status}
              </span>
              {selectedAccount.owner_user && (
                <span>
                  <strong>Owner:</strong> {selectedAccount.owner_user}
                </span>
              )}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {SECTIONS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setSection(id)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs border",
                  section === id
                    ? "bg-teal-100 border-teal-200 text-teal-900"
                    : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50",
                )}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>

          {section === "dashboard" && (
            <>
              {dashLoading && <LoadingState message="Loading dashboard…" />}
              {dashError && (
                <ErrorState
                  message={dashErr instanceof Error ? dashErr.message : "Failed to load dashboard"}
                  onRetry={() => refetchDash()}
                />
              )}
              {dashboard && (
                <div className="space-y-4">
                  <PartialErrorsBanner errors={dashboard.errors} />
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                    <KpiCard label="Active leads" value={dashboard.active_leads} />
                    <KpiCard label="Active buyers" value={dashboard.active_buyers} />
                    {(dashboard.discovered_buyers ?? 0) > 0 && (
                      <KpiCard label="Discovered buyers" value={dashboard.discovered_buyers!} />
                    )}
                    <KpiCard label="Proposals" value={dashboard.proposals} />
                    <KpiCard label="Opportunities" value={dashboard.opportunities} />
                    <KpiCard
                      label="Revenue"
                      value={fmtMoney(dashboard.revenue_summary.total_revenue)}
                    />
                  </div>
                  {(dashboard.high_potential_discoveries ?? 0) > 0 && (
                    <div className="card p-4 flex items-center justify-between gap-2">
                      <p className="text-sm text-gray-700">
                        {dashboard.high_potential_discoveries} high-potential export buyer(s) in discovery
                        registry
                      </p>
                      <Link href="/buyer-discovery" className="text-xs text-brand-700 hover:underline">
                        Buyer Discovery →
                      </Link>
                    </div>
                  )}
                  {(dashboard.marketplace_opportunities ?? 0) > 0 && (
                    <div className="card p-4 flex items-center justify-between gap-2">
                      <p className="text-sm text-gray-700">
                        {dashboard.marketplace_opportunities} open marketplace opportunit
                        {dashboard.marketplace_opportunities === 1 ? "y" : "ies"} (
                        {dashboard.marketplace_total ?? 0} total listed)
                      </p>
                      <Link href="/marketplace" className="text-xs text-brand-700 hover:underline">
                        Marketplace →
                      </Link>
                    </div>
                  )}
                  {factorySnapshot && (
                    <div className="card p-4 space-y-3 border-amber-100">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-gray-900">Factory Snapshot</p>
                        <Link href="/factory-platform" className="text-xs text-brand-700 hover:underline">
                          Factory Platform →
                        </Link>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
                        <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
                          <p className="text-[10px] text-amber-800">Profile score</p>
                          <p className="text-lg font-semibold tabular-nums">{factorySnapshot.profile_score}</p>
                        </div>
                        <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
                          <p className="text-[10px] text-teal-700">Buyers</p>
                          <p className="text-lg font-semibold tabular-nums">{factorySnapshot.total_buyers}</p>
                        </div>
                        <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
                          <p className="text-[10px] text-indigo-700">Opportunities</p>
                          <p className="text-lg font-semibold tabular-nums">
                            {factorySnapshot.active_opportunities}
                          </p>
                        </div>
                        <div className="rounded-lg border border-gray-200 bg-gray-50 px-2 py-2">
                          <p className="text-[10px] text-gray-600">Verification</p>
                          <p className="text-sm font-semibold capitalize">
                            {factorySnapshot.verification_status.replace(/_/g, " ")}
                          </p>
                        </div>
                      </div>
                      <p className="text-xs text-gray-600">
                        {factorySnapshot.brand_name ?? factorySnapshot.company_name}
                      </p>
                    </div>
                  )}
                  <p className="text-[10px] text-gray-400">{dashboard.safety_notice}</p>
                </div>
              )}
            </>
          )}

          {section === "buyers" && (
            <>
              {buyersLoading && <LoadingState message="Loading buyers…" />}
              {buyersError && (
                <ErrorState
                  message={buyersErr instanceof Error ? buyersErr.message : "Failed to load buyers"}
                  onRetry={() => refetchBuyers()}
                />
              )}
              {buyers && (
                <div className="space-y-3">
                  <PartialErrorsBanner errors={buyers.errors} />
                  {buyers.items.length === 0 ? (
                    <EmptyState title="No buyers" description="Buyers appear when CRM leads exist for your company." />
                  ) : (
                    <div className="card overflow-hidden">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 text-left text-xs text-gray-500">
                          <tr>
                            <th className="px-4 py-2">Buyer</th>
                            <th className="px-4 py-2">Score</th>
                            <th className="px-4 py-2">Classification</th>
                            <th className="px-4 py-2">Opportunities</th>
                            <th className="px-4 py-2">Potential</th>
                          </tr>
                        </thead>
                        <tbody>
                          {buyers.items.map((b: CustomerPortalBuyerItem) => (
                            <tr key={b.buyer_id} className="border-t border-gray-100">
                              <td className="px-4 py-2">
                                <p className="font-medium text-gray-900">{b.name}</p>
                                {b.company && <p className="text-xs text-gray-500">{b.company}</p>}
                              </td>
                              <td className="px-4 py-2 tabular-nums">{b.buyer_score}/100</td>
                              <td className="px-4 py-2 capitalize text-xs">{b.classification.replace(/_/g, " ")}</td>
                              <td className="px-4 py-2 tabular-nums">{b.opportunities}</td>
                              <td className="px-4 py-2 tabular-nums">{fmtMoney(b.annual_potential)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {section === "buyer-opportunities" && (
            <>
              {marketplaceLoading && <LoadingState message="Loading marketplace opportunities…" />}
              {marketplaceOpps && (
                <div className="space-y-3">
                  <p className="text-xs text-gray-500">
                    Partner marketplace exchange — express interest or claim manually on the main
                    marketplace page.
                  </p>
                  <Link href="/marketplace" className="text-xs text-brand-700 hover:underline">
                    Open Marketplace →
                  </Link>
                  {marketplaceOpps.items.length === 0 ? (
                    <EmptyState
                      title="No opportunities"
                      description="Listed buyer opportunities appear here when partners share them."
                    />
                  ) : (
                    <div className="card overflow-hidden">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 text-left text-xs text-gray-500">
                          <tr>
                            <th className="px-4 py-2">Opportunity</th>
                            <th className="px-4 py-2">Market</th>
                            <th className="px-4 py-2">Value</th>
                            <th className="px-4 py-2">Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {marketplaceOpps.items.map((o) => (
                            <tr key={o.id} className="border-t border-gray-100">
                              <td className="px-4 py-2">
                                <p className="font-medium">{o.title}</p>
                                <p className="text-xs text-gray-500">{o.buyer_company}</p>
                              </td>
                              <td className="px-4 py-2 text-gray-600">
                                {[o.country, o.industry].filter(Boolean).join(" · ") || "—"}
                              </td>
                              <td className="px-4 py-2 tabular-nums">{fmtMoney(o.estimated_value)}</td>
                              <td className="px-4 py-2 capitalize">{o.status.replace("_", " ")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {section === "buyer-acquisition" && (
            <>
              {acquisitionLoading && <LoadingState message="Loading buyer acquisition…" />}
              {acquisitionOverview && acquisitionInsights && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm text-gray-600">
                      Unified buyer acquisition workspace — read-only aggregation.
                    </p>
                    <Link href="/buyer-acquisition" className="text-xs text-brand-700 hover:underline">
                      Open Buyer Acquisition →
                    </Link>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <KpiCard label="Total buyers" value={acquisitionOverview.total_buyers} />
                    <KpiCard label="Strategic" value={acquisitionOverview.strategic_buyers} />
                    <KpiCard label="High potential" value={acquisitionOverview.high_potential_buyers} />
                    <KpiCard label="Marketplace opps" value={acquisitionOverview.marketplace_opportunities} />
                  </div>
                  <div className="card p-4">
                    <h3 className="text-sm font-semibold mb-2">Top unified buyers</h3>
                    <ul className="text-xs space-y-2">
                      {(acquisitionInsights.top_buyers ?? []).map((b) => (
                        <li key={`${b.rank}-${b.company_name}`} className="flex justify-between gap-2">
                          <span>{b.company_name}</span>
                          <span className="tabular-nums text-gray-500">score {b.score}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <p className="text-[10px] text-gray-400">{acquisitionOverview.safety_notice}</p>
                </div>
              )}
            </>
          )}

          {section === "network-insights" && (
            <>
              {networkInsightsLoading && <LoadingState message="Loading network insights…" />}
              {networkInsights && (
                <div className="space-y-4">
                  <p className="text-sm text-gray-600">
                    Global buyer network insights — read-only, no automatic actions.
                  </p>
                  <div className="grid md:grid-cols-2 gap-4">
                    <div className="card p-4">
                      <h3 className="text-sm font-semibold mb-2">Strongest buyers</h3>
                      <ul className="text-xs space-y-2">
                        {(networkInsights.strongest_buyers ?? []).map((b) => (
                          <li key={b.buyer_id} className="flex justify-between gap-2">
                            <span>{b.company_name}</span>
                            <span className="tabular-nums text-gray-500">{b.network_strength}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="card p-4">
                      <h3 className="text-sm font-semibold mb-2">Underutilized buyers</h3>
                      <ul className="text-xs space-y-2">
                        {(networkInsights.underutilized_buyers ?? []).map((b) => (
                          <li key={b.buyer_id}>{b.company_name}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  <Link href="/buyer-network" className="text-xs text-brand-700 hover:underline">
                    Open Buyer Network →
                  </Link>
                </div>
              )}
            </>
          )}

          {section === "deals" && (
            <>
              {dealsLoading && <LoadingState message="Loading deals…" />}
              {dealsError && (
                <ErrorState
                  message={dealsErr instanceof Error ? dealsErr.message : "Failed to load deals"}
                  onRetry={() => refetchDeals()}
                />
              )}
              {deals && (
                <div className="space-y-3">
                  <PartialErrorsBanner errors={deals.errors} />
                  {deals.items.length === 0 ? (
                    <EmptyState title="No deals" description="Deals appear when opportunities exist in CRM." />
                  ) : (
                    <div className="card overflow-hidden">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 text-left text-xs text-gray-500">
                          <tr>
                            <th className="px-4 py-2">Deal</th>
                            <th className="px-4 py-2">Status</th>
                            <th className="px-4 py-2">Risk</th>
                            <th className="px-4 py-2">Close %</th>
                            <th className="px-4 py-2">Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {deals.items.map((d: CustomerPortalDealItem) => (
                            <tr key={d.deal_id} className="border-t border-gray-100">
                              <td className="px-4 py-2">
                                <p className="font-medium text-gray-900">{d.title}</p>
                                {d.buyer_name && <p className="text-xs text-gray-500">{d.buyer_name}</p>}
                              </td>
                              <td className="px-4 py-2 capitalize text-xs">{d.status}</td>
                              <td className="px-4 py-2">
                                <span
                                  className={cn(
                                    "text-[10px] px-2 py-0.5 rounded-full border capitalize",
                                    RISK_STYLES[d.risk_level] ?? "bg-gray-100 text-gray-700",
                                  )}
                                >
                                  {d.risk_level.replace(/_/g, " ")}
                                </span>
                              </td>
                              <td className="px-4 py-2 tabular-nums">{Math.round(d.close_probability)}%</td>
                              <td className="px-4 py-2 tabular-nums">{fmtMoney(d.revenue)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {section === "proposals" && (
            <>
              {proposalsLoading && <LoadingState message="Loading proposals…" />}
              {proposalsError && (
                <ErrorState
                  message={proposalsErr instanceof Error ? proposalsErr.message : "Failed to load proposals"}
                  onRetry={() => refetchProposals()}
                />
              )}
              {proposals && (
                <>
                  {proposals.items.length === 0 ? (
                    <EmptyState title="No proposals" description="Proposals appear when created for your company." />
                  ) : (
                    <div className="card overflow-hidden">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 text-left text-xs text-gray-500">
                          <tr>
                            <th className="px-4 py-2">Title</th>
                            <th className="px-4 py-2">Status</th>
                            <th className="px-4 py-2">Buyer</th>
                            <th className="px-4 py-2">Sent</th>
                          </tr>
                        </thead>
                        <tbody>
                          {proposals.items.map((p: CustomerPortalProposalItem) => (
                            <tr key={p.proposal_id} className="border-t border-gray-100">
                              <td className="px-4 py-2 font-medium text-gray-900">{p.title}</td>
                              <td className="px-4 py-2 capitalize text-xs">{p.status}</td>
                              <td className="px-4 py-2 text-xs text-gray-600">{p.buyer_name ?? "—"}</td>
                              <td className="px-4 py-2 text-xs text-gray-500">
                                {p.sent_at ? format(parseISO(p.sent_at), "MMM d, yyyy") : "—"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {section === "reports" && (
            <>
              {reportsLoading && <LoadingState message="Loading reports…" />}
              {reportsError && (
                <ErrorState
                  message={reportsErr instanceof Error ? reportsErr.message : "Failed to load reports"}
                  onRetry={() => refetchReports()}
                />
              )}
              {reports && (
                <div className="space-y-4">
                  <PartialErrorsBanner errors={reports.errors} />
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div className="card p-4 space-y-2">
                      <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                        <Target size={16} className="text-teal-600" />
                        Revenue attribution
                      </p>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div>
                          <p className="text-gray-500">Total revenue</p>
                          <p className="font-semibold tabular-nums">
                            {fmtMoney(reports.revenue_attribution.total_revenue)}
                          </p>
                        </div>
                        <div>
                          <p className="text-gray-500">Deals won</p>
                          <p className="font-semibold tabular-nums">{reports.revenue_attribution.deals_won}</p>
                        </div>
                        <div>
                          <p className="text-gray-500">Avg deal</p>
                          <p className="font-semibold tabular-nums">
                            {fmtMoney(reports.revenue_attribution.avg_deal_size)}
                          </p>
                        </div>
                        <div>
                          <p className="text-gray-500">Conversion</p>
                          <p className="font-semibold tabular-nums">
                            {(reports.revenue_attribution.conversion_rate * 100).toFixed(1)}%
                          </p>
                        </div>
                      </div>
                    </div>
                    <div className="card p-4 space-y-2">
                      <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                        <TrendingUp size={16} className="text-teal-600" />
                        Revenue forecast
                      </p>
                      <p className="text-[10px] text-gray-500">
                        Confidence: {reports.forecast_confidence}
                      </p>
                      {reports.revenue_forecast.length === 0 ? (
                        <p className="text-xs text-gray-500">No forecast periods available.</p>
                      ) : (
                        <ul className="space-y-1 text-xs">
                          {reports.revenue_forecast.map((f) => (
                            <li key={f.period} className="flex justify-between gap-2">
                              <span className="text-gray-600">{f.period}</span>
                              <span className="font-medium tabular-nums">
                                {fmtMoney(f.expected_case)} (exp.)
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                  {reports.top_buyers.length > 0 && (
                    <div className="card p-4">
                      <p className="text-sm font-semibold text-gray-900 mb-2">Top buyers</p>
                      <ul className="space-y-1 text-sm">
                        {reports.top_buyers.map((b) => (
                          <li key={b.buyer_id} className="flex justify-between gap-2">
                            <span>{b.name}</span>
                            <span className="text-xs text-gray-500 tabular-nums">
                              score {b.buyer_score} · {fmtMoney(b.annual_potential)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(reports.buyer_opportunities?.length ?? 0) > 0 && (
                    <div className="card p-4">
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <p className="text-sm font-semibold text-gray-900">Buyer opportunities</p>
                        <Link href="/buyer-discovery" className="text-xs text-brand-700 hover:underline">
                          Discovery registry →
                        </Link>
                      </div>
                      <ul className="space-y-1 text-sm">
                        {reports.buyer_opportunities!.map((b) => (
                          <li key={b.buyer_id} className="flex justify-between gap-2">
                            <span>{b.company_name}</span>
                            <span className="text-xs text-gray-500 tabular-nums">
                              score {b.opportunity_score}
                              {b.country ? ` · ${b.country}` : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className="text-[10px] text-gray-400">{reports.safety_notice}</p>
                </div>
              )}
            </>
          )}

          {section === "billing" && (
            <>
              {billingLoading && <LoadingState message="Loading billing…" />}
              {billingError && (
                <ErrorState
                  message={billingErr instanceof Error ? billingErr.message : "Failed to load billing"}
                  onRetry={() => refetchBilling()}
                />
              )}
              {billing && (
                <div className="space-y-4">
                  <PartialErrorsBanner errors={billing.errors} />
                  <div className="card p-4 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div>
                      <p className="text-[10px] uppercase text-gray-400">Plan</p>
                      <p className="text-lg font-semibold">
                        {billing.billing_summary?.plan?.name ?? "Free"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase text-gray-400">Status</p>
                      <p className="text-sm font-medium capitalize">
                        {billing.billing_summary?.status ?? "none"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase text-gray-400">Monthly price</p>
                      <p className="text-lg font-semibold tabular-nums">
                        {billing.billing_summary?.monthly_price != null
                          ? `$${billing.billing_summary.monthly_price}`
                          : "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] uppercase text-gray-400">Next renewal</p>
                      <p className="text-sm">
                        {billing.billing_summary?.next_renewal
                          ? format(parseISO(billing.billing_summary.next_renewal), "dd MMM yyyy")
                          : "—"}
                      </p>
                    </div>
                  </div>
                  {billing.billing_summary?.usage_summary && (
                    <div className="card p-4 space-y-3">
                      <p className="text-sm font-semibold text-gray-900">Usage vs plan limits</p>
                      <div className="grid sm:grid-cols-2 gap-3 text-xs">
                        {(["users", "leads", "buyers", "deals"] as const).map((key) => {
                          const m = billing.billing_summary.usage_summary[key];
                          return (
                            <div key={key} className="flex justify-between">
                              <span className="capitalize text-gray-600">{key}</span>
                              <span className="tabular-nums">
                                {m.current}
                                {m.limit != null ? ` / ${m.limit}` : " / ∞"}
                                {m.utilization_pct != null ? ` (${m.utilization_pct}%)` : ""}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  <p className="text-[10px] text-gray-400">{billing.safety_notice}</p>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
