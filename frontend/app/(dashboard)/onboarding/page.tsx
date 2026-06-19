"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  Clock,
  Sparkles,
  RefreshCw,
} from "lucide-react";
import toast from "react-hot-toast";
import { tenantOnboardingApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { OnboardingAssistant } from "@/components/onboarding/OnboardingAssistant";

export default function OnboardingDashboardPage() {
  const qc = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["tenant-onboarding"],
    queryFn: () => tenantOnboardingApi.dashboard().then((r) => r.data),
  });

  const refresh = useMutation({
    mutationFn: () => tenantOnboardingApi.refresh().then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      if (res.progress.new_milestones.length) {
        res.progress.new_milestones.forEach((m) => toast.success(m.message));
      }
    },
  });

  const demo = useMutation({
    mutationFn: () => tenantOnboardingApi.generateDemoData().then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      toast.success(res.message);
    },
    onError: () => toast.error("Could not generate demo data"),
  });

  if (isLoading) return <LoadingState message="Loading your setup progress…" />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load onboarding"}
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) return null;

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto space-y-8">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <h1 className="page-title">Factory Setup</h1>
          <p className="text-sm text-gray-500 mt-1">
            Get your first business results in about 15 minutes.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
        >
          <RefreshCw size={14} className={refresh.isPending ? "animate-spin" : ""} />
          Refresh progress
        </button>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center gap-6">
          <div
            className={cn(
              "flex items-center justify-center w-24 h-24 rounded-full border-4 font-bold text-2xl tabular-nums shrink-0",
              data.progress_percent >= 100
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-brand-200 bg-brand-50 text-brand-700",
            )}
          >
            {data.progress_percent}%
          </div>
          <div className="flex-1 space-y-2">
            <p className="text-lg font-semibold text-gray-900">
              {data.status === "completed"
                ? "Setup complete — your workspace is ready"
                : data.next_step
                  ? `Next: ${data.next_step.label}`
                  : "Start with your company profile"}
            </p>
            <div className="flex flex-wrap gap-4 text-sm text-gray-500">
              <span className="inline-flex items-center gap-1">
                <CheckCircle2 size={14} className="text-emerald-600" />
                {data.completed_steps} completed
              </span>
              <span className="inline-flex items-center gap-1">
                <Circle size={14} />
                {data.remaining_steps} remaining
              </span>
              <span className="inline-flex items-center gap-1">
                <Clock size={14} />
                ~{data.estimated_minutes_remaining} min left
              </span>
            </div>
            {data.next_step ? (
              <Link
                href={data.next_step.route}
                className="inline-flex items-center gap-2 mt-2 rounded-lg bg-brand-600 text-white text-sm font-medium px-4 py-2 hover:bg-brand-700"
              >
                Continue setup
                <ArrowRight size={16} />
              </Link>
            ) : null}
          </div>
        </div>
      </div>

      {!data.demo_data_generated ? (
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-5 flex flex-col sm:flex-row sm:items-center gap-4">
          <Sparkles className="text-violet-600 shrink-0" size={24} />
          <div className="flex-1">
            <p className="font-semibold text-violet-900">Try the demo environment</p>
            <p className="text-sm text-violet-800 mt-0.5">
              One click adds sample buyers, leads, deals, proposals, and communications.
            </p>
          </div>
          <button
            type="button"
            onClick={() => demo.mutate()}
            disabled={demo.isPending}
            className="rounded-lg bg-violet-600 text-white text-sm font-medium px-4 py-2 hover:bg-violet-700 disabled:opacity-50"
          >
            {demo.isPending ? "Generating…" : "Generate demo data"}
          </button>
        </div>
      ) : null}

      <div className="grid lg:grid-cols-[1fr_300px] gap-6">
        <div className="rounded-xl border border-slate-200 bg-white divide-y divide-slate-100">
          {data.steps.map((step) => (
            <Link
              key={step.id}
              href={step.route}
              className="flex items-center gap-4 p-4 hover:bg-slate-50 transition-colors"
            >
              {step.completed ? (
                <CheckCircle2 className="text-emerald-600 shrink-0" size={20} />
              ) : (
                <Circle className="text-gray-300 shrink-0" size={20} />
              )}
              <div className="flex-1 min-w-0">
                <p className={cn("font-medium", step.completed ? "text-gray-500" : "text-gray-900")}>
                  {step.label}
                </p>
                <p className="text-xs text-gray-400">~{step.estimated_minutes} min</p>
              </div>
              <ArrowRight size={16} className="text-gray-300 shrink-0" />
            </Link>
          ))}
        </div>
        <OnboardingAssistant />
      </div>

      {data.new_milestones.length > 0 ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 space-y-1">
          {data.new_milestones.map((m) => (
            <p key={m.step_id} className="text-sm text-emerald-900">{m.message}</p>
          ))}
        </div>
      ) : null}
    </div>
  );
}
