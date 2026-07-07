import type { OnboardingStepReadiness, OnboardingStepReadinessStatus } from "@/lib/api";

export const STEP_STATUS_META: Record<
  OnboardingStepReadinessStatus,
  { label: string; badge: string; icon: string }
> = {
  completed: {
    label: "Complete",
    badge: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    icon: "text-emerald-500",
  },
  missing: {
    label: "To do",
    badge: "bg-slate-50 text-slate-700 ring-slate-200",
    icon: "text-slate-400",
  },
  recommended: {
    label: "Recommended",
    badge: "bg-sky-50 text-sky-700 ring-sky-200",
    icon: "text-sky-500",
  },
  blocked: {
    label: "Blocked",
    badge: "bg-amber-50 text-amber-800 ring-amber-200",
    icon: "text-amber-500",
  },
};

export function formatMinutesRemaining(minutes: number): string {
  if (minutes <= 0) return "All set";
  if (minutes < 60) return `~${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  return rem > 0 ? `~${hours}h ${rem}m` : `~${hours}h`;
}

export function countCompletedSteps(steps: OnboardingStepReadiness[]): number {
  return steps.filter((s) => s.status === "completed").length;
}

export function readinessHeadline(
  platformReady: boolean,
  overallPercent: number,
  nextStep: OnboardingStepReadiness | null,
): string {
  if (overallPercent >= 100) return "Your factory workspace is fully operational";
  if (!platformReady) return "Let's get your platform ready for export growth";
  if (nextStep) return `Next up: ${nextStep.label}`;
  return "You're on track — keep building momentum";
}
