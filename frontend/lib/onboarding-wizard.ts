import type { OnboardingDashboard, OnboardingReadinessResponse, NorthStarGoalKey } from "@/lib/api";

export type WizardStepId = "welcome" | "company" | "goal" | "connections" | "publishing" | "complete";

export interface WizardStepDef {
  id: WizardStepId;
  label: string;
  shortLabel: string;
  route: string;
  estimatedMinutes: number;
}

export const ONBOARDING_WIZARD_STEPS: WizardStepDef[] = [
  { id: "welcome", label: "Welcome", shortLabel: "Welcome", route: "/onboarding/welcome", estimatedMinutes: 1 },
  { id: "company", label: "Company", shortLabel: "Company", route: "/onboarding/company", estimatedMinutes: 3 },
  { id: "goal", label: "North Star Goal", shortLabel: "Goal", route: "/onboarding/goal", estimatedMinutes: 2 },
  { id: "connections", label: "Connections", shortLabel: "Connections", route: "/onboarding/channels", estimatedMinutes: 5 },
  { id: "publishing", label: "Publishing", shortLabel: "Publishing", route: "/onboarding/publishing", estimatedMinutes: 3 },
  { id: "complete", label: "Finish", shortLabel: "Finish", route: "/onboarding/complete", estimatedMinutes: 1 },
];


export type { NorthStarGoalKey };

export interface NorthStarGoalCardDef {
  key: NorthStarGoalKey;
  title: string;
  description: string;
  icon: string;
}

export const NORTH_STAR_GOAL_CARDS: NorthStarGoalCardDef[] = [
  {
    key: "export_leads",
    title: "Generate Export Leads",
    description: "Grow inbound inquiries and qualified export opportunities.",
    icon: "🌍",
  },
  {
    key: "better_sales_pipeline",
    title: "Sell More Products",
    description: "Move deals through your pipeline and close more orders.",
    icon: "📦",
  },
  {
    key: "brand_awareness",
    title: "Increase Brand Awareness",
    description: "Build visibility with consistent content across channels.",
    icon: "✨",
  },
  {
    key: "more_buyers",
    title: "Find Buyers",
    description: "Discover, match, and nurture international buyer relationships.",
    icon: "🤝",
  },
  {
    key: "better_publishing",
    title: "Grow Marketplace",
    description: "Publish consistently and expand your marketplace presence.",
    icon: "🚀",
  },
];

export const COMPANY_SIZE_OPTIONS = [
  { label: "1–10 employees", value: "1-10", employeeCount: 10 },
  { label: "11–50 employees", value: "11-50", employeeCount: 50 },
  { label: "51–200 employees", value: "51-200", employeeCount: 200 },
  { label: "201–500 employees", value: "201-500", employeeCount: 500 },
  { label: "500+ employees", value: "500+", employeeCount: 1000 },
] as const;

export const TIMEZONE_OPTIONS = [
  "Asia/Shanghai",
  "Asia/Tashkent",
  "Asia/Almaty",
  "Asia/Dubai",
  "Europe/Moscow",
  "Europe/Istanbul",
  "Europe/London",
  "America/New_York",
  "America/Los_Angeles",
  "UTC",
] as const;

export const POSTING_FREQUENCY_OPTIONS = [
  { label: "Daily", value: "daily" },
  { label: "3× per week", value: "3x_week" },
  { label: "Weekly", value: "weekly" },
  { label: "Bi-weekly", value: "biweekly" },
  { label: "Monthly", value: "monthly" },
] as const;

export const APPROVAL_MODE_OPTIONS = [
  {
    label: "Auto-publish approved content",
    value: "auto" as const,
    description: "Content flows to channels after internal approval.",
  },
  {
    label: "Manual review before publish",
    value: "manual" as const,
    description: "Every post requires explicit approval before going live.",
  },
] as const;

export const LANGUAGE_OPTIONS = ["English", "Russian", "Chinese", "Uzbek", "Korean", "Japanese"] as const;

export interface WizardStepStatus {
  id: WizardStepId;
  label: string;
  shortLabel: string;
  route: string;
  completed: boolean;
  current: boolean;
}

export interface WizardProgressState {
  currentStep: number;
  totalSteps: number;
  percent: number;
  steps: WizardStepStatus[];
  estimatedMinutesRemaining: number;
}

