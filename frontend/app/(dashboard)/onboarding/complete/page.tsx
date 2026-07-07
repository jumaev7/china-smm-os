"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Rocket, Sparkles, Target } from "lucide-react";
import { OnboardingCelebration } from "@/components/onboarding/OnboardingCelebration";
import { OnboardingIllustration } from "@/components/onboarding/OnboardingIllustration";
import { OnboardingWizardShell } from "@/components/onboarding/OnboardingWizardShell";
import { LoadingState } from "@/components/ui/PageStates";
import { useOnboardingDashboard, useOnboardingReadiness } from "@/lib/onboarding-hooks";
import { NORTH_STAR_GOAL_CARDS } from "@/lib/onboarding-wizard";
import { cn } from "@/lib/utils";

export default function OnboardingCompletePage() {
  const { data: dashboard, isLoading: dashLoading } = useOnboardingDashboard();
  const { data: readiness, isLoading: readyLoading } = useOnboardingReadiness();
  const [showConfetti, setShowConfetti] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShowConfetti(true), 300);
    return () => clearTimeout(timer);
  }, []);

  if (dashLoading || readyLoading) {
    return <LoadingState message="Finalizing your workspace…" />;
  }

  const platformReady = readiness?.platform_ready ?? false;
  const goalLabel =
    NORTH_STAR_GOAL_CARDS.find((g) => g.key === readiness?.north_star_goal)?.title ??
    readiness?.north_star_label;

  return (
    <OnboardingWizardShell
      stepId="complete"
      title="You're all set!"
      subtitle="Your workspace is configured and your customer success journey is active."
      showNav={false}
      hideNext
    >
      {dashboard?.new_milestones?.length ? (
        <OnboardingCelebration milestones={dashboard.new_milestones} />
      ) : null}

      <div className="max-w-2xl mx-auto space-y-8">
        <div
          className={cn(
            "relative overflow-hidden rounded-3xl border p-8 sm:p-12 text-center shadow-elevated animate-scale-in",
            "border-emerald-200/80 bg-gradient-to-br from-emerald-50 via-white to-brand-50/40",
            "dark-tenant:border-emerald-500/20 dark-tenant:from-emerald-500/10 dark-tenant:via-surface-dark-card dark-tenant:to-violet-500/5",
          )}
        >
          {showConfetti ? <SuccessParticles /> : null}

          <div className="relative">
            <OnboardingIllustration variant="success" className="w-full max-w-[220px] h-40 mx-auto mb-6" />

            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-emerald-100 mb-5 animate-celebrate dark-tenant:bg-emerald-500/15">
              <CheckCircle2 size={32} className="text-emerald-600 dark-tenant:text-emerald-400" />
            </div>

            <h2 className="text-2xl sm:text-3xl font-bold text-navy-900 dark-tenant:text-slate-50">
              Platform Ready
            </h2>
            <p className="text-gray-600 mt-3 max-w-md mx-auto leading-relaxed dark-tenant:text-slate-400">
              {platformReady
                ? "Your factory workspace is operational. Start publishing, capturing leads, and growing export revenue."
                : "Core setup is complete. Finish remaining optional steps from the setup hub when you're ready."}
            </p>
          </div>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <SuccessCard
            icon={Rocket}
            title="Platform Ready"
            description={
              platformReady
                ? "All required platform steps are complete."
                : `${readiness?.platform_readiness_percent ?? 0}% platform readiness — keep building momentum.`
            }
            complete={platformReady}
            delay={100}
          />
          <SuccessCard
            icon={Target}
            title="Customer Success Journey Activated"
            description={
              goalLabel
                ? `Personalized for: ${goalLabel}`
                : "Your journey checkpoints and recommendations are live."
            }
            complete={!!readiness?.north_star_goal}
            delay={200}
          />
        </div>

        <div className="rounded-2xl border border-brand-100 bg-brand-50/40 p-5 flex items-start gap-4 dark-tenant:border-violet-500/20 dark-tenant:bg-violet-500/10">
          <Sparkles size={20} className="text-brand-600 shrink-0 mt-0.5 dark-tenant:text-violet-400" />
          <div>
            <p className="font-semibold text-navy-900 dark-tenant:text-slate-100">What happens next?</p>
            <ul className="text-sm text-gray-600 mt-2 space-y-1 dark-tenant:text-slate-400">
              <li>• Upload content and schedule your first publication</li>
              <li>• Explore the CRM pipeline and buyer matching tools</li>
              <li>• Track weekly wins in your customer success journey</li>
            </ul>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white font-semibold px-6 py-3.5 hover:bg-brand-700 shadow-sm transition-colors animate-scale-in dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500"
          >
            Go To Dashboard
            <ArrowRight size={18} />
          </Link>
          <Link
            href="/onboarding"
            className="text-sm font-medium text-gray-600 hover:text-navy-900 dark-tenant:text-slate-400 dark-tenant:hover:text-slate-200"
          >
            Return to setup hub
          </Link>
        </div>
      </div>
    </OnboardingWizardShell>
  );
}

function SuccessCard({
  icon: Icon,
  title,
  description,
  complete,
  delay,
}: {
  icon: typeof Rocket;
  title: string;
  description: string;
  complete: boolean;
  delay: number;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border p-5 animate-fade-in-up",
        complete
          ? "border-emerald-100 bg-emerald-50/40 dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/5"
          : "border-slate-200 bg-white dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card",
      )}
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "w-10 h-10 rounded-xl flex items-center justify-center shrink-0",
            complete
              ? "bg-emerald-100 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
              : "bg-slate-100 text-slate-500 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-400",
          )}
        >
          <Icon size={20} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-navy-900 dark-tenant:text-slate-100">{title}</h3>
            {complete ? <CheckCircle2 size={16} className="text-emerald-500" /> : null}
          </div>
          <p className="text-sm text-gray-600 mt-1 dark-tenant:text-slate-400">{description}</p>
        </div>
      </div>
    </div>
  );
}

function SuccessParticles() {
  const dots = [
    { top: "8%", left: "10%", color: "bg-emerald-400", delay: "0ms" },
    { top: "15%", left: "88%", color: "bg-brand-400", delay: "120ms" },
    { top: "75%", left: "8%", color: "bg-violet-400", delay: "200ms" },
    { top: "82%", left: "92%", color: "bg-amber-400", delay: "80ms" },
    { top: "45%", left: "5%", color: "bg-rose-400", delay: "160ms" },
    { top: "50%", left: "94%", color: "bg-cyan-400", delay: "240ms" },
  ];

  return (
  <>
    {dots.map((d, i) => (
      <span
        key={i}
        className={cn("absolute w-2 h-2 rounded-full animate-celebrate opacity-70", d.color)}
        style={{ top: d.top, left: d.left, animationDelay: d.delay }}
        aria-hidden
      />
    ))}
  </>
  );
}
