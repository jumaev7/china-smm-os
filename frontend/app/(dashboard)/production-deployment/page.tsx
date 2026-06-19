"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  Database,
  Loader2,
  RefreshCw,
  Server,
  Shield,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  ProductionChecklistStatus,
  ProductionEnvStatus,
  ProductionItemStatus,
  productionDeploymentApi,
  realFactoryPilotApi,
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
  StatusBadge,
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

const ENV_STYLES: Record<ProductionEnvStatus, string> = {
  valid: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-800",
  critical: "bg-red-100 text-red-800",
};

const CHECKLIST_STYLES: Record<ProductionChecklistStatus, string> = {
  completed: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-800",
  blocked: "bg-red-100 text-red-800",
};

const ITEM_STYLES: Record<ProductionItemStatus, string> = {
  ready: "text-emerald-600",
  warning: "text-amber-600",
  blocked: "text-red-600",
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

export default function ProductionDeploymentPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <ProductionDeploymentPageContent />
    </AdminAuthGuard>
  );
}

function ProductionDeploymentPageContent() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["production-deployment-overview"],
    queryFn: () => productionDeploymentApi.overview().then((r) => r.data),
  });

  const { data: summary } = useQuery({
    queryKey: ["production-deployment-summary"],
    queryFn: () => productionDeploymentApi.summary().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: realPilotReadiness } = useQuery({
    queryKey: ["real-factory-pilot-production-panel"],
    queryFn: () => realFactoryPilotApi.summary().then((r) => r.data),
    enabled: !!overview,
  });

  const refreshMutation = useMutation({
    mutationFn: () => productionDeploymentApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(t("production.refreshSuccess", { score: data.production_readiness_score }));
      qc.invalidateQueries({ queryKey: ["production-deployment"] });
    },
    onError: () => toast.error(t("pilot.refreshFailed")),
  });

  if (isLoading) return <LoadingState label={t("production.loading")} />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("production.loadError")}
        onRetry={() => refetch()}
      />
    );
  }

  const { readiness, environment, checklist, backups, monitoring, security } = overview;

  return (
    <PageShell className="max-w-5xl space-y-6">
      <PageHeader
        title={t("production.title")}
        subtitle={t("production.subtitle")}
        icon={Cloud}
        actions={
          <button
            type="button"
            disabled={refreshMutation.isPending}
            onClick={() => refreshMutation.mutate()}
            className="btn-secondary text-sm flex items-center gap-1.5"
          >
            {refreshMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            {t("pilot.refreshAssessment")}
          </button>
        }
      />

      <p className="text-xs text-gray-500 border border-gray-100 rounded-lg px-3 py-2 bg-gray-50">
        {overview.safety_notice}
      </p>

      {realPilotReadiness && (
        <section className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">{t("production.realPilotPanel")}</p>
            <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline">
              {t("pilot.realFactoryPilot.title")} →
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <ScoreRing score={realPilotReadiness.readiness_score} />
            <div className="text-xs text-gray-600 space-y-1 flex-1">
              {realPilotReadiness.selected_factory?.company_name ? (
                <p>
                  {t("pilot.realFactoryPilot.company")}:{" "}
                  <span className="font-medium text-gray-900">
                    {realPilotReadiness.selected_factory.company_name}
                  </span>
                </p>
              ) : (
                <p>{t("pilot.realFactoryPilot.noFactorySelected")}</p>
              )}
              <p className="capitalize">
                {t("buyer.colStatus")}: {realPilotReadiness.status.replace(/_/g, " ")}
              </p>
              <p>
                {t("dashboard.criticalIssues")}: {realPilotReadiness.blockers.length} ·{" "}
                {t("dashboard.warnings")}: {realPilotReadiness.warnings.length}
              </p>
            </div>
          </div>
          {realPilotReadiness.pilot_launch_notes[0] && (
            <p className="text-xs text-gray-500">{realPilotReadiness.pilot_launch_notes[0]}</p>
          )}
        </section>
      )}

      {/* 1. Readiness Overview */}
      <section className="card p-4 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">{t("production.readinessOverview")}</h2>
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={overview.production_readiness_score} />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm flex-1">
            <div>
              <p className="text-[10px] uppercase text-gray-400">{t("production.deployment")}</p>
              <StatusBadge variant={overview.deployment_ready ? "success" : "warning"}>
                {overview.deployment_ready ? t("production.ready") : t("production.notReady")}
              </StatusBadge>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400">{t("production.environment")}</p>
              <p className="font-medium">
                {overview.environment_valid ? (
                  <span className="text-emerald-700">{t("production.valid")}</span>
                ) : (
                  <span className="text-amber-700">
                    {environment.critical_count} {t("systemStatus.health_critical").toLowerCase()}
                  </span>
                )}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400">{t("production.checklist")}</p>
              <p className="font-medium tabular-nums">
                {checklist.completed_count}/{checklist.items.length} ok
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400">{t("production.security")}</p>
              <p className="font-medium tabular-nums">{overview.security_score}/100</p>
            </div>
          </div>
        </div>
        <div className="grid sm:grid-cols-2 gap-2">
          {readiness.components.map((c) => (
            <div
              key={c.key}
              className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium text-gray-800">{c.label}</p>
                {c.details && <p className="text-[10px] text-gray-500">{c.details}</p>}
              </div>
              <span className="text-xs font-semibold tabular-nums">{c.score}</span>
            </div>
          ))}
        </div>
      </section>

      {/* 2. Environment Validation */}
      <section className="card p-4 space-y-3">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Server size={16} className="text-sky-600" />
          {t("production.environmentValidation")}
        </h2>
        <div className="space-y-2">
          {environment.checks.map((c) => (
            <div
              key={c.key}
              className="flex items-start justify-between gap-2 rounded-lg border border-gray-100 px-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium text-gray-800">{c.label}</p>
                <p className="text-[10px] text-gray-500">{c.message}</p>
              </div>
              <span
                className={cn(
                  "text-xs font-semibold px-2 py-0.5 rounded-full shrink-0",
                  ENV_STYLES[c.status],
                )}
              >
                {c.status}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* 3. Deployment Checklist */}
      <section className="card p-4 space-y-3">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <CheckCircle2 size={16} className="text-emerald-600" />
          {t("production.deploymentChecklist")}
        </h2>
        <div className="space-y-2">
          {checklist.items.map((item) => (
            <div
              key={item.key}
              className="flex items-start justify-between gap-2 rounded-lg border border-gray-100 px-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium text-gray-800">{item.label}</p>
                <p className="text-[10px] text-gray-500">{item.message}</p>
                {item.next_action && item.status !== "completed" && (
                  <p className="text-[10px] text-amber-700 mt-0.5">→ {item.next_action}</p>
                )}
              </div>
              <span
                className={cn(
                  "text-xs font-semibold px-2 py-0.5 rounded-full shrink-0",
                  CHECKLIST_STYLES[item.status],
                )}
              >
                {item.status}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* 4. Backup Readiness */}
      <section className="card p-4 space-y-3 border-violet-100">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Database size={16} className="text-violet-600" />
          {t("production.backupReadiness")}
        </h2>
        <div className="space-y-2">
          {backups.items.map((item) => (
            <div
              key={item.key}
              className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium text-gray-800">{item.label}</p>
                <p className="text-[10px] text-gray-500">{item.message}</p>
              </div>
              <span className={cn("text-xs font-semibold capitalize", ITEM_STYLES[item.status])}>
                {item.status}
              </span>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-500">
          Refer to PRODUCTION_DEPLOYMENT_GUIDE.md in the repository for the full backup checklist.
        </p>
      </section>

      {/* 5. Monitoring Readiness */}
      <section className="card p-4 space-y-3 border-sky-100">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <ActivityIcon />
          {t("production.monitoringReadiness")}
        </h2>
        <div className="space-y-2">
          {monitoring.items.map((item) => (
            <div
              key={item.key}
              className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium text-gray-800">{item.label}</p>
                <p className="text-[10px] text-gray-500">{item.message}</p>
              </div>
              <span className={cn("text-xs font-semibold capitalize", ITEM_STYLES[item.status])}>
                {item.status}
              </span>
            </div>
          ))}
        </div>
        <Link href="/system/stability" className="text-xs text-brand-700 hover:underline">
          {t("common.open")} {t("nav.systemStability")} →
        </Link>
      </section>

      {/* 6. Security Readiness */}
      <section className="card p-4 space-y-3 border-red-100">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Shield size={16} className="text-red-600" />
          {t("production.securityReadiness")}
        </h2>
        <div className="flex flex-wrap gap-4 text-sm">
          <div>
            <p className="text-[10px] uppercase text-gray-400">{t("deal.healthScore")}</p>
            <p className="font-semibold tabular-nums">{security.readiness_score}/100</p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400">{t("production.security")}</p>
            <p className="font-semibold tabular-nums">{security.protected_route_count}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400">{t("nav.audit")}</p>
            <p className="font-semibold tabular-nums text-red-700">{security.open_route_count}</p>
          </div>
        </div>
        {security.critical_findings.length > 0 && (
          <ul className="text-sm text-red-800 space-y-1">
            {security.critical_findings.map((f) => (
              <li key={f.key} className="flex items-start gap-1">
                <XCircle size={14} className="shrink-0 mt-0.5" />
                <span>
                  <strong>{f.label}:</strong> {f.message}
                </span>
              </li>
            ))}
          </ul>
        )}
        {security.warnings.length > 0 && (
          <ul className="text-sm text-amber-800 space-y-1">
            {security.warnings.map((f) => (
              <li key={f.key} className="flex items-start gap-1">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <span>
                  <strong>{f.label}:</strong> {f.message}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Link href="/admin-audit" className="text-xs text-brand-700 hover:underline">
          {t("nav.audit")} →
        </Link>
      </section>

      {/* 7. Production Summary */}
      {summary && (
        <section className="card p-4 space-y-3 border-emerald-100">
          <h2 className="text-sm font-semibold text-gray-900">{t("production.summary")}</h2>
          <div className="grid sm:grid-cols-3 gap-3 text-center text-xs">
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">{t("deal.readiness")}</p>
              <p className="text-lg font-semibold tabular-nums">{summary.readiness_score}%</p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">{t("dashboard.criticalIssues")}</p>
              <p className="text-lg font-semibold tabular-nums">{summary.blockers.length}</p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">{t("dashboard.warnings")}</p>
              <p className="text-lg font-semibold tabular-nums">{summary.warnings.length}</p>
            </div>
          </div>
          {summary.blockers.length > 0 && (
            <ul className="list-disc list-inside text-sm text-red-800">
              {summary.blockers.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
          {summary.next_action && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/50 px-3 py-2 text-sm">
              <p className="font-medium text-amber-900">
                {t("production.nextAction")} {summary.next_action.title}
              </p>
              <p className="text-xs text-amber-800">{summary.next_action.description}</p>
            </div>
          )}
          {summary.recommendations.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-semibold text-gray-700">{t("executive.recommendedActions")}</p>
              {summary.recommendations.slice(0, 5).map((r) => (
                <p key={r.id} className="text-xs text-gray-600">
                  [{r.priority}] {r.title}
                </p>
              ))}
            </div>
          )}
        </section>
      )}
    </PageShell>
  );
}

function ActivityIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="text-sky-600"
    >
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  );
}
