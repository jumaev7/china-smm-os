"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  CheckCircle2,
  Clapperboard,
  Loader2,
  Map,
  Presentation,
  RefreshCw,
  Route,
  Shield,
  Sparkles,
  Target,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import { DemoStepStatus, pilotDemoApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { useTranslation } from "@/lib/I18nProvider";
import {
  OVERVIEW_HEAVY_QUERY_OPTIONS,
  OVERVIEW_SECTION_QUERY_OPTIONS,
  OVERVIEW_WIDGET_QUERY_OPTIONS,
} from "@/lib/overview-query-options";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/ui/PageStates";
import { DashboardSkeleton } from "@/components/ui/Skeleton";
import {
  ExecutiveKpiBar,
  HealthIndicator,
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";

const STEP_VARIANT: Record<DemoStepStatus, "success" | "warning" | "danger" | "neutral"> = {
  ready: "success",
  warning: "warning",
  blocked: "danger",
  info: "neutral",
};

export default function PilotDemoPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotDemoPageContent />
    </AdminAuthGuard>
  );
}

function PilotDemoPageContent() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const {
    data: readiness,
    isLoading: readinessLoading,
    isError: readinessError,
    error: readinessErr,
    refetch: refetchReadiness,
  } = useQuery({
    queryKey: ["pilot-demo-readiness"],
    queryFn: () => pilotDemoApi.readiness().then((r) => r.data),
    ...OVERVIEW_WIDGET_QUERY_OPTIONS,
  });

  const { data: overview, isError: overviewError } = useQuery({
    queryKey: ["pilot-demo-overview"],
    queryFn: () => pilotDemoApi.overview().then((r) => r.data),
    enabled: !!readiness,
    ...OVERVIEW_HEAVY_QUERY_OPTIONS,
  });

  const { data: scenarios } = useQuery({
    queryKey: ["pilot-demo-scenarios"],
    queryFn: () => pilotDemoApi.scenarios().then((r) => r.data),
    enabled: !!readiness,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: factoryJourney } = useQuery({
    queryKey: ["pilot-demo-factory-owner"],
    queryFn: () => pilotDemoApi.factoryOwner().then((r) => r.data),
    enabled: !!readiness,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: executiveJourney } = useQuery({
    queryKey: ["pilot-demo-executive"],
    queryFn: () => pilotDemoApi.executive().then((r) => r.data),
    enabled: !!readiness,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const { data: presentationFlow } = useQuery({
    queryKey: ["pilot-demo-presentation-flow"],
    queryFn: () => pilotDemoApi.presentationFlow("factory_owner_demo").then((r) => r.data),
    enabled: !!readiness,
    ...OVERVIEW_SECTION_QUERY_OPTIONS,
  });

  const refreshMutation = useMutation({
    mutationFn: () => pilotDemoApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["pilot-demo"] });
      refetchReadiness();
    },
    onError: (e: Error) => toast.error(e.message || "Refresh failed"),
  });

  if (readinessLoading && !readiness) return <DashboardSkeleton />;
  if (readinessError || !readiness) {
    return <ErrorState error={readinessErr} onRetry={() => refetchReadiness()} />;
  }

  const metrics = overview?.metrics;
  const summary = overview?.summary;
  const readinessScore = overview?.readiness_score ?? readiness.readiness_score;

  return (
    <PageShell>
      <PageHeader
        title="Pilot Demo Center"
        subtitle="End-to-end presentation guide for factory owners and executives — read-only, no auto actions."
        icon={Clapperboard}
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
              Refresh assessment
            </button>
            <Link href="/pilot-launch" className="btn-secondary text-sm">
              Pilot Launch
            </Link>
          </>
        }
      />

      <div className="card-premium p-3 border-brand-100 bg-brand-50/30 text-xs text-brand-900 flex items-start gap-2">
        <Shield size={14} className="shrink-0 mt-0.5" />
        <span>{overview?.safety_notice ?? readiness.safety_notice}</span>
      </div>

      {overviewError && (
        <p className="text-xs text-amber-700 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2">
          {t("errors.sectionUnavailable")}
        </p>
      )}

      <ExecutiveKpiBar
        healthScore={readinessScore}
        healthLabel="Demo readiness"
        items={[
          { label: "Demo buyers", value: metrics?.demo_buyers ?? "—" },
          { label: "Opportunities", value: metrics?.demo_opportunities ?? "—" },
          {
            label: "Revenue (USD)",
            value: metrics ? metrics.demo_revenue_usd.toLocaleString() : "—",
          },
          { label: "Deals", value: metrics?.demo_deals ?? "—" },
          { label: "Marketplace", value: metrics?.demo_marketplace_opportunities ?? "—" },
        ]}
      />

      <section id="overview" className="card-premium p-5 space-y-4">
        <p className="section-title">Demo Overview</p>
        <div className="flex flex-wrap items-center gap-6">
          <HealthIndicator score={readinessScore} label="Readiness" size="lg" />
          <div className="text-sm text-gray-600 space-y-1">
            <p>
              Demo data:{" "}
              {overview?.demo_data_present ? (
                <span className="text-emerald-700 font-medium">present</span>
              ) : (
                <span className="text-amber-700 font-medium">
                  not seeded —{" "}
                  <Link href="/pilot-launch" className="underline">
                    seed in Pilot Launch
                  </Link>
                </span>
              )}
            </p>
            {overview?.demo_company_name && (
              <p>Company: {overview.demo_company_name}</p>
            )}
            {overview?.refreshed_at && (
              <p className="text-xs text-gray-400">
                Refreshed {new Date(overview.refreshed_at).toLocaleString()}
              </p>
            )}
          </div>
          {metrics && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 flex-1 min-w-[200px]">
              <Metric label="Buyers" value={metrics.demo_buyers} />
              <Metric label="Opportunities" value={metrics.demo_opportunities} />
              <Metric label="Revenue (USD)" value={metrics.demo_revenue_usd.toLocaleString()} />
              <Metric label="Marketplace" value={metrics.demo_marketplace_opportunities} />
              <Metric label="Deals" value={metrics.demo_deals} />
              <Metric label="Forecasts" value={metrics.demo_forecast_periods} />
            </div>
          )}
        </div>
      </section>

      <section id="scenarios" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Sparkles size={16} className="text-indigo-600" />
          Demo Scenarios
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          {(scenarios?.scenarios ?? []).map((s) => (
            <div
              key={s.id}
              className={cn(
                "rounded-lg border p-3 text-sm",
                s.id === overview?.active_scenario_id
                  ? "border-indigo-300 bg-indigo-50/40"
                  : "border-gray-200",
              )}
            >
              <p className="font-medium text-gray-900">{s.title}</p>
              <p className="text-xs text-gray-500 mt-1">{s.description}</p>
              <p className="text-[10px] text-gray-400 mt-2">
                ~{s.estimated_minutes} min · {s.recommended_for}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section id="factory-owner" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Route size={16} className="text-indigo-600" />
          Factory Owner Journey
          {factoryJourney && (
            <span className="text-xs font-normal text-gray-500">
              {factoryJourney.completed_steps}/{factoryJourney.total_steps} ready
            </span>
          )}
        </p>
        {factoryJourney ? (
          <JourneySteps steps={factoryJourney.steps} highlightId={factoryJourney.current_step_id} />
        ) : (
          <EmptyState message="Loading journey…" />
        )}
      </section>

      <section id="executive" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Presentation size={16} className="text-indigo-600" />
          Executive Journey
        </p>
        {executiveJourney ? (
          <JourneySteps steps={executiveJourney.steps} highlightId={executiveJourney.current_step_id} />
        ) : (
          <EmptyState message="Loading journey…" />
        )}
      </section>

      <section id="presentation" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Map size={16} className="text-indigo-600" />
          Presentation Flow
          {presentationFlow && (
            <span className="text-xs font-normal text-gray-500">
              ~{presentationFlow.estimated_total_minutes} min total
            </span>
          )}
        </p>
        {presentationFlow && (
          <ol className="space-y-2 text-sm">
            {presentationFlow.steps.map((step) => (
              <li key={step.order} className="flex gap-3 items-start">
                <span className="text-xs font-mono text-gray-400 w-5">{step.order}</span>
                <div className="flex-1">
                  <Link href={step.route} className="font-medium text-brand-700 hover:underline">
                    {step.title}
                  </Link>
                  <span className="text-xs text-gray-400 ml-2">({step.minutes} min)</span>
                  {step.talking_points[0] && (
                    <p className="text-xs text-gray-500 mt-0.5">{step.talking_points[0]}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section id="readiness" className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Target size={16} className="text-indigo-600" />
          Demo Readiness
        </p>
        {readiness && (
          <>
            {readiness.missing_data.length > 0 && (
              <div className="text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded-lg p-2">
                <p className="font-medium mb-1">Missing data</p>
                <ul className="list-disc list-inside space-y-0.5">
                  {readiness.missing_data.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </div>
            )}
            {readiness.broken_links.length > 0 && (
              <div className="text-xs text-red-800 bg-red-50 border border-red-100 rounded-lg p-2">
                <p className="font-medium mb-1">Broken API probes</p>
                <ul className="list-disc list-inside">
                  {readiness.broken_links.slice(0, 5).map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="grid sm:grid-cols-2 gap-2 text-xs">
              {readiness.items.slice(0, 8).map((item) => (
                <div
                  key={item.key}
                  className="flex items-center gap-2 rounded border border-gray-100 px-2 py-1.5"
                >
                  {item.status === "ok" ? (
                    <CheckCircle2 size={12} className="text-emerald-600 shrink-0" />
                  ) : (
                    <XCircle size={12} className="text-amber-600 shrink-0" />
                  )}
                  <span className="text-gray-700">{item.label}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="card p-4 space-y-2 border-indigo-200 bg-indigo-50/30">
        <p className="text-sm font-semibold text-gray-900">Next Recommended Step</p>
        <p className="text-sm text-gray-700">
          {summary?.what_to_show_next ?? "Run Pilot Launch seed, then refresh demo assessment."}
        </p>
        {overview?.next_recommended_step && (
          <p className="text-xs text-gray-500">
            Journey step: <code className="text-indigo-800">{overview.next_recommended_step}</code>
          </p>
        )}
        {summary?.estimated_presentation_minutes != null && (
          <p className="text-[10px] text-gray-400">
            Est. presentation: {summary.estimated_presentation_minutes} minutes
          </p>
        )}
      </section>
    </PageShell>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50/80 px-2 py-2 text-center">
      <p className="text-[10px] text-gray-500">{label}</p>
      <p className="text-sm font-semibold tabular-nums text-gray-900">{value}</p>
    </div>
  );
}

function JourneySteps({
  steps,
  highlightId,
}: {
  steps: {
    step: number;
    id: string;
    title: string;
    narrative: string;
    admin_route?: string | null;
    status: DemoStepStatus;
    message?: string | null;
  }[];
  highlightId?: string | null;
}) {
  return (
    <ol className="space-y-2">
      {steps.map((s) => (
        <li
          key={s.id}
          className={cn(
            "rounded-lg border p-3 text-sm",
            s.id === highlightId ? "border-indigo-300 bg-indigo-50/30" : "border-gray-100",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-400 font-mono">#{s.step}</span>
            <span className="font-medium text-gray-900">{s.title}</span>
            <StatusBadge variant={STEP_VARIANT[s.status]}>{s.status}</StatusBadge>
          </div>
          <p className="text-xs text-gray-600 mt-1">{s.narrative}</p>
          {s.message && <p className="text-[10px] text-gray-400 mt-1">{s.message}</p>}
          {s.admin_route && (
            <Link href={s.admin_route} className="text-xs text-brand-700 hover:underline mt-1 inline-block">
              Open {s.admin_route} →
            </Link>
          )}
        </li>
      ))}
    </ol>
  );
}
