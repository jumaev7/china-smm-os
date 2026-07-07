"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, Clock, Sparkles, Target } from "lucide-react";
import { factoryPlatformApi, tenantOnboardingApi } from "@/lib/api";
import { OnboardingIllustration } from "@/components/onboarding/OnboardingIllustration";
import { OnboardingWizardProgress } from "@/components/onboarding/OnboardingWizardProgress";
import { OnboardingWizardShell } from "@/components/onboarding/OnboardingWizardShell";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  useOnboardingDashboard,
  useOnboardingReadiness,
  useOnboardingTenantId,
} from "@/lib/onboarding-hooks";
import { formatMinutesRemaining } from "@/lib/onboarding-ui";

export default function OnboardingWelcomePage() {
  const qc = useQueryClient();
  const tenantId = useOnboardingTenantId();
  const { data: dashboard, isLoading: dashLoading, isError, error, refetch } = useOnboardingDashboard();
  const { data: readiness, isLoading: readyLoading } = useOnboardingReadiness();

  const { data: profile } = useQuery({
    queryKey: ["factory-profile", tenantId],
    queryFn: () => factoryPlatformApi.profile(tenantId).then((r) => r.data),
    enabled: !!tenantId,
  });

  const startSetup = useMutation({
    mutationFn: () => tenantOnboardingApi.refresh().then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      if (res.progress.readiness) {
        qc.setQueryData(["tenant-onboarding-readiness"], res.progress.readiness);
      }
    },
  });

  if (dashLoading || readyLoading) {
    return <LoadingState message="Preparing your workspace…" />;
  }
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load onboarding"}
        onRetry={() => refetch()}
      />
    );
  }

  const companyName = profile?.profile.company_name?.trim() || null;
  const displayName = companyName || "your company";
  const progress = readiness?.overall_percent ?? dashboard?.progress_percent ?? 0;
  const minutesLeft =
    readiness?.estimated_minutes_remaining ?? dashboard?.estimated_minutes_remaining ?? 15;

  return (
    <OnboardingWizardShell
      stepId="welcome"
      title={`Welcome${companyName ? `, ${companyName}` : ""}`}
      subtitle="Let's configure your export growth platform in a few guided steps."
      showNav={false}
      hideNext
    >
      <div className="space-y-8 max-w-2xl">
        <div className="card-premium overflow-hidden animate-fade-in-up">
          <div className="relative p-6 sm:p-8">
            <div className="absolute -top-16 -right-16 w-48 h-48 rounded-full bg-brand-200/20 blur-3xl pointer-events-none dark-tenant:bg-violet-500/10" />
            <div className="relative grid sm:grid-cols-[1fr_180px] gap-6 items-center">
              <div className="space-y-4">
                <div className="inline-flex items-center gap-2 rounded-full bg-brand-50 border border-brand-100 px-3 py-1 text-xs font-semibold text-brand-700 dark-tenant:bg-violet-500/10 dark-tenant:border-violet-500/20 dark-tenant:text-violet-300">
                  <Sparkles size={12} />
                  Enterprise onboarding
                </div>
                <p className="text-base sm:text-lg text-gray-700 leading-relaxed dark-tenant:text-slate-300">
                  China SMM OS helps <strong className="text-navy-900 dark-tenant:text-slate-100">{displayName}</strong>{" "}
                  reach international buyers with content, CRM, and publishing — all in one workspace.
                </p>
                <div className="flex flex-wrap gap-3">
                  <StatChip icon={Clock} label="Setup time" value={formatMinutesRemaining(minutesLeft)} />
                  <StatChip icon={Target} label="Progress" value={`${progress}%`} />
                  <StatChip icon={Building2} label="Steps" value="6 guided steps" />
                </div>
              </div>
              <OnboardingIllustration variant="platform" className="hidden sm:block h-36" />
            </div>
          </div>
        </div>

        <OnboardingWizardProgress className="lg:hidden" />

        <div className="grid sm:grid-cols-3 gap-3">
          {[
            { title: "Company profile", text: "Identity, industry, and market focus" },
            { title: "North star goal", text: "Personalized journey from day one" },
            { title: "Go live", text: "Connect channels and publish" },
          ].map((item, i) => (
            <div
              key={item.title}
              className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-card animate-fade-in-up dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <p className="text-sm font-semibold text-navy-900 dark-tenant:text-slate-100">{item.title}</p>
              <p className="text-xs text-gray-500 mt-1 dark-tenant:text-slate-500">{item.text}</p>
            </div>
          ))}
        </div>

        <Link
          href="/onboarding/company"
          onClick={() => startSetup.mutate()}
          className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white font-semibold px-6 py-3.5 hover:bg-brand-700 shadow-sm transition-all animate-scale-in dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500"
        >
          Start Setup
          <ArrowRight size={18} />
        </Link>
      </div>
    </OnboardingWizardShell>
  );
}

function StatChip({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Clock;
  label: string;
  value: string;
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-xl bg-slate-50 border border-slate-100 px-3 py-2 dark-tenant:bg-white/[0.04] dark-tenant:border-white/[0.06]">
      <Icon size={14} className="text-brand-500 dark-tenant:text-violet-400" />
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium dark-tenant:text-slate-500">
          {label}
        </p>
        <p className="text-sm font-semibold text-navy-900 tabular-nums dark-tenant:text-slate-200">{value}</p>
      </div>
    </div>
  );
}
