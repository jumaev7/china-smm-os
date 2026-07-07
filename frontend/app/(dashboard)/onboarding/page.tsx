"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  Clock,
  RefreshCw,
  Sparkles,
  Target,
  Zap,
} from "lucide-react";
import toast from "react-hot-toast";
import { tenantOnboardingApi } from "@/lib/api";
import { countCompletedSteps, formatMinutesRemaining, readinessHeadline } from "@/lib/onboarding-ui";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { OnboardingAssistant } from "@/components/onboarding/OnboardingAssistant";
import { OnboardingAutoConfigPanel } from "@/components/onboarding/OnboardingAutoConfigPanel";
import { OnboardingBusinessImpact } from "@/components/onboarding/OnboardingBusinessImpact";
import { OnboardingCelebration } from "@/components/onboarding/OnboardingCelebration";
import { OnboardingIllustration } from "@/components/onboarding/OnboardingIllustration";
import { OnboardingJourneyProgress } from "@/components/onboarding/OnboardingJourneyProgress";
import { OnboardingStepCard } from "@/components/onboarding/OnboardingStepCard";
import { ExecutiveWalkthroughPanels } from "@/components/onboarding/ExecutiveWalkthroughPanels";
import { FirstSuccessMilestones } from "@/components/onboarding/FirstSuccessMilestones";
import { ReadinessGauge } from "@/components/onboarding/ReadinessGauge";
import { useOnboardingDashboard, useOnboardingReadiness } from "@/lib/onboarding-hooks";

