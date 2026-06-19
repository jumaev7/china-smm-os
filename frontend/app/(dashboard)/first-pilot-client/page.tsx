"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Rocket,
  Shield,
  Target,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  FirstPilotBlocker,
  FirstPilotOperationalStatus,
  FirstPilotReadinessStatus,
  FirstPilotRecommendationPriority,
  firstPilotClientApi,
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
  ScoreCard,
  StatusBadge,
} from "@/components/ui/design-system";

const READINESS_STYLES: Record<FirstPilotReadinessStatus, string> = {
  ready: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-800",
  blocked: "bg-red-100 text-red-800",
};

const OPERATIONAL_STYLES: Record<FirstPilotOperationalStatus, string> = {
  ready: "text-emerald-600",
  warning: "text-amber-600",
  blocked: "text-red-600",
  unavailable: "text-gray-400",
};

const PRIORITY_STYLES: Record<FirstPilotRecommendationPriority, string> = {
  high: "border-red-200 bg-red-50/50",
  medium: "border-amber-200 bg-amber-50/50",
  low: "border-gray-200 bg-gray-50/50",
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

export default function FirstPilotClientPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <FirstPilotClientPageContent />
    </AdminAuthGuard>
  );
}

function FirstPilotClientPageContent() {
  const qc = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["first-pilot-client-overview"],
    queryFn: () => firstPilotClientApi.overview().then((r) => r.data),
  });

  const { data: recommendations } = useQuery({
    queryKey: ["first-pilot-client-recommendations"],
    queryFn: () => firstPilotClientApi.recommendations().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: summary } = useQuery({
    queryKey: ["first-pilot-client-summary"],
    queryFn: () => firstPilotClientApi.summary().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: realFactoryPilotLink } = useQuery({
    queryKey: ["real-factory-pilot-first-pilot-link"],
    queryFn: () => realFactoryPilotApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
  });

  const refreshMutation = useMutation({
    mutationFn: () => firstPilotClientApi.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(`Readiness refreshed — score ${data.readiness_score}%`);
      qc.invalidateQueries({ queryKey: ["first-pilot-client"] });
    },
    onError: () => toast.error("Refresh failed"),
  });

  if (isLoading) return <LoadingState label="Loading first pilot client readiness…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load overview"}
        onRetry={() => refetch()}
      />
    );
  }

  const blockers = overview.blockers as FirstPilotBlocker[];

  return (
    <PageShell>
      <PageHeader
        title="First Pilot Client"
        subtitle="Prepare China SMM OS for onboarding the first real factory client — read-only assessment."
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
              Refresh
            </button>
            <Link href="/pilot-onboarding" className="btn-secondary text-sm">
              Pilot onboarding
            </Link>
          </div>
        }
      />

      <div className="card p-3 border-amber-100 bg-amber-50/50 text-xs text-amber-900 flex items-start gap-2">
        <Shield size={14} className="shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {realFactoryPilotLink && (
        <section className="card p-4 space-y-2 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Real Factory Pilot</p>
            <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline">
              Open pilot workspace →
            </Link>
          </div>
          <p className="text-xs text-gray-600">
            Execution checklist: {realFactoryPilotLink.checklist_progress}% · Status:{" "}
            <span className="capitalize font-medium">
              {realFactoryPilotLink.status.replace(/_/g, " ")}
            </span>
            {realFactoryPilotLink.company_name
              ? ` · ${realFactoryPilotLink.company_name}`
              : ""}
          </p>
        </section>
      )}

      {/* 1. Readiness Overview */}
      <section className="card p-5 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900">1. Readiness Overview</p>
          {overview.company_name && (
            <StatusBadge
              variant={overview.launch_ready ? "success" : "warning"}
            >
              {overview.launch_ready ? "Launch ready" : "In preparation"}
            </StatusBadge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={overview.readiness_score} />
          <div className="space-y-1 text-sm">
            {overview.client_identified ? (
              <>
                <p className="font-medium text-gray-900">{overview.company_name}</p>
                <p className="text-xs text-gray-500">
                  Onboarding: {overview.onboarding_status ?? "unknown"}
                </p>
                <p className="text-xs text-gray-500">
                  Blockers: {overview.blocker_count} ({overview.critical_blocker_count} critical)
                </p>
              </>
            ) : (
              <EmptyState
                title="No pilot client identified"
                description="Approve a real factory application (non-demo) in Factory Partners."
              />
            )}
          </div>
          <ScoreCard
            title="Launch readiness"
            score={overview.readiness_score}
            subtitle={
              overview.launch_ready
                ? "All critical checks passed"
                : "Complete blockers before launch"
            }
            className="ml-auto min-w-[140px]"
          />
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {overview.client_readiness.components.map((c) => (
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

      {/* 2. Operational Readiness */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900">2. Operational Readiness</p>
        <p className="text-xs text-gray-500">
          {overview.operational_readiness.ready_count}/{overview.operational_readiness.total}{" "}
          operational checks ready
        </p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {overview.operational_readiness.items.map((item) => (
            <div
              key={item.key}
              className="flex items-start gap-2 rounded-lg border border-gray-100 px-3 py-2 text-xs"
            >
              {item.ready ? (
                <CheckCircle2 size={14} className={OPERATIONAL_STYLES.ready} />
              ) : (
                <XCircle size={14} className={OPERATIONAL_STYLES[item.status]} />
              )}
              <div>
                <p className="font-medium text-gray-800">{item.label}</p>
                {item.message && <p className="text-gray-500 mt-0.5">{item.message}</p>}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 3. Launch Blockers */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <AlertTriangle size={16} className="text-amber-600" />
          3. Launch Blockers
        </p>
        {blockers.length === 0 ? (
          <p className="text-sm text-emerald-700 flex items-center gap-1.5">
            <CheckCircle2 size={16} />
            No launch blockers detected
          </p>
        ) : (
          <ul className="space-y-2">
            {blockers.map((b) => (
              <li
                key={b.blocker}
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
                    Resolve →
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 4. Recommendations */}
      {recommendations && (
        <section className="card p-5 space-y-4">
          <p className="text-sm font-semibold text-gray-900">4. Recommendations</p>
          {(["high_priority", "medium_priority", "low_priority"] as const).map((group) => {
            const items = recommendations[group];
            if (!items?.length) return null;
            const label =
              group === "high_priority"
                ? "High priority"
                : group === "medium_priority"
                  ? "Medium priority"
                  : "Low priority";
            return (
              <div key={group} className="space-y-2">
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                  {label}
                </p>
                {items.map((r) => (
                  <div
                    key={r.id}
                    className={cn("rounded-lg border px-3 py-2 text-xs", PRIORITY_STYLES[r.priority])}
                  >
                    <p className="font-medium text-gray-900">{r.title}</p>
                    <p className="text-gray-600 mt-0.5">{r.description}</p>
                    {r.route_hint && (
                      <Link href={r.route_hint} className="text-brand-700 hover:underline mt-1 inline-block">
                        Open →
                      </Link>
                    )}
                  </div>
                ))}
              </div>
            );
          })}
        </section>
      )}

      {/* 5. Pilot Summary */}
      {summary && (
        <section className="card p-5 space-y-4 border-brand-100">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Target size={16} className="text-brand-600" />
            5. Pilot Summary
          </p>
          <div className="grid sm:grid-cols-3 gap-3 text-center text-xs">
            <div className="rounded-lg border border-brand-100 bg-brand-50/50 px-2 py-3">
              <p className="text-[10px] text-brand-700">Readiness score</p>
              <p className="text-2xl font-semibold tabular-nums text-brand-900">
                {summary.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-3">
              <p className="text-[10px] text-gray-600">Operational</p>
              <p className="text-lg font-semibold">
                {summary.operational_ready ? "Ready" : "Pending"}
              </p>
            </div>
            <div className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-3">
              <p className="text-[10px] text-gray-600">Launch</p>
              <p className="text-lg font-semibold">
                {summary.launch_ready ? "Ready" : "Not yet"}
              </p>
            </div>
          </div>
        </section>
      )}

      {/* 6. Next Actions */}
      <section className="card p-5 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Rocket size={16} className="text-violet-600" />
          6. Next Actions
        </p>
        {overview.next_action ? (
          <div className="rounded-lg border border-violet-200 bg-violet-50/50 px-4 py-3 text-sm">
            <p className="font-semibold text-gray-900">{overview.next_action.title}</p>
            <p className="text-gray-600 mt-1 text-xs">{overview.next_action.description}</p>
            {overview.next_action.route_hint && (
              <Link
                href={overview.next_action.route_hint}
                className="btn-primary text-xs mt-3 inline-flex"
              >
                Take action
              </Link>
            )}
          </div>
        ) : (
          <p className="text-sm text-emerald-700">Pilot client appears ready for final review.</p>
        )}
        <div className="flex flex-wrap gap-2 pt-2">
          <Link href="/factory-partners" className="text-xs text-brand-700 hover:underline">
            Factory Partners
          </Link>
          <Link href="/pilot-onboarding" className="text-xs text-brand-700 hover:underline">
            Pilot Onboarding
          </Link>
          <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline">
            Real Factory Pilot
          </Link>
          <Link href="/factory-platform" className="text-xs text-brand-700 hover:underline">
            Factory Platform
          </Link>
          <Link href="/executive-copilot" className="text-xs text-brand-700 hover:underline">
            Executive Copilot
          </Link>
        </div>
      </section>
    </PageShell>
  );
}
