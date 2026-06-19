"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Inbox,
  ListTodo,
  FileText,
  Briefcase,
  CreditCard,
  Sparkles,
  Loader2,
  AlertTriangle,
  TrendingUp,
  ArrowRight,
  Lightbulb,
  Bot,
  Search,
  Brain,
  Activity,
  ClipboardCheck,
  Workflow,
  CircleDollarSign,
  Crown,
  Building2,
  Factory,
  Store,
  Network,
  Layers,
  Target,
  Rocket,
  Cloud,
  Presentation,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  dashboardApi,
  DashboardAiSummary,
  executiveCopilotApi,
  leadIntelligenceApi,
  revenueAttributionApi,
  salesAgentApi,
  salesManagerApi,
  salesDepartmentV3Api,
  multiAgentTeamApi,
  revenueForecastApi,
  buyerIntelligenceApi,
  buyerAcquisitionApi,
  buyerAcquisitionEngineApi,
  revenueEngineApi,
  dealRoomV2Api,
  buyerDiscoveryApi,
  buyerNetworkApi,
  marketplaceApi,
  dealRiskApi,
  factoryPartnerPortalApi,
  pilotOnboardingApi,
  pilotLaunchApi,
  pilotDemoApi,
  pilotSalesDemoApi,
  pilotLaunchValidationApi,
  firstPilotClientApi,
  productionDeploymentApi,
  realFactoryPilotApi,
  factoryPlatformApi,
  customerPortalApi,
  customerPortalV2Api,
  subscriptionBillingApi,
  salesWorkflowApi,
  systemApi,
  auditApi,
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
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";
import { translateSystemStatus, translateHealthStatus } from "@/lib/uiLabels";
import { useCleanupWhenFetched } from "@/lib/useDocumentInteractionCleanup";
import {
  DASHBOARD_CORE_QUERY_OPTIONS,
  DASHBOARD_OPTIONAL_WIDGET_OPTIONS,
} from "@/lib/dashboard-query-options";
import { isOverviewLoading } from "@/lib/overview-query-options";
import { useDashboardAuthGates } from "@/lib/useDashboardAuthGates";
import { useDashboardOverlayCleanup } from "@/lib/useDashboardOverlayCleanup";
import { DashboardWidgetUnavailable } from "@/components/dashboard/DashboardWidgetUnavailable";

