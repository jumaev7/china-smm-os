"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Factory,
  Loader2,
  RefreshCw,
  Rocket,
  Shield,
  Target,
  CircleDollarSign,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  FirstPilotReadinessStatus,
  RealFactoryPilotBlocker,
  RealFactoryPilotStatus,
  buyerAcquisitionEngineApi,
  realFactoryPilotApi,
  pilotLaunchValidationApi,
  revenueEngineApi,
} from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/ui/PageStates";
import {
  PageHeader,
  PageShell,
  ScoreCard,
  StatusBadge,
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

type ReadinessStatus = FirstPilotReadinessStatus;

const READINESS_STYLES: Record<ReadinessStatus, string> = {
  ready: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-800",
  blocked: "bg-red-100 text-red-800",
};

const STATUS_VARIANT: Record<
  RealFactoryPilotStatus,
  "success" | "warning" | "danger" | "neutral"
> = {
  not_started: "neutral",
  in_progress: "warning",
  blocked: "danger",
  ready_for_demo: "warning",
  ready_for_live_pilot: "success",
  live_pilot_started: "success",
  completed: "success",
};

function ScoreRing({ score }: { score: number }) {
  const color =
    score >= 80
      ? "text-emerald-600 border-emerald-200 bg-emerald-50"
      : score >= 50
        ? "text-amber-600 border-amber-200 bg-amber-50"
        : "text-gray-600 border-gray-200 bg-gray-50";
  return (
    <div
      className={cn(
        "inline-flex items-center justify-center w-20 h-20 rounded-full border-4 font-bold text-2xl tabular-nums",
        color,
      )}
    >
      {score}
    </div>
  );
}

export default function RealFactoryPilotPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <RealFactoryPilotPageContent />
    </AdminAuthGuard>
  );
}

