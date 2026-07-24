import { format, parseISO } from "date-fns";
import type { StatusVariant } from "@/lib/design-system";

/**
 * Display helpers for the Advertising Intelligence surface.
 *
 * Money is always received as integer MINOR units plus an explicit currency;
 * values from different currencies must never be summed. These helpers format a
 * single-currency amount for display and never convert between currencies.
 */

export const ADVERTISING_STATUS_OPTIONS: Array<{ label: string; value: string }> = [
  { label: "All statuses", value: "" },
  { label: "Active", value: "active" },
  { label: "Paused", value: "paused" },
  { label: "Archived", value: "archived" },
  { label: "Deleted", value: "deleted" },
];

export const ADVERTISING_LINKED_OPTIONS: Array<{ label: string; value: string }> = [
  { label: "All campaigns", value: "" },
  { label: "Linked", value: "true" },
  { label: "Unlinked", value: "false" },
];

export const ADVERTISING_FATIGUE_OPTIONS: Array<{ label: string; value: string }> = [
  { label: "All creatives", value: "" },
  { label: "Healthy", value: "healthy" },
  { label: "Watch", value: "watch" },
  { label: "Fatigued", value: "fatigued" },
];

function currencyFractionDigits(currency: string): number {
  try {
    const fmt = new Intl.NumberFormat(undefined, { style: "currency", currency });
    return fmt.resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    return 2;
  }
}

/** Format integer minor units + currency as a localized money string. */
export function formatMoneyMinor(
  minor: number | null | undefined,
  currency?: string | null,
): string {
  if (minor == null || Number.isNaN(minor)) return "—";
  if (!currency) {
    // No currency context — show raw minor units explicitly, never guess a symbol.
    return `${formatNumber(minor)} (minor units)`;
  }
  const cur = currency.toUpperCase();
  const digits = currencyFractionDigits(cur);
  const major = minor / 10 ** digits;
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: cur }).format(major);
  } catch {
    return `${major.toFixed(digits)} ${cur}`;
  }
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 10_000) {
    return new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 1,
      notation: "compact",
    }).format(value);
  }
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

export function formatRatioPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatFrequency(value: number | string | null | undefined): string {
  if (value == null) return "—";
  const num = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(num)) return "—";
  return `${num.toFixed(2)}×`;
}

export function formatWhen(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "MMM d, yyyy HH:mm");
  } catch {
    return iso;
  }
}

export function formatShortDate(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "MMM d, yyyy");
  } catch {
    return iso;
  }
}

export function titleCaseKey(key?: string | null): string {
  if (!key) return "—";
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Local connection status of the tenant's link to the provider account. */
export function connectionVariant(status?: string | null): StatusVariant {
  switch (status) {
    case "connected":
      return "success";
    case "expired":
    case "permission_blocked":
      return "warning";
    case "disconnected":
    case "revoked":
    case "error":
      return "danger";
    default:
      return "neutral";
  }
}

/** Provider-reported delivery status of a campaign / ad group / ad. */
export function entityStatusVariant(status?: string | null): StatusVariant {
  switch (status) {
    case "active":
      return "success";
    case "paused":
    case "campaign_paused":
    case "adset_paused":
    case "pending_review":
    case "in_process":
    case "pending_billing_info":
      return "info";
    case "with_issues":
      return "warning";
    case "disapproved":
      return "danger";
    case "completed":
    case "archived":
    case "deleted":
    default:
      return "neutral";
  }
}

export function pacingLabel(status?: string | null): string {
  switch (status) {
    case "on_pace":
    case "on_track":
      return "On pace";
    case "underspending":
    case "under_pacing":
      return "Underspending";
    case "overspending":
    case "over_pacing":
      return "Overspending";
    case "budget_exhausted":
    case "exhausted":
      return "Budget exhausted";
    case "paused":
      return "Paused";
    case "ended":
      return "Ended";
    case "insufficient_data":
      return "Insufficient data";
    case "not_applicable":
      return "Not applicable";
    default:
      return "Unknown";
  }
}

export function pacingVariant(status?: string | null): StatusVariant {
  switch (status) {
    case "on_pace":
    case "on_track":
      return "success";
    case "underspending":
    case "under_pacing":
      return "info";
    case "overspending":
    case "over_pacing":
      return "warning";
    case "budget_exhausted":
    case "exhausted":
      return "danger";
    case "paused":
    case "ended":
      return "neutral";
    default:
      return "neutral";
  }
}

export function fatigueLabel(status?: string | null): string {
  switch (status) {
    case "no_signal":
    case "healthy":
      return "No fatigue signal";
    case "possible_fatigue":
    case "watch":
      return "Possible fatigue signal";
    case "strong_fatigue_signal":
    case "fatigued":
      return "Strong fatigue signal";
    case "insufficient_data":
      return "Insufficient data";
    default:
      return "Unknown";
  }
}

export function fatigueVariant(status?: string | null): StatusVariant {
  switch (status) {
    case "no_signal":
    case "healthy":
      return "success";
    case "possible_fatigue":
    case "watch":
      return "warning";
    case "strong_fatigue_signal":
    case "fatigued":
      return "danger";
    default:
      return "neutral";
  }
}

export function deliveryVariant(status?: string | null): StatusVariant {
  switch (status) {
    case "delivering":
      return "success";
    case "limited":
      return "warning";
    case "not_delivering":
      return "danger";
    default:
      return "neutral";
  }
}

export function freshnessVariant(status?: string | null): StatusVariant {
  switch (status) {
    case "fresh":
      return "success";
    case "aging":
      return "info";
    case "stale":
      return "warning";
    case "unsupported":
    case "unavailable":
    default:
      return "neutral";
  }
}

export function severityVariant(severity?: string | null): StatusVariant {
  switch (severity) {
    case "critical":
    case "error":
      return "danger";
    case "warning":
      return "warning";
    case "info":
    default:
      return "info";
  }
}
