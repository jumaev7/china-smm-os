"use client";

import type { CustomerSuccessJourneyDashboard } from "@/lib/api";
import { buildAchievements } from "@/lib/customer-success-journey-ui";
import { cn } from "@/lib/utils";

const TONE_STYLES = {
  gold: "from-amber-400/20 to-yellow-500/10 border-amber-300/40 text-amber-700 dark-tenant:from-amber-500/15 dark-tenant:to-yellow-500/5 dark-tenant:border-amber-500/25 dark-tenant:text-amber-300",
  emerald: "from-emerald-400/20 to-emerald-500/10 border-emerald-300/40 text-emerald-700 dark-tenant:from-emerald-500/15 dark-tenant:to-emerald-500/5 dark-tenant:border-emerald-500/25 dark-tenant:text-emerald-300",
  violet: "from-violet-400/20 to-violet-500/10 border-violet-300/40 text-violet-700 dark-tenant:from-violet-500/15 dark-tenant:to-violet-500/5 dark-tenant:border-violet-500/25 dark-tenant:text-violet-300",
  sky: "from-sky-400/20 to-sky-500/10 border-sky-300/40 text-sky-700 dark-tenant:from-sky-500/15 dark-tenant:to-sky-500/5 dark-tenant:border-sky-500/25 dark-tenant:text-sky-300",
  amber: "from-orange-400/20 to-orange-500/10 border-orange-300/40 text-orange-700 dark-tenant:from-orange-500/15 dark-tenant:to-orange-500/5 dark-tenant:border-orange-500/25 dark-tenant:text-orange-300",
};

export function JourneyAchievementsPanel({
  journey,
  delay = 0,
}: {
  journey: CustomerSuccessJourneyDashboard;
  delay?: number;
}) {
  const achievements = buildAchievements(journey);
  const earnedCount = achievements.filter((a) => a.earned).length;

  return (
    <section
      className="card-premium p-6 animate-fade-in-up"
      style={{ animationDelay: `${delay}ms` }}
      aria-label="Achievements"
    >
      <div className="flex items-center justify-between gap-3 mb-5">
        <div>
          <h2 className="section-title text-base font-semibold text-navy-900 dark-tenant:text-slate-100">
            Achievements
          </h2>
          <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">
            {earnedCount} of {achievements.length} badges earned
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {achievements.map((badge, i) => {
          const Icon = badge.icon;
          return (
            <div
              key={badge.id}
              className={cn(
                "relative rounded-2xl border p-4 text-center transition-all duration-300 animate-fade-in-up",
                "bg-gradient-to-br",
                badge.earned
                  ? TONE_STYLES[badge.tone]
                  : "from-slate-50 to-slate-100/50 border-slate-200/60 opacity-50 grayscale dark-tenant:from-white/[0.02] dark-tenant:to-white/[0.04] dark-tenant:border-white/[0.06]",
              )}
              style={{ animationDelay: `${delay + i * 40}ms` }}
              title={badge.description}
            >
              <div
                className={cn(
                  "w-10 h-10 rounded-xl mx-auto flex items-center justify-center mb-2",
                  badge.earned
                    ? "bg-white/60 dark-tenant:bg-white/10"
                    : "bg-white/40 dark-tenant:bg-white/[0.04]",
                )}
              >
                <Icon size={18} />
              </div>
              <p className="text-xs font-bold leading-tight">{badge.label}</p>
              {badge.earned && (
                <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-emerald-500 shadow-sm" aria-hidden />
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