export function employeeCountToSize(count: number | null | undefined): string {
  if (count == null) return "";
  if (count <= 10) return "1-10";
  if (count <= 50) return "11-50";
  if (count <= 200) return "51-200";
  if (count <= 500) return "201-500";
  return "500+";
}

export function sizeToEmployeeCount(size: string): number | undefined {
  const match = COMPANY_SIZE_OPTIONS.find((o) => o.value === size);
  return match?.employeeCount;
}

export function publishingPrefsStorageKey(tenantId: string): string {
  return `onboarding-publishing-prefs:${tenantId}`;
}

export interface PublishingPrefsLocal {
  timezone: string;
  posting_frequency: string;
  prefs_saved_at?: string;
}

export function readPublishingPrefs(tenantId: string): PublishingPrefsLocal | null {
  if (typeof window === "undefined" || !tenantId) return null;
  try {
    const raw = localStorage.getItem(publishingPrefsStorageKey(tenantId));
    return raw ? (JSON.parse(raw) as PublishingPrefsLocal) : null;
  } catch {
    return null;
  }
}

export function writePublishingPrefs(tenantId: string, prefs: PublishingPrefsLocal): void {
  if (typeof window === "undefined" || !tenantId) return;
  localStorage.setItem(publishingPrefsStorageKey(tenantId), JSON.stringify(prefs));
}

export function computeWizardProgress(
  readiness: OnboardingReadinessResponse | undefined,
  dashboard: OnboardingDashboard | undefined,
  currentPath: string,
  publishingPrefsSaved: boolean,
): WizardProgressState {
  const companyDone =
    readiness?.platform_steps.find((s) => s.id === "company_info")?.status === "completed";
  const goalDone = !!readiness?.north_star_goal;
  const connectionsDone = hasAnyConnection(readiness);
  const publishingDone =
    publishingPrefsSaved ||
    readiness?.platform_steps.find((s) => s.id === "publishing_readiness")?.status === "completed";
  const welcomeDone = dashboard?.status !== "not_started";
  const completeDone = !!readiness?.platform_ready || dashboard?.status === "completed";

  const completionMap: Record<WizardStepId, boolean> = {
    welcome: welcomeDone,
    company: companyDone,
    goal: goalDone,
    connections: connectionsDone,
    publishing: publishingDone,
    complete: completeDone,
  };

  const steps: WizardStepStatus[] = ONBOARDING_WIZARD_STEPS.map((step) => ({
    id: step.id,
    label: step.label,
    shortLabel: step.shortLabel,
    route: step.route,
    completed: completionMap[step.id],
    current: currentPath === step.route || currentPath.startsWith(`${step.route}/`),
  }));

  const completedCount = steps.filter((s) => s.completed).length;
  const currentIndex = Math.max(
    0,
    steps.findIndex((s) => s.current) !== -1
      ? steps.findIndex((s) => s.current)
      : steps.findIndex((s) => !s.completed),
  );

  const remainingMinutes = ONBOARDING_WIZARD_STEPS.filter((s) => !completionMap[s.id]).reduce(
    (sum, s) => sum + s.estimatedMinutes,
    0,
  );

  return {
    currentStep: currentIndex + 1,
    totalSteps: ONBOARDING_WIZARD_STEPS.length,
    percent: Math.round((completedCount / ONBOARDING_WIZARD_STEPS.length) * 100),
    steps,
    estimatedMinutesRemaining:
      readiness?.estimated_minutes_remaining ?? dashboard?.estimated_minutes_remaining ?? remainingMinutes,
  };
}

function hasAnyConnection(readiness: OnboardingReadinessResponse | undefined): boolean {
  if (!readiness) return false;
  const connectionIds = [
    "telegram_connected",
    "facebook_connected",
    "instagram_connected",
  ];
  return connectionIds.some(
    (id) => readiness.platform_steps.find((s) => s.id === id)?.status === "completed",
  );
}

export function wizardNextRoute(currentId: WizardStepId): string | undefined {
  const idx = ONBOARDING_WIZARD_STEPS.findIndex((s) => s.id === currentId);
  if (idx < 0 || idx >= ONBOARDING_WIZARD_STEPS.length - 1) return undefined;
  return ONBOARDING_WIZARD_STEPS[idx + 1].route;
}

export function wizardPrevRoute(currentId: WizardStepId): string | undefined {
  const idx = ONBOARDING_WIZARD_STEPS.findIndex((s) => s.id === currentId);
  if (idx <= 0) return undefined;
  return ONBOARDING_WIZARD_STEPS[idx - 1].route;
}
