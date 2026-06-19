"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  Loader2,
  Map,
  Presentation,
  RefreshCw,
  Shield,
  Sparkles,
  Target,
  TrendingUp,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  pilotSalesDemoApi,
  pilotLaunchValidationApi,
  SalesDemoStepStatus,
} from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import {
  ErrorState,
} from "@/components/ui/PageStates";
import { DashboardSkeleton } from "@/components/ui/Skeleton";
import {
  ExecutiveKpiBar,
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";

const STEP_VARIANT: Record<SalesDemoStepStatus, "success" | "warning" | "danger" | "neutral"> = {
  ready: "success",
  warning: "warning",
  blocked: "danger",
  info: "neutral",
};

export default function PilotSalesDemoPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotSalesDemoPageContent />
    </AdminAuthGuard>
  );
}

function PilotSalesDemoPageContent() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["pilot-sales-demo-overview"],
    queryFn: () => pilotSalesDemoApi.overview().then((r) => r.data),
  });

  const { data: launchValidation } = useQuery({
    queryKey: ["pilot-launch-validation-sales-demo-panel"],
    queryFn: () => pilotLaunchValidationApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const refreshMutation = useMutation({
    mutationFn: () => pilotSalesDemoApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["pilot-sales-demo"] });
      refetch();
    },
    onError: (e: Error) => toast.error(e.message || t("pilot.refreshFailed")),
  });

  if (isLoading) return <DashboardSkeleton />;
  if (isError || !overview)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("pilot.salesDemoPage.loadError")}
        onRetry={() => refetch()}
      />
    );

  const metrics = overview.metrics;

  return (
    <PageShell>
      <PageHeader
        title={t("pilot.salesDemoPage.title")}
        subtitle={t("pilot.salesDemoPage.subtitle")}
        icon={Presentation}
        iconClassName="text-brand-600"
        actions={
          <>
            <button
              type="button"
              onClick={() => refreshMutation.mutate()}
              disabled={refreshMutation.isPending}
              className="btn-secondary text-sm flex items-center gap-1"
            >
              {refreshMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
              {t("pilot.refreshAssessment")}
            </button>
            <Link href="/real-factory-pilot" className="btn-secondary text-sm">
              {t("pilot.pilotExecutionReport")}
            </Link>
          </>
        }
      />

      <div className="card-premium p-3 border-brand-100 bg-brand-50/30 text-xs text-brand-900 flex items-start gap-2">
        <Shield size={14} className="shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      <ExecutiveKpiBar
        healthScore={overview.readiness_score}
        healthLabel={t("pilot.salesDemoPage.demoReadiness")}
        items={[
          { label: t("pilot.salesDemoPage.buyersFound"), value: metrics.buyers_found },
          { label: t("pilot.salesDemoPage.opportunities"), value: metrics.opportunities },
          { label: t("pilot.salesDemoPage.activeDeals"), value: metrics.active_deals },
          { label: t("pilot.salesDemoPage.pipelineUsd"), value: metrics.pipeline_value_usd.toLocaleString() },
          { label: t("pilot.salesDemoPage.forecastUsd"), value: metrics.revenue_forecast_usd.toLocaleString() },
          { label: t("pilot.salesDemoPage.dealRooms"), value: metrics.deal_rooms },
        ]}
      />

      <section className="card-premium p-5 space-y-3">
        <p className="section-title">{t("pilot.salesDemoPage.executiveSummary")}</p>
        <p className="text-sm text-gray-700">{overview.executive_summary}</p>
        <div className="flex flex-wrap gap-2 text-xs">
          {metrics.buyer_countries.map((c) => (
            <span
              key={c}
              className="rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-sky-800"
            >
              {c}
            </span>
          ))}
        </div>
        {overview.implementation_complete && (
          <p className="text-xs text-emerald-700 flex items-center gap-1">
            <CheckCircle2 size={14} />
            {t("pilot.salesDemoPage.implementationComplete")}
          </p>
        )}
      </section>

      <section id="sections" className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5 px-1">
          <Sparkles size={16} className="text-indigo-600" />
          {t("pilot.salesDemoPage.presentationSections")}
        </p>
        <div className="grid gap-3">
          {overview.sections.map((section) => (
            <div key={section.id} className="card p-4 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-semibold text-gray-900">{section.title}</p>
                <StatusBadge variant={STEP_VARIANT[section.status]}>{section.status}</StatusBadge>
              </div>
              <p className="text-sm text-gray-600">{section.summary}</p>
              <ul className="text-xs text-gray-500 list-disc pl-4 space-y-0.5">
                {section.highlights.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
              {section.route && (
                <Link
                  href={section.route}
                  className="text-xs text-brand-700 hover:underline inline-flex items-center gap-1"
                >
                  {t("pilot.salesDemoPage.openModule")}
                  <ArrowRight size={12} />
                </Link>
              )}
            </div>
          ))}
        </div>
      </section>

      <section id="factory-owner-story" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Building2 size={16} className="text-indigo-600" />
          {t("pilot.salesDemoPage.factoryOwnerStory")}
          {overview.factory_owner_story.company_name && (
            <span className="text-xs font-normal text-gray-500">
              — {overview.factory_owner_story.company_name}
            </span>
          )}
        </p>
        <div className="space-y-3">
          {overview.factory_owner_story.phases.map((phase) => (
            <div
              key={phase.phase}
              className={cn(
                "rounded-lg border p-3 text-sm",
                phase.status === "ready" && "border-emerald-200 bg-emerald-50/30",
                phase.status === "warning" && "border-amber-200 bg-amber-50/30",
                phase.status === "blocked" && "border-red-200 bg-red-50/30",
                phase.status === "info" && "border-gray-200",
              )}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <p className="font-medium text-gray-900">{phase.title}</p>
                <StatusBadge variant={STEP_VARIANT[phase.status]}>{phase.status}</StatusBadge>
              </div>
              <p className="text-gray-600 text-xs">{phase.narrative}</p>
              {phase.highlights.length > 0 && (
                <ul className="mt-2 text-[11px] text-gray-500 list-disc pl-4">
                  {phase.highlights.map((h) => (
                    <li key={h}>{h}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </section>

      <section id="demo-flow" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Map size={16} className="text-indigo-600" />
          {overview.demo_flow.title}
          <span className="text-xs font-normal text-gray-500">
            ~{overview.demo_flow.estimated_total_minutes} min
          </span>
        </p>
        <ol className="space-y-2">
          {overview.demo_flow.steps.map((step) => (
            <li
              key={step.order}
              className="flex items-start gap-3 rounded-lg border border-gray-100 p-3 text-sm"
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-800">
                {step.order}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-gray-900">{step.title}</p>
                  <span className="text-[10px] text-gray-400">{step.minutes} min</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">{step.talking_points[0]}</p>
                <Link
                  href={step.route}
                  className="text-xs text-brand-700 hover:underline mt-1 inline-flex items-center gap-1"
                >
                  {step.route}
                  <ArrowRight size={10} />
                </Link>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section id="metrics" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <TrendingUp size={16} className="text-indigo-600" />
          {t("pilot.salesDemoPage.demoMetrics")}
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Metric label={t("pilot.salesDemoPage.demoReadiness")} value={`${metrics.readiness_score}%`} />
          <Metric label={t("pilot.salesDemoPage.buyersFound")} value={metrics.buyers_found} />
          <Metric label={t("pilot.salesDemoPage.opportunities")} value={metrics.opportunities} />
          <Metric label={t("pilot.salesDemoPage.activeDeals")} value={metrics.active_deals} />
          <Metric label={t("pilot.salesDemoPage.pipelineUsd")} value={metrics.pipeline_value_usd.toLocaleString()} />
          <Metric label={t("pilot.salesDemoPage.forecastUsd")} value={metrics.revenue_forecast_usd.toLocaleString()} />
          <Metric label={t("pilot.salesDemoPage.dealRooms")} value={metrics.deal_rooms} />
          <Metric label={t("factory.profileScore")} value={`${metrics.factory_profile_score}%`} />
        </div>
        <p className="text-xs text-gray-500">
          {t("pilot.salesDemoPage.buyerCountries")}: {metrics.buyer_countries.join(", ") || "—"}
        </p>
      </section>

      <section id="ctas" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Target size={16} className="text-indigo-600" />
          {t("pilot.salesDemoPage.nextActions")}
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          {overview.ctas.map((cta) => (
            <Link
              key={cta.id}
              href={cta.route}
              className="rounded-lg border border-gray-200 p-3 hover:border-brand-300 hover:bg-brand-50/30 transition-colors"
            >
              <p className="text-sm font-medium text-gray-900">{cta.title}</p>
              <p className="text-xs text-gray-500 mt-1">{cta.description}</p>
            </Link>
          ))}
        </div>
      </section>

      {launchValidation && (
        <section className="card p-4 space-y-2 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">{t("pilot.salesDemoPage.launchValidation")}</p>
            <Link href="/pilot-launch-validation" className="text-xs text-brand-700 hover:underline">
              {t("pilot.salesDemoPage.fullValidation")}
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              <p className="text-[10px] text-indigo-700">{t("pilot.launchValidation.launchReadiness")}</p>
              <p className="text-lg font-semibold tabular-nums">{launchValidation.readiness_score}%</p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">{t("pilot.launchValidation.adminFlow")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {launchValidation.admin_flow_ready}/{launchValidation.admin_flow_total}
              </p>
            </div>
            <div className="rounded-lg border border-sky-100 bg-sky-50/50 px-2 py-2">
              <p className="text-[10px] text-sky-700">{t("pilot.launchValidation.tenantFlow")}</p>
              <p className="text-lg font-semibold tabular-nums">
                {launchValidation.tenant_flow_ready}/{launchValidation.tenant_flow_total}
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">{t("pilot.launchValidation.sectionBlockers")}</p>
              <p className="text-lg font-semibold tabular-nums">{launchValidation.blocker_count}</p>
            </div>
          </div>
        </section>
      )}

      {!overview.execution_data_present && (
        <section className="card p-4 border-amber-200 bg-amber-50/40">
          <p className="text-sm font-medium text-amber-900 flex items-center gap-1.5">
            <XCircle size={16} />
            {t("pilot.salesDemoPage.notSeeded")}
          </p>
          <p className="text-xs text-amber-800 mt-1">
            {t("pilot.salesDemoPage.seedHint")}
          </p>
          <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline mt-2 inline-block">
            {t("pilot.salesDemoPage.openRealFactoryPilot")}
          </Link>
        </section>
      )}
    </PageShell>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-2 text-center">
      <p className="text-[10px] text-gray-500">{label}</p>
      <p className="text-sm font-semibold text-gray-900 tabular-nums">{value}</p>
    </div>
  );
}
