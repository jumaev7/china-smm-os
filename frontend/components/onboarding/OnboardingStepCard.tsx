"use client";

import Link from "next/link";
import {
  ArrowRight,
  Ban,
  CheckCircle2,
  CircleDashed,
  Lightbulb,
  Lock,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import type { OnboardingStepReadiness } from "@/lib/api";
import { STEP_STATUS_META } from "@/lib/onboarding-ui";
import { cn } from "@/lib/utils";

export function OnboardingStepCard({
  step,
  index = 0,
  locked = false,
}: {
  step: OnboardingStepReadiness;
  index?: number;
  locked?: boolean;
}) {
  const meta = STEP_STATUS_META[step.status];
  const isComplete = step.status === "completed";
  const isBlocked = step.status === "blocked";
  const isRecommended = step.status === "recommended";

  const StatusIcon = isComplete
    ? CheckCircle2
    : isBlocked
      ? Ban
      : isRecommended
        ? Sparkles
        : CircleDashed;

  const content = (
    <article
      className={cn(
        "group relative rounded-2xl border bg-white p-4 sm:p-5 transition-all duration-300 animate-fade-in-up",
        locked && "opacity-60 pointer-events-none",
        isComplete
          ? "border-emerald-100 shadow-sm animate-celebrate"
          : isBlocked
            ? "border-amber-100"
            : "border-slate-200 shadow-card hover:shadow-card-hover hover:border-brand-200",
      )}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {isComplete ? (
        <div className="absolute top-0 left-4 right-4 h-0.5 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-500" />
      ) : null}

      <div className="flex gap-4">
        <div
          className={cn(
            "shrink-0 flex items-center justify-center w-11 h-11 rounded-xl ring-1",
            isComplete ? "bg-emerald-50 ring-emerald-100" : "bg-slate-50 ring-slate-100",
          )}
        >
          <StatusIcon size={22} className={meta.icon} />
        </div>

        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3
                className={cn(
                  "font-semibold text-[15px] leading-snug",
                  isComplete ? "text-gray-500 line-through decoration-emerald-300" : "text-navy-900",
                )}
              >
                {step.label}
              </h3>
              <p className="text-xs text-gray-400 mt-0.5">~{step.estimated_minutes} min</p>
            </div>
            <span
              className={cn(
                "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide ring-1",
                meta.badge,
              )}
            >
              {meta.label}
            </span>
          </div>

          {step.why_it_matters ? (
            <p className="text-sm text-gray-600 leading-relaxed flex gap-2">
              <Lightbulb size={14} className="text-amber-500 shrink-0 mt-0.5" />
              <span>{step.why_it_matters}</span>
            </p>
          ) : null}

          {!isComplete && step.next_action ? (
            <p className="text-xs font-medium text-brand-700 bg-brand-50 rounded-lg px-3 py-2">
              {step.next_action}
            </p>
          ) : null}

          {step.business_value ? (
            <p className="text-xs text-gray-500 flex items-start gap-1.5">
              <TrendingUp size={12} className="text-emerald-500 shrink-0 mt-0.5" />
              <span>
                <span className="font-medium text-gray-600">Business impact: </span>
                {step.business_value}
              </span>
            </p>
          ) : null}
        </div>

        {!locked && !isBlocked ? (
          <ArrowRight
            size={18}
            className="shrink-0 text-gray-300 group-hover:text-brand-500 group-hover:translate-x-0.5 transition-all self-center"
          />
        ) : locked ? (
          <Lock size={16} className="shrink-0 text-gray-300 self-center" />
        ) : null}
      </div>
    </article>
  );

  if (locked || isBlocked) return content;

  return (
    <Link href={step.route} className="block focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 rounded-2xl">
      {content}
    </Link>
  );
}
