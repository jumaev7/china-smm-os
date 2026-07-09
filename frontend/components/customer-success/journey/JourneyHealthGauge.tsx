"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  computeHealthTrend,
  healthStrokeColor,
  healthTone,
  healthTrackColor,
} from "@/lib/customer-success-journey-ui";
import type { CustomerSuccessHealthScore } from "@/lib/api";

const RING_RADIUS = 72;
const CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

export function JourneyHealthGauge({
  healthScore,
  journeyDay,
  delay = 0,
}: {
  healthScore: CustomerSuccessHealthScore;
  journeyDay: number;
  delay?: number;
}) {
  const score = healthScore.score;
  const clamped = Math.min(100, Math.max(0, score));
  const offset = CIRCUMFERENCE - (clamped / 100) * CIRCUMFERENCE;
  const trend = computeHealthTrend(score, journeyDay);
  const variant = healthTone(score);

  return (
    <div
      className="card-premium p-6 sm:p-8 flex flex-col items-center justify-center text-center animate-fade-in-up"
      style={{ animationDelay: `${delay}ms` }}
      role="region"
      aria-label={`Health score ${score} out of 100`}
    >
      <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark-tenant:text-slate-500 mb-6 self-start">
        Health Score
      </p>

      <div className="relative w-44 h-44">
        <svg
          width={176}
          height={176}
          viewBox="0 0 180 180"
          className="rotate-[-90deg] absolute inset-0 m-auto"
          aria-hidden
        >
          <circle cx="90" cy="90" r={RING_RADIUS} fill="none" stroke={healthTrackColor(score)} strokeWidth="12" />
          <circle
            cx="90"
            cy="90"
            r={RING_RADIUS}
            fill="none"
            stroke={healthStrokeColor(score)}
            strokeWidth="12"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
            className="transition-all duration-1000 ease-out"
            style={{ transitionDelay: `${delay}ms` }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className={cn(
              "text-4xl font-bold tabular-nums",
              variant === "success" && "text-emerald-600 dark-tenant:text-emerald-400",
              variant === "warning" && "text-amber-600 dark-tenant:text-amber-400",
              variant === "danger" && "text-red-600 dark-tenant:text-red-400",
            )}
          >
            {clamped}
          </span>
          <span className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">out of 100</span>
        </div>
      </div>

      <div className="mt-6 space-y-2 w-full">
        <p className="text-sm font-semibold text-navy-900 dark-tenant:text-slate-100">{healthScore.label}</p>
        <p className="text-xs text-gray-500 dark-tenant:text-slate-400 leading-relaxed">{healthScore.summary}</p>
        <div
          className={cn(
            "inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full",
            trend.delta > 0
              ? "bg-emerald-50 text-emerald-700 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-400"
              : trend.delta < 0
                ? "bg-red-50 text-red-700 dark-tenant:bg-red-500/10 dark-tenant:text-red-400"
                : "bg-slate-50 text-slate-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-400",
          )}
        >
          {trend.delta > 0 ? <TrendingUp size={12} /> : trend.delta < 0 ? <TrendingDown size={12} /> : null}
          {trend.label}
        </div>
      </div>

      {healthScore.factors.length > 0 && (
        <div className="mt-6 w-full space-y-2 border-t border-gray-100 dark-tenant:border-white/[0.06] pt-5">
          {healthScore.factors.slice(0, 3).map((f) => (
            <div key={f.factor} className="flex items-center justify-between gap-2 text-xs">
              <span className="text-gray-600 dark-tenant:text-slate-400 truncate">{f.label}</span>
              <span className="font-semibold tabular-nums text-navy-800 dark-tenant:text-slate-200">{f.score}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
