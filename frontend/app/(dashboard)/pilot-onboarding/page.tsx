"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Circle,
  ClipboardCheck,
  Loader2,
  RefreshCw,
  Rocket,
  Shield,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  pilotOnboardingApi,
  pilotLaunchApi,
  firstPilotClientApi,
  realFactoryPilotApi,
  PilotOnboardingDetail,
  PilotOnboardingStatus,
  PilotOnboardingSummary,
} from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const STATUS_STYLES: Record<PilotOnboardingStatus, string> = {
  not_started: "bg-gray-100 text-gray-700",
  in_progress: "bg-sky-100 text-sky-800",
  blocked: "bg-red-100 text-red-800",
  ready: "bg-emerald-100 text-emerald-800",
  completed: "bg-violet-100 text-violet-800",
};

const STATUS_LABELS: Record<PilotOnboardingStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  blocked: "Blocked",
  ready: "Ready",
  completed: "Completed",
};

function ReadinessRing({ score }: { score: number }) {
  const color =
    score >= 90
      ? "text-emerald-600 border-emerald-200 bg-emerald-50"
      : score >= 50
        ? "text-amber-600 border-amber-200 bg-amber-50"
        : "text-gray-600 border-gray-200 bg-gray-50";
  return (
    <div
      className={cn(
        "inline-flex items-center justify-center w-16 h-16 rounded-full border-4 font-bold text-lg tabular-nums",
        color,
      )}
    >
      {score}
    </div>
  );
}

export default function PilotOnboardingPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotOnboardingPageContent />
    </AdminAuthGuard>
  );
}

