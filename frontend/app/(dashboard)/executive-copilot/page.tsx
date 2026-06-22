"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Briefcase,
  Bot,
  Building2,
  CircleDollarSign,
  Contact,
  CreditCard,
  FileSignature,
  Inbox,
  Lightbulb,
  ListTodo,
  Loader2,
  Sparkles,
  Target,
  Search,
  Store,
  Network,
  Layers,
  TrendingUp,
  Factory,
  Rocket,
  Cloud,
  Presentation,
  ClipboardCheck,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  executiveCopilotApi,
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
  CustomerPortalV2HealthOverview,
  salesDepartmentV3Api,
  ExecutiveCopilotAlert,
  ExecutiveCopilotBriefing,
  ExecutiveCopilotRecommendation,
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
  ScoreCard,
  SectionCard,
  StatTile,
  StatusBadge,
} from "@/components/ui/design-system";
import type { StatusVariant } from "@/lib/design-system";
import { useTranslation } from "@/lib/I18nProvider";
import {
  isOverviewLoading,
  OVERVIEW_HEAVY_QUERY_OPTIONS,
  OVERVIEW_SECTION_QUERY_OPTIONS,
  OVERVIEW_WIDGET_QUERY_OPTIONS,
} from "@/lib/overview-query-options";

const PRIORITY_VARIANT: Record<string, StatusVariant> = {
  urgent: "danger",
  high: "warning",
  medium: "warning",
  low: "neutral",
};

const SEVERITY_VARIANT: Record<string, StatusVariant> = {
  critical: "danger",
  high: "warning",
  medium: "warning",
  low: "neutral",
};

function WidgetMetricGrid({
  items,
  columns = 4,
}: {
  items: { label: string; value: string | number; tone?: "neutral" | "brand" | "success" | "warning" | "danger" | "violet" | "info" | "sky" }[];
  columns?: 4 | 5;
}) {
  return (
    <div
      className={cn(
        "grid gap-3",
        columns === 5 ? "sm:grid-cols-2 lg:grid-cols-5" : "sm:grid-cols-2 lg:grid-cols-4",
      )}
    >
      {items.map((item) => (
        <StatTile key={item.label} label={item.label} value={item.value} tone={item.tone} />
      ))}
    </div>
  );
}

const CATEGORY_LABELS: Record<string, string> = {
  hot_lead_follow_up: "Hot lead follow-up",
  proposal_follow_up: "Proposal follow-up",
  inactive_lead_recovery: "Inactive lead recovery",
  overdue_task_escalation: "Overdue task escalation",
  conversation_response_reminder: "Conversation reminder",
};

export default function ExecutiveCopilotPage() {
  return <ExecutiveCopilotPageContent />;
}

