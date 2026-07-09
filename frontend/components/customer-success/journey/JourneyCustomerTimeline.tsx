"use client";

import Link from "next/link";
import { format, parseISO } from "date-fns";
import { CheckCircle2, Circle, Lock } from "lucide-react";
import type { CustomerSuccessJourneyDashboard, OnboardingReadinessResponse } from "@/lib/api";
import { buildCustomerMilestones } from "@/lib/customer-success-journey-ui";
import { cn } from "@/lib/utils";

export function JourneyCustomerTimeline({
  journey,
  readiness,
  delay = 0,
}: {
  journey: CustomerSuccessJourneyDashboard;
  readiness?: OnboardingReadinessResponse | null;
  delay?: number;
}) {
  const milestones = buildCustomerMilestones(journey, readiness);

  return (
    <section
      className="card-premium p-6 animate-fade-in-up"
      style={{ animationDelay: `${delay}ms` }}
      aria-label="Customer journey timeline"
    >
      <div className="mb-6">
        <h2 className="section-title text-base font-semibold text-navy-900 dark-tenant:text-slate-100">
          Customer Journey
        </h2>
        <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">
          Key milestones from signup to revenue
        </p>
      </div>

      <ol className="relative space-y-0">
        {milestones.map((milestone, i) => {
          const isLast = i === milestones.length - 1;
          const Icon = milestone.completed ? CheckCircle2 : milestone.future ? Lock : Circle;

          const content = (
            <div
              className={cn(
                "flex gap-4 pb-6",
                isLast && "pb-0",
                milestone.future && "opacity-50",
              )}
            >
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10",
                    milestone.completed
                      ? "bg-emerald-500 text-white shadow-sm"
                      : milestone.future
                        ? "bg-slate-100 text-slate-400 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-500"
                        : "bg-violet-100 text-violet-700 ring-2 ring-violet-200 dark-tenant:bg-violet-500/15 dark-tenant:text-violet-300 dark-tenant:ring-violet-500/30",
                  )}
                >
                  <Icon size={14} />
                </div>
                {!isLast && (
                  <div
                    className={cn(
                      "w-0.5 flex-1 min-h-[24px] mt-1",
                      milestone.completed
                        ? "bg-emerald-300 dark-tenant:bg-emerald-500/40"
                        : "bg-slate-200 dark-tenant:bg-white/[0.08]",
                    )}
                  />
                )}
              </div>

              <div className="flex-1 pt-0.5 min-w-0">
                <p
                  className={cn(
                    "text-sm font-medium",
                    milestone.completed
                      ? "text-navy-900 dark-tenant:text-slate-100"
                      : milestone.future
                        ? "text-gray-400 dark-tenant:text-slate-500"
                        : "text-navy-800 dark-tenant:text-slate-200",
                  )}
                >
                  {milestone.label}
                </p>
                {milestone.completed && milestone.completedAt && (
                  <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500 mt-0.5">
                    {format(parseISO(milestone.completedAt), "MMM d, yyyy")}
                  </p>
                )}
                {!milestone.completed && !milestone.future && (
                  <p className="text-[10px] text-violet-600 dark-tenant:text-violet-400 mt-0.5 font-medium">
                    In progress
                  </p>
                )}
              </div>
            </div>
          );

          if (milestone.href && !milestone.future) {
            return (
              <li key={milestone.id}>
                <Link href={milestone.href} className="block hover:opacity-90 transition-opacity rounded-lg -mx-2 px-2">
                  {content}
                </Link>
              </li>
            );
          }

          return <li key={milestone.id}>{content}</li>;
        })}
      </ol>
    </section>
  );
}
