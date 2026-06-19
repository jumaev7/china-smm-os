import { api } from "./api";

export type DemoFactoryPackageId = "haocheng" | "toy_manufacturer" | "textile_factory";

export interface DemoFactoryPackageSummary {
  id: DemoFactoryPackageId;
  company_name: string;
  industry: string;
  country: string;
  description: string;
  highlights: string[];
}

export interface DemoTourStep {
  order: number;
  id: string;
  title: string;
  description: string;
  route: string;
  minutes: number;
  talking_points: string[];
  business_value: string;
}

export interface ExportGrowthStoryStep {
  order: number;
  id: string;
  title: string;
  description: string;
  route: string;
  status: "complete" | "active" | "pending";
  metric_label?: string | null;
  metric_value?: string | null;
}

export interface ValueDemoAction {
  id: string;
  title: string;
  description: string;
  route: string;
  priority: "high" | "medium" | "low";
}

export interface ValueDemoResponse {
  buyers_found: number;
  opportunities_generated: number;
  pipeline_value_usd: number;
  estimated_revenue_influenced_usd: number;
  active_deals: number;
  proposals_sent: number;
  communications_active: number;
  content_pieces: number;
  ai_recommendations: number;
  actions_today: ValueDemoAction[];
  demo_data_loaded: boolean;
  company_name?: string | null;
}

export interface ExecutiveDemoKpi {
  label: string;
  value: string;
  change?: string | null;
  trend: "up" | "down" | "neutral";
}

export interface ExecutiveDemoSection {
  id: string;
  title: string;
  summary: string;
  route: string;
  highlights: string[];
}

export interface ExecutiveDemoResponse {
  company_name: string;
  industry?: string | null;
  country?: string | null;
  headline: string;
  kpis: ExecutiveDemoKpi[];
  sections: ExecutiveDemoSection[];
  ai_recommendations: string[];
  roi_score: number;
  generated_at: string;
}

export interface PositioningComparison {
  category: string;
  traditional: string;
  this_platform: string;
}

export interface ProductPositioningResponse {
  mission: string;
  tagline: string;
  differentiators: string[];
  comparisons: PositioningComparison[];
  key_capabilities: string[];
}

export interface ReadinessComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  status: "ready" | "partial" | "missing";
  notes?: string | null;
}

export interface DemoReadinessResponse {
  score: number;
  grade: "A" | "B" | "C" | "D" | "F";
  components: ReadinessComponent[];
  strengths: string[];
  gaps: string[];
  recommended_next_steps: string[];
}

export const commercialDemoApi = {
  listPackages: () =>
    api.get<{ packages: DemoFactoryPackageSummary[] }>("/commercial-demo/packages"),

  loadPackage: (packageId: DemoFactoryPackageId) =>
    api.post<{
      loaded: boolean;
      package_id: DemoFactoryPackageId;
      company_name: string;
      message: string;
      counts: Record<string, number>;
    }>(`/commercial-demo/packages/${packageId}/load`),

  getTour: () =>
    api.get<{ title: string; estimated_minutes: number; steps: DemoTourStep[] }>(
      "/commercial-demo/tour",
    ),

  getExportGrowthStory: () =>
    api.get<{
      title: string;
      subtitle: string;
      steps: ExportGrowthStoryStep[];
      total_pipeline_usd: number;
      roi_improvement_pct: number;
    }>("/commercial-demo/export-growth-story"),

  getValueDemo: () => api.get<ValueDemoResponse>("/commercial-demo/value-demo"),

  getExecutiveDemo: () => api.get<ExecutiveDemoResponse>("/commercial-demo/executive-demo"),

  getPositioning: () => api.get<ProductPositioningResponse>("/commercial-demo/positioning"),

  getReadiness: () => api.get<DemoReadinessResponse>("/commercial-demo/readiness"),
};

export const DEMO_MODE_STORAGE_KEY = "china_smm_demo_mode";
export const DEMO_PACKAGE_STORAGE_KEY = "china_smm_demo_package";
