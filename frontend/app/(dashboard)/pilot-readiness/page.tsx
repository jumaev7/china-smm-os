"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Loader2,
  RefreshCw,
  Server,
  Shield,
  XCircle,
} from "lucide-react";
import { pilotReadinessApi, PilotReadinessStatus } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/components/ui/PageStates";
import { DashboardSkeleton } from "@/components/ui/Skeleton";
import {
  ExecutiveKpiBar,
  PageHeader,
  PageShell,
  ScoreCard,
  StatusBadge,
} from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

const STATUS_VARIANT: Record<PilotReadinessStatus, "success" | "warning" | "danger"> = {
  ready: "success",
  warning: "warning",
  blocked: "danger",
};

const ROUTE_STATUS_ICON = {
  pass: CheckCircle2,
  slow: AlertTriangle,
  fail: XCircle,
  denied: Shield,
  skipped: AlertTriangle,
} as const;

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
        "inline-flex items-center justify-center w-24 h-24 rounded-full border-4 font-bold text-3xl tabular-nums",
        color,
      )}
    >
      {score}
    </div>
  );
}

export default function PilotReadinessPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotReadinessPageContent />
    </AdminAuthGuard>
  );
}

function PilotReadinessPageContent() {
  const { t } = useTranslation();

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["pilot-readiness-overview"],
    queryFn: () => pilotReadinessApi.overview().then((r) => r.data),
    refetchInterval: 60_000,
  });

  if (isLoading) return <DashboardSkeleton />;
  if (isError || !data)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load pilot readiness"}
        onRetry={() => refetch()}
      />
    );

  const kpis = [
    { label: "Briefs", value: data.briefs_count },
    { label: "Open tasks", value: data.content_tasks_count },
    { label: "Approved content", value: data.approved_content_count },
    { label: "Scheduled / published", value: data.scheduled_published_content_count },
    { label: "Routes pass", value: `${data.routes_pass_count}/${data.route_audits.length}` },
    { label: "Open issues", value: data.open_issues.length },
  ];

  const healthCards = [
    data.demo_tenant_health,
    data.auth_rbac_status,
    data.backend_status,
    data.database_status,
  ];

  return (
    <PageShell>
      <PageHeader
        title="Pilot Readiness Dashboard"
        subtitle="Demo tenant health, auth/RBAC, infrastructure, content metrics, and route stability for pilot demo prep."
        actions={
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="btn-secondary text-xs flex items-center gap-1.5"
          >
            {isFetching ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Refresh
          </button>
        }
      />

      <div className="card p-5 flex flex-wrap items-center gap-6">
        <ScoreRing score={data.readiness_score} />
        <div className="space-y-2">
          <StatusBadge variant={STATUS_VARIANT[data.status]}>{data.status}</StatusBadge>
          <p className="text-xs text-gray-500 max-w-md">{data.safety_notice}</p>
          <p className="text-[10px] text-gray-400">
            Generated {new Date(data.generated_at).toLocaleString()}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <Link href="/pilot-launch-validation" className="btn-secondary text-xs">
            Launch Validation
          </Link>
          <Link href="/real-factory-pilot" className="btn-secondary text-xs">
            Real Factory Pilot
          </Link>
        </div>
      </div>

      <ExecutiveKpiBar items={kpis} />

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {healthCards.map((c) => (
          <ScoreCard
            key={c.key}
            title={c.label}
            score={c.score}
            subtitle={c.message ?? undefined}
          />
        ))}
      </div>

      {data.open_issues.length > 0 && (
        <div className="card divide-y divide-gray-100">
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <AlertTriangle size={16} className="text-amber-500" />
              Open issues ({data.open_issues.length})
            </p>
          </div>
          {data.open_issues.map((issue) => (
            <div key={issue} className="px-4 py-2.5 text-xs text-amber-900 bg-amber-50/30">
              {issue}
            </div>
          ))}
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <p className="text-sm font-semibold text-gray-900">Route stability audit</p>
          <span className="text-[10px] text-gray-400">
            {data.routes_pass_count} pass · {data.routes_fail_count} fail
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-100 bg-gray-50/50">
                <th className="px-3 py-2 font-medium">Route</th>
                <th className="px-3 py-2 font-medium">Audience</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">API</th>
                <th className="px-3 py-2 font-medium">HTTP</th>
                <th className="px-3 py-2 font-medium">Ms</th>
                <th className="px-3 py-2 font-medium">Notes</th>
              </tr>
            </thead>
            <tbody>
              {data.route_audits.map((row) => {
                const Icon = ROUTE_STATUS_ICON[row.status] ?? AlertTriangle;
                const href = row.canonical_route ?? row.route;
                return (
                  <tr key={row.route} className="border-b border-gray-50 hover:bg-gray-50/50">
                    <td className="px-3 py-2">
                      <Link href={href} className="text-brand-700 hover:underline font-mono">
                        {row.route}
                      </Link>
                      {row.canonical_route && row.canonical_route !== row.route && (
                        <span className="block text-[10px] text-gray-400">
                          → {row.canonical_route}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 capitalize text-gray-600">{row.audience}</td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1 capitalize">
                        <Icon
                          size={14}
                          className={cn(
                            row.status === "pass" && "text-emerald-500",
                            row.status === "slow" && "text-amber-500",
                            row.status === "fail" && "text-red-500",
                          )}
                        />
                        {row.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-gray-600 max-w-[140px] truncate" title={row.api_probe ?? ""}>
                      {row.api_probe?.replace("/api/v1/", "") ?? "—"}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{row.api_status_code ?? "—"}</td>
                    <td className="px-3 py-2 tabular-nums">{row.duration_ms ?? "—"}</td>
                    <td className="px-3 py-2 text-gray-500 max-w-[200px] truncate" title={row.issue ?? ""}>
                      {row.issue ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[10px] text-gray-400 text-center pb-4">
        {t("pilot.launchValidation.safetyNotice")} Verify tenant routes as demo@factory.local and admin routes as admin@example.com.
      </p>
    </PageShell>
  );
}
