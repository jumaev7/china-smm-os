"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  Loader2,
  Play,
  Presentation,
  RefreshCw,
  RotateCcw,
  Shield,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  PilotDemoModeAction,
  PilotDemoModeStepStatus,
  pilotDemoModeApi,
} from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { useTranslation } from "@/lib/I18nProvider";
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

const STEP_VARIANT: Record<
  PilotDemoModeStepStatus,
  "success" | "warning" | "danger" | "neutral"
> = {
  complete: "success",
  active: "warning",
  pending: "neutral",
  blocked: "danger",
};

const READINESS_VARIANT: Record<string, "success" | "warning" | "neutral"> = {
  ready: "success",
  in_progress: "warning",
  not_started: "neutral",
};

const DEMO_ACTIONS: PilotDemoModeAction[] = [
  "create_sample_brief",
  "generate_sample_plan",
  "approve_sample_plan",
  "create_sample_tasks",
  "simulate_publishing_pipeline",
  "generate_sample_revenue_metrics",
];

function StepIcon({ status }: { status: PilotDemoModeStepStatus }) {
  if (status === "complete") return <CheckCircle2 size={18} className="text-emerald-600" />;
  if (status === "active") return <Play size={18} className="text-amber-600" />;
  if (status === "blocked") return <Shield size={18} className="text-red-500" />;
  return <Circle size={18} className="text-gray-300" />;
}

