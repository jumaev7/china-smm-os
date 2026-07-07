"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Check, Circle } from "lucide-react";
import { useWizardProgress } from "@/lib/onboarding-hooks";
import { formatMinutesRemaining } from "@/lib/onboarding-ui";
import { cn } from "@/lib/utils";

export function OnboardingWizardProgress({ className }: { className?: string }) {
  const pathname = usePathname();
  const progress = useWizardProgress(pathname);

  if (!progress) {
    return <OnboardingWizardProgressSkeleton />;
  }

  return (
    <div
      className={cn(
        "rounded-2xl border border-slate-200/80 bg-white/90 backdrop-blur p-4 sm:p-5 shadow-card dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card/90",
        className,
      )}
      aria-label={`Setup progress: step ${progress.currentStep} of ${progress.totalSteps}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark-tenant:text-slate-500">
            Setup progress
          </p>
          <p className="text-sm font-semibold text-navy-900 dark-tenant:text-slate-100 mt-0.5">
            Step {progress.currentStep} of {progress.totalSteps}
            <span className="text-gray-400 font-normal dark-tenant:text-slate-500">
              {" "}
              · {formatMinutesRemaining(progress.estimatedMinutesRemaining)} left
            </span>
          </p>
        </div>
        <div className="flex items-center gap-3 min-w-[140px]">
          <div className="flex-1 h-2.5 rounded-full bg-slate-100 overflow-hidden dark-tenant:bg-white/[0.06]">
            <div
              className="h-full rounded-full bg-gradient-to-r from-brand-500 to-violet-500 transition-all duration-700 ease-out"
              style={{ width: `${progress.percent}%` }}
              role="progressbar"
              aria-valuenow={progress.percent}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
          <span className="text-sm font-bold tabular-nums text-brand-700 dark-tenant:text-violet-400 w-10 text-right">
            {progress.percent}%
          </span>
        </div>
      </div>

      <nav className="flex flex-wrap gap-2" aria-label="Completed sections">
        {progress.steps.map((step) => (
          <Link
            key={step.id}
            href={step.route}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
              step.current
                ? "bg-brand-600 text-white shadow-sm dark-tenant:bg-violet-600"
                : step.completed
                  ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-100 hover:bg-emerald-100 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-300 dark-tenant:ring-emerald-500/20"
                  : "bg-slate-50 text-gray-500 ring-1 ring-slate-100 hover:bg-slate-100 dark-tenant:bg-white/[0.04] dark-tenant:text-slate-400 dark-tenant:ring-white/[0.06]",
            )}
          >
            {step.completed ? (
              <Check size={12} className="shrink-0" aria-hidden />
            ) : (
              <Circle size={12} className="shrink-0 opacity-50" aria-hidden />
            )}
            {step.shortLabel}
          </Link>
        ))}
      </nav>
    </div>
  );
}

export function OnboardingWizardProgressSkeleton() {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card animate-pulse dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card">
      <div className="flex justify-between mb-4">
        <div className="space-y-2">
          <div className="h-3 w-24 bg-slate-100 rounded dark-tenant:bg-white/[0.06]" />
          <div className="h-4 w-40 bg-slate-100 rounded dark-tenant:bg-white/[0.06]" />
        </div>
        <div className="h-4 w-16 bg-slate-100 rounded dark-tenant:bg-white/[0.06]" />
      </div>
      <div className="h-2.5 bg-slate-100 rounded-full mb-4 dark-tenant:bg-white/[0.06]" />
      <div className="flex gap-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-7 w-20 bg-slate-100 rounded-full dark-tenant:bg-white/[0.06]" />
        ))}
      </div>
    </div>
  );
}
