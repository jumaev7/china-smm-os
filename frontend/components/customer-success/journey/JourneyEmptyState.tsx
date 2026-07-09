"use client";

import Link from "next/link";
import { Rocket } from "lucide-react";
import { OnboardingIllustration } from "@/components/onboarding/OnboardingIllustration";
import { cn } from "@/lib/utils";

export function JourneyEmptyState({
  platformReady,
  onRefresh,
  refreshing,
}: {
  platformReady: boolean;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  if (!platformReady) {
    return (
      <div className="card-premium p-8 sm:p-12 text-center animate-fade-in-up max-w-2xl mx-auto">
        <OnboardingIllustration variant="platform" className="w-full max-w-[220px] h-40 mx-auto mb-6" />
        <div className="w-12 h-12 rounded-2xl bg-violet-100 flex items-center justify-center mx-auto mb-4 dark-tenant:bg-violet-500/10">
          <Rocket size={22} className="text-violet-600 dark-tenant:text-violet-400" />
        </div>
        <h2 className="text-xl font-semibold text-navy-900 dark-tenant:text-slate-100">
          Complete onboarding to unlock your success dashboard
        </h2>
        <p className="text-sm text-gray-600 dark-tenant:text-slate-400 mt-3 max-w-md mx-auto leading-relaxed">
          Your Customer Success Journey activates once your platform is ready. Finish setup to track health,
          adoption, and revenue milestones in one place.
        </p>
        <Link
          href="/onboarding"
          className={cn(
            "inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white font-semibold text-sm px-6 py-3 mt-6",
            "hover:bg-brand-700 shadow-sm transition-colors",
            "dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500 dark-tenant:shadow-glow",
          )}
        >
          Continue onboarding
        </Link>
      </div>
    );
  }

  return (
    <div className="card-premium p-8 sm:p-12 text-center animate-fade-in-up max-w-2xl mx-auto">
      <OnboardingIllustration variant="success" className="w-full max-w-[220px] h-40 mx-auto mb-6" />
      <h2 className="text-xl font-semibold text-navy-900 dark-tenant:text-slate-100">
        Your success journey is warming up
      </h2>
      <p className="text-sm text-gray-600 dark-tenant:text-slate-400 mt-3 max-w-md mx-auto leading-relaxed">
        We&apos;re gathering your first activity signals. Refresh to pull the latest health score, recommendations,
        and milestones.
      </p>
      {onRefresh && (
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className={cn(
            "inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white font-semibold text-sm px-6 py-3 mt-6",
            "hover:bg-brand-700 shadow-sm transition-colors disabled:opacity-60",
            "dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500 dark-tenant:shadow-glow",
          )}
        >
          {refreshing ? "Refreshing…" : "Refresh dashboard"}
        </button>
      )}
    </div>
  );
}
