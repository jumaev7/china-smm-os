import { cn } from "@/lib/utils";

/** Semantic tones for inner dashboard KPI/stat cells (light + tenant dark). */
export type DashboardMetricTone =
  | "neutral"
  | "slate"
  | "brand"
  | "info"
  | "sky"
  | "indigo"
  | "violet"
  | "success"
  | "teal"
  | "cyan"
  | "warning"
  | "orange"
  | "danger"
  | "fuchsia";

export function dashboardMetricTileClass(
  tone: DashboardMetricTone,
  opts?: { link?: boolean; compact?: boolean; hero?: boolean },
) {
  return cn(
    "dashboard-metric-tile",
    `dashboard-metric-tile--${tone}`,
    opts?.link && "dashboard-metric-tile--link",
    opts?.compact && "dashboard-metric-tile--compact",
    opts?.hero && "dashboard-metric-tile--hero",
  );
}

export function dashboardMetricValueClass(
  tone: DashboardMetricTone,
  size: "lg" | "xl" | "sm" | "body" = "lg",
) {
  return cn("dashboard-metric-value", `dashboard-metric-value--${size}`, `dashboard-metric-value--${tone}`);
}

export function dashboardMetricLabelClass(tone: DashboardMetricTone | "muted") {
  return cn("dashboard-metric-label", `dashboard-metric-label--${tone}`);
}
