import toast from "react-hot-toast";
import type { StatusVariant } from "@/lib/design-system";
import { getApiErrorMessage, getCampaignPlannerError } from "@/lib/api";

/** Human-readable messages for the stable Campaign Planner error codes. */
const CAMPAIGN_ERROR_MESSAGES: Record<string, string> = {
  campaign_not_found: "Campaign not found.",
  campaign_child_not_found: "That item no longer exists.",
  plan_version_not_found: "Plan version not found.",
  slot_not_found: "Slot not found.",
  pillar_not_found: "Content pillar not found.",
  content_not_found: "Content not found.",
  review_not_found: "No review is available yet.",
  ai_request_not_found: "AI proposal not found.",
  campaign_invalid_state: "This campaign can no longer be modified in its current state.",
  plan_version_immutable: "This plan version is published and read-only.",
  concurrency_conflict: "This campaign was changed elsewhere. Reload and try again.",
  plan_configuration_invalid: "The plan configuration is incomplete (check platforms and dates).",
  validation_error: "Some fields are invalid. Please review and try again.",
  limit_exceeded: "A configured limit was exceeded.",
  assignment_blocked: "Assignment is blocked by readiness checks.",
  duplicate_resource: "This item already exists.",
  // Governed AI platform codes
  AI_DISABLED: "AI is disabled for this workspace.",
  AI_POLICY_BLOCKED: "AI is disabled for this workspace.",
  AI_QUOTA_EXCEEDED: "AI usage limit reached. Try again later.",
  AI_PROVIDER_UNAVAILABLE: "The AI provider is temporarily unavailable.",
  AI_OUTPUT_INVALID: "The AI proposal could not be validated. Please retry.",
};

export function campaignErrorMessage(err: unknown, fallback = "Something went wrong"): string {
  const { code, message } = getCampaignPlannerError(err);
  if (code && CAMPAIGN_ERROR_MESSAGES[code]) return CAMPAIGN_ERROR_MESSAGES[code];
  if (message) return message;
  const generic = getApiErrorMessage(err);
  return generic || fallback;
}

export function toastCampaignError(err: unknown, fallback = "Something went wrong"): void {
  toast.error(campaignErrorMessage(err, fallback));
}

export function campaignStatusVariant(status: string): StatusVariant {
  switch (status) {
    case "active":
    case "approved":
      return "success";
    case "planning":
    case "draft":
      return "info";
    case "paused":
      return "warning";
    case "completed":
      return "neutral";
    case "archived":
      return "neutral";
    default:
      return "neutral";
  }
}

export function planStatusVariant(status: string): StatusVariant {
  switch (status) {
    case "published":
      return "success";
    case "reviewed":
      return "info";
    case "draft":
      return "warning";
    case "superseded":
    case "archived":
      return "neutral";
    default:
      return "neutral";
  }
}

export function slotStatusVariant(status: string): StatusVariant {
  switch (status) {
    case "ready":
      return "success";
    case "assigned":
      return "info";
    case "ready_with_warnings":
      return "warning";
    case "blocked":
      return "danger";
    case "unassigned":
    case "skipped":
      return "neutral";
    default:
      return "neutral";
  }
}

export function readinessVariant(status: string): StatusVariant {
  switch (status) {
    case "ready":
      return "success";
    case "ready_with_warnings":
      return "warning";
    case "blocked":
      return "danger";
    default:
      return "neutral";
  }
}

export function isPlanReadOnly(status?: string | null): boolean {
  return status === "published" || status === "superseded" || status === "archived";
}

export function titleCase(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value.length <= 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function generationMethodLabel(method?: string | null): string | null {
  if (!method) return null;
  switch (method) {
    case "ai_assisted":
    case "ai_variant":
      return "AI-assisted";
    case "deterministic":
    case "deterministic_variant":
      return "Deterministic";
    case "content":
    case "source":
      return "Source content";
    default:
      return titleCase(method);
  }
}
