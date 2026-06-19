"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Briefcase,
  Building2,
  CreditCard,
  Factory,
  FileText,
  LayoutDashboard,
  Sparkles,
  Target,
  TrendingUp,
} from "lucide-react";
import {
  customerPortalV2Api,
  CustomerPortalV2DealItem,
  CustomerPortalV2OpportunityItem,
  CustomerPortalV2ProposalItem,
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
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  KpiCard,
  PageHeader,
  PageShell,
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

type Section =
  | "dashboard"
  | "opportunities"
  | "deals"
  | "proposals"
  | "reports"
  | "billing"
  | "factory-snapshot";

const SECTIONS: { id: Section; labelKey: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", labelKey: "customerPortal.sectionDashboard", icon: LayoutDashboard },
  { id: "opportunities", labelKey: "customerPortal.sectionOpportunities", icon: Target },
  { id: "deals", labelKey: "customerPortal.sectionDeals", icon: Briefcase },
  { id: "proposals", labelKey: "customerPortal.sectionProposals", icon: FileText },
  { id: "reports", labelKey: "customerPortal.sectionReports", icon: TrendingUp },
  { id: "billing", labelKey: "customerPortal.sectionBilling", icon: CreditCard },
  { id: "factory-snapshot", labelKey: "customerPortal.sectionFactorySnapshot", icon: Factory },
];

const RISK_STYLES: Record<string, string> = {
  healthy: "bg-emerald-100 text-emerald-900 border-emerald-200",
  watchlist: "bg-amber-100 text-amber-900 border-amber-200",
  at_risk: "bg-orange-100 text-orange-900 border-orange-200",
  critical: "bg-red-100 text-red-900 border-red-300",
  stalled: "bg-gray-100 text-gray-800 border-gray-300",
  lost_probability_high: "bg-red-200 text-red-950 border-red-400",
};

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function OpportunityTable({ items, emptyLabel }: { items: CustomerPortalV2OpportunityItem[]; emptyLabel: string }) {
  const { t } = useTranslation();
  if (items.length === 0) {
    return <EmptyState message={emptyLabel} />;
  }
  return (
    <DataTable>
      <DataTableHead>
        <tr>
          <DataTableTh>{t("customerPortal.colOpportunity")}</DataTableTh>
          <DataTableTh>{t("customerPortal.colScore")}</DataTableTh>
          <DataTableTh>{t("customerPortal.colCountry")}</DataTableTh>
          <DataTableTh>{t("customerPortal.colIndustry")}</DataTableTh>
          <DataTableTh>{t("customerPortal.colRecommendedAction")}</DataTableTh>
        </tr>
      </DataTableHead>
      <DataTableBody>
          {items.map((row) => (
            <DataTableRow key={row.opportunity_id}>
              <DataTableTd>
                <p className="font-medium text-navy-900">{row.title}</p>
                {row.buyer_company && <p className="text-xs text-gray-500">{row.buyer_company}</p>}
              </DataTableTd>
              <DataTableTd className="tabular-nums">{row.opportunity_score}</DataTableTd>
              <DataTableTd>{row.country || "—"}</DataTableTd>
              <DataTableTd>{row.industry || "—"}</DataTableTd>
              <DataTableTd className="text-xs text-gray-600">{row.recommended_action}</DataTableTd>
            </DataTableRow>
          ))}
      </DataTableBody>
    </DataTable>
  );
}

export default function CustomerPortalV2Page() {
  const { t } = useTranslation();
  const [section, setSection] = useState<Section>("dashboard");

  const { data: dashboard, isLoading: dashLoading, isError: dashError, error: dashErr, refetch: refetchDash } = useQuery({
    queryKey: ["customer-portal-v2-dashboard"],
    queryFn: () => customerPortalV2Api.dashboard().then((r) => r.data),
    enabled: section === "dashboard",
  });

  const { data: opportunities, isLoading: oppsLoading, isError: oppsError, error: oppsErr, refetch: refetchOpps } = useQuery({
    queryKey: ["customer-portal-v2-opportunities"],
    queryFn: () => customerPortalV2Api.opportunities({ limit: 100 }).then((r) => r.data),
    enabled: section === "opportunities",
  });

  const { data: deals, isLoading: dealsLoading, isError: dealsError, error: dealsErr, refetch: refetchDeals } = useQuery({
    queryKey: ["customer-portal-v2-deals"],
    queryFn: () => customerPortalV2Api.deals({ limit: 100 }).then((r) => r.data),
    enabled: section === "deals",
  });

  const { data: proposals, isLoading: proposalsLoading, isError: proposalsError, error: proposalsErr, refetch: refetchProposals } = useQuery({
    queryKey: ["customer-portal-v2-proposals"],
    queryFn: () => customerPortalV2Api.proposals({ limit: 100 }).then((r) => r.data),
    enabled: section === "proposals",
  });

  const { data: reports, isLoading: reportsLoading, isError: reportsError, error: reportsErr, refetch: refetchReports } = useQuery({
    queryKey: ["customer-portal-v2-reports"],
    queryFn: () => customerPortalV2Api.reports().then((r) => r.data),
    enabled: section === "reports",
  });

  const { data: billing, isLoading: billingLoading, isError: billingError, error: billingErr, refetch: refetchBilling } = useQuery({
    queryKey: ["customer-portal-v2-billing"],
    queryFn: () => customerPortalV2Api.billing().then((r) => r.data),
    enabled: section === "billing",
  });

  const { data: factorySnapshot, isLoading: snapshotLoading, isError: snapshotError, error: snapshotErr, refetch: refetchSnapshot } = useQuery({
    queryKey: ["customer-portal-v2-factory-snapshot"],
    queryFn: () => customerPortalV2Api.factorySnapshot().then((r) => r.data),
    enabled: section === "factory-snapshot",
  });

  const companyName =
    dashboard?.tenant?.company_name ?? opportunities?.tenant?.company_name ?? t("customerPortal.partnerWorkspace");

  return (
    <PageShell>
      <PageHeader
        title={t("customerPortal.title")}
        subtitle={`${t("customerPortal.partnerWorkspace")} — ${companyName}`}
        icon={Sparkles}
        iconClassName="text-accent-cyan"
        actions={
          <Link href="/customer-portal" className="btn-secondary text-xs">
            {t("customerPortal.legacyPortal")}
          </Link>
        }
      />

      <nav className="flex flex-wrap gap-1 p-1 rounded-2xl bg-slate-100/80 border border-gray-100">
        {SECTIONS.map(({ id, labelKey, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-xl transition-all",
              section === id
                ? "bg-white text-brand-800 border border-brand-200 shadow-sm"
                : "text-gray-500 hover:text-navy-900 hover:bg-white/60 border border-transparent",
            )}
          >
            <Icon size={14} />
            {t(labelKey)}
          </button>
        ))}
      </nav>

      {section === "dashboard" && (
        <>
          {dashLoading && <DashboardSkeleton />}
          {dashError && (
            <ErrorState
              message={dashErr instanceof Error ? dashErr.message : t("customerPortal.loadDashboardError")}
              onRetry={() => refetchDash()}
            />
          )}
          {dashboard && (
            <div className="space-y-4">
              <PartialErrorsBanner errors={dashboard.errors} />
              <p className="text-[10px] text-gray-400">{dashboard.safety_notice}</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                <KpiCard label={t("customerPortal.activeBuyers")} value={dashboard.active_buyers} />
                <KpiCard label={t("customerPortal.opportunities")} value={dashboard.active_opportunities} />
                <KpiCard label={t("customerPortal.openDeals")} value={dashboard.open_deals} />
                <KpiCard label={t("customerPortal.sectionProposals")} value={dashboard.proposals} />
                <KpiCard label={t("customerPortal.profilePct")} value={`${dashboard.profile_completeness}%`} icon={Building2} iconClassName="bg-accent-cyan/10 text-accent-cyan" />
                <KpiCard label={t("customerPortal.plan")} value={dashboard.current_plan || t("customerPortal.free")} />
              </div>
              <div className="card p-4 space-y-2">
                <p className="text-sm font-semibold text-gray-900">{t("customerPortal.revenueSummary")}</p>
                <div className="grid sm:grid-cols-4 gap-3 text-sm">
                  <div>
                    <p className="text-[10px] text-gray-400">{t("customerPortal.totalRevenue")}</p>
                    <p className="font-semibold tabular-nums">
                      {fmtMoney(dashboard.revenue_summary.total_revenue)}{" "}
                      {dashboard.revenue_summary.currency}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-400">{t("customerPortal.dealsWon")}</p>
                    <p className="font-semibold tabular-nums">{dashboard.revenue_summary.deals_won}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-400">{t("customerPortal.avgDealSize")}</p>
                    <p className="font-semibold tabular-nums">
                      {fmtMoney(dashboard.revenue_summary.avg_deal_size)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-gray-400">{t("customerPortal.conversion")}</p>
                    <p className="font-semibold tabular-nums">
                      {(dashboard.revenue_summary.conversion_rate * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>
              </div>
              <div className="card p-4 text-sm text-gray-600">
                <p>
                  <span className="font-medium text-gray-900">{t("customerPortal.subscription")}</span>{" "}
                  {dashboard.subscription_status || "none"} · Tenant status: {dashboard.tenant.tenant_status}
                </p>
              </div>
            </div>
          )}
        </>
      )}

      {section === "opportunities" && (
        <>
          {oppsLoading && <LoadingState message={t("customerPortal.loadingOpportunities")} />}
          {oppsError && (
            <ErrorState
              message={oppsErr instanceof Error ? oppsErr.message : "Failed to load opportunities"}
              onRetry={() => refetchOpps()}
            />
          )}
          {opportunities && (
            <div className="space-y-6">
              <PartialErrorsBanner errors={opportunities.errors} />
              <section className="card p-4 space-y-3">
                <p className="text-sm font-semibold text-gray-900">{t("nav.buyerAcquisition")}</p>
                <OpportunityTable items={opportunities.buyer_acquisition} emptyLabel={t("customerPortal.emptyAcquisition")} />
              </section>
              <section className="card p-4 space-y-3">
                <p className="text-sm font-semibold text-gray-900">{t("nav.marketplace")}</p>
                <OpportunityTable items={opportunities.marketplace} emptyLabel={t("customerPortal.emptyMarketplace")} />
              </section>
              <section className="card p-4 space-y-3">
                <p className="text-sm font-semibold text-gray-900">{t("nav.buyerNetwork")}</p>
                <OpportunityTable items={opportunities.buyer_network} emptyLabel={t("common.nothingHere")} />
              </section>
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
            <div className="card p-4 space-y-3">
              <PartialErrorsBanner errors={deals.errors} />
              {(deals.items as CustomerPortalV2DealItem[]).length === 0 ? (
                <EmptyState message={t("customerPortal.emptyDeals")} />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-[10px] uppercase text-gray-400 border-b">
                        <th className="py-2 pr-3">{t("customerPortal.colDeal")}</th>
                        <th className="py-2 pr-3">{t("customerPortal.colBuyer")}</th>
                        <th className="py-2 pr-3">{t("customerPortal.colStage")}</th>
                        <th className="py-2 pr-3">{t("customerPortal.colRisk")}</th>
                        <th className="py-2 pr-3">{t("customerPortal.colClosePct")}</th>
                        <th className="py-2">{t("customerPortal.colValue")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {deals.items.map((row) => (
                        <tr key={row.deal_id} className="border-b border-gray-50">
                          <td className="py-2.5 pr-3 font-medium">{row.deal_name}</td>
                          <td className="py-2.5 pr-3">{row.buyer || "—"}</td>
                          <td className="py-2.5 pr-3 capitalize">{row.stage}</td>
                          <td className="py-2.5 pr-3">
                            <span
                              className={cn(
                                "text-[10px] px-2 py-0.5 rounded border font-medium",
                                RISK_STYLES[row.risk_level] || RISK_STYLES.healthy,
                              )}
                            >
                              {row.risk_level}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 tabular-nums">
                            {(row.close_probability > 1
                              ? row.close_probability
                              : row.close_probability * 100
                            ).toFixed(0)}
                            %
                          </td>
                          <td className="py-2.5 tabular-nums">
                            {fmtMoney(row.estimated_value)} {row.currency}
                          </td>
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
            <div className="card p-4">
              {(proposals.items as CustomerPortalV2ProposalItem[]).length === 0 ? (
                <EmptyState message={t("customerPortal.emptyProposals")} />
              ) : (
                <ul className="divide-y divide-gray-50">
                  {proposals.items.map((p) => (
                    <li key={p.proposal_id} className="py-3 flex flex-wrap justify-between gap-2">
                      <div>
                        <p className="font-medium text-gray-900">{p.proposal_title}</p>
                        <p className="text-xs text-gray-500">
                          {p.buyer || "—"} · {p.status}
                        </p>
                      </div>
                      <div className="text-right text-sm">
                        <p className="font-semibold tabular-nums">{fmtMoney(p.estimated_value)}</p>
                        <p className="text-[10px] text-gray-400">
                          {p.last_updated ? format(parseISO(p.last_updated), "MMM d, yyyy") : "—"}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
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
                <div className="card p-4">
                  <p className="text-sm font-semibold text-gray-900 mb-2">Revenue attribution</p>
                  <p className="text-2xl font-semibold tabular-nums">
                    {fmtMoney(reports.revenue_attribution.total_revenue)}{" "}
                    {reports.revenue_attribution.currency}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {reports.revenue_attribution.deals_won} deals won
                  </p>
                </div>
                <div className="card p-4">
                  <p className="text-sm font-semibold text-gray-900 mb-2">Marketplace performance</p>
                  <p className="text-sm text-gray-600">
                    Open: {reports.marketplace_performance.open_opportunities} · Visibility:{" "}
                    {reports.marketplace_performance.visibility_score}
                  </p>
                </div>
              </div>
              {reports.revenue_forecast.length > 0 && (
                <div className="card p-4">
                  <p className="text-sm font-semibold text-gray-900 mb-2">
                    Revenue forecast ({reports.forecast_confidence})
                  </p>
                  <ul className="text-sm space-y-1">
                    {reports.revenue_forecast.map((f, i) => (
                      <li key={i} className="flex justify-between">
                        <span>{f.period || "Period"}</span>
                        <span className="tabular-nums">{fmtMoney(f.expected_case)} {f.currency}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {reports.buyer_performance.length > 0 && (
                <div className="card p-4">
                  <p className="text-sm font-semibold text-gray-900 mb-2">Buyer performance</p>
                  <ul className="text-sm divide-y divide-gray-50">
                    {reports.buyer_performance.map((b, i) => (
                      <li key={i} className="py-2 flex justify-between">
                        <span>{b.name}</span>
                        <span className="tabular-nums">Score {b.buyer_score}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
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
              <div className="grid sm:grid-cols-3 gap-3">
                <KpiCard label="Plan" value={billing.current_plan || "Free"} />
                <KpiCard label="Status" value={billing.subscription_status || "—"} />
                <KpiCard label="Monthly" value={`$${billing.monthly_price}`} />
              </div>
              {billing.invoice_summary.length > 0 && (
                <div className="card p-4">
                  <p className="text-sm font-semibold text-gray-900 mb-2">Recent invoices</p>
                  <ul className="text-sm divide-y divide-gray-50">
                    {billing.invoice_summary.map((inv) => (
                      <li key={inv.invoice_id} className="py-2 flex justify-between">
                        <span>
                          {inv.invoice_number || inv.invoice_id.slice(0, 8)} · {inv.status}
                        </span>
                        <span className="tabular-nums">
                          {fmtMoney(inv.amount)} {inv.currency}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {section === "factory-snapshot" && (
        <>
          {snapshotLoading && <LoadingState message="Loading factory snapshot…" />}
          {snapshotError && (
            <ErrorState
              message={snapshotErr instanceof Error ? snapshotErr.message : "Failed to load snapshot"}
              onRetry={() => refetchSnapshot()}
            />
          )}
          {factorySnapshot && (
            <div className="space-y-4">
              <PartialErrorsBanner errors={factorySnapshot.errors} />
              <div className="grid sm:grid-cols-4 gap-3">
                <KpiCard label="Profile score" value={factorySnapshot.profile_score} />
                <KpiCard label="Products" value={factorySnapshot.products_count} />
                <KpiCard label="Certificates" value={factorySnapshot.certificates_count} />
                <KpiCard label="Verification" value={factorySnapshot.verification_status} />
              </div>
              <div className="card p-4">
                <p className="text-sm font-semibold text-gray-900 mb-2 flex items-center gap-1.5">
                  <Building2 size={16} className="text-teal-600" />
                  Company profile
                </p>
                <p className="text-sm text-gray-700">
                  {(factorySnapshot.company_profile as { company_name?: string }).company_name ||
                    factorySnapshot.tenant.company_name}
                </p>
                {(factorySnapshot.company_profile as { description?: string }).description && (
                  <p className="text-xs text-gray-500 mt-2 line-clamp-3">
                    {(factorySnapshot.company_profile as { description?: string }).description}
                  </p>
                )}
              </div>
              {factorySnapshot.export_markets.length > 0 && (
                <div className="card p-4">
                  <p className="text-sm font-semibold text-gray-900 mb-2">Export markets</p>
                  <ul className="text-sm grid sm:grid-cols-2 gap-2">
                    {factorySnapshot.export_markets.map((m, i) => (
                      <li key={i} className="rounded border border-gray-100 px-3 py-2">
                        {m.country} · score {m.market_score} · {m.opportunities} opps
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <Link href="/factory-platform" className="text-xs text-brand-700 hover:underline">
                Open full Factory Platform →
              </Link>
            </div>
          )}
        </>
      )}
    </PageShell>
  );
}
