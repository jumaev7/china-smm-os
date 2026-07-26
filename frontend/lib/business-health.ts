/** Pure helpers for Business Health Score v2 presentation. */

export type BusinessHealthBand =
  | "excellent"
  | "healthy"
  | "needs_attention"
  | "at_risk"
  | "critical";

const BAND_LABELS: Record<BusinessHealthBand, string> = {
  excellent: "Excellent",
  healthy: "Healthy",
  needs_attention: "Needs attention",
  at_risk: "At risk",
  critical: "Critical",
};

export function businessHealthBandFromScore(score: number): BusinessHealthBand {
  if (score >= 85) return "excellent";
  if (score >= 70) return "healthy";
  if (score >= 50) return "needs_attention";
  if (score >= 30) return "at_risk";
  return "critical";
}

export function businessHealthBandLabel(statusOrScore: string | number): string {
  if (typeof statusOrScore === "number") {
    return BAND_LABELS[businessHealthBandFromScore(statusOrScore)];
  }
  const key = statusOrScore as BusinessHealthBand;
  return BAND_LABELS[key] ?? statusOrScore.replace(/_/g, " ");
}

/** Safe in-app destinations for domain drill-down (existing routes only). */
export function domainDrilldownHref(domain: string): string | null {
  switch (domain) {
    case "sales":
      return "/crm";
    case "publishing":
      return "/publishing";
    case "campaign_planning":
      return "/campaign-planner";
    case "organic_measurement":
      return "/analytics";
    case "advertising":
      return "/advertising";
    case "integration":
      return "/integrations";
    case "automation":
      return "/automation";
    case "customer_success":
      return "/customer-success";
    case "revenue_billing":
      return "/billing";
    default:
      return null;
  }
}
