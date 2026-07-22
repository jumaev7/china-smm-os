import { format, parseISO } from "date-fns";
import type { StatusVariant } from "@/lib/design-system";
import type { MeasurementPeriodDays } from "@/lib/api";

export const MEASUREMENT_PERIOD_OPTIONS: Array<{ label: string; value: string }> = [
  { label: "7 days", value: "7" },
  { label: "30 days", value: "30" },
  { label: "90 days", value: "90" },
];

export const MEASUREMENT_SORT_METRICS: Array<{ label: string; value: string }> = [
  { label: "Published at", value: "published_at" },
  { label: "Impressions", value: "impressions" },
  { label: "Reach", value: "reach" },
  { label: "Views", value: "views" },
  { label: "Likes", value: "likes" },
  { label: "Comments", value: "comments" },
  { label: "Shares", value: "shares" },
  { label: "Engagements", value: "engagements" },
  { label: "Link clicks", value: "link_clicks" },
];

export function parsePeriodDays(value: string): MeasurementPeriodDays {
  if (value === "7") return 7;
  if (value === "90") return 90;
  return 30;
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

export function formatMetricValue(value: number | null | undefined, valueType?: string | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (valueType === "ratio") {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (Math.abs(value) >= 1000) {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1, notation: "compact" }).format(
      value,
    );
  }
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
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
      return "neutral";
    default:
      return "neutral";
  }
}

export function classificationLabel(classification?: string | null): string {
  if (!classification) return "—";
  return classification.replace(/_/g, " ");
}

export function classificationVariant(classification?: string | null): StatusVariant {
  switch (classification) {
    case "above_baseline":
      return "success";
    case "near_baseline":
    case "at_baseline":
      return "info";
    case "below_baseline":
      return "warning";
    case "insufficient_data":
    default:
      return "neutral";
  }
}

export function kpiStatusVariant(status?: string | null): StatusVariant {
  switch (status) {
    case "target_reached":
    case "target_exceeded":
      return "success";
    case "in_progress":
      return "info";
    case "data_stale":
      return "warning";
    case "not_measurable":
    case "no_data":
    default:
      return "neutral";
  }
}

export function titleCaseKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function confidencePct(confidence?: number | null): string {
  if (confidence == null || Number.isNaN(confidence)) return "—";
  const pct = confidence <= 1 ? confidence * 100 : confidence;
  return `${pct.toFixed(0)}%`;
}
