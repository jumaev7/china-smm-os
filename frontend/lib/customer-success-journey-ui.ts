import type { LucideIcon } from "lucide-react";
import {
  Award,
  Briefcase,
  FileText,
  LayoutDashboard,
  Package,
  Send,
  ShoppingBag,
  Store,
  Target,
  Users,
} from "lucide-react";
import type {
  CustomerSuccessJourneyDashboard,
  JourneyFeatureAdoption,
  JourneyRecommendation,
  JourneyRecommendationPriority,
  OnboardingReadinessResponse,
} from "@/lib/api";
import { healthScoreVariant } from "@/lib/design-system";
import type { StatusVariant } from "@/lib/design-system";

export type FeatureAdoptionCard = {
  key: string;
  label: string;
  icon: LucideIcon;
  href: string;
  usagePercent: number;
  status: "active" | "partial" | "inactive";
  statusLabel: string;
  lastActivity: string;
  adopted: boolean;
};

export type CustomerMilestone = {
  id: string;
  label: string;
  completed: boolean;
  future: boolean;
  completedAt?: string | null;
  href?: string;
};

export type JourneyAchievement = {
  id: string;
  label: string;
  description: string;
  earned: boolean;
  icon: LucideIcon;
  tone: "gold" | "emerald" | "violet" | "sky" | "amber";
};

const FEATURE_CARD_DEFS: Array<{
  key: string;
  label: string;
  icon: LucideIcon;
  href: string;
  featureKeys: string[];
}> = [
  { key: "publishing", label: "Publishing", icon: Send, href: "/publishing", featureKeys: ["publishing", "meta_connected"] },
  { key: "crm", label: "CRM", icon: Briefcase, href: "/crm-pipeline", featureKeys: ["crm_leads", "crm_deals", "communication"] },
  { key: "marketplace", label: "Marketplace", icon: Store, href: "/marketplace", featureKeys: ["growth_center"] },
  { key: "buyer_finder", label: "Buyer Finder", icon: Users, href: "/buyers", featureKeys: ["buyers", "export_leads"] },
  { key: "products", label: "Products", icon: Package, href: "/content", featureKeys: ["content"] },
  { key: "executive_dashboard", label: "Executive Dashboard", icon: LayoutDashboard, href: "/dashboard", featureKeys: ["executive_dashboard"] },
];

const PRIORITY_IMPACT: Record<JourneyRecommendationPriority, string> = {
  urgent: "+15–20 health pts",
  high: "+10–15 adoption pts",
  medium: "+5–10 momentum pts",
  low: "+2–5 engagement pts",
};

export function healthTone(score: number): StatusVariant {
  return healthScoreVariant(score);
}

export function healthStrokeColor(score: number): string {
  const variant = healthTone(score);
  if (variant === "success") return "#10b981";
  if (variant === "warning") return "#f59e0b";
  return "#ef4444";
}

export function healthTrackColor(score: number): string {
  const variant = healthTone(score);
  if (variant === "success") return "rgba(16, 185, 129, 0.15)";
  if (variant === "warning") return "rgba(245, 158, 11, 0.15)";
  return "rgba(239, 68, 68, 0.15)";
}

export function computeHealthTrend(healthScore: number, journeyDay: number): { delta: number; label: string } {
  const expected = Math.round((Math.min(journeyDay, 30) / 30) * 65);
  const delta = healthScore - expected;
  if (delta > 5) return { delta, label: `+${delta} vs expected pace` };
  if (delta < -5) return { delta, label: `${delta} vs expected pace` };
  return { delta: 0, label: "On track with journey pace" };
}

export function computeNorthStarProgress(journey: CustomerSuccessJourneyDashboard): number {
  const checkpointPct = journey.success_score.checkpoint_completion_pct;
  const outcomePct = journey.success_score.outcome_signals_pct;
  if (!journey.north_star_goal) return Math.round((checkpointPct + outcomePct) / 2);
  const goalBoost: Record<string, number> = {
    export_leads: journey.features.find((f) => f.key === "export_leads")?.score ?? 0,
    better_publishing: Math.max(
      journey.features.find((f) => f.key === "publishing")?.score ?? 0,
      journey.features.find((f) => f.key === "meta_connected")?.score ?? 0,
    ),
    more_buyers: journey.features.find((f) => f.key === "buyers")?.score ?? 0,
    better_sales_pipeline: Math.max(
      journey.features.find((f) => f.key === "crm_deals")?.score ?? 0,
      journey.features.find((f) => f.key === "proposals")?.score ?? 0,
    ),
    brand_awareness: Math.max(
      journey.features.find((f) => f.key === "content")?.score ?? 0,
      journey.features.find((f) => f.key === "publishing")?.score ?? 0,
    ),
  };
  const goalScore = goalBoost[journey.north_star_goal] ?? checkpointPct;
  return Math.round(goalScore * 0.6 + checkpointPct * 0.4);
}

export function buildFeatureAdoptionCards(features: JourneyFeatureAdoption[]): FeatureAdoptionCard[] {
  const byKey = new Map(features.map((f) => [f.key, f]));

  return FEATURE_CARD_DEFS.map((def) => {
    const matched = def.featureKeys.map((k) => byKey.get(k)).filter(Boolean) as JourneyFeatureAdoption[];
    const usagePercent = matched.length
      ? Math.round(matched.reduce((sum, f) => sum + f.score, 0) / matched.length)
      : 0;
    const adopted = matched.some((f) => f.adopted);
    const partial = !adopted && usagePercent >= 35;
    const status: FeatureAdoptionCard["status"] = adopted ? "active" : partial ? "partial" : "inactive";
    const statusLabel = adopted ? "Active" : partial ? "In progress" : "Not started";
    const lastUsed = matched
      .map((f) => f.first_used_at)
      .filter(Boolean)
      .sort()
      .pop();

    return {
      key: def.key,
      label: def.label,
      icon: def.icon,
      href: def.href,
      usagePercent,
      status,
      statusLabel,
      lastActivity: lastUsed ? formatRelativeDate(lastUsed) : adopted ? "Recently" : "No activity yet",
      adopted,
    };
  });
}

