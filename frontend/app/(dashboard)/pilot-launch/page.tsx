"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Database,
  Loader2,
  Play,
  RefreshCw,
  Rocket,
  Shield,
  Cloud,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  LaunchItemStatus,
  pilotLaunchApi,
  pilotDemoApi,
  productionDeploymentApi,
  QaStepStatus,
  SmokeStatus,
} from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/ui/PageStates";

const STATUS_STYLES: Record<LaunchItemStatus, string> = {
  completed: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-800",
  blocked: "bg-red-100 text-red-800",
};

const SMOKE_STYLES: Record<SmokeStatus, string> = {
  ok: "text-emerald-600",
  warning: "text-amber-600",
  error: "text-red-600",
  slow: "text-amber-600",
};

const QA_STYLES: Record<QaStepStatus, string> = {
  pass: "text-emerald-600",
  warning: "text-amber-600",
  fail: "text-red-600",
  skipped: "text-gray-400",
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

export default function PilotLaunchPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotLaunchPageContent />
    </AdminAuthGuard>
  );
}

function PilotLaunchPageContent() {
  const qc = useQueryClient();

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["pilot-launch-overview"],
    queryFn: () => pilotLaunchApi.overview().then((r) => r.data),
  });

  const { data: readiness } = useQuery({
    queryKey: ["pilot-launch-readiness"],
    queryFn: () => pilotLaunchApi.readiness().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: checklist } = useQuery({
    queryKey: ["pilot-launch-checklist"],
    queryFn: () => pilotLaunchApi.checklist().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: smoke } = useQuery({
    queryKey: ["pilot-launch-smoke"],
    queryFn: () => pilotLaunchApi.smokeTests().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: demoReadiness } = useQuery({
    queryKey: ["pilot-demo-readiness-panel"],
    queryFn: () => pilotDemoApi.readiness().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: deploymentSummary } = useQuery({
    queryKey: ["production-deployment-pilot-launch"],
    queryFn: () => productionDeploymentApi.summary().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: qa, refetch: refetchQa } = useQuery({
    queryKey: ["pilot-launch-qa"],
    queryFn: () => pilotLaunchApi.runQa().then((r) => r.data),
    enabled: false,
  });

  const seedMutation = useMutation({
    mutationFn: () => pilotLaunchApi.seedDemoData(false).then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      qc.invalidateQueries({ queryKey: ["pilot-launch"] });
      refetch();
    },
    onError: (e: Error) => toast.error(e.message || "Seed failed"),
  });

  const qaMutation = useMutation({
    mutationFn: () => pilotLaunchApi.runQa().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(`QA: ${data.pass_count}/${data.steps.length} passed`);
      qc.setQueryData(["pilot-launch-qa"], data);
      refetchQa();
      refetch();
    },
    onError: (e: Error) => toast.error(e.message || "QA failed"),
  });

  if (isLoading) return <LoadingState message="Loading pilot launch…" />;
  if (isError || !overview)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load pilot launch"}
        onRetry={() => refetch()}
      />
    );

  const qaData = qaMutation.data ?? qa;
  const blockers = overview.blockers;
  const nextActions = overview.next_actions;

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Rocket className="text-violet-600" size={22} />
            Pilot Launch
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            QA checklist, demo data, smoke tests, and launch readiness for first pilot client demo.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="btn-secondary text-xs flex items-center gap-1"
        >
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      <p className="text-xs text-gray-500 flex items-center gap-1">
        <Shield size={12} />
        {overview.safety_notice}
      </p>

      {demoReadiness && (
        <section className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-900">Demo Readiness Panel</h2>
            <Link href="/pilot-demo" className="text-xs text-brand-700 hover:underline">
              Pilot demo center →
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <ScoreRing score={demoReadiness.readiness_score} />
            <div className="text-xs text-gray-600 space-y-1 flex-1">
              {demoReadiness.missing_data.length > 0 && (
                <p className="text-amber-800">
                  Missing: {demoReadiness.missing_data.slice(0, 2).join("; ")}
                </p>
              )}
              <p>{demoReadiness.safety_notice}</p>
            </div>
          </div>
        </section>
      )}

      {/* 1. Launch Overview */}
      <section className="card p-4 space-y-4">
        <h2 className="text-sm font-semibold text-gray-900">Launch Overview</h2>
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={overview.readiness_score} />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm flex-1">
            <div>
              <p className="text-[10px] uppercase text-gray-400">Demo data</p>
              <p className="font-medium">
                {overview.demo_data_present ? (
                  <span className="text-emerald-700">Present</span>
                ) : (
                  <span className="text-amber-700">Not seeded</span>
                )}
              </p>
              {overview.demo_company_name && (
                <p className="text-xs text-gray-500">{overview.demo_company_name}</p>
              )}
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400">QA passed</p>
              <p className="font-medium tabular-nums">
                {overview.qa_pass_count}/{overview.qa_total}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400">Smoke tests</p>
              <p className="font-medium tabular-nums">
                {overview.smoke_ok_count}/{overview.smoke_total}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400">Checklist</p>
              <p className="font-medium tabular-nums">
                {overview.checklist_completed} ok · {overview.checklist_blocked} blocked
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 2. Readiness Score */}
      {readiness && (
        <section className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Readiness Score</h2>
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
                <span
                  className={cn(
                    "text-xs font-semibold px-2 py-0.5 rounded-full",
                    STATUS_STYLES[c.status],
                  )}
                >
                  {c.score}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 3. Demo Data */}
      <section className="card p-4 space-y-3 border-violet-100">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Database size={16} className="text-violet-600" />
          Demo Data
        </h2>
        <p className="text-xs text-gray-600">
          Seeds a tagged pilot stack (factory application → tenant → portal → subscription →
          buyers, deals, marketplace). Never overwrites non-demo records.
        </p>
        <button
          type="button"
          disabled={seedMutation.isPending || overview.demo_data_present}
          onClick={() => seedMutation.mutate()}
          className="btn-primary text-sm flex items-center gap-1 disabled:opacity-50"
        >
          {seedMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Database size={14} />
          )}
          Seed demo data
        </button>
        {overview.demo_data_present && (
          <p className="text-xs text-emerald-700 flex items-center gap-1">
            <CheckCircle2 size={12} />
            Demo dataset already present — use pilot onboarding to walk through flows.
          </p>
        )}
        <Link href="/pilot-onboarding" className="text-xs text-brand-700 hover:underline">
          Open pilot onboarding →
        </Link>
      </section>

      {/* 4. QA Checklist */}
      <section className="card p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <ClipboardCheck size={16} />
            QA Checklist
          </h2>
          <button
            type="button"
            onClick={() => qaMutation.mutate()}
            disabled={qaMutation.isPending}
            className="btn-secondary text-xs flex items-center gap-1"
          >
            {qaMutation.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Play size={12} />
            )}
            Run QA
          </button>
        </div>
        {qaData ? (
          <ul className="space-y-1 text-sm">
            {qaData.steps.map((s) => (
              <li key={s.step} className="flex items-center gap-2">
                <span className={cn("font-medium", QA_STYLES[s.status])}>{s.status}</span>
                <span className="text-gray-800">{s.label}</span>
                {s.message && <span className="text-xs text-gray-400">— {s.message}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-gray-500">Run QA to validate end-to-end pilot flow.</p>
        )}
      </section>

      {/* 5. Smoke Tests */}
      {smoke && (
        <section className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Smoke Tests</h2>
          <p className="text-xs text-gray-500">
            {smoke.ok_count}/{smoke.total} pages healthy (API probes)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-400 border-b">
                  <th className="py-1 pr-2">Page</th>
                  <th className="py-1 pr-2">Route</th>
                  <th className="py-1 pr-2">Status</th>
                  <th className="py-1">ms</th>
                </tr>
              </thead>
              <tbody>
                {smoke.tests.map((t) => (
                  <tr key={t.page} className="border-b border-gray-50">
                    <td className="py-1.5 font-medium">{t.page}</td>
                    <td className="py-1.5">
                      <Link href={t.route} className="text-brand-700 hover:underline">
                        {t.route}
                      </Link>
                    </td>
                    <td className={cn("py-1.5 font-medium", SMOKE_STYLES[t.status])}>
                      {t.status}
                    </td>
                    <td className="py-1.5 tabular-nums text-gray-500">{t.duration_ms ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Deployment Readiness Panel */}
      {deploymentSummary && (
        <section className="card p-4 space-y-3 border-slate-200">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Cloud size={16} className="text-slate-600" />
              Deployment Readiness
            </h2>
            <Link href="/production-deployment" className="text-xs text-brand-700 hover:underline">
              Full assessment →
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center text-xs">
            <div className="rounded-lg border border-slate-100 bg-slate-50/50 px-2 py-2">
              <p className="text-[10px] text-slate-700">Readiness</p>
              <p className="text-lg font-semibold tabular-nums">
                {deploymentSummary.readiness_score}%
              </p>
            </div>
            <div className="rounded-lg border border-red-100 bg-red-50/50 px-2 py-2">
              <p className="text-[10px] text-red-700">Blockers</p>
              <p className="text-lg font-semibold tabular-nums">
                {deploymentSummary.blockers.length}
              </p>
            </div>
            <div className="rounded-lg border border-amber-100 bg-amber-50/50 px-2 py-2">
              <p className="text-[10px] text-amber-700">Warnings</p>
              <p className="text-lg font-semibold tabular-nums">
                {deploymentSummary.warnings.length}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 px-2 py-2">
              <p className="text-[10px] text-emerald-700">Deploy</p>
              <p className="text-lg font-semibold tabular-nums">
                {deploymentSummary.deployment_ready ? "Ready" : "Pending"}
              </p>
            </div>
          </div>
          {deploymentSummary.next_action && (
            <p className="text-xs text-gray-600">
              Next: {deploymentSummary.next_action.title}
            </p>
          )}
          <p className="text-[10px] text-gray-400">{deploymentSummary.safety_notice}</p>
        </section>
      )}

      {/* 6. Blockers */}
      <section className="card p-4 space-y-2 border-red-100">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <XCircle size={16} className="text-red-600" />
          Blockers
        </h2>
        {blockers.length === 0 ? (
          <EmptyState title="No blockers" description="Launch checklist has no blocked items." />
        ) : (
          <ul className="list-disc list-inside text-sm text-red-800 space-y-1">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}
        {checklist && checklist.blocked_count > 0 && (
          <ul className="text-xs text-gray-600 mt-2 space-y-1">
            {checklist.items
              .filter((i) => i.status === "blocked")
              .map((i) => (
                <li key={i.id}>
                  {i.label}: {i.message}
                </li>
              ))}
          </ul>
        )}
      </section>

      {/* 7. Next Actions */}
      <section className="card p-4 space-y-2 border-amber-100">
        <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <AlertTriangle size={16} className="text-amber-600" />
          Next Actions
        </h2>
        {nextActions.length === 0 && !checklist?.next_action ? (
          <p className="text-sm text-emerald-700 flex items-center gap-1">
            <CheckCircle2 size={14} />
            Ready for pilot demo walkthrough.
          </p>
        ) : (
          <ul className="list-decimal list-inside text-sm text-gray-800 space-y-1">
            {checklist?.next_action && <li>{checklist.next_action}</li>}
            {nextActions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