export default function OnboardingDashboardPage() {
  const qc = useQueryClient();
  const { data: dashboard, isLoading: dashLoading, isError, error, refetch } = useOnboardingDashboard();
  const { data: readiness, isLoading: readyLoading } = useOnboardingReadiness();

  const refresh = useMutation({
    mutationFn: () => tenantOnboardingApi.refresh().then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      if (res.progress.readiness) {
        qc.setQueryData(["tenant-onboarding-readiness"], res.progress.readiness);
      } else {
        qc.invalidateQueries({ queryKey: ["tenant-onboarding-readiness"] });
      }
      if (res.progress.new_milestones.length) {
        res.progress.new_milestones.forEach((m) => toast.success(m.message, { duration: 5000 }));
      }
    },
  });

  const demo = useMutation({
    mutationFn: () => tenantOnboardingApi.generateDemoData().then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      if (res.progress.readiness) {
        qc.setQueryData(["tenant-onboarding-readiness"], res.progress.readiness);
      }
      toast.success(res.message);
    },
    onError: () => toast.error("Could not generate demo data"),
  });

  if (dashLoading || readyLoading) {
    return <LoadingState message="Preparing your guided setup experience…" />;
  }
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load onboarding"}
        onRetry={() => refetch()}
      />
    );
  }
  if (!dashboard || !readiness) return null;

  const platformDone = countCompletedSteps(readiness.platform_steps);
  const businessDone = countCompletedSteps(readiness.business_steps);
  const headline = readinessHeadline(
    readiness.platform_ready,
    readiness.overall_percent,
    readiness.next_step,
  );

  return (
    <div className="min-h-full bg-gradient-to-b from-slate-50 via-white to-slate-50">
      <OnboardingCelebration milestones={dashboard.new_milestones} />

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-10">
        {/* Hero */}
        <section className="relative overflow-hidden rounded-3xl border border-brand-100 bg-gradient-to-br from-brand-50 via-white to-violet-50/40 shadow-card">
          <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-brand-200/30 blur-3xl pointer-events-none" />
          <div className="absolute -bottom-16 -left-16 w-48 h-48 rounded-full bg-violet-200/30 blur-3xl pointer-events-none" />

          <div className="relative grid lg:grid-cols-[1fr_240px] gap-8 p-6 sm:p-10">
            <div className="space-y-6 animate-fade-in-up">
              <div className="flex flex-wrap items-center gap-3">
                <span className="inline-flex items-center gap-1.5 rounded-full bg-white/80 border border-brand-100 px-3 py-1 text-xs font-semibold text-brand-700 shadow-sm">
                  <Zap size={12} />
                  Guided setup
                </span>
                {readiness.auto_config_applied ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 border border-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700">
                    <Sparkles size={12} />
                    Workspace pre-configured
                  </span>
                ) : null}
              </div>

              <div>
                <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-navy-900">{headline}</h1>
                <p className="text-sm sm:text-base text-gray-600 mt-2 max-w-xl leading-relaxed">
                  We&apos;ll walk you through platform setup, then your first real business wins — with clear impact at
                  every step.
                </p>
              </div>

              <div className="flex flex-wrap gap-4 text-sm">
                <StatPill icon={Target} label="Overall progress" value={`${readiness.overall_percent}%`} />
                <StatPill
                  icon={Clock}
                  label="Estimated remaining"
                  value={formatMinutesRemaining(readiness.estimated_minutes_remaining)}
                />
                <StatPill
                  icon={Building2}
                  label="Phase"
                  value={
                    dashboard.status === "completed"
                      ? "Complete"
                      : readiness.platform_ready
                        ? "Business"
                        : "Platform"
                  }
                />
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <Link
                  href="/onboarding/welcome"
                  className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-brand-700 shadow-sm transition-colors animate-scale-in"
                >
                  Start guided setup
                  <ArrowRight size={16} />
                </Link>
                {readiness.next_step ? (
                  <Link
                    href={readiness.next_step.route}
                    className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-brand-700 shadow-sm transition-colors animate-scale-in"
                  >
                    Continue: {readiness.next_step.label}
                    <ArrowRight size={16} />
                  </Link>
                ) : dashboard.status === "completed" ? (
                  <Link
                    href="/dashboard"
                    className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-emerald-700"
                  >
                    Go to executive dashboard
                    <ArrowRight size={16} />
                  </Link>
                ) : null}
                <button
                  type="button"
                  onClick={() => refresh.mutate()}
                  disabled={refresh.isPending}
                  className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-navy-900 px-3 py-2 rounded-lg hover:bg-white/60 transition-colors"
                >
                  <RefreshCw size={14} className={refresh.isPending ? "animate-spin" : ""} />
                  Sync progress
                </button>
              </div>
            </div>

            <div className="hidden lg:block animate-fade-in-up" style={{ animationDelay: "120ms" }}>
              <OnboardingIllustration variant="platform" className="h-full min-h-[180px]" />
            </div>
          </div>
        </section>

        <OnboardingJourneyProgress readiness={readiness} />

        {/* Readiness gauges */}
        <section className="grid sm:grid-cols-3 gap-6">
          <div className="sm:col-span-1 rounded-2xl border border-slate-200 bg-white p-6 shadow-card flex justify-center">
            <ReadinessGauge
              percent={readiness.overall_percent}
              label="Overall readiness"
              sublabel={`${platformDone + businessDone} steps done`}
              tone="brand"
              size="lg"
            />
          </div>
          <div className="sm:col-span-1 rounded-2xl border border-slate-200 bg-white p-6 shadow-card flex justify-center">
            <ReadinessGauge
              percent={readiness.platform_readiness_percent}
              label="Platform readiness"
              sublabel={`${platformDone}/${readiness.platform_steps.length} steps`}
              tone="brand"
              delay={80}
            />
          </div>
          <div className="sm:col-span-1 rounded-2xl border border-slate-200 bg-white p-6 shadow-card flex justify-center">
            <ReadinessGauge
              percent={readiness.business_readiness_percent}
              label="Business readiness"
              sublabel={
                readiness.platform_ready
                  ? `${businessDone}/${readiness.business_steps.length} steps`
                  : "Unlocks after platform"
              }
              tone={readiness.platform_ready ? "emerald" : "amber"}
              delay={160}
            />
          </div>
        </section>

        {readiness.publishing_blockers.length > 0 ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 flex gap-4 animate-fade-in">
            <AlertTriangle className="text-amber-600 shrink-0" size={22} />
            <div>
              <p className="font-semibold text-amber-900">Publishing needs attention</p>
              <ul className="mt-2 space-y-1 text-sm text-amber-800">
                {readiness.publishing_blockers.map((b) => (
                  <li key={b}>• {b}</li>
                ))}
              </ul>
            </div>
          </div>
        ) : null}

        <div className="grid xl:grid-cols-[1fr_320px] gap-8">
          <div className="space-y-10">
            <PhaseSection
              title="Platform readiness"
              subtitle="Connect your factory identity, channels, and content engine"
              illustration="platform"
              complete={readiness.platform_ready}
              completedCount={platformDone}
              totalCount={readiness.platform_steps.length}
            >
              <div className="space-y-3">
                {readiness.platform_steps.map((step, i) => (
                  <OnboardingStepCard key={step.id} step={step} index={i} />
                ))}
              </div>
            </PhaseSection>

            <PhaseSection
              title="Business readiness"
              subtitle="Capture leads, buyers, deals, and your first commercial proposal"
              illustration="business"
              complete={readiness.business_steps.every((s) => !s.required || s.status === "completed")}
              completedCount={businessDone}
              totalCount={readiness.business_steps.length}
              locked={!readiness.platform_ready}
            >
              <div className={cn("space-y-3", !readiness.platform_ready && "opacity-50 pointer-events-none")}>
                {readiness.business_steps.map((step, i) => (
                  <OnboardingStepCard key={step.id} step={step} index={i} locked={!readiness.platform_ready} />
                ))}
              </div>
              {!readiness.platform_ready ? (
                <p className="text-sm text-amber-700 bg-amber-50 rounded-xl px-4 py-3 mt-4 border border-amber-100">
                  Finish platform setup to unlock business milestones — your CRM and proposal tools are waiting.
                </p>
              ) : null}
            </PhaseSection>

            <OnboardingBusinessImpact />

            <FirstSuccessMilestones
              firstSuccess={readiness.first_success}
              platformReady={readiness.platform_ready}
            />

            <div className="rounded-3xl border border-amber-100 bg-gradient-to-br from-amber-50/50 to-white p-6 sm:p-8 shadow-card">
              <ExecutiveWalkthroughPanels walkthrough={readiness.executive_walkthrough} />
            </div>
          </div>

          <aside className="space-y-5 xl:sticky xl:top-6 xl:self-start">
            {readiness.auto_config_applied ? <OnboardingAutoConfigPanel /> : null}

            {!dashboard.demo_data_generated ? (
              <div className="rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 to-white p-5 shadow-card animate-fade-in-up">
                <div className="flex items-center gap-2 text-violet-700 mb-2">
                  <Sparkles size={18} />
                  <span className="font-semibold text-sm">Explore with sample data</span>
                </div>
                <p className="text-sm text-violet-900/80 leading-relaxed">
                  One click adds sample buyers, leads, deals, and proposals so you can experience the full workflow
                  before going live.
                </p>
                <button
                  type="button"
                  onClick={() => demo.mutate()}
                  disabled={demo.isPending}
                  className="mt-4 w-full rounded-xl bg-violet-600 text-white text-sm font-semibold py-2.5 hover:bg-violet-700 disabled:opacity-50 transition-colors"
                >
                  {demo.isPending ? "Generating…" : "Generate demo environment"}
                </button>
              </div>
            ) : null}

            <OnboardingAssistant />

            <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-gray-600 shadow-card">
              <p className="font-semibold text-navy-900 mb-2">Need a human touch?</p>
              <p className="leading-relaxed">
                Your dedicated success team can join a live walkthrough once platform readiness hits 80%.
              </p>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

