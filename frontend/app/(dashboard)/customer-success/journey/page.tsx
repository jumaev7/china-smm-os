"use client";

import { useState } from "react";
import {
  Activity,
  HeartPulse,
  RefreshCw,
  Rocket,
  Send,
  Shield,
  Star,
  Target,
} from "lucide-react";
import { CustomerSuccessPageHeader } from "@/components/customer-success/CustomerSuccessSubNav";
import { JourneyAchievementsPanel } from "@/components/customer-success/journey/JourneyAchievementsPanel";
import { JourneyActivityFeed } from "@/components/customer-success/journey/JourneyActivityFeed";
import { JourneyCustomerTimeline } from "@/components/customer-success/journey/JourneyCustomerTimeline";
import { JourneyDashboardSkeleton } from "@/components/customer-success/journey/JourneyDashboardSkeleton";
import { JourneyEmptyState } from "@/components/customer-success/journey/JourneyEmptyState";
import { JourneyFeatureAdoptionGrid } from "@/components/customer-success/journey/JourneyFeatureAdoptionGrid";
import { JourneyHealthGauge } from "@/components/customer-success/journey/JourneyHealthGauge";
import { JourneyNorthStarCard } from "@/components/customer-success/journey/JourneyNorthStarCard";
import { JourneyRecommendationsPanel } from "@/components/customer-success/journey/JourneyRecommendationsPanel";
import { ErrorState } from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import {
  useCustomerSuccessJourney,
  useCustomerSuccessSummary,
  useDismissJourneyRecommendation,
  useJourneyRefresh,
  useOnboardingReadinessForJourney,
} from "@/lib/customer-success-journey-hooks";
import { computeNorthStarProgress, publishingActivityLabel } from "@/lib/customer-success-journey-ui";
import { cn } from "@/lib/utils";

