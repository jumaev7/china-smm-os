"use client";

import Link from "next/link";
import { ArrowLeft, ArrowRight, Clock, Rocket } from "lucide-react";
import { OnboardingCelebration } from "./OnboardingCelebration";
import { OnboardingWizardProgress } from "./OnboardingWizardProgress";
import { LoadingState } from "@/components/ui/PageStates";
import { useOnboardingDashboard } from "@/lib/onboarding-hooks";
import { formatMinutesRemaining } from "@/lib/onboarding-ui";
import { wizardNextRoute, wizardPrevRoute, type WizardStepId } from "@/lib/onboarding-wizard";
import { cn } from "@/lib/utils";

const HUB_ROUTE = "/onboarding";

export function OnboardingWizardShell({
  stepId,
  title,
  subtitle,
  children,
  showNav = true,
  nextLabel,
  hideNext = false,
}: {
  stepId: WizardStepId;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  showNav?: boolean;
  nextLabel?: string;
  hideNext?: boolean;
}) {
  const { data: dashboard, isLoading } = useOnboardingDashboard();
  const nextRoute = wizardNextRoute(stepId);
  const prevRoute = wizardPrevRoute(stepId);

  if (isLoading && !dashboard) {
    return <LoadingState message="Loading setup…" />;
  }

  return (
    <div className="min-h-full bg-gradient-to-b from-slate-50 via-white to-slate-50 dark-tenant:from-surface-dark-page dark-tenant:via-surface-dark-page dark-tenant:to-surface-dark-elevated">
      {dashboard?.new_milestones?.length ? (
        <OnboardingCelebration milestones={dashboard.new_milestones} />
      ) : null}

      <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur sticky top-0 z-20 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated/90">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-4">
          <div className="flex items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-brand-50 flex items-center justify-center ring-1 ring-brand-100 dark-tenant:bg-violet-500/10 dark-tenant:ring-violet-500/20">
                <Rocket className="text-brand-600 dark-tenant:text-violet-400" size={20} />
              </div>
              <div>
                <Link
                  href={HUB_ROUTE}
                  className="text-sm font-semibold text-brand-600 hover:underline dark-tenant:text-violet-400"
                >
                  Setup Hub
                </Link>
                <p className="text-xs text-gray-500 flex items-center gap-1.5 mt-0.5 dark-tenant:text-slate-500">
                  <Clock size={11} />
                  {formatMinutesRemaining(dashboard?.estimated_minutes_remaining ?? 0)} remaining
                </p>
              </div>
            </div>
          </div>
          <OnboardingWizardProgress />
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-8 sm:py-10">
        <div className="mb-8 animate-fade-in-up">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-navy-900 dark-tenant:text-slate-50">
            {title}
          </h1>
          {subtitle ? (
            <p className="text-sm sm:text-base text-gray-600 mt-2 leading-relaxed max-w-2xl dark-tenant:text-slate-400">
              {subtitle}
            </p>
          ) : null}
        </div>

        <div className="animate-fade-in-up" style={{ animationDelay: "80ms" }}>
          {children}
        </div>

        {showNav && (prevRoute || (nextRoute && !hideNext)) ? (
          <nav
            className="flex flex-wrap items-center justify-between gap-3 mt-10 pt-6 border-t border-slate-100 dark-tenant:border-white/[0.06]"
            aria-label="Step navigation"
          >
            {prevRoute ? (
              <Link
                href={prevRoute}
                className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-navy-900 px-3 py-2 rounded-lg hover:bg-slate-50 transition-colors dark-tenant:text-slate-400 dark-tenant:hover:text-slate-100 dark-tenant:hover:bg-white/[0.04]"
              >
                <ArrowLeft size={16} />
                Back
              </Link>
            ) : (
              <span />
            )}
            {nextRoute && !hideNext ? (
              <Link
                href={nextRoute}
                className={cn(
                  "inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white text-sm font-semibold px-5 py-2.5",
                  "hover:bg-brand-700 shadow-sm transition-colors dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
                )}
              >
                {nextLabel ?? "Continue"}
                <ArrowRight size={16} />
              </Link>
            ) : null}
          </nav>
        ) : null}
      </main>
    </div>
  );
}
