"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Loader2,
  RefreshCw,
  Shield,
  Users,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  PilotLaunchValidationStatus,
  pilotLaunchValidationApi,
} from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
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
import { useTranslation } from "@/lib/I18nProvider";

const STATUS_VARIANT: Record<
  PilotLaunchValidationStatus,
  "success" | "warning" | "danger"
> = {
  ready: "success",
  warning: "warning",
  blocked: "danger",
};

const STATUS_ICON: Record<PilotLaunchValidationStatus, typeof CheckCircle2> = {
  ready: CheckCircle2,
  warning: AlertTriangle,
  blocked: XCircle,
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

export default function PilotLaunchValidationPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotLaunchValidationPageContent />
    </AdminAuthGuard>
  );
}

function PilotLaunchValidationPageContent() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["pilot-launch-validation-overview"],
    queryFn: () => pilotLaunchValidationApi.overview().then((r) => r.data),
  });

  const { data: readiness } = useQuery({
    queryKey: ["pilot-launch-validation-readiness"],
    queryFn: () => pilotLaunchValidationApi.readiness().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: adminFlow } = useQuery({
    queryKey: ["pilot-launch-validation-admin-flow"],
    queryFn: () => pilotLaunchValidationApi.adminFlow().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: tenantFlow } = useQuery({
    queryKey: ["pilot-launch-validation-tenant-flow"],
    queryFn: () => pilotLaunchValidationApi.tenantFlow().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: dataCompleteness } = useQuery({
    queryKey: ["pilot-launch-validation-data"],
    queryFn: () => pilotLaunchValidationApi.dataCompleteness().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: clientFacing } = useQuery({
    queryKey: ["pilot-launch-validation-client-facing"],
    queryFn: () => pilotLaunchValidationApi.clientFacingReadiness().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: blockers } = useQuery({
    queryKey: ["pilot-launch-validation-blockers"],
    queryFn: () => pilotLaunchValidationApi.blockers().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: nextActions } = useQuery({
    queryKey: ["pilot-launch-validation-next-actions"],
    queryFn: () => pilotLaunchValidationApi.nextActions().then((r) => r.data),
    enabled: !!overview,
  });

  const refreshMutation = useMutation({
    mutationFn: () => pilotLaunchValidationApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["pilot-launch-validation"] });
      refetch();
    },
    onError: (e: Error) => toast.error(e.message || t("pilot.refreshFailed")),
  });

  if (isLoading) return <DashboardSkeleton />;
  if (isError || !overview)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("pilot.launchValidation.loadError")}
        onRetry={() => refetch()}
      />
    );

  return (
    <PageShell>
      <PageHeader
        title={t("pilot.launchValidation.title")}
        subtitle={t("pilot.launchValidation.subtitle")}
        icon={ClipboardCheck}
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
            <Link href="/pilot-sales-demo" className="btn-secondary text-sm">
              {t("pilot.salesDemo")}
            </Link>
            <Link href="/real-factory-pilot" className="btn-secondary text-sm">
              {t("pilot.executionReport")}
            </Link>
          </>
        }
      />

      <div className="card-premium p-3 border-brand-100 bg-brand-50/30 text-xs text-brand-900 flex items-start gap-2">
        <Shield size={14} className="shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {/* 1. Validation Overview */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900">{t("pilot.launchValidation.sectionOverview")}</p>
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={overview.readiness_score} />
          <div className="flex-1 min-w-[200px]">
            <ExecutiveKpiBar
              healthScore={overview.readiness_score}
              healthLabel={t("pilot.launchValidation.launchReadiness")}
              items={[
                {
                  label: t("pilot.launchValidation.adminFlow"),
                  value: `${overview.admin_flow_ready}/${overview.admin_flow_total}`,
                },
                {
                  label: t("pilot.launchValidation.tenantFlow"),
                  value: `${overview.tenant_flow_ready}/${overview.tenant_flow_total}`,
                },
                {
                  label: t("pilot.launchValidation.dataComplete"),
                  value: `${overview.data_ready_count}/${overview.data_total}`,
                },
                {
                  label: t("pilot.launchValidation.clientPages"),
                  value: `${overview.client_facing_ready}/${overview.client_facing_total}`,
                },
              ]}
            />
          </div>
        </div>
        {overview.company_name && (
          <p className="text-sm text-gray-600">
            Factory: {overview.company_name}
            {overview.implementation_complete ? " — validation complete" : ""}
          </p>
        )}
        {!overview.execution_data_present && (
          <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2">
            Seed [PILOT_EXECUTION_V1] via POST /api/v1/pilot-execution/seed-pilot-data for full validation.
          </p>
        )}
        {readiness && (
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {readiness.components.map((c) => (
              <div key={c.key} className="rounded-lg border border-gray-100 p-2 text-center">
                <p className="text-[10px] text-gray-500 truncate">{c.label}</p>
                <p className="text-lg font-semibold tabular-nums">{c.score}</p>
                <StatusBadge variant={STATUS_VARIANT[c.status]} className="text-[10px]">
                  {c.status}
                </StatusBadge>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 2. Admin Flow */}
      {adminFlow && (
        <section className="card p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Users size={16} />
            {t("pilot.launchValidation.sectionAdminFlow")} ({adminFlow.ready_count}/{adminFlow.items.length} ready)
          </p>
          <div className="space-y-2">
            {adminFlow.items.map((item) => (
              <FlowRow key={item.id} item={item} />
            ))}
          </div>
        </section>
      )}

      {/* 3. Tenant Flow */}
      {tenantFlow && (
        <section className="card p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Users size={16} />
            {t("pilot.launchValidation.sectionTenantFlow")} ({tenantFlow.ready_count}/{tenantFlow.items.length} ready)
          </p>
          <div className="space-y-2">
            {tenantFlow.items.map((item) => (
              <FlowRow key={item.id} item={item} />
            ))}
          </div>
        </section>
      )}

      {/* 4. Data Completeness */}
      {dataCompleteness && (
        <section className="card p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Database size={16} />
            {t("pilot.launchValidation.sectionDataCompleteness")} ({dataCompleteness.ready_count}/{dataCompleteness.items.length} ready)
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {dataCompleteness.items.map((item) => {
              const Icon = STATUS_ICON[item.status];
              return (
                <div
                  key={item.id}
                  className="rounded-lg border border-gray-100 p-3 space-y-1"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-gray-900">{item.label}</p>
                    <Icon
                      size={14}
                      className={cn(
                        item.status === "ready" && "text-emerald-600",
                        item.status === "warning" && "text-amber-600",
                        item.status === "blocked" && "text-red-600",
                      )}
                    />
                  </div>
                  <p className="text-xs text-gray-500">
                    {item.count} / min {item.required_min}
                  </p>
                  {item.reason && (
                    <p className="text-xs text-gray-600 line-clamp-2">{item.reason}</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 5. Client-Facing Readiness */}
      {clientFacing && (
        <section className="card p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-900">
            {t("pilot.launchValidation.sectionClientFacing")} ({clientFacing.ready_count}/{clientFacing.pages.length} ready)
          </p>
          <div className="space-y-2">
            {clientFacing.pages.map((page) => (
              <div
                key={page.page}
                className="flex flex-wrap items-start justify-between gap-2 rounded-lg border border-gray-100 p-3"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Link href={page.route} className="text-sm font-medium text-brand-700 hover:underline">
                      {page.page.replace(/_/g, " ")}
                    </Link>
                    <StatusBadge variant={STATUS_VARIANT[page.status]}>{page.status}</StatusBadge>
                  </div>
                  {page.reason && <p className="text-xs text-gray-500 mt-1">{page.reason}</p>}
                  {page.missing_items.length > 0 && (
                    <p className="text-xs text-amber-700 mt-1">
                      {t("pilot.launchValidation.missing")} {page.missing_items.join(", ")}
                    </p>
                  )}
                </div>
                {page.next_action && (
                  <p className="text-xs text-gray-500 max-w-xs">{page.next_action}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 6. Blockers */}
      {blockers && (
        <section className="card p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-900">
            {t("pilot.launchValidation.sectionBlockers")} ({blockers.blocked_count} blocked · {blockers.warning_count} warnings)
          </p>
          {blockers.blockers.length === 0 ? (
            <p className="text-sm text-emerald-700 flex items-center gap-1">
              <CheckCircle2 size={14} />
              {t("pilot.launchValidation.noBlockers")}
            </p>
          ) : (
            <ul className="space-y-2">
              {blockers.blockers.map((b) => (
                <li
                  key={`${b.category}-${b.id}`}
                  className={cn(
                    "rounded-lg border p-3 text-sm",
                    b.severity === "blocked"
                      ? "border-red-100 bg-red-50/50"
                      : "border-amber-100 bg-amber-50/50",
                  )}
                >
                  <p className="font-medium text-gray-900">
                    {b.label}
                    <span className="text-xs text-gray-500 ml-2">({b.category})</span>
                  </p>
                  {b.reason && <p className="text-xs text-gray-600 mt-1">{b.reason}</p>}
                  {b.next_action && (
                    <p className="text-xs text-brand-700 mt-1">{b.next_action}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* 7. Next Actions */}
      {nextActions && (
        <section className="card p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-900">{t("pilot.launchValidation.sectionNextActions")}</p>
          {nextActions.primary_action && (
            <p className="text-sm font-medium text-brand-800 bg-brand-50 border border-brand-100 rounded-lg p-3">
              {t("pilot.launchValidation.primary")} {nextActions.primary_action}
            </p>
          )}
          <ol className="list-decimal list-inside space-y-1 text-sm text-gray-700">
            {nextActions.actions.map((action, i) => (
              <li key={i}>{action}</li>
            ))}
          </ol>
        </section>
      )}
    </PageShell>
  );
}

function FlowRow({
  item,
}: {
  item: {
    id: string;
    label: string;
    route: string;
    status: PilotLaunchValidationStatus;
    reason?: string | null;
    next_action?: string | null;
  };
}) {
  const Icon = STATUS_ICON[item.status];
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-100 p-3">
      <div className="flex items-center gap-2 min-w-0">
        <Icon
          size={14}
          className={cn(
            "shrink-0",
            item.status === "ready" && "text-emerald-600",
            item.status === "warning" && "text-amber-600",
            item.status === "blocked" && "text-red-600",
          )}
        />
        <Link href={item.route} className="text-sm font-medium text-gray-900 hover:text-brand-700">
          {item.label}
        </Link>
        <StatusBadge variant={STATUS_VARIANT[item.status]}>{item.status}</StatusBadge>
      </div>
      {item.reason && (
        <p className="text-xs text-gray-500 max-w-md truncate">{item.reason}</p>
      )}
    </div>
  );
}