function StatPill({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock;
  label: string;
  value: string;
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-xl bg-white/70 border border-white px-3 py-2 shadow-sm">
      <Icon size={14} className="text-brand-500" />
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
        <p className="text-sm font-semibold text-navy-900 tabular-nums">{value}</p>
      </div>
    </div>
  );
}

function PhaseSection({
  title,
  subtitle,
  illustration,
  complete,
  completedCount,
  totalCount,
  locked,
  children,
}: {
  title: string;
  subtitle: string;
  illustration: "platform" | "business";
  complete: boolean;
  completedCount: number;
  totalCount: number;
  locked?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-brand-700">{title}</p>
            {complete ? (
              <span className="text-[10px] font-bold uppercase tracking-wide text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full animate-celebrate">
                Complete
              </span>
            ) : locked ? (
              <span className="text-[10px] font-bold uppercase tracking-wide text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
                Locked
              </span>
            ) : null}
          </div>
          <h2 className="text-xl font-semibold text-navy-900 mt-1">{subtitle}</h2>
          <p className="text-sm text-gray-500 mt-1">
            {completedCount} of {totalCount} steps complete
          </p>
          <div className="mt-3 h-2 rounded-full bg-slate-100 max-w-xs overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-700",
                complete ? "bg-emerald-500" : "bg-brand-500",
              )}
              style={{ width: `${totalCount ? (completedCount / totalCount) * 100 : 0}%` }}
            />
          </div>
        </div>
        <OnboardingIllustration variant={illustration} className="w-32 h-24 sm:w-40 sm:h-28 shrink-0 hidden sm:block" />
      </div>
      {children}
    </section>
  );
}