function RealFactoryPilotPageContent() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["real-factory-pilot-overview"],
    queryFn: () => realFactoryPilotApi.overview().then((r) => r.data),
  });

  const { data: summary } = useQuery({
    queryKey: ["real-factory-pilot-summary"],
    queryFn: () => realFactoryPilotApi.summary().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: buyerEngineReadiness } = useQuery({
    queryKey: ["real-factory-pilot-buyer-engine", overview?.workspace?.tenant_id],
    queryFn: () =>
      buyerAcquisitionEngineApi
        .summaryWidget({
          tenant_id: overview?.workspace?.tenant_id ?? undefined,
        })
        .then((r) => r.data),
    enabled: !!overview?.workspace?.tenant_id,
  });

  const { data: revenueReadiness } = useQuery({
    queryKey: ["real-factory-pilot-revenue-readiness", overview?.workspace?.tenant_id],
    queryFn: () =>
      revenueEngineApi
        .revenueReadinessPanel({
          tenant_id: overview?.workspace?.tenant_id ?? undefined,
        })
        .then((r) => r.data),
    enabled: !!overview?.workspace?.tenant_id,
  });

  const { data: launchValidation } = useQuery({
    queryKey: ["pilot-launch-validation-real-factory-panel"],
    queryFn: () => pilotLaunchValidationApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const refreshMutation = useMutation({
    mutationFn: () => realFactoryPilotApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(`Pilot assessment refreshed — score ${data.readiness_score}%`);
      qc.invalidateQueries({ queryKey: ["real-factory-pilot"] });
    },
    onError: () => toast.error("Refresh failed"),
  });

  if (isLoading) return <LoadingState label="Loading real factory pilot workspace…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load overview"}
        onRetry={() => refetch()}
      />
    );
  }

  const workspace = overview.workspace;
  const blockers = overview.blockers as RealFactoryPilotBlocker[];
  const warnings = overview.warnings as RealFactoryPilotBlocker[];

  return (
    <PageShell>
      <PageHeader
        title={t("pilot.realFactoryPilot.title")}
        subtitle={t("pilot.realFactoryPilot.subtitle")}
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-secondary text-sm inline-flex items-center gap-1.5"
              disabled={refreshMutation.isPending}
              onClick={() => refreshMutation.mutate()}
            >
              {refreshMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
              {t("pilot.refresh")}
            </button>
            <Link href="/factory-partners" className="btn-secondary text-sm">
              {t("pilot.factoryPartners")}
            </Link>
          </div>
        }
      />

      <div className="card p-3 border-amber-100 bg-amber-50/50 text-xs text-amber-900 flex items-start gap-2">
        <Shield size={14} className="shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {/* 1. Pilot Overview */}
      <section className="card p-5 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900">{t("pilot.realFactoryPilot.sectionOverview")}</p>
          <StatusBadge variant={STATUS_VARIANT[overview.status]}>
            {overview.status.replace(/_/g, " ")}
          </StatusBadge>
        </div>
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={overview.readiness_score} />
          <div className="space-y-1 text-sm">
            {overview.factory_identified ? (
              <>
                <p className="font-medium text-gray-900">{overview.company_name}</p>
                <p className="text-xs text-gray-500">
                  Checklist: {overview.checklist_completed}/{overview.checklist_total}
                </p>
                <p className="text-xs text-gray-500">
                  Blockers: {overview.blocker_count} · Warnings: {overview.warning_count}
                </p>
              </>
            ) : (
              <EmptyState
                title={t("pilot.realFactoryPilot.noFactorySelected")}
                description="Approve a non-demo factory application in Factory Partners."
              />
            )}
          </div>
          <ScoreCard
            title={t("pilot.realFactoryPilot.pilotReadiness")}
            score={overview.readiness_score}
            subtitle={
              overview.status === "completed"
                ? "Pilot workspace complete"
                : "Complete checklist before live pilot"
            }
            className="ml-auto min-w-[140px]"
          />
        </div>
      </section>

      {/* 2. Selected Factory */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Factory size={16} className="text-brand-600" />
          {t("pilot.realFactoryPilot.sectionSelectedFactory")}
        </p>
        {workspace.factory_identified ? (
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 text-xs">
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("pilot.realFactoryPilot.company")}</p>
              <p className="font-medium text-gray-900">{workspace.company_name}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("pilot.realFactoryPilot.tenant")}</p>
              <p className="font-medium">{workspace.tenant_id ? t("pilot.realFactoryPilot.provisioned") : t("pilot.realFactoryPilot.pending")}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("pilot.realFactoryPilot.subscription")}</p>
              <p className="font-medium capitalize">{workspace.subscription_status ?? "—"}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("pilot.realFactoryPilot.adminUser")}</p>
              <p className="font-medium truncate">{workspace.admin_user_email ?? "—"}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("factory.profileScore")}</p>
              <p className="font-medium tabular-nums">{workspace.factory_profile_score}/100</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("factory.sectionProductCatalog")}</p>
              <p className="font-medium tabular-nums">{workspace.catalog_count} items</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("factory.sectionBuyerOpportunities")}</p>
              <p className="font-medium tabular-nums">{workspace.buyer_opportunity_count}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("nav.marketplace")}</p>
              <p className="font-medium tabular-nums">{workspace.marketplace_activity_count}</p>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-500">{t("pilot.realFactoryPilot.noFactoryWorkspace")}</p>
        )}
      </section>

      {/* 3. Readiness Score */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900">{t("pilot.realFactoryPilot.sectionReadiness")}</p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {overview.readiness.components.map((c) => (
            <div
              key={c.key}
              className="rounded-lg border border-gray-100 px-3 py-2 text-xs space-y-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-gray-700 font-medium">{c.label}</span>
                <span
                  className={cn(
                    "px-1.5 py-0.5 rounded text-[10px] font-medium",
                    READINESS_STYLES[c.status],
                  )}
                >
                  {c.score}
                </span>
              </div>
              {c.details && <p className="text-gray-500 line-clamp-2">{c.details}</p>}
            </div>
          ))}
        </div>
      </section>

      {buyerEngineReadiness && (
        <section className="card p-5 space-y-3 border-cyan-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Target size={16} className="text-cyan-700" />
              {t("pilot.realFactoryPilot.buyerAcquisitionReadiness")}
            </p>
            <Link href="/buyer-acquisition-engine" className="text-xs text-brand-700 hover:underline">
              {t("deal.openBuyerEngine")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-2 text-xs">
            <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 px-3 py-2">
              <p className="text-gray-500">{t("buyer.readinessKpi")}</p>
              <p className="font-semibold tabular-nums text-cyan-900">
                {buyerEngineReadiness.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("factory.totalBuyers")}</p>
              <p className="font-medium tabular-nums">{buyerEngineReadiness.total_buyers}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("buyer.highMatch")}</p>
              <p className="font-medium tabular-nums">{buyerEngineReadiness.matched_buyers}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("buyer.activePipelineKpi")}</p>
              <p className="font-medium tabular-nums">
                {buyerEngineReadiness.active_pipeline_leads}
              </p>
            </div>
          </div>
          {buyerEngineReadiness.top_buyer_name && (
            <p className="text-xs text-gray-600">
              Top match: {buyerEngineReadiness.top_buyer_name} (score{" "}
              {buyerEngineReadiness.top_buyer_score})
            </p>
          )}
          <p className="text-[10px] text-gray-400">{buyerEngineReadiness.safety_notice}</p>
        </section>
      )}

      {revenueReadiness && (
        <section className="card p-5 space-y-3 border-emerald-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CircleDollarSign size={16} className="text-emerald-700" />
              {t("pilot.realFactoryPilot.revenueReadiness")}
            </p>
            <Link href="/revenue-engine" className="text-xs text-brand-700 hover:underline">
              {t("deal.openRevenueEngine")}
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-2 text-xs">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2">
              <p className="text-gray-500">{t("revenue.readiness")}</p>
              <p className="font-semibold tabular-nums text-emerald-900">
                {revenueReadiness.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.revenueHealth")}</p>
              <p className="font-medium capitalize">{revenueReadiness.health_status}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.activeDeals")}</p>
              <p className="font-medium tabular-nums">{revenueReadiness.active_deals}</p>
            </div>
            <div className="rounded-lg border border-gray-100 px-3 py-2">
              <p className="text-gray-500">{t("revenue.sectionForecast")}</p>
              <p className="font-medium capitalize">{revenueReadiness.forecast_quality}</p>
            </div>
          </div>
          <p className="text-xs text-gray-600">{revenueReadiness.message}</p>
          <p className="text-[10px] text-gray-400">{revenueReadiness.safety_notice}</p>
        </section>
      )}

      {/* 4. Execution Checklist */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900">{t("pilot.realFactoryPilot.sectionChecklist")}</p>
        <p className="text-xs text-gray-500">
          {overview.checklist.completed_count}/{overview.checklist.total_steps} steps complete (
          {overview.checklist.progress_percent}%)
        </p>
        <ul className="space-y-2">
          {overview.checklist.items.map((item) => (
            <li
              key={item.step}
              className={cn(
                "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs",
                item.completed
                  ? "border-emerald-100 bg-emerald-50/30"
                  : "border-gray-100 bg-gray-50/30",
              )}
            >
              {item.completed ? (
                <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <XCircle size={14} className="text-gray-400 shrink-0 mt-0.5" />
              )}
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-800">{item.label}</p>
                {item.details && <p className="text-gray-500 mt-0.5">{item.details}</p>}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* 5. Blockers & Warnings */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <AlertTriangle size={16} className="text-amber-600" />
          {t("pilot.realFactoryPilot.sectionBlockers")}
        </p>
        {blockers.length === 0 && warnings.length === 0 ? (
          <p className="text-sm text-emerald-700 flex items-center gap-1.5">
            <CheckCircle2 size={16} />
            {t("pilot.realFactoryPilot.noBlockersWarnings")}
          </p>
        ) : (
          <ul className="space-y-2">
            {[...blockers, ...warnings].map((b) => (
              <li
                key={`${b.blocker}-${b.label}`}
                className={cn(
                  "rounded-lg border px-3 py-2 text-xs",
                  b.severity === "critical"
                    ? "border-red-200 bg-red-50/50"
                    : "border-amber-200 bg-amber-50/50",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-gray-900">{b.label}</span>
                  <span className="text-[10px] uppercase tracking-wide text-gray-500">
                    {b.severity}
                  </span>
                </div>
                <p className="text-gray-600 mt-1">{b.message}</p>
                {b.route_hint && (
                  <Link href={b.route_hint} className="text-brand-700 hover:underline mt-1 inline-block">
                    {t("common.resolve")} →
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 6. Guided Admin Actions */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900">{t("pilot.realFactoryPilot.sectionActions")}</p>
        <p className="text-xs text-gray-500">{t("deal.hintsOnly")}</p>
        <div className="grid sm:grid-cols-2 gap-2">
          {overview.actions.map((action) => (
            <div
              key={action.action}
              className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                action.available ? "border-brand-100 bg-brand-50/30" : "border-gray-100 opacity-70",
              )}
            >
              <p className="font-medium text-gray-900">{action.label}</p>
              <p className="text-gray-500 mt-0.5">{action.description}</p>
              {action.available && (
                <Link href={action.route_hint} className="text-brand-700 hover:underline mt-1 inline-block">
                  {t("common.open")} →
                </Link>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* 7. Pilot Launch Notes */}
      {summary && summary.pilot_launch_notes.length > 0 && (
        <section className="card p-5 space-y-3 border-violet-100">
          <p className="text-sm font-semibold text-gray-900">{t("pilot.realFactoryPilot.sectionNotes")}</p>
          <ul className="text-xs text-gray-600 space-y-1.5 list-disc list-inside">
            {summary.pilot_launch_notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      )}

      {launchValidation && (
        <section className="card p-5 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">{t("pilot.realFactoryPilot.launchValidation")}</p>
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
          {launchValidation.primary_next_action && (
            <p className="text-xs text-gray-600">{launchValidation.primary_next_action}</p>
          )}
        </section>
      )}

      {/* 8. Next Best Action */}
      <section className="card p-5 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Target size={16} className="text-violet-600" />
          {t("pilot.realFactoryPilot.sectionNextAction")}
        </p>
        {overview.next_best_action ? (
          <div className="rounded-lg border border-violet-200 bg-violet-50/50 px-4 py-3 text-sm">
            <p className="font-semibold text-gray-900">{overview.next_best_action.title}</p>
            <p className="text-gray-600 mt-1 text-xs">{overview.next_best_action.description}</p>
            {overview.next_best_action.route_hint && (
              <Link
                href={overview.next_best_action.route_hint}
                className="btn-primary text-xs mt-3 inline-flex"
              >
                {t("pilot.realFactoryPilot.takeAction")}
              </Link>
            )}
          </div>
        ) : (
          <p className="text-sm text-emerald-700 flex items-center gap-1.5">
            <Rocket size={16} />
            {t("pilot.realFactoryPilot.readyForReview")}
          </p>
        )}
        <div className="flex flex-wrap gap-2 pt-2">
          <Link href="/pilot-onboarding" className="text-xs text-brand-700 hover:underline">
            {t("nav.pilotOnboarding")}
          </Link>
          <Link href="/first-pilot-client" className="text-xs text-brand-700 hover:underline">
            {t("nav.firstPilotClient")}
          </Link>
          <Link href="/production-deployment" className="text-xs text-brand-700 hover:underline">
            {t("nav.productionDeployment")}
          </Link>
          <Link href="/executive-copilot" className="text-xs text-brand-700 hover:underline">
            {t("nav.executiveCopilot")}
          </Link>
        </div>
      </section>
    </PageShell>
  );
}