function formatPipeline(val: number | string): string {
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const gates = useDashboardAuthGates();
  const [briefing, setBriefing] = useState<DashboardAiSummary | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const optionalWidget = {
    ...DASHBOARD_OPTIONAL_WIDGET_OPTIONS,
    refetchInterval: 60_000 as const,
  };
  const optionalWidgetSlow = {
    ...DASHBOARD_OPTIONAL_WIDGET_OPTIONS,
    refetchInterval: 120_000 as const,
  };

  const {
    data: overview,
    isError,
    error,
    refetch,
    isFetched,
    isFetching,
  } = useQuery({
    queryKey: ["dashboard-overview"],
    queryFn: () => dashboardApi.overview().then((r) => r.data),
    refetchInterval: 60_000,
    enabled: gates.coreWidgetsEnabled,
    ...DASHBOARD_CORE_QUERY_OPTIONS,
  });

  useCleanupWhenFetched(isFetched, isFetching);
  useDashboardOverlayCleanup(gates.authReady);

  const agentSummaryQuery = useQuery({
    queryKey: ["sales-agent-summary"],
    queryFn: () => salesAgentApi.summary().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: agentSummary, isError: agentSummaryError } = agentSummaryQuery;

  const salesManagerSummaryQuery = useQuery({
    queryKey: ["sales-manager-summary"],
    queryFn: () => salesManagerApi.overview().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: salesManagerSummary, isError: salesManagerSummaryError } = salesManagerSummaryQuery;

  const executiveSummaryQuery = useQuery({
    queryKey: ["executive-copilot-summary"],
    queryFn: () => executiveCopilotApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: executiveSummary, isError: executiveSummaryError } = executiveSummaryQuery;

  const leadIntelSummaryQuery = useQuery({
    queryKey: ["lead-intelligence-summary"],
    queryFn: () => leadIntelligenceApi.overview().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: leadIntelSummary, isError: leadIntelSummaryError } = leadIntelSummaryQuery;

  const revenueAttributionSummaryQuery = useQuery({
    queryKey: ["revenue-attribution-summary"],
    queryFn: () => revenueAttributionApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: revenueAttributionSummary, isError: revenueAttributionSummaryError } =
    revenueAttributionSummaryQuery;

  const workflowSummaryQuery = useQuery({
    queryKey: ["workflows-summary"],
    queryFn: () => salesWorkflowApi.overview().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: workflowSummary, isError: workflowSummaryError } = workflowSummaryQuery;

  const salesDepartmentSummaryQuery = useQuery({
    queryKey: ["sales-department-v3-summary"],
    queryFn: () => salesDepartmentV3Api.summaryWidget().then((r) => r.data),
    enabled: gates.adminHeavyWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: salesDepartmentSummary, isError: salesDepartmentSummaryError } =
    salesDepartmentSummaryQuery;

  const multiAgentSummaryQuery = useQuery({
    queryKey: ["multi-agent-health-summary"],
    queryFn: () => multiAgentTeamApi.health().then((r) => r.data),
    enabled: gates.adminHeavyWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: multiAgentSummary, isError: multiAgentSummaryError } = multiAgentSummaryQuery;

  const revenueForecastSummaryQuery = useQuery({
    queryKey: ["revenue-forecast-summary"],
    queryFn: () => revenueForecastApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: revenueForecastSummary, isError: revenueForecastSummaryError } =
    revenueForecastSummaryQuery;

  const buyerIntelSummaryQuery = useQuery({
    queryKey: ["buyer-intelligence-summary"],
    queryFn: () => buyerIntelligenceApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: buyerIntelSummary, isError: buyerIntelSummaryError } = buyerIntelSummaryQuery;

  const buyerAcquisitionSummaryQuery = useQuery({
    queryKey: ["buyer-acquisition-summary"],
    queryFn: () => buyerAcquisitionApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: buyerAcquisitionSummary, isError: buyerAcquisitionSummaryError } =
    buyerAcquisitionSummaryQuery;

  const buyerAcquisitionEngineWidgetQuery = useQuery({
    queryKey: ["buyer-acquisition-engine-summary"],
    queryFn: () => buyerAcquisitionEngineApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: buyerAcquisitionEngineWidget, isError: buyerAcquisitionEngineWidgetError } =
    buyerAcquisitionEngineWidgetQuery;

  const revenueEngineWidgetQuery = useQuery({
    queryKey: ["revenue-engine-summary-widget"],
    queryFn: () => revenueEngineApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: revenueEngineWidget, isError: revenueEngineWidgetError } = revenueEngineWidgetQuery;

  const dealRoomV2WidgetQuery = useQuery({
    queryKey: ["deal-room-v2-summary-widget"],
    queryFn: () => dealRoomV2Api.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: dealRoomV2Widget, isError: dealRoomV2WidgetError } = dealRoomV2WidgetQuery;

  const buyerDiscoverySummaryQuery = useQuery({
    queryKey: ["buyer-discovery-summary"],
    queryFn: () => buyerDiscoveryApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: buyerDiscoverySummary, isError: buyerDiscoverySummaryError } =
    buyerDiscoverySummaryQuery;

  const marketplaceSummaryQuery = useQuery({
    queryKey: ["marketplace-summary"],
    queryFn: () => marketplaceApi.overview().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: marketplaceSummary, isError: marketplaceSummaryError } = marketplaceSummaryQuery;

  const buyerNetworkSummaryQuery = useQuery({
    queryKey: ["buyer-network-summary"],
    queryFn: () => buyerNetworkApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: buyerNetworkSummary, isError: buyerNetworkSummaryError } = buyerNetworkSummaryQuery;

  const dealRiskSummaryQuery = useQuery({
    queryKey: ["deal-risk-summary"],
    queryFn: () => dealRiskApi.summaryWidget().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: dealRiskSummary, isError: dealRiskSummaryError } = dealRiskSummaryQuery;

  const factoryPartnerSummaryQuery = useQuery({
    queryKey: ["factory-partner-summary"],
    queryFn: () => factoryPartnerPortalApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: factoryPartnerSummary, isError: factoryPartnerSummaryError } =
    factoryPartnerSummaryQuery;

  const pilotLaunchOverviewQuery = useQuery({
    queryKey: ["pilot-launch-overview-widget"],
    queryFn: () => pilotLaunchApi.overview().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: pilotLaunchOverview, isError: pilotLaunchOverviewError } = pilotLaunchOverviewQuery;

  const pilotDemoWidgetQuery = useQuery({
    queryKey: ["pilot-demo-overview-widget"],
    queryFn: () => pilotDemoApi.overview().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: pilotDemoWidget, isError: pilotDemoWidgetError } = pilotDemoWidgetQuery;

  const pilotSalesDemoWidgetQuery = useQuery({
    queryKey: ["pilot-sales-demo-summary-widget"],
    queryFn: () => pilotSalesDemoApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: pilotSalesDemoWidget, isError: pilotSalesDemoWidgetError } = pilotSalesDemoWidgetQuery;

  const pilotLaunchValidationWidgetQuery = useQuery({
    queryKey: ["pilot-launch-validation-summary-widget"],
    queryFn: () => pilotLaunchValidationApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: pilotLaunchValidationWidget, isError: pilotLaunchValidationWidgetError } =
    pilotLaunchValidationWidgetQuery;

  const pilotOnboardingSummaryQuery = useQuery({
    queryKey: ["pilot-onboarding-summary"],
    queryFn: () => pilotOnboardingApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: pilotOnboardingSummary, isError: pilotOnboardingSummaryError } =
    pilotOnboardingSummaryQuery;

  const firstPilotClientWidgetQuery = useQuery({
    queryKey: ["first-pilot-client-summary-widget"],
    queryFn: () => firstPilotClientApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: firstPilotClientWidget, isError: firstPilotClientWidgetError } =
    firstPilotClientWidgetQuery;

  const productionDeploymentWidgetQuery = useQuery({
    queryKey: ["production-deployment-summary-widget"],
    queryFn: () => productionDeploymentApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: productionDeploymentWidget, isError: productionDeploymentWidgetError } =
    productionDeploymentWidgetQuery;

  const realFactoryPilotWidgetQuery = useQuery({
    queryKey: ["real-factory-pilot-summary-widget"],
    queryFn: () => realFactoryPilotApi.summaryWidget().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: realFactoryPilotWidget, isError: realFactoryPilotWidgetError } =
    realFactoryPilotWidgetQuery;

  const customerPortalSummaryQuery = useQuery({
    queryKey: ["customer-portal-summary"],
    queryFn: () => customerPortalApi.summaryWidget().then((r) => r.data),
    enabled: gates.tenantWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: customerPortalSummary, isError: customerPortalSummaryError } =
    customerPortalSummaryQuery;

  const customerPortalV2SummaryQuery = useQuery({
    queryKey: ["customer-portal-v2-summary"],
    queryFn: () => customerPortalV2Api.summaryWidget().then((r) => r.data),
    enabled: gates.tenantWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: customerPortalV2Summary, isError: customerPortalV2SummaryError } =
    customerPortalV2SummaryQuery;

  const factoryPerformanceSummaryQuery = useQuery({
    queryKey: ["factory-performance-summary"],
    queryFn: () => factoryPlatformApi.summaryWidget().then((r) => r.data),
    enabled: gates.tenantWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: factoryPerformanceSummary, isError: factoryPerformanceSummaryError } =
    factoryPerformanceSummaryQuery;

  const subscriptionBillingSummaryQuery = useQuery({
    queryKey: ["subscription-billing-summary"],
    queryFn: () => subscriptionBillingApi.summaryWidget().then((r) => r.data),
    enabled: gates.tenantWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: subscriptionBillingSummary, isError: subscriptionBillingSummaryError } =
    subscriptionBillingSummaryQuery;

  const systemHealthQuery = useQuery({
    queryKey: ["system-health"],
    queryFn: () => systemApi.health().then((r) => r.data),
    enabled: gates.sharedWidgetsEnabled,
    ...optionalWidget,
  });
  const { data: systemHealth, isError: systemHealthError } = systemHealthQuery;

  const auditOverviewQuery = useQuery({
    queryKey: ["audit-overview"],
    queryFn: () => auditApi.overview().then((r) => r.data),
    enabled: gates.adminWidgetsEnabled,
    ...optionalWidgetSlow,
  });
  const { data: auditOverview, isError: auditOverviewError } = auditOverviewQuery;

  const summaryMutation = useMutation({
    mutationFn: () => dashboardApi.aiSummary().then((r) => r.data),
    onSuccess: (data) => {
      setBriefing(data);
      toast.success(t("dashboard.briefingGenerated"));
    },
    onError: (err: Error) => toast.error(err.message || t("dashboard.briefingFailed")),
  });

  if (!mounted || !gates.authReady || isOverviewLoading(overview, isError)) {
    return <DashboardSkeleton />;
  }

  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("dashboard.loadError")}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <PageShell>
      <PageHeader
        title={t("dashboard.title")}
        subtitle={t("dashboard.subtitle")}
        icon={LayoutDashboard}
      />

      <PartialErrorsBanner errors={overview.errors} />

      {executiveSummaryError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetExecutiveSummary")} />
      )}
      {executiveSummary && (
        <ExecutiveKpiBar
          healthScore={executiveSummary.business_health_score}
          healthLabel={t("dashboard.businessHealth")}
          items={[
            { label: t("dashboard.kpiInbox"), value: overview.inbox_new },
            { label: t("dashboard.kpiTasks"), value: overview.tasks_open },
            { label: t("dashboard.kpiContent"), value: overview.content_ready },
            { label: t("dashboard.pipeline"), value: overview.active_deals },
            { label: t("dashboard.hotLeads"), value: executiveSummary.hot_leads },
            { label: t("dashboard.opportunities"), value: executiveSummary.opportunities },
          ]}
        />
      )}

      {systemHealthError && (
        <DashboardWidgetUnavailable title={t("dashboard.systemStatus")} />
      )}
      {systemHealth && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Activity size={16} className="text-brand-600" />
              {t("dashboard.systemStatus")}
            </p>
            <Link
              href="/system"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.details")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {[
              { label: t("dashboard.database"), value: systemHealth.database, ok: systemHealth.database === "ok" },
              { label: t("dashboard.scheduler"), value: systemHealth.scheduler, ok: systemHealth.scheduler === "running" || systemHealth.scheduler === "disabled" },
              { label: t("dashboard.ai"), value: systemHealth.ai_services, ok: systemHealth.ai_services === "ok" || systemHealth.ai_services === "demo" },
              { label: t("dashboard.telegram"), value: systemHealth.telegram_bot, ok: systemHealth.telegram_bot === "configured" },
            ].map(({ label, value, ok }) => (
              <div
                key={label}
                className={cn(
                  "rounded-lg border px-3 py-2 text-xs",
                  ok ? "border-emerald-100 bg-emerald-50/50" : "border-amber-100 bg-amber-50/50",
                )}
              >
                <p className="text-[10px] text-gray-500">{label}</p>
                <p className="font-medium capitalize text-gray-900">{translateSystemStatus(t, value)}</p>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-gray-400">
            {t("dashboard.platformStatusLine", {
              status: translateSystemStatus(t, systemHealth.status),
              uptime: Math.floor(systemHealth.uptime / 60),
              clients: systemHealth.total_clients,
              posts: systemHealth.total_posts,
            })}
          </p>
        </div>
      )}

      {auditOverviewError && (
        <DashboardWidgetUnavailable title={t("dashboard.auditQa")} />
      )}
      {auditOverview && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <ClipboardCheck size={16} className="text-brand-600" />
              {t("dashboard.auditQa")}
            </p>
            <Link
              href="/audit"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("dashboard.viewAll")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <Link
              href="/audit?severity=critical"
              className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors"
            >
              <p className="text-lg font-semibold text-red-800 tabular-nums">
                {auditOverview.summary.critical}
              </p>
              <p className="text-[10px] text-red-600">{t("dashboard.criticalIssues")}</p>
            </Link>
            <Link
              href="/audit?severity=warning"
              className="rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2 hover:bg-amber-50 transition-colors"
            >
              <p className="text-lg font-semibold text-amber-800 tabular-nums">
                {auditOverview.summary.warning}
              </p>
              <p className="text-[10px] text-amber-600">{t("dashboard.warnings")}</p>
            </Link>
          </div>
          {auditOverview.summary.total === 0 && (
            <p className="text-[10px] text-emerald-600">{t("dashboard.allChecksPassed")}</p>
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard
          label={t("dashboard.kpiInbox")}
          value={overview.inbox_new}
          href="/inbox"
          icon={Inbox}
          iconClassName="bg-sky-50 text-sky-600"
          sub={t("dashboard.newItems")}
        />
        <KpiCard
          label={t("dashboard.kpiTasks")}
          value={overview.tasks_open}
          href="/tasks"
          icon={ListTodo}
          iconClassName="bg-violet-50 text-violet-600"
          sub={t("dashboard.open")}
        />
        <KpiCard
          label={t("dashboard.kpiContent")}
          value={overview.content_ready}
          href="/content"
          icon={FileText}
          iconClassName="bg-emerald-50 text-emerald-600"
          sub={t("dashboard.contentScheduled", { count: overview.content_scheduled })}
        />
        <KpiCard
          label={t("dashboard.pipeline")}
          value={overview.active_deals}
          href="/crm/deals"
          icon={Briefcase}
          iconClassName="bg-indigo-50 text-indigo-600"
          sub={`${formatPipeline(overview.pipeline_value)} UZS`}
        />
        <KpiCard
          label={t("dashboard.mrr")}
          value={`$${overview.mrr.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          href="/billing"
          icon={TrendingUp}
          iconClassName="bg-amber-50 text-amber-600"
        />
        <KpiCard
          label={t("dashboard.invoices")}
          value={overview.invoices_unpaid}
          href="/crm/deals"
          icon={CreditCard}
          iconClassName="bg-red-50 text-red-600"
          sub={t("dashboard.unpaid")}
        />
      </div>

      {(overview.operator_tasks_today ?? 0) > 0 && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <ListTodo size={16} className="text-violet-600" />
              {t("dashboard.operatorTasksToday")}
            </p>
            <Link
              href="/operator-tasks"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("dashboard.viewOperatorTasks")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <ul className="space-y-2 text-sm">
            {(overview.operator_tasks_today_items ?? []).slice(0, 6).map((task) => (
              <li key={task.id} className="flex items-center justify-between gap-2 border-b border-gray-50 pb-2">
                <Link href="/operator-tasks" className="font-medium text-brand-800 hover:underline truncate">
                  {task.title}
                </Link>
                <span className="text-[10px] text-gray-400 capitalize shrink-0">{task.priority}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {agentSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Bot size={16} className="text-brand-600" />
              {t("dashboard.salesAgentRecommendations")}
            </p>
            <Link
              href="/sales-agent"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("dashboard.viewAll")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <Link
              href="/sales-agent?priority=high"
              className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors"
            >
              <p className="text-lg font-semibold text-red-800 tabular-nums">
                {agentSummary.high_priority_count}
              </p>
              <p className="text-[10px] text-red-600">{t("dashboard.highPriority")}</p>
            </Link>
            <Link
              href="/sales-agent"
              className="rounded-lg border border-orange-100 bg-orange-50/50 px-3 py-2 hover:bg-orange-50 transition-colors"
            >
              <p className="text-lg font-semibold text-orange-800 tabular-nums">
                {agentSummary.overdue_followups}
              </p>
              <p className="text-[10px] text-orange-600">{t("dashboard.overdueFollowUps")}</p>
            </Link>
            <Link
              href="/sales-agent?type=payment_reminder"
              className="rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2 hover:bg-amber-50 transition-colors"
            >
              <p className="text-lg font-semibold text-amber-800 tabular-nums">
                {agentSummary.unpaid_invoices}
              </p>
              <p className="text-[10px] text-amber-600">{t("dashboard.unpaidInvoices")}</p>
            </Link>
            <Link
              href="/sales-agent?type=risk_warning"
              className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors"
            >
              <p className="text-lg font-semibold text-violet-800 tabular-nums">
                {agentSummary.risky_deals}
              </p>
              <p className="text-[10px] text-violet-600">{t("dashboard.riskyDeals")}</p>
            </Link>
          </div>
          <p className="text-[10px] text-gray-400">
            {t("dashboard.newRecommendations", { count: agentSummary.new_recommendations })}
          </p>
        </div>
      )}

      {leadIntelSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Brain size={16} className="text-brand-600" />
              {t("dashboard.widgetLeadIntelligence")}
            </p>
            <Link
              href="/lead-intelligence"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <Link href="/lead-intelligence" className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors">
              <p className="text-lg font-semibold text-red-800 tabular-nums">{leadIntelSummary.hot_leads}</p>
              <p className="text-[10px] text-red-600">{t("dashboard.leadHot")}</p>
            </Link>
            <Link href="/lead-intelligence" className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors">
              <p className="text-lg font-semibold text-violet-800 tabular-nums">{leadIntelSummary.qualified_leads}</p>
              <p className="text-[10px] text-violet-600">{t("dashboard.leadQualified")}</p>
            </Link>
            <Link href="/lead-intelligence" className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 hover:bg-emerald-50 transition-colors">
              <p className="text-lg font-semibold text-emerald-800 tabular-nums">{leadIntelSummary.nurturing_leads}</p>
              <p className="text-[10px] text-emerald-600">{t("dashboard.leadNurturing")}</p>
            </Link>
            <Link href="/lead-intelligence" className="rounded-lg border border-sky-100 bg-sky-50/50 px-3 py-2 hover:bg-sky-50 transition-colors">
              <p className="text-lg font-semibold text-sky-800 tabular-nums">{leadIntelSummary.cold_leads}</p>
              <p className="text-[10px] text-sky-600">{t("dashboard.leadCold")}</p>
            </Link>
            <Link href="/lead-intelligence" className="rounded-lg border border-gray-100 bg-gray-50/50 px-3 py-2 hover:bg-gray-50 transition-colors">
              <p className="text-lg font-semibold text-gray-800 tabular-nums">{leadIntelSummary.inactive_leads}</p>
              <p className="text-[10px] text-gray-600">{t("dashboard.leadInactive")}</p>
            </Link>
          </div>
          <p className="text-[10px] text-gray-400">
            {t("dashboard.readOnlyClassification", { count: leadIntelSummary.total_classified })}
          </p>
        </div>
      )}

      {revenueAttributionSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CircleDollarSign size={16} className="text-emerald-600" />
              {t("nav.revenueAttribution")}
            </p>
            <Link
              href="/revenue-attribution"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <Link
              href="/revenue-attribution"
              className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 hover:bg-emerald-50 transition-colors"
            >
              <p className="text-lg font-semibold text-emerald-800 tabular-nums">
                {Math.round(Number(revenueAttributionSummary.total_revenue) || 0).toLocaleString()}
              </p>
              <p className="text-[10px] text-emerald-600">{t("customerPortal.totalRevenue")}</p>
            </Link>
            <Link
              href="/revenue-attribution"
              className="rounded-lg border border-sky-100 bg-sky-50/50 px-3 py-2 hover:bg-sky-50 transition-colors"
            >
              <p className="text-lg font-semibold text-sky-800 tabular-nums">
                {revenueAttributionSummary.deals_won}
              </p>
              <p className="text-[10px] text-sky-600">{t("customerPortal.dealsWon")}</p>
            </Link>
            <Link
              href="/revenue-attribution"
              className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors"
            >
              <p className="text-lg font-semibold text-violet-800 tabular-nums">
                {revenueAttributionSummary.conversion_rate}%
              </p>
              <p className="text-[10px] text-violet-600">{t("customerPortal.conversion")}</p>
            </Link>
            <Link
              href="/revenue-attribution"
              className="rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2 hover:bg-amber-50 transition-colors"
            >
              <p className="text-sm font-semibold text-amber-900 truncate">
                {revenueAttributionSummary.best_source_label ?? "—"}
              </p>
              <p className="text-[10px] text-amber-600">{t("dashboard.bestSource")}</p>
            </Link>
          </div>
          <p className="text-[10px] text-gray-400">
            {t("dashboard.readOnlyAttribution")}
          </p>
        </div>
      )}

      {executiveSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Crown size={16} className="text-indigo-600" />
              {t("dashboard.widgetExecutiveSummary")}
            </p>
            <Link
              href="/executive-copilot"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-4 py-2">
              <p className="text-[10px] text-indigo-600">{t("dashboard.businessHealth")}</p>
              <p className="text-2xl font-semibold text-indigo-900 tabular-nums">
                {executiveSummary.business_health_score}
              </p>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-6 gap-3 flex-1 min-w-0">
              <Link
                href="/executive-copilot"
                className="rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-2 hover:bg-blue-50 transition-colors"
              >
                <p className="text-lg font-semibold text-blue-800 tabular-nums">
                  {executiveSummary.hot_leads}
                </p>
                <p className="text-[10px] text-blue-600">{t("dashboard.hotLeads")}</p>
              </Link>
              <Link
                href="/executive-copilot"
                className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 hover:bg-emerald-50 transition-colors"
              >
                <p className="text-lg font-semibold text-emerald-800 tabular-nums">
                  {executiveSummary.opportunities}
                </p>
                <p className="text-[10px] text-emerald-600">{t("dashboard.opportunities")}</p>
              </Link>
              <Link
                href="/executive-copilot"
                className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors"
              >
                <p className="text-lg font-semibold text-red-800 tabular-nums">
                  {executiveSummary.risk_count}
                </p>
                <p className="text-[10px] text-red-600">{t("executive.risks")}</p>
              </Link>
              <Link
                href="/operator-tasks"
                className="rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2 hover:bg-amber-50 transition-colors"
              >
                <p className="text-lg font-semibold text-amber-800 tabular-nums">
                  {executiveSummary.overdue_tasks}
                </p>
                <p className="text-[10px] text-amber-600">{t("executive.overdueTasks")}</p>
              </Link>
              <Link
                href="/unified-inbox"
                className="rounded-lg border border-sky-100 bg-sky-50/50 px-3 py-2 hover:bg-sky-50 transition-colors"
              >
                <p className="text-lg font-semibold text-sky-800 tabular-nums">
                  {executiveSummary.active_conversations}
                </p>
                <p className="text-[10px] text-sky-600">{t("executive.conversations")}</p>
              </Link>
              <Link
                href="/revenue"
                className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors"
              >
                <p className="text-lg font-semibold text-violet-800 tabular-nums">
                  {Math.round(executiveSummary.closed_revenue).toLocaleString()}
                </p>
                <p className="text-[10px] text-violet-600">{t("executive.closedRevenue")}</p>
              </Link>
            </div>
          </div>
          {(executiveSummary.top_recommendations?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {executiveSummary.top_recommendations.slice(0, 2).map((rec, i) => (
                <li key={i}>→ {rec.title}</li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-gray-400">
            {t("dashboard.heuristicExecutive")}
          </p>
        </div>
      )}

      {salesDepartmentSummaryError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetSalesDepartment")} />
      )}
      {salesDepartmentSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Building2 size={16} className="text-brand-600" />
              {t("dashboard.widgetSalesDepartment")}
            </p>
            <Link
              href="/sales-department-v3"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-4 py-2">
              <p className="text-[10px] text-brand-600">{t("dashboard.departmentHealth")}</p>
              <p className="text-2xl font-semibold text-brand-900 tabular-nums">
                {salesDepartmentSummary.business_health_score}
              </p>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3 flex-1 min-w-0">
              <Link
                href="/sales-department-v3"
                className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors"
              >
                <p className="text-lg font-semibold text-red-800 tabular-nums">
                  {salesDepartmentSummary.priority_leads}
                </p>
                <p className="text-[10px] text-red-600">{t("dashboard.priorityLeads")}</p>
              </Link>
              <Link
                href="/sales-department-v3"
                className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 hover:bg-emerald-50 transition-colors"
              >
                <p className="text-lg font-semibold text-emerald-800 tabular-nums">
                  {salesDepartmentSummary.active_opportunities}
                </p>
                <p className="text-[10px] text-emerald-600">{t("dashboard.opportunities")}</p>
              </Link>
              <Link
                href="/sales-department-v3"
                className="rounded-lg border border-orange-100 bg-orange-50/50 px-3 py-2 hover:bg-orange-50 transition-colors"
              >
                <p className="text-lg font-semibold text-orange-800 tabular-nums">
                  {salesDepartmentSummary.open_risks}
                </p>
                <p className="text-[10px] text-orange-600">{t("dashboard.openRisks")}</p>
              </Link>
              <Link
                href="/operator-tasks"
                className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors"
              >
                <p className="text-lg font-semibold text-violet-800 tabular-nums">
                  {salesDepartmentSummary.overdue_actions}
                </p>
                <p className="text-[10px] text-violet-600">{t("dashboard.overdueActions")}</p>
              </Link>
              <Link
                href="/revenue"
                className="rounded-lg border border-sky-100 bg-sky-50/50 px-3 py-2 hover:bg-sky-50 transition-colors"
              >
                <p className="text-lg font-semibold text-sky-800 tabular-nums">
                  {formatPipeline(salesDepartmentSummary.pipeline_value)}
                </p>
                <p className="text-[10px] text-sky-600">{t("dashboard.pipelineUzs")}</p>
              </Link>
            </div>
          </div>
          {(salesDepartmentSummary.top_actions?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {salesDepartmentSummary.top_actions.slice(0, 2).map((action, i) => (
                <li key={i}>→ {action.title}</li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-gray-400">
            {t("dashboard.unifiedSalesOs")}
          </p>
        </div>
      )}

      {multiAgentSummaryError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetMultiAgent")} />
      )}
      {multiAgentSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Bot size={16} className="text-brand-600" />
              {t("dashboard.widgetMultiAgent")}
            </p>
            <Link
              href="/multi-agent"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-4 py-2">
              <p className="text-[10px] text-indigo-600">{t("dashboard.teamHealth")}</p>
              <p className="text-2xl font-semibold text-indigo-900 tabular-nums">
                {multiAgentSummary.department_health}
              </p>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 flex-1 min-w-0">
              <Link
                href="/multi-agent"
                className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors"
              >
                <p className="text-lg font-semibold text-red-800 tabular-nums">
                  {multiAgentSummary.hot_leads}
                </p>
                <p className="text-[10px] text-red-600">{t("dashboard.hotLeads")}</p>
              </Link>
              <Link
                href="/multi-agent"
                className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 hover:bg-emerald-50 transition-colors"
              >
                <p className="text-lg font-semibold text-emerald-800 tabular-nums">
                  {multiAgentSummary.active_opportunities}
                </p>
                <p className="text-[10px] text-emerald-600">{t("dashboard.opportunities")}</p>
              </Link>
              <Link
                href="/multi-agent"
                className="rounded-lg border border-orange-100 bg-orange-50/50 px-3 py-2 hover:bg-orange-50 transition-colors"
              >
                <p className="text-lg font-semibold text-orange-800 tabular-nums">
                  {multiAgentSummary.open_risks}
                </p>
                <p className="text-[10px] text-orange-600">{t("dashboard.openRisks")}</p>
              </Link>
              <Link
                href="/operator-tasks"
                className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors"
              >
                <p className="text-lg font-semibold text-violet-800 tabular-nums">
                  {multiAgentSummary.overdue_actions}
                </p>
                <p className="text-[10px] text-violet-600">{t("dashboard.overdue")}</p>
              </Link>
            </div>
          </div>
          {(multiAgentSummary.top_recommendations?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {multiAgentSummary.top_recommendations.slice(0, 2).map((rec, i) => (
                <li key={i}>→ {rec.title}</li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-gray-400">
            {t("dashboard.multiAgentHint")}
          </p>
        </div>
      )}

      {revenueForecastSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <TrendingUp size={16} className="text-emerald-600" />
              {t("dashboard.widgetRevenueForecast")}
            </p>
            <Link
              href="/revenue-forecast"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-3 py-2">
              <p className="text-[10px] text-brand-600">{t("dashboard.expected30d")}</p>
              <p className="text-lg font-semibold text-brand-900 tabular-nums">
                {formatPipeline(revenueForecastSummary.expected_30d)}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2">
              <p className="text-[10px] text-emerald-600">{t("dashboard.bestCase")}</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {formatPipeline(revenueForecastSummary.best_case_30d)}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2">
              <p className="text-[10px] text-red-600">{t("dashboard.worstCase")}</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {formatPipeline(revenueForecastSummary.worst_case_30d)}
              </p>
            </div>
          </div>
          {(revenueForecastSummary.top_growth?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {revenueForecastSummary.top_growth.slice(0, 2).map((g, i) => (
                <li key={i}>→ {g.title}</li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-gray-400">
            {t("dashboard.forecastHint", { confidence: revenueForecastSummary.confidence })}
          </p>
        </div>
      )}

      {buyerIntelSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Brain size={16} className="text-violet-600" />
              {t("nav.buyerIntelligence")}
            </p>
            <Link
              href="/buyer-intelligence"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">{t("dashboard.leadHot")}</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">{buyerIntelSummary.hot_buyers}</p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">{t("dashboard.strategic")}</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {buyerIntelSummary.strategic_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">{t("dashboard.highPotential")}</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {buyerIntelSummary.high_potential_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-orange-100 bg-orange-50/50 px-2 py-2">
              <p className="text-[10px] text-orange-700">{t("dashboard.atRisk")}</p>
              <p className="text-lg font-semibold text-orange-900 tabular-nums">
                {buyerIntelSummary.at_risk_buyers}
              </p>
            </div>
          </div>
          {buyerIntelSummary.top_buyer_name && (
            <p className="text-xs text-gray-600">
              {t("dashboard.topBuyer", {
                name: buyerIntelSummary.top_buyer_name,
                score: buyerIntelSummary.top_buyer_score,
              })}
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            {t("dashboard.avgScoreHint", { score: buyerIntelSummary.average_buyer_score })}
          </p>
        </div>
      )}

      {buyerAcquisitionSummary && (
        <div className="card p-4 space-y-3 border-brand-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Layers size={16} className="text-brand-600" />
              {t("nav.buyerAcquisition")}
            </p>
            <Link
              href="/buyer-acquisition"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center">
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("dashboard.totalBuyers")}</p>
              <p className="text-lg font-semibold text-brand-900 tabular-nums">
                {buyerAcquisitionSummary.total_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">{t("dashboard.strategic")}</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {buyerAcquisitionSummary.strategic_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">{t("dashboard.highPotential")}</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {buyerAcquisitionSummary.high_potential_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">{t("dashboard.marketplace")}</p>
              <p className="text-lg font-semibold text-teal-900 tabular-nums">
                {buyerAcquisitionSummary.marketplace_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">{t("dashboard.networkOpps")}</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {buyerAcquisitionSummary.network_opportunities}
              </p>
            </div>
          </div>
          {buyerAcquisitionSummary.top_buyer_name && (
            <p className="text-xs text-gray-600">
              {t("dashboard.topUnifiedBuyer", {
                name: buyerAcquisitionSummary.top_buyer_name,
                score: buyerAcquisitionSummary.top_buyer_score,
              })}
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            {t("dashboard.unifiedAggregationHint")}
          </p>
        </div>
      )}

      {dealRoomV2WidgetError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetDealRoom")} />
      )}
      {dealRoomV2Widget && (
        <div className="card p-4 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Briefcase size={16} className="text-violet-700" />
              {t("dashboard.widgetDealRoom")}
            </p>
            <Link
              href="/deal-room"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-800">{t("deal.readiness")}</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {dealRoomV2Widget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("deal.activeDeals")}</p>
              <p className="text-lg font-semibold text-brand-900 tabular-nums">
                {dealRoomV2Widget.active_deal_rooms}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">{t("deal.pipeline")}</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {dealRoomV2Widget.total_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">{t("dashboard.healthAvg")}</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {dealRoomV2Widget.average_health_score}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">{t("deal.highRisk")}</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {dealRoomV2Widget.high_risk_deals}
              </p>
            </div>
          </div>
          {dealRoomV2Widget.top_deal && (
            <p className="text-xs text-gray-600">
              {t("dashboard.topDeal", {
                name: dealRoomV2Widget.top_deal.deal_name,
                value: dealRoomV2Widget.top_deal.deal_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                }),
                currency: dealRoomV2Widget.currency,
              })}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{dealRoomV2Widget.safety_notice}</p>
        </div>
      )}

      {revenueEngineWidget && (
        <div className="card p-4 space-y-3 border-emerald-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CircleDollarSign size={16} className="text-emerald-700" />
              {t("dashboard.widgetRevenueEngine")}
            </p>
            <Link
              href="/revenue-engine"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-800">{t("revenue.readiness")}</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {revenueEngineWidget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("deal.pipeline")}</p>
              <p className="text-lg font-semibold text-brand-900 tabular-nums">
                {revenueEngineWidget.total_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">{t("dashboard.forecast")}</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {revenueEngineWidget.forecasted_revenue.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">{t("revenue.activeDeals")}</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {revenueEngineWidget.active_deals}
              </p>
            </div>
            <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 px-2 py-2">
              <p className="text-[10px] text-cyan-800">{t("dashboard.health")}</p>
              <p className="text-lg font-semibold text-cyan-900 capitalize">
                {translateHealthStatus(t, revenueEngineWidget.health_status)}
              </p>
            </div>
          </div>
          {revenueEngineWidget.top_opportunity_title && (
            <p className="text-xs text-gray-600">
              {t("dashboard.topOpportunity", {
                title: revenueEngineWidget.top_opportunity_title,
                value: revenueEngineWidget.top_opportunity_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                }),
                currency: revenueEngineWidget.currency,
              })}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{revenueEngineWidget.safety_notice}</p>
        </div>
      )}

      {buyerAcquisitionEngineWidget && (
        <div className="card p-4 space-y-3 border-cyan-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Target size={16} className="text-cyan-700" />
              {t("dashboard.widgetBuyerAcquisitionEngine")}
            </p>
            <Link
              href="/buyer-acquisition-engine"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-center">
            <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 px-2 py-2">
              <p className="text-[10px] text-cyan-800">{t("revenue.readiness")}</p>
              <p className="text-lg font-semibold text-cyan-900 tabular-nums">
                {buyerAcquisitionEngineWidget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("dashboard.totalBuyers")}</p>
              <p className="text-lg font-semibold text-brand-900 tabular-nums">
                {buyerAcquisitionEngineWidget.total_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">{t("dashboard.matched")}</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {buyerAcquisitionEngineWidget.matched_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">{t("dashboard.activePipeline")}</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {buyerAcquisitionEngineWidget.active_pipeline_leads}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">{t("dashboard.avgMatch")}</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {buyerAcquisitionEngineWidget.average_match_score}
              </p>
            </div>
          </div>
          {buyerAcquisitionEngineWidget.top_buyer_name && (
            <p className="text-xs text-gray-600">
              {t("dashboard.topMatch", {
                name: buyerAcquisitionEngineWidget.top_buyer_name,
                score: buyerAcquisitionEngineWidget.top_buyer_score,
              })}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{buyerAcquisitionEngineWidget.safety_notice}</p>
        </div>
      )}

      {factoryPerformanceSummary && factoryPerformanceSummary.profile_score > 0 && (
        <div className="card p-4 space-y-3 border-amber-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Factory size={16} className="text-amber-700" />
              {t("dashboard.factoryPerformance")}
            </p>
            <Link
              href="/factory-platform"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-center">
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">Profile score</p>
              <p className="text-lg font-semibold text-amber-950 tabular-nums">
                {factoryPerformanceSummary.profile_score}
              </p>
            </div>
            <div className="rounded-lg border border-orange-100 bg-orange-50/50 px-2 py-2">
              <p className="text-[10px] text-orange-800">Catalog</p>
              <p className="text-lg font-semibold text-orange-950 tabular-nums">
                {factoryPerformanceSummary.catalog_score ?? 0}
              </p>
            </div>
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Buyers</p>
              <p className="text-lg font-semibold text-teal-900 tabular-nums">
                {factoryPerformanceSummary.total_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Opportunities</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {factoryPerformanceSummary.active_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Marketplace</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {factoryPerformanceSummary.marketplace_visibility}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Acquisition</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {factoryPerformanceSummary.buyer_acquisition_score}
              </p>
            </div>
          </div>
          <p className="text-xs text-gray-600">
            {factoryPerformanceSummary.company_name ?? "Factory workspace"} · verification:{" "}
            {factoryPerformanceSummary.verification_status.replace(/_/g, " ")}
          </p>
          {factoryPerformanceSummary.top_recommended_action && (
            <p className="text-xs text-amber-800">
              Next: {factoryPerformanceSummary.top_recommended_action}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{factoryPerformanceSummary.safety_notice}</p>
        </div>
      )}

      {buyerDiscoverySummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Search size={16} className="text-sky-600" />
              {t("nav.buyerDiscovery")}
            </p>
            <Link
              href="/buyer-discovery"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Discovered</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {buyerDiscoverySummary.total_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">High potential</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {buyerDiscoverySummary.high_potential}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Strategic</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {buyerDiscoverySummary.strategic}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Pipeline opps</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {buyerDiscoverySummary.pipeline_opportunity}
              </p>
            </div>
          </div>
          {buyerDiscoverySummary.top_buyer_name && (
            <p className="text-xs text-gray-600">
              Top opportunity: {buyerDiscoverySummary.top_buyer_name} (score{" "}
              {buyerDiscoverySummary.top_buyer_score})
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            Avg score {buyerDiscoverySummary.average_opportunity_score}/100 — intelligence only, no outreach automation.
          </p>
        </div>
      )}

      {buyerNetworkSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Network size={16} className="text-violet-600" />
              {t("nav.buyerNetwork")}
            </p>
            <Link
              href="/buyer-network"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Profiles</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {buyerNetworkSummary.total_profiles}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Strategic</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {buyerNetworkSummary.strategic_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Active</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {buyerNetworkSummary.active_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50/50 px-2 py-2">
              <p className="text-[10px] text-gray-600">Underutilized</p>
              <p className="text-lg font-semibold text-gray-800 tabular-nums">
                {buyerNetworkSummary.underutilized}
              </p>
            </div>
          </div>
          {buyerNetworkSummary.top_buyer_name && (
            <p className="text-xs text-gray-600">
              Top network buyer: {buyerNetworkSummary.top_buyer_name} (strength{" "}
              {buyerNetworkSummary.top_buyer_score})
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            Global buyer intelligence — mapping only, no automatic outreach or CRM writes.
          </p>
        </div>
      )}

      {marketplaceSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Store size={16} className="text-teal-600" />
              {t("nav.marketplace")}
            </p>
            <Link
              href="/marketplace"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Listed</p>
              <p className="text-lg font-semibold text-teal-900 tabular-nums">
                {marketplaceSummary.total_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Open</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {marketplaceSummary.open_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Interests</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {marketplaceSummary.total_interests}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Claims</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {marketplaceSummary.total_claims}
              </p>
            </div>
          </div>
          <p className="text-[10px] text-gray-400">{marketplaceSummary.safety_notice}</p>
        </div>
      )}

      {pilotDemoWidgetError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetPilotDemo")} />
      )}
      {pilotDemoWidget && (
        <div className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Sparkles size={16} className="text-indigo-600" />
              {t("dashboard.widgetPilotDemo")}
            </p>
            <Link
              href="/pilot-demo"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Demo center
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Readiness</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {pilotDemoWidget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Journey</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {pilotDemoWidget.metrics.demo_buyers} buyers
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Presentation</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {pilotDemoWidget.summary.estimated_presentation_minutes}m
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Revenue demo</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                ${pilotDemoWidget.metrics.demo_revenue_usd.toLocaleString()}
              </p>
            </div>
          </div>
          {pilotDemoWidget.summary.what_to_show_next && (
            <p className="text-xs text-gray-600 line-clamp-2">
              Next: {pilotDemoWidget.summary.what_to_show_next}
            </p>
          )}
        </div>
      )}

      {pilotLaunchValidationWidgetError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetPilotLaunchValidation")} />
      )}
      {pilotLaunchValidationWidget && (
        <div className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <ClipboardCheck size={16} className="text-indigo-600" />
              {t("dashboard.widgetPilotLaunchValidation")}
            </p>
            <Link
              href="/pilot-launch-validation"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Validation center
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Readiness</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {pilotLaunchValidationWidget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Admin flow</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {pilotLaunchValidationWidget.admin_flow_ready}/{pilotLaunchValidationWidget.admin_flow_total}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Tenant flow</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {pilotLaunchValidationWidget.tenant_flow_ready}/{pilotLaunchValidationWidget.tenant_flow_total}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {pilotLaunchValidationWidget.blocker_count}
              </p>
            </div>
          </div>
          {pilotLaunchValidationWidget.primary_next_action && (
            <p className="text-xs text-gray-600 line-clamp-2">
              Next: {pilotLaunchValidationWidget.primary_next_action}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{pilotLaunchValidationWidget.safety_notice}</p>
        </div>
      )}

      {pilotSalesDemoWidgetError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetPilotSalesDemo")} />
      )}
      {pilotSalesDemoWidget && (
        <div className="card p-4 space-y-3 border-teal-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Presentation size={16} className="text-teal-600" />
              {t("dashboard.widgetPilotSalesDemo")}
            </p>
            <Link
              href="/pilot-sales-demo"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Sales presentation
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Readiness</p>
              <p className="text-lg font-semibold text-teal-900 tabular-nums">
                {pilotSalesDemoWidget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Buyers</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {pilotSalesDemoWidget.buyers_found}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Pipeline</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                ${pilotSalesDemoWidget.pipeline_value_usd.toLocaleString()}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Deal rooms</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {pilotSalesDemoWidget.deal_rooms}
              </p>
            </div>
          </div>
          {pilotSalesDemoWidget.company_name && (
            <p className="text-xs text-gray-600">
              Factory: {pilotSalesDemoWidget.company_name}
              {pilotSalesDemoWidget.next_demo_step
                ? ` — Start: ${pilotSalesDemoWidget.next_demo_step}`
                : ""}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{pilotSalesDemoWidget.safety_notice}</p>
        </div>
      )}

      {pilotLaunchOverviewError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetPilotLaunchReadiness")} />
      )}
      {pilotLaunchOverview && (
        <div className="card p-4 space-y-3 border-fuchsia-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Rocket size={16} className="text-fuchsia-600" />
              {t("dashboard.widgetPilotLaunchReadiness")}
            </p>
            <Link
              href="/pilot-launch"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Launch center
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-fuchsia-100 bg-fuchsia-50/50 px-2 py-2">
              <p className="text-[10px] text-fuchsia-700">Readiness</p>
              <p className="text-lg font-semibold text-fuchsia-900 tabular-nums">
                {pilotLaunchOverview.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">QA passed</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {pilotLaunchOverview.qa_pass_count}/{pilotLaunchOverview.qa_total}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Smoke OK</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {pilotLaunchOverview.smoke_ok_count}/{pilotLaunchOverview.smoke_total}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blocked</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {pilotLaunchOverview.checklist_blocked}
              </p>
            </div>
          </div>
          {pilotLaunchOverview.demo_company_name && (
            <p className="text-xs text-gray-600">
              Demo: {pilotLaunchOverview.demo_company_name}
              {pilotLaunchOverview.demo_data_present ? "" : ` ${t("dashboard.notSeeded")}`}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{pilotLaunchOverview.safety_notice}</p>
        </div>
      )}

      {pilotOnboardingSummaryError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetPilotOnboarding")} />
      )}
      {pilotOnboardingSummary && (
        <div className="card p-4 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Rocket size={16} className="text-violet-600" />
              {t("dashboard.widgetPilotOnboarding")}
            </p>
            <Link
              href="/pilot-onboarding"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("dashboard.openWorkspace")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">In progress</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {pilotOnboardingSummary.in_progress}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blocked</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {pilotOnboardingSummary.blocked}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Pilot ready</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {pilotOnboardingSummary.pilot_ready}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-2">
              <p className="text-[10px] text-gray-600">Avg readiness</p>
              <p className="text-lg font-semibold text-gray-900 tabular-nums">
                {pilotOnboardingSummary.average_readiness_score}%
              </p>
            </div>
          </div>
          {pilotOnboardingSummary.latest_company_name && (
            <p className="text-xs text-gray-600">
              Latest: {pilotOnboardingSummary.latest_company_name}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{pilotOnboardingSummary.safety_notice}</p>
        </div>
      )}

      {firstPilotClientWidgetError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetFirstPilotClient")} />
      )}
      {firstPilotClientWidget && (
        <div className="card p-4 space-y-3 border-teal-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Rocket size={16} className="text-teal-600" />
              {t("dashboard.widgetFirstPilotClient")}
            </p>
            <Link
              href="/first-pilot-client"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Readiness center
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Readiness</p>
              <p className="text-lg font-semibold text-teal-900 tabular-nums">
                {firstPilotClientWidget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {firstPilotClientWidget.blocker_count}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Critical</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {firstPilotClientWidget.critical_blocker_count}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Launch</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {firstPilotClientWidget.launch_ready ? "Ready" : "Pending"}
              </p>
            </div>
          </div>
          {firstPilotClientWidget.company_name && (
            <p className="text-xs text-gray-600">
              Client: {firstPilotClientWidget.company_name}
              {firstPilotClientWidget.next_action_title
                ? ` — Next: ${firstPilotClientWidget.next_action_title}`
                : ""}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{firstPilotClientWidget.safety_notice}</p>
        </div>
      )}

      {realFactoryPilotWidgetError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetRealFactoryPilot")} />
      )}
      {realFactoryPilotWidget && (
        <div className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Factory size={16} className="text-indigo-600" />
              {t("dashboard.widgetRealFactoryPilot")}
            </p>
            <Link
              href="/real-factory-pilot"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("dashboard.pilotWorkspace")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Readiness</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {realFactoryPilotWidget.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Checklist</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {realFactoryPilotWidget.checklist_progress}%
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {realFactoryPilotWidget.blocker_count}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Status</p>
              <p className="text-sm font-semibold text-emerald-900 capitalize">
                {realFactoryPilotWidget.status.replace(/_/g, " ")}
              </p>
            </div>
          </div>
          {realFactoryPilotWidget.company_name && (
            <p className="text-xs text-gray-600">
              Factory: {realFactoryPilotWidget.company_name}
              {realFactoryPilotWidget.next_action_title
                ? ` — Next: ${realFactoryPilotWidget.next_action_title}`
                : ""}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{realFactoryPilotWidget.safety_notice}</p>
        </div>
      )}

      {productionDeploymentWidgetError && (
        <DashboardWidgetUnavailable title={t("dashboard.widgetProductionDeployment")} />
      )}
      {productionDeploymentWidget && (
        <div className="card p-4 space-y-3 border-slate-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Cloud size={16} className="text-slate-600" />
              {t("dashboard.widgetProductionDeployment")}
            </p>
            <Link
              href="/production-deployment"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Deployment center
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-slate-100 bg-slate-50/50 px-2 py-2">
              <p className="text-[10px] text-slate-700">Readiness</p>
              <p className="text-lg font-semibold text-slate-900 tabular-nums">
                {productionDeploymentWidget.production_readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {productionDeploymentWidget.blocker_count}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Critical</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {productionDeploymentWidget.critical_finding_count}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Deploy</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {productionDeploymentWidget.deployment_ready ? "Ready" : "Pending"}
              </p>
            </div>
          </div>
          {productionDeploymentWidget.next_action_title && (
            <p className="text-xs text-gray-600">
              Next: {productionDeploymentWidget.next_action_title}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{productionDeploymentWidget.safety_notice}</p>
        </div>
      )}

      {factoryPartnerSummaryError && (
        <DashboardWidgetUnavailable title={t("nav.factoryPartners")} />
      )}
      {factoryPartnerSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Building2 size={16} className="text-indigo-600" />
              Factory Partner Applications
            </p>
            <Link
              href="/factory-partners"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Review
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Pending review</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {factoryPartnerSummary.pending_review}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Approved</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {factoryPartnerSummary.approved}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-2">
              <p className="text-[10px] text-gray-600">Draft</p>
              <p className="text-lg font-semibold text-gray-900 tabular-nums">
                {factoryPartnerSummary.draft}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Rejected</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {factoryPartnerSummary.rejected}
              </p>
            </div>
          </div>
          {factoryPartnerSummary.latest_company_name && (
            <p className="text-xs text-gray-600">
              Latest pending: {factoryPartnerSummary.latest_company_name}
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            Manual review only — no auto-approval or CRM creation.
          </p>
        </div>
      )}

      {customerPortalV2Summary && (
        <div className="card p-4 space-y-3 border-teal-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Building2 size={16} className="text-teal-600" />
              {t("nav.customerPortalV2")}
            </p>
            <Link
              href="/customer-portal-v2"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("dashboard.openV2Workspace")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Buyers</p>
              <p className="text-lg font-semibold text-teal-900 tabular-nums">
                {customerPortalV2Summary.active_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Opportunities</p>
              <p className="text-lg font-semibold text-indigo-900 tabular-nums">
                {customerPortalV2Summary.active_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Open deals</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {customerPortalV2Summary.open_deals}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Profile %</p>
              <p className="text-lg font-semibold text-violet-900 tabular-nums">
                {customerPortalV2Summary.profile_completeness}
              </p>
            </div>
          </div>
          {customerPortalV2Summary.company_name && (
            <p className="text-xs text-gray-600">Tenant: {customerPortalV2Summary.company_name}</p>
          )}
          <p className="text-[10px] text-gray-400">{customerPortalV2Summary.safety_notice}</p>
        </div>
      )}

      {customerPortalSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Building2 size={16} className="text-teal-600" />
              {t("customerPortal.legacyPortal")}
            </p>
            <Link
              href="/customer-portal"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("dashboard.openPortal")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Active</p>
              <p className="text-lg font-semibold text-teal-900 tabular-nums">
                {customerPortalSummary.active_accounts}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Pending</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                {customerPortalSummary.pending_accounts}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-2">
              <p className="text-[10px] text-gray-600">Suspended</p>
              <p className="text-lg font-semibold text-gray-900 tabular-nums">
                {customerPortalSummary.suspended_accounts}
              </p>
            </div>
            <div className="rounded-lg border border-slate-100 bg-slate-50/50 px-2 py-2">
              <p className="text-[10px] text-slate-700">Total</p>
              <p className="text-lg font-semibold text-slate-900 tabular-nums">
                {customerPortalSummary.total_accounts}
              </p>
            </div>
          </div>
          {customerPortalSummary.latest_company_name && (
            <p className="text-xs text-gray-600">
              Latest active: {customerPortalSummary.latest_company_name}
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            Company-scoped read-only portal — no CRM admin or automatic actions.
          </p>
        </div>
      )}

      {subscriptionBillingSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CreditCard size={16} className="text-amber-600" />
              Subscription Summary
            </p>
            <Link
              href="/billing"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              Manage billing
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">MRR</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                ${subscriptionBillingSummary.mrr.toLocaleString()}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Active</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {subscriptionBillingSummary.active_subscriptions}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Trial</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {subscriptionBillingSummary.trial_subscriptions}
              </p>
            </div>
            <div className="rounded-lg border border-orange-100 bg-orange-50/50 px-2 py-2">
              <p className="text-[10px] text-orange-700">Near limit</p>
              <p className="text-lg font-semibold text-orange-900 tabular-nums">
                {subscriptionBillingSummary.tenants_near_limit}
              </p>
            </div>
          </div>
          <p className="text-[10px] text-gray-400">
            Architecture only — no payment processing or automatic charges.
          </p>
        </div>
      )}

      {dealRiskSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <AlertTriangle size={16} className="text-orange-600" />
              {t("nav.dealRisk")}
            </p>
            <Link
              href="/deal-risk"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Healthy</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {dealRiskSummary.healthy_deals}
              </p>
            </div>
            <div className="rounded-lg border border-orange-100 bg-orange-50/50 px-2 py-2">
              <p className="text-[10px] text-orange-700">At risk</p>
              <p className="text-lg font-semibold text-orange-900 tabular-nums">
                {dealRiskSummary.at_risk_deals}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Critical</p>
              <p className="text-lg font-semibold text-red-900 tabular-nums">
                {dealRiskSummary.critical_deals}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">High close %</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {dealRiskSummary.high_close_probability_deals}
              </p>
            </div>
          </div>
          {dealRiskSummary.top_risk_deal_title && (
            <p className="text-xs text-gray-600">Top risk: {dealRiskSummary.top_risk_deal_title}</p>
          )}
          <p className="text-[10px] text-gray-400">
            Avg health {dealRiskSummary.average_health_score}/100 — read-only intelligence only.
          </p>
        </div>
      )}

      {salesManagerSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Briefcase size={16} className="text-violet-600" />
              {t("nav.salesManager")}
            </p>
            <Link
              href="/sales-manager"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-6 gap-3">
            <Link
              href="/crm"
              className="rounded-lg border border-blue-100 bg-blue-50/50 px-3 py-2 hover:bg-blue-50 transition-colors"
            >
              <p className="text-lg font-semibold text-blue-800 tabular-nums">
                {salesManagerSummary.hot_leads}
              </p>
              <p className="text-[10px] text-blue-600">Hot leads</p>
            </Link>
            <Link
              href="/sales-manager"
              className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 hover:bg-emerald-50 transition-colors"
            >
              <p className="text-lg font-semibold text-emerald-800 tabular-nums">
                {salesManagerSummary.opportunities_count}
              </p>
              <p className="text-[10px] text-emerald-600">Opportunities</p>
            </Link>
            <Link
              href="/sales-manager"
              className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors"
            >
              <p className="text-lg font-semibold text-red-800 tabular-nums">
                {salesManagerSummary.risks_count}
              </p>
              <p className="text-[10px] text-red-600">Risks</p>
            </Link>
            <Link
              href="/operator-tasks"
              className="rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2 hover:bg-amber-50 transition-colors"
            >
              <p className="text-lg font-semibold text-amber-800 tabular-nums">
                {salesManagerSummary.overdue_tasks}
              </p>
              <p className="text-[10px] text-amber-600">Overdue tasks</p>
            </Link>
            <Link
              href="/unified-inbox"
              className="rounded-lg border border-sky-100 bg-sky-50/50 px-3 py-2 hover:bg-sky-50 transition-colors"
            >
              <p className="text-lg font-semibold text-sky-800 tabular-nums">
                {salesManagerSummary.inbox_activity.open_conversations}
              </p>
              <p className="text-[10px] text-sky-600">Conversations</p>
            </Link>
            <Link
              href="/proposals"
              className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors"
            >
              <p className="text-lg font-semibold text-violet-800 tabular-nums">
                {salesManagerSummary.active_proposals}
              </p>
              <p className="text-[10px] text-violet-600">Proposals</p>
            </Link>
          </div>
          <p className="text-[10px] text-gray-400">
            Read-only executive layer — manual actions only
          </p>
        </div>
      )}

      {workflowSummary && (
        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Workflow size={16} className="text-brand-600" />
              {t("nav.workflows")}
            </p>
            <Link
              href="/workflows"
              className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1"
            >
              {t("common.open")}
              <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <Link
              href="/workflows"
              className="rounded-lg border border-brand-100 bg-brand-50/50 px-3 py-2 hover:bg-brand-50 transition-colors"
            >
              <p className="text-lg font-semibold text-brand-800 tabular-nums">
                {workflowSummary.active_recommendations}
              </p>
              <p className="text-[10px] text-brand-600">Active</p>
            </Link>
            <Link
              href="/workflows"
              className="rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 hover:bg-red-50 transition-colors"
            >
              <p className="text-lg font-semibold text-red-800 tabular-nums">
                {workflowSummary.high_priority}
              </p>
              <p className="text-[10px] text-red-600">High priority</p>
            </Link>
            <Link
              href="/workflows"
              className="rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2 hover:bg-amber-50 transition-colors"
            >
              <p className="text-lg font-semibold text-amber-800 tabular-nums">
                {workflowSummary.follow_up_workflows}
              </p>
              <p className="text-[10px] text-amber-600">Follow-ups</p>
            </Link>
            <Link
              href="/workflows"
              className="rounded-lg border border-violet-100 bg-violet-50/50 px-3 py-2 hover:bg-violet-50 transition-colors"
            >
              <p className="text-lg font-semibold text-violet-800 tabular-nums">
                {workflowSummary.proposal_workflows}
              </p>
              <p className="text-[10px] text-violet-600">Proposals</p>
            </Link>
            <Link
              href="/workflows"
              className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2 hover:bg-emerald-50 transition-colors"
            >
              <p className="text-lg font-semibold text-emerald-800 tabular-nums">
                {workflowSummary.crm_cleanup_workflows}
              </p>
              <p className="text-[10px] text-emerald-600">CRM cleanup</p>
            </Link>
          </div>
          <p className="text-[10px] text-gray-400">
            Recommendation-only — no automatic execution
          </p>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 card p-4 space-y-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Sparkles size={16} className="text-brand-600" />
              {t("dashboard.aiCeoBriefing")}
            </p>
            <button
              type="button"
              disabled={summaryMutation.isPending}
              onClick={() => summaryMutation.mutate()}
              className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 bg-brand-50 text-brand-800 hover:bg-brand-100 disabled:opacity-50 flex items-center gap-1"
            >
              {summaryMutation.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Sparkles size={12} />
              )}
              {t("dashboard.generateBriefing")}
            </button>
          </div>

          {!briefing && !summaryMutation.isPending && (
            <p className="text-sm text-gray-500">
              {t("dashboard.briefingEmpty")}
            </p>
          )}

          {briefing && (
            <>
              <p className="text-sm text-gray-800 leading-relaxed">{briefing.executive_summary}</p>

              <div>
                <p className="text-xs font-semibold text-gray-700 mb-2">{t("dashboard.todayPriorities")}</p>
                <ol className="list-decimal list-inside space-y-1">
                  {briefing.top_priorities.map((item, i) => (
                    <li key={i} className="text-sm text-gray-800">
                      {item}
                    </li>
                  ))}
                </ol>
              </div>

              <p className="text-[10px] text-gray-400">
                {t("dashboard.advisoryOnly", { source: briefing.source })}
              </p>
            </>
          )}
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-900">{t("dashboard.quickActions")}</p>
          <div className="space-y-1.5">
            {[
              { href: "/crm", label: t("dashboard.quickActionCrm"), icon: Briefcase },
              { href: "/inbox", label: t("dashboard.quickActionInbox"), icon: Inbox },
              { href: "/billing", label: t("dashboard.quickActionBilling"), icon: CreditCard },
              { href: "/content", label: t("dashboard.quickActionContent"), icon: FileText },
            ].map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex items-center justify-between text-sm text-gray-700 hover:text-brand-800 px-2 py-2 rounded-lg hover:bg-gray-50"
              >
                <span className="flex items-center gap-2">
                  <Icon size={14} className="text-gray-400" />
                  {label}
                </span>
                <ArrowRight size={14} className="text-gray-300" />
              </Link>
            ))}
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <AlertTriangle size={16} className="text-red-500" />
            {t("executive.risks")}
          </p>
          {(briefing?.risks?.length ?? 0) > 0 && (
            <ul className="space-y-1.5 mb-3">
              {briefing!.risks.map((r, i) => (
                <li key={i} className="text-sm text-gray-700 flex gap-2">
                  <span className="text-red-400 shrink-0">•</span>
                  {r}
                </li>
              ))}
            </ul>
          )}
          {overview.deal_risks.length === 0 && !briefing?.risks?.length && (
            <p className="text-sm text-gray-400">{t("dashboard.noDealRisks")}</p>
          )}
          {overview.deal_risks.length > 0 && (
            <ul className="space-y-2">
              {overview.deal_risks.map((risk) => (
                <li key={`${risk.deal_id}-${risk.risk_type}`}>
                  <Link
                    href={`/crm/deals/${risk.deal_id}`}
                    className={cn(
                      "block text-sm rounded-lg border px-3 py-2 hover:bg-gray-50",
                      risk.severity === "high"
                        ? "border-red-200 bg-red-50/50 text-red-900"
                        : "border-amber-200 bg-amber-50/50 text-amber-900",
                    )}
                  >
                    {risk.title}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {overview.overdue_followups > 0 && (
            <p className="text-xs text-orange-700">
              {overview.overdue_followups} overdue CRM follow-up(s)
            </p>
          )}
          {overview.near_limit_clients > 0 && (
            <p className="text-xs text-orange-700">
              {overview.near_limit_clients} client(s) near monthly post limit
            </p>
          )}
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Lightbulb size={16} className="text-emerald-500" />
            {t("executive.opportunities")}
          </p>
          {briefing?.opportunities?.length ? (
            <ul className="space-y-1.5">
              {briefing.opportunities.map((o, i) => (
                <li key={i} className="text-sm text-gray-700 flex gap-2">
                  <span className="text-emerald-400 shrink-0">•</span>
                  {o}
                </li>
              ))}
            </ul>
          ) : (
            <ul className="space-y-1.5 text-sm text-gray-600">
              {overview.won_deals > 0 && (
                <li>{overview.won_deals} deal(s) won — consider upsell or referrals</li>
              )}
              {overview.content_ready > 0 && (
                <li>{overview.content_ready} content ready to schedule and publish</li>
              )}
              {overview.active_deals > 0 && (
                <li>
                  {overview.active_deals} active deal(s) in pipeline (
                  {formatPipeline(overview.pipeline_value)} UZS)
                </li>
              )}
              {!overview.won_deals && !overview.content_ready && !overview.active_deals && (
                <li className="text-gray-400">Generate AI briefing for tailored opportunities.</li>
              )}
            </ul>
          )}

          {briefing?.recommended_actions && briefing.recommended_actions.length > 0 && (
            <div className="pt-2 border-t border-gray-100">
              <p className="text-xs font-semibold text-gray-700 mb-2">{t("dashboard.recommendedActions")}</p>
              <ul className="space-y-1">
                {briefing.recommended_actions.map((a, i) => (
                  <li key={i} className="text-xs text-gray-600">
                    → {a}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-center">
        <div className="card p-3">
          <p className="text-lg font-semibold text-gray-900">{overview.clients_waiting_materials}</p>
          <p className="text-[10px] text-gray-500">Clients waiting materials</p>
        </div>
        <div className="card p-3">
          <p className="text-lg font-semibold text-gray-900">{overview.content_scheduled}</p>
          <p className="text-[10px] text-gray-500">Content scheduled</p>
        </div>
        <div className="card p-3">
          <p className="text-lg font-semibold text-emerald-700">{overview.won_deals}</p>
          <p className="text-[10px] text-gray-500">Won deals</p>
        </div>
        <div className="card p-3">
          <p className="text-lg font-semibold text-gray-500">{overview.lost_deals}</p>
          <p className="text-[10px] text-gray-500">Lost deals</p>
        </div>
      </div>
    </PageShell>
  );
}