function WorkflowDiagram({
  nodes,
  edges,
}: {
  nodes: { id: string; label: string; status: string; step: number }[];
  edges: { from: string; to: string }[];
}) {
  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex min-w-max items-center gap-1">
        {nodes.map((node, idx) => (
          <div key={node.id} className="flex items-center">
            <div
              className={cn(
                "flex flex-col items-center rounded-lg border px-3 py-2 min-w-[120px] max-w-[140px] text-center",
                node.status === "complete" && "border-emerald-200 bg-emerald-50",
                node.status === "active" && "border-amber-200 bg-amber-50",
                node.status === "pending" && "border-gray-200 bg-gray-50",
                node.status === "blocked" && "border-red-200 bg-red-50",
              )}
            >
              <span className="text-[10px] font-medium text-gray-500">Step {node.step}</span>
              <span className="text-xs font-medium text-gray-800 leading-tight mt-0.5">
                {node.label}
              </span>
            </div>
            {idx < edges.length && (
              <ArrowRight size={14} className="mx-1 text-gray-400 shrink-0" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PilotDemoModePage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotDemoModePageContent />
    </AdminAuthGuard>
  );
}

function PilotDemoModePageContent() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["pilot-demo-mode-overview"],
    queryFn: () => pilotDemoModeApi.overview().then((r) => r.data),
  });

  const actionMutation = useMutation({
    mutationFn: (action: PilotDemoModeAction) =>
      pilotDemoModeApi.runAction(action).then((r) => r.data),
    onSuccess: (result) => {
      toast.success(result.message || t("pilot.demoModePage.actionSuccess"));
      qc.setQueryData(["pilot-demo-mode-overview"], result.overview);
    },
    onError: (e: Error) => toast.error(e.message || t("pilot.demoModePage.actionFailed")),
  });

  const resetMutation = useMutation({
    mutationFn: () => pilotDemoModeApi.reset().then((r) => r.data),
    onSuccess: (result) => {
      toast.success(result.message || t("pilot.demoModePage.resetSuccess"));
      qc.setQueryData(["pilot-demo-mode-overview"], result.overview);
    },
    onError: (e: Error) => toast.error(e.message || t("pilot.demoModePage.actionFailed")),
  });

  if (isLoading) return <DashboardSkeleton />;
  if (isError || !data)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("pilot.demoModePage.loadError")}
        onRetry={() => refetch()}
      />
    );

  const readinessKey = data.readiness_status as keyof typeof READINESS_VARIANT;

  return (
    <PageShell>
      <PageHeader
        title={t("pilot.demoModePage.title")}
        subtitle={t("pilot.demoModePage.subtitle")}
        icon={Presentation}
        iconClassName="text-brand-600"
        actions={
          <>
            <button
              type="button"
              onClick={() => refetch()}
              disabled={isFetching}
              className="btn-secondary text-xs flex items-center gap-1.5"
            >
              {isFetching ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RefreshCw size={13} />
              )}
              {t("pilot.refresh")}
            </button>
            <button
              type="button"
              onClick={() => {
                if (window.confirm(t("pilot.demoModePage.resetConfirm"))) {
                  resetMutation.mutate();
                }
              }}
              disabled={resetMutation.isPending}
              className="btn-secondary text-xs flex items-center gap-1.5 text-red-700 border-red-200"
            >
              {resetMutation.isPending ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <RotateCcw size={13} />
              )}
              {t("pilot.demoModePage.resetDemo")}
            </button>
          </>
        }
      />

      <div className="mb-4 rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800">
        <Shield size={14} className="inline mr-1.5 -mt-0.5" />
        {data.safety_notice || t("pilot.demoModePage.safetyNotice")}
      </div>

      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <ScoreCard
          title={t("pilot.demoModePage.readinessStatus")}
          score={data.readiness_score}
          className="lg:col-span-1"
        />
        <div className="lg:col-span-2 flex flex-wrap items-center gap-3">
          <StatusBadge variant={READINESS_VARIANT[readinessKey] ?? "neutral"}>
            {t(`pilot.demoModePage.readiness.${data.readiness_status}`)}
          </StatusBadge>
          <StatusBadge variant="neutral">
            {t("pilot.demoModePage.progress")}: {data.progress_percent}%
          </StatusBadge>
          <StatusBadge variant={data.demo_data_present ? "success" : "neutral"}>
            {data.demo_data_present ? "Demo data active" : "No demo data"}
          </StatusBadge>
        </div>
      </div>

      <ExecutiveKpiBar
        items={data.kpis.map((k) => ({ label: k.label, value: k.value }))}
        className="mb-6"
      />

      <div className="grid gap-6 lg:grid-cols-2 mb-6">
        <section className="card p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Sparkles size={16} className="text-brand-600" />
            {t("pilot.demoModePage.executiveSummary")}
          </h3>
          <p className="text-sm text-gray-700 leading-relaxed">{data.executive_summary}</p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            <Link href="/briefs" className="text-brand-700 hover:underline">
              Briefs →
            </Link>
            <Link href="/content" className="text-brand-700 hover:underline">
              Content →
            </Link>
            <Link href="/tasks" className="text-brand-700 hover:underline">
              Tasks →
            </Link>
            <Link href="/crm" className="text-brand-700 hover:underline">
              CRM →
            </Link>
            <Link href="/pilot-readiness" className="text-brand-700 hover:underline">
              Pilot Readiness →
            </Link>
          </div>
        </section>

        <section className="card p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <TrendingUp size={16} className="text-brand-600" />
            {t("pilot.demoModePage.demoActions")}
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {DEMO_ACTIONS.map((action) => (
              <button
                key={action}
                type="button"
                disabled={actionMutation.isPending}
                onClick={() => actionMutation.mutate(action)}
                className="btn-secondary text-xs text-left py-2 px-3 hover:border-brand-300"
              >
                {actionMutation.isPending ? (
                  <Loader2 size={12} className="inline animate-spin mr-1" />
                ) : (
                  <Play size={12} className="inline mr-1" />
                )}
                {t(`pilot.demoModePage.actions.${action}`)}
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="card p-5 mb-6">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">
          {t("pilot.demoModePage.workflowDiagram")}
        </h3>
        <WorkflowDiagram
          nodes={data.workflow_diagram.nodes}
          edges={data.workflow_diagram.edges}
        />
      </section>

      <section className="card p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">
          {t("pilot.demoModePage.workflowTimeline")}
        </h3>
        <ol className="relative border-l border-gray-200 ml-3 space-y-6">
          {data.workflow_steps.map((step) => (
            <li key={step.id} className="ml-6">
              <span className="absolute -left-3 flex items-center justify-center w-6 h-6 rounded-full bg-white border border-gray-200">
                <StepIcon status={step.status} />
              </span>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-gray-900">
                    {step.step}. {step.title}
                  </p>
                  <p className="text-xs text-gray-600 mt-0.5">{step.description}</p>
                </div>
                <StatusBadge variant={STEP_VARIANT[step.status]}>
                  {t(`pilot.demoModePage.stepStatus.${step.status}`)}
                </StatusBadge>
              </div>
              {step.action_key && step.status !== "complete" && (
                <button
                  type="button"
                  disabled={actionMutation.isPending}
                  onClick={() =>
                    actionMutation.mutate(step.action_key as PilotDemoModeAction)
                  }
                  className="mt-2 text-xs text-brand-700 hover:underline flex items-center gap-1"
                >
                  {actionMutation.isPending ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : (
                    <Play size={11} />
                  )}
                  {t(`pilot.demoModePage.actions.${step.action_key}`)}
                </button>
              )}
            </li>
          ))}
        </ol>
      </section>
    </PageShell>
  );
}
