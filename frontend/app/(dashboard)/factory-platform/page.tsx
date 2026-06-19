"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Briefcase,
  Building2,
  Factory,
  Image,
  LayoutDashboard,
  Lightbulb,
  Package,
  Plus,
  Sparkles,
  Target,
  Trash2,
  TrendingUp,
  Users,
  Store,
  Network,
  Layers,
  Award,
  Globe2,
  ShieldCheck,
  Gauge,
  ClipboardList,
  Clapperboard,
  CircleDollarSign,
} from "lucide-react";
import {
  buyerIntelligenceApi,
  buyerAcquisitionApi,
  buyerAcquisitionEngineApi,
  revenueEngineApi,
  buyerNetworkApi,
  dealRiskApi,
  factoryPlatformApi,
  customerPortalV2Api,
  firstPilotClientApi,
  marketplaceApi,
  FactoryPlatformWorkspace,
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
  KpiCard,
  PageHeader,
  PageShell,
  ScoreCard,
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

type Section =
  | "performance"
  | "company-profile"
  | "catalog"
  | "certificates"
  | "export-markets"
  | "media-center"
  | "buyer-opportunities"
  | "verification"
  | "profile-completeness"
  | "reports"
  | "buyer-acquisition"
  | "buyer-network"
  | "marketplace"
  | "deals";

const SECTIONS: { id: Section; labelKey: string; icon: typeof LayoutDashboard }[] = [
  { id: "performance", labelKey: "factory.sectionPerformance", icon: Gauge },
  { id: "company-profile", labelKey: "factory.sectionCompanyProfile", icon: Building2 },
  { id: "profile-completeness", labelKey: "factory.sectionProfileCompleteness", icon: ClipboardList },
  { id: "media-center", labelKey: "factory.sectionMediaCenter", icon: Image },
  { id: "catalog", labelKey: "factory.sectionProductCatalog", icon: Package },
  { id: "certificates", labelKey: "factory.sectionCertificates", icon: Award },
  { id: "export-markets", labelKey: "factory.sectionExportMarkets", icon: Globe2 },
  { id: "buyer-opportunities", labelKey: "factory.sectionBuyerOpportunities", icon: Target },
  { id: "verification", labelKey: "factory.sectionVerification", icon: ShieldCheck },
  { id: "buyer-acquisition", labelKey: "factory.sectionBuyerAcquisition", icon: Layers },
  { id: "buyer-network", labelKey: "factory.sectionBuyerNetwork", icon: Network },
  { id: "marketplace", labelKey: "factory.sectionMarketplace", icon: Store },
  { id: "reports", labelKey: "factory.sectionReports", icon: TrendingUp },
];

const RISK_STYLES: Record<string, string> = {
  healthy: "bg-emerald-100 text-emerald-900 border-emerald-200",
  watchlist: "bg-amber-100 text-amber-900 border-amber-200",
  at_risk: "bg-orange-100 text-orange-900 border-orange-200",
  critical: "bg-red-100 text-red-900 border-red-300",
  stalled: "bg-gray-100 text-gray-800 border-gray-300",
  lost_probability_high: "bg-red-200 text-red-950 border-red-400",
};

const DEMO_JOURNEY_PREVIEW = [
  { step: 5, title: "Factory Platform", route: "/factory-platform" },
  { step: 6, title: "Buyer Acquisition", route: "/buyer-acquisition" },
  { step: 7, title: "Marketplace", route: "/marketplace" },
  { step: 8, title: "Executive Copilot", route: "/executive-copilot" },
  { step: 9, title: "Reports & Forecasts", route: "/revenue-forecast" },
] as const;

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

const EXPORT_MARKET_PRESETS = [
  "Uzbekistan",
  "Kazakhstan",
  "Kyrgyzstan",
  "Tajikistan",
  "Russia",
  "UAE",
  "Turkey",
];

const CERTIFICATE_TYPES = ["ISO", "CE", "SGS", "FDA", "HALAL"];

export default function FactoryPlatformPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [section, setSection] = useState<Section>("performance");
  const [tenantId, setTenantId] = useState<string>("");
  const [newProductName, setNewProductName] = useState("");
  const [newProductCategory, setNewProductCategory] = useState("");
  const [newCertName, setNewCertName] = useState("");
  const [newCertType, setNewCertType] = useState("ISO");
  const [newMarketCountry, setNewMarketCountry] = useState(EXPORT_MARKET_PRESETS[0]);
  const [mediaType, setMediaType] = useState<"image" | "video" | "pdf_catalog">("image");

  const { data: workspacesData, isLoading: wsLoading } = useQuery({
    queryKey: ["factory-platform-workspaces"],
    queryFn: () => factoryPlatformApi.workspaces().then((r) => r.data),
  });

  const workspaces = useMemo(
    () => (workspacesData?.items ?? []) as FactoryPlatformWorkspace[],
    [workspacesData],
  );

  useEffect(() => {
    if (!tenantId && workspaces.length > 0) {
      const stored =
        typeof window !== "undefined" ? localStorage.getItem("factoryPlatformTenantId") : null;
      const pick =
        stored && workspaces.some((w) => w.tenant_id === stored)
          ? stored
          : workspaces[0].tenant_id;
      setTenantId(pick);
    }
  }, [workspaces, tenantId]);

  useEffect(() => {
    if (tenantId && typeof window !== "undefined") {
      localStorage.setItem("factoryPlatformTenantId", tenantId);
    }
  }, [tenantId]);

  const selected = workspaces.find((w) => w.tenant_id === tenantId);
  const companyId = selected?.company_id;

  const { data: performance, isLoading: perfLoading, isError: perfError, error: perfErr, refetch: refetchPerf } =
    useQuery({
      queryKey: ["factory-platform-performance", tenantId],
      queryFn: () => factoryPlatformApi.performance(tenantId).then((r) => r.data),
      enabled: !!tenantId && section === "performance",
    });

  const { data: customerSnapshotPreview } = useQuery({
    queryKey: ["factory-platform-customer-snapshot-preview"],
    queryFn: () => customerPortalV2Api.factorySnapshot().then((r) => r.data),
    enabled: section === "performance",
    retry: 1,
  });

  const { data: profileV2, isLoading: profileLoading, isError: profileError, error: profileErr, refetch: refetchProfile } =
    useQuery({
      queryKey: ["factory-platform-profile-v2", tenantId],
      queryFn: () => factoryPlatformApi.profile(tenantId).then((r) => r.data),
      enabled: !!tenantId && section === "company-profile",
    });

  const { data: catalog, isLoading: catalogLoading, isError: catalogError, error: catalogErr, refetch: refetchCatalog } =
    useQuery({
      queryKey: ["factory-platform-catalog", tenantId],
      queryFn: () => factoryPlatformApi.catalog(tenantId).then((r) => r.data),
      enabled: !!tenantId && section === "catalog",
    });

  const { data: certificates, isLoading: certsLoading, refetch: refetchCertificates } = useQuery({
    queryKey: ["factory-platform-certificates", tenantId],
    queryFn: () => factoryPlatformApi.certificates(tenantId).then((r) => r.data),
    enabled: !!tenantId && section === "certificates",
  });

  const { data: exportMarkets, isLoading: marketsLoading, refetch: refetchExportMarkets } = useQuery({
    queryKey: ["factory-platform-export-markets", tenantId],
    queryFn: () => factoryPlatformApi.exportMarkets(tenantId).then((r) => r.data),
    enabled: !!tenantId && section === "export-markets",
  });

  const { data: profileScore, isLoading: scoreLoading, refetch: refetchScore } = useQuery({
    queryKey: ["factory-platform-profile-score", tenantId],
    queryFn: () => factoryPlatformApi.profileScore(tenantId).then((r) => r.data),
    enabled: !!tenantId && (section === "profile-completeness" || section === "performance"),
  });

  const { data: profileReadiness, isLoading: readinessLoading } = useQuery({
    queryKey: ["factory-platform-profile-readiness", tenantId],
    queryFn: () => factoryPlatformApi.profileReadiness(tenantId).then((r) => r.data),
    enabled: !!tenantId && section === "profile-completeness",
  });

  const { data: mediaData, isLoading: mediaLoading, refetch: refetchMedia } = useQuery({
    queryKey: ["factory-platform-media", tenantId],
    queryFn: () => factoryPlatformApi.media(tenantId).then((r) => r.data),
    enabled: !!tenantId && section === "media-center",
  });

  const invalidateReadiness = () => {
    queryClient.invalidateQueries({ queryKey: ["factory-platform-profile-score", tenantId] });
    queryClient.invalidateQueries({ queryKey: ["factory-platform-profile-readiness", tenantId] });
    queryClient.invalidateQueries({ queryKey: ["factory-platform-summary-widget"] });
  };

  const createProductMutation = useMutation({
    mutationFn: () =>
      factoryPlatformApi.createCatalogProduct(tenantId, {
        product_name: newProductName,
        category: newProductCategory || undefined,
        status: "active",
        export_available: true,
      }),
    onSuccess: () => {
      setNewProductName("");
      setNewProductCategory("");
      refetchCatalog();
      invalidateReadiness();
    },
  });

  const deleteProductMutation = useMutation({
    mutationFn: (productId: string) => factoryPlatformApi.deleteCatalogProduct(tenantId, productId),
    onSuccess: () => {
      refetchCatalog();
      invalidateReadiness();
    },
  });

  const createCertMutation = useMutation({
    mutationFn: () =>
      factoryPlatformApi.createCertificate(tenantId, {
        certificate_name: newCertName,
        certificate_type: newCertType,
      }),
    onSuccess: () => {
      setNewCertName("");
      refetchCertificates();
      invalidateReadiness();
    },
  });

  const deleteCertMutation = useMutation({
    mutationFn: (certificateId: string) =>
      factoryPlatformApi.deleteCertificate(tenantId, certificateId),
    onSuccess: () => {
      refetchCertificates();
      invalidateReadiness();
    },
  });

  const createMarketMutation = useMutation({
    mutationFn: () =>
      factoryPlatformApi.createExportMarket(tenantId, {
        country: newMarketCountry,
        market_score: 60,
      }),
    onSuccess: () => {
      refetchExportMarkets();
      invalidateReadiness();
    },
  });

  const deleteMarketMutation = useMutation({
    mutationFn: (marketId: string) => factoryPlatformApi.deleteExportMarket(tenantId, marketId),
    onSuccess: () => {
      refetchExportMarkets();
      invalidateReadiness();
    },
  });

  const uploadMediaMutation = useMutation({
    mutationFn: (formData: FormData) => factoryPlatformApi.uploadMedia(tenantId, formData),
    onSuccess: () => {
      refetchMedia();
      invalidateReadiness();
    },
  });

  const deleteMediaMutation = useMutation({
    mutationFn: (mediaId: string) => factoryPlatformApi.deleteMedia(tenantId, mediaId),
    onSuccess: () => {
      refetchMedia();
      invalidateReadiness();
    },
  });

  const { data: verification, isLoading: verLoading } = useQuery({
    queryKey: ["factory-platform-verification", tenantId],
    queryFn: () => factoryPlatformApi.verificationStatus(tenantId).then((r) => r.data),
    enabled: !!tenantId && section === "verification",
  });

  const { data: dashboard, isLoading: dashLoading, isError: dashError, error: dashErr, refetch: refetchDash } =
    useQuery({
      queryKey: ["factory-platform-dashboard", tenantId],
      queryFn: () => factoryPlatformApi.dashboard(tenantId).then((r) => r.data),
      enabled: !!tenantId && section === "performance",
    });

  const { data: engineOpportunities } = useQuery({
    queryKey: ["factory-platform-engine-opportunities", tenantId, companyId],
    queryFn: () =>
      buyerAcquisitionEngineApi
        .opportunities({ tenant_id: tenantId, client_id: companyId ?? undefined })
        .then((r) => r.data),
    enabled: !!tenantId && section === "performance",
  });

  const { data: revenuePerformance } = useQuery({
    queryKey: ["factory-platform-revenue-performance", tenantId, companyId],
    queryFn: () =>
      revenueEngineApi
        .revenuePerformancePanel({ tenant_id: tenantId, client_id: companyId ?? undefined })
        .then((r) => r.data),
    enabled: !!tenantId && section === "performance",
  });

  const { data: company, isLoading: companyLoading, isError: companyError, error: companyErr, refetch: refetchCompany } =
    useQuery({
      queryKey: ["factory-platform-company", tenantId],
      queryFn: () => factoryPlatformApi.company(tenantId).then((r) => r.data),
      enabled: false,
    });

  const { data: products, isLoading: productsLoading, isError: productsError, error: productsErr, refetch: refetchProducts } =
    useQuery({
      queryKey: ["factory-platform-products", tenantId],
      queryFn: () => factoryPlatformApi.products(tenantId, { limit: 100 }).then((r) => r.data),
      enabled: false,
    });

  const { data: buyers, isLoading: buyersLoading, isError: buyersError, error: buyersErr, refetch: refetchBuyers } =
    useQuery({
      queryKey: ["factory-platform-buyers", companyId],
      queryFn: () =>
        buyerIntelligenceApi.buyers({ client_id: companyId, limit: 100 }).then((r) => r.data),
      enabled: !!companyId && section === "buyer-opportunities",
    });

  const { data: marketplaceOpps, isLoading: marketplaceLoading } = useQuery({
    queryKey: ["factory-platform-marketplace", tenantId],
    queryFn: () =>
      marketplaceApi.topOpportunities({ tenant_id: tenantId, limit: 12 }).then((r) => r.data),
    enabled: !!tenantId && section === "marketplace",
  });

  const { data: acquisitionData, isLoading: acquisitionLoading } = useQuery({
    queryKey: ["factory-platform-buyer-acquisition", tenantId, companyId],
    queryFn: () =>
      buyerAcquisitionApi.insights({ tenant_id: tenantId, client_id: companyId, limit: 10 }).then((r) => r.data),
    enabled: !!tenantId && section === "buyer-acquisition",
  });

  const { data: acquisitionOverview } = useQuery({
    queryKey: ["factory-platform-buyer-acquisition-overview", tenantId, companyId],
    queryFn: () =>
      buyerAcquisitionApi.overview({ tenant_id: tenantId, client_id: companyId }).then((r) => r.data),
    enabled: !!tenantId && section === "buyer-acquisition",
  });

  const { data: networkInsights, isLoading: networkLoading } = useQuery({
    queryKey: ["factory-platform-buyer-network", tenantId],
    queryFn: () => buyerNetworkApi.insights({ tenant_id: tenantId, limit: 12 }).then((r) => r.data),
    enabled: !!tenantId && section === "buyer-network",
  });

  const { data: deals, isLoading: dealsLoading, isError: dealsError, error: dealsErr, refetch: refetchDeals } =
    useQuery({
      queryKey: ["factory-platform-deals", companyId],
      queryFn: () => dealRiskApi.deals({ client_id: companyId, limit: 100 }).then((r) => r.data),
      enabled: !!companyId && section === "deals",
    });

  const { data: reports, isLoading: reportsLoading, isError: reportsError, error: reportsErr, refetch: refetchReports } =
    useQuery({
      queryKey: ["factory-platform-reports", tenantId],
      queryFn: () => factoryPlatformApi.reports(tenantId).then((r) => r.data),
      enabled: !!tenantId && section === "reports",
    });

  const { data: insights, isLoading: insightsLoading, isError: insightsError, error: insightsErr, refetch: refetchInsights } =
    useQuery({
      queryKey: ["factory-platform-insights", tenantId],
      queryFn: () => factoryPlatformApi.insights(tenantId).then((r) => r.data),
      enabled: !!tenantId && section === "buyer-opportunities",
    });

  const { data: pilotReadinessIndicator } = useQuery({
    queryKey: ["first-pilot-client-factory-indicator", tenantId],
    queryFn: () => firstPilotClientApi.tenantIndicator(tenantId).then((r) => r.data),
    enabled: !!tenantId,
  });

  if (wsLoading) return <DashboardSkeleton />;

  return (
    <PageShell>
      <PageHeader
        title={t("factory.title")}
        subtitle={t("factory.subtitle")}
        icon={Factory}
        iconClassName="text-accent-gold"
        actions={
          workspaces.length > 0 ? (
            <select
              className="input max-w-xs text-sm"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
            >
              {workspaces.map((w) => (
                <option key={w.tenant_id} value={w.tenant_id}>
                  {w.company_name}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />

      {pilotReadinessIndicator && (
        <section className="card p-4 space-y-2 border-teal-100 bg-teal-50/20">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Gauge size={16} className="text-teal-600" />
              {t("factory.readinessIndicator")}
            </p>
            <Link href="/first-pilot-client" className="text-xs text-brand-700 hover:underline">
              {t("nav.firstPilotClient")} →
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs">
            <span className="text-2xl font-semibold tabular-nums text-teal-900">
              {pilotReadinessIndicator.readiness_score}%
            </span>
            <span className="text-gray-600">{pilotReadinessIndicator.message}</span>
            {pilotReadinessIndicator.is_pilot_client && (
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-medium",
                  pilotReadinessIndicator.launch_ready
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-amber-100 text-amber-800",
                )}
              >
                {pilotReadinessIndicator.launch_ready ? t("factory.launchReady") : t("factory.preparing")}
              </span>
            )}
          </div>
        </section>
      )}

      <section className="card p-4 space-y-2 border-indigo-100 bg-indigo-50/20">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Clapperboard size={16} className="text-indigo-600" />
            {t("factory.previewDemoJourney")}
          </p>
          <Link href="/pilot-demo" className="text-xs text-brand-700 hover:underline">
            {t("nav.pilotDemo")} →
          </Link>
        </div>
        <p className="text-xs text-gray-500">
          Factory-owner presentation path — tenant-facing stops after onboarding.
        </p>
        <ol className="flex flex-wrap gap-2 text-xs">
          {DEMO_JOURNEY_PREVIEW.map((s) => (
            <li key={s.step}>
              <Link
                href={s.route}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-1",
                  s.route === "/factory-platform"
                    ? "border-indigo-300 bg-indigo-100 text-indigo-900"
                    : "border-gray-200 bg-white text-gray-700 hover:border-indigo-200",
                )}
              >
                <span className="text-[10px] text-gray-400">#{s.step}</span>
                {s.title}
              </Link>
            </li>
          ))}
        </ol>
      </section>

      {workspaces.length === 0 ? (
        <EmptyState
          title={t("factory.noWorkspaces")}
          description="Approve a factory application, create client, create tenant, then return here."
          action={
            <Link href="/factory-partners" className="btn-primary text-sm">
              Factory Partners admin
            </Link>
          }
        />
      ) : (
        <>
          {selected && (
            <div className="card p-3 text-xs text-gray-600 flex flex-wrap gap-x-4 gap-y-1">
              <span>
                <strong>Company:</strong> {selected.company_name}
              </span>
              <span>
                <strong>Tenant:</strong> {selected.tenant_status}
              </span>
              {selected.has_portal && (
                <Link href="/customer-portal" className="text-brand-700 hover:underline">
                  Customer Portal linked
                </Link>
              )}
            </div>
          )}

          <div className="flex flex-wrap gap-2 p-1 rounded-2xl bg-slate-100/80 border border-gray-100">
            {SECTIONS.map(({ id, labelKey, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setSection(id)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all",
                  section === id
                    ? "bg-white border-brand-200 text-brand-800 shadow-sm"
                    : "bg-transparent border-transparent text-gray-600 hover:bg-white/60",
                )}
              >
                <Icon size={14} />
                {t(labelKey)}
              </button>
            ))}
          </div>

          {section === "performance" && (
            <>
              {(perfLoading || dashLoading) && <LoadingState message={t("factory.loadingPerformance")} />}
              {perfError && (
                <ErrorState
                  message={String((perfErr as Error)?.message ?? t("factory.loadPerformanceError"))}
                  onRetry={() => refetchPerf()}
                />
              )}
              {performance && (
                <div className="space-y-4">
                  <PartialErrorsBanner errors={performance.errors} />
                  {customerSnapshotPreview && (
                    <div className="card p-4 border-teal-100 bg-teal-50/30 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold text-gray-900">
                          Customer-facing factory snapshot (preview)
                        </p>
                        <Link href="/customer-portal-v2" className="text-xs text-brand-700 hover:underline">
                          View in Customer Portal v2 →
                        </Link>
                      </div>
                      <p className="text-xs text-gray-600">
                        Profile {customerSnapshotPreview.profile_score}% · Products{" "}
                        {customerSnapshotPreview.products_count} · Certificates{" "}
                        {customerSnapshotPreview.certificates_count} ·{" "}
                        {customerSnapshotPreview.verification_status}
                      </p>
                    </div>
                  )}
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                    <KpiCard label={t("factory.totalBuyers")} value={performance.total_buyers} />
                    <KpiCard label={t("factory.activeOpportunities")} value={performance.active_opportunities} />
                    <KpiCard label={t("factory.marketplaceVisibility")} value={performance.marketplace_visibility} />
                    <KpiCard label={t("factory.acquisitionScore")} value={performance.buyer_acquisition_score} />
                    <KpiCard label={t("factory.profileScore")} value={performance.profile_score} />
                  </div>
                  {dashboard && (
                    <>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <KpiCard label={t("factory.activeLeads")} value={dashboard.active_leads} />
                        <KpiCard label={t("factory.activeDeals")} value={dashboard.active_deals} />
                        <KpiCard label={t("factory.proposals")} value={dashboard.proposals_count} />
                        <KpiCard label={t("factory.totalBuyers")} value={dashboard.active_buyers} />
                      </div>
                      <div className="card p-4">
                        <h2 className="text-sm font-semibold text-gray-800 mb-2">{t("factory.revenueSummary")}</h2>
                        <p className="text-lg font-semibold tabular-nums">
                          {fmtMoney(dashboard.revenue_summary.total_revenue)}{" "}
                          {dashboard.revenue_summary.currency}
                        </p>
                      </div>
                    </>
                  )}
                  {revenuePerformance && (
                    <div className="card p-4 border-emerald-100 space-y-3">
                      <div className="flex items-center justify-between gap-2">
                        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                          <CircleDollarSign size={16} className="text-emerald-700" />
                          {t("factory.revenuePerformance")}
                        </h2>
                        <Link
                          href="/revenue-engine"
                          className="text-xs text-brand-700 hover:underline"
                        >
                          {t("factory.openRevenueEngine")}
                        </Link>
                      </div>
                      <div className="grid sm:grid-cols-4 gap-2 text-xs">
                        <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
                          <p className="text-gray-500">{t("revenue.pipelineValue")}</p>
                          <p className="font-semibold tabular-nums">
                            {fmtMoney(revenuePerformance.total_pipeline_value)}
                          </p>
                        </div>
                        <div className="rounded-lg border border-gray-100 px-2 py-2">
                          <p className="text-gray-500">{t("factory.forecast")}</p>
                          <p className="font-medium tabular-nums">
                            {fmtMoney(revenuePerformance.forecasted_revenue)}
                          </p>
                        </div>
                        <div className="rounded-lg border border-gray-100 px-2 py-2">
                          <p className="text-gray-500">{t("factory.won")}</p>
                          <p className="font-medium tabular-nums">
                            {fmtMoney(revenuePerformance.won_revenue)}
                          </p>
                        </div>
                        <div className="rounded-lg border border-gray-100 px-2 py-2">
                          <p className="text-gray-500">{t("revenue.activeDeals")}</p>
                          <p className="font-medium tabular-nums">{revenuePerformance.active_deals}</p>
                        </div>
                      </div>
                      {revenuePerformance.top_factory_name && (
                        <p className="text-xs text-gray-600">
                          Top factory: {revenuePerformance.top_factory_name} · pipeline{" "}
                          {fmtMoney(revenuePerformance.top_factory_pipeline)}
                        </p>
                      )}
                      <p className="text-[10px] text-gray-400">{revenuePerformance.safety_notice}</p>
                    </div>
                  )}
                  {engineOpportunities && engineOpportunities.buyer_opportunities.length > 0 && (
                    <div className="card p-4 border-cyan-100 space-y-3">
                      <div className="flex items-center justify-between gap-2">
                        <h2 className="text-sm font-semibold text-gray-900">
                          Top Buyer Opportunities
                        </h2>
                        <Link
                          href="/buyer-acquisition-engine"
                          className="text-xs text-brand-700 hover:underline"
                        >
                          {t("factory.openBuyerEngine")}
                        </Link>
                      </div>
                      <ul className="space-y-2 text-sm">
                        {engineOpportunities.buyer_opportunities.slice(0, 6).map((o) => (
                          <li
                            key={o.opportunity_id}
                            className="flex items-center justify-between gap-2 border-b border-gray-50 pb-2"
                          >
                            <div>
                              <p className="font-medium">{o.title}</p>
                              <p className="text-xs text-gray-500">
                                {[o.country, o.industry].filter(Boolean).join(" · ") || o.subtitle}
                              </p>
                            </div>
                            <span className="text-xs font-semibold tabular-nums text-cyan-800">
                              {o.score}
                            </span>
                          </li>
                        ))}
                      </ul>
                      <p className="text-[10px] text-gray-400">{engineOpportunities.safety_notice}</p>
                    </div>
                  )}
                  <p className="text-[10px] text-gray-400">{performance.safety_notice}</p>
                </div>
              )}
            </>
          )}

          {section === "company-profile" && (
            <>
              {profileLoading && <LoadingState message="Loading company profile…" />}
              {profileError && (
                <ErrorState
                  message={String((profileErr as Error)?.message ?? "Failed")}
                  onRetry={() => refetchProfile()}
                />
              )}
              {profileV2?.profile && (
                <div className="card p-4 space-y-4 text-sm">
                  <h2 className="font-semibold text-gray-900">{profileV2.profile.company_name}</h2>
                  {profileV2.profile.brand_name && (
                    <p className="text-gray-600">
                      <strong>Brand:</strong> {profileV2.profile.brand_name}
                    </p>
                  )}
                  <div className="grid sm:grid-cols-2 gap-3 text-gray-600">
                    {profileV2.profile.country && (
                      <p>
                        <strong>Country:</strong> {profileV2.profile.country}
                        {profileV2.profile.city ? `, ${profileV2.profile.city}` : ""}
                      </p>
                    )}
                    {profileV2.profile.address && (
                      <p>
                        <strong>Address:</strong> {profileV2.profile.address}
                      </p>
                    )}
                    {profileV2.profile.industry && (
                      <p>
                        <strong>Industry:</strong> {profileV2.profile.industry}
                      </p>
                    )}
                    {profileV2.profile.website && (
                      <p>
                        <strong>Website:</strong> {profileV2.profile.website}
                      </p>
                    )}
                    {profileV2.profile.contact_email && (
                      <p>
                        <strong>Email:</strong> {profileV2.profile.contact_email}
                      </p>
                    )}
                    {profileV2.profile.contact_phone && (
                      <p>
                        <strong>Phone:</strong> {profileV2.profile.contact_phone}
                      </p>
                    )}
                    {profileV2.profile.founded_year && (
                      <p>
                        <strong>Founded:</strong> {profileV2.profile.founded_year}
                      </p>
                    )}
                    {profileV2.profile.employee_count != null && (
                      <p>
                        <strong>Employees:</strong> {profileV2.profile.employee_count}
                      </p>
                    )}
                  </div>
                  {profileV2.profile.description && (
                    <p className="text-gray-600">{profileV2.profile.description}</p>
                  )}
                  <p className="text-[10px] text-gray-400">{profileV2.safety_notice}</p>
                </div>
              )}
            </>
          )}

          {section === "catalog" && (
            <>
              {catalogLoading && <LoadingState message="Loading product catalog…" />}
              {catalogError && (
                <ErrorState
                  message={String((catalogErr as Error)?.message ?? "Failed")}
                  onRetry={() => refetchCatalog()}
                />
              )}
              {catalog && (
                <div className="space-y-4">
                  <PartialErrorsBanner errors={catalog.errors} />
                  <div className="card p-4 space-y-3">
                    <p className="text-xs font-semibold text-gray-700">{t("factory.addProduct")}</p>
                    <div className="grid sm:grid-cols-3 gap-2">
                      <input
                        className="input text-sm"
                        placeholder={t("factory.productName")}
                        value={newProductName}
                        onChange={(e) => setNewProductName(e.target.value)}
                      />
                      <input
                        className="input text-sm"
                        placeholder={t("factory.category")}
                        value={newProductCategory}
                        onChange={(e) => setNewProductCategory(e.target.value)}
                      />
                      <button
                        type="button"
                        className="btn-primary text-sm flex items-center justify-center gap-1"
                        disabled={!newProductName || createProductMutation.isPending}
                        onClick={() => createProductMutation.mutate()}
                      >
                        <Plus size={14} /> {t("factory.createProduct")}
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="px-2 py-1 rounded bg-emerald-50 border border-emerald-200">
                      Active: {catalog.active_count}
                    </span>
                    <span className="px-2 py-1 rounded bg-gray-50 border border-gray-200">
                      Draft: {catalog.draft_count}
                    </span>
                    <span className="px-2 py-1 rounded bg-slate-50 border border-slate-200">
                      Archived: {catalog.archived_count}
                    </span>
                  </div>
                  <div className="card overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 text-left text-xs text-gray-500">
                        <tr>
                          <th className="p-2">{t("factory.colProduct")}</th>
                          <th className="p-2">{t("factory.category")}</th>
                          <th className="p-2">{t("factory.colMoqPrice")}</th>
                          <th className="p-2">{t("factory.colExport")}</th>
                          <th className="p-2">{t("factory.colStatus")}</th>
                          <th className="p-2 w-10" />
                        </tr>
                      </thead>
                      <tbody>
                        {catalog.items.map((p) => (
                          <tr key={p.product_id} className="border-t border-gray-100">
                            <td className="p-2">
                              <p className="font-medium">{p.product_name}</p>
                              {p.description && (
                                <p className="text-xs text-gray-500 truncate max-w-xs">{p.description}</p>
                              )}
                            </td>
                            <td className="p-2">{p.category ?? "—"}</td>
                            <td className="p-2 text-xs">
                              {p.moq != null ? `MOQ ${p.moq}` : "—"}
                              {p.price_min != null || p.price_max != null
                                ? ` · ${p.price_min ?? "?"}–${p.price_max ?? "?"} ${p.currency ?? "USD"}`
                                : ""}
                            </td>
                            <td className="p-2 text-xs">
                              {p.export_available === false ? "No" : "Yes"}
                            </td>
                            <td className="p-2 capitalize">{p.status}</td>
                            <td className="p-2">
                              <button
                                type="button"
                                className="text-red-600 hover:text-red-800"
                                onClick={() => deleteProductMutation.mutate(p.product_id)}
                              >
                                <Trash2 size={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {catalog.items.length === 0 && (
                      <p className="p-4 text-sm text-gray-500">No catalog products yet.</p>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {section === "certificates" && (
            <>
              {certsLoading && <LoadingState message="Loading certificates…" />}
              {certificates && (
                <div className="space-y-4">
                  <div className="card p-4 space-y-3">
                    <p className="text-xs font-semibold text-gray-700">Add certificate</p>
                    <div className="grid sm:grid-cols-3 gap-2">
                      <input
                        className="input text-sm"
                        placeholder="Certificate name"
                        value={newCertName}
                        onChange={(e) => setNewCertName(e.target.value)}
                      />
                      <select
                        className="input text-sm"
                        value={newCertType}
                        onChange={(e) => setNewCertType(e.target.value)}
                      >
                        {CERTIFICATE_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="btn-primary text-sm flex items-center justify-center gap-1"
                        disabled={!newCertName || createCertMutation.isPending}
                        onClick={() => createCertMutation.mutate()}
                      >
                        <Plus size={14} /> Add certificate
                      </button>
                    </div>
                  </div>
                  <div className="flex gap-2 text-xs">
                    <span className="px-2 py-1 rounded bg-emerald-50 border border-emerald-200">
                      Valid: {certificates.valid_count}
                    </span>
                    <span className="px-2 py-1 rounded bg-red-50 border border-red-200">
                      Expired: {certificates.expired_count}
                    </span>
                  </div>
                  <div className="card overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 text-left text-xs text-gray-500">
                        <tr>
                          <th className="p-2">Certificate</th>
                          <th className="p-2">Type</th>
                          <th className="p-2">Number</th>
                          <th className="p-2">Issue / Expiry</th>
                          <th className="p-2 w-10" />
                        </tr>
                      </thead>
                      <tbody>
                        {certificates.items.map((c) => (
                          <tr key={c.certificate_id} className="border-t border-gray-100">
                            <td className="p-2">{c.certificate_name}</td>
                            <td className="p-2">{c.certificate_type}</td>
                            <td className="p-2">{c.certificate_number ?? "—"}</td>
                            <td className="p-2 text-xs">
                              {c.issue_date ?? "—"} → {c.expiry_date ?? "—"}
                              {c.is_expired && (
                                <span className="ml-1 text-[10px] text-red-600">expired</span>
                              )}
                            </td>
                            <td className="p-2">
                              <button
                                type="button"
                                className="text-red-600 hover:text-red-800"
                                onClick={() => deleteCertMutation.mutate(c.certificate_id)}
                              >
                                <Trash2 size={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}

          {section === "export-markets" && (
            <>
              {marketsLoading && <LoadingState message="Loading export markets…" />}
              {exportMarkets && (
                <div className="space-y-4">
                  <PartialErrorsBanner errors={exportMarkets.errors} />
                  <div className="card p-4 space-y-3">
                    <p className="text-xs font-semibold text-gray-700">Add export market</p>
                    <div className="grid sm:grid-cols-2 gap-2">
                      <select
                        className="input text-sm"
                        value={newMarketCountry}
                        onChange={(e) => setNewMarketCountry(e.target.value)}
                      >
                        {EXPORT_MARKET_PRESETS.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="btn-primary text-sm flex items-center justify-center gap-1"
                        disabled={createMarketMutation.isPending}
                        onClick={() => createMarketMutation.mutate()}
                      >
                        <Plus size={14} /> Add market
                      </button>
                    </div>
                  </div>
                  <div className="card overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 text-left text-xs text-gray-500">
                        <tr>
                          <th className="p-2">Country</th>
                          <th className="p-2">Market score</th>
                          <th className="p-2">Active buyers</th>
                          <th className="p-2">Opportunities</th>
                          <th className="p-2 w-10" />
                        </tr>
                      </thead>
                      <tbody>
                        {exportMarkets.items.map((m) => (
                          <tr key={m.market_id} className="border-t border-gray-100">
                            <td className="p-2 font-medium">{m.country}</td>
                            <td className="p-2 tabular-nums">{m.market_score}</td>
                            <td className="p-2 tabular-nums">{m.active_buyers}</td>
                            <td className="p-2 tabular-nums">{m.opportunities}</td>
                            <td className="p-2">
                              <button
                                type="button"
                                className="text-red-600 hover:text-red-800"
                                onClick={() => deleteMarketMutation.mutate(m.market_id)}
                              >
                                <Trash2 size={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}

          {section === "media-center" && (
            <>
              {mediaLoading && <LoadingState message="Loading media center…" />}
              {mediaData && (
                <div className="space-y-4">
                  <p className="text-xs text-gray-500">
                    Reusable by Customer Portal, Buyer Acquisition, and SMM modules.
                  </p>
                  <div className="card p-4 space-y-3">
                    <p className="text-xs font-semibold text-gray-700">Upload media</p>
                    <div className="flex flex-wrap gap-2 items-center">
                      <select
                        className="input text-sm max-w-[160px]"
                        value={mediaType}
                        onChange={(e) =>
                          setMediaType(e.target.value as "image" | "video" | "pdf_catalog")
                        }
                      >
                        <option value="image">Factory photo</option>
                        <option value="video">Factory video</option>
                        <option value="pdf_catalog">PDF catalog</option>
                      </select>
                      <input
                        type="file"
                        className="text-sm"
                        accept={
                          mediaType === "pdf_catalog"
                            ? "application/pdf"
                            : mediaType === "video"
                              ? "video/*"
                              : "image/*"
                        }
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          const fd = new FormData();
                          fd.append("file", file);
                          fd.append("media_type", mediaType);
                          fd.append("title", file.name);
                          uploadMediaMutation.mutate(fd);
                          e.target.value = "";
                        }}
                      />
                    </div>
                    <div className="flex gap-2 text-xs">
                      <span className="px-2 py-1 rounded bg-blue-50 border border-blue-200">
                        Images: {mediaData.image_count}
                      </span>
                      <span className="px-2 py-1 rounded bg-violet-50 border border-violet-200">
                        Videos: {mediaData.video_count}
                      </span>
                      <span className="px-2 py-1 rounded bg-amber-50 border border-amber-200">
                        PDFs: {mediaData.pdf_count}
                      </span>
                    </div>
                  </div>
                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {mediaData.items.map((m) => (
                      <div key={m.media_id} className="card p-3 space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <p className="text-sm font-medium">{m.title ?? m.original_filename}</p>
                            <p className="text-[10px] text-gray-500 capitalize">{m.media_type.replace(/_/g, " ")}</p>
                          </div>
                          <button
                            type="button"
                            className="text-red-600"
                            onClick={() => deleteMediaMutation.mutate(m.media_id)}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                        {m.url && m.media_type === "image" && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={m.url} alt={m.title ?? ""} className="rounded max-h-32 object-cover w-full" />
                        )}
                        {m.url && (
                          <a href={m.url} target="_blank" rel="noreferrer" className="text-xs text-brand-700 hover:underline">
                            Open file
                          </a>
                        )}
                        <p className="text-[10px] text-gray-400">
                          Modules: {m.reusable_modules.join(", ")}
                        </p>
                      </div>
                    ))}
                  </div>
                  {mediaData.items.length === 0 && (
                    <p className="text-sm text-gray-500">No media uploaded yet.</p>
                  )}
                </div>
              )}
            </>
          )}

          {section === "verification" && (
            <>
              {verLoading && <LoadingState message="Loading verification status…" />}
              {verification && (
                <div className="card p-4 space-y-4">
                  <div className="flex items-center gap-3">
                    <p className="text-sm font-semibold capitalize">
                      Status: {verification.verification_status.replace(/_/g, " ")}
                    </p>
                    <span className="text-xs text-gray-500">
                      Profile score {verification.profile_score}/100
                    </span>
                  </div>
                  {verification.requirements_met.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-emerald-700 mb-1">Requirements met</p>
                      <ul className="text-sm text-gray-700 list-disc pl-5">
                        {verification.requirements_met.map((r) => (
                          <li key={r}>{r.replace(/_/g, " ")}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {verification.requirements_missing.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-amber-700 mb-1">Still needed</p>
                      <ul className="text-sm text-gray-700 list-disc pl-5">
                        {verification.requirements_missing.map((r) => (
                          <li key={r}>{r.replace(/_/g, " ")}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className="text-[10px] text-gray-400">{verification.safety_notice}</p>
                </div>
              )}
            </>
          )}

          {section === "profile-completeness" && (
            <>
              {(scoreLoading || readinessLoading) && <LoadingState message="Loading profile score…" />}
              {(profileScore || profileReadiness) && (
                <div className="space-y-4">
                  <ScoreCard
                    title={t("factory.profileCompletenessTitle")}
                    score={(profileReadiness ?? profileScore)!.profile_score}
                    subtitle={t("factory.profileCompletenessSubtitle")}
                    metrics={[
                      { label: "Company profile", value: `${(profileReadiness ?? profileScore)!.components.profile}/45` },
                      { label: "Products", value: `${(profileReadiness ?? profileScore)!.components.products}/15` },
                      { label: "Certificates", value: `${(profileReadiness ?? profileScore)!.components.certificates}/15` },
                      { label: "Export markets", value: `${(profileReadiness ?? profileScore)!.components.export_markets}/15` },
                    ]}
                  />
                  {profileReadiness?.breakdown && profileReadiness.breakdown.length > 0 && (
                    <div className="card p-4 space-y-3">
                      <p className="text-xs font-medium text-gray-500">Readiness breakdown</p>
                      <div className="space-y-2">
                        {profileReadiness.breakdown.map((item) => (
                          <div key={item.key} className="flex items-center justify-between gap-2 text-sm">
                            <span className={item.complete ? "text-emerald-800" : "text-gray-700"}>
                              {item.label}
                            </span>
                            <span className="tabular-nums text-xs text-gray-500">
                              {item.score}/{item.max_score}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {(profileReadiness?.recommended_actions ?? profileScore?.recommended_actions ?? []).length > 0 && (
                    <div className="card p-4">
                      <p className="text-xs font-medium text-gray-500 mb-2">Recommended actions</p>
                      <ul className="text-sm text-gray-700 list-disc pl-5 space-y-1">
                        {(profileReadiness?.recommended_actions ?? profileScore?.recommended_actions ?? []).map(
                          (action) => (
                            <li key={action}>{action}</li>
                          ),
                        )}
                      </ul>
                    </div>
                  )}
                  {(profileReadiness?.missing_items ?? profileScore?.missing_items ?? []).length > 0 && (
                    <div className="card p-4">
                      <p className="text-xs font-medium text-gray-500 mb-2">Missing items</p>
                      <ul className="text-sm text-gray-700 list-disc pl-5">
                        {(profileReadiness?.missing_items ?? profileScore?.missing_items ?? []).map((item) => (
                          <li key={item}>{item.replace(/_/g, " ")}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {section === "buyer-opportunities" && (
            <>
              {(buyersLoading || insightsLoading) && <LoadingState message="Loading buyer opportunities…" />}
              {buyersError && (
                <ErrorState
                  message={String((buyersErr as Error)?.message ?? "Failed")}
                  onRetry={() => refetchBuyers()}
                />
              )}
              <div className="space-y-4">
                {insights && (
                  <>
                    <PartialErrorsBanner errors={insights.errors} />
                    {insights.recommended_actions.length > 0 && (
                      <div className="card p-4">
                        <h3 className="text-sm font-semibold flex items-center gap-1 mb-2">
                          <Lightbulb size={14} className="text-amber-600" /> Recommended actions
                        </h3>
                        <ul className="text-sm space-y-2">
                          {insights.recommended_actions.slice(0, 6).map((a, i) => (
                            <li key={i}>{a.action}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}
                {buyers && (
                  <div className="card overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 text-left text-xs text-gray-500">
                        <tr>
                          <th className="p-2">Buyer</th>
                          <th className="p-2">Score</th>
                          <th className="p-2">Classification</th>
                          <th className="p-2">Risk</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(buyers.items ?? []).map((b) => (
                          <tr key={b.buyer_id} className="border-t border-gray-100">
                            <td className="p-2">{b.name}</td>
                            <td className="p-2 tabular-nums">{b.buyer_score}</td>
                            <td className="p-2">{b.classification?.replace(/_/g, " ")}</td>
                            <td className="p-2">
                              <span
                                className={cn(
                                  "px-1.5 py-0.5 rounded text-[10px] border",
                                  RISK_STYLES[b.risk_level] ?? "bg-gray-50",
                                )}
                              >
                                {b.risk_level}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="p-2 border-t flex gap-3">
                      <Link href="/buyer-intelligence" className="text-xs text-brand-700 hover:underline">
                        Buyer Intelligence →
                      </Link>
                      <Link href="/buyer-acquisition" className="text-xs text-brand-700 hover:underline">
                        Buyer Acquisition →
                      </Link>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {section === "buyer-acquisition" && (
            <>
              {acquisitionLoading && <LoadingState message="Loading buyer acquisition…" />}
              {acquisitionOverview && acquisitionData && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm text-gray-600">
                      Unified buyer acquisition — Discovery, Network, Marketplace, Intelligence.
                    </p>
                    <Link href="/buyer-acquisition" className="text-xs text-brand-700 hover:underline">
                      {t("executive.openBuyerAcquisition")}
                    </Link>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                    <KpiCard label={t("factory.totalBuyers")} value={acquisitionOverview.total_buyers} />
                    <KpiCard label={t("nav.buyerNetwork")} value={acquisitionOverview.strategic_buyers} />
                    <KpiCard label={t("factory.activeOpportunities")} value={acquisitionOverview.high_potential_buyers} />
                    <KpiCard label={t("nav.marketplace")} value={acquisitionOverview.marketplace_opportunities} />
                    <KpiCard label={t("factory.acquisitionScore")} value={acquisitionOverview.network_opportunities} />
                  </div>
                  <div className="card p-4">
                    <p className="text-xs font-semibold mb-2">Top unified buyers</p>
                    <ul className="text-xs space-y-1">
                      {(acquisitionData.top_buyers ?? []).map((b) => (
                        <li key={`${b.rank}-${b.company_name}`}>
                          {b.company_name} · score {b.score}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <p className="text-[10px] text-gray-400">{acquisitionOverview.safety_notice}</p>
                </div>
              )}
            </>
          )}

          {section === "buyer-network" && (
            <>
              {networkLoading && <LoadingState message="Loading buyer network…" />}
              {networkInsights && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm text-gray-600">
                      Global buyer network — relationship mapping and intelligence only.
                    </p>
                    <Link href="/buyer-network" className="text-xs text-brand-700 hover:underline">
                      {t("nav.buyerNetwork")} →
                    </Link>
                  </div>
                  <div className="grid md:grid-cols-2 gap-4">
                    <div className="card p-4">
                      <p className="text-xs font-semibold mb-2">Strongest buyers</p>
                      <ul className="text-xs space-y-1">
                        {(networkInsights.strongest_buyers ?? []).map((b) => (
                          <li key={b.buyer_id}>
                            {b.company_name} · strength {b.network_strength}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="card p-4">
                      <p className="text-xs font-semibold mb-2">Strategic buyers</p>
                      <ul className="text-xs space-y-1">
                        {(networkInsights.strategic_buyers ?? []).map((b) => (
                          <li key={b.buyer_id}>{b.company_name}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {section === "marketplace" && (
            <>
              {marketplaceLoading && <LoadingState message="Loading marketplace…" />}
              {marketplaceOpps && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm text-gray-600">
                      Buyer opportunity exchange — manual interest and claims only.
                    </p>
                    <Link href="/marketplace" className="text-xs text-brand-700 hover:underline">
                      {t("nav.marketplace")} →
                    </Link>
                  </div>
                  <div className="grid md:grid-cols-3 gap-4">
                    {(["best_opportunities", "newest_opportunities", "strategic_opportunities"] as const).map(
                      (key) => (
                        <div key={key} className="card p-4">
                          <p className="text-xs font-semibold capitalize mb-2">
                            {key.replace(/_/g, " ")}
                          </p>
                          <ul className="text-xs space-y-1">
                            {(marketplaceOpps[key] ?? []).map((o) => (
                              <li key={o.opportunity_id}>
                                <span className="font-medium">{o.title}</span>
                                <span className="text-gray-500"> · {o.rank_score}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {section === "reports" && (
            <>
              {reportsLoading && <LoadingState message="Loading reports…" />}
              {reportsError && (
                <ErrorState
                  message={String((reportsErr as Error)?.message ?? "Failed")}
                  onRetry={() => refetchReports()}
                />
              )}
              {reports && (
                <div className="space-y-4">
                  <PartialErrorsBanner errors={reports.errors} />
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div className="card p-4">
                      <h3 className="text-sm font-semibold flex items-center gap-1">
                        <TrendingUp size={14} /> Revenue attribution
                      </h3>
                      <p className="text-lg font-semibold mt-2 tabular-nums">
                        {fmtMoney(reports.revenue_attribution.total_revenue)}{" "}
                        {reports.revenue_attribution.currency}
                      </p>
                    </div>
                    <div className="card p-4">
                      <h3 className="text-sm font-semibold">Revenue forecast</h3>
                      <p className="text-xs text-gray-500 mt-1">
                        Confidence: {reports.forecast_confidence}
                      </p>
                      <ul className="mt-2 text-xs space-y-1">
                        {reports.revenue_forecast.map((f) => (
                          <li key={f.period}>
                            {f.period}: expected {fmtMoney(f.expected_case)} {f.currency}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                  {reports.top_buyers.length > 0 && (
                    <div className="card p-4">
                      <h3 className="text-sm font-semibold mb-2">Top buyers</h3>
                      <ul className="text-sm space-y-1">
                        {reports.top_buyers.map((b) => (
                          <li key={b.buyer_id} className="flex justify-between">
                            <span>{b.name}</span>
                            <span className="text-gray-500">Score {b.buyer_score}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {(reports.discovery_opportunities?.length ?? 0) > 0 && (
                    <div className="card p-4">
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <h3 className="text-sm font-semibold">Buyer Discovery</h3>
                        <Link href="/buyer-discovery" className="text-xs text-brand-700 hover:underline">
                          Open →
                        </Link>
                      </div>
                      <ul className="text-sm space-y-1">
                        {reports.discovery_opportunities!.map((b) => (
                          <li key={b.buyer_id} className="flex justify-between gap-2">
                            <span>{b.company_name}</span>
                            <span className="text-gray-500">Score {b.opportunity_score}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {reports.high_risk_deals.length > 0 && (
                    <div className="card p-4">
                      <h3 className="text-sm font-semibold mb-2">High-risk deals</h3>
                      <ul className="text-sm space-y-1">
                        {reports.high_risk_deals.map((d) => (
                          <li key={d.deal_id} className="flex justify-between gap-2">
                            <span>{d.title}</span>
                            <span className={cn("text-[10px] px-1 rounded", RISK_STYLES[d.risk_level])}>
                              {d.risk_level}
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

        </>
      )}
    </PageShell>
  );
}
