"use client";

import Link from "next/link";
import { CheckCircle2, Circle, Star } from "lucide-react";
import type { CustomerSuccessJourneyDashboard } from "@/lib/api";
import { computeNorthStarProgress } from "@/lib/customer-success-journey-ui";
import { cn } from "@/lib/utils";

export function JourneyNorthStarCard({
  journey,
  delay = 0,
}: {
  journey: CustomerSuccessJourneyDashboard;
  delay?: number;
}) {
  const progress = computeNorthStarProgress(journey);
  const goalLabel = journey.north_star_label ?? "Set your north star goal";
  const hasGoal = Boolean(journey.north_star_goal);

  return (
    <div
      className="card-premium p-6 sm:p-8 animate-fade-in-up h-full flex flex-col"
      style={{ animationDelay: `${delay}ms` }}
      role="region"
      aria-label="North star progress"
    >
      <div className="flex items-start justify-between gap-3 mb-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-violet-600 dark-tenant:text-violet-400 flex items-center gap-1.5">
            <Star size={12} />
            North Star
          </p>
          <h2 className="text-lg font-semibold text-navy-900 dark-tenant:text-slate-100 mt-1">{goalLabel}</h2>
          {!hasGoal && (
            <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-1">
              Define your primary success outcome to personalize recommendations.
            </p>
          )}
        </div>
        <div className="text-right shrink-0">
          <p className="text-3xl font-bold tabular-nums text-violet-700 dark-tenant:text-violet-300">{progress}%</p>
          <p className="text-[10px] uppercase tracking-wider text-gray-400 dark-tenant:text-slate-500">complete</p>
        </div>
      </div>

      <div className="h-2.5 rounded-full bg-slate-100 dark-tenant:bg-white/[0.08] overflow-hidden mb-6">
        <div
          className="h-full rounded-full bg-gradient-to-r from-violet-600 to-indigo-500 transition-all duration-1000 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="grid grid-cols-3 gap-3 mb-6">
        <MetricPill label="Checkpoints" value={`${journey.success_score.checkpoint_completion_pct}%`} />
        <MetricPill label="Features" value={`${journey.success_score.feature_breadth_pct}%`} />
        <MetricPill label="Outcomes" value={`${journey.success_score.outcome_signals_pct}%`} />
      </div>

      <div className="flex-1">
        <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark-tenant:text-slate-500 mb-3">
          Milestone timeline
        </p>
        <div className="space-y-2">
          {journey.checkpoints.map((cp) => (
            <div
              key={cp.id}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2.5 border transition-colors",
                cp.status === "achieved"
                  ? "border-emerald-200/80 bg-emerald-50/50 dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/[0.06]"
                  : cp.status === "in_progress"
                    ? "border-violet-200/80 bg-violet-50/40 dark-tenant:border-violet-500/20 dark-tenant:bg-violet-500/[0.06]"
                    : cp.status === "locked"
                      ? "border-gray-100 bg-gray-50/50 opacity-60 dark-tenant:border-white/[0.04] dark-tenant:bg-white/[0.02]"
                      : "border-gray-100 bg-white dark-tenant:border-white/[0.06] dark-tenant:bg-white/[0.02]",
              )}
            >
              {cp.status === "achieved" ? (
                <CheckCircle2 size={16} className="text-emerald-600 dark-tenant:text-emerald-400 shrink-0" />
              ) : (
                <Circle size={16} className="text-gray-300 dark-tenant:text-slate-600 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-navy-900 dark-tenant:text-slate-200 truncate">
                  {cp.label} — {cp.theme}
                </p>
                <p className="text-[10px] text-gray-500 dark-tenant:text-slate-500">Day {cp.day}</p>
              </div>
              <span className="text-xs font-semibold tabular-nums text-gray-600 dark-tenant:text-slate-400">
                {cp.completion_percent}%
              </span>
            </div>
          ))}
        </div>
      </div>

      {!hasGoal && (
        <Link
          href="/onboarding/goal"
          className="mt-5 inline-flex items-center justify-center rounded-xl bg-violet-600 text-white text-sm font-semibold px-4 py-2.5 hover:bg-violet-500 transition-colors dark-tenant:shadow-glow"
        >
          Set north star goal
        </Link>
      )}
    </div>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-slate-50 border border-slate-100 px-3 py-2 text-center dark-tenant:bg-white/[0.04] dark-tenant:border-white/[0.06]">
      <p className="text-[10px] uppercase tracking-wider text-gray-400 dark-tenant:text-slate-500">{label}</p>
      <p className="text-sm font-bold tabular-nums text-navy-900 dark-tenant:text-slate-100 mt-0.5">{value}</p>
    </div>
  );
}