function ExecutiveCopilotPageContent() {
  const { t } = useTranslation();
  const [briefing, setBriefing] = useState<ExecutiveCopilotBriefing | null>(null);
  const [showAdvancedSections, setShowAdvancedSections] = useState(false);

  const {
    data: summaryWidget,
    isError: widgetError,
    error: widgetErr,
    refetch: refetchWidget,
  } = useQuery({
    queryKey: ["executive-copilot-summary-widget"],
    queryFn: () => executiveCopilotApi.summaryWidget().then((r) => r.data),
    ...OVERVIEW_WIDGET_QUERY_OPTIONS,
  });

  const advancedSectionsEnabled = !!summaryWidget && showAdvancedSections;

  const {
    data: overview,
    isError: overviewError,
  } = useQuery({
    queryKey: ["executive-copilot-overview"],
    queryFn: () => executiveCopilotApi.overview().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_HEAVY_QUERY_OPTIONS,
  });

  const { data: alerts } = useQuery({
    queryKey: ["executive-copilot-alerts"],
    queryFn: () => executiveCopilotApi.alerts({ limit: 50 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: recommendations } = useQuery({
    queryKey: ["executive-copilot-recommendations"],
    queryFn: () => executiveCopilotApi.recommendations({ limit: 30 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: departmentOverview } = useQuery({
    queryKey: ["sales-department-v3-executive"],
    queryFn: () => salesDepartmentV3Api.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: multiAgentOverview } = useQuery({
    queryKey: ["multi-agent-executive"],
    queryFn: () => multiAgentTeamApi.health().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: revenueForecastExec } = useQuery({
    queryKey: ["revenue-forecast-executive-copilot"],
    queryFn: () => revenueForecastApi.executive().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: buyerTop } = useQuery({
    queryKey: ["buyer-intelligence-executive"],
    queryFn: () => buyerIntelligenceApi.topBuyers({ limit: 5 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: buyerAcquisitionExec } = useQuery({
    queryKey: ["buyer-acquisition-executive-copilot"],
    queryFn: () => buyerAcquisitionApi.insights({ limit: 5 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: buyerAcquisitionOverview } = useQuery({
    queryKey: ["buyer-acquisition-overview-executive"],
    queryFn: () => buyerAcquisitionApi.overview().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: buyerAcquisitionEngineExec } = useQuery({
    queryKey: ["buyer-acquisition-engine-executive"],
    queryFn: () => buyerAcquisitionEngineApi.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: buyerAcquisitionEngineOverview } = useQuery({
    queryKey: ["buyer-acquisition-engine-overview-executive"],
    queryFn: () => buyerAcquisitionEngineApi.overview().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: revenueEngineExec } = useQuery({
    queryKey: ["revenue-engine-executive"],
    queryFn: () => revenueEngineApi.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: dealRoomV2Exec } = useQuery({
    queryKey: ["deal-room-v2-executive"],
    queryFn: () => dealRoomV2Api.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: revenueEngineOpps } = useQuery({
    queryKey: ["revenue-engine-opportunities-executive"],
    queryFn: () => revenueEngineApi.opportunities().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: buyerDiscoveryExec } = useQuery({
    queryKey: ["buyer-discovery-executive-copilot"],
    queryFn: () => buyerDiscoveryApi.executiveInsights({ limit: 5 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: marketplaceExec } = useQuery({
    queryKey: ["marketplace-executive-copilot"],
    queryFn: () => marketplaceApi.overview().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: marketplaceTop } = useQuery({
    queryKey: ["marketplace-top-executive"],
    queryFn: () => marketplaceApi.topOpportunities({ limit: 5 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: buyerNetworkExec } = useQuery({
    queryKey: ["buyer-network-executive-copilot"],
    queryFn: () => buyerNetworkApi.executiveSummary({ limit: 5 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: dealRiskHigh } = useQuery({
    queryKey: ["deal-risk-executive"],
    queryFn: () => dealRiskApi.highRisk({ limit: 5 }).then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: factoryPartnerWidget } = useQuery({
    queryKey: ["factory-partner-executive"],
    queryFn: () => factoryPartnerPortalApi.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: pilotLaunchOverview } = useQuery({
    queryKey: ["pilot-launch-executive"],
    queryFn: () => pilotLaunchApi.overview().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: pilotDemoReadiness } = useQuery({
    queryKey: ["pilot-demo-executive"],
    queryFn: () => pilotDemoApi.readiness().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: pilotSalesDemoSummary } = useQuery({
    queryKey: ["pilot-sales-demo-executive"],
    queryFn: () => pilotSalesDemoApi.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: pilotLaunchValidationSummary } = useQuery({
    queryKey: ["pilot-launch-validation-executive"],
    queryFn: () => pilotLaunchValidationApi.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: pilotOnboardingOverview } = useQuery({
    queryKey: ["pilot-onboarding-executive"],
    queryFn: () => pilotOnboardingApi.overview().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: firstPilotClientSummary } = useQuery({
    queryKey: ["first-pilot-client-executive"],
    queryFn: () => firstPilotClientApi.summary().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: productionDeploymentSummary } = useQuery({
    queryKey: ["production-deployment-executive"],
    queryFn: () => productionDeploymentApi.summary().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: realFactoryPilotSummary } = useQuery({
    queryKey: ["real-factory-pilot-executive"],
    queryFn: () => realFactoryPilotApi.summary().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: customerPortalWidget } = useQuery({
    queryKey: ["customer-portal-executive"],
    queryFn: () => customerPortalApi.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: customerPortalV2Health } = useQuery({
    queryKey: ["customer-portal-v2-health"],
    queryFn: () => customerPortalV2Api.summaryWidget().then((r) => r.data as CustomerPortalV2HealthOverview),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: factoryHealthWidget } = useQuery({
    queryKey: ["factory-health-executive"],
    queryFn: () => factoryPlatformApi.summaryWidget().then((r) => r.data),
    enabled: advancedSectionsEnabled,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const briefingMutation = useMutation({
    mutationFn: () => executiveCopilotApi.generateBriefing().then((r) => r.data),
    onSuccess: (data) => {
      setBriefing(data);
      toast.success(t("executive.briefingGenerated"));
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isOverviewLoading(summaryWidget, widgetError)) return <DashboardSkeleton />;
  if (widgetError || !summaryWidget) {
    return (
      <div className="space-y-4">
        <ErrorState
          error={widgetErr}
          onRetry={() => refetchWidget()}
        />
      </div>
    );
  }

  const effectiveOverview = overview ?? {
    business_health_score: summaryWidget.business_health_score,
    hot_leads: summaryWidget.hot_leads,
    opportunities: summaryWidget.opportunities,
    overdue_tasks: summaryWidget.overdue_tasks,
    active_conversations: summaryWidget.active_conversations,
    proposals_pending: summaryWidget.proposals_pending,
    risk_count: summaryWidget.risk_count,
    open_tasks: summaryWidget.overdue_tasks,
    leads_count: 0,
    workflow_recommendations: 0,
    revenue: {
      closed_revenue: summaryWidget.closed_revenue,
      pipeline_value: 0,
      deals_won: 0,
      pending_commission: 0,
      currency: "UZS",
    },
    errors: overviewError ? [t("errors.sectionUnavailable")] : undefined,
  };

  const alertItems =
    alerts?.items ??
    summaryWidget.top_alerts ??
    [];
  const recItems =
    recommendations?.items ??
    summaryWidget.top_recommendations ??
    [];
  const health = effectiveOverview.business_health_score ?? 0;
  const rev = effectiveOverview.revenue ?? {
    closed_revenue: summaryWidget.closed_revenue,
    pipeline_value: 0,
    deals_won: 0,
    pending_commission: 0,
    currency: "UZS",
  };

  const opportunityHighlights = recItems.filter((r) =>
    ["hot_lead_follow_up", "proposal_follow_up"].includes(r.category),
  );

  return (
    <PageShell wide>
      <PageHeader
        title={t("executive.title")}
        subtitle={t("executive.subtitle")}
        icon={Sparkles}
        iconClassName="text-violet-400"
        badge={
          <StatusBadge variant={health >= 75 ? "success" : health >= 50 ? "warning" : "danger"} dot>
            {t("executive.live")}
          </StatusBadge>
        }
        actions={
          <button
            type="button"
            className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1.5"
            disabled={briefingMutation.isPending}
            onClick={() => briefingMutation.mutate()}
          >
            {briefingMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Lightbulb size={12} />
            )}
            {t("executive.generateBriefing")}
          </button>
        }
      />

      {overviewError && (
        <PartialErrorsBanner errors={[t("errors.sectionUnavailable")]} />
      )}
      <PartialErrorsBanner errors={effectiveOverview.errors} />

      <ExecutiveKpiBar
        healthScore={health}
        healthLabel={t("executive.businessHealthScore")}
        items={[
          {
            label: t("executive.closedRevenue"),
            value: `${Math.round(rev.closed_revenue).toLocaleString()} ${rev.currency}`,
          },
          { label: t("executive.hotLeads"), value: effectiveOverview.hot_leads },
          { label: t("executive.opportunities"), value: effectiveOverview.opportunities },
          { label: t("executive.overdueTasks"), value: effectiveOverview.overdue_tasks },
          { label: t("executive.conversations"), value: effectiveOverview.active_conversations },
          { label: t("executive.risks"), value: effectiveOverview.risk_count },
        ]}
      />

      {!showAdvancedSections && (
        <div className="card-premium p-4 flex flex-wrap items-center justify-between gap-3 border border-violet-200/60 dark-tenant:border-violet-500/20">
          <div>
            <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">Detailed analytics</p>
            <p className="text-xs text-gray-500 dark-tenant:text-slate-400">
              Load department, buyer, revenue, pilot, and platform sections when you need the full analysis.
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary text-xs"
            onClick={() => setShowAdvancedSections(true)}
          >
            Load details
          </button>
        </div>
      )}

      <PageSection
        title={t("executive.sectionOverview")}
        description={t("executive.sectionOverviewDesc")}
      >
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3">
          <KpiCard
            label={t("executive.closedRevenue")}
            value={`${Math.round(rev.closed_revenue).toLocaleString()} ${rev.currency}`}
          />
          <KpiCard label={t("executive.hotLeads")} value={effectiveOverview.hot_leads} href="/crm" />
          <KpiCard label={t("executive.opportunities")} value={effectiveOverview.opportunities} />
          <KpiCard label={t("executive.overdueTasks")} value={effectiveOverview.overdue_tasks} href="/tasks" />
          <KpiCard label={t("executive.conversations")} value={effectiveOverview.active_conversations} href="/communications" />
          <KpiCard label={t("executive.proposalsPending")} value={effectiveOverview.proposals_pending} href="/proposals" />
          <KpiCard label={t("executive.risks")} value={effectiveOverview.risk_count} href="/deal-risk" />
        </div>
      </PageSection>

      {departmentOverview && (
        <SectionCard
          title={t("executive.widgetSalesDepartment")}
          icon={Building2}
          iconClassName="text-violet-400"
          href="/sales-department-v3"
          linkLabel={t("executive.openSalesDeptV3")}
          footer={
            <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500">
              Coordinates lead intelligence, communication intelligence, deal room, operator tasks, and workflows.
            </p>
          }
        >
          <div className="grid sm:grid-cols-2 lg:grid-cols-6 gap-3">
            <KpiCard label={t("executive.businessHealthScore")} value={departmentOverview.business_health_score} />
            <KpiCard label={t("executive.hotLeads")} value={departmentOverview.priority_leads} />
            <KpiCard label={t("executive.opportunities")} value={departmentOverview.active_opportunities} />
            <KpiCard label={t("executive.risks")} value={departmentOverview.open_risks} />
            <KpiCard label={t("executive.overdueTasks")} value={departmentOverview.overdue_actions} />
            <KpiCard label={t("nav.communications")} value={Math.round(departmentOverview.communication_health)} />
          </div>
          {(departmentOverview.weekly_priorities?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 dark-tenant:text-slate-400 space-y-1">
              {departmentOverview.weekly_priorities.slice(0, 3).map((item, i) => (
                <li key={i}>• {item}</li>
              ))}
            </ul>
          )}
        </SectionCard>
      )}

      {multiAgentOverview && (
        <section className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Bot size={16} className="text-indigo-600" />
              {t("executive.widgetMultiAgent")}
            </p>
            <Link href="/multi-agent" className="text-xs text-brand-700 hover:underline">
              {t("executive.openMultiAgent")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <KpiCard label={t("executive.businessHealthScore")} value={multiAgentOverview.department_health} />
            <KpiCard label={t("executive.hotLeads")} value={multiAgentOverview.hot_leads} />
            <KpiCard label={t("executive.opportunities")} value={multiAgentOverview.active_opportunities} />
            <KpiCard label={t("executive.risks")} value={multiAgentOverview.open_risks} />
            <KpiCard label={t("executive.overdueTasks")} value={multiAgentOverview.overdue_actions} />
          </div>
          {(multiAgentOverview.top_recommendations?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {multiAgentOverview.top_recommendations.slice(0, 3).map((rec, i) => (
                <li key={i}>• {rec.title}</li>
              ))}
            </ul>
          )}
          {multiAgentOverview.conflicts_count > 0 && (
            <p className="text-[10px] text-amber-700">
              {multiAgentOverview.conflicts_count} cross-agent conflict(s) — review manually on Multi-Agent page.
            </p>
          )}
          <p className="text-[10px] text-gray-400">
            Five specialized agents (Director, Manager, Lead Analyst, Communication, Operations) — advisory only.
          </p>
        </section>
      )}

      {(buyerTop?.top_buyers?.length ?? 0) > 0 && (
        <section className="card p-4 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Target size={16} className="text-violet-600" />
              {t("executive.widgetTopBuyers")}
            </p>
            <Link href="/buyer-intelligence" className="text-xs text-brand-700 hover:underline">
              {t("executive.openBuyerIntelligence")}
            </Link>
          </div>
          <ol className="space-y-2">
            {buyerTop!.top_buyers.slice(0, 5).map((b) => (
              <li key={b.buyer_id} className="flex items-start gap-2 text-sm">
                <span className="font-bold text-brand-700 w-5">{b.rank}</span>
                <div>
                  <p className="font-medium text-gray-900">{b.name}</p>
                  <p className="text-xs text-gray-500">
                    Score {b.buyer_score} · {b.classification.replace(/_/g, " ")}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="text-[10px] text-gray-400">Read-only buyer intelligence — no automatic CRM or deal updates.</p>
        </section>
      )}

      {buyerAcquisitionOverview && (buyerAcquisitionExec?.top_buyers?.length ?? 0) > 0 && (
        <section className="card p-4 space-y-3 border-brand-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Layers size={16} className="text-brand-600" />
              {t("executive.widgetBuyerAcquisition")}
            </p>
            <Link href="/buyer-acquisition" className="text-xs text-brand-700 hover:underline">
              {t("executive.openBuyerAcquisition")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-5 gap-3 text-center text-xs">
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("factory.totalBuyers")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionOverview.total_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">High potential</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionOverview.high_potential_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Strategic</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionOverview.strategic_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Marketplace</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionOverview.marketplace_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Network opps</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionOverview.network_opportunities}
              </p>
            </div>
          </div>
          <ol className="space-y-2 text-sm">
            {buyerAcquisitionExec!.top_buyers.slice(0, 5).map((b) => (
              <li key={`${b.rank}-${b.company_name}`} className="flex items-start gap-2">
                <span className="font-bold text-brand-700 w-5">{b.rank}</span>
                <div>
                  <p className="font-medium text-gray-900">{b.company_name}</p>
                  <p className="text-xs text-gray-500">
                    Score {b.score} · Opp {b.opportunity_score} · Net {b.network_strength}
                    {[b.country, b.industry].filter(Boolean).length > 0 &&
                      ` · ${[b.country, b.industry].filter(Boolean).join(" · ")}`}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="text-[10px] text-gray-400">
            Unified acquisition workspace — read-only aggregation, no automatic outreach or CRM writes.
          </p>
        </section>
      )}

      {buyerAcquisitionEngineExec && buyerAcquisitionEngineOverview && (
        <section className="card p-4 space-y-3 border-cyan-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Target size={16} className="text-cyan-700" />
              {t("executive.widgetBuyerEngine")}
            </p>
            <Link href="/buyer-acquisition-engine" className="text-xs text-brand-700 hover:underline">
              {t("executive.openBuyerEngine")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-5 gap-3 text-center text-xs">
            <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 px-2 py-2">
              <p className="text-[10px] text-cyan-800">{t("deal.readiness")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionEngineExec.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("factory.totalBuyers")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionEngineOverview.total_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Matched</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionEngineOverview.matched_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">Active pipeline</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionEngineOverview.active_pipeline_leads}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Pipeline value</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerAcquisitionEngineOverview.crm_summary.pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
          </div>
          <ol className="space-y-2 text-sm">
            {buyerAcquisitionEngineOverview.factory_view.top_buyers.slice(0, 5).map((b) => (
              <li key={b.buyer_id} className="flex items-start gap-2">
                <span className="font-bold text-cyan-700 w-5">{b.match_score}</span>
                <div>
                  <p className="font-medium text-gray-900">{b.company_name}</p>
                  <p className="text-xs text-gray-500">
                    {[b.country, b.industry].filter(Boolean).join(" · ") || "Match score only"}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="text-[10px] text-gray-400">{buyerAcquisitionEngineExec.safety_notice}</p>
        </section>
      )}

      {dealRoomV2Exec && (
        <section className="card p-4 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Briefcase size={16} className="text-violet-700" />
              {t("executive.widgetDealRoom")}
            </p>
            <Link href="/deal-room" className="text-xs text-brand-700 hover:underline">
              {t("executive.openDealRoom")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-5 gap-3 text-center text-xs">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-800">{t("deal.readiness")}</p>
              <p className="text-lg font-semibold tabular-nums">{dealRoomV2Exec.readiness_score}%</p>
            </div>
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("deal.activeDeals")}</p>
              <p className="text-lg font-semibold tabular-nums">{dealRoomV2Exec.active_deal_rooms}</p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">{t("deal.pipeline")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {dealRoomV2Exec.total_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">{t("deal.weighted")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {dealRoomV2Exec.weighted_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">{t("deal.highRisk")}</p>
              <p className="text-lg font-semibold tabular-nums">{dealRoomV2Exec.high_risk_deals}</p>
            </div>
          </div>
          {dealRoomV2Exec.top_deal && (
            <p className="text-xs text-gray-600">
              Top deal: {dealRoomV2Exec.top_deal.deal_name} — close{" "}
              {dealRoomV2Exec.top_deal.close_probability}%
            </p>
          )}
          <p className="text-[10px] text-gray-400">{dealRoomV2Exec.safety_notice}</p>
        </section>
      )}

      {revenueEngineExec && (
        <section className="card p-4 space-y-3 border-emerald-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CircleDollarSign size={16} className="text-emerald-700" />
              {t("executive.widgetRevenue")}
            </p>
            <Link href="/revenue-engine" className="text-xs text-brand-700 hover:underline">
              {t("executive.openRevenueEngine")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-5 gap-3 text-center text-xs">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-800">{t("revenue.readiness")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {revenueEngineExec.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-2">
              <p className="text-[10px] text-brand-700">{t("revenue.pipelineValue")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {revenueEngineExec.total_pipeline_value.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">{t("revenue.forecasted")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {revenueEngineExec.forecasted_revenue.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">{t("revenue.activeDeals")}</p>
              <p className="text-lg font-semibold tabular-nums">{revenueEngineExec.active_deals}</p>
            </div>
            <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 px-2 py-2">
              <p className="text-[10px] text-cyan-800">{t("revenue.wonRevenue")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {revenueEngineExec.won_revenue.toLocaleString(undefined, {
                  maximumFractionDigits: 0,
                })}
              </p>
            </div>
          </div>
          {revenueEngineOpps && revenueEngineOpps.top_revenue_opportunities.length > 0 && (
            <ol className="space-y-2 text-sm">
              {revenueEngineOpps.top_revenue_opportunities.slice(0, 5).map((o) => (
                <li key={o.opportunity_id} className="flex items-start gap-2">
                  <span className="font-bold text-emerald-700 w-16 text-xs tabular-nums">
                    {o.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                  <div>
                    <p className="font-medium text-gray-900">{o.title}</p>
                    <p className="text-xs text-gray-500">
                      {[o.buyer_name, o.factory_name, o.stage].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          )}
          <p className="text-[10px] text-gray-400">{revenueEngineExec.safety_notice}</p>
        </section>
      )}

      {(buyerDiscoveryExec?.highest_potential_buyers?.length ?? 0) > 0 && (
        <section className="card p-4 space-y-3 border-sky-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Search size={16} className="text-sky-600" />
              {t("executive.widgetBuyerDiscovery")}
            </p>
            <Link href="/buyer-discovery" className="text-xs text-brand-700 hover:underline">
              {t("common.open")} {t("nav.buyerDiscovery")} →
            </Link>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 text-center text-xs">
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Discovered</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerDiscoveryExec!.overview.total_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">High potential</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerDiscoveryExec!.overview.high_potential}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Strategic</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerDiscoveryExec!.overview.strategic}
              </p>
            </div>
          </div>
          <ol className="space-y-2 text-sm">
            {buyerDiscoveryExec!.highest_potential_buyers.slice(0, 5).map((b) => (
              <li key={b.buyer_id} className="flex items-start gap-2">
                <span className="font-bold text-brand-700 w-5">{b.rank}</span>
                <div>
                  <p className="font-medium text-gray-900">{b.company_name}</p>
                  <p className="text-xs text-gray-500">
                    Score {b.opportunity_score} · {[b.country, b.industry].filter(Boolean).join(" · ")}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="text-[10px] text-gray-400">
            Export buyer discovery — read-only intelligence, no automatic outreach or CRM writes.
          </p>
        </section>
      )}

      {buyerNetworkExec && (
        <section className="card p-4 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Network size={16} className="text-violet-600" />
              {t("executive.widgetBuyerNetwork")}
            </p>
            <Link href="/buyer-network" className="text-xs text-brand-700 hover:underline">
              {t("common.open")} {t("nav.buyerNetwork")} →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Profiles</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerNetworkExec.overview.total_profiles}
              </p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Strategic</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerNetworkExec.overview.strategic_buyers}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Relationships</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerNetworkExec.overview.total_relationships}
              </p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50/50 px-2 py-2">
              <p className="text-[10px] text-gray-600">Avg strength</p>
              <p className="text-lg font-semibold tabular-nums">
                {buyerNetworkExec.overview.average_network_strength}
              </p>
            </div>
          </div>
          <ol className="space-y-2 text-sm">
            {buyerNetworkExec.strongest_buyers.slice(0, 5).map((b) => (
              <li key={b.buyer_id} className="flex items-start gap-2">
                <span className="font-bold text-brand-700 w-5">{b.rank}</span>
                <div>
                  <p className="font-medium text-gray-900">{b.company_name}</p>
                  <p className="text-xs text-gray-500">
                    Strength {b.network_strength} · {[b.country, b.industry].filter(Boolean).join(" · ")}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="text-[10px] text-gray-400">{buyerNetworkExec.safety_notice}</p>
        </section>
      )}

      {marketplaceExec && (
        <SectionCard
          title={t("executive.widgetMarketplace")}
          icon={Store}
          iconClassName="text-teal-400"
          href="/marketplace"
          linkLabel={`${t("common.open")} ${t("nav.marketplace")} →`}
          footer={
            <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500">{marketplaceExec.safety_notice}</p>
          }
        >
          <WidgetMetricGrid
            items={[
              { label: "Listed", value: marketplaceExec.total_opportunities, tone: "success" },
              { label: "Open", value: marketplaceExec.open_opportunities, tone: "info" },
              { label: "Interests", value: marketplaceExec.total_interests, tone: "warning" },
              { label: "Claims", value: marketplaceExec.total_claims, tone: "violet" },
            ]}
          />
          {(marketplaceTop?.best_opportunities?.length ?? 0) > 0 && (
            <ol className="space-y-2 text-sm">
              {marketplaceTop!.best_opportunities.slice(0, 5).map((o) => (
                <li key={o.opportunity_id} className="flex items-start gap-2">
                  <span className="font-bold text-brand-700 dark-tenant:text-violet-400 w-5">{o.rank}</span>
                  <div>
                    <p className="font-medium text-gray-900 dark-tenant:text-slate-100">{o.title}</p>
                    <p className="text-xs text-gray-500 dark-tenant:text-slate-400">
                      {o.buyer_company} · score {o.rank_score}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </SectionCard>
      )}

      {(factoryPartnerWidget?.pending_review ?? 0) > 0 && (
        <section className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Building2 size={16} className="text-indigo-600" />
              Pending Factory Applications
            </p>
            <Link href="/factory-partners" className="text-xs text-brand-700 hover:underline">
              Review applications →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {factoryPartnerWidget!.pending_review} application(s) awaiting manual review
            {factoryPartnerWidget!.latest_company_name
              ? ` — latest: ${factoryPartnerWidget!.latest_company_name}`
              : ""}
          </p>
          <p className="text-[10px] text-gray-400">
            Onboarding only — no auto-approval, publishing, or CRM creation.
          </p>
        </section>
      )}

      {pilotDemoReadiness && (
        <section className="card p-4 space-y-3 border-indigo-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Sparkles size={16} className="text-indigo-600" />
              Demo Readiness Overview
            </p>
            <Link href="/pilot-demo" className="text-xs text-brand-700 hover:underline">
              Pilot demo center →
            </Link>
          </div>
          <div className="grid sm:grid-cols-3 gap-3 text-center text-xs">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Demo readiness</p>
              <p className="text-lg font-semibold tabular-nums">{pilotDemoReadiness.readiness_score}%</p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Missing items</p>
              <p className="text-lg font-semibold tabular-nums">{pilotDemoReadiness.missing_data.length}</p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Broken probes</p>
              <p className="text-lg font-semibold tabular-nums">{pilotDemoReadiness.broken_links.length}</p>
            </div>
          </div>
          <p className="text-[10px] text-gray-400">{pilotDemoReadiness.safety_notice}</p>
        </section>
      )}

      {pilotSalesDemoSummary && (
        <section className="card p-4 space-y-3 border-teal-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Presentation size={16} className="text-teal-600" />
              {t("executive.widgetPilotSalesDemo")}
            </p>
            <Link href="/pilot-sales-demo" className="text-xs text-brand-700 hover:underline">
              {t("nav.pilotSalesDemo")} →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Demo readiness</p>
              <p className="text-lg font-semibold tabular-nums">{pilotSalesDemoSummary.readiness_score}%</p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Buyers found</p>
              <p className="text-lg font-semibold tabular-nums">{pilotSalesDemoSummary.buyers_found}</p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Pipeline (USD)</p>
              <p className="text-lg font-semibold tabular-nums">
                ${pilotSalesDemoSummary.pipeline_value_usd.toLocaleString()}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Deal rooms</p>
              <p className="text-lg font-semibold tabular-nums">{pilotSalesDemoSummary.deal_rooms}</p>
            </div>
          </div>
          {pilotSalesDemoSummary.company_name && (
            <p className="text-xs text-gray-600">
              {pilotSalesDemoSummary.company_name}
              {pilotSalesDemoSummary.implementation_complete ? " — execution complete" : ""}
            </p>
          )}
          <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline">
            Pilot execution report →
          </Link>
          <p className="text-[10px] text-gray-400">{pilotSalesDemoSummary.safety_notice}</p>
        </section>
      )}

      {pilotLaunchValidationSummary && (
        <section className="card p-4 space-y-3 border-indigo-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <ClipboardCheck size={16} className="text-indigo-600" />
              {t("executive.widgetPilotLaunchValidation")}
            </p>
            <Link href="/pilot-launch-validation" className="text-xs text-brand-700 hover:underline">
              {t("nav.pilotLaunchValidation")} →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Readiness</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchValidationSummary.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Admin flow</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchValidationSummary.admin_flow_ready}/{pilotLaunchValidationSummary.admin_flow_total}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Tenant flow</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchValidationSummary.tenant_flow_ready}/{pilotLaunchValidationSummary.tenant_flow_total}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchValidationSummary.blocker_count}
              </p>
            </div>
          </div>
          {pilotLaunchValidationSummary.primary_next_action && (
            <p className="text-xs text-gray-600 line-clamp-2">
              Next: {pilotLaunchValidationSummary.primary_next_action}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{pilotLaunchValidationSummary.safety_notice}</p>
        </section>
      )}

      {firstPilotClientSummary && (
        <section className="card p-4 space-y-3 border-teal-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Rocket size={16} className="text-teal-600" />
              Pilot Client Readiness Overview
            </p>
            <Link href="/first-pilot-client" className="text-xs text-brand-700 hover:underline">
              First pilot client →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Readiness</p>
              <p className="text-lg font-semibold tabular-nums">
                {firstPilotClientSummary.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold tabular-nums">
                {firstPilotClientSummary.blockers.length}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Operational</p>
              <p className="text-lg font-semibold tabular-nums">
                {firstPilotClientSummary.operational_ready ? "Ready" : "Pending"}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Launch</p>
              <p className="text-lg font-semibold tabular-nums">
                {firstPilotClientSummary.launch_ready ? "Ready" : "Pending"}
              </p>
            </div>
          </div>
          {firstPilotClientSummary.company_name && (
            <p className="text-xs text-gray-600">Client: {firstPilotClientSummary.company_name}</p>
          )}
          {firstPilotClientSummary.next_action && (
            <p className="text-xs text-gray-600">
              Next: {firstPilotClientSummary.next_action.title}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{firstPilotClientSummary.safety_notice}</p>
        </section>
      )}

      {realFactoryPilotSummary && (
        <section className="card p-4 space-y-3 border-indigo-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Factory size={16} className="text-indigo-600" />
              {t("executive.widgetRealFactoryPilot")}
            </p>
            <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline">
              {t("nav.realFactoryPilot")} →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Readiness</p>
              <p className="text-lg font-semibold tabular-nums">
                {realFactoryPilotSummary.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold tabular-nums">
                {realFactoryPilotSummary.blockers.length}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Warnings</p>
              <p className="text-lg font-semibold tabular-nums">
                {realFactoryPilotSummary.warnings.length}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Status</p>
              <p className="text-sm font-semibold capitalize">
                {realFactoryPilotSummary.status.replace(/_/g, " ")}
              </p>
            </div>
          </div>
          {realFactoryPilotSummary.selected_factory?.company_name && (
            <p className="text-xs text-gray-600">
              Factory: {realFactoryPilotSummary.selected_factory.company_name}
            </p>
          )}
          {realFactoryPilotSummary.next_best_action && (
            <p className="text-xs text-gray-600">
              Next: {realFactoryPilotSummary.next_best_action.title}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{realFactoryPilotSummary.safety_notice}</p>
        </section>
      )}

      {productionDeploymentSummary && (
        <section className="card p-4 space-y-3 border-slate-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Cloud size={16} className="text-slate-600" />
              Production Readiness Overview
            </p>
            <Link href="/production-deployment" className="text-xs text-brand-700 hover:underline">
              Deployment center →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-slate-100 bg-slate-50/50 px-2 py-2">
              <p className="text-[10px] text-slate-700">Readiness</p>
              <p className="text-lg font-semibold tabular-nums">
                {productionDeploymentSummary.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold tabular-nums">
                {productionDeploymentSummary.blockers.length}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Warnings</p>
              <p className="text-lg font-semibold tabular-nums">
                {productionDeploymentSummary.warnings.length}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Deploy</p>
              <p className="text-lg font-semibold tabular-nums">
                {productionDeploymentSummary.deployment_ready ? "Ready" : "Pending"}
              </p>
            </div>
          </div>
          {productionDeploymentSummary.next_action && (
            <p className="text-xs text-gray-600">
              Next: {productionDeploymentSummary.next_action.title}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{productionDeploymentSummary.safety_notice}</p>
        </section>
      )}

      {pilotLaunchOverview && (
        <section className="card p-4 space-y-3 border-fuchsia-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Rocket size={16} className="text-fuchsia-600" />
              Pilot Launch Summary
            </p>
            <Link href="/pilot-launch" className="text-xs text-brand-700 hover:underline">
              Open pilot launch →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-fuchsia-100 bg-fuchsia-50/50 px-2 py-2">
              <p className="text-[10px] text-fuchsia-700">Readiness</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchOverview.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">QA</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchOverview.qa_pass_count}/{pilotLaunchOverview.qa_total}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Smoke</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchOverview.smoke_ok_count}/{pilotLaunchOverview.smoke_total}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blocked</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotLaunchOverview.checklist_blocked}
              </p>
            </div>
          </div>
          {pilotLaunchOverview.blockers.length > 0 && (
            <p className="text-xs text-red-700">
              Blockers: {pilotLaunchOverview.blockers.slice(0, 3).join("; ")}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{pilotLaunchOverview.safety_notice}</p>
        </section>
      )}

      {pilotOnboardingOverview && (
        <section className="card p-4 space-y-3 border-violet-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Rocket size={16} className="text-violet-600" />
              Pilot Onboarding
            </p>
            <Link href="/pilot-onboarding" className="text-xs text-brand-700 hover:underline">
              Open pilot onboarding →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">In progress</p>
              <p className="text-lg font-semibold tabular-nums">{pilotOnboardingOverview.in_progress}</p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blocked</p>
              <p className="text-lg font-semibold tabular-nums">{pilotOnboardingOverview.blocked}</p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Pilot ready</p>
              <p className="text-lg font-semibold tabular-nums">{pilotOnboardingOverview.pilot_ready_count}</p>
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-2">
              <p className="text-[10px] text-gray-600">Avg readiness</p>
              <p className="text-lg font-semibold tabular-nums">
                {pilotOnboardingOverview.average_readiness_score}%
              </p>
            </div>
          </div>
          <p className="text-[10px] text-gray-400">{pilotOnboardingOverview.safety_notice}</p>
        </section>
      )}

      {customerPortalV2Health && (
        <section className="card p-4 space-y-3 border-teal-200">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Building2 size={16} className="text-teal-600" />
              {t("executive.widgetCustomerPortal")}
            </p>
            <Link href="/customer-portal-v2" className="text-xs text-brand-700 hover:underline">
              {t("common.open")} {t("nav.customerPortalV2")} →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Buyers</p>
              <p className="text-lg font-semibold tabular-nums">{customerPortalV2Health.active_buyers}</p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Opportunities</p>
              <p className="text-lg font-semibold tabular-nums">
                {customerPortalV2Health.active_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Open deals</p>
              <p className="text-lg font-semibold tabular-nums">{customerPortalV2Health.open_deals}</p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Profile</p>
              <p className="text-lg font-semibold tabular-nums">
                {customerPortalV2Health.profile_completeness}%
              </p>
            </div>
          </div>
          {customerPortalV2Health.company_name && (
            <p className="text-xs text-gray-600">Workspace: {customerPortalV2Health.company_name}</p>
          )}
          <p className="text-[10px] text-gray-400">{customerPortalV2Health.safety_notice}</p>
        </section>
      )}

      {(customerPortalWidget?.active_accounts ?? 0) > 0 && (
        <section className="card p-4 space-y-3 border-teal-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Building2 size={16} className="text-teal-600" />
              Partner Portal Overview (v1)
            </p>
            <Link href="/customer-portal" className="text-xs text-brand-700 hover:underline">
              {t("common.open")} {t("nav.customerPortal")} →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {customerPortalWidget!.active_accounts} active factory portal account(s)
            {customerPortalWidget!.latest_company_name
              ? ` — latest: ${customerPortalWidget!.latest_company_name}`
              : ""}
          </p>
          <p className="text-[10px] text-gray-400">
            Read-only company-scoped access — no CRM admin or automatic actions.
          </p>
        </section>
      )}

      {factoryHealthWidget && factoryHealthWidget.profile_score > 0 && (
        <section className="card p-4 space-y-3 border-amber-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Factory size={16} className="text-amber-700" />
              {t("executive.widgetFactoryHealth")}
            </p>
            <Link href="/factory-platform" className="text-xs text-brand-700 hover:underline">
              {t("common.open")} {t("nav.factoryPlatform")} →
            </Link>
          </div>
          <div className="grid sm:grid-cols-5 gap-3 text-center text-xs">
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-800">Profile score</p>
              <p className="text-lg font-semibold tabular-nums">{factoryHealthWidget.profile_score}</p>
            </div>
            <div className="rounded-lg border border-orange-100 bg-orange-50/50 px-2 py-2">
              <p className="text-[10px] text-orange-800">Catalog</p>
              <p className="text-lg font-semibold tabular-nums">{factoryHealthWidget.catalog_score ?? 0}</p>
            </div>
            <div className="rounded-lg border border-teal-100 bg-teal-50/50 px-2 py-2">
              <p className="text-[10px] text-teal-700">Buyers</p>
              <p className="text-lg font-semibold tabular-nums">{factoryHealthWidget.total_buyers}</p>
            </div>
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">Opportunities</p>
              <p className="text-lg font-semibold tabular-nums">
                {factoryHealthWidget.active_opportunities}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Marketplace visibility</p>
              <p className="text-lg font-semibold tabular-nums">
                {factoryHealthWidget.marketplace_visibility}
              </p>
            </div>
          </div>
          <p className="text-sm text-gray-700">
            {factoryHealthWidget.company_name ?? "Factory workspace"} · verification:{" "}
            {factoryHealthWidget.verification_status.replace(/_/g, " ")}
          </p>
          {factoryHealthWidget.top_recommended_action && (
            <p className="text-xs text-amber-800">
              Recommended: {factoryHealthWidget.top_recommended_action}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{factoryHealthWidget.safety_notice}</p>
        </section>
      )}

      {overview?.subscription_billing && (
        <section className="card p-4 space-y-3 border-amber-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CreditCard size={16} className="text-amber-600" />
              {t("executive.widgetBilling")}
            </p>
            <Link href="/billing" className="text-xs text-brand-700 hover:underline">
              {t("common.open")} {t("nav.billing")} →
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">MRR</p>
              <p className="text-lg font-semibold text-amber-900 tabular-nums">
                ${(overview.subscription_billing?.mrr ?? 0).toLocaleString()}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Active</p>
              <p className="text-lg font-semibold text-emerald-900 tabular-nums">
                {overview.subscription_billing?.active_subscriptions ?? 0}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">Trial</p>
              <p className="text-lg font-semibold text-sky-900 tabular-nums">
                {overview.subscription_billing?.trial_subscriptions ?? 0}
              </p>
            </div>
            <div className="rounded-lg border border-violet-100 bg-violet-50/50 px-2 py-2">
              <p className="text-[10px] text-violet-700">Plans</p>
              <p className="text-xs font-medium text-violet-900 mt-1">
                {Object.entries(overview.subscription_billing?.plan_distribution ?? {})
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ") || "—"}
              </p>
            </div>
          </div>
          <p className="text-[10px] text-gray-400">
            Architecture only — no payment processing, card storage, or automatic charges.
          </p>
        </section>
      )}

      {(dealRiskHigh?.items?.length ?? 0) > 0 && (
        <section className="card p-4 space-y-3 border-orange-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <AlertTriangle size={16} className="text-orange-600" />
              {t("executive.widgetHighRiskDeals")}
            </p>
            <Link href="/deal-risk" className="text-xs text-brand-700 hover:underline">
              {t("deal.openDealRisk")}
            </Link>
          </div>
          <ol className="space-y-2">
            {dealRiskHigh!.items.slice(0, 5).map((d) => (
              <li key={d.deal_id} className="flex items-start gap-2 text-sm">
                <span className="font-bold text-orange-700 w-5">{d.rank}</span>
                <div>
                  <p className="font-medium text-gray-900">{d.title}</p>
                  <p className="text-xs text-gray-500 capitalize">
                    Health {d.deal_health_score} · {d.risk_level.replace(/_/g, " ")} · close {d.close_probability}%
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <p className="text-[10px] text-gray-400">Read-only deal risk — no automatic messaging or stage updates.</p>
        </section>
      )}

      {revenueForecastExec?.executive && (
        <section className="card p-4 space-y-3 border-emerald-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <TrendingUp size={16} className="text-emerald-600" />
              {t("executive.widgetRevenueForecast")}
            </p>
            <Link href="/revenue-forecast" className="text-xs text-brand-700 hover:underline">
              {t("common.open")} {t("nav.revenueForecast")} →
            </Link>
          </div>
          <p className="text-sm text-gray-700">{revenueForecastExec.executive.forecast_summary}</p>
          {(revenueForecastExec.executive.top_growth_opportunities?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {revenueForecastExec.executive.top_growth_opportunities.slice(0, 3).map((g) => (
                <li key={g.opportunity_id}>• {g.title}</li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-gray-400">
            Heuristic 7d / 30d / 90d scenarios — forecasting only, no automatic deal updates.
          </p>
        </section>
      )}

      {overview?.revenue_attribution?.summary && (
        <section className="card p-4 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CircleDollarSign size={16} className="text-emerald-600" />
              Revenue Insights
            </p>
            <Link href="/revenue-attribution" className="text-xs text-brand-700 hover:underline">
              Open attribution →
            </Link>
          </div>
          <p className="text-sm text-gray-700">{overview.revenue_attribution.summary}</p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 text-xs">
            {[
              ["Best source", overview.revenue_attribution.best_source?.label],
              ["Best channel", overview.revenue_attribution.best_channel?.label],
              ["Weakest source", overview.revenue_attribution.weakest_source?.label],
              ["Best proposal source", overview.revenue_attribution.best_proposal_source?.label],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-gray-100 px-2 py-1.5">
                <p className="text-[10px] text-gray-400">{label}</p>
                <p className="font-medium text-gray-900">{value ?? "—"}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <ScoreCard
        title={t("executive.sectionHealthScore")}
        score={health}
        subtitle={t("executive.healthSubtitle")}
        metrics={[
          { label: t("executive.pipeline"), value: `${Math.round(rev.pipeline_value).toLocaleString()} ${rev.currency}` },
          { label: t("executive.dealsWon"), value: rev.deals_won },
          { label: t("executive.openTasks"), value: effectiveOverview.open_tasks },
          { label: t("executive.proposalsPending"), value: effectiveOverview.proposals_pending },
        ]}
      />

      <SectionCard
        title={t("executive.sectionAlerts")}
        icon={AlertTriangle}
        iconClassName="text-red-400"
      >
        {alertItems.length === 0 ? (
          <EmptyState title={t("executive.noAlerts")} description={t("executive.noAlertsHint")} />
        ) : (
          <ul className="space-y-2">
            {alertItems.map((a: ExecutiveCopilotAlert) => (
              <li
                key={a.id}
                className="flex flex-wrap items-start justify-between gap-2 border-b border-gray-50 dark-tenant:border-white/[0.04] pb-2"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">{a.title}</p>
                  <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">{a.message}</p>
                  <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500 capitalize mt-0.5">{a.source}</p>
                </div>
                <StatusBadge
                  variant={SEVERITY_VARIANT[a.severity] ?? "warning"}
                  className="capitalize text-[10px]"
                >
                  {a.severity}
                </StatusBadge>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard
        title={t("executive.sectionOpportunities")}
        icon={TrendingUp}
        iconClassName="text-emerald-400"
      >
        {effectiveOverview.opportunities === 0 ? (
          <EmptyState title={t("executive.noOpportunities")} description={t("executive.noOpportunitiesHint")} />
        ) : (
          <p className="text-sm text-gray-600 dark-tenant:text-slate-400">
            {effectiveOverview.opportunities} opportunity signal(s) detected across CRM, proposals, inbox, and
            operator tasks. Review items in Sales Manager or CRM for detail.
          </p>
        )}
        {opportunityHighlights.length > 0 && (
          <ul className="space-y-2 text-xs">
            {opportunityHighlights.slice(0, 8).map((o, i) => (
              <li key={i} className="border-b border-gray-50 dark-tenant:border-white/[0.04] pb-2">
                <p className="font-medium text-gray-900 dark-tenant:text-slate-100">{o.title}</p>
                <p className="text-gray-500 dark-tenant:text-slate-400">{o.description}</p>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard
        title={t("executive.sectionRecommendations")}
        icon={Target}
        iconClassName="text-violet-400"
        footer={
          <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500">
            Advisory only — no CRM updates or auto-messaging.
          </p>
        }
      >
        {recItems.length === 0 ? (
          <EmptyState title={t("executive.noRecommendations")} description={t("executive.noRecommendationsHint")} />
        ) : (
          <ul className="space-y-2">
            {recItems.map((r: ExecutiveCopilotRecommendation, i) => (
              <li
                key={`${r.category}-${i}`}
                className="flex flex-wrap items-start justify-between gap-2 border-b border-gray-50 dark-tenant:border-white/[0.04] pb-2"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">{r.title}</p>
                  <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">{r.description}</p>
                  <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500 mt-0.5">
                    {CATEGORY_LABELS[r.category] ?? r.category} · {r.source}
                  </p>
                </div>
                <StatusBadge
                  variant={PRIORITY_VARIANT[r.priority] ?? "warning"}
                  className="capitalize shrink-0 text-[10px]"
                >
                  {r.priority}
                </StatusBadge>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <section className="card p-4 space-y-3 border-violet-100">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Briefcase size={16} className="text-violet-600" />
            {t("executive.widgetDealRecommendations")}
          </p>
          <Link href="/deal-room" className="text-xs text-brand-700 hover:underline">
            {t("executive.openDealRoom")}
          </Link>
        </div>
        {recItems.length === 0 ? (
          <p className="text-sm text-gray-400">No deal-level recommendations at this time.</p>
        ) : (
          <ul className="space-y-2 text-xs">
            {recItems.slice(0, 6).map((r: ExecutiveCopilotRecommendation, i) => (
              <li key={`deal-${i}`} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{r.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{r.description}</p>
                </div>
                {r.lead_id ? (
                  <Link
                    href={`/deal-room?lead_id=${r.lead_id}`}
                    className="text-[10px] text-violet-700 hover:underline shrink-0"
                  >
                    {t("nav.dealRoom")}
                  </Link>
                ) : (
                  <Link href="/deal-room" className="text-[10px] text-gray-400 hover:underline shrink-0">
                    {t("common.view")}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-gray-400">Open a deal workspace to review aggregated context manually.</p>
      </section>

      <SectionCard
        title={t("executive.sectionBriefing")}
        icon={Lightbulb}
        iconClassName="text-violet-400"
      >
        {!briefing ? (
          <p className="text-sm text-gray-400 dark-tenant:text-slate-500">
            Click Generate Briefing for a heuristic executive summary. No AI calls on page load.
          </p>
        ) : (
          <>
            <p className="text-sm text-gray-800 dark-tenant:text-slate-200 leading-relaxed">{briefing.summary}</p>
            <p className="text-xs text-gray-500 dark-tenant:text-slate-400">
              Health score at generation: {briefing.business_health_score}/100
            </p>
            {briefing.communication_intelligence &&
              (briefing.communication_intelligence.total_analyzed ?? 0) > 0 && (
              <div className="rounded-xl border border-teal-200/80 bg-teal-50/40 p-3 dark-tenant:border-teal-500/20 dark-tenant:bg-teal-500/10">
                <p className="text-xs font-semibold text-teal-900 dark-tenant:text-teal-200 mb-1">Communication Intelligence</p>
                <p className="text-xs text-gray-700 dark-tenant:text-slate-300">
                  {briefing.communication_intelligence.hot_buyers} hot buyers ·{" "}
                  {briefing.communication_intelligence.follow_ups_required} follow-ups ·{" "}
                  {briefing.communication_intelligence.inactive_conversations} inactive
                </p>
                <Link href="/communication-intelligence" className="text-[10px] text-brand-700 hover:underline dark-tenant:text-violet-400">
                  Open Communication Intelligence →
                </Link>
              </div>
            )}
            {briefing.opportunities.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-emerald-700 dark-tenant:text-emerald-400 mb-1">{t("executive.opportunities")}</p>
                <ul className="space-y-1">
                  {briefing.opportunities.map((o, i) => (
                    <li key={i} className="text-sm text-gray-700 dark-tenant:text-slate-300">
                      • {o}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {briefing.risks.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-red-700 dark-tenant:text-red-400 mb-1">{t("executive.risks")}</p>
                <ul className="space-y-1">
                  {briefing.risks.map((r, i) => (
                    <li key={i} className="text-sm text-gray-700 dark-tenant:text-slate-300">
                      • {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {briefing.recommendations.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-brand-700 dark-tenant:text-violet-400 mb-1">{t("executive.sectionRecommendations")}</p>
                <ul className="space-y-1">
                  {briefing.recommendations.map((r, i) => (
                    <li key={i} className="text-sm text-gray-700 dark-tenant:text-slate-300">
                      → {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500">Source: {briefing.source}</p>
          </>
        )}
      </SectionCard>

      <SectionCard title={t("executive.quickLinks")} icon={Briefcase} iconClassName="text-sky-400">
        <div className="flex flex-wrap gap-2">
          {[
            { href: "/crm", labelKey: "nav.crm", icon: Contact },
            { href: "/revenue", labelKey: "nav.revenue", icon: CircleDollarSign },
            { href: "/revenue-attribution", labelKey: "nav.revenueAttribution", icon: CircleDollarSign },
            { href: "/unified-inbox", labelKey: "nav.unifiedInbox", icon: Inbox },
            { href: "/operator-tasks", labelKey: "nav.operatorTasks", icon: ListTodo },
            { href: "/proposals", labelKey: "nav.proposals", icon: FileSignature },
            { href: "/sales-manager", labelKey: "nav.salesManager", icon: Briefcase },
            { href: "/deal-room", labelKey: "nav.dealRoom", icon: Briefcase },
          ].map(({ href, labelKey, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="inline-flex items-center gap-1.5 text-xs text-gray-700 hover:text-brand-800 dark-tenant:text-slate-300 dark-tenant:hover:text-violet-300 px-2 py-1.5 rounded-lg border border-gray-100 dark-tenant:border-white/[0.06] hover:bg-gray-50 dark-tenant:hover:bg-white/[0.04] transition-colors"
            >
              <Icon size={12} />
              {t(labelKey)}
            </Link>
          ))}
        </div>
      </SectionCard>
    </PageShell>
  );
}
