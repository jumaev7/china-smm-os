"use client";

import Link from "next/link";
import { useEffect } from "react";
import { ArrowRight, CheckCircle2, Lightbulb, TrendingUp } from "lucide-react";
import { OnboardingLayout } from "./OnboardingLayout";
import { OnboardingIllustration } from "./OnboardingIllustration";
import { useOnboardingRefresh, useOnboardingStep } from "@/lib/onboarding-hooks";
import { STEP_STATUS_META } from "@/lib/onboarding-ui";
import { cn } from "@/lib/utils";

type IllustrationVariant = "platform" | "business" | "success" | "executive";

export function OnboardingStepShell({
  stepId,
  title,
  subtitle,
  illustration = "platform",
  children,
  nextHref,
  nextLabel,
}: {
  stepId: string;
  title: string;
  subtitle?: string;
  illustration?: IllustrationVariant;
  children: React.ReactNode;
  nextHref?: string;
  nextLabel?: string;
}) {
  const step = useOnboardingStep(stepId);
  const refresh = useOnboardingRefresh();

  useEffect(() => {
    refresh.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId]);

  const isComplete = step?.status === "completed";
  const meta = step ? STEP_STATUS_META[step.status] : null;

  return (
    <OnboardingLayout title={title} subtitle={subtitle} contextStep={stepId}>
      <div className="space-y-6 max-w-2xl">
        {step ? (
          <div
            className={cn(
              "rounded-2xl border p-5 animate-fade-in-up",
              isComplete
                ? "border-emerald-100 bg-gradient-to-br from-emerald-50/80 to-white"
                : "border-brand-100 bg-gradient-to-br from-brand-50/50 to-white",
            )}
          >
            <div className="flex flex-col sm:flex-row gap-5">
              <OnboardingIllustration variant={illustration} className="w-full sm:w-36 h-28 shrink-0" />
              <div className="flex-1 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  {meta ? (
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide ring-1",
                        meta.badge,
                      )}
                    >
                      {isComplete ? <CheckCircle2 size={10} /> : null}
                      {meta.label}
                    </span>
                  ) : null}
                  <span className="text-xs text-gray-400">~{step.estimated_minutes} min</span>
                </div>

                {step.why_it_matters ? (
                  <p className="text-sm text-gray-700 leading-relaxed flex gap-2">
                    <Lightbulb size={15} className="text-amber-500 shrink-0 mt-0.5" />
                    <span>{step.why_it_matters}</span>
                  </p>
                ) : null}

                {!isComplete && step.next_action ? (
                  <p className="text-xs font-medium text-brand-800 bg-brand-50 rounded-lg px-3 py-2">
                    {step.next_action}
                  </p>
                ) : null}

                {step.business_value ? (
                  <p className="text-xs text-gray-600 flex items-start gap-1.5">
                    <TrendingUp size={12} className="text-emerald-500 shrink-0 mt-0.5" />
                    <span>
                      <span className="font-medium">Business impact: </span>
                      {step.business_value}
                    </span>
                  </p>
                ) : null}

                {isComplete ? (
                  <p className="text-sm font-medium text-emerald-700 flex items-center gap-1.5 animate-celebrate">
                    <CheckCircle2 size={16} />
                    Step complete — great work!
                  </p>
                ) : null}
              </div>
            </div>
          </div>
        ) : null}

        {children}

        {nextHref ? (
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Link
              href={nextHref}
              className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-brand-700 shadow-sm transition-colors"
            >
              {nextLabel ?? "Continue"}
              <ArrowRight size={16} />
            </Link>
            <Link href="/onboarding" className="text-sm text-gray-500 hover:text-navy-900">
              Back to setup hub
            </Link>
          </div>
        ) : null}
      </div>
    </OnboardingLayout>
  );
}
