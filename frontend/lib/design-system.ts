/**
 * China SMM OS — Premium Enterprise Design System (UI/UX v1)
 * Visual tokens and registry only — no API or business logic.
 */

export const DESIGN_SYSTEM_VERSION = "1.0.0";

export const designTokens = {
  colors: {
    navy: {
      50: "#f4f6fb",
      100: "#e8ecf6",
      200: "#c5d0e8",
      400: "#5a6f9e",
      600: "#1a2b4a",
      800: "#0f1a2e",
      900: "#0a1220",
    },
    brand: {
      50: "#eef4ff",
      100: "#d9e6ff",
      200: "#b3ccff",
      400: "#4d7cff",
      500: "#2563eb",
      600: "#1d4ed8",
      700: "#1e40af",
      800: "#1e3a8a",
      900: "#172554",
    },
    accent: {
      gold: "#c9a227",
      goldLight: "#f5e6b8",
      cyan: "#06b6d4",
      cyanLight: "#cffafe",
    },
    surface: {
      page: "#f8fafc",
      card: "#ffffff",
      elevated: "#ffffff",
      sidebar: "#0f1a2e",
      sidebarHover: "#1a2b4a",
      darkPage: "#0b0f1a",
      darkCard: "#141b2d",
      darkElevated: "#1a2236",
    },
    semantic: {
      success: { bg: "#ecfdf5", border: "#a7f3d0", text: "#047857" },
      warning: { bg: "#fffbeb", border: "#fde68a", text: "#b45309" },
      danger: { bg: "#fef2f2", border: "#fecaca", text: "#b91c1c" },
      info: { bg: "#eff6ff", border: "#bfdbfe", text: "#1d4ed8" },
    },
  },
  spacing: {
    page: "1.5rem",
    section: "1.5rem",
    card: "1.25rem",
    stack: "0.75rem",
    inline: "0.5rem",
  },
  typography: {
    pageTitle: "text-2xl font-semibold tracking-tight text-navy-900",
    sectionTitle: "text-sm font-semibold text-navy-800",
    kpiValue: "text-2xl font-semibold tabular-nums text-navy-900",
    kpiLabel: "text-[10px] uppercase tracking-wider font-medium text-gray-500",
    body: "text-sm text-gray-600",
    caption: "text-xs text-gray-500",
  },
  radius: {
    sm: "0.375rem",
    md: "0.5rem",
    lg: "0.75rem",
    xl: "1rem",
    full: "9999px",
  },
  shadow: {
    card: "0 1px 3px 0 rgb(15 26 46 / 0.06), 0 1px 2px -1px rgb(15 26 46 / 0.04)",
    cardHover: "0 4px 12px -2px rgb(15 26 46 / 0.08), 0 2px 6px -2px rgb(15 26 46 / 0.04)",
    elevated: "0 8px 24px -4px rgb(15 26 46 / 0.12)",
    sidebar: "2px 0 12px -2px rgb(15 26 46 / 0.08)",
  },
} as const;

/** Pages upgraded in UI/UX Premium v1 */
export const UPGRADED_PAGES = [
  { route: "/dashboard", name: "Dashboard", tier: "priority" },
  { route: "/content", name: "Content Studio", tier: "priority" },
  { route: "/pipeline", name: "Pipeline", tier: "priority" },
  { route: "/executive-copilot", name: "Executive Copilot", tier: "priority" },
  { route: "/factory-platform", name: "Factory Platform", tier: "priority" },
  { route: "/customer-portal-v2", name: "Customer Portal v2", tier: "priority" },
  { route: "/buyer-acquisition", name: "Buyer Acquisition", tier: "priority" },
  { route: "/buyer-acquisition-engine", name: "Buyer Acquisition Engine", tier: "priority" },
  { route: "/revenue-engine", name: "Revenue Engine", tier: "priority" },
  { route: "/marketplace", name: "Marketplace", tier: "priority" },
  { route: "/pilot-demo", name: "Pilot Demo", tier: "priority" },
  { route: "/pilot-sales-demo", name: "Pilot Sales Demo", tier: "priority" },
  { route: "/pilot-launch-validation", name: "Pilot Launch Validation", tier: "priority" },
  { route: "/first-pilot-client", name: "First Pilot Client", tier: "priority" },
  { route: "/real-factory-pilot", name: "Real Factory Pilot", tier: "priority" },
] as const;

export const DESIGN_SYSTEM_REGISTRY = {
  id: "premium-enterprise-v1",
  version: DESIGN_SYSTEM_VERSION,
  theme: {
    primary: ["Dark Navy", "White", "Premium Blue"],
    accent: ["Gold", "Electric Cyan"],
  },
  tokens: designTokens,
  components: [
    "KpiCard",
    "ExecutiveKpiBar",
    "ScoreCard",
    "HealthIndicator",
    "StatusBadge",
    "PageHeader",
    "PageSection",
    "DataTable",
    "EmptyState",
    "LoadingState",
    "Skeleton",
  ],
  upgradedPages: UPGRADED_PAGES,
} as const;

export type StatusVariant = "success" | "warning" | "danger" | "info" | "neutral";

export const STATUS_VARIANT_CLASSES: Record<StatusVariant, string> = {
  success: "bg-success-50 text-success-800 border-success-200",
  warning: "bg-warning-50 text-warning-800 border-warning-200",
  danger: "bg-danger-50 text-danger-800 border-danger-200",
  info: "bg-info-50 text-info-800 border-info-200",
  neutral: "bg-gray-50 text-gray-700 border-gray-200",
};

export function healthScoreVariant(score: number): StatusVariant {
  if (score >= 75) return "success";
  if (score >= 50) return "warning";
  return "danger";
}
