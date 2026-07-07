"use client";

import { CheckCircle2, Circle, Lock } from "lucide-react";
import type { OnboardingReadinessResponse } from "@/lib/api";
import { formatMinutesRemaining } from "@/lib/onboarding-ui";
import { cn } from "@/lib/utils";

const PHASES = [
  { key: "platform", label: "Platform", percentKey: "platform_readiness_percent" as const },
  { key: "business", label: "Business", percentKey: "business_readiness_percent" as const },
  { key: "first_success", label: "First Success", percentKey: null },
] as const;

export function OnboardingJourneyProgress({ readiness }: { readiness: OnboardingReadinessResponse }) {
  const firstSuccessPercent = readiness.first_success?.percent ?? 0;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card animate-fade-in-up">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-400">Your journey</p>
          <p className="text-sm font-semibold text-navy-900 mt-0.5">
            {formatMinutesRemaining(readiness.estimated_minutes_remaining)} remaining
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold tabular-nums text-brand-700">{readiness.overall_percent}%</p>
          <p className="text-xs text-gray-500">overall readiness</p>
        </div>
      </div>

      <div className="relative">
        <div className="absolute top-5 left-5 right-5 h-0.5 bg-slate-100 hidden sm:block" />
        <div className="grid sm:grid-cols-3 gap-4">
          {PHASES.map((phase, i) => {
            const locked = phase.key === "business" && !readiness.platform_ready;
            const lockedFs = phase.key === "first_success" && !readiness.platform_ready;
            const percent =
              phase.key === "first_success"
                ? firstSuccessPercent
                : readiness[phase.percentKey!];
            const complete =
              phase.key === "platform"
                ? readiness.platform_ready
                : phase.key === "business"
                  ? readiness.business_readiness_percent >= 100
                  : (readiness.first_success?.achieved_count ?? 0) >= (readiness.first_success?.total_count ?? 4);

            return (
              <div
                key={phase.key}
                className="relative flex sm:flex-col items-center sm:text-center gap-3 sm:gap-2 animate-fade-in-up"
                style={{ animationDelay: `${i * 100}ms` }}
              >
                <div
                  className={cn(
                    "relative z-10 flex items-center justify-center w-10 h-10 rounded-full ring-4 ring-white",
                    complete
                      ? "bg-emerald-500 text-white"
                      : locked || lockedFs
                        ? "bg-slate-100 text-slate-400"
                        : "bg-brand-600 text-white",
                  )}
                >
                  {complete ? (
                    <CheckCircle2 size={20} />
                  ) : locked || lockedFs ? (
                    <Lock size={16} />
                  ) : (
                    <Circle size={18} />
                  )}
                </div>
                <div className="flex-1 sm:flex-none">
                  <p className="text-sm font-semibold text-navy-900">{phase.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {locked || lockedFs ? "Unlocks next" : `${percent}% complete`}
                  </p>
                  <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden sm:max-w-[120px] sm:mx-auto">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-700",
                        complete ? "bg-emerald-500" : "bg-brand-500",
                      )}
                      style={{ width: `${locked || lockedFs ? 0 : percent}%` }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