export default function CustomerSuccessJourneyPage() {
  const [dismissingId, setDismissingId] = useState<string | null>(null);

  const journeyQuery = useCustomerSuccessJourney();
  const summaryQuery = useCustomerSuccessSummary();
  const readinessQuery = useOnboardingReadinessForJourney();
  const refreshMutation = useJourneyRefresh();
  const dismissMutation = useDismissJourneyRecommendation();

  const journey = journeyQuery.data;
  const summary = summaryQuery.data;
  const readiness = readinessQuery.data;

  const isLoading = journeyQuery.isLoading || summaryQuery.isLoading;
  const isError = journeyQuery.isError;

  const handleDismiss = async (id: string) => {
    setDismissingId(id);
    try {
      await dismissMutation.mutateAsync(id);
    } finally {
      setDismissingId(null);
    }
  };

  const handleRefresh = () => {
    void refreshMutation.mutate();
    void journeyQuery.refetch();
    void summaryQuery.refetch();
  };

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <CustomerSuccessPageHeader
          title="Customer Success"
          subtitle="How healthy is this customer? Real-time health, adoption, and journey progress."
        />
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshMutation.isPending || journeyQuery.isFetching}
          className={cn(
            "inline-flex items-center gap-2 self-start rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium",
            "text-gray-700 hover:border-brand-200 hover:text-brand-700 transition-colors disabled:opacity-60",
            "dark-tenant:bg-surface-dark-elevated dark-tenant:border-white/10 dark-tenant:text-slate-300",
            "dark-tenant:hover:border-violet-500/30 dark-tenant:hover:text-violet-300",
          )}
          aria-label="Refresh dashboard"
        >
          <RefreshCw
            size={14}
            className={cn((refreshMutation.isPending || journeyQuery.isFetching) && "animate-spin")}
          />
          Refresh
        </button>
      </div>

      {isLoading && <JourneyDashboardSkeleton />}

      {isError && (
        <ErrorState
          message={journeyQuery.error instanceof Error ? journeyQuery.error.message : "Failed to load dashboard"}
          onRetry={() => journeyQuery.refetch()}
        />
      )}

      {!isLoading && !isError && journey && !journey.platform_ready && (
        <JourneyEmptyState platformReady={false} />
      )}

      {!isLoading && !isError && journey && journey.platform_ready && (
        <>
          {/* Top KPI row */}
          <section
            className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 animate-fade-in-up"
            aria-label="Key performance indicators"
          >
            <KpiCard
              label="Overall Health"
              value={journey.health_score?.score ?? journey.success_score.score}
              sub={journey.health_score?.label ?? journey.success_score.label}
              icon={HeartPulse}
              iconClassName="bg-emerald-50 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
              href="/customer-success"
            />
            <KpiCard
              label="Adoption Score"
              value={`${summary?.adoption_score ?? journey.success_score.feature_breadth_pct}%`}
              sub="Feature breadth"
              icon={Activity}
              iconClassName="bg-sky-50 text-sky-600 dark-tenant:bg-sky-500/15 dark-tenant:text-sky-400"
              href="/customer-success/adoption"
            />
            <KpiCard
              label="Platform Readiness"
              value={readiness?.platform_ready ? "Ready" : `${readiness?.platform_readiness_percent ?? 0}%`}
              sub={journey.status === "completed" ? "Journey complete" : `Day ${journey.journey_day} of 30`}
              icon={Shield}
              iconClassName="bg-violet-50 text-violet-600 dark-tenant:bg-violet-500/15 dark-tenant:text-violet-400"
              href="/onboarding"
            />
            <KpiCard
              label="North Star Progress"
              value={`${computeNorthStarProgress(journey)}%`}
              sub={journey.north_star_label ?? "Set your goal"}
              icon={Star}
              iconClassName="bg-amber-50 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
              href="/onboarding/goal"
            />
            <KpiCard
              label="Publishing Activity"
              value={publishingActivityLabel(journey)}
              sub={`${journey.days_remaining}d left in journey`}
              icon={Send}
              iconClassName="bg-pink-50 text-pink-600 dark-tenant:bg-pink-500/15 dark-tenant:text-pink-400"
              href="/publishing"
            />
          </section>

          {/* Health + North Star */}
          <section className="grid lg:grid-cols-2 gap-6">
            {journey.health_score ? (
              <JourneyHealthGauge
                healthScore={journey.health_score}
                journeyDay={journey.journey_day}
                delay={80}
              />
            ) : (
              <div className="card-premium p-8 flex flex-col items-center justify-center text-center animate-fade-in-up">
                <Target size={32} className="text-violet-500 mb-4" />
                <p className="text-sm font-semibold text-navy-900 dark-tenant:text-slate-100">Health score calibrating</p>
                <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-2">
                  Success score: {journey.success_score.score}/100 — {journey.success_score.label}
                </p>
              </div>
            )}
            <JourneyNorthStarCard journey={journey} delay={120} />
          </section>

          {/* Feature adoption */}
          <JourneyFeatureAdoptionGrid features={journey.features} delay={160} />

          {/* Timeline + Recommendations */}
          <section className="grid lg:grid-cols-5 gap-6">
            <div className="lg:col-span-2">
              <JourneyCustomerTimeline
                journey={journey}
                readiness={readiness}
                delay={200}
              />
            </div>
            <div className="lg:col-span-3">
              <JourneyRecommendationsPanel
                recommendations={journey.recommendations}
                onDismiss={handleDismiss}
                dismissingId={dismissingId}
                delay={220}
              />
            </div>
          </section>

          {/* Achievements + Activity */}
          <section className="grid lg:grid-cols-2 gap-6">
            <JourneyAchievementsPanel journey={journey} delay={260} />
            <JourneyActivityFeed
              timeline={journey.timeline}
              weeklyWins={journey.weekly_wins}
              delay={280}
            />
          </section>

          {/* Journey status banner */}
          {journey.status === "completed" && (
            <div
              className={cn(
                "rounded-2xl border border-emerald-200 bg-gradient-to-r from-emerald-50 to-white p-5 flex items-center gap-4",
                "dark-tenant:border-emerald-500/20 dark-tenant:from-emerald-500/[0.08] dark-tenant:to-transparent animate-fade-in-up",
              )}
            >
              <div className="w-12 h-12 rounded-xl bg-emerald-500 text-white flex items-center justify-center shrink-0">
                <Rocket size={22} />
              </div>
              <div>
                <p className="font-semibold text-emerald-900 dark-tenant:text-emerald-300">
                  30-day journey complete
                </p>
                <p className="text-sm text-emerald-700/80 dark-tenant:text-emerald-400/80 mt-0.5">
                  Renewal readiness: {journey.renewal_readiness.score}/100 — {journey.renewal_readiness.label}
                </p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
