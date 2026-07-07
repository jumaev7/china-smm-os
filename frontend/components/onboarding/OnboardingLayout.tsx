"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CheckCircle2, Circle, Clock, Rocket } from "lucide-react";
import { OnboardingAssistant } from "./OnboardingAssistant";
import { OnboardingCelebration } from "./OnboardingCelebration";
import { LoadingState } from "@/components/ui/PageStates";
import { useOnboardingDashboard, useOnboardingReadiness } from "@/lib/onboarding-hooks";
import { formatMinutesRemaining } from "@/lib/onboarding-ui";
import { cn } from "@/lib/utils";

const HUB_ROUTE = "/onboarding";

export function OnboardingLayout({
  title,
  subtitle,
  children,
  contextStep,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  contextStep?: string;
}) {
  const pathname = usePathname();
  const { data: dashboard, isLoading: dashLoading } = useOnboardingDashboard();
  const { data: readiness } = useOnboardingReadiness();

  if (dashLoading && !dashboard) {
    return <LoadingState message="Loading onboarding…" />;
  }

  const progress = readiness?.overall_percent ?? dashboard?.progress_percent ?? 0;
  const navSteps = readiness
    ? [...readiness.platform_steps.filter((s) => s.required), ...readiness.business_steps.filter((s) => s.required)].slice(0, 8)
    : (dashboard?.steps ?? []).slice(0, 8);

  return (
    <div className="min-h-full bg-gradient-to-b from-slate-50 via-white to-slate-50">
      {dashboard?.new_milestones?.length ? (
        <OnboardingCelebration milestones={dashboard.new_milestones} />
      ) : null}

      <div className="border-b border-slate-200 bg-white/90 backdrop-blur sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-brand-50 flex items-center justify-center ring-1 ring-brand-100">
                <Rocket className="text-brand-600" size={20} />
              </div>
              <div>
                <Link href={HUB_ROUTE} className="text-sm font-semibold text-brand-600 hover:underline">
                  Factory Setup Hub
                </Link>
                <p className="text-xs text-gray-500 flex items-center gap-2 mt-0.5">
                  <Clock size={11} />
                  {formatMinutesRemaining(
                    readiness?.estimated_minutes_remaining ?? dashboard?.estimated_minutes_remaining ?? 0,
                  )}{" "}
                  remaining
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 min-w-[220px]">
              <div className="flex-1 h-2.5 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-700 ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="text-sm font-bold tabular-nums text-brand-700 w-11">{progress}%</span>
            </div>
          </div>

          {navSteps.length > 0 ? (
            <nav className="flex gap-1.5 overflow-x-auto pb-1 -mx-1 px-1 scrollbar-thin">
              {navSteps.map((step) => {
                const route = "route" in step ? step.route : (step as { route: string }).route;
                const label = "label" in step ? step.label : (step as { label: string }).label;
                const done =
                  "status" in step
                    ? step.status === "completed"
                    : (step as { completed: boolean }).completed;
                const active = pathname === route || pathname.startsWith(`${route}/`);
                const shortLabel = label.split(" ").slice(0, 2).join(" ");

                return (
                  <Link
                    key={route}
                    href={route}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all",
                      active
                        ? "bg-brand-600 text-white shadow-sm"
                        : done
                          ? "bg-emerald-50 text-emerald-800 hover:bg-emerald-100 ring-1 ring-emerald-100"
                          : "bg-slate-100 text-gray-600 hover:bg-slate-200",
                    )}
                  >
                    {done ? <CheckCircle2 size={12} /> : <Circle size={12} />}
                    {shortLabel}
                  </Link>
                );
              })}
            </nav>
          ) : null}
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="grid lg:grid-cols-[1fr_300px] gap-8">
          <div>
            <header className="mb-6 animate-fade-in-up">
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-navy-900">{title}</h1>
              {subtitle ? <p className="text-sm sm:text-base text-gray-600 mt-2 leading-relaxed max-w-xl">{subtitle}</p> : null}
            </header>
            {children}
          </div>
          <aside className="space-y-4 lg:sticky lg:top-28 lg:self-start">
            <OnboardingAssistant contextStep={contextStep} />
          </aside>
        </div>
      </div>
    </div>
  );
}