export function buildCustomerMilestones(
  journey: CustomerSuccessJourneyDashboard,
  readiness?: OnboardingReadinessResponse | null,
): CustomerMilestone[] {
  const step = (id: string) =>
    readiness?.platform_steps.find((s) => s.id === id)
    ?? readiness?.business_steps.find((s) => s.id === id)
    ?? readiness?.first_success?.milestones.find((s) => s.id === id);

  const feat = (key: string) => journey.features.find((f) => f.key === key);
  const platformReady = journey.platform_ready;
  const onboardingComplete = readiness ? readiness.overall_percent >= 100 || platformReady : platformReady;

  const defs: Array<{ id: string; label: string; href?: string; done: boolean; needsPlatform?: boolean }> = [
    { id: "company_created", label: "Company created", href: "/onboarding/company", done: Boolean(step("company_info")?.status === "completed") },
    { id: "onboarding_completed", label: "Onboarding completed", href: "/onboarding", done: onboardingComplete },
    { id: "platform_ready", label: "Platform ready", href: "/onboarding/complete", done: platformReady },
    { id: "first_content", label: "First content", href: "/content", done: Boolean(feat("content")?.adopted || step("first_ai_content")?.status === "completed") },
    { id: "first_publish", label: "First publish", href: "/publishing", done: Boolean(feat("publishing")?.adopted || step("first_published_content")?.status === "completed") },
    { id: "first_lead", label: "First lead", href: "/crm-pipeline", done: Boolean(feat("crm_leads")?.adopted || step("first_lead")?.status === "completed") },
    { id: "first_buyer", label: "First buyer", href: "/buyers", done: Boolean(feat("buyers")?.adopted || step("first_buyer")?.status === "completed") },
    { id: "first_proposal", label: "First proposal", href: "/proposals", done: Boolean(feat("proposals")?.adopted || step("first_proposal")?.status === "completed") },
    { id: "first_contract", label: "First contract", href: "/deals", done: Boolean(feat("crm_deals")?.adopted && (feat("proposals")?.adopted ?? false)) },
  ];

  let foundCurrent = false;
  return defs.map((d) => {
    const completed = d.done;
    const future = !completed && foundCurrent;
    if (!completed && !foundCurrent) foundCurrent = true;
    const matched = step(
      d.id === "first_content" ? "first_ai_content"
        : d.id === "first_publish" ? "first_published_content"
          : d.id === "first_lead" ? "first_lead"
            : d.id === "first_buyer" ? "first_buyer"
              : d.id === "first_proposal" ? "first_proposal"
                : d.id === "company_created" ? "company_info"
                  : "",
    );
    return {
      id: d.id,
      label: d.label,
      completed,
      future: !completed && future,
      completedAt: matched?.completed_at,
      href: d.href,
    };
  });
}

export function buildAchievements(journey: CustomerSuccessJourneyDashboard): JourneyAchievement[] {
  const feat = (key: string) => journey.features.find((f) => f.key === key);
  const publishingScore = feat("publishing")?.score ?? 0;
  const leadsScore = feat("export_leads")?.score ?? feat("crm_leads")?.score ?? 0;

  return [
    {
      id: "first_publish",
      label: "First Publish",
      description: "Content live on a connected channel",
      earned: Boolean(feat("publishing")?.adopted),
      icon: Send,
      tone: "emerald",
    },
    {
      id: "ten_posts",
      label: "10 Posts",
      description: "Consistent publishing momentum",
      earned: publishingScore >= 70 || (feat("content")?.score ?? 0) >= 80,
      icon: FileText,
      tone: "sky",
    },
    {
      id: "hundred_leads",
      label: "100 Leads",
      description: "Scaled export lead generation",
      earned: leadsScore >= 85,
      icon: Target,
      tone: "violet",
    },
    {
      id: "marketplace_connected",
      label: "Marketplace Connected",
      description: "Growth Center actively used",
      earned: Boolean(feat("growth_center")?.adopted),
      icon: ShoppingBag,
      tone: "gold",
    },
    {
      id: "crm_complete",
      label: "CRM Complete",
      description: "Leads, deals, and communication active",
      earned: Boolean(feat("crm_leads")?.adopted && feat("crm_deals")?.adopted),
      icon: Briefcase,
      tone: "amber",
    },
    {
      id: "journey_complete",
      label: "30-Day Champion",
      description: "Completed the customer success journey",
      earned: journey.status === "completed",
      icon: Award,
      tone: "gold",
    },
  ];
}

export function recommendationImpact(rec: JourneyRecommendation): string {
  return PRIORITY_IMPACT[rec.priority];
}

export function publishingActivityLabel(journey: CustomerSuccessJourneyDashboard): string {
  const publishing = journey.features.find((f) => f.key === "publishing");
  if (publishing?.adopted) return "Active";
  if ((publishing?.score ?? 0) >= 40) return "Warming up";
  return "Inactive";
}

function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
