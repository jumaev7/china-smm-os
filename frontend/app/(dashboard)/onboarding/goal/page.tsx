"use client";

import { useState } from "react";
import { NorthStarGoalCard } from "@/components/onboarding/NorthStarGoalCard";
import { OnboardingCardsSkeleton } from "@/components/onboarding/OnboardingEmptyState";
import { OnboardingWizardShell } from "@/components/onboarding/OnboardingWizardShell";
import { useOnboardingReadiness, useSaveNorthStarGoal } from "@/lib/onboarding-hooks";
import { NORTH_STAR_GOAL_CARDS, type NorthStarGoalKey } from "@/lib/onboarding-wizard";

export default function OnboardingGoalPage() {
  const { data: readiness, isLoading } = useOnboardingReadiness();
  const save = useSaveNorthStarGoal();
  const [pending, setPending] = useState<NorthStarGoalKey | null>(null);

  const selected = (readiness?.north_star_goal as NorthStarGoalKey | null) ?? null;

  function handleSelect(key: NorthStarGoalKey) {
    setPending(key);
    save.mutate(key, {
      onSettled: () => setPending(null),
    });
  }

  return (
    <OnboardingWizardShell
      stepId="goal"
      title="What's your north star goal?"
      subtitle="Choose one priority — we'll tailor your customer success journey and recommendations around it."
      nextLabel="Continue to connections"
    >
      <div className="space-y-4 max-w-2xl">
        <p className="text-sm text-gray-500 dark-tenant:text-slate-500">
          Select a single goal. You can change this later from your dashboard.
        </p>

        {isLoading ? (
          <OnboardingCardsSkeleton count={5} />
        ) : (
          <div className="grid gap-3" role="radiogroup" aria-label="North star goal">
            {NORTH_STAR_GOAL_CARDS.map((goal, i) => (
              <NorthStarGoalCard
                key={goal.key}
                goal={goal}
                selected={selected === goal.key || pending === goal.key}
                onSelect={() => handleSelect(goal.key)}
                saving={save.isPending && pending === goal.key}
                index={i}
              />
            ))}
          </div>
        )}

        {selected ? (
          <p className="text-sm text-emerald-700 bg-emerald-50 rounded-xl px-4 py-3 border border-emerald-100 animate-fade-in dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-300 dark-tenant:border-emerald-500/20">
            Goal set: <strong>{NORTH_STAR_GOAL_CARDS.find((g) => g.key === selected)?.title}</strong> — your
            journey is personalized.
          </p>
        ) : null}
      </div>
    </OnboardingWizardShell>
  );
}