function PilotOnboardingPageContent() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<PilotOnboardingStatus | "">("");

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["pilot-onboarding-overview"],
    queryFn: () => pilotOnboardingApi.overview().then((r) => r.data),
  });

  const { data: launchReadiness } = useQuery({
    queryKey: ["pilot-launch-readiness-panel"],
    queryFn: () => pilotLaunchApi.readiness().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: firstPilotReadiness } = useQuery({
    queryKey: ["first-pilot-client-onboarding-panel"],
    queryFn: () => firstPilotClientApi.overview().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: realFactoryPilotPanel } = useQuery({
    queryKey: ["real-factory-pilot-onboarding-panel"],
    queryFn: () => realFactoryPilotApi.summary().then((r) => r.data),
    enabled: !!overview,
  });

  const { data: applicationsData } = useQuery({
    queryKey: ["pilot-onboarding-applications", statusFilter],
    queryFn: () =>
      pilotOnboardingApi
        .applications({
          onboarding_status: statusFilter || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!overview,
  });

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ["pilot-onboarding-detail", selectedId],
    queryFn: () => pilotOnboardingApi.get(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const refreshMutation = useMutation({
    mutationFn: (id: string) => pilotOnboardingApi.refresh(id).then((r) => r.data),
    onSuccess: (d) => {
      toast.success(d.message);
      qc.invalidateQueries({ queryKey: ["pilot-onboarding"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const items = applicationsData?.items ?? [];
  const selected: PilotOnboardingDetail | undefined = detail;
  const autoSelected = selected ?? items.find((a) => a.application_id === selectedId);
  const onboardingDetail =
    detail ??
    (autoSelected && "checklist" in autoSelected && Array.isArray(autoSelected.checklist)
      ? (autoSelected as PilotOnboardingDetail)
      : undefined);

  if (isLoading) return <LoadingState message="Loading pilot onboarding…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load pilot onboarding"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Rocket className="w-5 h-5 text-brand-600" />
            Pilot Client Onboarding
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Guided workflow from factory application to pilot-ready tenant — manual admin actions only.
          </p>
        </div>
        <Link href="/factory-partners" className="text-sm text-brand-700 hover:underline">
          Factory Partners admin →
        </Link>
      </div>

      <div className="card p-3 border-amber-100 bg-amber-50/50 text-xs text-amber-900 flex items-start gap-2">
        <Shield size={14} className="shrink-0 mt-0.5" />
        <span>{overview.safety_notice}</span>
      </div>

      {launchReadiness && (
        <section className="card p-4 space-y-3 border-fuchsia-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Launch readiness panel</p>
            <Link href="/pilot-launch" className="text-xs text-brand-700 hover:underline">
              Pilot launch center →
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <ReadinessRing score={launchReadiness.score} />
            <div className="text-xs text-gray-600 space-y-1 flex-1">
              <p>
                Demo data:{" "}
                {launchReadiness.demo_data_present ? (
                  <span className="text-emerald-700 font-medium">present</span>
                ) : (
                  <span className="text-amber-700 font-medium">not seeded</span>
                )}
              </p>
              <p>{launchReadiness.safety_notice}</p>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 gap-2">
            {launchReadiness.components.slice(0, 4).map((c) => (
              <div
                key={c.key}
                className="text-xs flex justify-between rounded border border-gray-100 px-2 py-1"
              >
                <span className="text-gray-700">{c.label}</span>
                <span className="font-medium tabular-nums">{c.score}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {firstPilotReadiness && (
        <section className="card p-4 space-y-3 border-teal-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Pilot Client Readiness Panel</p>
            <Link href="/first-pilot-client" className="text-xs text-brand-700 hover:underline">
              First pilot client center →
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <ReadinessRing score={firstPilotReadiness.readiness_score} />
            <div className="text-xs text-gray-600 space-y-1 flex-1">
              {firstPilotReadiness.company_name ? (
                <p>
                  Client:{" "}
                  <span className="font-medium text-gray-900">{firstPilotReadiness.company_name}</span>
                </p>
              ) : (
                <p className="text-amber-700">No real pilot client identified yet</p>
              )}
              <p>
                Blockers: {firstPilotReadiness.blocker_count} (
                {firstPilotReadiness.critical_blocker_count} critical)
              </p>
              <p>{firstPilotReadiness.safety_notice}</p>
            </div>
          </div>
          {firstPilotReadiness.next_action && (
            <div className="text-xs rounded border border-teal-100 bg-teal-50/50 px-2 py-2">
              Next: {firstPilotReadiness.next_action.title}
              {firstPilotReadiness.next_action.route_hint && (
                <Link
                  href={firstPilotReadiness.next_action.route_hint}
                  className="text-brand-700 hover:underline ml-2"
                >
                  Open →
                </Link>
              )}
            </div>
          )}
        </section>
      )}

      {realFactoryPilotPanel && (
        <section className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Real Factory Pilot Panel</p>
            <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline">
              Real factory pilot →
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <ReadinessRing score={realFactoryPilotPanel.readiness_score} />
            <div className="text-xs text-gray-600 space-y-1 flex-1">
              {realFactoryPilotPanel.selected_factory?.company_name ? (
                <p>
                  Factory:{" "}
                  <span className="font-medium text-gray-900">
                    {realFactoryPilotPanel.selected_factory.company_name}
                  </span>
                </p>
              ) : (
                <p className="text-amber-700">No real factory selected yet</p>
              )}
              <p className="capitalize">
                Status: {realFactoryPilotPanel.status.replace(/_/g, " ")}
              </p>
              <p>{realFactoryPilotPanel.safety_notice}</p>
            </div>
          </div>
          {realFactoryPilotPanel.next_best_action && (
            <div className="text-xs rounded border border-indigo-100 bg-indigo-50/50 px-2 py-2">
              Next: {realFactoryPilotPanel.next_best_action.title}
              {realFactoryPilotPanel.next_best_action.route_hint && (
                <Link
                  href={realFactoryPilotPanel.next_best_action.route_hint}
                  className="text-brand-700 hover:underline ml-2"
                >
                  Open →
                </Link>
              )}
            </div>
          )}
        </section>
      )}

      {/* 1. Overview */}
      <section className="card p-5 space-y-4">
        <p className="text-sm font-semibold text-gray-900">1. Overview</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 text-center">
          {(
            [
              ["Total", overview.total_applications, "text-gray-900"],
              ["Not started", overview.not_started, "text-gray-700"],
              ["In progress", overview.in_progress, "text-sky-800"],
              ["Blocked", overview.blocked, "text-red-800"],
              ["Ready", overview.ready, "text-emerald-800"],
              ["Completed", overview.completed, "text-violet-800"],
              ["Pilot ready", overview.pilot_ready_count, "text-brand-800"],
            ] as const
          ).map(([label, val, color]) => (
            <div key={label} className="rounded-lg border border-gray-100 bg-gray-50/50 px-2 py-2">
              <p className="text-[10px] text-gray-500">{label}</p>
              <p className={cn("text-lg font-semibold tabular-nums", color)}>{val}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-500">
          Average readiness: {overview.average_readiness_score}% · Pending approval:{" "}
          {overview.pending_approval}
        </p>
        {overview.integration_checks.length > 0 && (
          <PartialErrorsBanner
            errors={overview.integration_checks
              .filter((c) => c.status !== "ok")
              .map((c) => `${c.module}: ${c.message}`)}
          />
        )}
      </section>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* 2. Applications */}
        <section className="card p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-900">2. Applications</p>
          <div className="flex flex-wrap gap-1">
            {(["", "in_progress", "blocked", "ready", "completed"] as const).map((s) => (
              <button
                key={s || "all"}
                type="button"
                onClick={() => setStatusFilter(s)}
                className={cn(
                  "px-3 py-1 rounded-full text-xs border",
                  statusFilter === s
                    ? "bg-brand-100 border-brand-200 text-brand-800"
                    : "bg-white border-gray-200 text-gray-600",
                )}
              >
                {s ? STATUS_LABELS[s] : "All"}
              </button>
            ))}
          </div>
          {items.length === 0 ? (
            <EmptyState title="No applications" description="Factory partner applications will appear here." />
          ) : (
            <ul className="divide-y divide-gray-100 max-h-80 overflow-y-auto">
              {items.map((app: PilotOnboardingSummary) => (
                <li key={app.application_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(app.application_id)}
                    className={cn(
                      "w-full text-left px-3 py-3 hover:bg-gray-50 transition",
                      selectedId === app.application_id && "bg-brand-50",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-gray-900">{app.company}</span>
                      <span className="text-xs font-semibold tabular-nums">{app.readiness_score}%</span>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span
                        className={cn(
                          "text-[10px] px-2 py-0.5 rounded-full",
                          STATUS_STYLES[app.status],
                        )}
                      >
                        {STATUS_LABELS[app.status]}
                      </span>
                      <span className="text-[10px] text-gray-400 capitalize">{app.application_status}</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 3. Readiness Score + detail panels */}
        <section className="space-y-4">
          {!autoSelected ? (
            <div className="card p-8 text-center text-sm text-gray-500">
              Select an application to view readiness, checklist, blockers, and guided actions.
            </div>
          ) : detailLoading && !detail ? (
            <LoadingState message="Loading application onboarding…" />
          ) : (
            <>
              {/* 3. Readiness Score */}
              <div className="card p-5 flex items-center gap-4">
                <ReadinessRing score={autoSelected.readiness_score} />
                <div>
                  <p className="text-sm font-semibold text-gray-900">3. Readiness Score</p>
                  <p className="text-lg font-medium">{autoSelected.company}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    {STATUS_LABELS[autoSelected.status]} · Application: {autoSelected.application_status}
                  </p>
                  <button
                    type="button"
                    className="mt-2 text-xs text-brand-700 flex items-center gap-1 hover:underline"
                    disabled={refreshMutation.isPending}
                    onClick={() => refreshMutation.mutate(autoSelected.application_id)}
                  >
                    {refreshMutation.isPending ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <RefreshCw size={12} />
                    )}
                    Refresh state
                  </button>
                </div>
              </div>

              {/* 4. Checklist */}
              {onboardingDetail?.checklist && (
                <div className="card p-5 space-y-3">
                  <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                    <ClipboardCheck size={16} />
                    4. Checklist
                  </p>
                  <ol className="space-y-2">
                    {onboardingDetail.checklist.map((step) => (
                      <li key={step.step} className="flex items-start gap-2 text-sm">
                        {step.completed ? (
                          <CheckCircle2 size={16} className="text-emerald-600 shrink-0 mt-0.5" />
                        ) : (
                          <Circle size={16} className="text-gray-300 shrink-0 mt-0.5" />
                        )}
                        <div>
                          <p className={cn("font-medium", step.completed ? "text-gray-900" : "text-gray-500")}>
                            {step.label}
                          </p>
                          {step.details && (
                            <p className="text-xs text-gray-400">{step.details}</p>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* 5. Blockers */}
              <div className="card p-5 space-y-3">
                <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                  <AlertTriangle size={16} className="text-amber-600" />
                  5. Blockers
                </p>
                {autoSelected.blockers.length === 0 ? (
                  <p className="text-sm text-emerald-700">No blockers detected.</p>
                ) : (
                  <ul className="space-y-2">
                    {autoSelected.blockers.map((b) => (
                      <li
                        key={b.blocker}
                        className={cn(
                          "text-sm rounded-lg px-3 py-2 border",
                          b.severity === "critical"
                            ? "border-red-200 bg-red-50 text-red-900"
                            : "border-amber-200 bg-amber-50 text-amber-900",
                        )}
                      >
                        <p className="font-medium">{b.label}</p>
                        <p className="text-xs mt-0.5 opacity-90">{b.message}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* 6. Next Best Action */}
              <div className="card p-5 space-y-2 border-brand-100">
                <p className="text-sm font-semibold text-gray-900">6. Next Best Action</p>
                {autoSelected.next_best_action ? (
                  <div>
                    <p className="font-medium text-brand-800">{autoSelected.next_best_action.label}</p>
                    <p className="text-xs text-gray-600 mt-1">
                      {autoSelected.next_best_action.description}
                    </p>
                    {autoSelected.next_best_action.route_hint && (
                      <Link
                        href={autoSelected.next_best_action.route_hint}
                        className="inline-flex items-center gap-1 mt-2 text-sm text-brand-700 hover:underline"
                      >
                        Go to action <ArrowRight size={14} />
                      </Link>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">
                    {autoSelected.status === "completed"
                      ? "Pilot ready — all checklist steps complete."
                      : "No immediate action available."}
                  </p>
                )}
              </div>

              {/* 7. Guided Admin Actions */}
              {onboardingDetail?.available_actions && (
                <div className="card p-5 space-y-3">
                  <p className="text-sm font-semibold text-gray-900">7. Guided Admin Actions</p>
                  <ul className="space-y-2">
                    {onboardingDetail.available_actions.map((action) => (
                      <li
                        key={action.action}
                        className={cn(
                          "flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm",
                          action.available
                            ? "border-brand-200 bg-brand-50/30"
                            : "border-gray-100 bg-gray-50 opacity-60",
                        )}
                      >
                        <div>
                          <p className="font-medium">{action.label}</p>
                          <p className="text-xs text-gray-500">{action.description}</p>
                        </div>
                        {action.available && action.route_hint ? (
                          <Link
                            href={action.route_hint}
                            className="text-xs text-brand-700 whitespace-nowrap hover:underline"
                          >
                            Open →
                          </Link>
                        ) : (
                          <span className="text-[10px] text-gray-400">Not available</span>
                        )}
                      </li>
                    ))}
                  </ul>
                  <p className="text-[10px] text-gray-400">
                    Manual execution only — actions open admin pages; nothing runs automatically.
                  </p>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
