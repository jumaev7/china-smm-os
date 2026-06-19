import axios, { AxiosError } from "axios";
import {
  ADMIN_AUTH_TOKEN_KEY,
  AUTH_TOKEN_KEY,
  clearAdminSessionStorage,
  clearTenantSessionStorage,
  notifyAdminSessionChanged,
  notifyTenantSessionChanged,
  readActiveSession,
} from "@/lib/session-sync";

export function getApiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const path = err.config?.url ?? err.config?.baseURL ?? "unknown endpoint";
    const status = err.response?.status;

    if (err.code === "ECONNABORTED") {
      return `Request timed out (15s) — ${path}`;
    }
    if (status === 504) {
      return `Server timed out — ${path}`;
    }
    if (!err.response) {
      return `Cannot reach API — ${path}. Check that the backend is running.`;
    }

    const detail = err.response?.data?.detail;
    let detailText = "";
    if (typeof detail === "string") detailText = detail;
    else if (Array.isArray(detail)) {
      detailText = detail
        .map((d: { msg?: string }) => (typeof d === "object" && d?.msg ? d.msg : String(d)))
        .join("; ");
    }

    const parts = [`${path}`];
    if (status) parts.push(`HTTP ${status}`);
    if (detailText) parts.push(detailText);
    else if (err.message && err.message !== "Network Error") parts.push(err.message);

    return parts.join(" — ");
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}

export function getApiErrorPath(err: unknown): string | undefined {
  if (axios.isAxiosError(err)) {
    return err.config?.url ?? undefined;
  }
  return undefined;
}

export function getApiErrorStatus(err: unknown): number | undefined {
  if (axios.isAxiosError(err)) {
    return err.response?.status;
  }
  return undefined;
}

/** Normalize API list responses that may be a plain array or paginated object. */
export function normalizeList<T = any>(value: unknown): T[] {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") {
    const v = value as Record<string, unknown>;
    if (Array.isArray(v.items)) return v.items as T[];
    if (Array.isArray(v.clients)) return v.clients as T[];
    if (Array.isArray(v.data)) return v.data as T[];
    if (Array.isArray(v.results)) return v.results as T[];
  }
  return [];
}

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 15000,
});

api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("tenant_auth_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

function attachApiErrorInterceptor(client: typeof api, sessionKind: "tenant" | "admin") {
  client.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      if (error.response?.status === 401 && typeof window !== "undefined") {
        if (sessionKind === "tenant") {
          clearTenantSessionStorage();
          notifyTenantSessionChanged();
        } else {
          clearAdminSessionStorage();
          notifyAdminSessionChanged();
        }
      }
      error.message = getApiErrorMessage(error);
      return Promise.reject(error);
    },
  );
}

attachApiErrorInterceptor(api, "tenant");

export const adminApi = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 15000,
});

adminApi.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("admin_auth_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

attachApiErrorInterceptor(adminApi, "admin");

// ─── Types ────────────────────────────────────────────────────────────────────

export type SourceLanguage = "zh" | "en" | "ru" | "ko" | "ja";
export type ContentStyle = "professional" | "casual" | "luxury" | "educational" | "promotional";
export type ToneOfVoice = "formal" | "friendly" | "premium" | "energetic" | "technical";
export type PreferredOutputLang = "ru" | "uz" | "en" | "cn";
export type Platform = "instagram" | "facebook" | "tiktok" | "telegram" | "linkedin";
export type ContentStatus = "new" | "needs_review" | "needs_caption" | "rejected" | "draft" | "ready" | "ready_for_approval" | "approved" | "scheduled" | "publishing" | "published" | "partial_failed" | "failed" | "changes_requested";

export interface Client {
  id: string;
  company_name: string;
  source_language: SourceLanguage;
  business_category: string;
  content_style: ContentStyle;
  status: string;
  notes?: string;
  brand_name?: string | null;
  business_description?: string | null;
  products_services?: string | null;
  target_audience?: string | null;
  tone_of_voice?: ToneOfVoice;
  preferred_languages?: PreferredOutputLang[];
  cta_phone?: string | null;
  cta_telegram?: string | null;
  cta_website?: string | null;
  cta_address?: string | null;
  words_to_avoid?: string | null;
  hashtag_preferences?: string | null;
  logo_url?: string | null;
  telegram_group_id?: string | null;
  telegram_group_title?: string | null;
  telegram_workflow_mode?: "auto_create_from_media" | "admin_controlled_buffer";
  operator_auto_draft_enabled?: boolean;
  telegram_publish_chat_id?: string | null;
  telegram_publish_title?: string | null;
  telegram_publish_type?: "channel" | "supergroup" | null;
  created_at: string;
  updated_at: string;
}

export interface MediaFile {
  id: string;
  client_id: string;
  original_filename: string;
  file_type: "image" | "video";
  mime_type: string;
  storage_path: string;
  thumbnail_path?: string;
  file_size: number;
  url: string;
  thumbnail_url?: string;
  ocr_text?: string;
  uploaded_at: string;
}

export interface SelectedMediaItem {
  ordinal: number;
  media_file_id: string;
  media_type: "image" | "video" | string;
  url: string;
  text?: string;
}

export interface ReadinessItem {
  id: string;
  label: string;
  ready: boolean;
  critical: boolean;
  message?: string | null;
}

export interface ContentReadiness {
  ready: boolean;
  ready_for_approve: boolean;
  ready_for_schedule: boolean;
  items: ReadinessItem[];
}

export interface PublishSafetyError {
  id: string;
  message: string;
  critical: boolean;
}

export type PublishMode = "test_publish" | "manual_publish" | "scheduled_publish";

export interface PublishSafety {
  passed: boolean;
  errors: PublishSafetyError[];
  message?: string | null;
  mode?: PublishMode | null;
}

export interface PlatformPublishResult {
  platform: Platform;
  success: boolean;
  mock?: boolean;
  platform_post_id?: string | null;
  post_url?: string | null;
  message?: string | null;
  error?: string | null;
}

export interface PublishContentResponse {
  content_id: string;
  status: ContentStatus;
  previous_status: string;
  published_at?: string | null;
  all_success: boolean;
  results: PlatformPublishResult[];
  test?: boolean;
}

export interface PublishAttempt {
  id: string;
  content_id: string;
  platform: Platform;
  account_id?: string | null;
  account_name?: string | null;
  status: string;
  response?: string | null;
  error?: string | null;
  platform_post_id?: string | null;
  post_url?: string | null;
  created_at: string;
}

export interface PublishingAccount {
  id: string;
  platform: Platform;
  account_name: string;
  account_id: string;
  status: "connected" | "disconnected" | "mock";
  created_at: string;
  updated_at: string;
}

export interface ContentItem {
  id: string;
  client_id: string;
  media_file_id?: string;
  platforms: Platform[];
  status: ContentStatus;
  source: "manual" | "telegram" | "telegram_group" | "tg_group_buffer" | "tg_inbox_auto_draft" | "content_plan" | "content_factory" | "content_studio" | "repurpose_engine";
  telegram_group_title?: string | null;
  telegram_message_id?: number | null;
  telegram_excluded?: boolean;
  telegram_instructions?: string | null;
  telegram_buffer_refs?: string | null;
  selected_media?: SelectedMediaItem[] | null;
  context_ai_override?: string | null;
  context_ai_detected?: string | null;
  context_ai_confidence?: number | null;
  content_classification?: string | null;
  telegram_original_caption?: string | null;
  telegram_forward_from?: string | null;
  suggestions?: {
    title?: string;
    short_description?: string;
    captions?: { ru?: string; uz?: string; en?: string; zh?: string };
    hashtags?: string;
    cta?: string;
    target_platforms?: Platform[];
    price_detected?: string;
    method?: string;
  } | null;
  quality_warnings?: { id: string; message: string; critical?: boolean }[] | null;
  source_badge?: string | null;
  caption_short_ru?: string;
  caption_short_uz?: string;
  caption_short_en?: string;
  caption_long_ru?: string;
  caption_long_uz?: string;
  caption_long_en?: string;
  hashtags?: string;
  internal_notes?: string;
  scheduled_for?: string;
  approved_at?: string;
  published_at?: string;
  client_approved_at?: string | null;
  client_review_feedback?: string | null;
  client_review_status?: "pending" | "approved" | "changes_requested" | null;
  client_review_preview_sent_at?: string | null;
  client_review_preview_error?: string | null;
  review_token?: string | null;
  campaign_id?: string | null;
  parent_content_id?: string | null;
  parent_media_asset_id?: string | null;
  linked_sales_lead_id?: string | null;
  linked_buyer_id?: string | null;
  linked_sales_deal_id?: string | null;
  created_at: string;
  updated_at: string;
  media_url?: string;
  media_file_type?: "image" | "video" | null;
  subtitle_url?: string | null;
  subtitle_url_cn?: string | null;
  subtitle_url_ru?: string | null;
  subtitle_url_uz?: string | null;
  subtitle_url_en?: string | null;
  subtitled_video_url_cn?: string | null;
  subtitled_video_url_ru?: string | null;
  subtitled_video_url_uz?: string | null;
  subtitled_video_url_en?: string | null;
  dubbed_video_url_ru?: string | null;
  dubbed_video_url_uz?: string | null;
  dubbed_video_url_en?: string | null;
  dubbed_video_extended_url_ru?: string | null;
  dubbed_video_extended_url_uz?: string | null;
  dubbed_video_extended_url_en?: string | null;
  final_video_url_cn?: string | null;
  final_video_url_ru?: string | null;
  final_video_url_uz?: string | null;
  final_video_url_en?: string | null;
  final_export_urls?: Record<string, string> | null;
  generated_final_video_url?: string | null;
  content_plan_context?: {
    plan_item_id: string;
    plan_id: string;
    plan_title: string;
    theme: string;
    goal: string;
    content_type: string;
    planned_date: string;
    ai_generated?: boolean;
  } | null;
  media_request_sent_at?: string | null;
  media_request_message?: string | null;
  media_request_status?: "requested" | "fulfilled" | "skipped" | null;
  media_request_format?: "photo" | "video" | "carousel" | "story" | "any" | null;
}

export const CONTEXT_AI_CATEGORIES = [
  "food",
  "auto_service",
  "technology",
  "beauty",
  "construction",
  "retail",
  "education",
  "real_estate",
  "logistics",
  "medical",
  "generic_business",
] as const;

export type ContextAiCategory = (typeof CONTEXT_AI_CATEGORIES)[number];

export const CONTEXT_AI_CATEGORY_LABELS: Record<string, string> = {
  food: "Food / Cafe / Restaurant",
  auto_service: "Auto repair / Car service",
  technology: "Computer / Technology",
  beauty: "Beauty / Salon",
  construction: "Construction / Materials",
  retail: "Retail / E-commerce",
  education: "Education / Training",
  real_estate: "Real estate",
  logistics: "Logistics",
  medical: "Medical / Clinic",
  generic_business: "Generic business",
};

export type SubtitleBurnLang = "cn" | "ru" | "uz" | "en";
export type VoiceoverLang = "ru" | "uz" | "en";
export type VoiceoverMode = "fitted" | "extended";

export interface CalendarContentInfo {
  id: string;
  client_id: string;
  status: ContentStatus;
  platforms: Platform[];
  caption_short_ru?: string;
  caption_short_en?: string;
  caption_short_uz?: string;
  media_url?: string;
}

export interface CalendarClientInfo {
  id: string;
  company_name: string;
}

export interface CalendarEntry {
  id: string;
  content_item_id: string;
  scheduled_date: string;
  time_slot?: string;
  platforms: Platform[];
  note?: string;
  created_at: string;
  content_item?: CalendarContentInfo;
  client?: CalendarClientInfo;
}

// ─── Client API ───────────────────────────────────────────────────────────────

export const clientsApi = {
  list: (params?: { skip?: number; limit?: number; status?: string }) =>
    api.get<{ items: Client[]; total: number }>("/clients", { params }),
  get: (id: string) => api.get<Client>(`/clients/${id}`),
  create: (data: Partial<Client>) => api.post<Client>("/clients", data),
  update: (id: string, data: Partial<Client>) => api.patch<Client>(`/clients/${id}`, data),
  delete: (id: string) => api.delete(`/clients/${id}`),
};

// ─── Client Knowledge Base API ────────────────────────────────────────────────

export type KbSection =
  | "company_profile"
  | "products_services"
  | "pricing"
  | "target_audience"
  | "tone_style"
  | "faq"
  | "past_campaigns"
  | "do_not_say"
  | "competitors"
  | "notes";

export type KbSource = "manual" | "telegram" | "content" | "ai_summary";
export type KbImportance = "low" | "medium" | "high";

export interface ClientKnowledgeBaseEntry {
  id: string;
  client_id: string;
  section: KbSection;
  title: string;
  content: string;
  source: KbSource;
  importance: KbImportance;
  created_at: string;
  updated_at: string;
}

export const clientKnowledgeBaseApi = {
  list: (clientId: string) =>
    api.get<{ items: ClientKnowledgeBaseEntry[]; total: number }>(
      `/clients/${clientId}/knowledge-base`,
    ),
  create: (
    clientId: string,
    data: {
      section: KbSection;
      title: string;
      content: string;
      source?: KbSource;
      importance?: KbImportance;
    },
  ) => api.post<ClientKnowledgeBaseEntry>(`/clients/${clientId}/knowledge-base`, data),
  update: (
    clientId: string,
    kbId: string,
    data: Partial<{
      section: KbSection;
      title: string;
      content: string;
      source: KbSource;
      importance: KbImportance;
    }>,
  ) => api.patch<ClientKnowledgeBaseEntry>(`/clients/${clientId}/knowledge-base/${kbId}`, data),
  delete: (clientId: string, kbId: string) =>
    api.delete(`/clients/${clientId}/knowledge-base/${kbId}`),
  aiSummarize: (clientId: string) =>
    api.post<{
      ok: boolean;
      message: string;
      created: number;
      updated: number;
      items: ClientKnowledgeBaseEntry[];
    }>(`/clients/${clientId}/knowledge-base/ai-summarize`),
};

// ─── Billing API ──────────────────────────────────────────────────────────────

export type BillingStatus = "active" | "unpaid" | "paused";

export interface ClientBillingUsage {
  posts_created_this_cycle: number;
  posts_published_this_cycle: number;
  posts_remaining?: number | null;
}

export interface ClientBilling {
  client_id: string;
  company_name: string;
  plan_name?: string | null;
  monthly_fee?: number | null;
  monthly_post_limit?: number | null;
  billing_status: BillingStatus;
  billing_cycle_start?: string | null;
  billing_cycle_end?: string | null;
  usage: ClientBillingUsage;
  near_limit: boolean;
}

export interface BillingOverviewClientUsage {
  client_id: string;
  company_name: string;
  plan_name?: string | null;
  billing_status: BillingStatus;
  monthly_post_limit?: number | null;
  posts_created_this_cycle: number;
  posts_published_this_cycle: number;
  posts_remaining?: number | null;
  near_limit: boolean;
}

export interface BillingOverview {
  active_clients: number;
  unpaid_clients: number;
  monthly_recurring_revenue: number;
  total_posts_used: number;
  clients_near_limit: BillingOverviewClientUsage[];
  usage_by_client: BillingOverviewClientUsage[];
}

export type DashboardDealRiskType =
  | "stale_activity"
  | "overdue_followup"
  | "proposal_stalled"
  | "invoice_unpaid";

export interface DashboardDealRisk {
  deal_id: string;
  lead_id: string;
  lead_name?: string | null;
  deal_title: string;
  risk_type: DashboardDealRiskType;
  title: string;
  severity: "high" | "medium";
}

export interface DashboardOperatorTaskItem {
  id: string;
  title: string;
  priority: string;
  action_type?: string | null;
  due_at?: string | null;
}

export interface DashboardOverview {
  inbox_new: number;
  tasks_open: number;
  operator_tasks_today?: number;
  operator_tasks_today_items?: DashboardOperatorTaskItem[];
  content_ready: number;
  content_scheduled: number;
  clients_waiting_materials: number;
  invoices_unpaid: number;
  active_deals: number;
  won_deals: number;
  lost_deals: number;
  pipeline_value: number | string;
  mrr: number;
  overdue_followups: number;
  near_limit_clients: number;
  deal_risks: DashboardDealRisk[];
  errors?: string[];
}

export interface DashboardAiSummary {
  executive_summary: string;
  top_priorities: string[];
  risks: string[];
  opportunities: string[];
  recommended_actions: string[];
  source: string;
}

function pickActiveSessionClient() {
  if (typeof window === "undefined") return api;

  const activeSession = readActiveSession();
  const hasAdminToken = !!localStorage.getItem(ADMIN_AUTH_TOKEN_KEY);
  const hasTenantToken = !!localStorage.getItem(AUTH_TOKEN_KEY);

  if (activeSession === "admin" && hasAdminToken) return adminApi;
  if (activeSession === "tenant" && hasTenantToken) return api;
  if (hasAdminToken && !hasTenantToken) return adminApi;
  if (hasTenantToken && !hasAdminToken) return api;
  return api;
}

/** Tenant product APIs — always prefer tenant JWT when both sessions exist. */
function pickTenantProductClient() {
  if (typeof window === "undefined") return api;
  if (localStorage.getItem(AUTH_TOKEN_KEY)) return api;
  if (localStorage.getItem(ADMIN_AUTH_TOKEN_KEY)) return adminApi;
  return api;
}

function pickBillingSessionClient() {
  return pickActiveSessionClient();
}

export const dashboardApi = {
  overview: () => pickActiveSessionClient().get<DashboardOverview>("/dashboard/overview"),
  aiSummary: () => pickActiveSessionClient().post<DashboardAiSummary>("/dashboard/ai-summary"),
};

export interface SalesDeptOverviewKpis {
  total_leads: number;
  new_leads: number;
  qualified_leads: number;
  active_deals: number;
  won_deals: number;
  lost_deals: number;
  pipeline_value: number | string;
  closed_revenue: number | string;
  commission_earned: number | string;
  pending_commission: number | string;
  partner_count: number;
  buyer_recommendations_count: number;
  landing_page_leads: number;
  attribution_clicks: number;
}

export interface SalesDeptFunnel {
  leads: number;
  contacted: number;
  qualified: number;
  proposal_sent: number;
  negotiation: number;
  won: number;
  lost: number;
}

export interface SalesDeptDashboard {
  overview: SalesDeptOverviewKpis;
  sales_funnel: SalesDeptFunnel;
  top_products: Array<{
    product_id: string;
    product_name: string;
    leads_count: number;
    deals_count: number;
    revenue: number | string;
    buyer_recommendations_count: number;
  }>;
  top_countries: Array<{
    country: string;
    leads_count: number;
    deals_count: number;
    revenue: number | string;
    opportunity_score: number;
  }>;
  top_attribution_sources: Array<{
    source: string;
    clicks: number;
    leads: number;
    deals: number;
    revenue: number | string;
    conversion_rate: number;
  }>;
  partner_performance: Array<{
    partner_id: string;
    partner_name: string;
    leads: number;
    deals: number;
    revenue: number | string;
    commission: number | string;
  }>;
  action_queue: {
    overdue_followups: Array<{ lead_id: string; name: string; due_at?: string | null }>;
    pending_proposals: Array<{ proposal_id: string; lead_id: string; title: string; status: string }>;
    unpaid_invoices: Array<{ document_id: string; lead_id: string; title: string }>;
    high_priority_sales_agent_recommendations: Array<{
      id: string;
      title: string;
      priority: string;
      recommendation_type: string;
      lead_id?: string | null;
      deal_id?: string | null;
    }>;
    risky_deals: Array<{
      deal_id: string;
      lead_id: string;
      deal_title: string;
      lead_name?: string | null;
      risk_type: string;
      title: string;
      severity: string;
    }>;
  };
  sales_assistant?: {
    open_count: number;
    urgent_count: number;
    top_recommendations: Array<{
      id: string;
      title: string;
      priority: string;
      recommendation_type: string;
      lead_id?: string | null;
      deal_id?: string | null;
      conversation_id?: string | null;
    }>;
  };
  operator_tasks?: {
    open_count: number;
    urgent_count: number;
    overdue_count: number;
    top_tasks: Array<{
      id: string;
      title: string;
      priority: string;
      action_type?: string | null;
      due_at?: string | null;
      status?: string;
    }>;
  };
  sales_manager?: {
    leads_count: number;
    hot_leads: number;
    opportunities_count: number;
    risks_count: number;
    overdue_tasks: number;
    active_proposals: number;
    top_recommendations: Array<{
      category: string;
      title: string;
      priority: string;
    }>;
  };
  lead_intelligence?: LeadIntelligenceMetrics;
  errors: string[];
  filters: Record<string, string | null>;
}

export interface SalesDeptAiBriefing {
  executive_summary: string;
  what_is_working: string[];
  risks: string[];
  opportunities: string[];
  recommended_actions: string[];
  priority_score: number;
  source: string;
  errors: string[];
}

export const salesDepartmentApi = {
  dashboard: (params?: { client_id?: string; date_from?: string; date_to?: string }) =>
    api.get<SalesDeptDashboard>("/sales-department/dashboard", { params }),
  aiBriefing: (clientId?: string) =>
    api.post<SalesDeptAiBriefing>("/sales-department/ai-briefing", null, {
      params: clientId ? { client_id: clientId } : undefined,
    }),
};

export interface SalesDeptV3PriorityLead {
  lead_id: string;
  name: string;
  company?: string | null;
  priority_score: number;
  urgency: string;
  revenue_potential: number;
  lead_score: number;
  qualification_level?: string | null;
  recommended_action?: string | null;
  sources: string[];
}

export interface SalesDeptV3PriorityConversation {
  conversation_id: string;
  channel: string;
  source: string;
  contact_name?: string | null;
  response_urgency: string;
  follow_up_priority: string;
  communication_health: number;
  classification?: string | null;
  recommended_action?: string | null;
}

export interface SalesDeptV3Opportunity {
  opportunity_id: string;
  title: string;
  source: string;
  opportunity_health: number;
  deal_risk: string;
  closing_probability: number;
  expected_value?: number | string | null;
  lead_id?: string | null;
  deal_room_id?: string | null;
  priority: string;
}

export interface SalesDeptV3Risk {
  risk_id: string;
  title: string;
  issue: string;
  severity: string;
  source: string;
  category?: string | null;
  lead_id?: string | null;
  deal_id?: string | null;
  conversation_id?: string | null;
}

export interface SalesDeptV3RecommendedAction {
  action_id: string;
  title: string;
  description: string;
  priority: string;
  source: string;
  category: string;
  lead_id?: string | null;
  deal_id?: string | null;
  conversation_id?: string | null;
  due_at?: string | null;
  is_overdue: boolean;
  requires_escalation: boolean;
}

export interface SalesDeptV3Overview {
  executive_summary: {
    summary: string;
    business_health_score: number;
    hot_leads: number;
    priority_leads: number;
    active_opportunities: number;
    open_risks: number;
    overdue_actions: number;
    communication_health: number;
  };
  top_opportunities: SalesDeptV3Opportunity[];
  top_risks: SalesDeptV3Risk[];
  priority_leads: SalesDeptV3PriorityLead[];
  priority_conversations: SalesDeptV3PriorityConversation[];
  recommended_actions: SalesDeptV3RecommendedAction[];
  revenue_forecast: {
    pipeline_value: number | string;
    weighted_pipeline: number | string;
    closed_revenue: number | string;
    forecast_30d: number | string;
    forecast_90d: number | string;
    currency: string;
    confidence: string;
  };
  buyer_intelligence?: {
    overview?: BuyerIntelligenceOverview;
    top_buyers?: BuyerRankingItem[];
    highest_risk?: BuyerRiskItem[];
  };
  buyer_discovery?: {
    overview?: BuyerDiscoveryOverview;
    highest_potential_buyers?: BuyerDiscoveryRankingItem[];
    acquisition_opportunities?: BuyerDiscoveryRankingItem[];
    best_markets?: Array<{ label: string; count: number; share_pct: number }>;
  };
  marketplace?: {
    overview?: {
      total_opportunities?: number;
      open_opportunities?: number;
      total_interests?: number;
      total_claims?: number;
    };
    best_opportunities?: Array<{ opportunity_id: string; title: string; rank_score: number }>;
  };
  deal_risk?: {
    overview?: DealRiskOverview;
    highest_risk_deals?: {
      rank: number;
      deal_id: string;
      title: string;
      deal_health_score: number;
      risk_level: DealRiskLevel;
    }[];
  };
  weekly_priorities: string[];
  coordination: Record<string, unknown>;
  errors: string[];
}

export interface SalesDeptV3Briefing {
  executive_summary: string;
  top_opportunities: string[];
  top_risks: string[];
  weekly_priorities: string[];
  recommended_actions: string[];
  revenue_forecast_note: string;
  source: string;
  generated_at: string;
  errors: string[];
}

export interface SalesDeptV3SummaryWidget {
  business_health_score: number;
  priority_leads: number;
  hot_leads: number;
  active_opportunities: number;
  open_risks: number;
  overdue_actions: number;
  pipeline_value: number | string;
  closed_revenue: number | string;
  communication_health: number;
  top_opportunities: Array<{ title: string; closing_probability: number; priority: string }>;
  top_risks: Array<{ issue: string; severity: string }>;
  top_actions: Array<{ title: string; priority: string; is_overdue: boolean }>;
  weekly_priorities: string[];
  errors: string[];
}

export interface SalesDeptV3DepartmentRecommendation {
  category: string;
  title: string;
  description: string;
  priority: string;
  source: string;
}

export interface MultiAgentRecommendation {
  title: string;
  description: string;
  priority: string;
  source_agent?: string;
  category?: string;
}

export interface MultiAgentAgentOutput {
  agent_name: string;
  summary: string;
  recommendations: string[];
  priority: string;
}

export interface MultiAgentConflict {
  topic: string;
  agents: string[];
  description: string;
}

export interface MultiAgentCoordinator {
  combined_summary: string;
  top_recommendations: MultiAgentRecommendation[];
  conflicts: MultiAgentConflict[];
  department_health: number;
  department_health_label: string;
}

export interface MultiAgentOverview {
  team_summary: string;
  coordinator: MultiAgentCoordinator;
  agents: MultiAgentAgentOutput[];
  active_agent_count: number;
  safety_notice: string;
  errors: string[];
}

export interface MultiAgentHealth {
  department_health: number;
  department_health_label: string;
  agent_health: Record<string, number>;
  hot_leads: number;
  open_risks: number;
  overdue_actions: number;
  communication_health: number;
  active_opportunities: number;
  top_recommendations: Array<{ title: string; priority: string; source_agent?: string }>;
  conflicts_count: number;
  safety_notice: string;
  errors: string[];
}

export interface MultiAgentBriefing {
  briefing_title: string;
  combined_summary: string;
  agent_summaries: Record<string, string>;
  top_recommendations: string[];
  conflicts: string[];
  department_health: number;
  weekly_priorities: string[];
  source: string;
  generated_at: string;
  safety_notice: string;
  errors: string[];
}

export const multiAgentTeamApi = {
  overview: (params?: { client_id?: string }) =>
    api.get<MultiAgentOverview>("/multi-agent/overview", { params }),
  agents: (params?: { client_id?: string }) =>
    api.get<{ agents: MultiAgentAgentOutput[]; total: number; errors: string[] }>(
      "/multi-agent/agents",
      { params },
    ),
  recommendations: (params?: { client_id?: string; limit?: number }) =>
    api.get<{
      top_recommendations: MultiAgentRecommendation[];
      by_agent: Record<string, string[]>;
      total: number;
      errors: string[];
    }>("/multi-agent/recommendations", { params }),
  health: (params?: { client_id?: string }) =>
    api.get<MultiAgentHealth>("/multi-agent/health", { params }),
  generateBriefing: (clientId?: string) =>
    api.post<MultiAgentBriefing>(
      "/multi-agent/generate-briefing",
      clientId ? { client_id: clientId } : {},
    ),
};

export interface RevenueForecastPeriod {
  period: string;
  best_case: number | string;
  expected_case: number | string;
  worst_case: number | string;
  currency: string;
}

export interface RevenueForecastPipelineStage {
  stage: string;
  count: number;
  forecast_revenue: number | string;
  win_probability: number;
}

export interface RevenueForecastRiskItem {
  risk_id: string;
  category: string;
  title: string;
  description: string;
  severity: string;
  entity_type?: string | null;
  entity_id?: string | null;
}

export interface RevenueForecastGrowthOpportunity {
  opportunity_id: string;
  title: string;
  description: string;
  expected_impact: number | string;
  priority: string;
  source: string;
}

export interface RevenueForecastOverview {
  forecasts: RevenueForecastPeriod[];
  currency: string;
  confidence: string;
  inputs_summary: Record<string, unknown>;
  safety_notice: string;
  errors: string[];
}

export interface RevenueForecastExecutive {
  forecast_summary: string;
  top_growth_opportunities: RevenueForecastGrowthOpportunity[];
  top_revenue_risks: RevenueForecastRiskItem[];
}

export interface RevenueForecastGenerateResult {
  forecasts: RevenueForecastPeriod[];
  pipeline: RevenueForecastPipelineStage[];
  executive: RevenueForecastExecutive;
  risks_total: number;
  currency: string;
  source: string;
  generated_at: string;
  safety_notice: string;
  errors: string[];
}

export interface RevenueForecastSummaryWidget {
  expected_30d: number | string;
  best_case_30d: number | string;
  worst_case_30d: number | string;
  pipeline_forecast: number | string;
  confidence: string;
  top_growth: Array<{ title: string; expected_impact: number | string; priority: string }>;
  top_risks: Array<{ title: string; severity: string; category: string }>;
  currency: string;
  errors: string[];
}

export interface RevenueForecastPanelItem {
  title: string;
  description: string;
  priority: string;
  source: string;
}

export const revenueForecastApi = {
  overview: (params?: { client_id?: string }) =>
    api.get<RevenueForecastOverview>("/revenue-forecast/overview", { params }),
  pipeline: (params?: { client_id?: string }) =>
    api.get<{
      stages: RevenueForecastPipelineStage[];
      total_pipeline_forecast: number | string;
      currency: string;
      errors: string[];
    }>("/revenue-forecast/pipeline", { params }),
  risks: (params?: { client_id?: string }) =>
    api.get<{
      inactive_deals: RevenueForecastRiskItem[];
      overdue_opportunities: RevenueForecastRiskItem[];
      proposals_at_risk: RevenueForecastRiskItem[];
      communication_risks: RevenueForecastRiskItem[];
      total: number;
      errors: string[];
    }>("/revenue-forecast/risks", { params }),
  executive: (params?: { client_id?: string }) =>
    api.get<{ executive: RevenueForecastExecutive; forecasts: RevenueForecastPeriod[]; errors: string[] }>(
      "/revenue-forecast/executive",
      { params },
    ),
  summaryWidget: (params?: { client_id?: string }) =>
    api.get<RevenueForecastSummaryWidget>("/revenue-forecast/summary-widget", { params }),
  generateForecast: (clientId?: string) =>
    api.post<RevenueForecastGenerateResult>(
      "/revenue-forecast/generate-forecast",
      clientId ? { client_id: clientId } : {},
    ),
};

export const salesDepartmentV3Api = {
  overview: (params?: { client_id?: string }) =>
    api.get<SalesDeptV3Overview>("/sales-department-v3/overview", { params }),
  priorities: (params?: { client_id?: string; limit?: number }) =>
    api.get<{ priority_leads: SalesDeptV3PriorityLead[]; priority_conversations: SalesDeptV3PriorityConversation[]; total: number; errors: string[] }>(
      "/sales-department-v3/priorities",
      { params },
    ),
  opportunities: (params?: { client_id?: string; limit?: number }) =>
    api.get<{ items: SalesDeptV3Opportunity[]; total: number; errors: string[] }>(
      "/sales-department-v3/opportunities",
      { params },
    ),
  risks: (params?: { client_id?: string; limit?: number }) =>
    api.get<{ items: SalesDeptV3Risk[]; total: number; errors: string[] }>(
      "/sales-department-v3/risks",
      { params },
    ),
  recommendations: (params?: { client_id?: string; limit?: number }) =>
    api.get<{
      recommended_actions: SalesDeptV3RecommendedAction[];
      overdue_actions: SalesDeptV3RecommendedAction[];
      escalation_list: SalesDeptV3RecommendedAction[];
      total: number;
      errors: string[];
    }>("/sales-department-v3/recommendations", { params }),
  summaryWidget: (params?: { client_id?: string }) =>
    api.get<SalesDeptV3SummaryWidget>("/sales-department-v3/summary-widget", { params }),
  generateBriefing: (clientId?: string) =>
    api.post<SalesDeptV3Briefing>("/sales-department-v3/generate-briefing", clientId ? { client_id: clientId } : {}),
};

export type AiCommandRiskLevel = "low" | "medium" | "high";

export interface AiCommandActionPlan {
  action_type: string;
  label: string;
  payload: Record<string, unknown>;
  is_critical?: boolean;
}

export interface AiCommandPlanResult {
  command_id: string;
  summary: string;
  parsed_intent: string;
  actions: AiCommandActionPlan[];
  risk_level: AiCommandRiskLevel;
  requires_confirmation: boolean;
  unsupported_parts: string[];
  context_summary?: string | null;
}

export interface AiCommandContextPayload {
  current_page?: string;
  entity_type?: string;
  entity_id?: string;
  selected_items?: string[];
  user_context_json?: Record<string, unknown>;
}

export interface AiCommandSuggestionItem {
  label: string;
  command: string;
  kind: "command" | "link";
  href?: string | null;
}

export interface AiCommandSuggestionsResult {
  current_page?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  entity_label?: string | null;
  entity_summary?: string | null;
  suggestions: AiCommandSuggestionItem[];
}

export interface AiCommandActionResult {
  id: string;
  action_type: string;
  label: string;
  status: string;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

export interface AiCommandExecuteResult {
  command_id: string;
  status: string;
  summary?: string | null;
  actions: AiCommandActionResult[];
  error?: string | null;
}

export interface AiCommandHistoryItem {
  id: string;
  raw_command: string;
  parsed_intent?: string | null;
  status: string;
  summary?: string | null;
  action_count: number;
  completed_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
}

export const aiCommandApi = {
  plan: (body: { command: string } & AiCommandContextPayload) =>
    api.post<AiCommandPlanResult>("/ai-command/plan", body),
  suggestions: (body: AiCommandContextPayload) =>
    api.post<AiCommandSuggestionsResult>("/ai-command/suggestions", body),
  execute: (commandId: string) =>
    api.post<AiCommandExecuteResult>(`/ai-command/${commandId}/execute`, {}),
  history: (params?: { skip?: number; limit?: number }) =>
    api.get<{ items: AiCommandHistoryItem[]; total: number }>("/ai-command/history", { params }),
  get: (commandId: string) =>
    api.get<AiCommandExecuteResult & { raw_command: string; risk_level?: string; unsupported_parts?: string[] }>(
      `/ai-command/${commandId}`,
    ),
};

export type CommissionStatus = "pending" | "approved" | "paid";

export interface RevenueAttributionBreakdown {
  source: string;
  label: string;
  deal_count: number;
  revenue: number | string;
  commission: number | string;
}

export interface RevenueDealRow {
  deal_id: string;
  title: string;
  client_name?: string | null;
  lead_name?: string | null;
  attribution_source?: string | null;
  deal_amount?: number | string | null;
  currency: string;
  commission_percent?: number | string | null;
  commission_amount?: number | string | null;
  commission_status?: CommissionStatus | null;
  partner_commission_percent?: number | string | null;
  partner_commission_amount?: number | string | null;
  status: string;
  updated_at: string;
}

export interface RevenueAttributionLinkStats {
  link_id: string;
  title: string;
  code: string;
  channel: string;
  clicks_count: number;
  leads_count: number;
  won_deals_count: number;
  revenue: number | string;
  commission: number | string;
  click_to_lead_rate: number;
  lead_to_won_rate: number;
}

export interface RevenueOverview {
  total_pipeline_value: number | string;
  total_closed_revenue: number | string;
  total_commission_earned: number | string;
  pending_commission: number | string;
  paid_commission: number | string;
  our_commission: number | string;
  partner_commission: number | string;
  deals_won: number;
  deals_lost: number;
  attribution_breakdown: RevenueAttributionBreakdown[];
  attribution_links?: RevenueAttributionLinkStats[];
  deals: RevenueDealRow[];
  deals_total?: number;
  errors?: string[];
}

export type AttributionLinkChannel = "telegram" | "whatsapp" | "wechat" | "website" | "manual";

export interface AttributionLink {
  id: string;
  client_id: string;
  campaign_id?: string | null;
  product_id?: string | null;
  partner_id?: string | null;
  channel: AttributionLinkChannel;
  code: string;
  destination_url: string;
  title: string;
  description?: string | null;
  clicks_count: number;
  leads_count: number;
  tracking_url: string;
  client_name?: string | null;
  campaign_name?: string | null;
  product_name?: string | null;
  partner_name?: string | null;
  conversion_rate: number;
  linked_revenue: number | string;
  linked_commission: number | string;
  won_deals_count: number;
  created_at: string;
}

export const ATTRIBUTION_CHANNEL_LABELS: Record<AttributionLinkChannel, string> = {
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  wechat: "WeChat",
  website: "Website",
  manual: "Manual",
};

export const attributionLinksApi = {
  list: (params?: {
    client_id?: string;
    campaign_id?: string;
    product_id?: string;
    partner_id?: string;
    channel?: AttributionLinkChannel;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: AttributionLink[]; total: number }>("/attribution-links", { params }),
  create: (data: {
    client_id: string;
    channel: AttributionLinkChannel;
    destination_url: string;
    title: string;
    campaign_id?: string | null;
    product_id?: string | null;
    partner_id?: string | null;
    description?: string | null;
  }) => api.post<AttributionLink>("/attribution-links", data),
};

export type LandingPageStatus = "draft" | "published" | "archived";

export interface LandingPage {
  id: string;
  client_id: string;
  campaign_id?: string | null;
  product_id?: string | null;
  attribution_link_id?: string | null;
  slug: string;
  title: string;
  subtitle?: string | null;
  description?: string | null;
  hero_image_url?: string | null;
  cta_text: string;
  status: LandingPageStatus;
  public_url: string;
  client_name?: string | null;
  campaign_name?: string | null;
  product_name?: string | null;
  leads_count: number;
  created_at: string;
  updated_at: string;
}

export interface PublicLandingPage {
  slug: string;
  title: string;
  subtitle?: string | null;
  description?: string | null;
  hero_image_url?: string | null;
  cta_text: string;
  product?: { name: string; category?: string | null; description?: string | null } | null;
  campaign?: { name: string; objective?: string | null } | null;
}

export const landingPagesApi = {
  list: (params?: { client_id?: string; status?: LandingPageStatus; skip?: number; limit?: number }) =>
    api.get<{ items: LandingPage[]; total: number }>("/landing-pages", { params }),
  get: (id: string) => api.get<LandingPage>(`/landing-pages/${id}`),
  create: (data: {
    client_id: string;
    slug: string;
    title: string;
    subtitle?: string | null;
    description?: string | null;
    hero_image_url?: string | null;
    cta_text?: string;
    campaign_id?: string | null;
    product_id?: string | null;
    attribution_link_id?: string | null;
    status?: LandingPageStatus;
  }) => api.post<LandingPage>("/landing-pages", data),
  update: (id: string, data: Partial<{
    slug: string;
    title: string;
    subtitle: string | null;
    description: string | null;
    hero_image_url: string | null;
    cta_text: string;
    campaign_id: string | null;
    product_id: string | null;
    attribution_link_id: string | null;
    status: LandingPageStatus;
  }>) => api.patch<LandingPage>(`/landing-pages/${id}`, data),
};

export const publicLandingApi = {
  get: (slug: string) =>
    axios.get<PublicLandingPage>(`${getBackendBaseUrl()}/public/landing/${slug}`),
  submitLead: (slug: string, data: {
    name: string;
    company?: string;
    phone?: string;
    email?: string;
    telegram?: string;
    whatsapp?: string;
    wechat?: string;
    country?: string;
    message?: string;
  }) =>
    axios.post<{ ok: boolean; message: string }>(
      `${getBackendBaseUrl()}/public/landing/${slug}/lead`,
      data,
    ),
};

export interface RevenueAiInsights {
  summary: string;
  risks: string[];
  opportunities: string[];
  recommendations: string[];
  source: string;
}

export const revenueApi = {
  overview: () => api.get<RevenueOverview>("/revenue/overview"),
  approveCommission: (dealId: string) =>
    api.post<RevenueDealRow>(`/revenue/deals/${dealId}/approve-commission`),
  markCommissionPaid: (dealId: string) =>
    api.post<RevenueDealRow>(`/revenue/deals/${dealId}/mark-paid`),
  aiInsights: () => api.post<RevenueAiInsights>("/revenue/ai-insights"),
};

export type PartnerStatus = "active" | "inactive";

export type PartnerType =
  | "distributor"
  | "dealer"
  | "importer"
  | "agent"
  | "retail_chain"
  | "construction_company"
  | "other";

export const PARTNER_TYPE_LABELS: Record<PartnerType, string> = {
  distributor: "Distributor",
  dealer: "Dealer",
  importer: "Importer",
  agent: "Agent",
  retail_chain: "Retail Chain",
  construction_company: "Construction Company",
  other: "Other",
};

export interface ReferralLink {
  id: string;
  partner_id: string;
  code: string;
  description?: string | null;
  created_at: string;
}

export interface Partner {
  id: string;
  name: string;
  company?: string | null;
  company_name?: string | null;
  country?: string | null;
  city?: string | null;
  partner_type?: PartnerType | null;
  industries_json?: string[];
  website?: string | null;
  phone?: string | null;
  telegram?: string | null;
  email?: string | null;
  status: PartnerStatus;
  notes?: string | null;
  referral_links: ReferralLink[];
  leads_count: number;
  won_deals: number;
  revenue: number | string;
  commission: number | string;
  created_at: string;
  updated_at: string;
}

export interface PartnerMatchItem {
  partner_id: string;
  name: string;
  company_name?: string | null;
  partner_type?: string | null;
  country?: string | null;
  score: number;
  reason: string;
}

export interface PartnerHub {
  id: string;
  name: string;
  company_name?: string | null;
  country?: string | null;
  city?: string | null;
  partner_type?: string | null;
  industries_json: string[];
  website?: string | null;
  phone?: string | null;
  email?: string | null;
  status: PartnerStatus;
  notes?: string | null;
  leads_count: number;
  won_deals: number;
  revenue: number | string;
  commission: number | string;
  activities: {
    id: string;
    partner_id: string;
    activity_type: string;
    description: string;
    created_at: string;
  }[];
  related_products: {
    interest_id: string;
    product_id: string;
    name: string;
    category?: string | null;
    unit_price?: number | string | null;
    currency: string;
    interest_score?: number | null;
    notes?: string | null;
  }[];
  related_leads: {
    id: string;
    name: string;
    company?: string | null;
    status: string;
    interest?: string | null;
    referral_code?: string | null;
    created_at?: string | null;
    match_hits?: number | null;
  }[];
  matched_leads: {
    id: string;
    name: string;
    company?: string | null;
    status: string;
    interest?: string | null;
    match_hits?: number | null;
  }[];
}

export interface PartnerPerformance {
  partner_id: string;
  leads: number;
  won_deals: number;
  revenue: number | string;
  commission: number | string;
  our_commission: number | string;
  lead_items: {
    id: string;
    name: string;
    company?: string | null;
    status: string;
    estimated_value?: number | string | null;
    referral_code?: string | null;
    created_at: string;
  }[];
  deal_items: {
    id: string;
    title: string;
    status: string;
    deal_amount?: number | string | null;
    currency: string;
    partner_commission_amount?: number | string | null;
    commission_amount?: number | string | null;
    updated_at: string;
  }[];
  timeline: {
    id: string;
    deal_id: string;
    deal_title: string;
    event_type: string;
    title: string;
    created_at: string;
  }[];
}

export interface PartnerAiInsights {
  best_opportunities: string[];
  inactive_leads: string[];
  revenue_forecast: string;
  recommended_actions: string[];
  source: string;
}

export const partnersApi = {
  list: (params?: {
    status?: PartnerStatus;
    search?: string;
    country?: string;
    partner_type?: string;
    industry?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: Partner[]; total: number }>("/partners", { params }),
  filters: () =>
    api.get<{ countries: string[]; partner_types: string[]; industries: string[] }>(
      "/partners/filters/list",
    ),
  create: (data: {
    name: string;
    company?: string | null;
    company_name?: string | null;
    country?: string | null;
    city?: string | null;
    partner_type?: PartnerType | null;
    industries_json?: string[];
    website?: string | null;
    phone?: string | null;
    telegram?: string | null;
    email?: string | null;
    status?: PartnerStatus;
    notes?: string | null;
    referral_code?: string;
    referral_description?: string;
  }) => api.post<Partner>("/partners", data),
  get: (id: string) => api.get<Partner>(`/partners/${id}`),
  hub: (id: string) => api.get<PartnerHub>(`/partners/${id}/hub`),
  addActivity: (id: string, data: { activity_type: string; description: string }) =>
    api.post(`/partners/${id}/activities`, data),
  update: (
    id: string,
    data: Partial<{
      name: string;
      company: string | null;
      company_name: string | null;
      country: string | null;
      city: string | null;
      partner_type: PartnerType | null;
      industries_json: string[];
      website: string | null;
      phone: string | null;
      telegram: string | null;
      email: string | null;
      status: PartnerStatus;
      notes: string | null;
    }>,
  ) => api.patch<Partner>(`/partners/${id}`, data),
  delete: (id: string) => api.delete(`/partners/${id}`),
  performance: (id: string) => api.get<PartnerPerformance>(`/partners/${id}/performance`),
  aiInsights: (id: string) => api.post<PartnerAiInsights>(`/partners/${id}/insights`),
  matchProduct: (productId: string) =>
    api.post<{
      product_id: string;
      product_name: string;
      query_context: string;
      matches: PartnerMatchItem[];
      demo_mode: boolean;
    }>(`/partners/match-product/${productId}`),
  matchLead: (leadId: string) =>
    api.post<{
      lead_id: string;
      lead_name: string;
      query_context: string;
      matches: PartnerMatchItem[];
      demo_mode: boolean;
    }>(`/partners/match-lead/${leadId}`),
};

export type SalesAgentRecommendationType =
  | "follow_up"
  | "proposal"
  | "contract"
  | "invoice"
  | "payment_reminder"
  | "partner_follow_up"
  | "risk_warning"
  | "opportunity";

export type SalesAgentPriority = "high" | "medium" | "low";
export type SalesAgentStatus = "new" | "accepted" | "dismissed" | "done";

export interface SalesAgentRecommendation {
  id: string;
  client_id: string;
  client_name?: string | null;
  lead_id?: string | null;
  lead_name?: string | null;
  deal_id?: string | null;
  deal_title?: string | null;
  partner_id?: string | null;
  partner_name?: string | null;
  recommendation_type: SalesAgentRecommendationType;
  title: string;
  description: string;
  priority: SalesAgentPriority;
  suggested_message?: string | null;
  suggested_action?: string | null;
  status: SalesAgentStatus;
  linked_task_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SalesAgentSummary {
  high_priority_count: number;
  overdue_followups: number;
  unpaid_invoices: number;
  risky_deals: number;
  new_recommendations: number;
}

export const salesAgentApi = {
  scan: () =>
    api.post<{ scanned: number; created: number; skipped_duplicates: number }>(
      "/sales-agent/scan",
    ),
  summary: () => api.get<SalesAgentSummary>("/sales-agent/summary"),
  list: (params?: {
    status?: SalesAgentStatus;
    priority?: SalesAgentPriority;
    client_id?: string;
    type?: SalesAgentRecommendationType;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: SalesAgentRecommendation[]; total: number }>(
      "/sales-agent/recommendations",
      { params },
    ),
  accept: (id: string) =>
    api.post<{ recommendation: SalesAgentRecommendation; task_id: string }>(
      `/sales-agent/recommendations/${id}/accept`,
    ),
  dismiss: (id: string) =>
    api.post<SalesAgentRecommendation>(`/sales-agent/recommendations/${id}/dismiss`),
  markDone: (id: string) =>
    api.post<SalesAgentRecommendation>(`/sales-agent/recommendations/${id}/mark-done`),
};

export type SalesAssistantRecommendationType =
  | "reply_needed"
  | "follow_up_needed"
  | "proposal_needed"
  | "lead_link_needed"
  | "deal_update_needed"
  | "hot_lead"
  | "stalled_deal"
  | "missing_task"
  | "playbook_recommended";

export type SalesAssistantPriority = "low" | "medium" | "high" | "urgent";
export type SalesAssistantStatus = "open" | "dismissed" | "completed";

export interface SalesAssistantRecommendation {
  id: string;
  client_id?: string | null;
  client_name?: string | null;
  lead_id?: string | null;
  lead_name?: string | null;
  deal_id?: string | null;
  deal_title?: string | null;
  conversation_id?: string | null;
  channel?: string | null;
  recommendation_type: SalesAssistantRecommendationType;
  priority: SalesAssistantPriority;
  title: string;
  summary: string;
  recommended_action: string;
  reason: string;
  status: SalesAssistantStatus;
  linked_task_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SalesAssistantSummary {
  open_count: number;
  urgent_count: number;
  follow_ups_needed: number;
  proposals_needed: number;
}

export const salesAssistantApi = {
  scan: (useAi = false) =>
    api.post<{ scanned: number; created: number; skipped_duplicates: number }>(
      "/sales-assistant/scan",
      { use_ai: useAi },
    ),
  list: (params?: {
    status?: SalesAssistantStatus;
    priority?: SalesAssistantPriority;
    client_id?: string;
    lead_id?: string;
    deal_id?: string;
    conversation_id?: string;
    type?: SalesAssistantRecommendationType;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{
      items: SalesAssistantRecommendation[];
      total: number;
      summary: SalesAssistantSummary;
    }>("/sales-assistant/recommendations", { params }),
  dismiss: (id: string) =>
    api.post<SalesAssistantRecommendation>(`/sales-assistant/recommendations/${id}/dismiss`),
  complete: (id: string) =>
    api.post<SalesAssistantRecommendation>(`/sales-assistant/recommendations/${id}/complete`),
  createTask: (id: string) =>
    api.post<{ recommendation: SalesAssistantRecommendation; task_id: string }>(
      `/sales-assistant/recommendations/${id}/create-task`,
    ),
};

export interface SalesManagerOverview {
  leads_count: number;
  hot_leads: number;
  qualified_leads: number;
  neglected_leads: number;
  overdue_tasks: number;
  active_proposals: number;
  proposal_conversion_rate: number;
  inbox_activity: {
    open_conversations: number;
    unanswered: number;
    active_24h: number;
    wechat_threads: number;
    whatsapp_threads: number;
  };
  operator_workload: {
    open_tasks: number;
    overdue_tasks: number;
    urgent_tasks: number;
    unassigned_tasks: number;
    overloaded_assignees: number;
  };
  opportunities_count: number;
  risks_count: number;
  conversations_count: number;
  workflow_recommendations?: number;
  workflow_high_priority?: number;
  workflow_follow_ups?: number;
  workflow_proposals?: number;
  workflow_crm_cleanup?: number;
  communication_intelligence?: {
    follow_ups_required?: number;
    avg_health_score?: number;
    risk_count?: number;
    opportunity_count?: number;
  };
  revenue_performance?: RevenueAttributionSummaryWidget & {
    insights?: RevenueAttributionInsights;
  };
  errors?: string[];
}

export interface SalesManagerOpportunity {
  type: string;
  source: string;
  priority: "urgent" | "high" | "medium" | "low";
  action: string;
  title: string;
  summary?: string | null;
  lead_id?: string | null;
  deal_id?: string | null;
  conversation_id?: string | null;
  entity_id?: string | null;
  classification?: string | null;
}

export interface SalesManagerRisk {
  issue: string;
  severity: "critical" | "high" | "medium" | "low";
  recommendation: string;
  type: string;
  source?: string | null;
  lead_id?: string | null;
  deal_id?: string | null;
  conversation_id?: string | null;
}

export interface SalesManagerRecommendation {
  category: string;
  title: string;
  description: string;
  priority: "urgent" | "high" | "medium" | "low";
  lead_id?: string | null;
  conversation_id?: string | null;
  workflow_type?: string | null;
}

export interface SalesManagerBriefing {
  summary: string;
  opportunities: string[];
  risks: string[];
  recommendations: string[];
  source: string;
  generated_at: string;
  errors?: string[];
}

export interface SalesManagerSummaryWidget {
  hot_leads: number;
  opportunities_count: number;
  risks_count: number;
  overdue_tasks: number;
  open_conversations: number;
  active_proposals: number;
  top_opportunities: Array<{ type: string; title: string; priority: string }>;
  top_risks: Array<{ issue: string; severity: string }>;
}

export type ExecutiveCopilotRecommendationCategory =
  | "hot_lead_follow_up"
  | "proposal_follow_up"
  | "inactive_lead_recovery"
  | "overdue_task_escalation"
  | "conversation_response_reminder";

export interface ExecutiveCopilotRevenueSummary {
  closed_revenue: number;
  pipeline_value: number;
  deals_won: number;
  pending_commission: number;
  currency: string;
}

export interface ExecutiveCopilotOverview {
  revenue: ExecutiveCopilotRevenueSummary;
  opportunities: number;
  hot_leads: number;
  overdue_tasks: number;
  active_conversations: number;
  proposals_pending: number;
  risk_count: number;
  business_health_score: number;
  leads_count: number;
  open_tasks: number;
  workflow_recommendations: number;
  revenue_attribution?: RevenueAttributionInsights;
  subscription_billing?: {
    mrr: number;
    active_subscriptions: number;
    trial_subscriptions: number;
    plan_distribution: Record<string, number>;
  };
  errors?: string[];
}

export interface ExecutiveCopilotAlert {
  id: string;
  type: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  message: string;
  source: string;
  lead_id?: string | null;
  deal_id?: string | null;
  conversation_id?: string | null;
}

export interface ExecutiveCopilotRecommendation {
  category: ExecutiveCopilotRecommendationCategory;
  title: string;
  description: string;
  priority: "urgent" | "high" | "medium" | "low";
  lead_id?: string | null;
  conversation_id?: string | null;
  entity_id?: string | null;
  source: string;
}

export interface ExecutiveCopilotBriefing {
  summary: string;
  business_health_score: number;
  opportunities: string[];
  risks: string[];
  recommendations: string[];
  communication_intelligence?: CommunicationIntelligenceOverview;
  source: string;
  generated_at: string;
  errors?: string[];
}

export interface ExecutiveCopilotSummaryWidget {
  business_health_score: number;
  hot_leads: number;
  opportunities: number;
  risk_count: number;
  overdue_tasks: number;
  active_conversations: number;
  proposals_pending: number;
  closed_revenue: number;
  top_alerts: ExecutiveCopilotAlert[];
  top_recommendations: ExecutiveCopilotRecommendation[];
  factory_partner_pending?: number;
  subscription_mrr?: number;
  active_subscriptions?: number;
}

export type ExecutiveCopilotAxiosClient = "adminApi" | "tenantApi";

export function getExecutiveCopilotAxiosClient(): ExecutiveCopilotAxiosClient {
  if (typeof window !== "undefined" && localStorage.getItem("admin_auth_token")) {
    return "adminApi";
  }
  return "tenantApi";
}

function pickExecutiveAuthClient() {
  return getExecutiveCopilotAxiosClient() === "adminApi" ? adminApi : api;
}

const EXECUTIVE_COPILOT_TIMEOUT_MS = 25_000;

export const executiveCopilotApi = {
  overview: (clientId?: string) =>
    pickExecutiveAuthClient().get<ExecutiveCopilotOverview>("/executive-copilot/overview", {
      params: clientId ? { client_id: clientId } : undefined,
      timeout: EXECUTIVE_COPILOT_TIMEOUT_MS,
    }),
  alerts: (params?: { client_id?: string; limit?: number }) =>
    pickExecutiveAuthClient().get<{ items: ExecutiveCopilotAlert[]; total: number }>(
      "/executive-copilot/alerts",
      { params, timeout: EXECUTIVE_COPILOT_TIMEOUT_MS },
    ),
  recommendations: (params?: { client_id?: string; limit?: number }) =>
    pickExecutiveAuthClient().get<{ items: ExecutiveCopilotRecommendation[]; total: number }>(
      "/executive-copilot/recommendations",
      { params, timeout: EXECUTIVE_COPILOT_TIMEOUT_MS },
    ),
  summaryWidget: (clientId?: string) =>
    pickExecutiveAuthClient().get<ExecutiveCopilotSummaryWidget>(
      "/executive-copilot/summary-widget",
      {
        params: clientId ? { client_id: clientId } : undefined,
        timeout: EXECUTIVE_COPILOT_TIMEOUT_MS,
      },
    ),
  generateBriefing: (clientId?: string) =>
    pickExecutiveAuthClient().post<ExecutiveCopilotBriefing>(
      "/executive-copilot/generate-briefing",
      {
        client_id: clientId ?? undefined,
      },
      { timeout: EXECUTIVE_COPILOT_TIMEOUT_MS },
    ),
};

export type DealRoomStage =
  | "new"
  | "qualification"
  | "proposal"
  | "negotiation"
  | "contract"
  | "closing"
  | "won"
  | "lost";

export type DealRoomStatus = "active" | "on_hold" | "closed";

export interface DealRoomItem {
  id: string;
  crm_client_id: string;
  client_name?: string | null;
  deal_name: string;
  stage: DealRoomStage | string;
  status: DealRoomStatus | string;
  probability: number;
  expected_value?: number | string | null;
  created_at: string;
  updated_at: string;
}

export interface DealRoomClientSummary {
  id: string;
  company_name: string;
  contact_name?: string | null;
  email?: string | null;
  phone?: string | null;
  lead_intelligence?: {
    lead_id?: string;
    lead_name?: string;
    lead_score?: number | null;
    qualification_level?: string | null;
    status?: string;
    priority?: string;
    ai_summary?: string | null;
    recommended_action?: string | null;
    estimated_value?: number | string | null;
  } | null;
}

export interface DealRoomConversationItem {
  id: string;
  channel: string;
  title: string;
  status: string;
  last_message_at?: string | null;
  lead_id?: string | null;
  unread_count?: number;
}

export interface DealRoomProposalItem {
  id: string;
  title: string;
  status: string;
  language?: string | null;
  sent_at?: string | null;
  created_at?: string | null;
}

export interface DealRoomTaskItem {
  id: string;
  title: string;
  status: string;
  priority: string;
  due_at?: string | null;
  action_type?: string | null;
}

export interface DealRoomRecommendationItem {
  id: string;
  source: "sales_assistant" | "executive_copilot";
  title: string;
  description: string;
  priority: string;
  recommended_action?: string | null;
}

export interface DealRoomRiskItem {
  type: string;
  severity: "critical" | "high" | "medium" | "low";
  issue: string;
  recommendation: string;
}

export interface DealRoomProbability {
  score: number;
  factors: string[];
  stored_probability: number;
}

export interface DealRoomDetail {
  id: string;
  crm_client_id: string;
  deal_name: string;
  stage: string;
  status: string;
  expected_value?: number | string | null;
  created_at: string;
  updated_at: string;
  client?: DealRoomClientSummary | null;
  conversations: DealRoomConversationItem[];
  proposals: DealRoomProposalItem[];
  tasks: DealRoomTaskItem[];
  recommendations: DealRoomRecommendationItem[];
  risks: DealRoomRiskItem[];
  probability: DealRoomProbability;
  communication_analysis?: Array<{
    conversation_id: string;
    channel: string;
    title?: string;
    health_score?: number;
    classification?: string;
    urgency?: string;
    insights?: string[];
    recommended_actions?: string[];
  }>;
  revenue_attribution?: RevenueAttributionLeadSummary | null;
  buyer_intelligence?: {
    buyer_score: number;
    classification: string;
    risk_level: string;
    annual_potential?: number | string;
    potential?: {
      expected_annual_revenue: number | string;
      expected_deal_size: number | string;
      growth_potential: string;
      currency: string;
    };
    insights?: string[];
    recommendations?: string[];
    risks?: string[];
  } | null;
  deal_risk?: {
    deal_health_score: number;
    risk_level: DealRiskLevel;
    close_probability: number;
    expected_close_date?: string | null;
    confidence_level?: string;
    risk_reasons?: string[];
    recommendations?: string[];
    risk_factors?: string[];
  } | null;
  errors?: string[];
}

export const dealRoomApi = {
  list: (params?: { crm_client_id?: string; status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: DealRoomItem[]; total: number }>("/deal-room", { params }),
  get: (id: string) => api.get<DealRoomDetail>(`/deal-room/${id}`),
  create: (data: {
    crm_client_id: string;
    deal_name: string;
    stage?: DealRoomStage;
    status?: DealRoomStatus;
    expected_value?: number | null;
    crm_lead_id?: string;
  }) => api.post<DealRoomItem>("/deal-room/create", data),
  updateStage: (data: { deal_room_id: string; stage: DealRoomStage; probability?: number }) =>
    api.post<DealRoomItem>("/deal-room/update-stage", data),
  findOrCreate: (data: { crm_lead_id: string; crm_client_id?: string; deal_name?: string }) =>
    api.post<DealRoomItem>("/deal-room/find-or-create", data),
};

export type DealRoomV2Stage =
  | "inquiry"
  | "qualification"
  | "quotation"
  | "negotiation"
  | "sample"
  | "contract"
  | "payment"
  | "closed_won"
  | "closed_lost";

export interface DealRoomV2Overview {
  total_deal_rooms: number;
  active_deal_rooms: number;
  readiness_score: number;
  average_health_score: number;
  total_pipeline_value: number;
  weighted_pipeline_value: number;
  high_risk_deals: number;
  integrations: Record<string, string>;
  safety_notice: string;
}

export interface DealRoomV2Workspace {
  id: string;
  deal_name: string;
  crm_client_id: string;
  client_name?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  deal_overview?: {
    deal_health_score: number;
    deal_value: number;
    expected_revenue: number;
    close_probability: number;
    estimated_close_date?: string | null;
    deal_owner?: string | null;
    currency: string;
    current_stage: string;
    current_stage_label: string;
  };
  pipeline?: {
    current_stage: string;
    current_stage_label: string;
    stages: Array<{
      stage: string;
      label: string;
      status: string;
      probability: number;
    }>;
  };
  buyer_information?: {
    linked_buyer_profile_id?: string | null;
    company_name?: string | null;
    contact_name?: string | null;
    country?: string | null;
    industry?: string | null;
    relationship_strength: string;
    acquisition_source: string;
    lead_id?: string | null;
    match_score?: number | null;
    email?: string | null;
    phone?: string | null;
  };
  revenue_integration?: {
    expected_revenue: number;
    weighted_revenue: number;
    revenue_forecast_impact: string;
    pipeline_contribution: number;
    deal_value: number;
    close_probability: number;
    currency: string;
  };
  risk_assessment?: {
    commercial_risk: number;
    commercial_risk_level: string;
    payment_risk: number;
    payment_risk_level: string;
    logistics_risk: number;
    logistics_risk_level: string;
    compliance_risk: number;
    compliance_risk_level: string;
    overall_risk_score: number;
    overall_risk_level: string;
    deal_health_score: number;
    deal_risk_classification: string;
    risk_factors: string[];
  };
  documents?: {
    items: Array<{
      id: string;
      category: string;
      title: string;
      status: string;
      document_type?: string;
      amount?: number;
      updated_at?: string;
    }>;
    quotation_count: number;
    contract_count: number;
    certificate_count: number;
    shipping_count: number;
    payment_count: number;
  };
  activity_timeline?: {
    items: Array<{
      id: string;
      event_type: string;
      category: string;
      title: string;
      description: string;
      occurred_at?: string;
    }>;
  };
  integrations?: Record<string, string>;
  guided_actions?: Array<{ action_id: string; title: string; description: string; route: string }>;
  safety_notice: string;
  errors?: string[];
}

export interface DealRoomV2ListItem extends DealRoomItem {
  v2_stage: string;
  v2_stage_label: string;
  deal_value: number;
  close_probability: number;
}

export interface DealRoomV2SummaryWidget {
  readiness_score: number;
  total_deal_rooms: number;
  active_deal_rooms: number;
  total_pipeline_value: number;
  weighted_pipeline_value: number;
  average_health_score: number;
  high_risk_deals: number;
  top_deal?: {
    deal_room_id: string;
    deal_name: string;
    stage: string;
    deal_value: number;
    close_probability: number;
  } | null;
  currency: string;
  safety_notice: string;
}

export const dealRoomV2Api = {
  overview: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<DealRoomV2Overview>("/deal-room/v2/overview", { params }),
  workspaces: (params?: { crm_client_id?: string; status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: DealRoomV2ListItem[]; total: number }>("/deal-room/v2/workspaces", { params }),
  workspace: (id: string) => api.get<DealRoomV2Workspace>(`/deal-room/v2/workspace/${id}`),
  summaryWidget: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<DealRoomV2SummaryWidget>("/deal-room/v2/summary-widget", { params }),
  dealAcquisitionPanel: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      active_deal_rooms: number;
      total_pipeline_value: number;
      deals: Array<{
        deal_room_id: string;
        deal_name: string;
        buyer_company?: string;
        acquisition_source?: string;
        relationship_strength?: string;
        match_score?: number;
        stage: string;
      }>;
      message: string;
      safety_notice: string;
    }>("/deal-room/v2/deal-acquisition-panel", { params }),
  dealRevenuePanel: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      readiness_score: number;
      total_pipeline_value: number;
      weighted_pipeline_value: number;
      active_deal_rooms: number;
      deals: Array<{
        deal_room_id: string;
        deal_name: string;
        deal_value: number;
        expected_revenue: number;
        weighted_revenue: number;
        pipeline_contribution: number;
        forecast_impact: string;
        stage: string;
      }>;
      message: string;
      currency: string;
      safety_notice: string;
    }>("/deal-room/v2/deal-revenue-panel", { params }),
  refresh: (params?: { client_id?: string; tenant_id?: string }) =>
    api.post<{
      refreshed_at: string;
      readiness_score: number;
      active_deal_rooms: number;
      total_pipeline_value: number;
      safety_notice: string;
    }>("/deal-room/v2/refresh", null, { params }),
};

export const salesManagerApi = {
  overview: (clientId?: string) =>
    api.get<SalesManagerOverview>("/sales-manager/overview", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  opportunities: (params?: { client_id?: string; limit?: number }) =>
    api.get<{ items: SalesManagerOpportunity[]; total: number }>(
      "/sales-manager/opportunities",
      { params },
    ),
  risks: (params?: { client_id?: string; limit?: number }) =>
    api.get<{ items: SalesManagerRisk[]; total: number }>("/sales-manager/risks", { params }),
  recommendations: (params?: { client_id?: string; limit?: number }) =>
    api.get<{ items: SalesManagerRecommendation[]; total: number }>(
      "/sales-manager/recommendations",
      { params },
    ),
  generateBriefing: (useAi = false, clientId?: string) =>
    api.post<SalesManagerBriefing>("/sales-manager/generate-briefing", {
      use_ai: useAi,
      client_id: clientId ?? undefined,
    }),
};

export type LeadClassification = "hot" | "qualified" | "nurturing" | "cold" | "inactive";
export type LeadUrgencyLevel = "urgent" | "high" | "medium" | "low";

export interface LeadClassificationOverview {
  hot_leads: number;
  qualified_leads: number;
  nurturing_leads: number;
  cold_leads: number;
  inactive_leads: number;
  total_classified: number;
  errors?: string[];
}

export interface LeadClassificationListItem {
  lead_id: string;
  name: string;
  company?: string | null;
  score: number;
  classification: LeadClassification;
  last_activity_at?: string | null;
  recommended_action: string;
  status: string;
  client_id: string;
}

export interface LeadIntelligenceRecommendations {
  next_recommended_action: string;
  follow_up_recommendation?: string | null;
  proposal_recommendation?: string | null;
  urgency_level: LeadUrgencyLevel;
}

export interface LeadClassificationDetail {
  lead_id: string;
  name: string;
  company?: string | null;
  status: string;
  client_id: string;
  classification: LeadClassification;
  score: number;
  reasons: string[];
  recommendations: LeadIntelligenceRecommendations;
  linked_crm: CrmLead;
  linked_threads: Array<{
    thread_id: string;
    channel?: string | null;
    title?: string | null;
    status?: string | null;
    message_count: number;
  }>;
  linked_proposals: Array<{
    proposal_id: string;
    title: string;
    status: string;
    updated_at?: string | null;
  }>;
  last_activity_at?: string | null;
}

export const leadIntelligenceApi = {
  overview: (clientId?: string) =>
    api.get<LeadClassificationOverview>("/lead-intelligence/overview", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  leads: (params?: {
    client_id?: string;
    classification?: LeadClassification;
    min_score?: number;
    max_score?: number;
    activity?: "active" | "stale" | "inactive" | "all";
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: LeadClassificationListItem[]; total: number }>(
      "/lead-intelligence/leads",
      { params },
    ),
  detail: (leadId: string) =>
    api.get<LeadClassificationDetail>(`/lead-intelligence/${leadId}`),
  classify: (body?: { lead_ids?: string[]; client_id?: string }) =>
    api.post<{ items: LeadClassificationDetail[]; classified: number }>(
      "/lead-intelligence/classify",
      body ?? {},
    ),
  recalculate: (body?: { client_id?: string; limit?: number }) =>
    api.post<{
      classified: number;
      overview: LeadClassificationOverview;
      message: string;
    }>("/lead-intelligence/recalculate", body ?? {}),
};

export type BuyerClassification =
  | "hot_buyer"
  | "strategic_buyer"
  | "high_potential_buyer"
  | "active_buyer"
  | "inactive_buyer"
  | "price_sensitive_buyer"
  | "at_risk_buyer";

export type BuyerRiskLevel = "low" | "medium" | "high" | "critical";

export interface BuyerIntelligenceOverview {
  hot_buyers: number;
  strategic_buyers: number;
  high_potential_buyers: number;
  active_buyers: number;
  inactive_buyers: number;
  price_sensitive_buyers: number;
  at_risk_buyers: number;
  total_buyers: number;
  average_buyer_score: number;
  errors: string[];
  safety_notice: string;
}

export interface BuyerListItem {
  buyer_id: string;
  name: string;
  company?: string | null;
  country?: string | null;
  industry?: string | null;
  buyer_score: number;
  classification: BuyerClassification;
  annual_potential: number | string;
  risk_level: BuyerRiskLevel;
  status: string;
  client_id: string;
}

export interface BuyerPotential {
  expected_annual_revenue: number | string;
  expected_deal_size: number | string;
  growth_potential: string;
  currency: string;
}

export interface BuyerIntelligenceDetail {
  buyer_id: string;
  name: string;
  company?: string | null;
  country?: string | null;
  industry?: string | null;
  status: string;
  client_id: string;
  buyer_score: number;
  classification: BuyerClassification;
  risk_level: BuyerRiskLevel;
  potential: BuyerPotential;
  insights: string[];
  recommendations: string[];
  risks: string[];
  linked_deals: Array<{
    deal_id: string;
    title: string;
    status: string;
    expected_value?: number | string | null;
    updated_at?: string | null;
  }>;
  linked_proposals: Array<{
    proposal_id: string;
    title: string;
    status: string;
    updated_at?: string | null;
  }>;
  linked_communications: Array<{
    thread_id: string;
    channel?: string | null;
    title?: string | null;
    message_count: number;
  }>;
  last_activity_at?: string | null;
}

export interface BuyerRankingItem {
  rank: number;
  buyer_id: string;
  name: string;
  company?: string | null;
  buyer_score: number;
  classification: BuyerClassification;
  annual_potential: number | string;
  metric_label: string;
}

export interface BuyerRiskItem {
  buyer_id: string;
  name: string;
  company?: string | null;
  risk_level: BuyerRiskLevel;
  classification: BuyerClassification;
  buyer_score: number;
  title: string;
  description: string;
  risk_signals: string[];
}

export interface BuyerIntelligenceSummaryWidget {
  hot_buyers: number;
  strategic_buyers: number;
  high_potential_buyers: number;
  at_risk_buyers: number;
  average_buyer_score: number;
  top_buyer_name?: string | null;
  top_buyer_score: number;
  errors: string[];
}

export type BuyerDiscoveryCategory =
  | "high_potential"
  | "strategic"
  | "active"
  | "new"
  | "watchlist";

export type BuyerDiscoveryPipelineStage =
  | "discovered"
  | "researched"
  | "qualified"
  | "contacted"
  | "opportunity"
  | "customer";

export interface BuyerDiscoveryOverview {
  total_buyers: number;
  high_potential: number;
  strategic: number;
  active: number;
  new_buyers: number;
  watchlist: number;
  average_opportunity_score: number;
  pipeline_discovered: number;
  pipeline_researched: number;
  pipeline_qualified: number;
  pipeline_contacted: number;
  pipeline_opportunity: number;
  pipeline_customer: number;
  integration_checks: Array<{
    module: string;
    status: string;
    message: string;
    details?: Record<string, unknown>;
  }>;
  errors: string[];
  safety_notice: string;
}

export interface BuyerDiscoverySummaryWidget {
  total_buyers: number;
  high_potential: number;
  strategic: number;
  new_buyers: number;
  watchlist: number;
  average_opportunity_score: number;
  pipeline_opportunity: number;
  top_buyer_name?: string | null;
  top_buyer_score: number;
  errors: string[];
}

export interface BuyerDiscoveryExecutiveInsights {
  overview: BuyerDiscoveryOverview;
  best_markets: Array<{ label: string; count: number; share_pct: number }>;
  top_industries: Array<{ label: string; count: number; share_pct: number }>;
  highest_potential_buyers: BuyerDiscoveryRankingItem[];
  acquisition_opportunities: BuyerDiscoveryRankingItem[];
  strategic_buyers: BuyerDiscoveryRankingItem[];
  safety_notice: string;
}

export interface BuyerRegistryItem {
  id: string;
  company_name: string;
  country?: string | null;
  city?: string | null;
  industry?: string | null;
  website?: string | null;
  contact_status: string;
  source: string;
  discovered_at: string;
  opportunity_score: number;
  category: BuyerDiscoveryCategory;
  pipeline_stage: BuyerDiscoveryPipelineStage;
  crm_lead_id?: string | null;
  client_id: string;
}

export interface BuyerDiscoveryRankingItem {
  rank: number;
  buyer_id: string;
  company_name: string;
  country?: string | null;
  industry?: string | null;
  opportunity_score: number;
  category: BuyerDiscoveryCategory;
  pipeline_stage: BuyerDiscoveryPipelineStage;
  metric_label: string;
}

export type MarketplaceOpportunityType =
  | "distributor"
  | "importer"
  | "wholesaler"
  | "retailer"
  | "project"
  | "partnership"
  | "rfq";

export type MarketplaceOpportunityStatus = "open" | "in_review" | "claimed" | "closed";

export type MarketplaceVisibility = "public" | "private" | "tenant_only";

export interface MarketplaceOverview {
  total_opportunities: number;
  open_opportunities: number;
  in_review: number;
  claimed: number;
  closed: number;
  total_views: number;
  total_interests: number;
  total_claims: number;
  average_estimated_value: number;
  integration_checks: Array<{
    module: string;
    status: string;
    message: string;
    details?: Record<string, unknown>;
  }>;
  errors: string[];
  safety_notice: string;
}

export interface MarketplaceOpportunityItem {
  id: string;
  title: string;
  description?: string | null;
  buyer_company: string;
  country?: string | null;
  industry?: string | null;
  opportunity_type: MarketplaceOpportunityType;
  estimated_value?: number | string | null;
  status: MarketplaceOpportunityStatus;
  visibility: MarketplaceVisibility;
  created_by_tenant?: string | null;
  rank_score: number;
  view_count: number;
  interest_count: number;
  claim_count: number;
  created_at: string;
  updated_at: string;
}

export interface MarketplaceRankingItem {
  rank: number;
  opportunity_id: string;
  title: string;
  buyer_company: string;
  country?: string | null;
  industry?: string | null;
  opportunity_type: MarketplaceOpportunityType;
  estimated_value?: number | string | null;
  rank_score: number;
  metric_label: string;
}

export interface MarketplaceSummaryWidget {
  total_opportunities: number;
  open_opportunities: number;
  total_interests: number;
  top_opportunity_title?: string | null;
  top_opportunity_value: number;
  errors: string[];
}

export interface MarketplaceExecutiveSummary {
  overview: MarketplaceOverview;
  best_opportunities: MarketplaceRankingItem[];
  strategic_opportunities: MarketplaceRankingItem[];
  top_industries: Array<{ label: string; count: number; share_pct: number }>;
  safety_notice: string;
}

export const marketplaceApi = {
  overview: (params?: { tenant_id?: string }) =>
    api.get<MarketplaceOverview>("/marketplace/overview", { params }),
  opportunities: (params?: {
    country?: string;
    industry?: string;
    opportunity_type?: MarketplaceOpportunityType;
    min_value?: number;
    max_value?: number;
    status?: MarketplaceOpportunityStatus;
    tenant_id?: string;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: MarketplaceOpportunityItem[]; total: number }>(
      "/marketplace/opportunities",
      { params },
    ),
  topOpportunities: (params?: { tenant_id?: string; limit?: number }) =>
    api.get<{
      best_opportunities: MarketplaceRankingItem[];
      newest_opportunities: MarketplaceRankingItem[];
      strategic_opportunities: MarketplaceRankingItem[];
      errors: string[];
    }>("/marketplace/top-opportunities", { params }),
  insights: (params?: { tenant_id?: string }) =>
    api.get<{
      top_industries: Array<{ label: string; count: number; share_pct: number }>;
      top_countries: Array<{ label: string; count: number; share_pct: number }>;
      most_active_tenants: Array<{
        tenant_id: string;
        tenant_name: string;
        activity_count: number;
      }>;
      most_valuable_opportunities: MarketplaceRankingItem[];
      total_opportunities: number;
      errors: string[];
    }>("/marketplace/insights", { params }),
  activity: (params?: { limit?: number }) =>
    api.get<{
      items: Array<{
        id: string;
        activity_type: "view" | "interest" | "claim" | "created";
        opportunity_id: string;
        opportunity_title: string;
        tenant_id?: string | null;
        tenant_label?: string | null;
        occurred_at: string;
        detail?: string | null;
      }>;
      total: number;
      errors: string[];
    }>("/marketplace/activity", { params }),
  createOpportunity: (body: {
    title: string;
    buyer_company: string;
    description?: string;
    country?: string;
    industry?: string;
    opportunity_type?: MarketplaceOpportunityType;
    estimated_value?: number;
    visibility?: MarketplaceVisibility;
    created_by_tenant?: string;
  }) =>
    api.post<{
      opportunity: MarketplaceOpportunityItem;
      message: string;
      errors: string[];
    }>("/marketplace/create-opportunity", body),
  expressInterest: (body: { opportunity_id: string; tenant_id: string; note?: string }) =>
    api.post<{ recorded: boolean; message: string; errors: string[] }>(
      "/marketplace/express-interest",
      body,
    ),
  claimOpportunity: (body: { opportunity_id: string; tenant_id: string }) =>
    api.post<{
      claimed: boolean;
      opportunity?: MarketplaceOpportunityItem | null;
      message: string;
      errors: string[];
    }>("/marketplace/claim-opportunity", body),
};

export const buyerDiscoveryApi = {
  overview: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<BuyerDiscoveryOverview>("/buyer-discovery/overview", { params }),
  buyers: (params?: {
    client_id?: string;
    tenant_id?: string;
    category?: BuyerDiscoveryCategory;
    pipeline_stage?: BuyerDiscoveryPipelineStage;
    min_score?: number;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: BuyerRegistryItem[]; total: number }>("/buyer-discovery/buyers", { params }),
  topOpportunities: (params?: { client_id?: string; tenant_id?: string; limit?: number }) =>
    api.get<{
      top_buyers: BuyerDiscoveryRankingItem[];
      fastest_growing: BuyerDiscoveryRankingItem[];
      highest_opportunity: BuyerDiscoveryRankingItem[];
      strategic_buyers: BuyerDiscoveryRankingItem[];
      errors: string[];
    }>("/buyer-discovery/top-opportunities", { params }),
  marketInsights: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      top_countries: Array<{ label: string; count: number; share_pct: number }>;
      top_industries: Array<{ label: string; count: number; share_pct: number }>;
      top_buyer_segments: Array<{ label: string; count: number; share_pct: number }>;
      total_buyers: number;
      errors: string[];
    }>("/buyer-discovery/market-insights", { params }),
  pipeline: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      stages: Array<{ stage: BuyerDiscoveryPipelineStage; count: number; label: string }>;
      total: number;
      errors: string[];
    }>("/buyer-discovery/pipeline", { params }),
  summaryWidget: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<BuyerDiscoverySummaryWidget>("/buyer-discovery/summary-widget", { params }),
  executiveInsights: (params?: { client_id?: string; tenant_id?: string; limit?: number }) =>
    api.get<BuyerDiscoveryExecutiveInsights>("/buyer-discovery/executive-insights", { params }),
  recalculate: (body?: { client_id?: string; tenant_id?: string; limit?: number }) =>
    api.post<{
      synced: number;
      recalculated: number;
      overview: BuyerDiscoveryOverview;
      message: string;
      errors: string[];
    }>("/buyer-discovery/recalculate", body ?? {}),
};

export type BuyerNetworkClassification =
  | "strategic"
  | "high_potential"
  | "active"
  | "growing"
  | "watchlist"
  | "underutilized";

export type BuyerNetworkStatus =
  | "strategic"
  | "active"
  | "growing"
  | "watchlist"
  | "underutilized";

export type BuyerRelationshipType =
  | "discovered"
  | "contacted"
  | "active"
  | "customer"
  | "strategic";

export interface BuyerNetworkOverview {
  total_profiles: number;
  total_relationships: number;
  strategic_buyers: number;
  high_potential: number;
  active_buyers: number;
  underutilized: number;
  average_opportunity_score: number;
  average_network_strength: number;
  tenants_connected: number;
  integration_checks: Array<{
    module: string;
    status: string;
    message: string;
    details?: Record<string, unknown>;
  }>;
  errors: string[];
  safety_notice: string;
}

export interface BuyerNetworkProfileItem {
  id: string;
  company_name: string;
  country?: string | null;
  city?: string | null;
  industry?: string | null;
  website?: string | null;
  classification: BuyerNetworkClassification;
  opportunity_score: number;
  network_strength: number;
  buyer_status: BuyerNetworkStatus;
  relationship_count: number;
  created_at: string;
  updated_at: string;
}

export interface BuyerRelationshipItem {
  id: string;
  buyer_id: string;
  tenant_id: string;
  tenant_name?: string | null;
  company_name: string;
  relationship_type: BuyerRelationshipType;
  relationship_strength: number;
  country?: string | null;
  industry?: string | null;
  opportunity_score: number;
  created_at: string;
}

export interface BuyerNetworkInsightItem {
  rank: number;
  buyer_id: string;
  company_name: string;
  country?: string | null;
  industry?: string | null;
  opportunity_score: number;
  network_strength: number;
  buyer_status: BuyerNetworkStatus;
  metric_label: string;
}

export interface BuyerNetworkExecutiveSummary {
  overview: BuyerNetworkOverview;
  strongest_buyers: BuyerNetworkInsightItem[];
  strategic_buyers: BuyerNetworkInsightItem[];
  top_countries: Array<{ label: string; count: number; share_pct: number }>;
  safety_notice: string;
}

export interface BuyerNetworkSummaryWidget {
  total_profiles: number;
  strategic_buyers: number;
  active_buyers: number;
  underutilized: number;
  average_network_strength: number;
  top_buyer_name?: string | null;
  top_buyer_score: number;
  errors: string[];
}

export const buyerNetworkApi = {
  overview: (params?: { tenant_id?: string }) =>
    api.get<BuyerNetworkOverview>("/buyer-network/overview", { params }),
  profiles: (params?: {
    country?: string;
    industry?: string;
    classification?: BuyerNetworkClassification;
    buyer_status?: BuyerNetworkStatus;
    tenant_id?: string;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: BuyerNetworkProfileItem[]; total: number }>(
      "/buyer-network/profiles",
      { params },
    ),
  relationships: (params?: {
    tenant_id?: string;
    buyer_id?: string;
    relationship_type?: BuyerRelationshipType;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: BuyerRelationshipItem[]; total: number }>(
      "/buyer-network/relationships",
      { params },
    ),
  graph: (params?: { buyer_id?: string; limit?: number }) =>
    api.get<{
      focus_buyer_id?: string | null;
      related_buyers: Array<{
        buyer_id: string;
        company_name: string;
        country?: string | null;
        industry?: string | null;
        opportunity_score: number;
        network_strength: number;
        link_reason: string;
      }>;
      related_industries: Array<{ label: string; count: number; share_pct: number }>;
      related_countries: Array<{ label: string; count: number; share_pct: number }>;
      errors: string[];
    }>("/buyer-network/graph", { params }),
  insights: (params?: { tenant_id?: string; limit?: number }) =>
    api.get<{
      strongest_buyers: BuyerNetworkInsightItem[];
      fastest_growing: BuyerNetworkInsightItem[];
      strategic_buyers: BuyerNetworkInsightItem[];
      underutilized_buyers: BuyerNetworkInsightItem[];
      errors: string[];
    }>("/buyer-network/insights", { params }),
  topBuyers: (params?: { tenant_id?: string; limit?: number }) =>
    api.get<{
      top_buyers: BuyerNetworkInsightItem[];
      by_network_strength: BuyerNetworkInsightItem[];
      by_opportunity: BuyerNetworkInsightItem[];
      errors: string[];
    }>("/buyer-network/top-buyers", { params }),
  summaryWidget: (params?: { tenant_id?: string }) =>
    api.get<BuyerNetworkSummaryWidget>("/buyer-network/summary-widget", { params }),
  executiveSummary: (params?: { tenant_id?: string; limit?: number }) =>
    api.get<BuyerNetworkExecutiveSummary>("/buyer-network/executive-summary", { params }),
  recalculate: (body?: { tenant_id?: string; limit?: number }) =>
    api.post<{
      profiles_synced: number;
      profiles_recalculated: number;
      relationships_recalculated: number;
      overview: BuyerNetworkOverview;
      message: string;
      errors: string[];
    }>("/buyer-network/recalculate", body ?? {}),
};

export type BuyerAcquisitionPipelineStage =
  | "discovered"
  | "researched"
  | "qualified"
  | "contacted"
  | "opportunity"
  | "customer";

export type BuyerAcquisitionOpportunitySource = "marketplace" | "discovery" | "network";

export interface BuyerAcquisitionOverview {
  total_buyers: number;
  strategic_buyers: number;
  high_potential_buyers: number;
  marketplace_opportunities: number;
  network_opportunities: number;
  discovery_buyers: number;
  network_profiles: number;
  intelligence_buyers: number;
  average_opportunity_score: number;
  average_buyer_score: number;
  average_network_strength: number;
  integration_checks: Array<{ module: string; status: string; message: string; details?: Record<string, unknown> }>;
  errors: string[];
  safety_notice: string;
}

export interface UnifiedBuyerProfile {
  unified_key: string;
  company_name: string;
  country?: string | null;
  city?: string | null;
  industry?: string | null;
  website?: string | null;
  opportunity_score: number;
  buyer_score: number;
  network_strength: number;
  relationship_status: string;
  pipeline_stage: BuyerAcquisitionPipelineStage;
  classification?: string | null;
  sources: string[];
  discovery_id?: string | null;
  network_id?: string | null;
  intelligence_id?: string | null;
  client_id?: string | null;
  discovered_at?: string | null;
}

export interface UnifiedOpportunityItem {
  opportunity_id: string;
  title: string;
  source: BuyerAcquisitionOpportunitySource;
  buyer_company?: string | null;
  country?: string | null;
  industry?: string | null;
  score: number;
  opportunity_type?: string | null;
  estimated_value?: number | null;
  status?: string | null;
  description?: string | null;
}

export interface BuyerAcquisitionInsightItem {
  rank: number;
  company_name: string;
  country?: string | null;
  industry?: string | null;
  score: number;
  buyer_score: number;
  network_strength: number;
  opportunity_score: number;
  relationship_status?: string | null;
  source?: string | null;
  buyer_id?: string | null;
}

export interface BuyerAcquisitionSummaryWidget {
  total_buyers: number;
  strategic_buyers: number;
  high_potential_buyers: number;
  marketplace_opportunities: number;
  network_opportunities: number;
  top_buyer_name?: string | null;
  top_buyer_score: number;
  errors: string[];
}

export interface BuyerAcquisitionExecutiveOverview {
  overview: BuyerAcquisitionOverview;
  top_buyers: BuyerAcquisitionInsightItem[];
  strongest_relationships: BuyerAcquisitionInsightItem[];
  highest_opportunity_buyers: BuyerAcquisitionInsightItem[];
  best_countries: Array<{ label: string; count: number; share_pct: number }>;
  best_industries: Array<{ label: string; count: number; share_pct: number }>;
  safety_notice: string;
}

export const buyerAcquisitionApi = {
  overview: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<BuyerAcquisitionOverview>("/buyer-acquisition/overview", { params }),
  buyers: (params?: {
    client_id?: string;
    tenant_id?: string;
    pipeline_stage?: BuyerAcquisitionPipelineStage;
    min_score?: number;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: UnifiedBuyerProfile[]; total: number; errors: string[] }>(
      "/buyer-acquisition/buyers",
      { params },
    ),
  opportunities: (params?: {
    client_id?: string;
    tenant_id?: string;
    source?: BuyerAcquisitionOpportunitySource;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{
      items: UnifiedOpportunityItem[];
      total: number;
      marketplace_count: number;
      discovery_count: number;
      network_count: number;
      errors: string[];
    }>("/buyer-acquisition/opportunities", { params }),
  pipeline: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      stages: Array<{ stage: BuyerAcquisitionPipelineStage; count: number; label: string }>;
      total: number;
      errors: string[];
    }>("/buyer-acquisition/pipeline", { params }),
  insights: (params?: { client_id?: string; tenant_id?: string; limit?: number }) =>
    api.get<{
      top_buyers: BuyerAcquisitionInsightItem[];
      strongest_relationships: BuyerAcquisitionInsightItem[];
      highest_opportunity_buyers: BuyerAcquisitionInsightItem[];
      best_countries: Array<{ label: string; count: number; share_pct: number }>;
      best_industries: Array<{ label: string; count: number; share_pct: number }>;
      errors: string[];
      safety_notice: string;
    }>("/buyer-acquisition/insights", { params }),
  summaryWidget: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<BuyerAcquisitionSummaryWidget>("/buyer-acquisition/summary-widget", { params }),
  factoryReadiness: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<FactoryReadinessIndicators>("/buyer-acquisition/factory-readiness", { params }),
};

export type BuyerEnginePipelineStatus =
  | "new"
  | "contacted"
  | "replied"
  | "negotiating"
  | "quotation_sent"
  | "sample_sent"
  | "won"
  | "lost";

export interface BuyerEngineBuyerRecord {
  buyer_id: string;
  company_name: string;
  country?: string | null;
  industry?: string | null;
  website?: string | null;
  email?: string | null;
  phone?: string | null;
  whatsapp?: string | null;
  wechat?: string | null;
  status: string;
  pipeline_status: BuyerEnginePipelineStatus;
  match_score: number;
  sources: string[];
  crm_lead_id?: string | null;
  discovery_id?: string | null;
  network_id?: string | null;
  client_id?: string | null;
}

export interface BuyerEngineMatchItem {
  buyer_id: string;
  company_name: string;
  country?: string | null;
  industry?: string | null;
  match_score: number;
  match_factors: Record<string, unknown>;
  pipeline_status: BuyerEnginePipelineStatus;
  recommended_action?: string | null;
}

export interface BuyerEngineOverview {
  total_buyers: number;
  database_buyers: number;
  matched_buyers: number;
  high_match_buyers: number;
  active_pipeline_leads: number;
  total_opportunities: number;
  average_match_score: number;
  readiness_score: number;
  factory_view: {
    top_buyers: BuyerEngineMatchItem[];
    best_matches: BuyerEngineMatchItem[];
    active_opportunities: number;
    lead_counts: Record<string, number>;
  };
  crm_summary: {
    total_leads: number;
    active_leads: number;
    won_deals: number;
    lost_deals: number;
    pipeline_value: number;
    average_match_score: number;
    safety_notice: string;
  };
  integration_checks: Array<{ module: string; status: string; message: string }>;
  guided_actions: Array<{
    key: string;
    title: string;
    description: string;
    route: string;
    enabled: boolean;
  }>;
  errors: string[];
  safety_notice: string;
}

export interface BuyerEngineSummaryWidget {
  readiness_score: number;
  total_buyers: number;
  matched_buyers: number;
  active_pipeline_leads: number;
  average_match_score: number;
  top_buyer_name?: string | null;
  top_buyer_score: number;
  safety_notice: string;
}

export interface BuyerEngineOpportunityItem {
  opportunity_id: string;
  opportunity_type: "buyer" | "country" | "industry";
  title: string;
  subtitle?: string | null;
  country?: string | null;
  industry?: string | null;
  buyer_company?: string | null;
  score: number;
  lead_count: number;
  estimated_value?: number | null;
  recommended_action?: string | null;
}

export const buyerAcquisitionEngineApi = {
  overview: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<BuyerEngineOverview>("/buyer-acquisition-engine/overview", { params }),
  buyers: (params?: {
    client_id?: string;
    tenant_id?: string;
    pipeline_status?: BuyerEnginePipelineStatus;
    min_match_score?: number;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: BuyerEngineBuyerRecord[]; total: number; errors: string[]; safety_notice: string }>(
      "/buyer-acquisition-engine/buyers",
      { params },
    ),
  matches: (params?: {
    client_id?: string;
    tenant_id?: string;
    min_score?: number;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{
      items: BuyerEngineMatchItem[];
      total: number;
      average_match_score: number;
      factory_industries: string[];
      factory_products: string[];
      export_markets: string[];
      errors: string[];
      safety_notice: string;
    }>("/buyer-acquisition-engine/matches", { params }),
  pipeline: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      stages: Array<{ status: BuyerEnginePipelineStatus; label: string; count: number }>;
      total: number;
      active_count: number;
      errors: string[];
      safety_notice: string;
    }>("/buyer-acquisition-engine/pipeline", { params }),
  opportunities: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      buyer_opportunities: BuyerEngineOpportunityItem[];
      country_opportunities: BuyerEngineOpportunityItem[];
      industry_opportunities: BuyerEngineOpportunityItem[];
      total: number;
      errors: string[];
      safety_notice: string;
    }>("/buyer-acquisition-engine/opportunities", { params }),
  summary: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<BuyerEngineOverview["crm_summary"]>("/buyer-acquisition-engine/summary", { params }),
  actions: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      items: BuyerEngineOverview["guided_actions"];
      safety_notice: string;
    }>("/buyer-acquisition-engine/actions", { params }),
  summaryWidget: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<BuyerEngineSummaryWidget>("/buyer-acquisition-engine/summary-widget", { params }),
  refresh: (params?: { client_id?: string; tenant_id?: string }) =>
    api.post<{
      refreshed_at: string;
      readiness_score: number;
      total_buyers: number;
      matched_buyers: number;
      active_pipeline_leads: number;
      safety_notice: string;
    }>("/buyer-acquisition-engine/refresh", null, { params }),
};

export type RevenueEngineDealStage =
  | "lead"
  | "qualified"
  | "negotiation"
  | "quotation"
  | "sample"
  | "contract"
  | "won"
  | "lost";

export type RevenueHealthStatus = "healthy" | "warning" | "critical";

export interface RevenueEngineDealRecord {
  deal_id: string;
  title: string;
  buyer_name?: string | null;
  buyer_company?: string | null;
  factory_id: string;
  factory_name?: string | null;
  value: number;
  currency: string;
  stage: RevenueEngineDealStage;
  stage_label: string;
  probability: number;
  expected_close_date?: string | null;
  lead_id?: string | null;
  crm_deal_status?: string | null;
  lead_status?: string | null;
  sources: string[];
}

export interface RevenueEngineOpportunityItem {
  opportunity_id: string;
  title: string;
  subtitle?: string | null;
  buyer_name?: string | null;
  factory_name?: string | null;
  value: number;
  stage?: RevenueEngineDealStage | null;
  probability: number;
  score: number;
  sources: string[];
  recommended_action?: string | null;
}

export interface RevenueEngineOverview {
  executive_dashboard: {
    total_pipeline_value: number;
    forecasted_revenue: number;
    won_revenue: number;
    lost_revenue: number;
    active_opportunities: number;
    deal_count: number;
    weighted_pipeline_value: number;
    currency: string;
  };
  forecast: {
    pipeline_value: number;
    weighted_pipeline_value: number;
    expected_revenue: number;
    won_revenue: number;
    lost_revenue: number;
    currency: string;
    forecast_quality: string;
    active_deals: number;
    won_deals: number;
    lost_deals: number;
    errors: string[];
    safety_notice: string;
  };
  pipeline: {
    stages: Array<{
      stage: RevenueEngineDealStage;
      label: string;
      count: number;
      value: number;
      weighted_value: number;
    }>;
    total_deals: number;
    active_deals: number;
    pipeline_value: number;
    weighted_pipeline_value: number;
    currency: string;
    errors: string[];
    safety_notice: string;
  };
  health: {
    status: RevenueHealthStatus;
    health_score: number;
    factors: Array<{
      key: string;
      label: string;
      status: RevenueHealthStatus;
      score: number;
      message: string;
    }>;
    pipeline_coverage_ratio: number;
    win_rate: number;
    active_deals: number;
    forecast_quality: string;
    errors: string[];
    safety_notice: string;
  };
  top_opportunities: RevenueEngineOpportunityItem[];
  factory_count: number;
  readiness_score: number;
  integration_checks: Array<{ module: string; status: string; message: string }>;
  guided_actions: Array<{
    key: string;
    title: string;
    description: string;
    route: string;
    enabled: boolean;
  }>;
  errors: string[];
  safety_notice: string;
}

export interface RevenueEngineSummaryWidget {
  readiness_score: number;
  health_status: RevenueHealthStatus;
  health_score: number;
  total_pipeline_value: number;
  forecasted_revenue: number;
  won_revenue: number;
  active_deals: number;
  deal_count: number;
  top_opportunity_title?: string | null;
  top_opportunity_value: number;
  currency: string;
  safety_notice: string;
}

export const revenueEngineApi = {
  overview: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<RevenueEngineOverview>("/revenue-engine/overview", { params }),
  deals: (params?: {
    client_id?: string;
    tenant_id?: string;
    stage?: RevenueEngineDealStage;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: RevenueEngineDealRecord[]; total: number; errors: string[]; safety_notice: string }>(
      "/revenue-engine/deals",
      { params },
    ),
  pipeline: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<RevenueEngineOverview["pipeline"]>("/revenue-engine/pipeline", { params }),
  forecast: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<RevenueEngineOverview["forecast"]>("/revenue-engine/forecast", { params }),
  factories: (params?: { client_id?: string; tenant_id?: string; skip?: number; limit?: number }) =>
    api.get<{
      items: Array<{
        factory_id: string;
        factory_name: string;
        tenant_id?: string | null;
        active_deals: number;
        won_deals: number;
        lost_deals: number;
        pipeline_value: number;
        weighted_pipeline_value: number;
        expected_revenue: number;
        won_revenue: number;
        average_deal_size: number;
        currency: string;
      }>;
      total: number;
      errors: string[];
      safety_notice: string;
    }>("/revenue-engine/factories", { params }),
  opportunities: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      top_revenue_opportunities: RevenueEngineOpportunityItem[];
      highest_value_buyers: RevenueEngineOpportunityItem[];
      highest_value_factories: RevenueEngineOpportunityItem[];
      total: number;
      errors: string[];
      safety_notice: string;
    }>("/revenue-engine/opportunities", { params }),
  health: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<RevenueEngineOverview["health"]>("/revenue-engine/health", { params }),
  summary: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      executive_dashboard: RevenueEngineOverview["executive_dashboard"];
      health_status: RevenueHealthStatus;
      health_score: number;
      readiness_score: number;
      forecast_quality: string;
      win_rate: number;
      active_deals: number;
      errors: string[];
      safety_notice: string;
    }>("/revenue-engine/summary", { params }),
  actions: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      items: RevenueEngineOverview["guided_actions"];
      safety_notice: string;
    }>("/revenue-engine/actions", { params }),
  summaryWidget: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<RevenueEngineSummaryWidget>("/revenue-engine/summary-widget", { params }),
  revenueImpactPanel: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      readiness_score: number;
      health_status: RevenueHealthStatus;
      total_pipeline_value: number;
      forecasted_revenue: number;
      won_revenue: number;
      active_deals: number;
      win_rate: number;
      top_opportunities: RevenueEngineOpportunityItem[];
      message: string;
      safety_notice: string;
    }>("/revenue-engine/revenue-impact-panel", { params }),
  revenueReadinessPanel: (params?: { tenant_id?: string }) =>
    api.get<{
      readiness_score: number;
      health_status: RevenueHealthStatus;
      health_score: number;
      total_pipeline_value: number;
      forecasted_revenue: number;
      active_deals: number;
      won_deals: number;
      forecast_quality: string;
      message: string;
      safety_notice: string;
    }>("/revenue-engine/revenue-readiness-panel", { params }),
  revenuePerformancePanel: (params?: { client_id?: string; tenant_id?: string }) =>
    api.get<{
      readiness_score: number;
      total_pipeline_value: number;
      forecasted_revenue: number;
      won_revenue: number;
      active_deals: number;
      factory_count: number;
      top_factory_name?: string | null;
      top_factory_pipeline: number;
      average_deal_size: number;
      currency: string;
      safety_notice: string;
    }>("/revenue-engine/revenue-performance-panel", { params }),
  refresh: (params?: { client_id?: string; tenant_id?: string }) =>
    api.post<{
      refreshed_at: string;
      readiness_score: number;
      health_status: RevenueHealthStatus;
      total_pipeline_value: number;
      forecasted_revenue: number;
      active_deals: number;
      safety_notice: string;
    }>("/revenue-engine/refresh", null, { params }),
};

export const buyerIntelligenceApi = {
  overview: (clientId?: string) =>
    api.get<BuyerIntelligenceOverview>("/buyer-intelligence/overview", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  buyers: (params?: {
    client_id?: string;
    classification?: BuyerClassification;
    min_score?: number;
    max_score?: number;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: BuyerListItem[]; total: number }>("/buyer-intelligence/buyers", { params }),
  detail: (buyerId: string) =>
    api.get<BuyerIntelligenceDetail>(`/buyer-intelligence/${buyerId}`),
  topBuyers: (params?: { client_id?: string; limit?: number }) =>
    api.get<{
      top_buyers: BuyerRankingItem[];
      fastest_growing: BuyerRankingItem[];
      highest_revenue: BuyerRankingItem[];
      errors: string[];
    }>("/buyer-intelligence/top-buyers", { params }),
  risks: (params?: { client_id?: string; limit?: number }) =>
    api.get<{
      items: BuyerRiskItem[];
      total: number;
      by_level: Record<string, number>;
      errors: string[];
    }>("/buyer-intelligence/risks", { params }),
  summaryWidget: (clientId?: string) =>
    api.get<BuyerIntelligenceSummaryWidget>("/buyer-intelligence/summary-widget", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  recalculate: (body?: { client_id?: string; limit?: number }) =>
    api.post<{
      evaluated: number;
      overview: BuyerIntelligenceOverview;
      message: string;
      errors: string[];
    }>("/buyer-intelligence/recalculate", body ?? {}),
};

export type DealRiskLevel =
  | "healthy"
  | "watchlist"
  | "at_risk"
  | "critical"
  | "stalled"
  | "lost_probability_high";

export interface DealRiskOverview {
  healthy_deals: number;
  watchlist_deals: number;
  at_risk_deals: number;
  critical_deals: number;
  stalled_deals: number;
  lost_probability_high_deals: number;
  high_close_probability_deals: number;
  total_deals: number;
  average_health_score: number;
  total_at_risk_revenue: number | string;
  errors: string[];
  safety_notice: string;
}

export interface DealRiskListItem {
  deal_id: string;
  title: string;
  buyer_name?: string | null;
  buyer_company?: string | null;
  lead_id: string;
  client_id: string;
  status: string;
  deal_health_score: number;
  risk_level: DealRiskLevel;
  close_probability: number;
  expected_close_date?: string | null;
  revenue: number | string;
  currency: string;
}

export interface DealRiskDetail {
  deal_id: string;
  title: string;
  status: string;
  client_id: string;
  lead_id: string;
  buyer_name?: string | null;
  buyer_company?: string | null;
  expected_value?: number | string | null;
  currency: string;
  deal_health_score: number;
  risk_level: DealRiskLevel;
  close_probability: number;
  expected_close_date?: string | null;
  confidence_level: string;
  risk_reasons: string[];
  recommendations: string[];
  risk_factors: string[];
  linked_buyer_intelligence?: {
    buyer_id: string;
    name: string;
    company?: string | null;
    buyer_score: number;
    classification?: string | null;
    risk_level?: string | null;
  } | null;
  linked_communications: {
    thread_id: string;
    channel?: string | null;
    title?: string | null;
    message_count: number;
  }[];
  linked_proposals: {
    proposal_id: string;
    title: string;
    status: string;
    updated_at?: string | null;
  }[];
  linked_tasks: {
    task_id: string;
    title: string;
    status: string;
    priority: string;
    due_at?: string | null;
    is_overdue: boolean;
  }[];
  last_activity_at?: string | null;
}

export interface DealRiskSummaryWidget {
  healthy_deals: number;
  at_risk_deals: number;
  critical_deals: number;
  high_close_probability_deals: number;
  average_health_score: number;
  total_at_risk_revenue: number | string;
  top_risk_deal_title?: string | null;
  errors: string[];
}

export const dealRiskApi = {
  overview: (clientId?: string) =>
    api.get<DealRiskOverview>("/deal-risk/overview", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  deals: (params?: {
    client_id?: string;
    risk_level?: DealRiskLevel;
    min_health?: number;
    max_health?: number;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: DealRiskListItem[]; total: number }>("/deal-risk/deals", { params }),
  detail: (dealId: string) => api.get<DealRiskDetail>(`/deal-risk/${dealId}`),
  highRisk: (params?: { client_id?: string; limit?: number }) =>
    api.get<{
      items: {
        rank: number;
        deal_id: string;
        title: string;
        buyer_name?: string | null;
        deal_health_score: number;
        risk_level: DealRiskLevel;
        close_probability: number;
        revenue: number | string;
        risk_reasons: string[];
      }[];
      total: number;
      largest_at_risk_revenue: number | string;
      requiring_intervention: number;
      errors: string[];
    }>("/deal-risk/high-risk", { params }),
  opportunities: (params?: { client_id?: string; limit?: number }) =>
    api.get<{
      items: {
        rank: number;
        deal_id: string;
        title: string;
        buyer_name?: string | null;
        close_probability: number;
        expected_close_date?: string | null;
        revenue: number | string;
        deal_health_score: number;
      }[];
      likely_close_this_month: number;
      total: number;
      errors: string[];
    }>("/deal-risk/opportunities", { params }),
  summaryWidget: (clientId?: string) =>
    api.get<DealRiskSummaryWidget>("/deal-risk/summary-widget", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  recalculate: (body?: { client_id?: string; limit?: number }) =>
    api.post<{
      evaluated: number;
      overview: DealRiskOverview;
      message: string;
      errors: string[];
    }>("/deal-risk/recalculate", body ?? {}),
};

export type ConversationClassification =
  | "inquiry"
  | "qualification"
  | "negotiation"
  | "proposal"
  | "closing"
  | "inactive";

/** @deprecated use ConversationClassification */
export type CommunicationClassification = ConversationClassification;

export type CommunicationUrgency = "urgent" | "high" | "medium" | "low";

export interface CommunicationIntelligenceResult {
  health_score: number;
  classification: ConversationClassification;
  urgency: CommunicationUrgency;
  insights: string[];
  recommended_actions: string[];
}

export interface CommunicationIntelligenceOverview {
  active_buyers: number;
  hot_buyers: number;
  negotiations: number;
  follow_ups_required: number;
  inactive_conversations: number;
  total_analyzed: number;
  errors?: string[];
}

export interface CommunicationIntelligenceListItem {
  conversation_id: string;
  source: "thread" | "whatsapp";
  source_id: string;
  contact_name: string;
  channel: string;
  health_score: number;
  classification: ConversationClassification;
  urgency: CommunicationUrgency;
  recommended_action: string;
  last_message_at?: string | null;
  lead_id?: string | null;
  deal_id?: string | null;
  client_id?: string | null;
  status: string;
}

export interface CommunicationIntelligenceDetail {
  conversation_id: string;
  source: "thread" | "whatsapp";
  source_id: string;
  contact_name: string;
  channel: string;
  status: string;
  intelligence: CommunicationIntelligenceResult;
  linked_crm: {
    lead_id?: string | null;
    lead_name?: string | null;
    lead_status?: string | null;
    deal_id?: string | null;
    deal_title?: string | null;
    client_id?: string | null;
  };
  linked_deal_room?: { deal_room_id: string; deal_name: string } | null;
  linked_proposals: Array<{
    proposal_id: string;
    title: string;
    status: string;
    updated_at?: string | null;
  }>;
  last_message_at?: string | null;
  message_count: number;
}

export const communicationIntelligenceApi = {
  overview: (clientId?: string) =>
    api.get<CommunicationIntelligenceOverview>("/communication-intelligence/overview", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  conversations: (params?: {
    client_id?: string;
    channel?: string;
    classification?: ConversationClassification;
    urgency?: CommunicationUrgency;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: CommunicationIntelligenceListItem[]; total: number }>(
      "/communication-intelligence/conversations",
      { params },
    ),
  detail: (conversationId: string) =>
    api.get<CommunicationIntelligenceDetail>(
      `/communication-intelligence/conversations/${encodeURIComponent(conversationId)}`,
    ),
  analyze: (body?: { conversation_ids?: string[]; client_id?: string }) =>
    api.post<{ items: CommunicationIntelligenceDetail[]; analyzed: number }>(
      "/communication-intelligence/analyze",
      body ?? {},
    ),
  recalculate: (body?: { client_id?: string; limit?: number }) =>
    api.post<{
      analyzed: number;
      overview: CommunicationIntelligenceOverview;
      message: string;
    }>("/communication-intelligence/recalculate", body ?? {}),
};

export interface RevenueAttributionObject {
  source: string;
  label: string;
  revenue: number | string;
  deals: number;
  conversion_rate: number;
  avg_deal_size: number | string;
}

export interface RevenueAttributionChannelObject {
  channel: string;
  label: string;
  revenue: number | string;
  deals: number;
  conversion_rate: number;
  avg_deal_size: number | string;
}

export interface RevenueAttributionOverview {
  total_revenue: number | string;
  deals_won: number;
  avg_deal_size: number | string;
  conversion_rate: number;
  proposal_conversion_rate: number;
  total_leads: number;
  currency: string;
  recalculated_at?: string | null;
  errors?: string[];
}

export interface RevenueAttributionConversionRow {
  metric: string;
  label: string;
  numerator: number;
  denominator: number;
  rate: number;
}

export interface RevenueAttributionInsightItem {
  key: string;
  label: string;
  value: string;
  metric?: string | null;
  revenue?: number | string | null;
  conversion_rate?: number | null;
}

export interface RevenueAttributionInsights {
  best_source?: RevenueAttributionInsightItem | null;
  best_channel?: RevenueAttributionInsightItem | null;
  best_proposal_source?: RevenueAttributionInsightItem | null;
  weakest_source?: RevenueAttributionInsightItem | null;
  summary: string;
  errors?: string[];
}

export interface RevenueAttributionLeadSummary {
  lead_id: string;
  source: string;
  source_label: string;
  channel: string;
  channel_label: string;
  campaign?: string | null;
  attribution_link_id?: string | null;
  won_revenue?: number | string | null;
  deal_count: number;
}

export interface RevenueAttributionSummaryWidget {
  total_revenue: number | string;
  deals_won: number;
  conversion_rate: number;
  best_source?: string | null;
  best_source_label?: string | null;
  best_channel?: string | null;
  best_channel_label?: string | null;
}

export const revenueAttributionApi = {
  overview: (clientId?: string) =>
    api.get<RevenueAttributionOverview>("/revenue-attribution/overview", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  sources: (clientId?: string) =>
    api.get<{ items: RevenueAttributionObject[]; total: number; errors?: string[] }>(
      "/revenue-attribution/sources",
      { params: clientId ? { client_id: clientId } : undefined },
    ),
  channels: (clientId?: string) =>
    api.get<{ items: RevenueAttributionChannelObject[]; total: number; errors?: string[] }>(
      "/revenue-attribution/channels",
      { params: clientId ? { client_id: clientId } : undefined },
    ),
  conversions: (clientId?: string) =>
    api.get<{
      items: RevenueAttributionConversionRow[];
      proposal_conversion_rate: number;
      errors?: string[];
    }>("/revenue-attribution/conversions", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  insights: (clientId?: string) =>
    api.get<RevenueAttributionInsights>("/revenue-attribution/insights", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  summaryWidget: (clientId?: string) =>
    api.get<RevenueAttributionSummaryWidget>("/revenue-attribution/summary-widget", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  lead: (leadId: string) =>
    api.get<RevenueAttributionLeadSummary>(`/revenue-attribution/lead/${leadId}`),
  recalculate: (body?: { client_id?: string }) =>
    api.post<{
      overview: RevenueAttributionOverview;
      sources_count: number;
      channels_count: number;
      message: string;
    }>("/revenue-attribution/recalculate", body ?? {}),
};

export type WorkflowType =
  | "follow_up_workflow"
  | "proposal_workflow"
  | "re_engagement_workflow"
  | "crm_cleanup_workflow"
  | "hot_lead_workflow";

export type WorkflowActionType =
  | "create_task"
  | "schedule_follow_up"
  | "review_proposal"
  | "review_lead"
  | "link_crm"
  | "update_next_action";

export type WorkflowPriority = "urgent" | "high" | "medium" | "low";

export interface WorkflowAction {
  action: WorkflowActionType;
  label: string;
  description: string;
}

export interface WorkflowTemplate {
  workflow_type: WorkflowType;
  name: string;
  description: string;
  typical_actions: WorkflowActionType[];
}

export interface WorkflowRecommendation {
  id: string;
  client_id?: string | null;
  client_name?: string | null;
  lead_id?: string | null;
  lead_name?: string | null;
  deal_id?: string | null;
  proposal_id?: string | null;
  conversation_id?: string | null;
  channel?: string | null;
  workflow_type: WorkflowType;
  detection_type: string;
  priority: WorkflowPriority;
  title: string;
  reason: string;
  recommended_actions: WorkflowAction[];
  status: "open" | "dismissed" | "completed";
  linked_task_id?: string | null;
  entity_type?: string | null;
  entity_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowOverview {
  active_recommendations: number;
  high_priority: number;
  follow_up_workflows: number;
  proposal_workflows: number;
  crm_cleanup_workflows: number;
  hot_lead_workflows: number;
  re_engagement_workflows: number;
  errors?: string[];
}

export const salesWorkflowApi = {
  overview: (clientId?: string) =>
    api.get<WorkflowOverview>("/workflows/overview", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  recommendations: (params?: {
    status?: string;
    priority?: WorkflowPriority;
    workflow_type?: WorkflowType;
    client_id?: string;
    lead_id?: string;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: WorkflowRecommendation[]; total: number; overview: WorkflowOverview }>(
      "/workflows/recommendations",
      { params },
    ),
  templates: () => api.get<{ items: WorkflowTemplate[] }>("/workflows/templates"),
  generate: (body?: { client_id?: string }) =>
    api.post<{ scanned: number; created: number; skipped_duplicates: number }>(
      "/workflows/generate",
      body ?? {},
    ),
  createTask: (id: string) =>
    api.post<{ recommendation: WorkflowRecommendation; task_id: string; suggested: boolean }>(
      `/workflows/recommendations/${id}/create-task`,
    ),
};

export type OperatorEngineActionType =
  | "reply_to_message"
  | "follow_up"
  | "create_proposal"
  | "review_proposal"
  | "link_lead"
  | "update_deal"
  | "check_payment"
  | "review_hot_lead"
  | "manual_sales_action";

export interface OperatorTaskEngineItem {
  id: string;
  client_id: string;
  company_name?: string | null;
  source_type: string;
  source_id?: string | null;
  title: string;
  description?: string | null;
  priority: string;
  status: string;
  action_type?: OperatorEngineActionType | string | null;
  channel?: string | null;
  due_at?: string | null;
  completed_at?: string | null;
  dismissed_at?: string | null;
  recommendation_id?: string | null;
  conversation_id?: string | null;
  lead_id?: string | null;
  lead_name?: string | null;
  lead_classification?: LeadClassification | null;
  lead_classification_score?: number | null;
  lead_classification_urgency?: LeadUrgencyLevel | null;
  deal_id?: string | null;
  deal_title?: string | null;
  proposal_id?: string | null;
  proposal_title?: string | null;
  recommended_action?: string | null;
  created_at: string;
  updated_at: string;
}

export interface OperatorTaskEngineSummary {
  open_count: number;
  urgent_count: number;
  overdue_count: number;
  due_today_count: number;
}

export const operatorTaskEngineApi = {
  list: (params?: {
    status?: string;
    client_id?: string;
    priority?: string;
    action_type?: string;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{
      items: OperatorTaskEngineItem[];
      total: number;
      summary: OperatorTaskEngineSummary;
    }>("/operator-task-engine/tasks", { params }),
  generate: (clientId?: string) =>
    api.post<{ scanned: number; created: number; skipped_duplicates: number }>(
      "/operator-task-engine/generate",
      clientId ? { client_id: clientId } : {},
    ),
  fromRecommendation: (id: string) =>
    api.post<{ task: OperatorTaskEngineItem; message: string }>(
      `/operator-task-engine/from-recommendation/${id}`,
    ),
  fromConversation: (
    conversationId: string,
    data?: {
      task_type?: string;
      title?: string;
      description?: string;
      priority?: string;
      due_at?: string;
    },
  ) =>
    api.post<{ task: OperatorTaskEngineItem; message: string }>(
      `/operator-task-engine/from-conversation/${encodeURIComponent(conversationId)}`,
      data ?? {},
    ),
  fromProposal: (proposalId: string, data?: { due_at?: string }) =>
    api.post<{ task: OperatorTaskEngineItem; message: string }>(
      `/operator-task-engine/from-proposal/${proposalId}`,
      data ?? {},
    ),
  complete: (taskId: string) =>
    api.post<{ task: OperatorTaskEngineItem; message: string }>(
      `/operator-task-engine/${taskId}/complete`,
    ),
  dismiss: (taskId: string) =>
    api.post<{ task: OperatorTaskEngineItem; message: string }>(
      `/operator-task-engine/${taskId}/dismiss`,
    ),
};

export type SystemHealthStatus = "ok" | "degraded";
export type SystemComponentStatus = "ok" | "error" | "running" | "stopped" | "disabled" | "demo" | "unconfigured" | "configured";

export interface SystemHealth {
  status: SystemHealthStatus;
  uptime: number;
  database: "ok" | "error";
  scheduler: "running" | "stopped" | "disabled";
  ai_services: "ok" | "demo" | "unconfigured";
  telegram_bot: "configured" | "unconfigured";
  demo_mode: boolean;
  total_clients: number;
  total_leads: number;
  total_deals: number;
  total_content: number;
  total_posts: number;
  total_revenue: number | string;
  total_commissions: number | string;
}

export interface DemoSeedResult {
  created: boolean;
  message: string;
  client_id?: string;
  partner_id?: string;
  leads?: number;
  deals?: number;
  won_deals?: number;
  content_items?: number;
}

export interface DemoResetResult {
  deleted: boolean;
  message: string;
  counts?: Record<string, number>;
}

export interface SchemaHealthMissingColumn {
  table: string;
  column: string;
}

export interface SchemaHealth {
  ok: boolean;
  database_connected: boolean;
  alembic_current_revision: string | null;
  alembic_head_revision: string | null;
  migration_drift: boolean;
  missing_tables: string[];
  missing_columns: SchemaHealthMissingColumn[];
  checked_models: string[];
  warnings: string[];
}

export type ApiHealthProbeStatus = "ok" | "error" | "slow";

export interface ApiHealthEndpoint {
  name: string;
  path: string;
  status: ApiHealthProbeStatus;
  duration_ms: number;
  error: string | null;
}

export interface ApiHealth {
  endpoints: ApiHealthEndpoint[];
  ok_count: number;
  total: number;
}

export interface RecentErrorEntry {
  timestamp: string;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  error_summary: string | null;
  category?: string;
}

export interface RecentErrors {
  errors: RecentErrorEntry[];
  slow: RecentErrorEntry[];
  categories?: Record<string, number>;
}

export interface QueryHealthEntry {
  endpoint: string;
  avg_duration_ms: number;
  max_duration_ms: number;
  call_count: number;
  avg_query_count: number;
}

export interface QueryHealth {
  endpoints: QueryHealthEntry[];
  slowest_requests: Array<{
    endpoint: string;
    duration_ms: number;
    query_count: number;
    query_duration_ms: number;
  }>;
}

export interface DependencyChainItem {
  kind: string;
  name: string;
}

export interface PageDependency {
  page: string;
  route: string;
  endpoints: string[];
  services: string[];
  tables: string[];
  chain: DependencyChainItem[];
}

export interface SystemDependencies {
  pages: PageDependency[];
  total: number;
}

export interface HealthSnapshot {
  timestamp: string;
  schema_ok: boolean;
  migration_drift: boolean;
  missing_tables_count: number;
  missing_columns_count: number;
  api_ok_count: number;
  api_total: number;
  error_count_5xx: number;
  slow_count: number;
  error_categories: Record<string, number>;
  broken_endpoints: string[];
}

export interface HealthSnapshots {
  snapshots: HealthSnapshot[];
  retention_hours: number;
}

export interface I18nHealth {
  missing_keys: Record<string, string[]>;
  unused_keys: string[];
  translated_keys_count: Record<string, number>;
  canonical_locale: string;
  used_keys_count: number;
}

export type UiLanguage = "ru" | "en" | "zh";

export interface UserSettings {
  id: string;
  preferred_language: UiLanguage;
  default_proposal_language?: UiLanguage | null;
  default_content_language?: UiLanguage | null;
  updated_at: string;
}

export const usersApi = {
  getSettings: () => api.get<UserSettings>("/users/settings"),
  updateLanguage: (preferred_language: UiLanguage) =>
    api.patch<UserSettings>("/users/language", { preferred_language }),
};

export const systemApi = {
  health: () => api.get<SystemHealth>("/system/health"),
  schemaHealth: () => api.get<SchemaHealth>("/system/schema-health"),
  apiHealth: () => api.get<ApiHealth>("/system/api-health"),
  recentErrors: () => api.get<RecentErrors>("/system/recent-errors"),
  queryHealth: () => api.get<QueryHealth>("/system/query-health"),
  dependencies: () => api.get<SystemDependencies>("/system/dependencies"),
  healthSnapshots: () => api.get<HealthSnapshots>("/system/health-snapshots"),
  i18nHealth: () => api.get<I18nHealth>("/system/i18n-health"),
  demoSeed: () => api.post<DemoSeedResult>("/system/demo-seed"),
  demoReset: () => api.post<DemoResetResult>("/system/demo-reset"),
};

export interface TelegramIngestionSettings {
  enabled: boolean;
  allowed_group_ids: string[];
  default_tenant_id?: string | null;
  default_status: ContentStatus;
  default_target_languages: string[];
  auto_classification: boolean;
  auto_enrichment: boolean;
  quality_checks_enabled: boolean;
  updated_at?: string | null;
  env_bot_configured: boolean;
}

export const telegramApi = {
  status: () => adminApi.get<{ configured: boolean; admin_filter_active: boolean }>("/telegram/status"),
  getIngestionSettings: () => adminApi.get<TelegramIngestionSettings>("/telegram/ingestion/settings"),
  updateIngestionSettings: (data: Partial<TelegramIngestionSettings>) =>
    adminApi.patch<TelegramIngestionSettings>("/telegram/ingestion/settings", data),
};

export type ProposalDocumentStatus = "draft" | "reviewed" | "sent" | "accepted" | "rejected";
export type ProposalType =
  | "short_offer"
  | "detailed_commercial_offer"
  | "distributor_offer"
  | "export_offer";
export type ProposalRegenerableSection =
  | "intro"
  | "product_summary"
  | "pricing"
  | "terms"
  | "call_to_action";

export interface ProposalDocument {
  id: string;
  client_id: string;
  client_name?: string | null;
  lead_id?: string | null;
  lead_name?: string | null;
  deal_id?: string | null;
  deal_title?: string | null;
  product_id?: string | null;
  product_ids: string[];
  title: string;
  language: string;
  status: ProposalDocumentStatus;
  proposal_type?: string | null;
  sections: Record<string, string>;
  proposal_text: string;
  demo_mode?: boolean;
  revenue_hint?: {
    message: string;
    suggested_deal_amount?: number | null;
    deal_id?: string | null;
    pricing_excerpt?: string | null;
  } | null;
  exported_pdf_path?: string | null;
  exported_docx_path?: string | null;
  last_exported_at?: string | null;
  pdf_download_url?: string | null;
  docx_download_url?: string | null;
  sent_at?: string | null;
  accepted_at?: string | null;
  rejected_at?: string | null;
  follow_up_at?: string | null;
  buyer_feedback?: string | null;
  deal_hint?: {
    deal_id: string;
    message: string;
    current_status: string;
    current_expected_value?: number | null;
    suggested_status?: string | null;
    suggested_expected_value?: number | null;
  } | null;
  can_create_deal?: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProposalWorkflowResult {
  proposal: ProposalDocument;
  follow_up_task_id?: string | null;
  deal_created_id?: string | null;
  message?: string | null;
}

export interface ProposalExportResult {
  id: string;
  format: "pdf" | "docx";
  path: string;
  last_exported_at: string;
  download_url?: string | null;
}

export const proposalsApi = {
  list: (params?: {
    client_id?: string;
    lead_id?: string;
    deal_id?: string;
    status?: ProposalDocumentStatus;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: ProposalDocument[]; total: number }>("/proposals", { params }),
  get: (id: string) => api.get<ProposalDocument>(`/proposals/${id}`),
  generate: (data: {
    client_id: string;
    lead_id?: string | null;
    deal_id?: string | null;
    product_ids?: string[];
    language?: string;
    proposal_type?: ProposalType;
    custom_requirements?: string | null;
  }) =>
    api.post<ProposalDocument>("/proposals/generate", data, { timeout: 120000 }),
  update: (
    id: string,
    data: Partial<{
      title: string;
      language: string;
      status: ProposalDocumentStatus;
      proposal_text: string;
      sections: Record<string, string>;
    }>,
  ) => api.patch<ProposalDocument>(`/proposals/${id}`, data),
  regenerateSection: (
    id: string,
    data: { section: ProposalRegenerableSection; custom_requirements?: string | null },
  ) =>
    api.post<ProposalDocument>(`/proposals/${id}/regenerate-section`, data, { timeout: 90000 }),
  exportPdf: (id: string) =>
    api.post<ProposalExportResult>(`/proposals/${id}/export/pdf`, {}, { timeout: 120000 }),
  exportDocx: (id: string) =>
    api.post<ProposalExportResult>(`/proposals/${id}/export/docx`, {}, { timeout: 120000 }),
  downloadPdf: async (id: string, filename?: string) => {
    const res = await api.get(`/proposals/${id}/download/pdf`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || `proposal-${id}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  },
  downloadDocx: async (id: string, filename?: string) => {
    const res = await api.get(`/proposals/${id}/download/docx`, { responseType: "blob" });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || `proposal-${id}.docx`;
    a.click();
    URL.revokeObjectURL(url);
  },
  markSent: (id: string, data?: { create_follow_up_task?: boolean }) =>
    api.post<ProposalWorkflowResult>(`/proposals/${id}/mark-sent`, data ?? {}),
  markAccepted: (
    id: string,
    data?: { create_deal?: boolean; deal_title?: string; expected_value?: number | null },
  ) => api.post<ProposalWorkflowResult>(`/proposals/${id}/mark-accepted`, data ?? {}),
  markRejected: (id: string, data?: { buyer_feedback?: string | null }) =>
    api.post<ProposalWorkflowResult>(`/proposals/${id}/mark-rejected`, data ?? {}),
  createFollowUpTask: async (id: string, data?: { due_at?: string | null }) => {
    const res = await operatorTaskEngineApi.fromProposal(
      id,
      data?.due_at ? { due_at: data.due_at } : undefined,
    );
    return {
      ...res,
      data: {
        ok: true,
        message: res.data.message,
        follow_up_task_id: res.data.task.id,
        proposal: undefined,
      } as unknown as ProposalWorkflowResult,
    };
  },
};

export type AuditSeverity = "critical" | "warning" | "info";

export type AuditFixActionType =
  | "cancel_schedule"
  | "send_client_review"
  | "open_billing"
  | "retry_publish"
  | "mark_failed_attempt_reviewed"
  | "seed_demo_data";

export interface AuditIssue {
  id: string;
  severity: AuditSeverity;
  category: string;
  title: string;
  description: string;
  entity_type: string;
  entity_id: string | null;
  suggested_fix: string;
  fix_action_type: AuditFixActionType | null;
  fix_action_label: string | null;
  fix_action_endpoint: string | null;
  fix_action_method: string | null;
}

export interface AuditFixApplyResult {
  ok: boolean;
  message: string;
  fix_action_type: AuditFixActionType;
  entity_type?: string | null;
  entity_id?: string | null;
  navigate_to?: string | null;
  result?: Record<string, unknown> | null;
}

export interface AuditSummary {
  critical: number;
  warning: number;
  info: number;
  total: number;
}

export interface AuditOverview {
  issues: AuditIssue[];
  summary: AuditSummary;
  categories: string[];
  ran_at: string;
  errors?: string[];
}

export const AUDIT_API_BASE =
  (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1").replace(/\/$/, "");

export const AUDIT_OVERVIEW_URL = `${AUDIT_API_BASE}/audit/overview`;
export const AUDIT_RUN_URL = `${AUDIT_API_BASE}/audit/run`;

export function formatAuditApiError(err: unknown, endpoint: string): string {
  const base = getApiErrorMessage(err);
  if (axios.isAxiosError(err)) {
    const status = err.response?.status;
    const statusPart = status ? `HTTP ${status}` : "network error";
    return `${base} (${statusPart}) — ${endpoint}`;
  }
  return `${base} — ${endpoint}`;
}

export const auditApi = {
  overview: () => adminApi.get<AuditOverview>("/audit/overview"),
  run: () => adminApi.post<AuditOverview>("/audit/run"),
  applyFix: (issueId: string) =>
    adminApi.post<AuditFixApplyResult>(`/audit/fixes/${encodeURIComponent(issueId)}/apply`),
};

export type ProductImportSource = "csv" | "xlsx" | "pdf" | "text";

export interface Product {
  id: string;
  client_id: string;
  name: string;
  sku: string | null;
  category: string | null;
  description: string | null;
  moq: number | null;
  unit_price: number | string | null;
  currency: string;
  attributes_json: Record<string, unknown> | null;
  images_json: unknown[] | null;
  active: boolean;
  created_at: string;
  company_name?: string | null;
}

export interface ProductMatchItem {
  product_id: string;
  name: string;
  sku: string | null;
  category: string | null;
  unit_price: number | string | null;
  currency: string;
  confidence: number;
  reason: string;
}

export interface ProductMatchLeadResult {
  lead_id: string;
  lead_name: string;
  query_context: string;
  matches: ProductMatchItem[];
  demo_mode: boolean;
}

export interface ProductImportResult {
  job: {
    id: string;
    client_id: string;
    source_type: string;
    source_file: string | null;
    status: string;
    result_json: Record<string, unknown> | null;
    created_at: string;
  };
  imported: number;
  skipped: number;
  errors: string[];
}

export const productsApi = {
  list: (params?: {
    client_id?: string;
    category?: string;
    search?: string;
    active?: boolean;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: Product[]; total: number }>("/products", { params }),
  get: (id: string) => api.get<Product>(`/products/${id}`),
  create: (data: {
    client_id: string;
    name: string;
    sku?: string | null;
    category?: string | null;
    description?: string | null;
    moq?: number | null;
    unit_price?: number | null;
    currency?: string;
    attributes_json?: Record<string, unknown> | null;
    images_json?: unknown[] | null;
    active?: boolean;
  }) => api.post<Product>("/products", data),
  update: (id: string, data: Partial<Omit<Product, "id" | "client_id" | "created_at">>) =>
    api.patch<Product>(`/products/${id}`, data),
  delete: (id: string) => api.delete(`/products/${id}`),
  categories: (clientId?: string) =>
    api.get<{ categories: string[] }>("/products/categories/list", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  import: (formData: FormData) =>
    api.post<ProductImportResult>("/products/import", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 60000,
    }),
  matchLead: (leadId: string) =>
    api.post<ProductMatchLeadResult>(`/products/match-lead/${leadId}`),
};

export type ExportDemandLevel = "low" | "medium" | "high" | "very_high";

export interface ExportOpportunity {
  id: string;
  client_id: string;
  product_id: string;
  country: string;
  score: number;
  market_summary?: string | null;
  demand_level?: ExportDemandLevel | string | null;
  recommended_partner_types_json?: string[] | null;
  recommended_channels_json?: string[] | null;
  created_at: string;
  product_name?: string | null;
  product_category?: string | null;
  company_name?: string | null;
}

export interface ExportInsight {
  id: string;
  product_id: string;
  insight_type: string;
  title: string;
  description: string;
  confidence?: number | null;
  created_at: string;
}

export interface ExportOpportunityDetail extends ExportOpportunity {
  insights: ExportInsight[];
  score_factors?: {
    partner_count: number;
    lead_count: number;
    industry_activity: number;
    historical_deals: number;
    breakdown?: Record<string, number>;
    computed_score?: number;
  } | null;
}

export interface ExportCountryRanking {
  country: string;
  opportunity_count: number;
  avg_score: number;
  max_score: number;
}

export interface ExportDashboard {
  top_opportunities: ExportOpportunity[];
  country_rankings: ExportCountryRanking[];
  total_opportunities: number;
  avg_score: number;
  products_analyzed: number;
  top_buyer_opportunities: BuyerOpportunitySummary[];
}

export type BuyerRecommendationType = "partner" | "crm_lead" | "contact" | "industry_segment";

export interface BuyerRecommendation {
  id: string;
  client_id: string;
  product_id: string;
  recommendation_type: BuyerRecommendationType;
  reference_id?: string | null;
  name: string;
  score: number;
  reason: string;
  country?: string | null;
  created_at: string;
  product_name?: string | null;
}

export interface BuyerOpportunitySummary {
  id: string;
  product_id: string;
  product_name?: string | null;
  recommendation_type: BuyerRecommendationType;
  reference_id?: string | null;
  name: string;
  country?: string | null;
  score: number;
  reason: string;
}

export interface BuyerFinderProductResult {
  product_id: string;
  product_name: string;
  product_category?: string | null;
  client_id: string;
  items: BuyerRecommendation[];
  total: number;
  demo_mode: boolean;
}

export interface BuyerFinderAnalyzeResult {
  product_id: string;
  product_name: string;
  analyzed_count: number;
  items: BuyerRecommendation[];
  demo_mode: boolean;
}

export const buyerFinderApi = {
  getForProduct: (productId: string) =>
    api.get<BuyerFinderProductResult>(`/buyer-finder/product/${productId}`),
  analyze: (productId: string) =>
    api.post<BuyerFinderAnalyzeResult>(`/buyer-finder/analyze/${productId}`, {}),
};

export type OutreachChannel = "email" | "whatsapp" | "wechat" | "linkedin";
export type OutreachType = "first_contact" | "follow_up" | "proposal_follow_up" | "re_engagement";
export type OutreachStatus = "draft" | "approved" | "sent" | "archived";
export type OutreachStyle = "formal" | "friendly" | "executive" | "distributor";
export type OutreachEventType =
  | "generated"
  | "approved"
  | "copied"
  | "sent"
  | "follow_up_created"
  | "thread_linked";

export interface OutreachEvent {
  id: string;
  event_type: OutreachEventType;
  payload_json?: Record<string, unknown> | null;
  created_at: string;
}

export interface OutreachMessage {
  id: string;
  client_id: string;
  client_name?: string | null;
  lead_id?: string | null;
  lead_name?: string | null;
  product_id?: string | null;
  product_name?: string | null;
  proposal_id?: string | null;
  proposal_title?: string | null;
  buyer_name?: string | null;
  buyer_company?: string | null;
  country?: string | null;
  channel: OutreachChannel;
  language: string;
  outreach_type: OutreachType;
  subject?: string | null;
  message_text: string;
  status: OutreachStatus;
  demo_mode?: boolean;
  style?: OutreachStyle | null;
  sent_at?: string | null;
  approved_at?: string | null;
  copied_at?: string | null;
  last_action_at?: string | null;
  communication_thread_id?: string | null;
  communication_thread_title?: string | null;
  follow_up_task_id?: string | null;
  follow_up_task_title?: string | null;
  sales_playbook_id?: string | null;
  sales_playbook_name?: string | null;
  sales_playbook_step_id?: string | null;
  events?: OutreachEvent[];
  created_at: string;
  updated_at: string;
}

export interface OutreachWorkflowResult {
  outreach: OutreachMessage;
  follow_up_task_id?: string | null;
  communication_thread_id?: string | null;
  message?: string | null;
}

export const outreachApi = {
  list: (params?: {
    client_id?: string;
    lead_id?: string;
    product_id?: string;
    status?: OutreachStatus;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: OutreachMessage[]; total: number }>("/outreach", { params }),
  get: (id: string) => api.get<OutreachMessage>(`/outreach/${id}`),
  generate: (data: {
    product_id: string;
    proposal_id?: string | null;
    lead_id?: string | null;
    buyer_name?: string | null;
    buyer_company?: string | null;
    country: string;
    language?: string;
    channel: OutreachChannel;
    outreach_type: OutreachType;
    style?: OutreachStyle;
  }) => api.post<OutreachMessage>("/outreach/generate", data, { timeout: 90000 }),
  update: (
    id: string,
    data: Partial<{
      subject: string;
      message_text: string;
      status: OutreachStatus;
      buyer_name: string;
      buyer_company: string;
    }>,
  ) => api.patch<OutreachMessage>(`/outreach/${id}`, data),
  regenerate: (id: string, data?: { style?: OutreachStyle }) =>
    api.post<OutreachMessage>(`/outreach/${id}/regenerate`, data ?? {}, { timeout: 90000 }),
  approve: (id: string) => api.post<OutreachWorkflowResult>(`/outreach/${id}/approve`),
  markCopied: (id: string) => api.post<OutreachWorkflowResult>(`/outreach/${id}/mark-copied`),
  markSent: (id: string, data?: { create_follow_up_task?: boolean }) =>
    api.post<OutreachWorkflowResult>(`/outreach/${id}/mark-sent`, data ?? {}),
  createFollowUp: (id: string, data?: { due_at?: string }) =>
    api.post<OutreachWorkflowResult>(`/outreach/${id}/create-follow-up`, data ?? {}),
  linkThread: (id: string, data: { communication_thread_id: string }) =>
    api.post<OutreachWorkflowResult>(`/outreach/${id}/link-thread`, data),
};

export type PlaybookStatus = "draft" | "active" | "archived";
export type PlaybookStepType = "outreach" | "follow_up" | "proposal" | "call" | "internal_task";
export type PlaybookChannel = OutreachChannel;

export interface SalesPlaybookStep {
  id: string;
  playbook_id: string;
  step_order: number;
  step_type: PlaybookStepType;
  title: string;
  instructions?: string | null;
  template_text?: string | null;
  delay_days?: number | null;
  created_at: string;
  updated_at: string;
}

export interface SalesPlaybook {
  id: string;
  client_id?: string | null;
  client_name?: string | null;
  name: string;
  description?: string | null;
  product_category?: string | null;
  buyer_type?: string | null;
  country?: string | null;
  language: string;
  channel: PlaybookChannel;
  status: PlaybookStatus;
  step_count?: number;
  steps?: SalesPlaybookStep[];
  demo_mode?: boolean;
  created_at: string;
  updated_at: string;
}

export interface SalesPlaybookApplyResult {
  playbook_id: string;
  lead_id: string;
  outreach_ids: string[];
  proposal_ids: string[];
  task_ids: string[];
  message: string;
}

export const salesPlaybooksApi = {
  list: (params?: { client_id?: string; status?: PlaybookStatus; skip?: number; limit?: number }) =>
    api.get<{ items: SalesPlaybook[]; total: number }>("/sales-playbooks", { params }),
  get: (id: string) => api.get<SalesPlaybook>(`/sales-playbooks/${id}`),
  create: (data: {
    client_id?: string | null;
    name: string;
    description?: string | null;
    product_category?: string | null;
    buyer_type?: string | null;
    country?: string | null;
    language?: string;
    channel: PlaybookChannel;
    status?: PlaybookStatus;
    steps?: Array<{
      step_order: number;
      step_type: PlaybookStepType;
      title: string;
      instructions?: string | null;
      template_text?: string | null;
      delay_days?: number | null;
    }>;
  }) => api.post<SalesPlaybook>("/sales-playbooks", data),
  update: (
    id: string,
    data: Partial<{
      name: string;
      description: string;
      product_category: string;
      buyer_type: string;
      country: string;
      language: string;
      channel: PlaybookChannel;
      status: PlaybookStatus;
    }>,
  ) => api.patch<SalesPlaybook>(`/sales-playbooks/${id}`, data),
  generate: (data: {
    client_id?: string | null;
    product_category: string;
    buyer_type: string;
    country: string;
    language?: string;
    channel: PlaybookChannel;
    name?: string | null;
  }) => api.post<SalesPlaybook>("/sales-playbooks/generate", data, { timeout: 90000 }),
  recommend: (data: {
    client_id?: string | null;
    product_id?: string | null;
    lead_id?: string | null;
    product_category?: string | null;
    buyer_type?: string | null;
    country?: string | null;
    language?: string | null;
    channel?: string | null;
  }) =>
    api.post<{ items: SalesPlaybook[]; match_reasons: Record<string, string[]> }>(
      "/sales-playbooks/recommend",
      data,
    ),
  createStep: (
    playbookId: string,
    data: {
      step_order: number;
      step_type: PlaybookStepType;
      title: string;
      instructions?: string | null;
      template_text?: string | null;
      delay_days?: number | null;
    },
  ) => api.post<SalesPlaybookStep>(`/sales-playbooks/${playbookId}/steps`, data),
  updateStep: (
    stepId: string,
    data: Partial<{
      step_order: number;
      step_type: PlaybookStepType;
      title: string;
      instructions: string;
      template_text: string;
      delay_days: number;
    }>,
  ) => api.patch<SalesPlaybookStep>(`/sales-playbooks/steps/${stepId}`, data),
  applyToLead: (playbookId: string, leadId: string, data?: { product_id?: string | null }) =>
    api.post<SalesPlaybookApplyResult>(
      `/sales-playbooks/${playbookId}/apply-to-lead/${leadId}`,
      data ?? {},
    ),
};

export interface ExportAnalyzeResult {
  product_id: string;
  product_name: string;
  overall_score: number;
  market_summary: string;
  top_countries: string[];
  top_partner_types: string[];
  top_channels: string[];
  opportunities: ExportOpportunity[];
  insights: ExportInsight[];
  demo_mode: boolean;
}

export const exportApi = {
  dashboard: (limit?: number) =>
    api.get<ExportDashboard>("/export/dashboard", { params: { limit } }),
  listOpportunities: (params?: {
    client_id?: string;
    product_id?: string;
    country?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: ExportOpportunity[]; total: number }>("/export/opportunities", { params }),
  getOpportunity: (id: string) => api.get<ExportOpportunityDetail>(`/export/opportunities/${id}`),
  analyzeProduct: (productId: string) =>
    api.post<ExportAnalyzeResult>(`/export/analyze-product/${productId}`, {}),
};

export type CampaignStatus = "draft" | "active" | "completed" | "archived";

export const CAMPAIGN_OBJECTIVES = [
  "Brand Awareness",
  "Product Launch",
  "Trade Show",
  "Lead Generation",
  "Distributor Recruitment",
] as const;

export interface CampaignStatusCounts {
  draft: number;
  review: number;
  approved: number;
  scheduled: number;
  published: number;
}

export interface CampaignContentItem {
  id: string;
  status: string;
  platforms: string[];
  source: string;
  scheduled_for?: string | null;
  published_at?: string | null;
  created_at: string;
  media_url?: string | null;
  caption_preview?: string | null;
}

export interface Campaign {
  id: string;
  client_id: string;
  name: string;
  description?: string | null;
  objective?: string | null;
  status: CampaignStatus;
  start_date?: string | null;
  end_date?: string | null;
  created_at: string;
  updated_at: string;
  client_name?: string | null;
  posts_count: number;
}

export interface CampaignDetail extends Campaign {
  status_counts: CampaignStatusCounts;
  content_items: CampaignContentItem[];
}

export const campaignsApi = {
  list: (params?: { client_id?: string; status?: CampaignStatus; skip?: number; limit?: number }) =>
    api.get<{ items: Campaign[]; total: number }>("/campaigns", { params }),
  get: (id: string) => api.get<CampaignDetail>(`/campaigns/${id}`),
  create: (data: {
    client_id: string;
    name: string;
    description?: string | null;
    objective?: string | null;
    status?: CampaignStatus;
    start_date?: string | null;
    end_date?: string | null;
  }) => api.post<CampaignDetail>("/campaigns", data),
  update: (
    id: string,
    data: Partial<{
      name: string;
      description: string | null;
      objective: string | null;
      status: CampaignStatus;
      start_date: string | null;
      end_date: string | null;
    }>,
  ) => api.patch<CampaignDetail>(`/campaigns/${id}`, data),
  assignContent: (id: string, contentIds: string[]) =>
    api.post<{ assigned: number; campaign_id: string }>(`/campaigns/${id}/assign-content`, {
      content_ids: contentIds,
    }),
  unassignContent: (id: string, contentIds: string[]) =>
    api.post<{ unassigned: number; campaign_id: string }>(`/campaigns/${id}/unassign-content`, {
      content_ids: contentIds,
    }),
};

export type ContentStudioGoal =
  | "Brand awareness"
  | "Lead generation"
  | "Product promotion"
  | "Distributor recruitment"
  | "Trade show announcement";

export const CONTENT_STUDIO_GOALS: ContentStudioGoal[] = [
  "Brand awareness",
  "Lead generation",
  "Product promotion",
  "Distributor recruitment",
  "Trade show announcement",
];

export interface ContentStudioDraft {
  content_id: string;
  title: string;
  preview: string;
  platforms: string[];
  media_asset_id?: string | null;
  media_url?: string | null;
  status: string;
}

export interface ContentStudioSuggestion {
  title: string;
  angle: string;
  content_goal: string;
  suggested_platforms: string[];
  rationale: string;
}

export const contentStudioApi = {
  generate: (data: {
    client_id: string;
    campaign_id?: string | null;
    media_asset_ids?: string[];
    platforms?: string[];
    content_count?: number;
    content_goal: ContentStudioGoal;
  }) => api.post<{ drafts: ContentStudioDraft[]; generated_count: number; demo_mode: boolean }>(
    "/content-studio/generate",
    data,
    { timeout: 120000 },
  ),
  suggestions: (params: {
    client_id: string;
    campaign_id?: string;
    media_asset_ids?: string[];
  }) =>
    api.get<{ suggestions: ContentStudioSuggestion[]; demo_mode: boolean }>(
      "/content-studio/suggestions",
      {
        params: {
          client_id: params.client_id,
          campaign_id: params.campaign_id,
          media_asset_ids: params.media_asset_ids,
        },
        timeout: 60000,
      },
    ),
};

export type RepurposeSourceType = "media_asset" | "content_item" | "campaign";

export type RepurposeOutputFormat =
  | "instagram_post"
  | "facebook_post"
  | "linkedin_post"
  | "telegram_post"
  | "short_video_script"
  | "carousel_post"
  | "distributor_recruitment_post";

export const REPURPOSE_OUTPUT_FORMATS: RepurposeOutputFormat[] = [
  "instagram_post",
  "facebook_post",
  "linkedin_post",
  "telegram_post",
  "short_video_script",
  "carousel_post",
  "distributor_recruitment_post",
];

export const REPURPOSE_FORMAT_LABELS: Record<RepurposeOutputFormat, string> = {
  instagram_post: "Instagram Post",
  facebook_post: "Facebook Post",
  linkedin_post: "LinkedIn Post",
  telegram_post: "Telegram Post",
  short_video_script: "Short Video Script",
  carousel_post: "Carousel Post",
  distributor_recruitment_post: "Distributor Recruitment Post",
};

export interface ContentRepurposeDraft {
  content_id: string;
  output_format: string;
  format_label: string;
  preview: string;
  platforms: string[];
  media_asset_id?: string | null;
  media_url?: string | null;
  parent_content_id?: string | null;
  parent_media_asset_id?: string | null;
  status: string;
}

export interface ContentRepurposeFormatSuggestion {
  output_format: string;
  format_label: string;
  rationale: string;
  priority: number;
}

export const contentRepurposeApi = {
  generate: (data: {
    client_id: string;
    source_type: RepurposeSourceType;
    source_id: string;
    output_formats: RepurposeOutputFormat[];
  }) =>
    api.post<{ drafts: ContentRepurposeDraft[]; generated_count: number; demo_mode: boolean }>(
      "/content-repurpose/generate",
      data,
      { timeout: 120000 },
    ),
  suggestions: (params: {
    client_id: string;
    source_type: RepurposeSourceType;
    source_id: string;
  }) =>
    api.get<{ suggestions: ContentRepurposeFormatSuggestion[]; demo_mode: boolean }>(
      "/content-repurpose/suggestions",
      { params, timeout: 60000 },
    ),
};

export type CommunicationChannel = "telegram" | "whatsapp" | "wechat" | "wecom" | "email" | "manual";
export type ThreadStatus = "open" | "waiting" | "closed";
export type MessageDirection = "inbound" | "outbound" | "draft" | "internal_note";
export type WeChatChannel = "wechat" | "wecom";

export const COMMUNICATION_CHANNELS: CommunicationChannel[] = [
  "telegram", "whatsapp", "wechat", "wecom", "email", "manual",
];

export const THREAD_STATUSES: ThreadStatus[] = ["open", "waiting", "closed"];

export const CHANNEL_LABELS: Record<CommunicationChannel, string> = {
  telegram: "Telegram",
  whatsapp: "WhatsApp",
  wechat: "WeChat",
  wecom: "WeCom",
  email: "Email",
  manual: "Manual",
};

export interface CommunicationContact {
  id: string;
  client_id?: string | null;
  lead_id?: string | null;
  partner_id?: string | null;
  name: string;
  company?: string | null;
  role?: string | null;
  phone?: string | null;
  telegram?: string | null;
  whatsapp?: string | null;
  wechat?: string | null;
  wechat_id?: string | null;
  wecom_id?: string | null;
  qr_code_url?: string | null;
  email?: string | null;
  country?: string | null;
  language?: string | null;
  preferred_language?: string | null;
  notes?: string | null;
  client_name?: string | null;
  lead_name?: string | null;
  partner_name?: string | null;
  thread_count?: number;
  created_at: string;
  updated_at: string;
}

export interface CommunicationThread {
  id: string;
  contact_id: string;
  client_id?: string | null;
  lead_id?: string | null;
  partner_id?: string | null;
  channel: CommunicationChannel;
  external_thread_id?: string | null;
  external_contact_id?: string | null;
  last_manual_sync_at?: string | null;
  title: string;
  status: ThreadStatus;
  last_message_at?: string | null;
  contact_name?: string | null;
  client_name?: string | null;
  lead_name?: string | null;
  deal_id?: string | null;
  deal_title?: string | null;
  message_count?: number;
  last_message_preview?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CommunicationMessage {
  id: string;
  thread_id: string;
  direction: MessageDirection;
  sender_name: string;
  message_text: string;
  attachments_json?: unknown[] | null;
  original_language?: string | null;
  translated_text?: string | null;
  ai_summary?: string | null;
  copied_at?: string | null;
  manual_sent_at?: string | null;
  created_at: string;
}

export interface CommunicationThreadDetail extends CommunicationThread {
  messages: CommunicationMessage[];
  contact?: CommunicationContact | null;
  linked_outreach?: OutreachMessage[];
}

export interface CommunicationAiSummary {
  summary: string;
  next_action: string;
  sentiment: string;
  possible_lead_interest: string;
  demo_mode?: boolean;
}

export type CommCrmTaskType =
  | "follow_up"
  | "send_catalog"
  | "send_proposal"
  | "request_details"
  | "schedule_call";

export const COMM_CRM_TASK_TYPES: { value: CommCrmTaskType; label: string }[] = [
  { value: "follow_up", label: "Follow up" },
  { value: "send_catalog", label: "Send catalog" },
  { value: "send_proposal", label: "Send proposal" },
  { value: "request_details", label: "Request details" },
  { value: "schedule_call", label: "Schedule call" },
];

export interface CommunicationCrmExtract {
  name?: string | null;
  company?: string | null;
  phone?: string | null;
  email?: string | null;
  telegram?: string | null;
  whatsapp?: string | null;
  wechat?: string | null;
  country?: string | null;
  language?: string | null;
  interest?: string | null;
  urgency?: string | null;
  budget?: string | null;
  next_follow_up_at?: string | null;
  suggested_status: string;
  suggested_priority: string;
  demo_mode?: boolean;
}

export interface CommunicationCrmLeadPayload {
  name?: string | null;
  company?: string | null;
  phone?: string | null;
  email?: string | null;
  telegram?: string | null;
  whatsapp?: string | null;
  wechat?: string | null;
  country?: string | null;
  language?: string | null;
  interest?: string | null;
  urgency?: string | null;
  budget?: string | null;
  next_follow_up_at?: string | null;
  suggested_status?: string | null;
  suggested_priority?: string | null;
  notes?: string | null;
  attribution_link_id?: string | null;
}

export const communicationsApi = {
  listContacts: (params?: {
    client_id?: string;
    lead_id?: string;
    partner_id?: string;
    search?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: CommunicationContact[]; total: number }>("/communications/contacts", { params }),
  getContact: (id: string) =>
    api.get<CommunicationContact & { threads: CommunicationThread[] }>(`/communications/contacts/${id}`),
  createContact: (data: {
    name: string;
    client_id?: string | null;
    lead_id?: string | null;
    partner_id?: string | null;
    company?: string | null;
    role?: string | null;
    phone?: string | null;
    telegram?: string | null;
    whatsapp?: string | null;
    wechat?: string | null;
    email?: string | null;
    country?: string | null;
    language?: string | null;
    notes?: string | null;
  }) => api.post<CommunicationContact>("/communications/contacts", data),
  listThreads: (params?: {
    client_id?: string;
    contact_id?: string;
    lead_id?: string;
    channel?: CommunicationChannel;
    status?: ThreadStatus;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: CommunicationThread[]; total: number }>("/communications/threads", { params }),
  getThread: (id: string) => api.get<CommunicationThreadDetail>(`/communications/threads/${id}`),
  createThread: (data: {
    contact_id: string;
    channel: CommunicationChannel;
    title: string;
    client_id?: string | null;
    lead_id?: string | null;
    partner_id?: string | null;
    external_thread_id?: string | null;
    status?: ThreadStatus;
  }) => api.post<CommunicationThread>("/communications/threads", data),
  addMessage: (threadId: string, data: {
    direction: MessageDirection;
    sender_name: string;
    message_text: string;
    attachments_json?: unknown[] | null;
  }) => api.post<CommunicationMessage>(`/communications/threads/${threadId}/messages`, data),
  aiSummary: (threadId: string) =>
    api.post<CommunicationAiSummary>(`/communications/threads/${threadId}/ai-summary`, {}, { timeout: 60000 }),
  linkLead: (threadId: string, leadId: string) =>
    api.post<{ thread_id: string; lead_id: string; lead_name: string }>(
      `/communications/threads/${threadId}/link-lead`,
      { lead_id: leadId },
    ),
  createLead: (threadId: string, data?: CommunicationCrmLeadPayload) =>
    api.post<{ lead_id: string; lead_name: string; thread_id: string; created: boolean; updated: boolean }>(
      `/communications/threads/${threadId}/create-lead`,
      data ?? {},
    ),
  extractCrm: (threadId: string) =>
    api.post<CommunicationCrmExtract>(`/communications/threads/${threadId}/extract-crm`, {}, { timeout: 90000 }),
  suggestReply: (threadId: string) =>
    api.post<{ reply_text: string; demo_mode?: boolean }>(
      `/communications/threads/${threadId}/suggest-reply`,
      {},
      { timeout: 60000 },
    ),
  createTask: (threadId: string, data: {
    task_type: CommCrmTaskType;
    title?: string;
    description?: string;
    priority?: "high" | "medium" | "low";
    due_at?: string;
  }) =>
    api.post<{ task_id: string; title: string; thread_id: string; task_type: string }>(
      `/communications/threads/${threadId}/create-task`,
      data,
    ),
};

// ── Communication Hub MVP (dashboard, inbox, follow-ups, templates) ──

export type MessageTemplateCategory =
  | "first_contact"
  | "follow_up"
  | "proposal_follow_up"
  | "negotiation"
  | "re_engagement"
  | "customer_support";

export const MESSAGE_TEMPLATE_CATEGORIES: MessageTemplateCategory[] = [
  "first_contact",
  "follow_up",
  "proposal_follow_up",
  "negotiation",
  "re_engagement",
  "customer_support",
];

export type FollowUpBucket = "overdue" | "today" | "upcoming";

export interface CommunicationDashboardKpis {
  total_communications: number;
  communications_this_week: number;
  unanswered_conversations: number;
  follow_ups_due_today: number;
  active_buyers: number;
  active_negotiations: number;
}

export interface CommunicationConversationPreview {
  id: string;
  thread_id: string;
  title: string;
  contact_name?: string | null;
  channel: string;
  last_message_preview?: string | null;
  last_message_at?: string | null;
  status: string;
  unread_count: number;
}

export interface CommunicationActivityItem {
  id: string;
  type: string;
  title: string;
  subtitle?: string | null;
  channel?: string | null;
  occurred_at: string;
  href?: string | null;
}

export interface CommunicationFollowUp {
  id: string;
  tenant_id: string;
  communication_id?: string | null;
  thread_id?: string | null;
  title: string;
  description?: string | null;
  due_date: string;
  status: string;
  assigned_user?: string | null;
  is_overdue: boolean;
  thread_title?: string | null;
  channel?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CommunicationDashboard {
  kpis: CommunicationDashboardKpis;
  recent_conversations: CommunicationConversationPreview[];
  recent_activity: CommunicationActivityItem[];
  follow_ups_due: CommunicationFollowUp[];
  unanswered: CommunicationConversationPreview[];
  statistics: Record<string, number>;
}

export interface CommunicationRecord {
  id: string;
  tenant_id?: string | null;
  channel: string;
  customer_id?: string | null;
  buyer_id?: string | null;
  lead_id?: string | null;
  deal_id?: string | null;
  client_id?: string | null;
  thread_id: string;
  subject: string;
  content: string;
  direction: string;
  status: string;
  contact_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageTemplate {
  id: string;
  tenant_id: string;
  name: string;
  category: MessageTemplateCategory;
  content: string;
  language: string;
  created_at: string;
  updated_at: string;
}

export const communicationHubApi = {
  dashboard: () => api.get<CommunicationDashboard>("/communications/dashboard"),
  listInbox: (params?: { channel?: string; status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: CommunicationRecord[]; total: number }>("/communications/inbox", { params }),
  listRecords: (params?: { channel?: string; status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: CommunicationRecord[]; total: number }>("/communications/records", { params }),
  createRecord: (data: {
    channel: string;
    subject: string;
    content: string;
    direction?: string;
    status?: string;
    contact_name?: string;
  }) => api.post<CommunicationRecord>("/communications/records", data),
  listFollowups: (params?: {
    bucket?: FollowUpBucket;
    status?: string;
    assigned_user?: string;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{
      items: CommunicationFollowUp[];
      total: number;
      overdue_count: number;
      today_count: number;
      upcoming_count: number;
    }>("/communications/followups", { params }),
  createFollowup: (data: {
    title: string;
    description?: string;
    due_date: string;
    communication_id?: string;
    thread_id?: string;
    assigned_user?: string;
  }) => api.post<CommunicationFollowUp>("/communications/followups", data),
  updateFollowup: (
    id: string,
    data: { title?: string; description?: string; due_date?: string; status?: string; assigned_user?: string },
  ) => api.patch<CommunicationFollowUp>(`/communications/followups/${id}`, data),
  completeFollowup: (id: string) =>
    api.post<CommunicationFollowUp>(`/communications/followups/${id}/complete`),
  listTemplates: (params?: { category?: string; language?: string; search?: string; skip?: number; limit?: number }) =>
    api.get<{ items: MessageTemplate[]; total: number }>("/communications/templates", { params }),
  createTemplate: (data: {
    name: string;
    category: MessageTemplateCategory;
    content: string;
    language?: string;
  }) => api.post<MessageTemplate>("/communications/templates", data),
  updateTemplate: (
    id: string,
    data: Partial<{ name: string; category: MessageTemplateCategory; content: string; language: string }>,
  ) => api.patch<MessageTemplate>(`/communications/templates/${id}`, data),
  deleteTemplate: (id: string) => api.delete(`/communications/templates/${id}`),
  aiCapabilities: () =>
    api.get<{ analyze_conversations: boolean; recommend_responses: boolean; implementation_status: string }>(
      "/communications/ai/capabilities",
    ),
};

export interface WeChatAiPanel {
  summary: string;
  recommended_next_action: string;
  sentiment: string;
  has_linked_lead: boolean;
  has_linked_deal: boolean;
  proposal_count: number;
  playbook_name?: string | null;
}

export interface WeChatThreadDetail extends CommunicationThread {
  messages: CommunicationMessage[];
  contact?: CommunicationContact | null;
  ai_panel?: WeChatAiPanel | null;
}

export interface WeChatGenerateReplyResult {
  message_id: string;
  language: string;
  reply_text: string;
  tone: string;
  recommended_next_action: string;
  risk_flags: string[];
  demo_mode?: boolean;
}

export const wechatApi = {
  dashboard: () => api.get<WeChatDashboard>("/wechat/dashboard"),
  listAccounts: () => api.get<{ items: WeChatAccount[]; total: number }>("/wechat/accounts"),
  createAccount: (data: {
    account_name: string;
    account_type?: WeChatAccountType;
    provider?: string | null;
  }) => api.post<WeChatAccount>("/wechat/accounts", data),
  updateAccount: (id: string, data: { account_name?: string; status?: WeChatAccountStatus; provider?: string }) =>
    api.patch<WeChatAccount>(`/wechat/accounts/${id}`, data),
  seedDemo: () => api.post<WeChatDemoSeedResult>("/wechat/demo/seed"),
  aiCapabilities: () => api.get<WeChatAiCapabilities>("/wechat/ai/capabilities"),
  listContactsExtended: (params?: { search?: string; skip?: number; limit?: number }) =>
    api.get<{ items: WeChatContactExtended[]; total: number }>("/wechat/contacts/extended", { params }),
  linkContactBuyer: (contactId: string, buyerId: string) =>
    api.post<{ contact_id: string; buyer_id: string; buyer_name: string }>(
      `/wechat/contacts/${contactId}/link-buyer`,
      { buyer_id: buyerId },
    ),
  linkContactCustomer: (contactId: string, customerId: string) =>
    api.post<{ contact_id: string; customer_id: string; customer_name: string }>(
      `/wechat/contacts/${contactId}/link-customer`,
      { customer_id: customerId },
    ),
  linkProposal: (threadId: string, proposalId: string) =>
    api.post<{ thread_id: string; proposal_id: string; proposal_title: string }>(
      `/wechat/threads/${threadId}/link-proposal`,
      { proposal_id: proposalId },
    ),
  listContacts: (params?: {
    client_id?: string;
    search?: string;
    channel?: WeChatChannel;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: CommunicationContact[]; total: number }>("/wechat/contacts", { params }),
  createContact: (data: {
    name: string;
    channel?: WeChatChannel;
    client_id?: string | null;
    lead_id?: string | null;
    company?: string | null;
    country?: string | null;
    wechat_id?: string | null;
    wecom_id?: string | null;
    qr_code_url?: string | null;
    preferred_language?: string | null;
    phone?: string | null;
    email?: string | null;
    notes?: string | null;
  }) => api.post<CommunicationContact>("/wechat/contacts", data),
  listThreads: (params?: {
    client_id?: string;
    contact_id?: string;
    channel?: WeChatChannel;
    status?: ThreadStatus;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: CommunicationThread[]; total: number }>("/wechat/threads", { params }),
  getThread: (id: string) => api.get<WeChatThreadDetail>(`/wechat/threads/${id}`),
  createThread: (data: {
    contact_id: string;
    channel?: WeChatChannel;
    title?: string | null;
    client_id?: string | null;
    lead_id?: string | null;
    deal_id?: string | null;
    external_contact_id?: string | null;
  }) => api.post<WeChatThreadDetail>("/wechat/threads", data),
  pasteInbound: (threadId: string, data: {
    message_text: string;
    sender_name?: string | null;
    original_language?: string | null;
    translated_text?: string | null;
  }) => api.post<CommunicationMessage>(`/wechat/threads/${threadId}/messages`, data),
  generateReply: (threadId: string, data?: { operator_notes?: string | null }) =>
    api.post<WeChatGenerateReplyResult>(
      `/wechat/threads/${threadId}/generate-reply`,
      data ?? {},
      { timeout: 90000 },
    ),
  markCopied: (messageId: string) =>
    api.post<{ message_id: string; copied_at: string }>(`/wechat/messages/${messageId}/mark-copied`),
  markManuallySent: (messageId: string) =>
    api.post<{ message_id: string; manual_sent_at: string; direction: string }>(
      `/wechat/messages/${messageId}/mark-manually-sent`,
    ),
  createLead: (threadId: string, data?: {
    name?: string | null;
    company?: string | null;
    interest?: string | null;
    notes?: string | null;
  }) =>
    api.post<{ lead_id: string; lead_name: string; thread_id: string; created: boolean; updated: boolean }>(
      `/wechat/threads/${threadId}/create-lead`,
      data ?? {},
    ),
  linkLead: (threadId: string, leadId: string) =>
    api.post<{ thread_id: string; lead_id: string; lead_name: string }>(
      `/wechat/threads/${threadId}/link-lead`,
      { lead_id: leadId },
    ),
  linkDeal: (threadId: string, dealId: string) =>
    api.post<{ thread_id: string; deal_id: string; deal_title: string; lead_id?: string }>(
      `/wechat/threads/${threadId}/link-deal`,
      { deal_id: dealId },
    ),
  createTask: (threadId: string, data: {
    task_type: CommCrmTaskType;
    title?: string;
    description?: string;
    priority?: "high" | "medium" | "low";
    due_at?: string;
  }) => communicationsApi.createTask(threadId, data),
};

export type WeChatAccountStatus = "not_connected" | "connected" | "sync_error" | "disabled";
export type WeChatAccountType = "personal_wechat" | "wecom" | "official_account";

export interface WeChatAccount {
  id: string;
  tenant_id?: string | null;
  account_name: string;
  account_type: WeChatAccountType;
  status: WeChatAccountStatus;
  provider?: string | null;
  external_account_id?: string | null;
  connected_at?: string | null;
  last_sync_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WeChatDashboardKpis {
  total_contacts: number;
  active_conversations: number;
  new_conversations_this_week: number;
  opportunities_discovered: number;
  follow_ups_required: number;
  messages_total: number;
  accounts_connected: number;
}

export interface WeChatActivityItem {
  id: string;
  activity_type: string;
  title: string;
  subtitle?: string | null;
  channel: string;
  occurred_at: string;
  thread_id?: string | null;
  contact_id?: string | null;
}

export interface WeChatDashboard {
  connection: {
    overall_status: WeChatAccountStatus;
    accounts_total: number;
    accounts_connected: number;
    demo_mode: boolean;
    provider_ready: boolean;
    last_sync_at?: string | null;
  };
  kpis: WeChatDashboardKpis;
  linked_accounts: WeChatAccount[];
  recent_activity: WeChatActivityItem[];
  communication_hub_channel: string;
}

export interface WeChatContactExtended {
  id: string;
  tenant_id?: string | null;
  wechat_id?: string | null;
  wecom_id?: string | null;
  display_name: string;
  company?: string | null;
  country?: string | null;
  industry?: string | null;
  tags: string[];
  linked_lead_id?: string | null;
  linked_sales_lead_id?: string | null;
  linked_buyer_id?: string | null;
  linked_customer_id?: string | null;
  linked_lead_name?: string | null;
  linked_buyer_name?: string | null;
  linked_customer_name?: string | null;
  last_interaction_at?: string | null;
  thread_count: number;
  created_at: string;
  updated_at: string;
}

export interface WeChatDemoSeedResult {
  seeded: boolean;
  accounts_created: number;
  contacts_created: number;
  conversations_created: number;
  message: string;
}

export interface WeChatAiCapabilities {
  capabilities: Array<{
    id: string;
    label: string;
    description: string;
    status: "ready" | "planned";
  }>;
  uses_communication_ai_hub: boolean;
  demo_mode: boolean;
}

export type WeChatSyncAccountType = "personal_wechat" | "wecom" | "official_account";
export type WeChatSyncJobStatus = "pending" | "running" | "completed" | "failed";

export interface WeChatSyncAccount {
  id: string;
  account_name: string;
  account_type: WeChatSyncAccountType;
  status: string;
  provider?: string | null;
  external_account_id?: string | null;
  last_sync_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WeChatSyncJob {
  id: string;
  account_id?: string | null;
  account_name?: string | null;
  job_type: string;
  trigger: string;
  status: WeChatSyncJobStatus;
  stats_json?: Record<string, unknown> | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface WeChatSyncStatusOverview {
  accounts_total: number;
  accounts_connected: number;
  last_sync_at?: string | null;
  pending_jobs: number;
  failed_jobs_recent: number;
  adapters_available: string[];
}

export const wechatSyncApi = {
  listAccounts: () =>
    api.get<{ items: WeChatSyncAccount[]; total: number }>("/wechat-sync/accounts"),
  listJobs: (params?: { status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: WeChatSyncJob[]; total: number }>("/wechat-sync/jobs", { params }),
  status: () => api.get<WeChatSyncStatusOverview>("/wechat-sync/status"),
  syncContacts: (data?: { account_id?: string | null }) =>
    api.post<{ job_id: string; status: WeChatSyncJobStatus; stats: Record<string, unknown>; message: string }>(
      "/wechat-sync/sync-contacts",
      data ?? {},
    ),
  syncConversations: (data?: { account_id?: string | null }) =>
    api.post<{ job_id: string; status: WeChatSyncJobStatus; stats: Record<string, unknown>; message: string }>(
      "/wechat-sync/sync-conversations",
      data ?? {},
    ),
  testConnection: (accountId: string) =>
    api.post<{
      job_id: string;
      ok: boolean;
      provider: string;
      message: string;
      latency_ms: number;
      details: Record<string, unknown>;
    }>("/wechat-sync/test-connection", { account_id: accountId }),
};

export type WeChatProviderType =
  | "wecom_api"
  | "official_account_api"
  | "third_party_connector"
  | "custom_provider";
export type WeChatProviderStatus = "pending" | "active" | "inactive" | "error";
export type WeChatProviderConfigStatus = "draft" | "configured" | "validated" | "error";

export interface WeChatProviderCapabilities {
  contact_sync: boolean;
  conversation_sync: boolean;
  message_send: boolean;
  media_upload: boolean;
  webhook_support: boolean;
}

export interface WeChatProvider {
  id: string;
  provider_name: string;
  provider_type: WeChatProviderType;
  status: WeChatProviderStatus;
  capabilities: WeChatProviderCapabilities;
  created_at: string;
}

export interface WeChatProviderConfiguration {
  id: string;
  provider_id: string;
  provider_name?: string | null;
  tenant_id?: string | null;
  config_status: WeChatProviderConfigStatus;
  last_connection_test?: string | null;
  created_at: string;
}

export interface WeChatProviderHealthItem {
  provider_id: string;
  provider_name: string;
  provider_type: WeChatProviderType;
  status: WeChatProviderStatus;
  config_status?: WeChatProviderConfigStatus | null;
  last_connection_test?: string | null;
  connection_ok: boolean;
  message: string;
}

export interface WeChatProviderIntegrationCheck {
  module: string;
  status: "ok" | "degraded" | "unavailable";
  message: string;
  details: Record<string, unknown>;
}

export interface WeChatProviderWebhookStatusItem {
  event_type: "inbound_message" | "contact_update" | "conversation_update";
  status: string;
  processing_enabled: boolean;
  message: string;
}

export interface WeChatProviderHealthResponse {
  providers_total: number;
  providers_active: number;
  configurations_total: number;
  configurations_validated: number;
  last_connection_test?: string | null;
  overall_status: "ok" | "degraded" | "unavailable";
  provider_health: WeChatProviderHealthItem[];
  integration_checks: WeChatProviderIntegrationCheck[];
  webhook_status: WeChatProviderWebhookStatusItem[];
  safety: Record<string, boolean>;
}

export const wechatProviderApi = {
  listProviders: () =>
    api.get<{ items: WeChatProvider[]; total: number }>("/wechat-provider/providers"),
  listConfigurations: (params?: { tenant_id?: string }) =>
    api.get<{ items: WeChatProviderConfiguration[]; total: number }>(
      "/wechat-provider/configurations",
      { params },
    ),
  health: () => api.get<WeChatProviderHealthResponse>("/wechat-provider/health"),
  testConnection: (providerId: string, configJson?: Record<string, unknown>) =>
    api.post<{
      ok: boolean;
      provider_id: string;
      provider_name: string;
      provider_type: WeChatProviderType;
      message: string;
      latency_ms: number;
      config_valid: boolean;
      details: Record<string, unknown>;
    }>("/wechat-provider/test-connection", {
      provider_id: providerId,
      config_json: configJson,
    }),
  registerProvider: (data: {
    provider_name: string;
    provider_type: WeChatProviderType;
    tenant_id?: string | null;
    config_json?: Record<string, unknown>;
  }) =>
    api.post<{
      provider: WeChatProvider;
      configuration?: WeChatProviderConfiguration | null;
      message: string;
    }>("/wechat-provider/register-provider", data),
};

export type WhatsAppProviderType =
  | "meta_cloud_api"
  | "whatsapp_business_api"
  | "third_party_connector"
  | "custom_provider";
export type WhatsAppProviderStatus = "pending" | "active" | "inactive" | "error";
export type WhatsAppProviderConfigStatus = "draft" | "configured" | "validated" | "error";

export interface WhatsAppProviderCapabilities {
  contact_sync: boolean;
  conversation_sync: boolean;
  message_send: boolean;
  media_upload: boolean;
  webhook_support: boolean;
  template_messages: boolean;
}

export interface WhatsAppProvider {
  id: string;
  provider_name: string;
  provider_type: WhatsAppProviderType;
  status: WhatsAppProviderStatus;
  capabilities: WhatsAppProviderCapabilities;
  created_at: string;
}

export interface WhatsAppProviderConfiguration {
  id: string;
  provider_id: string;
  provider_name?: string | null;
  tenant_id?: string | null;
  config_status: WhatsAppProviderConfigStatus;
  phone_number?: string | null;
  business_account_id?: string | null;
  provider_status: string;
  last_connection_test?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppProviderHealthItem {
  provider_id: string;
  provider_name: string;
  provider_type: WhatsAppProviderType;
  status: WhatsAppProviderStatus;
  config_status?: WhatsAppProviderConfigStatus | null;
  phone_number?: string | null;
  business_account_id?: string | null;
  provider_status?: string | null;
  last_connection_test?: string | null;
  connection_ok: boolean;
  message: string;
}

export interface WhatsAppProviderIntegrationCheck {
  module: string;
  status: "ok" | "degraded" | "unavailable";
  message: string;
  details: Record<string, unknown>;
}

export interface WhatsAppProviderWebhookStatusItem {
  event_type:
    | "inbound_message"
    | "contact_update"
    | "conversation_update"
    | "delivery_status_update"
    | "template_status_update";
  status: string;
  processing_enabled: boolean;
  message: string;
}

export interface WhatsAppProviderHealthResponse {
  providers_total: number;
  providers_active: number;
  configurations_total: number;
  configurations_validated: number;
  last_connection_test?: string | null;
  overall_status: "ok" | "degraded" | "unavailable";
  provider_health: WhatsAppProviderHealthItem[];
  integration_checks: WhatsAppProviderIntegrationCheck[];
  webhook_status: WhatsAppProviderWebhookStatusItem[];
  safety: Record<string, boolean>;
}

export const whatsappProviderApi = {
  listProviders: () =>
    api.get<{ items: WhatsAppProvider[]; total: number }>("/whatsapp-provider/providers"),
  listConfigurations: (params?: { tenant_id?: string }) =>
    api.get<{ items: WhatsAppProviderConfiguration[]; total: number }>(
      "/whatsapp-provider/configurations",
      { params },
    ),
  health: () => api.get<WhatsAppProviderHealthResponse>("/whatsapp-provider/health"),
  testConnection: (providerId: string, configJson?: Record<string, unknown>) =>
    api.post<{
      ok: boolean;
      provider_id: string;
      provider_name: string;
      provider_type: WhatsAppProviderType;
      message: string;
      latency_ms: number;
      config_valid: boolean;
      details: Record<string, unknown>;
    }>("/whatsapp-provider/test-connection", {
      provider_id: providerId,
      config_json: configJson,
    }),
  registerProvider: (data: {
    provider_name: string;
    provider_type: WhatsAppProviderType;
    tenant_id?: string | null;
    phone_number?: string | null;
    business_account_id?: string | null;
    config_json?: Record<string, unknown>;
  }) =>
    api.post<{
      provider: WhatsAppProvider;
      configuration?: WhatsAppProviderConfiguration | null;
      message: string;
    }>("/whatsapp-provider/register-provider", data),
};

export type WhatsAppSyncAccountType =
  | "whatsapp_business_api"
  | "whatsapp_cloud_api"
  | "third_party_connector"
  | "manual_import";
export type WhatsAppSyncJobStatus = "pending" | "running" | "completed" | "failed";

export interface WhatsAppSyncAccount {
  id: string;
  account_name: string;
  account_type: WhatsAppSyncAccountType;
  status: string;
  phone_number?: string | null;
  provider?: string | null;
  external_account_id?: string | null;
  last_sync_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppSyncJob {
  id: string;
  account_id?: string | null;
  account_name?: string | null;
  job_type: string;
  trigger: string;
  status: WhatsAppSyncJobStatus;
  stats_json?: Record<string, unknown> | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
}

export interface WhatsAppSyncStatusOverview {
  accounts_total: number;
  accounts_connected: number;
  last_sync_at?: string | null;
  pending_jobs: number;
  failed_jobs_recent: number;
  adapters_available: string[];
}

export const whatsappSyncApi = {
  listAccounts: () =>
    api.get<{ items: WhatsAppSyncAccount[]; total: number }>("/whatsapp-sync/accounts"),
  listJobs: (params?: { status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: WhatsAppSyncJob[]; total: number }>("/whatsapp-sync/jobs", { params }),
  status: () => api.get<WhatsAppSyncStatusOverview>("/whatsapp-sync/status"),
  syncContacts: (data?: { account_id?: string | null }) =>
    api.post<{ job_id: string; status: WhatsAppSyncJobStatus; stats: Record<string, unknown>; message: string }>(
      "/whatsapp-sync/sync-contacts",
      data ?? {},
    ),
  syncConversations: (data?: { account_id?: string | null }) =>
    api.post<{ job_id: string; status: WhatsAppSyncJobStatus; stats: Record<string, unknown>; message: string }>(
      "/whatsapp-sync/sync-conversations",
      data ?? {},
    ),
  testConnection: (accountId: string) =>
    api.post<{
      job_id: string;
      ok: boolean;
      provider: string;
      message: string;
      latency_ms: number;
      details: Record<string, unknown>;
    }>("/whatsapp-sync/test-connection", { account_id: accountId }),
};

export interface WhatsAppContact {
  id: string;
  phone: string;
  display_name: string;
  company?: string | null;
  country?: string | null;
  crm_client_id?: string | null;
  crm_client_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppThread {
  id: string;
  contact_id: string;
  contact_name?: string | null;
  contact_phone?: string | null;
  company?: string | null;
  country?: string | null;
  crm_client_id?: string | null;
  last_message_at?: string | null;
  unread_count: number;
  last_message_preview?: string | null;
  created_at: string;
}

export interface WhatsAppMessage {
  id: string;
  thread_id: string;
  direction: "incoming" | "outgoing";
  content: string;
  status: "sent" | "delivered" | "read" | "draft" | "failed";
  created_at: string;
}

export interface WhatsAppDraftResult {
  message_id: string;
  thread_id: string;
  content: string;
  language: string;
  tone: string;
  recommended_next_action: string;
  demo_mode?: boolean;
}

export type WhatsAppAccountStatus = "not_connected" | "connected" | "sync_error" | "disabled";
export type WhatsAppAccountType =
  | "whatsapp_business_api"
  | "whatsapp_cloud_api"
  | "third_party_connector"
  | "manual_import";

export interface WhatsAppBusinessAccount {
  id: string;
  tenant_id?: string | null;
  account_name: string;
  phone_number?: string | null;
  business_display_name?: string | null;
  account_type: WhatsAppAccountType;
  status: WhatsAppAccountStatus;
  provider?: string | null;
  external_account_id?: string | null;
  connected_at?: string | null;
  last_sync_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppDashboardKpis {
  total_contacts: number;
  active_conversations: number;
  new_conversations_this_week: number;
  opportunities_discovered: number;
  follow_ups_required: number;
  messages_total: number;
  accounts_connected: number;
}

export interface WhatsAppActivityItem {
  id: string;
  activity_type: string;
  title: string;
  subtitle?: string | null;
  channel: string;
  occurred_at: string;
  thread_id?: string | null;
  contact_id?: string | null;
}

export interface WhatsAppDashboard {
  connection: {
    overall_status: WhatsAppAccountStatus;
    accounts_total: number;
    accounts_connected: number;
    demo_mode: boolean;
    provider_ready: boolean;
    webhook_configured: boolean;
    last_sync_at?: string | null;
  };
  kpis: WhatsAppDashboardKpis;
  linked_accounts: WhatsAppBusinessAccount[];
  recent_activity: WhatsAppActivityItem[];
  communication_hub_channel: string;
}

export interface WhatsAppContactExtended {
  id: string;
  tenant_id?: string | null;
  phone_number?: string | null;
  display_name: string;
  company?: string | null;
  country?: string | null;
  city?: string | null;
  industry?: string | null;
  tags: string[];
  linked_lead_id?: string | null;
  linked_sales_lead_id?: string | null;
  linked_buyer_id?: string | null;
  linked_customer_id?: string | null;
  linked_lead_name?: string | null;
  linked_buyer_name?: string | null;
  linked_customer_name?: string | null;
  last_interaction_at?: string | null;
  thread_count: number;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppDemoSeedResult {
  seeded: boolean;
  accounts_created: number;
  contacts_created: number;
  conversations_created: number;
  message: string;
}

export interface WhatsAppGenerateReplyResult {
  message_id: string;
  language: string;
  reply_text: string;
  tone: string;
  recommended_next_action: string;
  risk_flags: string[];
  demo_mode?: boolean;
}

export interface WhatsAppThreadDetail extends CommunicationThread {
  messages: CommunicationMessage[];
  contact?: CommunicationContact | null;
  ai_panel?: {
    summary: string;
    recommended_next_action: string;
    sentiment: string;
    has_linked_lead: boolean;
    has_linked_deal: boolean;
    proposal_count: number;
    playbook_name?: string | null;
  };
}

export const whatsappApi = {
  dashboard: () => api.get<WhatsAppDashboard>("/whatsapp/dashboard"),
  listAccounts: () => api.get<{ items: WhatsAppBusinessAccount[]; total: number }>("/whatsapp/accounts"),
  createAccount: (data: {
    account_name: string;
    account_type?: WhatsAppAccountType;
    phone_number?: string | null;
    business_display_name?: string | null;
    provider?: string | null;
  }) => api.post<WhatsAppBusinessAccount>("/whatsapp/accounts", data),
  updateAccount: (
    id: string,
    data: {
      account_name?: string;
      phone_number?: string;
      business_display_name?: string;
      status?: WhatsAppAccountStatus;
      provider?: string;
    },
  ) => api.patch<WhatsAppBusinessAccount>(`/whatsapp/accounts/${id}`, data),
  seedDemo: () => api.post<WhatsAppDemoSeedResult>("/whatsapp/demo/seed"),
  aiCapabilities: () => api.get<{ capabilities: { id: string; label: string; description: string; status: string }[] }>(
    "/whatsapp/ai/capabilities",
  ),
  listContactsExtended: (params?: { search?: string; skip?: number; limit?: number }) =>
    api.get<{ items: WhatsAppContactExtended[]; total: number }>("/whatsapp/contacts/extended", { params }),
  linkContactBuyer: (contactId: string, buyerId: string) =>
    api.post<{ contact_id: string; buyer_id: string; buyer_name: string }>(
      `/whatsapp/contacts/${contactId}/link-buyer`,
      { buyer_id: buyerId },
    ),
  linkContactCustomer: (contactId: string, customerId: string) =>
    api.post<{ contact_id: string; customer_id: string; customer_name: string }>(
      `/whatsapp/contacts/${contactId}/link-customer`,
      { customer_id: customerId },
    ),
  linkContactLead: (contactId: string, leadId: string) =>
    api.post<{ contact_id: string; lead_id: string; lead_name: string }>(
      `/whatsapp/contacts/${contactId}/link-lead`,
      { lead_id: leadId },
    ),
  linkProposal: (threadId: string, proposalId: string) =>
    api.post<{ thread_id: string; proposal_id: string; proposal_title: string }>(
      `/whatsapp/threads/${threadId}/link-proposal`,
      { proposal_id: proposalId },
    ),
  listContacts: (params?: { client_id?: string; search?: string; skip?: number; limit?: number }) =>
    api.get<{ items: CommunicationContact[]; total: number }>("/whatsapp/contacts", { params }),
  createContact: (data: {
    name: string;
    phone: string;
    client_id?: string | null;
    lead_id?: string | null;
    company?: string | null;
    country?: string | null;
    city?: string | null;
    industry?: string | null;
    preferred_language?: string | null;
    email?: string | null;
    notes?: string | null;
  }) => api.post<CommunicationContact>("/whatsapp/contacts", data),
  listThreads: (params?: {
    client_id?: string;
    contact_id?: string;
    status?: ThreadStatus;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: CommunicationThread[]; total: number }>("/whatsapp/threads", { params }),
  getThread: (id: string) => api.get<WhatsAppThreadDetail>(`/whatsapp/threads/${id}`),
  createThread: (data: {
    contact_id: string;
    title?: string | null;
    client_id?: string | null;
    lead_id?: string | null;
    deal_id?: string | null;
  }) => api.post<WhatsAppThreadDetail>("/whatsapp/threads", data),
  pasteInbound: (threadId: string, data: {
    message_text: string;
    sender_name?: string | null;
    original_language?: string | null;
    translated_text?: string | null;
  }) => api.post<CommunicationMessage>(`/whatsapp/threads/${threadId}/messages`, data),
  generateReply: (threadId: string, data?: { operator_notes?: string | null }) =>
    api.post<WhatsAppGenerateReplyResult>(
      `/whatsapp/threads/${threadId}/generate-reply`,
      data ?? {},
      { timeout: 90000 },
    ),
  markCopied: (messageId: string) =>
    api.post<{ message_id: string; copied_at: string }>(`/whatsapp/messages/${messageId}/mark-copied`),
  markManuallySent: (messageId: string) =>
    api.post<{ message_id: string; manual_sent_at: string; direction: string }>(
      `/whatsapp/messages/${messageId}/mark-manually-sent`,
    ),
  createLead: (threadId: string, data?: {
    name?: string | null;
    company?: string | null;
    interest?: string | null;
    notes?: string | null;
  }) =>
    api.post<{ lead_id: string; lead_name: string; thread_id: string; created: boolean; updated: boolean }>(
      `/whatsapp/threads/${threadId}/create-lead`,
      data ?? {},
    ),
  linkLead: (threadId: string, leadId: string) =>
    api.post<{ thread_id: string; lead_id: string; lead_name: string }>(
      `/whatsapp/threads/${threadId}/link-lead`,
      { lead_id: leadId },
    ),
  linkDeal: (threadId: string, dealId: string) =>
    api.post<{ thread_id: string; deal_id: string; deal_title: string; lead_id?: string }>(
      `/whatsapp/threads/${threadId}/link-deal`,
      { deal_id: dealId },
    ),
  // Legacy isolated-table endpoints (unified inbox compatibility)
  listLegacyContacts: (params?: { search?: string; skip?: number; limit?: number }) =>
    api.get<{ items: WhatsAppContact[]; total: number }>("/whatsapp/legacy/contacts", { params }),
  listLegacyThreads: (params?: { contact_id?: string; skip?: number; limit?: number }) =>
    api.get<{ items: WhatsAppThread[]; total: number }>("/whatsapp/legacy/threads", { params }),
  listLegacyMessages: (threadId: string, params?: { skip?: number; limit?: number }) =>
    api.get<{ items: WhatsAppMessage[]; total: number }>(`/whatsapp/legacy/messages/${threadId}`, { params }),
  createLegacyDraft: (data: { thread_id: string; operator_notes?: string | null }) =>
    api.post<WhatsAppDraftResult>("/whatsapp/legacy/draft", data),
  linkLegacyCrm: (data: { contact_id: string; crm_client_id: string }) =>
    api.post<{ contact_id: string; crm_client_id: string; crm_client_name: string; message: string }>(
      "/whatsapp/legacy/link-crm",
      data,
    ),
};

export type UnifiedInboxChannel = "wechat" | "wecom" | "whatsapp" | "email" | "manual" | "outreach";
export type UnifiedInboxPriority = "high" | "medium" | "low";

export interface UnifiedConversation {
  id: string;
  source: "thread" | "outreach" | "whatsapp";
  source_id: string;
  channel: UnifiedInboxChannel;
  contact_name: string;
  company?: string | null;
  country?: string | null;
  lead_id?: string | null;
  deal_id?: string | null;
  contact_id?: string | null;
  client_id?: string | null;
  last_message?: string | null;
  last_message_at?: string | null;
  unread_count: number;
  priority: UnifiedInboxPriority;
  status: string;
  lead_name?: string | null;
  deal_title?: string | null;
  thread_id?: string | null;
  outreach_id?: string | null;
  whatsapp_thread_id?: string | null;
  whatsapp_contact_id?: string | null;
  communication_health_score?: number | null;
  communication_classification?: string | null;
}

export interface UnifiedInboxAiPanel {
  summary: string;
  lead_status?: string | null;
  proposal_status?: string | null;
  recommended_action: string;
  has_linked_lead: boolean;
  has_linked_deal: boolean;
  proposal_count: number;
  can_create_lead: boolean;
  can_create_proposal: boolean;
  can_create_task: boolean;
}

export interface UnifiedConversationDetail {
  conversation: UnifiedConversation;
  thread?: CommunicationThread | null;
  messages: CommunicationMessage[];
  contact?: CommunicationContact | null;
  ai_panel: UnifiedInboxAiPanel;
  linked_outreach: { id: string; buyer_name?: string | null; status?: string }[];
  sales_assistant_recommendations?: SalesAssistantRecommendation[];
  communication_intelligence?: CommunicationIntelligenceDetail | null;
}

function unifiedInboxPath(id: string) {
  return `/unified-inbox/${encodeURIComponent(id)}`;
}

export const unifiedInboxApi = {
  list: (params?: {
    channel?: UnifiedInboxChannel;
    country?: string;
    company?: string;
    linked?: "linked" | "unlinked";
    unread?: boolean;
    priority?: UnifiedInboxPriority;
    search?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: UnifiedConversation[]; total: number }>("/unified-inbox", { params }),
  get: (id: string) => api.get<UnifiedConversationDetail>(unifiedInboxPath(id)),
  linkLead: (id: string, leadId: string) =>
    api.post<{ id: string; lead_id: string; lead_name: string; message: string }>(
      `${unifiedInboxPath(id)}/link-lead`,
      { lead_id: leadId },
    ),
  linkDeal: (id: string, dealId: string) =>
    api.post<{ id: string; deal_id: string; deal_title: string; message: string }>(
      `${unifiedInboxPath(id)}/link-deal`,
      { deal_id: dealId },
    ),
  createTask: (id: string, data: {
    task_type?: CommCrmTaskType;
    title?: string;
    description?: string;
    priority?: "high" | "medium" | "low";
    due_at?: string;
  }) =>
    api.post<{ id: string; task_id: string; title: string; task_type: string; message: string }>(
      `${unifiedInboxPath(id)}/create-task`,
      data,
    ),
};

export type PipelineStage =
  | "draft"
  | "internal_review"
  | "client_review"
  | "approved"
  | "scheduled"
  | "published"
  | "failed";

export const PIPELINE_STAGES: PipelineStage[] = [
  "draft",
  "internal_review",
  "client_review",
  "approved",
  "scheduled",
  "published",
  "failed",
];

export const PIPELINE_STAGE_LABELS: Record<PipelineStage, string> = {
  draft: "Draft",
  internal_review: "Internal Review",
  client_review: "Client Review",
  approved: "Approved",
  scheduled: "Scheduled",
  published: "Published",
  failed: "Failed",
};

export interface PipelineBoardCard {
  id: string;
  client_id: string;
  client_name?: string | null;
  campaign_id?: string | null;
  campaign_name?: string | null;
  platforms: string[];
  status: string;
  pipeline_stage: string;
  thumbnail_url?: string | null;
  media_url?: string | null;
  scheduled_for?: string | null;
  client_review_status?: string | null;
  approved_at?: string | null;
  published_at?: string | null;
  caption_preview?: string | null;
  has_failed_publish_attempt: boolean;
  allowed_transitions: string[];
}

export interface PipelineBoard {
  stages: Record<PipelineStage, PipelineBoardCard[]>;
  counts: Record<string, number>;
  total: number;
}

export const contentPipelineApi = {
  board: (params?: {
    client_id?: string;
    campaign_id?: string;
    platform?: string;
    status?: PipelineStage;
  }) => api.get<PipelineBoard>("/content-pipeline/board", { params }),
  transition: (
    contentId: string,
    data: { stage: PipelineStage; reason?: string; scheduled_for?: string },
  ) => api.patch<{ ok: boolean; content_id: string; pipeline_stage: string; status: string; message?: string }>(
    `/content-pipeline/items/${contentId}/stage`,
    data,
  ),
  retryPublish: (contentId: string) =>
    api.post<PublishingQueueActionResponse>(`/content-pipeline/items/${contentId}/retry-publish`),
};

export type MediaLibraryFileType =
  | "image"
  | "video"
  | "document"
  | "logo"
  | "certificate"
  | "catalog"
  | "other";

export interface MediaAssetAiLabels {
  objects?: string[];
  products?: string[];
  equipment?: string[];
  industries?: string[];
  source?: string | null;
}

export interface MediaAssetRelatedContent {
  id: string;
  status: string;
  source: string;
  created_at: string;
  caption_preview?: string | null;
}

export interface MediaAsset {
  id: string;
  client_id: string;
  campaign_id?: string | null;
  title: string;
  description?: string | null;
  file_type: MediaLibraryFileType | string;
  original_filename: string;
  storage_path: string;
  tags_json?: string[] | null;
  ai_labels_json?: MediaAssetAiLabels | null;
  uploaded_by?: string | null;
  created_at: string;
  client_name?: string | null;
  campaign_name?: string | null;
  url?: string | null;
  thumbnail_url?: string | null;
  usage_count: number;
  mime_type?: string | null;
  file_size?: number | null;
  related_content?: MediaAssetRelatedContent[];
}

export const MEDIA_LIBRARY_FILE_TYPES: MediaLibraryFileType[] = [
  "image",
  "video",
  "document",
  "logo",
  "certificate",
  "catalog",
  "other",
];

export const mediaLibraryApi = {
  list: (params?: {
    client_id?: string;
    campaign_id?: string;
    file_type?: string;
    search?: string;
    tag?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: MediaAsset[]; total: number }>("/media-library", { params }),
  get: (id: string) => api.get<MediaAsset>(`/media-library/${id}`),
  upload: (formData: FormData) =>
    api.post<MediaAsset>("/media-library/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 120000,
    }),
};

export const billingApi = {
  getClientBilling: (clientId: string) =>
    api.get<ClientBilling>(`/clients/${clientId}/billing`),
  updateClientBilling: (clientId: string, data: Partial<{
    plan_name: string | null;
    monthly_fee: number | null;
    monthly_post_limit: number | null;
    billing_status: BillingStatus;
    billing_cycle_start: string | null;
    billing_cycle_end: string | null;
  }>) => api.patch<ClientBilling>(`/clients/${clientId}/billing`, data),
  overview: () => api.get<BillingOverview>("/billing/overview"),
};

// ─── Subscription Billing v1 ─────────────────────────────────────────────────

export type SubscriptionStatus = "trial" | "active" | "suspended" | "expired" | "cancelled";
export type SubscriptionBillingCycle = "monthly" | "yearly";
export type InvoiceStatus = "draft" | "unpaid" | "paid" | "cancelled";

export interface SubscriptionPlan {
  id: string;
  name: string;
  code: string;
  monthly_price: number;
  yearly_price: number;
  max_users: number | null;
  max_leads: number | null;
  max_buyers: number | null;
  max_deals: number | null;
  features: string[] | null;
  created_at: string;
}

export interface SubscriptionRecord {
  id: string;
  tenant_id: string;
  plan_id: string;
  plan_name?: string | null;
  plan_code?: string | null;
  status: SubscriptionStatus;
  billing_cycle: SubscriptionBillingCycle;
  starts_at: string;
  expires_at?: string | null;
  created_at: string;
}

export interface SubscriptionInvoice {
  id: string;
  tenant_id: string;
  subscription_id: string;
  amount: number;
  currency: string;
  status: InvoiceStatus;
  invoice_date: string;
  due_date: string;
}

export interface UsageMetric {
  current: number;
  limit: number | null;
  utilization_pct: number | null;
}

export interface SubscriptionUsageSummary {
  tenant_id: string;
  users: UsageMetric;
  leads: UsageMetric;
  buyers: UsageMetric;
  deals: UsageMetric;
}

export interface SubscriptionBillingSummary {
  plan: SubscriptionPlan | null;
  status: SubscriptionStatus | null;
  next_renewal: string | null;
  monthly_price: number | null;
  usage_summary: SubscriptionUsageSummary;
}

export interface SubscriptionSummaryWidget {
  mrr: number;
  active_subscriptions: number;
  trial_subscriptions: number;
  plan_distribution: Record<string, number>;
  tenants_near_limit: number;
}

export const subscriptionBillingApi = {
  plans: () => pickBillingSessionClient().get<{ items: SubscriptionPlan[]; total: number }>("/billing/plans"),
  subscriptions: (params?: { tenant_id?: string; status?: string; skip?: number; limit?: number }) =>
    pickBillingSessionClient().get<{ items: SubscriptionRecord[]; total: number }>("/billing/subscriptions", { params }),
  invoices: (params?: { tenant_id?: string; status?: string; skip?: number; limit?: number }) =>
    pickBillingSessionClient().get<{ items: SubscriptionInvoice[]; total: number }>("/billing/invoices", { params }),
  usage: (tenantId: string) =>
    pickBillingSessionClient().get<SubscriptionUsageSummary>("/billing/usage", { params: { tenant_id: tenantId } }),
  summary: (tenantId: string) =>
    pickBillingSessionClient().get<SubscriptionBillingSummary>("/billing/summary", { params: { tenant_id: tenantId } }),
  summaryWidget: () => pickBillingSessionClient().get<SubscriptionSummaryWidget>("/billing/summary-widget"),
  createSubscription: (body: {
    tenant_id: string;
    plan_code: string;
    billing_cycle?: SubscriptionBillingCycle;
    status?: SubscriptionStatus;
  }) => pickBillingSessionClient().post<SubscriptionRecord>("/billing/create-subscription", body),
  activate: (subscriptionId: string) =>
    pickBillingSessionClient().post<SubscriptionRecord>("/billing/activate", { subscription_id: subscriptionId }),
  suspend: (subscriptionId: string) =>
    pickBillingSessionClient().post<SubscriptionRecord>("/billing/suspend", { subscription_id: subscriptionId }),
  cancel: (subscriptionId: string) =>
    pickBillingSessionClient().post<SubscriptionRecord>("/billing/cancel", { subscription_id: subscriptionId }),
};

// ─── Content Planner API ────────────────────────────────────────────────────

export type ContentPlanStatus = "draft" | "approved";
export type ContentPlanItemStatus = "planned" | "draft_created";
export type ContentPlanFormat = "image" | "video" | "carousel" | "story";

export interface ContentPlanItem {
  id: string;
  planned_date: string;
  theme: string;
  goal: string;
  platform_suggestions: string[];
  content_type: ContentPlanFormat;
  status: ContentPlanItemStatus;
  linked_content_id?: string | null;
  created_at: string;
}

export interface ContentPlan {
  id: string;
  client_id: string;
  company_name?: string | null;
  month: number;
  year: number;
  title: string;
  status: ContentPlanStatus;
  posts_per_month: number;
  items: ContentPlanItem[];
  created_at: string;
  updated_at: string;
}

export const contentPlannerApi = {
  generate: (data: {
    client_id: string;
    month: number;
    year: number;
    posts_per_month: number;
  }) => api.post<ContentPlan>("/content-planner/generate", data),
  findPlan: (params: { client_id: string; month: number; year: number }) =>
    api.get<ContentPlan | null>("/content-planner/plans", { params }),
  getPlan: (planId: string) => api.get<ContentPlan>(`/content-planner/plans/${planId}`),
  updatePlan: (planId: string, data: { title?: string }) =>
    api.patch<ContentPlan>(`/content-planner/plans/${planId}`, data),
  approvePlan: (planId: string) =>
    api.post<ContentPlan>(`/content-planner/plans/${planId}/approve`),
  createDraftFromItem: (itemId: string, data?: { generate_ai?: boolean }) =>
    api.post<{
      ok: boolean;
      created: boolean;
      message: string;
      plan_item_id: string;
      content_id: string;
      ai_generated: boolean;
      ai_error?: string | null;
    }>(`/content-planner/items/${itemId}/create-draft`, data ?? { generate_ai: true }),
};

// ─── Client Brief Intake API ────────────────────────────────────────────────────

export type ClientBriefStatus = "new" | "reviewing" | "changes_requested" | "approved" | "converted";
export type ClientBriefCampaignGoal = "awareness" | "leads" | "sales" | "brand_trust";
export type ClientBriefLanguage = "zh" | "en" | "ru" | "uz";
export type ClientBriefMediaType = "image" | "carousel" | "reel" | "story" | "short_video";
export type ClientBriefPlanStatus = "draft" | "approved";

export interface ClientBriefPlanCaptions {
  ru: string;
  uz: string;
  en: string;
  zh: string;
}

export interface ClientBriefPlanItem {
  theme: string;
  goal: string;
  platform: string;
  media_type: ClientBriefMediaType;
  captions: ClientBriefPlanCaptions;
  hashtags: string;
  cta: string;
  priority: "high" | "medium" | "low";
}

export interface ClientBriefContentPlan {
  summary: string;
  plan_status: ClientBriefPlanStatus;
  items: ClientBriefPlanItem[];
  source?: "ai" | "fallback" | "manual";
}

export interface ClientBrief {
  id: string;
  client_id: string;
  company_name?: string | null;
  tenant_id?: string | null;
  tenant_name?: string | null;
  product_name: string;
  product_description?: string | null;
  target_market: string;
  campaign_goal: ClientBriefCampaignGoal | string;
  language: string;
  languages: string[];
  desired_platforms: string[];
  media_urls: string[];
  notes?: string | null;
  status: ClientBriefStatus;
  ai_content_plan?: string | null;
  admin_feedback?: string | null;
  submitted_by?: string | null;
  created_at: string;
  updated_at: string;
}

export const clientBriefApi = {
  submit: (data: {
    client_id?: string;
    product_name: string;
    product_description?: string;
    target_market: string;
    campaign_goal: ClientBriefCampaignGoal;
    language?: ClientBriefLanguage;
    languages?: ClientBriefLanguage[];
    desired_platforms: string[];
    media_urls: string[];
    notes?: string;
  }) => api.post<ClientBrief>("/client-briefs", data),
  listMine: (params?: { skip?: number; limit?: number }) =>
    api.get<{ items: ClientBrief[]; total: number }>("/client-briefs", { params }),
  listAll: (params?: { skip?: number; limit?: number }) =>
    adminApi.get<{ items: ClientBrief[]; total: number }>("/client-briefs", { params }),
  get: (id: string) => api.get<ClientBrief>(`/client-briefs/${id}`),
  getAdmin: (id: string) => adminApi.get<ClientBrief>(`/client-briefs/${id}`),
  markReviewed: (id: string) =>
    adminApi.post<ClientBrief>(`/client-briefs/${id}/mark-reviewed`),
  approveBrief: (id: string) =>
    adminApi.post<ClientBrief>(`/client-briefs/${id}/approve-brief`),
  requestChanges: (id: string, feedback: string) =>
    adminApi.post<ClientBrief>(`/client-briefs/${id}/request-changes`, { feedback }),
  generatePlan: (id: string) =>
    adminApi.post<ClientBrief>(`/client-briefs/${id}/generate-plan`),
  updatePlan: (id: string, plan: ClientBriefContentPlan) =>
    adminApi.put<ClientBrief>(`/client-briefs/${id}/plan`, { plan }),
  approvePlan: (id: string) =>
    adminApi.post<ClientBrief>(`/client-briefs/${id}/approve-plan`),
  addMedia: (id: string, media_urls: string[]) =>
    api.post<ClientBrief>(`/client-briefs/${id}/add-media`, { media_urls }),
  convertToTasks: (id: string) =>
    adminApi.post<{
      brief: ClientBrief;
      tasks_created: number;
      content_items_created: number;
    }>(`/client-briefs/${id}/convert-to-tasks`),
};

// ─── Content Factory API ──────────────────────────────────────────────────────

export type FactoryContentType =
  | "reel"
  | "post"
  | "story"
  | "carousel"
  | "article"
  | "telegram"
  | "linkedin";

export type FactoryReviewStatus =
  | "draft"
  | "generated"
  | "needs_review"
  | "approved"
  | "scheduled"
  | "published"
  | "rejected";

export type FactoryContentCategory =
  | "product_announcement"
  | "factory_news"
  | "production_process"
  | "customer_success"
  | "promotion"
  | "exhibition"
  | "educational"
  | "export_opportunity"
  | "corporate_update"
  | "other";

export type FactorySupportedLanguage = "ru" | "uz" | "en" | "zh";

export interface ContentFactoryQualityScores {
  quality_score: number;
  readability_score: number;
  engagement_score: number;
  completeness_score: number;
  overall_score: number;
  recommendations?: string[];
}

export interface ContentFactoryItem {
  id: string;
  content_type: FactoryContentType;
  theme: string;
  angle: string;
  title: string;
  headline?: string | null;
  platforms: Platform[];
  hashtags?: string | null;
  cta_suggestion?: string | null;
  preview_caption?: string | null;
  captions?: Record<string, string> | null;
  generated_content_id?: string | null;
  review_status?: FactoryReviewStatus;
  quality_scores?: ContentFactoryQualityScores | null;
  platform_variants?: Record<string, { text: string; format: string }> | null;
  scheduled_for?: string | null;
  created_at: string;
}

export interface ContentFactory {
  id: string;
  client_id: string;
  company_name?: string | null;
  source_media_id?: string | null;
  source_media_url?: string | null;
  source_media_type?: string | null;
  source_content_id?: string | null;
  status: "draft" | "generated" | "failed";
  input_type?: string | null;
  input_text?: string | null;
  content_category?: FactoryContentCategory | null;
  target_languages?: FactorySupportedLanguage[];
  items: ContentFactoryItem[];
  created_at: string;
}

export interface ContentFactoryItemSummary {
  id: string;
  factory_id: string;
  company_name?: string | null;
  content_type: string;
  theme: string;
  title: string;
  headline?: string | null;
  platforms: string[];
  review_status: FactoryReviewStatus;
  preview_caption?: string | null;
  generated_content_id?: string | null;
  overall_score?: number | null;
  scheduled_for?: string | null;
  created_at: string;
}

export interface ContentFactoryDashboard {
  content_queue: ContentFactoryItemSummary[];
  generated_content: ContentFactoryItemSummary[];
  approval_queue: ContentFactoryItemSummary[];
  publishing_queue: ContentFactoryItemSummary[];
  kpis: {
    content_created: number;
    content_published: number;
    languages_used: Record<string, number>;
    approval_rate: number;
    publishing_rate: number;
    top_content_types: Array<{ type: string; count: number }>;
    factory_drafts: number;
  };
  status_counts: Record<string, number>;
}

export const contentFactoryApi = {
  dashboard: (clientId?: string) =>
    api.get<ContentFactoryDashboard>("/content-factory/dashboard", {
      params: clientId ? { client_id: clientId } : undefined,
    }),
  library: (params?: Record<string, string | number | undefined>) =>
    api.get<{ total: number; items: ContentFactoryItemSummary[] }>("/content-factory/library", { params }),
  review: (params?: { client_id?: string; status?: FactoryReviewStatus }) =>
    api.get<{ items: ContentFactoryItem[]; grouped: Record<string, ContentFactoryItem[]>; statuses: string[] }>(
      "/content-factory/review",
      { params },
    ),
  list: (clientId?: string) =>
    api.get<{ factories: Array<{ id: string; company_name?: string; item_count: number; created_at: string }> }>(
      "/content-factory/list",
      { params: clientId ? { client_id: clientId } : undefined },
    ),
  recommendations: (clientId: string) =>
    api.get<{
      best_posting_times: string[];
      missing_content_categories: Array<{ category: string; label: string }>;
      suggested_campaigns: Array<{ title: string; description: string; suggested_platforms: string[] }>;
      suggested_languages: string[];
      suggested_buyer_content: string[];
    }>(`/content-factory/recommendations/${clientId}`),
  demo: (clientId: string) =>
    api.get<{ samples: ContentFactoryItemSummary[]; sample_campaigns: Array<{ name: string; platforms: string[]; languages: string[] }> }>(
      `/content-factory/demo/${clientId}`,
    ),
  generate: (data: {
    client_id: string;
    source_media_id?: string;
    source_content_id?: string | null;
    number_of_variations?: number;
    content_category?: FactoryContentCategory;
    target_languages?: FactorySupportedLanguage[];
    input_text?: string;
    input_type?: string;
    target_platforms?: string[];
  }) => api.post<ContentFactory>("/content-factory/generate", data),
  generateText: (data: {
    client_id: string;
    input_text: string;
    source_media_id?: string;
    number_of_variations?: number;
    content_category?: FactoryContentCategory;
    target_languages?: FactorySupportedLanguage[];
    input_type?: string;
  }) => api.post<ContentFactory>("/content-factory/generate-text", data),
  fromTelegram: (contentId: string, data?: { number_of_variations?: number; target_languages?: FactorySupportedLanguage[] }) =>
    api.post<ContentFactory>(`/content-factory/from-telegram/${contentId}`, data ?? {}),
  get: (factoryId: string) => api.get<ContentFactory>(`/content-factory/${factoryId}`),
  updateReview: (itemId: string, data: { review_status: FactoryReviewStatus; notes?: string }) =>
    api.patch<{ ok: boolean; item_id: string; review_status: string }>(`/content-factory/items/${itemId}/review`, data),
  schedule: (itemId: string, data: { scheduled_for: string; platforms?: string[] }) =>
    api.post<{ ok: boolean; calendar_entry_id: string; scheduled_for: string }>(
      `/content-factory/items/${itemId}/schedule`,
      data,
    ),
  createDraftFromItem: (itemId: string, data?: { generate_ai?: boolean }) =>
    api.post<{
      ok: boolean;
      created: boolean;
      message: string;
      factory_item_id: string;
      content_id: string;
      ai_applied: boolean;
      ai_error?: string | null;
    }>(`/content-factory/items/${itemId}/create-draft`, data ?? { generate_ai: true }),
};

// ─── CRM API ──────────────────────────────────────────────────────────────────

export type LeadSource = "manual" | "telegram" | "website" | "instagram" | "referral" | "landing_page" | "other";

export type LeadStatus =
  | "new"
  | "contacted"
  | "qualified"
  | "proposal_sent"
  | "negotiation"
  | "won"
  | "lost";

export type LeadPriority = "high" | "medium" | "low";
export type QualificationLevel = "cold" | "warm" | "hot" | "qualified" | "opportunity";

export type CrmActivityType = "note" | "call" | "message" | "meeting" | "proposal" | "follow_up";

export interface LeadInsights {
  score: number;
  level: QualificationLevel;
  strengths: string[];
  risks: string[];
  next_action: string;
}

export interface LeadIntelligenceHotLead {
  lead_id: string;
  name: string;
  company?: string | null;
  lead_score: number;
  qualification_level: QualificationLevel;
  recommended_action?: string | null;
  status: LeadStatus;
}

export interface LeadIntelligenceMetrics {
  hot_leads: number;
  qualified_leads: number;
  neglected_leads: number;
  leads_without_activity: number;
  top_hot_leads: LeadIntelligenceHotLead[];
}

export interface LeadScoreResult {
  lead_id: string;
  insights: LeadInsights;
  ai_summary?: string | null;
  recommended_action?: string | null;
  demo_mode?: boolean;
  lead: CrmLead;
}

export interface CrmLead {
  id: string;
  client_id: string;
  company_name?: string | null;
  name: string;
  company?: string | null;
  phone?: string | null;
  telegram?: string | null;
  email?: string | null;
  source: LeadSource;
  language?: string | null;
  interest?: string | null;
  notes?: string | null;
  status: LeadStatus;
  priority: LeadPriority;
  estimated_value?: number | string | null;
  next_follow_up_at?: string | null;
  attribution_source?: string | null;
  attribution_campaign?: string | null;
  attribution_notes?: string | null;
  attributed_by?: string | null;
  attribution_link_id?: string | null;
  lead_score?: number | null;
  qualification_level?: QualificationLevel | null;
  ai_summary?: string | null;
  recommended_action?: string | null;
  last_scored_at?: string | null;
  lead_insights?: LeadInsights | null;
  revenue_attribution?: RevenueAttributionLeadSummary | null;
  created_at: string;
  updated_at: string;
}

export interface CrmActivity {
  id: string;
  lead_id: string;
  type: CrmActivityType;
  content: string;
  created_at: string;
}

export interface CrmPipelineColumn {
  status: LeadStatus;
  label: string;
  leads: CrmLead[];
  count: number;
}

export interface CrmPipeline {
  columns: CrmPipelineColumn[];
  total: number;
  counts: Record<string, number>;
  errors?: string[];
}

export interface CrmExtractResult {
  name?: string | null;
  company?: string | null;
  phone?: string | null;
  telegram?: string | null;
  email?: string | null;
  interest?: string | null;
  language?: string | null;
  priority: LeadPriority;
  suggested_next_step?: string | null;
  source: string;
}

export type MessagePurpose =
  | "first_contact"
  | "follow_up"
  | "proposal"
  | "objection_reply"
  | "meeting_reminder";

export interface CrmAiSuggestNextStep {
  recommended_next_step: string;
  suggested_message: string;
  suggested_status_change?: LeadStatus | null;
  follow_up_date?: string | null;
  reasoning: string;
  activity_id: string;
  source: string;
}

export interface CrmAiGeneratedMessage {
  message_text: string;
  tone: string;
  cta: string;
  purpose: MessagePurpose;
  language: string;
  source: string;
}

export type ProposalStatus = "draft" | "sent" | "accepted" | "rejected";

export type DocumentType = "contract" | "invoice" | "offer";
export type DocumentStatus = "draft" | "sent" | "signed" | "paid" | "canceled";

export interface CrmProposal {
  id: string;
  lead_id: string;
  client_id: string;
  lead_name?: string | null;
  title: string;
  language: string;
  status: ProposalStatus;
  proposal_text: string;
  estimated_value?: number | string | null;
  valid_until?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrmDocument {
  id: string;
  proposal_id: string;
  lead_id: string;
  client_id: string;
  lead_name?: string | null;
  proposal_title?: string | null;
  document_type: DocumentType;
  title: string;
  language: string;
  status: DocumentStatus;
  document_text: string;
  amount?: number | string | null;
  currency: string;
  due_date?: string | null;
  created_at: string;
  updated_at: string;
}

export type DealStatus =
  | "new"
  | "proposal"
  | "contract"
  | "invoice"
  | "waiting_payment"
  | "won"
  | "lost";

export type DealEventType =
  | "activity"
  | "proposal"
  | "contract"
  | "invoice"
  | "note"
  | "status_change";

export type RiskLevel = "low" | "medium" | "high";

export interface CrmDeal {
  id: string;
  lead_id: string;
  client_id: string;
  lead_name?: string | null;
  client_name?: string | null;
  title: string;
  status: DealStatus;
  expected_value?: number | string | null;
  probability: number;
  expected_close_date?: string | null;
  deal_amount?: number | string | null;
  currency?: string;
  commission_percent?: number | string | null;
  commission_amount?: number | string | null;
  commission_status?: CommissionStatus | null;
  days_in_pipeline: number;
  created_at: string;
  updated_at: string;
}

export interface CrmDealEvent {
  id: string;
  deal_id: string;
  event_type: DealEventType;
  title: string;
  payload_json: Record<string, unknown>;
  created_at: string;
}

export interface CrmDealDetail extends CrmDeal {
  lead: CrmLead;
  proposals: CrmProposal[];
  contracts: CrmDocument[];
  invoices: CrmDocument[];
  activities: CrmActivity[];
  events: CrmDealEvent[];
}

export interface CrmDealHealth {
  deal_score: number;
  risk_level: RiskLevel;
  recommended_action: string;
  reasoning: string;
  source: string;
}

export const crmApi = {
  pipeline: (params?: { client_id?: string }) =>
    api.get<CrmPipeline>("/crm/pipeline", { params }),
  listLeads: (params?: {
    client_id?: string;
    status?: LeadStatus;
    priority?: LeadPriority;
    source?: LeadSource;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: CrmLead[]; total: number }>("/crm/leads", { params }),
  getLead: (id: string) => api.get<CrmLead>(`/crm/leads/${id}`),
  createLead: (data: {
    client_id: string;
    name: string;
    company?: string | null;
    phone?: string | null;
    telegram?: string | null;
    email?: string | null;
    source?: LeadSource;
    language?: string | null;
    interest?: string | null;
    notes?: string | null;
    status?: LeadStatus;
    priority?: LeadPriority;
    estimated_value?: number | null;
    next_follow_up_at?: string | null;
    attribution_link_id?: string | null;
  }) => api.post<CrmLead>("/crm/leads", data),
  updateLead: (id: string, data: Partial<{
    name: string;
    company: string | null;
    phone: string | null;
    telegram: string | null;
    email: string | null;
    source: LeadSource;
    language: string | null;
    interest: string | null;
    notes: string | null;
    status: LeadStatus;
    priority: LeadPriority;
    estimated_value: number | null;
    next_follow_up_at: string | null;
    attribution_link_id: string | null;
  }>) => api.patch<CrmLead>(`/crm/leads/${id}`, data),
  deleteLead: (id: string) => api.delete(`/crm/leads/${id}`),
  listActivities: (leadId: string) =>
    api.get<{ items: CrmActivity[]; total: number }>(`/crm/leads/${leadId}/activities`),
  addActivity: (leadId: string, data: { type: CrmActivityType; content: string }) =>
    api.post<CrmActivity>(`/crm/leads/${leadId}/activities`, data),
  extractLead: (data: { client_id: string; text: string }) =>
    api.post<CrmExtractResult>("/crm/extract-lead", data),
  suggestNextStep: (leadId: string) =>
    api.post<CrmAiSuggestNextStep>(`/crm/leads/${leadId}/ai-suggest-next-step`),
  generateMessage: (leadId: string, data: { purpose: MessagePurpose; language?: string }) =>
    api.post<CrmAiGeneratedMessage>(`/crm/leads/${leadId}/ai-generate-message`, {
      language: data.language ?? "ru",
      purpose: data.purpose,
    }),
  saveMessageActivity: (
    leadId: string,
    data: { message_text: string; purpose: MessagePurpose; tone?: string },
  ) => api.post<CrmActivity>(`/crm/leads/${leadId}/ai-save-message`, data),
  scoreLead: (leadId: string) => api.post<LeadScoreResult>(`/crm/leads/${leadId}/score`),
  rescoreLeads: (data?: { client_id?: string; limit?: number }) =>
    api.post<{ scored: number; failed: number; message: string }>("/crm/leads/rescore", data ?? {}),
  intelligenceMetrics: (params?: { client_id?: string }) =>
    api.get<LeadIntelligenceMetrics>("/crm/leads/intelligence-metrics", { params }),
  listProposals: (leadId: string) =>
    api.get<{ items: CrmProposal[]; total: number }>(`/crm/leads/${leadId}/proposals`),
  generateProposal: (leadId: string, data?: { language?: string }) =>
    api.post<CrmProposal>(`/crm/leads/${leadId}/proposals/generate`, data ?? {}),
  getProposal: (id: string) => api.get<CrmProposal>(`/crm/proposals/${id}`),
  updateProposal: (
    id: string,
    data: Partial<{
      title: string;
      proposal_text: string;
      status: ProposalStatus;
      estimated_value: number | null;
      valid_until: string | null;
      language: string;
    }>,
  ) => api.patch<CrmProposal>(`/crm/proposals/${id}`, data),
  listDocuments: (proposalId: string) =>
    api.get<{ items: CrmDocument[]; total: number }>(`/crm/proposals/${proposalId}/documents`),
  generateDocument: (
    proposalId: string,
    data: { document_type: DocumentType; language?: string },
  ) => api.post<CrmDocument>(`/crm/proposals/${proposalId}/documents/generate`, data),
  getDocument: (id: string) => api.get<CrmDocument>(`/crm/documents/${id}`),
  updateDocument: (
    id: string,
    data: Partial<{
      title: string;
      document_text: string;
      status: DocumentStatus;
      amount: number | null;
      currency: string;
      due_date: string | null;
      language: string;
    }>,
  ) => api.patch<CrmDocument>(`/crm/documents/${id}`, data),
  listDeals: (params?: { client_id?: string; status?: DealStatus }) =>
    api.get<{ items: CrmDeal[]; total: number }>("/crm/deals", { params }),
  createDeal: (data: {
    lead_id: string;
    client_id: string;
    title: string;
    status?: DealStatus;
    expected_value?: number | null;
    probability?: number;
    expected_close_date?: string | null;
  }) => api.post<CrmDeal>("/crm/deals", data),
  getDeal: (id: string) => api.get<CrmDealDetail>(`/crm/deals/${id}`),
  getDealForLead: (leadId: string) => api.get<CrmDealDetail>(`/crm/leads/${leadId}/deal`),
  updateDeal: (
    id: string,
    data: Partial<{
      title: string;
      status: DealStatus;
      expected_value: number | null;
      probability: number;
      expected_close_date: string | null;
    }>,
  ) => api.patch<CrmDeal>(`/crm/deals/${id}`, data),
  addDealEvent: (
    dealId: string,
    data: { event_type?: DealEventType; title: string; payload_json?: Record<string, unknown> },
  ) => api.post<CrmDealEvent>(`/crm/deals/${dealId}/events`, data),
  assessDealHealth: (dealId: string) =>
    api.post<CrmDealHealth>(`/crm/deals/${dealId}/health`),
  markDealWon: (
    dealId: string,
    data: { deal_amount: number; commission_percent: number; currency?: string; partner_commission_percent?: number },
  ) => api.post<CrmDeal>(`/crm/deals/${dealId}/mark-won`, data),
};

// ─── Sales CRM (tenant-scoped) ────────────────────────────────────────────────

export type SalesLeadStatus = "new" | "contacted" | "qualified" | "converted" | "lost";
export type SalesLeadPriority = "high" | "medium" | "low";
export type SalesLeadSource = "manual" | "website" | "referral" | "exhibition" | "social" | "other";
export type SalesDealStage =
  | "new_lead"
  | "contacted"
  | "negotiation"
  | "proposal_sent"
  | "won"
  | "lost";
export type SalesActivityType = "call" | "email" | "meeting" | "note" | "task" | "other";

export const SALES_DEAL_STAGES: SalesDealStage[] = [
  "new_lead",
  "contacted",
  "negotiation",
  "proposal_sent",
  "won",
  "lost",
];

export interface SalesCustomer {
  id: string;
  tenant_id: string;
  name: string;
  company: string | null;
  phone: string | null;
  email: string | null;
  telegram: string | null;
  whatsapp: string | null;
  wechat: string | null;
  country: string | null;
  city: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  deal_count?: number;
  lead_count?: number;
}

export interface SalesLead {
  id: string;
  tenant_id: string;
  customer_id: string | null;
  name: string;
  company: string | null;
  phone: string | null;
  email: string | null;
  telegram: string | null;
  whatsapp: string | null;
  wechat: string | null;
  country: string | null;
  city: string | null;
  source: SalesLeadSource;
  status: SalesLeadStatus;
  priority: SalesLeadPriority;
  notes: string | null;
  assigned_to: string | null;
  created_at: string;
  updated_at: string;
}

export interface SalesDeal {
  id: string;
  tenant_id: string;
  customer_id: string | null;
  lead_id: string | null;
  title: string;
  value: number | null;
  currency: string;
  stage: SalesDealStage;
  probability: number;
  expected_close_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  customer_name?: string | null;
  lead_name?: string | null;
}

export interface SalesActivity {
  id: string;
  tenant_id: string;
  type: SalesActivityType;
  title: string;
  description: string | null;
  lead_id: string | null;
  customer_id: string | null;
  deal_id: string | null;
  activity_date: string;
  created_by: string | null;
  created_at: string;
}

export interface SalesDashboardStats {
  total_leads: number;
  new_leads: number;
  qualified_leads: number;
  total_deals: number;
  pipeline_value: number;
  won_deals: number;
  won_value: number;
  total_customers: number;
  leads_by_status: Record<string, number>;
  leads_by_source: Record<string, number>;
  pipeline_by_stage: Array<{ stage: SalesDealStage; count: number; total_value: number }>;
}

export interface SalesDashboard {
  stats: SalesDashboardStats;
  recent_activities: SalesActivity[];
}

export const salesCrmApi = {
  dashboard: () => api.get<SalesDashboard>("/sales-crm/dashboard"),
  listCustomers: (params?: { search?: string; skip?: number; limit?: number }) =>
    api.get<{ items: SalesCustomer[]; total: number }>("/sales-crm/customers", { params }),
  getCustomer: (id: string) => api.get<SalesCustomer>(`/sales-crm/customers/${id}`),
  createCustomer: (data: Omit<SalesCustomer, "id" | "tenant_id" | "created_at" | "updated_at">) =>
    api.post<SalesCustomer>("/sales-crm/customers", data),
  updateCustomer: (id: string, data: Partial<SalesCustomer>) =>
    api.patch<SalesCustomer>(`/sales-crm/customers/${id}`, data),
  deleteCustomer: (id: string) => api.delete(`/sales-crm/customers/${id}`),
  listLeads: (params?: {
    search?: string;
    status?: SalesLeadStatus;
    source?: SalesLeadSource;
    priority?: SalesLeadPriority;
    customer_id?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: SalesLead[]; total: number }>("/sales-crm/leads", { params }),
  getLead: (id: string) => api.get<SalesLead>(`/sales-crm/leads/${id}`),
  createLead: (data: Omit<SalesLead, "id" | "tenant_id" | "created_at" | "updated_at">) =>
    api.post<SalesLead>("/sales-crm/leads", data),
  updateLead: (id: string, data: Partial<SalesLead>) =>
    api.patch<SalesLead>(`/sales-crm/leads/${id}`, data),
  deleteLead: (id: string) => api.delete(`/sales-crm/leads/${id}`),
  listDeals: (params?: {
    stage?: SalesDealStage;
    customer_id?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: SalesDeal[]; total: number }>("/sales-crm/deals", { params }),
  getDeal: (id: string) => api.get<SalesDeal>(`/sales-crm/deals/${id}`),
  createDeal: (data: Omit<SalesDeal, "id" | "tenant_id" | "created_at" | "updated_at" | "customer_name" | "lead_name">) =>
    api.post<SalesDeal>("/sales-crm/deals", data),
  updateDeal: (id: string, data: Partial<SalesDeal>) =>
    api.patch<SalesDeal>(`/sales-crm/deals/${id}`, data),
  moveDealStage: (id: string, stage: SalesDealStage) =>
    api.patch<SalesDeal>(`/sales-crm/deals/${id}/stage`, { stage }),
  deleteDeal: (id: string) => api.delete(`/sales-crm/deals/${id}`),
  listActivities: (params?: {
    lead_id?: string;
    customer_id?: string;
    deal_id?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: SalesActivity[]; total: number }>("/sales-crm/activities", { params }),
  createActivity: (data: Omit<SalesActivity, "id" | "tenant_id" | "created_at" | "created_by">) =>
    api.post<SalesActivity>("/sales-crm/activities", data),
  getLeadRelated: (id: string) => api.get<PlatformRelationships>(`/sales-crm/leads/${id}/related`),
  getDealRelated: (id: string) => api.get<PlatformRelationships>(`/sales-crm/deals/${id}/related`),
};

// ─── Platform cross-module relationships ───────────────────────────────────────

export type RelatedEntityType =
  | "content"
  | "lead"
  | "buyer"
  | "deal"
  | "proposal"
  | "communication"
  | "customer";

export interface RelatedEntityItem {
  entity_type: RelatedEntityType;
  entity_id: string;
  label: string;
  href?: string | null;
  status?: string | null;
  meta?: Record<string, unknown> | null;
  updated_at?: string | null;
}

export interface PlatformRelationships {
  entity_type: string;
  entity_id: string;
  related_content: RelatedEntityItem[];
  related_leads: RelatedEntityItem[];
  related_buyers: RelatedEntityItem[];
  related_deals: RelatedEntityItem[];
  related_proposals: RelatedEntityItem[];
  related_communications: RelatedEntityItem[];
  related_customers: RelatedEntityItem[];
}

export const platformRelationshipsApi = {
  get: (entityType: "lead" | "deal" | "proposal" | "buyer" | "content", entityId: string) => {
    const paths: Record<string, string> = {
      lead: `/sales-crm/leads/${entityId}/related`,
      deal: `/sales-crm/deals/${entityId}/related`,
      proposal: `/sales-crm/proposals/${entityId}/related`,
      buyer: `/buyers/${entityId}/related`,
      content: `/content/${entityId}/related`,
    };
    return api.get<PlatformRelationships>(paths[entityType]);
  },
  updateContentLinks: (
    contentId: string,
    links: {
      linked_sales_lead_id?: string | null;
      linked_buyer_id?: string | null;
      linked_sales_deal_id?: string | null;
    },
  ) => api.patch<ContentItem>(`/content/${contentId}/links`, links),
};

// ─── Sales CRM Commercial Proposals ───────────────────────────────────────────

export type SalesProposalStatus = "draft" | "sent" | "viewed" | "accepted" | "rejected" | "expired";

export interface SalesProposalItem {
  id: string;
  proposal_id: string;
  product_or_service_name: string;
  description: string | null;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  sort_order: number;
  created_at: string;
}

export interface SalesProposalStatusEvent {
  status: SalesProposalStatus;
  at: string;
  note?: string | null;
}

export interface SalesProposal {
  id: string;
  tenant_id: string;
  proposal_number: string;
  title: string;
  customer_id: string | null;
  lead_id: string | null;
  deal_id: string | null;
  issue_date: string;
  valid_until: string | null;
  currency: string;
  subtotal: number;
  discount: number;
  tax: number;
  total: number;
  status: SalesProposalStatus;
  notes: string | null;
  terms: string | null;
  status_history: SalesProposalStatusEvent[];
  created_at: string;
  updated_at: string;
  items: SalesProposalItem[];
  customer_name?: string | null;
  lead_name?: string | null;
  deal_title?: string | null;
}

export type SalesProposalItemInput = Omit<
  SalesProposalItem,
  "id" | "proposal_id" | "total" | "sort_order" | "created_at"
>;

export const salesProposalsApi = {
  list: (params?: {
    search?: string;
    status?: SalesProposalStatus;
    customer_id?: string;
    deal_id?: string;
    date_from?: string;
    date_to?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: SalesProposal[]; total: number }>("/sales-crm/proposals", { params }),
  get: (id: string) => api.get<SalesProposal>(`/sales-crm/proposals/${id}`),
  create: (data: {
    title: string;
    customer_id?: string | null;
    lead_id?: string | null;
    deal_id?: string | null;
    issue_date: string;
    valid_until?: string | null;
    currency?: string;
    discount?: number;
    tax?: number;
    notes?: string | null;
    terms?: string | null;
    items: SalesProposalItemInput[];
  }) => api.post<SalesProposal>("/sales-crm/proposals", data),
  createFromLead: (leadId: string) =>
    api.post<SalesProposal>(`/sales-crm/proposals/from-lead/${leadId}`),
  createFromDeal: (dealId: string) =>
    api.post<SalesProposal>(`/sales-crm/proposals/from-deal/${dealId}`),
  update: (id: string, data: Partial<{
    title: string;
    customer_id: string | null;
    lead_id: string | null;
    deal_id: string | null;
    issue_date: string;
    valid_until: string | null;
    currency: string;
    discount: number;
    tax: number;
    notes: string | null;
    terms: string | null;
    items: SalesProposalItemInput[];
  }>) => api.patch<SalesProposal>(`/sales-crm/proposals/${id}`, data),
  updateStatus: (id: string, status: SalesProposalStatus) =>
    api.patch<SalesProposal>(`/sales-crm/proposals/${id}/status`, { status }),
  duplicate: (id: string) => api.post<SalesProposal>(`/sales-crm/proposals/${id}/duplicate`),
  delete: (id: string) => api.delete(`/sales-crm/proposals/${id}`),
};

// ─── Factory Growth Center ────────────────────────────────────────────────────

export type GrowthCenterHealthStatus = "healthy" | "warning" | "critical";
export type GrowthCenterRecommendationPriority = "urgent" | "high" | "medium" | "low";
export type GrowthCenterTimelineType =
  | "lead"
  | "buyer"
  | "proposal"
  | "communication"
  | "deal_change"
  | "activity";
export type GrowthCenterExportFormat = "pdf" | "excel";

export interface GrowthCenterDistributionItem {
  label: string;
  count: number;
}

export interface GrowthCenterOverviewKpis {
  total_leads: number;
  total_buyers: number;
  active_buyers: number;
  active_leads: number;
  total_deals: number;
  deals_won: number;
  deals_lost: number;
  total_proposal_value: number;
  pipeline_value: number;
  expected_revenue: number;
  follow_ups_due: number;
}

export interface GrowthCenterTrendPoint {
  period: string;
  count: number;
}

export interface GrowthCenterMarketInsights {
  buyers_by_country: GrowthCenterDistributionItem[];
  buyers_by_industry: GrowthCenterDistributionItem[];
  leads_by_source: GrowthCenterDistributionItem[];
  proposal_acceptance_rate: number;
  buyer_growth_trend: GrowthCenterTrendPoint[];
}

export interface GrowthCenterHealthIndicator {
  score: number;
  status: GrowthCenterHealthStatus;
  label: string;
  summary: string;
}

export interface GrowthCenterHealthScores {
  lead_health: GrowthCenterHealthIndicator;
  buyer_health: GrowthCenterHealthIndicator;
  deal_health: GrowthCenterHealthIndicator;
  communication_health: GrowthCenterHealthIndicator;
}

export interface GrowthCenterRecommendation {
  id: string;
  priority: GrowthCenterRecommendationPriority;
  title: string;
  expected_impact: string;
  reason: string;
  recommended_action: string;
  href: string | null;
  entity_type: string | null;
  entity_id: string | null;
}

export interface GrowthCenterOpportunity {
  id: string;
  buyer: string;
  country: string | null;
  potential_value: number;
  currency: string;
  deal_stage: string;
  probability: number;
  score: number;
}

export interface GrowthCenterTimelineItem {
  id: string;
  type: GrowthCenterTimelineType;
  title: string;
  subtitle: string | null;
  occurred_at: string;
  href: string | null;
}

export interface GrowthCenterExportFormatInfo {
  format: GrowthCenterExportFormat;
  label: string;
  mime_type: string;
  available: boolean;
  description: string;
}

export interface GrowthCenterExportRequest {
  include_kpis?: boolean;
  include_market_insights?: boolean;
  include_opportunities?: boolean;
  include_recommendations?: boolean;
  include_timeline?: boolean;
  locale?: string;
}

export interface GrowthCenterExportResponse {
  format: GrowthCenterExportFormat;
  status: "not_implemented" | "ready";
  message: string;
  download_url: string | null;
  filename: string | null;
}

export interface GrowthCenterDashboard {
  kpis: GrowthCenterOverviewKpis;
  market_insights: GrowthCenterMarketInsights;
  health_scores: GrowthCenterHealthScores;
  recommendations: GrowthCenterRecommendation[];
  opportunities: GrowthCenterOpportunity[];
  timeline: GrowthCenterTimelineItem[];
  export_formats: GrowthCenterExportFormatInfo[];
  generated_at: string;
}

export interface GrowthCenterSummary {
  total_leads: number;
  total_buyers: number;
  active_buyers: number;
  total_deals: number;
  pipeline_value: number | string;
  proposal_value: number | string;
  followups_due: number;
  growth_score: number;
  top_recommendations: GrowthCenterRecommendation[];
  generated_at: string;
}

export const growthCenterApi = {
  summary: () => pickTenantProductClient().get<GrowthCenterSummary>("/growth-center/summary"),
  dashboard: () => pickTenantProductClient().get<GrowthCenterDashboard>("/growth-center/dashboard"),
  listExportFormats: () =>
    pickTenantProductClient().get<GrowthCenterExportFormatInfo[]>("/growth-center/export/formats"),
  exportReport: (format: GrowthCenterExportFormat, body?: GrowthCenterExportRequest) =>
    pickTenantProductClient().post<GrowthCenterExportResponse>(`/growth-center/export/${format}`, body ?? {}),
};

// ─── AI Export Growth Engine ──────────────────────────────────────────────────

export type ExportGrowthRecommendationPriority = "urgent" | "high" | "medium" | "low";

export interface ExportGrowthScoreFactor {
  factor: string;
  weight_pct: number;
  score: number;
  weighted_contribution: number;
  summary: string;
}

export interface ExportGrowthScore {
  score: number;
  label: string;
  summary: string;
  factors: ExportGrowthScoreFactor[];
}

export interface ExportGrowthKpis {
  pipeline_value: number;
  expected_revenue: number;
  opportunity_value: number;
  active_buyers: number;
  buyer_growth_pct: number;
  proposal_acceptance_rate: number;
  communication_health: number;
  export_growth_score: number;
}

export interface ExportGrowthDailyAction {
  id: string;
  priority: ExportGrowthRecommendationPriority;
  title: string;
  expected_impact: string;
  reason: string;
  recommended_action: string;
  href: string | null;
  entity_type: string | null;
  entity_id: string | null;
}

export interface ExportGrowthOpportunity {
  id: string;
  category: string;
  title: string;
  country: string | null;
  industry: string | null;
  product: string | null;
  opportunity_score: number;
  estimated_value: number;
  currency: string;
  recommended_action: string;
  confidence_score: number;
  href: string | null;
  entity_type: string | null;
  entity_id: string | null;
}

export interface ExportGrowthMarketOpportunity {
  id: string;
  type: "country" | "industry" | "product";
  name: string;
  growth_score: number;
  demand_index: number;
  buyer_count: number;
  estimated_value: number;
  currency: string;
  recommended_action: string;
  data_source: string;
}

export interface ExportGrowthBuyerRecommendation {
  id: string;
  type: "follow_up" | "high_potential" | "inactive" | "new_target";
  company_name: string;
  country: string | null;
  match_score: number;
  reason: string;
  recommended_action: string;
  href: string | null;
  buyer_id: string | null;
}

export interface ExportGrowthContentRecommendation {
  id: string;
  type: "publish" | "create" | "localize" | "promote";
  title: string;
  language: string;
  platform: string;
  products: string[];
  reason: string;
  recommended_action: string;
  href: string | null;
}

export interface ExportGrowthSalesRecommendation {
  id: string;
  type: "at_risk" | "fast_close" | "high_value" | "stalled";
  deal_title: string;
  buyer: string | null;
  value: number;
  currency: string;
  stage: string;
  probability: number;
  reason: string;
  recommended_action: string;
  href: string | null;
  deal_id: string | null;
}

export interface ExportGrowthStrategicInsight {
  id: string;
  category: string;
  title: string;
  insight: string;
  confidence: number;
  recommended_action: string | null;
}

export interface ExportGrowthDistributionItem {
  label: string;
  count: number;
}

export interface ExportGrowthDashboard {
  kpis: ExportGrowthKpis;
  export_growth_score: ExportGrowthScore;
  daily_actions: ExportGrowthDailyAction[];
  opportunities: ExportGrowthOpportunity[];
  market_opportunities: ExportGrowthMarketOpportunity[];
  buyer_recommendations: ExportGrowthBuyerRecommendation[];
  content_recommendations: ExportGrowthContentRecommendation[];
  sales_recommendations: ExportGrowthSalesRecommendation[];
  strategic_insights: ExportGrowthStrategicInsight[];
  growing_markets: ExportGrowthDistributionItem[];
  demo_mode: boolean;
  generated_at: string;
}

export interface ExportGrowthSummary {
  export_growth_score: ExportGrowthScore;
  active_opportunities: number;
  high_value_opportunities: number;
  expected_revenue: number | string;
  buyers_to_contact: number;
  deals_at_risk: number;
  top_actions: ExportGrowthDailyAction[];
  demo_mode: boolean;
  generated_at: string;
}

export const exportGrowthApi = {
  summary: () => pickTenantProductClient().get<ExportGrowthSummary>("/export-growth/summary"),
  dashboard: () => pickTenantProductClient().get<ExportGrowthDashboard>("/export-growth/dashboard"),
};

// ─── Customer Success & Factory ROI Center ────────────────────────────────────

export type CustomerSuccessHealthStatus = "healthy" | "needs_attention" | "at_risk";
export type CustomerSuccessInsightCategory = "working" | "not_working" | "market" | "buyer" | "activity";
export type ChurnRiskLevel = "low" | "medium" | "high";

export interface FactoryRoiKpis {
  total_leads_generated: number;
  total_buyers_added: number;
  active_buyers: number;
  deals_created: number;
  deals_won: number;
  proposal_value: number | string;
  pipeline_value: number | string;
  estimated_revenue_influenced: number | string;
  communication_messages: number;
  content_items_created: number;
}

export interface RoiConfigWeights {
  pipeline_weight: number;
  proposal_weight: number;
  won_deals_weight: number;
  lead_value_multiplier: number;
}

export interface RoiCalculation {
  subscription_cost: number | string;
  subscription_currency: string;
  leads_generated: number;
  deals_created: number;
  pipeline_value: number | string;
  proposal_value: number | string;
  won_revenue: number | string;
  value_generated: number | string;
  revenue_influenced: number | string;
  estimated_roi_pct: number;
  roi_label: string;
  config: RoiConfigWeights;
}

export interface AdoptionMetric {
  key: string;
  label: string;
  count: number;
  period_count: number;
  score: number;
}

export interface AdoptionDashboard {
  metrics: AdoptionMetric[];
  engagement_score: number;
  user_logins_30d: number;
  active_users: number;
  total_users: number;
}

export interface BusinessImpactMetrics {
  buyers_acquired: number;
  buyers_reactivated: number;
  opportunities_created: number;
  proposal_acceptance_rate: number;
  average_deal_progression_days: number;
  won_deal_value: number | string;
  pipeline_created_value: number | string;
}

export interface HealthScoreFactor {
  factor: string;
  label: string;
  score: number;
  weight_pct: number;
  summary: string;
}

export interface CustomerSuccessHealthScore {
  score: number;
  status: CustomerSuccessHealthStatus;
  label: string;
  summary: string;
  factors: HealthScoreFactor[];
}

export interface AiInsight {
  id: string;
  category: CustomerSuccessInsightCategory;
  title: string;
  detail: string;
  priority: "urgent" | "high" | "medium" | "low";
  href?: string | null;
}

export interface CustomerSuccessDashboard {
  roi_kpis: FactoryRoiKpis;
  roi: RoiCalculation;
  health_score: CustomerSuccessHealthScore;
  adoption_summary: AdoptionDashboard;
  business_impact: BusinessImpactMetrics;
  insights: AiInsight[];
  top_markets: { label: string; count: number }[];
  is_demo: boolean;
  generated_at: string;
}

export interface CustomerSuccessSummary {
  customer_health_score: CustomerSuccessHealthScore;
  adoption_score: number;
  roi_estimate: RoiCalculation;
  active_users: number;
  content_activity: number;
  crm_activity: number;
  churn_risk: ChurnRiskLevel;
  top_insights: AiInsight[];
  is_demo: boolean;
  generated_at: string;
}

export interface ExecutiveReportSection {
  title: string;
  bullets: string[];
}

export interface ExecutiveReport {
  period: "monthly" | "quarterly";
  title: string;
  generated_at: string;
  executive_summary: string;
  sections: ExecutiveReportSection[];
  kpis: FactoryRoiKpis;
  roi: RoiCalculation;
  health_score: CustomerSuccessHealthScore;
}

export interface AdminTenantSummary {
  tenant_id: string;
  tenant_name: string;
  status: string;
  plan_name: string | null;
  health_score: number;
  health_status: CustomerSuccessHealthStatus;
  engagement_score: number;
  estimated_roi_pct: number;
  pipeline_value: number | string;
  active_buyers: number;
  churn_risk: ChurnRiskLevel;
}

export interface ChurnRiskItem {
  tenant_id: string;
  tenant_name: string;
  risk_level: ChurnRiskLevel;
  health_score: number;
  days_since_login: number | null;
  subscription_status: string | null;
  reasons: string[];
  recommendations: string[];
}

export const customerSuccessApi = {
  summary: () => pickTenantProductClient().get<CustomerSuccessSummary>("/customer-success/summary"),
  dashboard: () => pickTenantProductClient().get<CustomerSuccessDashboard>("/customer-success/dashboard"),
  roi: () => pickTenantProductClient().get<{ roi_kpis: FactoryRoiKpis; roi: RoiCalculation; health_score: CustomerSuccessHealthScore; generated_at: string }>("/customer-success/roi"),
  adoption: () => pickTenantProductClient().get<{ adoption: AdoptionDashboard; health_score: CustomerSuccessHealthScore; generated_at: string }>("/customer-success/adoption"),
  businessImpact: () => pickTenantProductClient().get<{ business_impact: BusinessImpactMetrics; roi_kpis: FactoryRoiKpis; top_markets: { label: string; count: number }[]; generated_at: string }>("/customer-success/business-impact"),
  report: (period: "monthly" | "quarterly") => pickTenantProductClient().get<ExecutiveReport>(`/customer-success/reports/${period}`),
  insights: () => pickTenantProductClient().get<{ insights: AiInsight[]; generated_at: string }>("/customer-success/insights"),
  calculateRoi: (config?: RoiConfigWeights) => pickTenantProductClient().post<{ roi_kpis: FactoryRoiKpis; roi: RoiCalculation; health_score: CustomerSuccessHealthScore; generated_at: string }>("/customer-success/roi/calculate", config ?? {}),
  adminTenants: () => adminApi.get<AdminTenantSummary[]>("/customer-success/admin/tenants"),
  adminChurnRisk: () => adminApi.get<ChurnRiskItem[]>("/customer-success/admin/churn-risk"),
};

// ─── Business Matching Center ─────────────────────────────────────────────────

export type BusinessMatchingOpportunityStatus =
  | "new"
  | "contacted"
  | "qualified"
  | "negotiation"
  | "won"
  | "lost";

export type BusinessMatchingOpportunityType =
  | "import"
  | "distribution"
  | "government"
  | "retail"
  | "general";

export type BusinessMatchingRecommendationPriority = "urgent" | "high" | "medium" | "low";

export interface BusinessMatchingKpis {
  total_opportunities: number;
  high_value_opportunities: number;
  active_matches: number;
  estimated_pipeline_value: number | string;
  average_match_score: number;
}

export interface BusinessMatchingOpportunityItem {
  id: string;
  title: string;
  opportunity_type: string;
  buyer_id?: string | null;
  buyer_company?: string | null;
  supplier_tenant_id?: string | null;
  supplier_company?: string | null;
  score: number;
  confidence_score: number;
  estimated_value?: number | string | null;
  status: string;
  notes?: string | null;
  match_reasoning?: string | null;
  country?: string | null;
  industry?: string | null;
  created_at: string;
  updated_at: string;
}

export interface BusinessMatchingBuyerItem {
  id: string;
  company_name: string;
  country?: string | null;
  industry?: string | null;
  status: string;
  match_score: number;
  confidence_score: number;
  recommended_actions: string[];
  similar_buyers: string[];
  product_categories: string[];
}

export interface BusinessMatchingSupplierItem {
  tenant_id: string;
  company_name: string;
  industry?: string | null;
  country?: string | null;
  product_categories: string[];
  certifications: string[];
  contact_email?: string | null;
  contact_phone?: string | null;
  match_score: number;
  confidence_score: number;
  match_reasoning?: string | null;
}

export interface BusinessMatchingRecommendation {
  id: string;
  category: string;
  priority: BusinessMatchingRecommendationPriority;
  title: string;
  reason: string;
  recommended_action: string;
  entity_id?: string | null;
  entity_type?: string | null;
}

export interface BusinessMatchingTrendPoint {
  period: string;
  count: number;
}

export interface BusinessMatchingDashboard {
  kpis: BusinessMatchingKpis;
  top_industries: Array<{ label: string; count: number }>;
  top_countries: Array<{ label: string; count: number }>;
  matching_opportunities: BusinessMatchingOpportunityItem[];
  recommended_buyers: BusinessMatchingBuyerItem[];
  recommended_suppliers: BusinessMatchingSupplierItem[];
  new_opportunities: BusinessMatchingOpportunityItem[];
  industry_trends: BusinessMatchingTrendPoint[];
  recommendations: BusinessMatchingRecommendation[];
}

export const businessMatchingApi = {
  dashboard: () => api.get<BusinessMatchingDashboard>("/business-matching/dashboard"),
  opportunities: (params?: {
    country?: string;
    industry?: string;
    product_category?: string;
    min_score?: number;
    status?: BusinessMatchingOpportunityStatus;
    skip?: number;
    limit?: number;
  }) =>
    api.get<{ items: BusinessMatchingOpportunityItem[]; total: number }>(
      "/business-matching/opportunities",
      { params },
    ),
  buyers: (params?: { min_score?: number; skip?: number; limit?: number }) =>
    api.get<{ items: BusinessMatchingBuyerItem[]; total: number }>(
      "/business-matching/buyers",
      { params },
    ),
  suppliers: (params?: { min_score?: number; skip?: number; limit?: number }) =>
    api.get<{ items: BusinessMatchingSupplierItem[]; total: number }>(
      "/business-matching/suppliers",
      { params },
    ),
  createOpportunity: (body: {
    title: string;
    opportunity_type?: BusinessMatchingOpportunityType;
    buyer_id?: string;
    supplier_tenant_id?: string;
    score?: number;
    confidence_score?: number;
    estimated_value?: number;
    status?: BusinessMatchingOpportunityStatus;
    notes?: string;
    match_reasoning?: string;
  }) => api.post<BusinessMatchingOpportunityItem>("/business-matching/opportunities", body),
  updateOpportunity: (
    id: string,
    body: Partial<{
      title: string;
      status: BusinessMatchingOpportunityStatus;
      score: number;
      notes: string;
    }>,
  ) => api.patch<BusinessMatchingOpportunityItem>(`/business-matching/opportunities/${id}`, body),
};

// ─── Buyer Network CRM ────────────────────────────────────────────────────────

export type BuyerStatus =
  | "prospect"
  | "contacted"
  | "interested"
  | "negotiating"
  | "active_buyer"
  | "inactive";

export const BUYER_STATUSES: BuyerStatus[] = [
  "prospect",
  "contacted",
  "interested",
  "negotiating",
  "active_buyer",
  "inactive",
];

export const CENTRAL_ASIA_COUNTRIES = [
  "Uzbekistan",
  "Kazakhstan",
  "Kyrgyzstan",
  "Tajikistan",
  "Turkmenistan",
];

export interface Buyer {
  id: string;
  tenant_id: string;
  company_name: string;
  contact_person: string | null;
  country: string | null;
  city: string | null;
  industry: string | null;
  website: string | null;
  email: string | null;
  phone: string | null;
  telegram: string | null;
  whatsapp: string | null;
  wechat: string | null;
  annual_purchase_volume: string | null;
  product_categories: string[];
  notes: string | null;
  tags: string[];
  status: BuyerStatus;
  created_at: string;
  updated_at: string;
  link_count?: number;
}

export interface BuyerDetail extends Buyer {
  linked_leads: BuyerLinkedEntity[];
  linked_deals: BuyerLinkedEntity[];
  linked_customers: BuyerLinkedEntity[];
  linked_proposals: BuyerLinkedEntity[];
}

export interface BuyerLinkedEntity {
  link_id: string;
  entity_type: "lead" | "deal" | "customer" | "proposal";
  entity_id: string;
  label: string;
  created_at: string;
}

export interface BuyerDashboard {
  total_buyers: number;
  active_buyers: number;
  new_buyers_this_month: number;
  top_industries: Array<{ label: string; count: number }>;
  top_countries: Array<{ label: string; count: number }>;
  geographic_distribution: Array<{ label: string; count: number }>;
  industry_distribution: Array<{ label: string; count: number }>;
  by_status: Record<string, number>;
}

export interface BuyerTimelineItem {
  id: string;
  kind: "activity" | "note" | "status_change";
  title: string;
  description: string | null;
  occurred_at: string;
  meta?: Record<string, unknown> | null;
}

export interface BuyerNote {
  id: string;
  tenant_id: string;
  buyer_id: string;
  content: string;
  created_by: string | null;
  created_at: string;
}

export interface BuyerStatusHistoryEntry {
  id: string;
  tenant_id: string;
  buyer_id: string;
  from_status: string | null;
  to_status: string;
  note: string | null;
  changed_by: string | null;
  changed_at: string;
}

export const buyersApi = {
  countries: () => api.get<{ countries: string[] }>("/buyers/meta/countries"),
  dashboard: () => api.get<BuyerDashboard>("/buyers/dashboard"),
  list: (params?: {
    search?: string;
    status?: BuyerStatus;
    country?: string;
    industry?: string;
    tag?: string;
    skip?: number;
    limit?: number;
  }) => api.get<{ items: Buyer[]; total: number }>("/buyers", { params }),
  get: (id: string) => api.get<BuyerDetail>(`/buyers/${id}`),
  create: (data: Omit<Buyer, "id" | "tenant_id" | "created_at" | "updated_at" | "link_count">) =>
    api.post<Buyer>("/buyers", data),
  update: (id: string, data: Partial<Omit<Buyer, "id" | "tenant_id" | "created_at" | "updated_at">>) =>
    api.patch<Buyer>(`/buyers/${id}`, data),
  delete: (id: string) => api.delete(`/buyers/${id}`),
  timeline: (id: string, limit?: number) =>
    api.get<{ items: BuyerTimelineItem[]; total: number }>(`/buyers/${id}/timeline`, { params: { limit } }),
  listNotes: (id: string) => api.get<{ items: BuyerNote[]; total: number }>(`/buyers/${id}/notes`),
  createNote: (id: string, content: string) =>
    api.post<BuyerNote>(`/buyers/${id}/notes`, { content }),
  deleteNote: (id: string, noteId: string) => api.delete(`/buyers/${id}/notes/${noteId}`),
  statusHistory: (id: string) =>
    api.get<{ items: BuyerStatusHistoryEntry[]; total: number }>(`/buyers/${id}/status-history`),
  listLinks: (id: string) => api.get<{ items: BuyerLinkedEntity[]; total: number }>(`/buyers/${id}/links`),
  createLink: (id: string, entity_type: BuyerLinkedEntity["entity_type"], entity_id: string) =>
    api.post<BuyerLinkedEntity>(`/buyers/${id}/links`, { entity_type, entity_id }),
  deleteLink: (id: string, linkId: string) => api.delete(`/buyers/${id}/links/${linkId}`),
};

// ─── Media API ────────────────────────────────────────────────────────────────

export const mediaApi = {
  upload: (
    clientId: string,
    file: File,
    onProgress?: (percent: number) => void,
  ) => {
    const form = new FormData();
    form.append("file", file);
    // DO NOT set Content-Type manually — axios must auto-set it with the
    // multipart boundary. Setting undefined removes the default json header.
    return api.post<MediaFile>(`/media/upload/${clientId}`, form, {
      headers: { "Content-Type": undefined },
      onUploadProgress: onProgress
        ? (evt) => {
            if (evt.total) {
              onProgress(Math.round((evt.loaded / evt.total) * 100));
            }
          }
        : undefined,
    });
  },
  listForClient: (clientId: string) =>
    api.get<MediaFile[]>(`/media/client/${clientId}`),
  delete: (mediaId: string) => api.delete(`/media/${mediaId}`),
};

// ─── Content API ──────────────────────────────────────────────────────────────

export const contentApi = {
  list: (params?: { client_id?: string; status?: string; source?: string; skip?: number; limit?: number }) =>
    api.get<{ items: ContentItem[]; total: number }>("/content", { params }),
  get: (id: string) => api.get<ContentItem>(`/content/${id}`),
  readiness: (id: string, intent: "approve" | "schedule" = "approve") =>
    api.get<ContentReadiness>(`/content/${id}/readiness`, { params: { intent } }),
  publishSafety: (
    id: string,
    params?: { mode?: PublishMode; platform?: Platform; account_id?: string },
  ) =>
    api.get<PublishSafety>(`/content/${id}/publish-safety`, { params }),
  create: (data: {
    client_id: string;
    media_file_id?: string;
    platforms: Platform[];
    internal_notes?: string;
  }) => api.post<ContentItem>("/content", data),
  update: (id: string, data: Partial<ContentItem>) =>
    api.patch<ContentItem>(`/content/${id}`, data),
  approve: (id: string) => api.post<ContentItem>(`/content/${id}/approve`),
  publish: (
    id: string,
    data?: {
      platforms?: Platform[];
      account_id?: string;
      test?: boolean;
      mode?: PublishMode;
    },
  ) => api.post<PublishContentResponse>(`/content/${id}/publish`, data ?? {}),
  getPublishHistory: (id: string) =>
    api.get<{ items: PublishAttempt[]; total: number }>(`/content/${id}/publish-history`),
  createReviewLink: (id: string) =>
    api.post<{ token: string; url: string }>(`/content/${id}/review-link`),
  sendClientReviewPreview: (id: string) =>
    api.post<{
      sent: boolean;
      sent_at?: string | null;
      error?: string | null;
      skipped?: boolean;
      reason?: string | null;
    }>(`/content/${id}/client-review/send-preview`),
  burnSubtitles: (id: string, lang: SubtitleBurnLang) =>
    api.post<ContentItem>(`/content/${id}/burn-subtitles`, { lang }),
  generateVoiceover: (id: string, lang: VoiceoverLang, mode: VoiceoverMode) =>
    api.post<ContentItem>(`/content/${id}/generate-voiceover`, { lang, mode }),
  generateFinalVideo: (
    id: string,
    subtitleLang: SubtitleBurnLang,
    voiceLang: VoiceoverLang,
    voiceMode: VoiceoverMode,
  ) =>
    api.post<ContentItem>(`/content/${id}/generate-final-video`, {
      subtitle_lang: subtitleLang,
      voice_lang: voiceLang,
      voice_mode: voiceMode,
    }),
  requestMedia: (id: string, data?: { format?: "photo" | "video" | "carousel" | "story" | "any" }) =>
    api.post<{
      ok: boolean;
      message: string;
      media_request_status: string;
      media_request_sent_at: string;
      media_request_message: string;
      media_request_format: string;
    }>(`/content/${id}/request-media`, data ?? {}),
  delete: (id: string) => api.delete(`/content/${id}`),
  schedule: (data: {
    content_item_id: string;
    scheduled_date: string;
    time_slot?: string;
    scheduled_for?: string;
    platforms?: Platform[];
    note?: string;
  }) => api.post<CalendarEntry>("/calendar/schedule", data),
  getCalendarMonth: (year: number, month: number) =>
    api.get<CalendarEntry[]>(`/calendar/month/${year}/${month}`),
  updateCalendarEntry: (entryId: string, data: {
    scheduled_date?: string;
    time_slot?: string;
    scheduled_for?: string;
    platforms?: Platform[];
    note?: string;
  }) => api.patch<CalendarEntry>(`/calendar/${entryId}`, data),
  deleteCalendarEntry: (entryId: string) => api.delete(`/calendar/${entryId}`),
  markPublished: (entryId: string) => api.post<CalendarEntry>(`/calendar/${entryId}/publish`),
  moveToDraft: (entryId: string) => api.post(`/calendar/${entryId}/draft`),
};

// ─── Operator inbox API ───────────────────────────────────────────────────────

export type InboxStatus = "new" | "used" | "ignored";

export interface OperatorInboxMediaPreview {
  buffer_id: string;
  media_type: string;
  url?: string | null;
  text?: string | null;
}

export type OperatorInboxIntent =
  | "create_post"
  | "edit_existing"
  | "schedule_post"
  | "ask_question"
  | "unclear";

export interface OperatorInboxMediaSelection {
  photo_ordinals: number[];
  video_ordinals: number[];
  buffer_ids: string[];
  use_all_media: boolean;
  use_client_text_as_description: boolean;
  summary?: string | null;
}

export interface OperatorInboxAiSuggestion {
  inbox_id: string;
  intent: OperatorInboxIntent;
  suggested_action: string;
  suggested_platforms: string[];
  suggested_schedule?: string | null;
  media_selection: OperatorInboxMediaSelection;
  reason: string;
  active_content_id?: string | null;
  source?: string | null;
  cached?: boolean;
  cached_at?: string | null;
}

export type InboxPriority = "high" | "medium" | "low";

export interface OperatorInboxSmartAnalysis {
  inbox_id: string;
  ai_summary?: string | null;
  priority?: InboxPriority | null;
  suggested_publish_date?: string | null;
  suggested_platforms: string[];
  detected_deadline?: string | null;
  detected_offer?: string | null;
  detected_language?: string | null;
  grouped_task_id?: string | null;
  source?: string | null;
  cached?: boolean;
  cached_at?: string | null;
}

export type AccountManagerIntent =
  | "new_content_request"
  | "change_request"
  | "media_upload"
  | "schedule_request"
  | "question"
  | "complaint"
  | "pricing_billing"
  | "unclear";

export type TaskStatus =
  | "todo"
  | "in_progress"
  | "waiting_client"
  | "done"
  | "canceled";

export interface OperatorInboxItem {
  id: string;
  client_id: string;
  company_name: string;
  telegram_group_title?: string | null;
  message_text?: string | null;
  media_count: number;
  media_previews: OperatorInboxMediaPreview[];
  created_at: string;
  message_at: string;
  status: InboxStatus;
  linked_content_id?: string | null;
  ai_suggestion?: OperatorInboxAiSuggestion | null;
  auto_drafted?: boolean;
  ai_summary?: string | null;
  priority?: InboxPriority | null;
  suggested_publish_date?: string | null;
  suggested_platforms?: string[];
  detected_deadline?: string | null;
  detected_offer?: string | null;
  detected_language?: string | null;
  grouped_task_id?: string | null;
  is_group_primary?: boolean;
  group_message_count?: number;
  group_media_count?: number;
  group_inbox_ids?: string[];
  needs_action?: boolean;
  related_to_media_request?: boolean;
  account_manager_intent?: AccountManagerIntent | null;
  account_manager_summary?: string | null;
  account_manager_recommended_action?: string | null;
  account_manager_priority?: InboxPriority | null;
  account_manager_reply_sent?: boolean;
  account_manager_reply_text?: string | null;
  account_manager_related_content_id?: string | null;
  operator_task_id?: string | null;
  operator_task_status?: TaskStatus | null;
  operator_task_title?: string | null;
}

export interface OperatorInboxListResponse {
  items: OperatorInboxItem[];
  total: number;
  counts: Record<string, number>;
}

export interface OperatorInboxActionResponse {
  ok: boolean;
  message: string;
  inbox_id: string;
  content_id?: string | null;
  status?: InboxStatus;
}

export interface OperatorInboxAiSuggestResponse {
  suggestion: OperatorInboxAiSuggestion;
}

export const operatorApi = {
  listInbox: (params?: {
    status?: InboxStatus;
    client_id?: string;
    priority?: InboxPriority;
    needs_action?: boolean;
    auto_drafted?: boolean;
    grouped?: boolean;
    skip?: number;
    limit?: number;
  }) => api.get<OperatorInboxListResponse>("/operator/inbox", { params }),
  createContent: (inboxId: string, fromGroup?: boolean) =>
    api.post<OperatorInboxActionResponse>(
      `/operator/inbox/${inboxId}/create-content`,
      null,
      { params: fromGroup ? { from_group: true } : undefined },
    ),
  ignore: (inboxId: string) =>
    api.post<OperatorInboxActionResponse>(`/operator/inbox/${inboxId}/ignore`),
  restore: (inboxId: string) =>
    api.post<OperatorInboxActionResponse>(`/operator/inbox/${inboxId}/restore`),
  aiSuggest: (inboxId: string, forceRefresh?: boolean) =>
    api.post<OperatorInboxAiSuggestResponse>(`/operator/inbox/${inboxId}/ai-suggest`, null, {
      params: forceRefresh ? { force_refresh: true } : undefined,
    }),
  smartAnalyze: (inboxId: string, forceRefresh?: boolean) =>
    api.post<OperatorInboxSmartAnalysis>(`/operator/inbox/${inboxId}/smart-analyze`, null, {
      params: forceRefresh ? { force_refresh: true } : undefined,
    }),
  groupInbox: (inboxIds: string[]) =>
    api.post<{ ok: boolean; message: string; grouped_task_id: string; primary_inbox_id: string; inbox_ids: string[] }>(
      "/operator/inbox/group",
      { inbox_ids: inboxIds },
    ),
  applyAiSuggestion: (inboxId: string) =>
    api.post<OperatorInboxActionResponse>(`/operator/inbox/${inboxId}/apply-ai-suggestion`),
};

// ─── Operator tasks API ───────────────────────────────────────────────────────

export type TaskSourceType =
  | "telegram_inbox"
  | "content"
  | "media_request"
  | "client_review"
  | "client_brief"
  | "manual";

export type TaskCreatedBy = "ai_account_manager" | "admin" | "system";

export type TaskExecutionStatus = "success" | "failed" | "pending";

export interface TaskExecutionResult {
  action?: string;
  message?: string;
  content_id?: string;
  suggested_reply?: string;
  reply_sent?: boolean;
  reply_sent_at?: string;
  media_request_message?: string;
  edit_summary?: string;
  error?: string;
}

export interface OperatorTask {
  id: string;
  client_id: string;
  company_name?: string | null;
  source_type: TaskSourceType;
  source_id?: string | null;
  title: string;
  description?: string | null;
  priority: InboxPriority;
  status: TaskStatus;
  due_at?: string | null;
  assigned_to?: string | null;
  created_by: TaskCreatedBy;
  linked_content_id?: string | null;
  execution_status?: TaskExecutionStatus | null;
  execution_result?: TaskExecutionResult | null;
  executed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskExecuteResponse {
  ok: boolean;
  action: string;
  message: string;
  content_id?: string | null;
  suggested_reply?: string | null;
  task: OperatorTask;
}

export interface OperatorTaskListResponse {
  items: OperatorTask[];
  total: number;
}

export const tasksApi = {
  list: (params?: {
    status?: TaskStatus;
    client_id?: string;
    priority?: InboxPriority;
    source_type?: TaskSourceType;
    skip?: number;
    limit?: number;
  }) => api.get<OperatorTaskListResponse>("/tasks", { params }),
  create: (data: {
    client_id: string;
    source_type?: TaskSourceType;
    source_id?: string | null;
    title: string;
    description?: string | null;
    priority?: InboxPriority;
    status?: TaskStatus;
    due_at?: string | null;
    assigned_to?: string | null;
    created_by?: TaskCreatedBy;
    linked_content_id?: string | null;
  }) => api.post<OperatorTask>("/tasks", data),
  update: (id: string, data: Partial<{
    title: string;
    description: string | null;
    priority: InboxPriority;
    status: TaskStatus;
    due_at: string | null;
    assigned_to: string | null;
    linked_content_id: string | null;
  }>) => api.patch<OperatorTask>(`/tasks/${id}`, data),
  delete: (id: string) => api.delete(`/tasks/${id}`),
  markDone: (id: string) => api.post<OperatorTask>(`/tasks/${id}/mark-done`),
  start: (id: string) => api.post<OperatorTask>(`/tasks/${id}/start`),
  waitClient: (id: string) => api.post<OperatorTask>(`/tasks/${id}/wait-client`),
  cancel: (id: string) => api.post<OperatorTask>(`/tasks/${id}/cancel`),
  execute: (id: string) => api.post<TaskExecuteResponse>(`/tasks/${id}/execute`),
  sendReply: (id: string, replyText?: string) =>
    api.post<{ ok: boolean; message: string; task: OperatorTask }>(
      `/tasks/${id}/send-reply`,
      replyText ? { reply_text: replyText } : {},
    ),
};

// ─── Publishing accounts API ──────────────────────────────────────────────────

export const publishingApi = {
  listAccounts: (params?: { platform?: Platform; status?: string }) =>
    api.get<{ items: PublishingAccount[]; total: number }>("/publishing/accounts", { params }),
  createAccount: (data: {
    platform: Platform;
    mock?: boolean;
    account_name?: string;
    account_id?: string;
    status?: string;
  }) => api.post<PublishingAccount>("/publishing/accounts", data),
  updateAccount: (id: string, data: Partial<PublishingAccount>) =>
    api.patch<PublishingAccount>(`/publishing/accounts/${id}`, data),
  deleteAccount: (id: string) => api.delete(`/publishing/accounts/${id}`),
  scheduledDebug: (clientTimezone?: string) =>
    api.get<ScheduledPublishDebugResponse>("/publishing/scheduled-debug", {
      params: clientTimezone ? { client_timezone: clientTimezone } : undefined,
    }),
  getCalendar: (params: {
    from: string;
    to: string;
    client_id?: string;
    platform?: Platform;
    status?: string;
  }) => api.get<PublishingCalendarResponse>("/publishing/calendar", { params }),
  getQueue: (clientTimezone?: string) =>
    api.get<PublishingQueueResponse>("/publishing/queue", {
      params: clientTimezone ? { client_timezone: clientTimezone } : undefined,
    }),
  cancelQueueItem: (contentId: string) =>
    api.post<PublishingQueueActionResponse>(`/publishing/queue/${contentId}/cancel`),
  retryQueueItem: (contentId: string) =>
    api.post<PublishingQueueActionResponse>(`/publishing/queue/${contentId}/retry`),
  sendClientReviewQueueItem: (contentId: string) =>
    api.post<PublishingQueueActionResponse>(`/publishing/queue/${contentId}/send-client-review`),
};

export interface PublishingCalendarItem {
  id: string;
  title: string;
  client_id: string;
  company_name: string;
  status: ContentStatus;
  scheduled_for?: string | null;
  published_at?: string | null;
  platforms: Platform[];
}

export interface PublishingCalendarResponse {
  items: PublishingCalendarItem[];
  total: number;
  from_date: string;
  to_date: string;
}

export interface ScheduledPublishDebugItem {
  id: string;
  status: string;
  scheduled_for?: string | null;
  utc_time?: string | null;
  local_time?: string | null;
  current_time: string;
  is_due: boolean;
  approved_at?: string | null;
  admin_approved: boolean;
  client_review_status?: string | null;
  client_approved: boolean;
  platforms: Platform[];
  platforms_count: number;
  publishing_accounts_available: Record<string, string[]>;
  selected_accounts: Record<string, string | null>;
  has_media: boolean;
  has_caption: boolean;
  skip_reason?: string | null;
}

export interface ScheduledPublishDebugResponse {
  current_time: string;
  due_count: number;
  items: ScheduledPublishDebugItem[];
}

export type PublishingQueueCategory =
  | "ready"
  | "waiting_client"
  | "waiting_account"
  | "future"
  | "failed"
  | "stuck_publishing"
  | "blocked";

export interface PublishingQueueItem {
  id: string;
  client_id: string;
  company_name: string;
  status: ContentStatus;
  scheduled_for?: string | null;
  local_time?: string | null;
  platforms: Platform[];
  client_review_status?: string | null;
  admin_approved: boolean;
  safety_status: "passed" | "blocked";
  block_reason?: string | null;
  block_reason_label?: string | null;
  queue_category: PublishingQueueCategory;
  is_due: boolean;
}

export interface PublishingQueueResponse {
  current_time: string;
  items: PublishingQueueItem[];
  total: number;
  counts: Record<string, number>;
}

export interface PublishingQueueActionResponse {
  ok: boolean;
  message: string;
  content_id: string;
  status?: string;
  safety_status?: string;
  block_reason?: string;
}

// ─── Analytics API ──────────────────────────────────────────────────────────────

export interface CountByDay {
  date: string;
  count: number;
}

export interface DailyPublishing {
  date: string;
  attempts: number;
  success: number;
  failed: number;
}

export interface ClientActivity {
  client_id: string;
  company_name: string;
  post_count: number;
}

export interface PlatformStat {
  platform: Platform;
  post_count: number;
  attempt_count: number;
  success_count: number;
}

export interface AnalyticsOverview {
  total_posts: number;
  scheduled_posts: number;
  published_posts: number;
  failed_posts: number;
  posts_over_time: CountByDay[];
  publishing_success_rate: number;
  publish_attempts_total: number;
  publish_attempts_success: number;
  most_active_clients: ClientActivity[];
}

export interface AnalyticsPlatforms {
  platforms: PlatformStat[];
}

export interface ActivityFeedItem {
  id: string;
  content_id: string;
  company_name: string;
  content_title: string;
  platform: Platform;
  status: string;
  error?: string | null;
  created_at: string;
}

export interface AnalyticsActivity {
  daily_publishing: DailyPublishing[];
  recent_activity: ActivityFeedItem[];
}

export const analyticsApi = {
  overview: () => api.get<AnalyticsOverview>("/analytics/overview"),
  platforms: () => api.get<AnalyticsPlatforms>("/analytics/platforms"),
  activity: () => api.get<AnalyticsActivity>("/analytics/activity"),
};

// ─── Workflow API ─────────────────────────────────────────────────────────────

export type WorkflowStepId =
  | "subtitles"
  | "translations"
  | "captions"
  | "hashtags"
  | "post_time"
  | "voice"
  | "export"
  | "status";

export type WorkflowStepStatus = "pending" | "running" | "completed" | "failed" | "skipped";
export type WorkflowRunStatus = "idle" | "running" | "completed" | "failed";

export interface WorkflowStepProgress {
  id: WorkflowStepId;
  label: string;
  status: WorkflowStepStatus;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface WorkflowProgress {
  content_id: string;
  status: WorkflowRunStatus;
  current_step?: WorkflowStepId | null;
  steps: WorkflowStepProgress[];
  started_at?: string | null;
  finished_at?: string | null;
  message: string;
  can_retry: boolean;
}

export const workflowApi = {
  prepare: (
    contentId: string,
    data: {
      voice_lang?: VoiceoverLang;
      subtitle_lang?: SubtitleBurnLang;
      voice_mode?: VoiceoverMode;
      source_language?: string;
      source_text?: string;
      context_hint?: string;
    },
  ) => api.post<WorkflowProgress>(`/content/${contentId}/workflow/prepare`, data),

  progress: (contentId: string) =>
    api.get<WorkflowProgress>(`/content/${contentId}/workflow/progress`),

  retry: (contentId: string, step?: WorkflowStepId) =>
    api.post<WorkflowProgress>(`/content/${contentId}/workflow/retry`, step ? { step } : {}),
};

// ─── Assistant API ────────────────────────────────────────────────────────────

export type AssistantPageType =
  | "clients"
  | "client_detail"
  | "content"
  | "content_detail"
  | "calendar"
  | "other";

export interface AssistantPageContext {
  pathname: string;
  page_type: AssistantPageType;
  summary?: string;
}

export interface AssistantChatMessage {
  role: "user" | "assistant";
  content: string;
}

export type AssistantSuggestedPatch = Partial<
  Pick<
    ContentItem,
    | "caption_short_ru"
    | "caption_short_uz"
    | "caption_short_en"
    | "caption_long_ru"
    | "caption_long_uz"
    | "caption_long_en"
    | "hashtags"
    | "internal_notes"
  >
>;

export interface AssistantChatResponse {
  reply: string;
  suggested_patch?: AssistantSuggestedPatch | null;
  applied?: boolean;
}

export const assistantApi = {
  chat: (data: {
    message: string;
    page_context: AssistantPageContext;
    client_id?: string;
    content_id?: string;
    history?: AssistantChatMessage[];
    auto_apply?: boolean;
  }) => api.post<AssistantChatResponse>("/assistant/chat", data),

  apply: (data: {
    content_id: string;
    patch: AssistantSuggestedPatch;
    auto?: boolean;
  }) =>
    api.post<{ applied_fields: AssistantSuggestedPatch }>("/assistant/apply", data),
};

// ─── AI API ───────────────────────────────────────────────────────────────────

export const aiApi = {
  /** POST /generate — original body-based endpoint */
  generate: (data: {
    content_item_id: string;
    source_language?: string;
    source_text?: string;
    context_hint?: string;
  }) => api.post<ContentItem>("/generate", data),

  /** POST /content/{id}/generate — RESTful endpoint */
  generateForContent: (
    contentId: string,
    data?: {
      source_language?: string;
      source_text?: string;
      context_hint?: string;
    },
  ) => api.post<ContentItem>(`/content/${contentId}/generate`, data ?? {}),
};

// ─── Public client review (no login) ─────────────────────────────────────────

export interface PublicReviewCaption {
  lang: string;
  short?: string | null;
  long?: string | null;
}

export interface PublicReview {
  company_name: string;
  status: string;
  media_url?: string | null;
  media_file_type?: string | null;
  selected_media?: SelectedMediaItem[] | null;
  captions: PublicReviewCaption[];
  hashtags?: string | null;
  final_video_url?: string | null;
  scheduled_for?: string | null;
  platforms?: string[];
  client_approved_at?: string | null;
  client_review_feedback?: string | null;
  client_review_status?: "pending" | "approved" | "changes_requested" | null;
  can_approve: boolean;
  can_request_changes: boolean;
  can_regenerate?: boolean;
}

export type FactoryPartnerApplicationStatus =
  | "draft"
  | "submitted"
  | "under_review"
  | "approved"
  | "rejected";

export interface FactoryPartnerApplication {
  id: string;
  company_name: string;
  country?: string | null;
  city?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_wechat?: string | null;
  contact_whatsapp?: string | null;
  contact_email?: string | null;
  website?: string | null;
  industry?: string | null;
  product_categories: string[];
  company_description?: string | null;
  cooperation_terms_accepted: boolean;
  commission_model?: string | null;
  target_markets: string[];
  documents: { name: string; url?: string | null; doc_type?: string | null }[];
  status: FactoryPartnerApplicationStatus;
  submitted_at?: string | null;
  reviewed_at?: string | null;
  created_client_id?: string | null;
  tenant_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FactoryPartnerSummaryWidget {
  pending_review: number;
  submitted: number;
  under_review: number;
  approved: number;
  rejected: number;
  draft: number;
  latest_company_name?: string | null;
}

export const factoryPartnerPortalApi = {
  list: (params?: { status?: string; search?: string; skip?: number; limit?: number }) =>
    adminApi.get<{ items: FactoryPartnerApplication[]; total: number }>(
      "/factory-partner/applications",
      { params },
    ),
  get: (id: string) =>
    adminApi.get<FactoryPartnerApplication>(`/factory-partner/applications/${id}`),
  apply: (body: Partial<FactoryPartnerApplication> & { company_name: string }) =>
    api.post<FactoryPartnerApplication>("/factory-partner/apply", body),
  update: (id: string, body: Record<string, unknown>) =>
    adminApi.patch<FactoryPartnerApplication>(`/factory-partner/applications/${id}`, body),
  submit: (id: string) =>
    adminApi.post<{ application: FactoryPartnerApplication; message: string }>(
      `/factory-partner/applications/${id}/submit`,
    ),
  approve: (id: string) =>
    adminApi.post<{ application: FactoryPartnerApplication; message: string }>(
      `/factory-partner/applications/${id}/approve`,
    ),
  reject: (id: string) =>
    adminApi.post<{ application: FactoryPartnerApplication; message: string }>(
      `/factory-partner/applications/${id}/reject`,
    ),
  createClient: (id: string) =>
    adminApi.post<{
      application_id: string;
      client_id: string;
      company_name: string;
      message: string;
    }>(`/factory-partner/applications/${id}/create-client`),
  createPortalAccount: (id: string) =>
    adminApi.post<{ account: CustomerPortalAccount; message: string }>(
      `/factory-partner/applications/${id}/create-portal-account`,
    ),
  createTenant: (id: string) =>
    adminApi.post<{ tenant: Tenant; owner_user?: TenantUser; message: string }>(
      `/factory-partner/applications/${id}/create-tenant`,
    ),
  summaryWidget: () =>
    adminApi.get<FactoryPartnerSummaryWidget>("/factory-partner/summary-widget"),
};

export type PilotOnboardingStatus =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "ready"
  | "completed";

export type PilotOnboardingAction =
  | "approve_application"
  | "create_client"
  | "create_tenant"
  | "create_portal_account"
  | "create_subscription"
  | "create_admin_user"
  | "open_factory_profile"
  | "open_billing";

export interface PilotOnboardingChecklistItem {
  step: string;
  label: string;
  completed: boolean;
  completed_at?: string | null;
  details?: string | null;
}

export interface PilotOnboardingBlockerItem {
  blocker: string;
  label: string;
  severity: "critical" | "warning";
  message: string;
}

export interface PilotOnboardingActionItem {
  action: PilotOnboardingAction;
  label: string;
  description: string;
  available: boolean;
  route_hint?: string | null;
  manual_only: boolean;
}

export interface PilotOnboardingSummary {
  application_id: string;
  company: string;
  status: PilotOnboardingStatus;
  application_status: string;
  readiness_score: number;
  blockers: PilotOnboardingBlockerItem[];
  next_best_action?: PilotOnboardingActionItem | null;
  tenant_id?: string | null;
  client_id?: string | null;
  updated_at?: string | null;
}

export interface PilotOnboardingOverview {
  total_applications: number;
  not_started: number;
  in_progress: number;
  blocked: number;
  ready: number;
  completed: number;
  average_readiness_score: number;
  pilot_ready_count: number;
  pending_approval: number;
  integration_checks: { module: string; status: string; message: string }[];
  safety_notice: string;
}

export interface PilotOnboardingDetail extends PilotOnboardingSummary {
  checklist: PilotOnboardingChecklistItem[];
  available_actions: PilotOnboardingActionItem[];
  country?: string | null;
  industry?: string | null;
  submitted_at?: string | null;
  reviewed_at?: string | null;
}

export interface PilotOnboardingSummaryWidget {
  total_tracked: number;
  in_progress: number;
  blocked: number;
  pilot_ready: number;
  average_readiness_score: number;
  pending_approval: number;
  latest_company_name?: string | null;
  safety_notice: string;
}

export interface PilotOnboardingExecutiveOverview extends PilotOnboardingOverview {
  launch_candidates: {
    application_id: string;
    company: string;
    status: PilotOnboardingStatus;
    readiness_score: number;
    blocker_count: number;
    next_action?: string | null;
  }[];
}

export const pilotOnboardingApi = {
  overview: () => adminApi.get<PilotOnboardingOverview>("/pilot-onboarding/overview"),
  summaryWidget: () =>
    adminApi.get<PilotOnboardingSummaryWidget>("/pilot-onboarding/summary-widget"),
  applications: (params?: {
    status?: string;
    onboarding_status?: PilotOnboardingStatus;
    search?: string;
    skip?: number;
    limit?: number;
  }) =>
    adminApi.get<{ items: PilotOnboardingSummary[]; total: number }>(
      "/pilot-onboarding/applications",
      { params },
    ),
  get: (id: string) => adminApi.get<PilotOnboardingDetail>(`/pilot-onboarding/${id}`),
  checklist: (id: string) =>
    adminApi.get<{
      application_id: string;
      company: string;
      readiness_score: number;
      checklist: PilotOnboardingChecklistItem[];
      completed_count: number;
      total_steps: number;
    }>(`/pilot-onboarding/${id}/checklist`),
  blockers: (id: string) =>
    adminApi.get<{
      application_id: string;
      company: string;
      blockers: PilotOnboardingBlockerItem[];
      blocker_count: number;
    }>(`/pilot-onboarding/${id}/blockers`),
  actions: (id: string) =>
    adminApi.get<{
      application_id: string;
      company: string;
      actions: PilotOnboardingActionItem[];
      next_best_action?: PilotOnboardingActionItem | null;
    }>(`/pilot-onboarding/${id}/actions`),
  refresh: (id: string) =>
    adminApi.post<{
      application_id: string;
      company: string;
      status: PilotOnboardingStatus;
      readiness_score: number;
      blockers: PilotOnboardingBlockerItem[];
      next_best_action?: PilotOnboardingActionItem | null;
      refreshed_at: string;
      message: string;
    }>(`/pilot-onboarding/${id}/refresh`),
};

export type LaunchItemStatus = "completed" | "warning" | "blocked";
export type SmokeStatus = "ok" | "warning" | "error" | "slow";
export type QaStepStatus = "pass" | "warning" | "fail" | "skipped";

export interface PilotLaunchReadinessComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  status: LaunchItemStatus;
  details?: string | null;
}

export interface PilotLaunchOverview {
  readiness_score: number;
  demo_data_present: boolean;
  demo_company_name?: string | null;
  demo_application_id?: string | null;
  demo_tenant_id?: string | null;
  qa_pass_count: number;
  qa_total: number;
  smoke_ok_count: number;
  smoke_total: number;
  checklist_completed: number;
  checklist_blocked: number;
  blockers: string[];
  next_actions: string[];
  safety_notice: string;
  implementation_complete: boolean;
}

export interface PilotLaunchSummaryWidget {
  readiness_score: number;
  demo_data_present: boolean;
  demo_company_name?: string | null;
  qa_pass_count: number;
  qa_total: number;
  smoke_ok_count: number;
  smoke_total: number;
  checklist_blocked: number;
  blockers: string[];
  next_action?: string | null;
  safety_notice: string;
}

export const pilotLaunchApi = {
  overview: () => adminApi.get<PilotLaunchOverview>("/pilot-launch/overview"),
  readiness: () =>
    adminApi.get<{
      score: number;
      components: PilotLaunchReadinessComponent[];
      demo_data_present: boolean;
      safety_notice: string;
    }>("/pilot-launch/readiness"),
  checklist: () =>
    adminApi.get<{
      items: {
        id: string;
        label: string;
        status: LaunchItemStatus;
        message?: string | null;
        next_action?: string | null;
      }[];
      completed_count: number;
      warning_count: number;
      blocked_count: number;
      next_action?: string | null;
      safety_notice: string;
    }>("/pilot-launch/checklist"),
  smokeTests: () =>
    adminApi.get<{
      tests: {
        page: string;
        route: string;
        api_probe?: string | null;
        status: SmokeStatus;
        duration_ms?: number | null;
        message?: string | null;
      }[];
      ok_count: number;
      total: number;
    }>("/pilot-launch/smoke-tests"),
  seedDemoData: (force = false) =>
    adminApi.post<{
      created: boolean;
      message: string;
      demo_marker: string;
      application_id?: string | null;
      tenant_id?: string | null;
      client_id?: string | null;
      login_email?: string | null;
      login_password?: string | null;
      counts: Record<string, number>;
    }>("/pilot-launch/seed-demo-data", { force }),
  runQa: () =>
    adminApi.post<{
      ran_at: string;
      pass_count: number;
      warning_count: number;
      fail_count: number;
      steps: { step: string; label: string; status: QaStepStatus; message?: string | null }[];
      safety_notice: string;
    }>("/pilot-launch/run-qa"),
};

export type DemoStepStatus = "ready" | "warning" | "blocked" | "info";

export interface PilotDemoScenario {
  id: string;
  title: string;
  audience: string;
  description: string;
  estimated_minutes: number;
  recommended_for: string;
  journey_route?: string | null;
}

export interface PilotDemoOverview {
  readiness_score: number;
  demo_data_present: boolean;
  demo_company_name?: string | null;
  active_scenario_id: string;
  metrics: {
    demo_buyers: number;
    demo_opportunities: number;
    demo_revenue_usd: number;
    demo_forecast_periods: number;
    demo_marketplace_opportunities: number;
    demo_deals: number;
    demo_proposals: number;
    demo_data_present: boolean;
    demo_company_name?: string | null;
  };
  summary: {
    what_to_show_next?: string | null;
    recommended_flow: string[];
    estimated_presentation_minutes: number;
    readiness_score: number;
  };
  next_recommended_step?: string | null;
  safety_notice: string;
  refreshed_at: string;
}

export interface PilotDemoJourneyStep {
  step: number;
  id: string;
  title: string;
  narrative: string;
  admin_route?: string | null;
  tenant_route?: string | null;
  status: DemoStepStatus;
  message?: string | null;
}

export const pilotDemoApi = {
  overview: () => adminApi.get<PilotDemoOverview>("/pilot-demo/overview"),
  scenarios: () =>
    adminApi.get<{
      scenarios: PilotDemoScenario[];
      default_scenario_id: string;
      safety_notice: string;
    }>("/pilot-demo/scenarios"),
  factoryOwner: () =>
    adminApi.get<{
      scenario_id: string;
      title: string;
      steps: PilotDemoJourneyStep[];
      completed_steps: number;
      total_steps: number;
      current_step_id?: string | null;
      safety_notice: string;
    }>("/pilot-demo/factory-owner"),
  executive: () =>
    adminApi.get<{
      scenario_id: string;
      title: string;
      steps: PilotDemoJourneyStep[];
      completed_steps: number;
      total_steps: number;
      current_step_id?: string | null;
      safety_notice: string;
    }>("/pilot-demo/executive"),
  readiness: () =>
    adminApi.get<{
      readiness_score: number;
      missing_data: string[];
      broken_links: string[];
      unavailable_pages: string[];
      items: { key: string; label: string; status: string; message?: string | null }[];
      demo_data_present: boolean;
      safety_notice: string;
    }>("/pilot-demo/readiness"),
  presentationFlow: (scenarioId = "factory_owner_demo") =>
    adminApi.get<{
      scenario_id: string;
      title: string;
      steps: {
        order: number;
        title: string;
        route: string;
        minutes: number;
        talking_points: string[];
      }[];
      estimated_total_minutes: number;
      recommended_flow: string[];
      what_to_show_next?: string | null;
      safety_notice: string;
    }>("/pilot-demo/presentation-flow", { params: { scenario_id: scenarioId } }),
  refresh: () =>
    adminApi.post<{
      refreshed_at: string;
      readiness_score: number;
      message: string;
      safety_notice: string;
    }>("/pilot-demo/refresh"),
};

export type SalesDemoStepStatus = "ready" | "warning" | "blocked" | "info";

export interface PilotSalesDemoMetrics {
  readiness_score: number;
  buyers_found: number;
  opportunities: number;
  active_deals: number;
  pipeline_value_usd: number;
  revenue_forecast_usd: number;
  deal_rooms: number;
  buyer_countries: string[];
  execution_data_present: boolean;
  company_name?: string | null;
  factory_profile_score: number;
  details: Record<string, unknown>;
}

export interface PilotSalesDemoStoryPhase {
  phase: string;
  title: string;
  narrative: string;
  highlights: string[];
  status: SalesDemoStepStatus;
}

export interface PilotSalesDemoSection {
  id: string;
  title: string;
  summary: string;
  highlights: string[];
  status: SalesDemoStepStatus;
  route?: string | null;
}

export interface PilotSalesDemoOverview {
  execution_marker: string;
  execution_data_present: boolean;
  company_name?: string | null;
  implementation_complete: boolean;
  readiness_score: number;
  metrics: PilotSalesDemoMetrics;
  sections: PilotSalesDemoSection[];
  factory_owner_story: {
    company_name?: string | null;
    execution_data_present: boolean;
    phases: PilotSalesDemoStoryPhase[];
    safety_notice: string;
  };
  demo_flow: {
    title: string;
    steps: {
      order: number;
      title: string;
      route: string;
      minutes: number;
      talking_points: string[];
      module: string;
    }[];
    estimated_total_minutes: number;
    safety_notice: string;
  };
  ctas: {
    id: string;
    title: string;
    description: string;
    route: string;
    action_type: string;
  }[];
  executive_summary: string;
  pilot_execution_report_route: string;
  safety_notice: string;
  refreshed_at: string;
}

export interface PilotSalesDemoSummaryWidget {
  readiness_score: number;
  execution_data_present: boolean;
  company_name?: string | null;
  buyers_found: number;
  active_deals: number;
  pipeline_value_usd: number;
  deal_rooms: number;
  implementation_complete: boolean;
  next_demo_step?: string | null;
  safety_notice: string;
}

export type PilotLaunchValidationStatus = "ready" | "warning" | "blocked";

export interface PilotLaunchValidationOverview {
  readiness_score: number;
  execution_marker: string;
  execution_data_present: boolean;
  company_name?: string | null;
  admin_flow_ready: number;
  admin_flow_total: number;
  tenant_flow_ready: number;
  tenant_flow_total: number;
  data_ready_count: number;
  data_total: number;
  client_facing_ready: number;
  client_facing_total: number;
  blocker_count: number;
  warning_count: number;
  blockers: string[];
  next_actions: string[];
  primary_next_action?: string | null;
  implementation_complete: boolean;
  safety_notice: string;
  refreshed_at: string;
}

export interface PilotLaunchValidationFlowItem {
  id: string;
  label: string;
  route: string;
  api_probe?: string | null;
  status: PilotLaunchValidationStatus;
  reason?: string | null;
  missing_items: string[];
  next_action?: string | null;
  duration_ms?: number | null;
}

export interface PilotLaunchValidationSummaryWidget {
  readiness_score: number;
  execution_data_present: boolean;
  company_name?: string | null;
  admin_flow_ready: number;
  admin_flow_total: number;
  tenant_flow_ready: number;
  tenant_flow_total: number;
  blocker_count: number;
  warning_count: number;
  primary_next_action?: string | null;
  implementation_complete: boolean;
  safety_notice: string;
}

export const pilotLaunchValidationApi = {
  overview: () =>
    adminApi.get<PilotLaunchValidationOverview>("/pilot-launch-validation/overview"),
  readiness: () =>
    adminApi.get<{
      score: number;
      components: {
        key: string;
        label: string;
        score: number;
        weight: number;
        status: PilotLaunchValidationStatus;
        details?: string | null;
      }[];
      execution_data_present: boolean;
      safety_notice: string;
    }>("/pilot-launch-validation/readiness"),
  adminFlow: () =>
    adminApi.get<{
      flow_type: "admin";
      items: PilotLaunchValidationFlowItem[];
      ready_count: number;
      warning_count: number;
      blocked_count: number;
      safety_notice: string;
    }>("/pilot-launch-validation/admin-flow"),
  tenantFlow: () =>
    adminApi.get<{
      flow_type: "tenant";
      items: PilotLaunchValidationFlowItem[];
      ready_count: number;
      warning_count: number;
      blocked_count: number;
      safety_notice: string;
    }>("/pilot-launch-validation/tenant-flow"),
  dataCompleteness: () =>
    adminApi.get<{
      items: {
        id: string;
        label: string;
        status: PilotLaunchValidationStatus;
        count: number;
        required_min: number;
        reason?: string | null;
        missing_items: string[];
        next_action?: string | null;
      }[];
      ready_count: number;
      warning_count: number;
      blocked_count: number;
      execution_data_present: boolean;
      company_name?: string | null;
      safety_notice: string;
    }>("/pilot-launch-validation/data-completeness"),
  clientFacingReadiness: () =>
    adminApi.get<{
      pages: {
        page: string;
        route: string;
        status: PilotLaunchValidationStatus;
        reason?: string | null;
        missing_items: string[];
        next_action?: string | null;
        api_probe?: string | null;
        probe_status?: string | null;
      }[];
      ready_count: number;
      warning_count: number;
      blocked_count: number;
      safety_notice: string;
    }>("/pilot-launch-validation/client-facing-readiness"),
  blockers: () =>
    adminApi.get<{
      blockers: {
        id: string;
        label: string;
        category: string;
        severity: "warning" | "blocked";
        reason?: string | null;
        next_action?: string | null;
      }[];
      warning_count: number;
      blocked_count: number;
      safety_notice: string;
    }>("/pilot-launch-validation/blockers"),
  nextActions: () =>
    adminApi.get<{
      actions: string[];
      primary_action?: string | null;
      safety_notice: string;
    }>("/pilot-launch-validation/next-actions"),
  summaryWidget: () =>
    adminApi.get<PilotLaunchValidationSummaryWidget>(
      "/pilot-launch-validation/summary-widget",
    ),
  refresh: () =>
    adminApi.post<{
      refreshed_at: string;
      readiness_score: number;
      message: string;
      safety_notice: string;
    }>("/pilot-launch-validation/refresh"),
};

export type PilotReadinessStatus = "ready" | "warning" | "blocked";

export interface PilotReadinessHealthComponent {
  key: string;
  label: string;
  status: PilotReadinessStatus;
  score: number;
  message?: string | null;
}

export type PilotReadinessRouteAuditStatus = "pass" | "fail" | "denied" | "slow" | "skipped";

export interface PilotReadinessRouteAudit {
  route: string;
  canonical_route?: string | null;
  audience: "tenant" | "admin" | "both";
  status: PilotReadinessRouteAuditStatus;
  access: "allowed" | "denied" | "login_required" | "unknown";
  api_probe?: string | null;
  api_status_code?: number | null;
  duration_ms?: number | null;
  issue?: string | null;
}

export interface PilotReadinessOverview {
  readiness_score: number;
  status: PilotReadinessStatus;
  generated_at: string;
  safety_notice: string;
  demo_tenant_health: PilotReadinessHealthComponent;
  auth_rbac_status: PilotReadinessHealthComponent;
  backend_status: PilotReadinessHealthComponent;
  database_status: PilotReadinessHealthComponent;
  briefs_count: number;
  content_tasks_count: number;
  approved_content_count: number;
  scheduled_published_content_count: number;
  open_issues: string[];
  route_audits: PilotReadinessRouteAudit[];
  routes_pass_count: number;
  routes_fail_count: number;
}

export const pilotReadinessApi = {
  overview: () => pickActiveSessionClient().get<PilotReadinessOverview>("/pilot-readiness/overview"),
};

export type PilotDemoModeStepStatus = "pending" | "active" | "complete" | "blocked";

export interface PilotDemoModeStep {
  step: number;
  id: string;
  title: string;
  description: string;
  status: PilotDemoModeStepStatus;
  completed_at?: string | null;
  action_key?: string | null;
}

export interface PilotDemoModeKpi {
  key: string;
  label: string;
  value: string | number;
  trend?: string | null;
}

export interface PilotDemoModeOverview {
  workflow_steps: PilotDemoModeStep[];
  current_step: number;
  progress_percent: number;
  readiness_status: "ready" | "in_progress" | "not_started";
  readiness_score: number;
  kpis: PilotDemoModeKpi[];
  workflow_diagram: {
    nodes: { id: string; label: string; status: string; step: number }[];
    edges: { from: string; to: string }[];
  };
  executive_summary: string;
  demo_data_present: boolean;
  demo_brief_id?: string | null;
  demo_tenant_id?: string | null;
  demo_client_id?: string | null;
  safety_notice: string;
  refreshed_at: string;
}

export type PilotDemoModeAction =
  | "create_sample_brief"
  | "generate_sample_plan"
  | "approve_sample_plan"
  | "create_sample_tasks"
  | "simulate_publishing_pipeline"
  | "generate_sample_revenue_metrics";

export const pilotDemoModeApi = {
  overview: () => adminApi.get<PilotDemoModeOverview>("/pilot-demo-mode/overview"),
  runAction: (action: PilotDemoModeAction) =>
    adminApi.post<{
      success: boolean;
      action: string;
      message: string;
      overview: PilotDemoModeOverview;
    }>(`/pilot-demo-mode/actions/${action}`),
  reset: () =>
    adminApi.post<{
      success: boolean;
      message: string;
      deleted_counts: Record<string, number>;
      overview: PilotDemoModeOverview;
    }>("/pilot-demo-mode/reset"),
};

export const pilotSalesDemoApi = {
  overview: () => adminApi.get<PilotSalesDemoOverview>("/pilot-sales-demo/overview"),
  metrics: () => adminApi.get<PilotSalesDemoMetrics>("/pilot-sales-demo/metrics"),
  factoryOwnerStory: () =>
    adminApi.get<PilotSalesDemoOverview["factory_owner_story"]>(
      "/pilot-sales-demo/factory-owner-story",
    ),
  demoFlow: () =>
    adminApi.get<PilotSalesDemoOverview["demo_flow"]>("/pilot-sales-demo/demo-flow"),
  summaryWidget: () =>
    adminApi.get<PilotSalesDemoSummaryWidget>("/pilot-sales-demo/summary-widget"),
  refresh: () =>
    adminApi.post<{
      refreshed_at: string;
      readiness_score: number;
      message: string;
      safety_notice: string;
    }>("/pilot-sales-demo/refresh"),
};

export type FirstPilotReadinessStatus = "ready" | "warning" | "blocked";
export type FirstPilotBlockerSeverity = "critical" | "warning";
export type FirstPilotRecommendationPriority = "high" | "medium" | "low";
export type FirstPilotOperationalStatus = "ready" | "warning" | "blocked" | "unavailable";

export interface FirstPilotReadinessComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  status: FirstPilotReadinessStatus;
  details?: string | null;
}

export interface FirstPilotReadiness {
  score: number;
  components: FirstPilotReadinessComponent[];
  client_identified: boolean;
  company_name?: string | null;
  application_id?: string | null;
  tenant_id?: string | null;
  safety_notice: string;
}

export interface FirstPilotOperationalItem {
  key: string;
  label: string;
  status: FirstPilotOperationalStatus;
  ready: boolean;
  message?: string | null;
}

export interface FirstPilotOperationalReadiness {
  items: FirstPilotOperationalItem[];
  ready_count: number;
  total: number;
  all_ready: boolean;
  safety_notice: string;
}

export interface FirstPilotBlocker {
  blocker: string;
  label: string;
  severity: FirstPilotBlockerSeverity;
  message: string;
  route_hint?: string | null;
}

export interface FirstPilotRecommendation {
  id: string;
  title: string;
  description: string;
  priority: FirstPilotRecommendationPriority;
  route_hint?: string | null;
}

export interface FirstPilotNextAction {
  title: string;
  description: string;
  route_hint?: string | null;
  priority: FirstPilotRecommendationPriority;
}

export interface FirstPilotOverview {
  readiness_score: number;
  operational_ready: boolean;
  launch_ready: boolean;
  client_identified: boolean;
  company_name?: string | null;
  application_id?: string | null;
  tenant_id?: string | null;
  client_id?: string | null;
  onboarding_status?: string | null;
  blocker_count: number;
  critical_blocker_count: number;
  recommendation_count: number;
  client_readiness: FirstPilotReadiness;
  operational_readiness: FirstPilotOperationalReadiness;
  blockers: FirstPilotBlocker[];
  next_action?: FirstPilotNextAction | null;
  integration_checks: { module: string; status: string; message: string }[];
  safety_notice: string;
  implementation_complete: boolean;
}

export interface FirstPilotSummary {
  readiness_score: number;
  operational_ready: boolean;
  launch_ready: boolean;
  blockers: FirstPilotBlocker[];
  recommendations: FirstPilotRecommendation[];
  next_action?: FirstPilotNextAction | null;
  company_name?: string | null;
  application_id?: string | null;
  tenant_id?: string | null;
  onboarding_status?: string | null;
  safety_notice: string;
}

export interface FirstPilotSummaryWidget {
  readiness_score: number;
  launch_ready: boolean;
  client_identified: boolean;
  company_name?: string | null;
  blocker_count: number;
  critical_blocker_count: number;
  onboarding_status?: string | null;
  next_action_title?: string | null;
  safety_notice: string;
}

export const firstPilotClientApi = {
  overview: () => adminApi.get<FirstPilotOverview>("/first-pilot-client/overview"),
  readiness: () => adminApi.get<FirstPilotReadiness>("/first-pilot-client/readiness"),
  blockers: () =>
    adminApi.get<{
      blockers: FirstPilotBlocker[];
      blocker_count: number;
      critical_count: number;
      company_name?: string | null;
      application_id?: string | null;
      safety_notice: string;
    }>("/first-pilot-client/blockers"),
  recommendations: () =>
    adminApi.get<{
      high_priority: FirstPilotRecommendation[];
      medium_priority: FirstPilotRecommendation[];
      low_priority: FirstPilotRecommendation[];
      total: number;
      safety_notice: string;
    }>("/first-pilot-client/recommendations"),
  summary: () => adminApi.get<FirstPilotSummary>("/first-pilot-client/summary"),
  summaryWidget: () => adminApi.get<FirstPilotSummaryWidget>("/first-pilot-client/summary-widget"),
  tenantIndicator: (tenantId: string) =>
    adminApi.get<{
      is_pilot_client: boolean;
      readiness_score: number;
      profile_score?: number;
      launch_ready: boolean;
      blocker_count: number;
      company_name?: string | null;
      message: string;
      safety_notice: string;
    }>("/first-pilot-client/tenant-indicator", { params: { tenant_id: tenantId } }),
  refresh: () =>
    adminApi.post<{
      refreshed_at: string;
      readiness_score: number;
      blocker_count: number;
      launch_ready: boolean;
      next_action?: FirstPilotNextAction | null;
      safety_notice: string;
    }>("/first-pilot-client/refresh"),
};

export type RealFactoryPilotStatus =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "ready_for_demo"
  | "ready_for_live_pilot"
  | "live_pilot_started"
  | "completed";

export interface RealFactoryPilotWorkspace {
  application_id?: string | null;
  company_name?: string | null;
  client_id?: string | null;
  tenant_id?: string | null;
  subscription_status?: string | null;
  admin_user_email?: string | null;
  factory_profile_score: number;
  catalog_count: number;
  certificate_count: number;
  export_market_count: number;
  buyer_opportunity_count: number;
  marketplace_activity_count: number;
  factory_identified: boolean;
}

export interface RealFactoryPilotReadinessComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  status: FirstPilotReadinessStatus;
  details?: string | null;
}

export interface RealFactoryPilotReadiness {
  score: number;
  components: RealFactoryPilotReadinessComponent[];
  factory_identified: boolean;
  company_name?: string | null;
  application_id?: string | null;
  tenant_id?: string | null;
  safety_notice: string;
}

export interface RealFactoryPilotChecklistItem {
  step: string;
  label: string;
  completed: boolean;
  status: "completed" | "pending" | "blocked";
  completed_at?: string | null;
  details?: string | null;
}

export interface RealFactoryPilotChecklist {
  items: RealFactoryPilotChecklistItem[];
  completed_count: number;
  total_steps: number;
  progress_percent: number;
  company_name?: string | null;
  application_id?: string | null;
  safety_notice: string;
}

export interface RealFactoryPilotBlocker {
  blocker: string;
  label: string;
  severity: "critical" | "warning";
  message: string;
  route_hint?: string | null;
}

export interface RealFactoryPilotAction {
  action: string;
  label: string;
  description: string;
  route_hint: string;
  available: boolean;
  manual_only: boolean;
}

export interface RealFactoryPilotNextAction {
  title: string;
  description: string;
  route_hint?: string | null;
  action?: string | null;
  priority: "high" | "medium" | "low";
}

export interface RealFactoryPilotOverview {
  status: RealFactoryPilotStatus;
  readiness_score: number;
  factory_identified: boolean;
  company_name?: string | null;
  application_id?: string | null;
  tenant_id?: string | null;
  client_id?: string | null;
  blocker_count: number;
  warning_count: number;
  critical_blocker_count: number;
  checklist_completed: number;
  checklist_total: number;
  workspace: RealFactoryPilotWorkspace;
  readiness: RealFactoryPilotReadiness;
  checklist: RealFactoryPilotChecklist;
  blockers: RealFactoryPilotBlocker[];
  warnings: RealFactoryPilotBlocker[];
  actions: RealFactoryPilotAction[];
  next_best_action?: RealFactoryPilotNextAction | null;
  pilot_launch_notes: string[];
  integration_checks: { module: string; status: string; message: string }[];
  safety_notice: string;
  implementation_complete: boolean;
}

export interface RealFactoryPilotSummary {
  selected_factory?: RealFactoryPilotWorkspace | null;
  status: RealFactoryPilotStatus;
  readiness_score: number;
  blockers: RealFactoryPilotBlocker[];
  warnings: RealFactoryPilotBlocker[];
  next_best_action?: RealFactoryPilotNextAction | null;
  pilot_launch_notes: string[];
  safety_notice: string;
}

export interface RealFactoryPilotSummaryWidget {
  readiness_score: number;
  status: RealFactoryPilotStatus;
  factory_identified: boolean;
  company_name?: string | null;
  blocker_count: number;
  critical_blocker_count: number;
  checklist_progress: number;
  next_action_title?: string | null;
  safety_notice: string;
}

export const realFactoryPilotApi = {
  overview: () => adminApi.get<RealFactoryPilotOverview>("/real-factory-pilot/overview"),
  checklist: () => adminApi.get<RealFactoryPilotChecklist>("/real-factory-pilot/checklist"),
  blockers: () =>
    adminApi.get<{
      blockers: RealFactoryPilotBlocker[];
      warnings: RealFactoryPilotBlocker[];
      blocker_count: number;
      warning_count: number;
      critical_count: number;
      company_name?: string | null;
      application_id?: string | null;
      safety_notice: string;
    }>("/real-factory-pilot/blockers"),
  actions: () =>
    adminApi.get<{
      actions: RealFactoryPilotAction[];
      next_action?: RealFactoryPilotAction | null;
      safety_notice: string;
    }>("/real-factory-pilot/actions"),
  readiness: () => adminApi.get<RealFactoryPilotReadiness>("/real-factory-pilot/readiness"),
  summary: () => adminApi.get<RealFactoryPilotSummary>("/real-factory-pilot/summary"),
  summaryWidget: () =>
    adminApi.get<RealFactoryPilotSummaryWidget>("/real-factory-pilot/summary-widget"),
  candidateIndicator: (applicationId: string) =>
    adminApi.get<{
      application_id: string;
      is_pilot_candidate: boolean;
      is_selected_factory: boolean;
      company_name?: string | null;
      readiness_score: number;
      status: RealFactoryPilotStatus;
      safety_notice: string;
    }>("/real-factory-pilot/candidate-indicator", { params: { application_id: applicationId } }),
  refresh: () =>
    adminApi.post<{
      refreshed_at: string;
      readiness_score: number;
      status: RealFactoryPilotStatus;
      blocker_count: number;
      next_best_action?: RealFactoryPilotNextAction | null;
      safety_notice: string;
    }>("/real-factory-pilot/refresh"),
};

export type ProductionEnvStatus = "valid" | "warning" | "critical";
export type ProductionChecklistStatus = "completed" | "warning" | "blocked";
export type ProductionItemStatus = "ready" | "warning" | "blocked";

export interface ProductionReadinessComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  status: FirstPilotReadinessStatus;
  details?: string | null;
}

export interface ProductionDeploymentOverview {
  production_readiness_score: number;
  deployment_ready: boolean;
  environment_valid: boolean;
  checklist_completed: number;
  checklist_blocked: number;
  backup_ready: boolean;
  monitoring_ready: boolean;
  security_score: number;
  critical_finding_count: number;
  blocker_count: number;
  warning_count: number;
  readiness: {
    production_readiness_score: number;
    components: ProductionReadinessComponent[];
    safety_notice: string;
  };
  environment: {
    valid: boolean;
    critical_count: number;
    warning_count: number;
    checks: Array<{
      key: string;
      label: string;
      status: ProductionEnvStatus;
      message: string;
      configured: boolean;
    }>;
    safety_notice: string;
  };
  checklist: {
    items: Array<{
      key: string;
      label: string;
      status: ProductionChecklistStatus;
      message: string;
      next_action?: string | null;
    }>;
    completed_count: number;
    warning_count: number;
    blocked_count: number;
    all_ready: boolean;
    next_action?: string | null;
    safety_notice: string;
  };
  backups: {
    items: Array<{
      key: string;
      label: string;
      status: ProductionItemStatus;
      message: string;
      configured: boolean;
    }>;
    ready_count: number;
    total: number;
    all_ready: boolean;
    safety_notice: string;
  };
  monitoring: {
    items: Array<{
      key: string;
      label: string;
      status: ProductionItemStatus;
      message: string;
      details: Record<string, unknown>;
    }>;
    ready_count: number;
    total: number;
    all_ready: boolean;
    safety_notice: string;
  };
  security: {
    readiness_score: number;
    critical_findings: Array<{
      key: string;
      label: string;
      severity: "critical" | "warning";
      message: string;
    }>;
    warnings: Array<{
      key: string;
      label: string;
      severity: "critical" | "warning";
      message: string;
    }>;
    protected_route_count: number;
    open_route_count: number;
    permission_coverage_percent: number;
    implementation_complete: boolean;
    safety_notice: string;
  };
  summary: {
    readiness_score: number;
    deployment_ready: boolean;
    blockers: string[];
    warnings: string[];
    recommendations: FirstPilotRecommendation[];
    next_action?: FirstPilotNextAction | null;
    safety_notice: string;
  };
  integration_checks: Array<{
    module: string;
    status: "ok" | "degraded";
    message: string;
    details: Record<string, unknown>;
  }>;
  safety_notice: string;
  implementation_complete: boolean;
}

export interface ProductionSummaryWidget {
  production_readiness_score: number;
  deployment_ready: boolean;
  blocker_count: number;
  critical_finding_count: number;
  environment_valid: boolean;
  next_action_title?: string | null;
  safety_notice: string;
}

export const productionDeploymentApi = {
  overview: () =>
    adminApi.get<ProductionDeploymentOverview>("/production-deployment/overview"),
  readiness: () =>
    adminApi.get<ProductionDeploymentOverview["readiness"]>("/production-deployment/readiness"),
  environment: () =>
    adminApi.get<ProductionDeploymentOverview["environment"]>("/production-deployment/environment"),
  checklist: () =>
    adminApi.get<ProductionDeploymentOverview["checklist"]>("/production-deployment/checklist"),
  backups: () =>
    adminApi.get<ProductionDeploymentOverview["backups"]>("/production-deployment/backups"),
  monitoring: () =>
    adminApi.get<ProductionDeploymentOverview["monitoring"]>("/production-deployment/monitoring"),
  security: () =>
    adminApi.get<ProductionDeploymentOverview["security"]>("/production-deployment/security"),
  summary: () =>
    adminApi.get<ProductionDeploymentOverview["summary"]>("/production-deployment/summary"),
  summaryWidget: () =>
    adminApi.get<ProductionSummaryWidget>("/production-deployment/summary-widget"),
  refresh: () =>
    adminApi.post<{
      refreshed_at: string;
      production_readiness_score: number;
      deployment_ready: boolean;
      blocker_count: number;
      next_action?: FirstPilotNextAction | null;
      safety_notice: string;
    }>("/production-deployment/refresh"),
};

export type PortalStatus = "pending" | "active" | "suspended";

export interface CustomerPortalAccount {
  id: string;
  company_id: string;
  company_name: string;
  portal_status: PortalStatus;
  owner_user?: string | null;
  factory_partner_application_id?: string | null;
  created_at: string;
}

export interface CustomerPortalRevenueSummary {
  total_revenue: number | string;
  deals_won: number;
  avg_deal_size: number | string;
  conversion_rate: number;
  currency: string;
}

export interface CustomerPortalDashboard {
  account: CustomerPortalAccount;
  active_leads: number;
  active_buyers: number;
  discovered_buyers?: number;
  high_potential_discoveries?: number;
  proposals: number;
  opportunities: number;
  marketplace_opportunities?: number;
  marketplace_total?: number;
  revenue_summary: CustomerPortalRevenueSummary;
  safety_notice: string;
  errors?: string[];
}

export interface CustomerPortalBuyerItem {
  buyer_id: string;
  name: string;
  company?: string | null;
  buyer_score: number;
  classification: BuyerClassification;
  risk_level: BuyerRiskLevel;
  opportunities: number;
  annual_potential: number | string;
  status: string;
}

export interface CustomerPortalDealItem {
  deal_id: string;
  title: string;
  buyer_name?: string | null;
  status: string;
  deal_health_score: number;
  risk_level: DealRiskLevel;
  close_probability: number;
  expected_close_date?: string | null;
  revenue: number | string;
  currency: string;
}

export interface CustomerPortalProposalItem {
  proposal_id: string;
  title: string;
  status: string;
  buyer_name?: string | null;
  sent_at?: string | null;
  created_at?: string | null;
}

export interface CustomerPortalForecastPeriod {
  period: string;
  best_case: number | string;
  expected_case: number | string;
  worst_case: number | string;
  currency: string;
}

export interface CustomerPortalTopBuyer {
  buyer_id: string;
  name: string;
  buyer_score: number;
  classification: string;
  annual_potential: number | string;
}

export interface CustomerPortalReports {
  account: CustomerPortalAccount;
  revenue_attribution: CustomerPortalRevenueSummary;
  revenue_forecast: CustomerPortalForecastPeriod[];
  forecast_confidence: string;
  top_buyers: CustomerPortalTopBuyer[];
  buyer_opportunities?: {
    buyer_id: string;
    company_name: string;
    opportunity_score: number;
    category: string;
    country?: string | null;
    industry?: string | null;
  }[];
  errors?: string[];
  safety_notice: string;
}

export interface CustomerPortalSummaryWidget {
  active_accounts: number;
  pending_accounts: number;
  suspended_accounts: number;
  total_accounts: number;
  latest_company_name?: string | null;
}

export type TenantStatus = "pending" | "active" | "suspended" | "archived";
export type TenantPlan = "starter" | "growth" | "enterprise" | "trial";
export type TenantUserRole = "owner" | "manager" | "sales" | "operator" | "viewer";
export type TenantUserStatus = "invited" | "active" | "suspended" | "removed";

export interface Tenant {
  id: string;
  company_name: string;
  status: TenantStatus;
  plan: TenantPlan;
  factory_partner_application_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TenantUser {
  id: string;
  tenant_id: string;
  email: string;
  role: TenantUserRole;
  status: TenantUserStatus;
  created_at: string;
  permissions: string[];
}

export interface TenantPortalStatus {
  has_portal_account: boolean;
  portal_account_id?: string | null;
  portal_status?: string | null;
  company_id?: string | null;
}

export interface TenantUsageSummary {
  client_count: number;
  active_users: number;
  crm_leads: number;
  crm_deals: number;
  portal_accounts: number;
}

export interface TenantDashboard {
  tenant: Tenant;
  users: TenantUser[];
  portal_status: TenantPortalStatus;
  usage_summary: TenantUsageSummary;
  subscription_overview?: {
    billing_summary: SubscriptionBillingSummary;
    recent_subscriptions: SubscriptionRecord[];
    safety_notice: string;
  } | null;
  roles_available: TenantUserRole[];
  safety_notice: string;
}

export interface TenantIsolationCheck {
  tenant_id: string;
  isolated: boolean;
  client_ids: string[];
  cross_tenant_leak: boolean;
  message: string;
}

export const tenantsApi = {
  list: (params?: { status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: Tenant[]; total: number }>("/tenants", { params }),
  get: (id: string) => api.get<TenantDashboard>(`/tenants/${id}`),
  create: (body: {
    company_name: string;
    status?: TenantStatus;
    plan?: TenantPlan;
    factory_partner_application_id?: string;
    owner_email?: string;
  }) => api.post<{ tenant: Tenant; owner_user?: TenantUser; message: string }>("/tenants", body),
  update: (id: string, body: Partial<{ company_name: string; status: TenantStatus; plan: TenantPlan }>) =>
    api.patch<Tenant>(`/tenants/${id}`, body),
  listUsers: (id: string, params?: { skip?: number; limit?: number }) =>
    api.get<{ tenant_id: string; items: TenantUser[]; total: number }>(`/tenants/${id}/users`, {
      params,
    }),
  addUser: (id: string, body: { email: string; role?: TenantUserRole; status?: TenantUserStatus }) =>
    api.post<TenantUser>(`/tenants/${id}/users`, body),
  isolationCheck: (id: string) => api.get<TenantIsolationCheck>(`/tenants/${id}/isolation-check`),
};

export interface FactoryPlatformWorkspace {
  tenant_id: string;
  company_id: string;
  company_name: string;
  tenant_status: string;
  has_portal?: boolean;
}

export interface FactoryPlatformTenantRef {
  tenant_id: string;
  company_id: string;
  company_name: string;
  tenant_status: string;
}

export interface FactoryPlatformCompanyProfile {
  company_id: string;
  company_name: string;
  country?: string | null;
  city?: string | null;
  website?: string | null;
  industry?: string | null;
  company_description?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  markets: string[];
  industries: string[];
  export_regions: string[];
  product_categories: string[];
  business_category?: string | null;
  updated_at?: string | null;
}

export interface FactoryPlatformDashboard {
  tenant: FactoryPlatformTenantRef;
  company_profile: FactoryPlatformCompanyProfile;
  active_buyers: number;
  active_leads: number;
  active_deals: number;
  proposals_count: number;
  proposals: {
    proposal_id: string;
    title: string;
    status: string;
    buyer_name?: string | null;
    created_at?: string | null;
  }[];
  revenue_summary: {
    total_revenue: number | string;
    deals_won: number;
    avg_deal_size: number | string;
    conversion_rate: number;
    currency: string;
  };
  billing_summary: Record<string, unknown>;
  safety_notice: string;
  errors?: string[];
}

export interface FactoryPlatformProducts {
  tenant: FactoryPlatformTenantRef;
  categories: string[];
  products: {
    product_id: string;
    name: string;
    sku?: string | null;
    category?: string | null;
    description?: string | null;
    moq?: number | null;
    unit_price?: number | string | null;
    currency: string;
    active: boolean;
  }[];
  products_total: number;
  catalog_records: {
    job_id: string;
    source_type: string;
    status: string;
    created_at?: string | null;
  }[];
  errors?: string[];
}

export interface FactoryPlatformReports {
  tenant: FactoryPlatformTenantRef;
  buyer_intelligence: Record<string, unknown>;
  top_buyers: {
    buyer_id: string;
    name: string;
    buyer_score: number;
    classification: string;
    risk_level: string;
    annual_potential: number | string;
  }[];
  buyer_discovery?: Record<string, unknown>;
  discovery_opportunities?: {
    buyer_id: string;
    company_name: string;
    opportunity_score: number;
    category: string;
    country?: string | null;
    industry?: string | null;
  }[];
  deal_risk: Record<string, unknown>;
  high_risk_deals: {
    deal_id: string;
    title: string;
    risk_level: string;
    deal_health_score: number;
    close_probability: number;
    revenue: number | string;
  }[];
  revenue_forecast: {
    period: string;
    best_case: number | string;
    expected_case: number | string;
    worst_case: number | string;
    currency: string;
  }[];
  forecast_confidence: string;
  revenue_attribution: FactoryPlatformDashboard["revenue_summary"];
  errors?: string[];
  safety_notice: string;
}

export interface FactoryPlatformInsights {
  tenant: FactoryPlatformTenantRef;
  buyer_opportunities: {
    buyer_id: string;
    name: string;
    classification: string;
    buyer_score: number;
    reason: string;
  }[];
  export_discovery?: {
    buyer_id: string;
    company_name: string;
    opportunity_score: number;
    category: string;
    country?: string | null;
    industry?: string | null;
  }[];
  deal_risks: {
    deal_id: string;
    title: string;
    risk_level: string;
    reason: string;
  }[];
  recommended_actions: {
    action: string;
    priority: string;
    source: string;
  }[];
  errors?: string[];
  safety_notice: string;
}

export const factoryPlatformApi = {
  workspaces: () =>
    api.get<{ items: FactoryPlatformWorkspace[]; total: number }>("/factory-platform/workspaces"),
  dashboard: (tenantId: string) =>
    api.get<FactoryPlatformDashboard>("/factory-platform/dashboard", {
      params: { tenant_id: tenantId },
    }),
  company: (tenantId: string) =>
    api.get<{ tenant: FactoryPlatformTenantRef; profile: FactoryPlatformCompanyProfile; errors?: string[] }>(
      "/factory-platform/company",
      { params: { tenant_id: tenantId } },
    ),
  products: (tenantId: string, params?: { skip?: number; limit?: number }) =>
    api.get<FactoryPlatformProducts>("/factory-platform/products", {
      params: { tenant_id: tenantId, ...params },
    }),
  reports: (tenantId: string) =>
    api.get<FactoryPlatformReports>("/factory-platform/reports", {
      params: { tenant_id: tenantId },
    }),
  insights: (tenantId: string) =>
    api.get<FactoryPlatformInsights>("/factory-platform/insights", {
      params: { tenant_id: tenantId },
    }),
  profile: (tenantId: string) =>
    api.get<FactoryCompanyProfileResponse>("/factory-platform/profile", {
      params: { tenant_id: tenantId },
    }),
  catalog: (tenantId: string) =>
    api.get<FactoryCatalogResponse>("/factory-platform/catalog", {
      params: { tenant_id: tenantId },
    }),
  certificates: (tenantId: string) =>
    api.get<FactoryCertificatesResponse>("/factory-platform/certificates", {
      params: { tenant_id: tenantId },
    }),
  exportMarkets: (tenantId: string) =>
    api.get<FactoryExportMarketsResponse>("/factory-platform/export-markets", {
      params: { tenant_id: tenantId },
    }),
  performance: (tenantId: string) =>
    api.get<FactoryPerformanceResponse>("/factory-platform/performance", {
      params: { tenant_id: tenantId },
    }),
  profileScore: (tenantId: string) =>
    api.get<FactoryProfileScoreResponse>("/factory-platform/profile-score", {
      params: { tenant_id: tenantId },
    }),
  verificationStatus: (tenantId: string) =>
    api.get<FactoryVerificationStatusResponse>("/factory-platform/verification-status", {
      params: { tenant_id: tenantId },
    }),
  summaryWidget: (tenantId?: string) =>
    api.get<FactoryPerformanceSummaryWidget>("/factory-platform/summary-widget", {
      params: tenantId ? { tenant_id: tenantId } : undefined,
    }),
  profileReadiness: (tenantId: string) =>
    api.get<FactoryProfileReadinessResponse>("/factory-platform/profile-readiness", {
      params: { tenant_id: tenantId },
    }),
  updateProfile: (tenantId: string, body: FactoryProfileUpdateRequest) =>
    api.patch<FactoryCompanyProfileResponse>("/factory-platform/profile", body, {
      params: { tenant_id: tenantId },
    }),
  createCatalogProduct: (tenantId: string, body: FactoryCatalogProductCreate) =>
    api.post<{ tenant: FactoryPlatformTenantRef; item: FactoryCatalogItem }>(
      "/factory-platform/catalog/products",
      body,
      { params: { tenant_id: tenantId } },
    ),
  updateCatalogProduct: (tenantId: string, productId: string, body: FactoryCatalogProductUpdate) =>
    api.patch<{ tenant: FactoryPlatformTenantRef; item: FactoryCatalogItem }>(
      `/factory-platform/catalog/products/${productId}`,
      body,
      { params: { tenant_id: tenantId } },
    ),
  deleteCatalogProduct: (tenantId: string, productId: string) =>
    api.delete<{ deleted: boolean; product_id: string }>(
      `/factory-platform/catalog/products/${productId}`,
      { params: { tenant_id: tenantId } },
    ),
  createCertificate: (tenantId: string, body: FactoryCertificateCreate) =>
    api.post<{ tenant: FactoryPlatformTenantRef; item: FactoryCertificateItem }>(
      "/factory-platform/certificates",
      body,
      { params: { tenant_id: tenantId } },
    ),
  updateCertificate: (tenantId: string, certificateId: string, body: FactoryCertificateUpdate) =>
    api.patch<{ tenant: FactoryPlatformTenantRef; item: FactoryCertificateItem }>(
      `/factory-platform/certificates/${certificateId}`,
      body,
      { params: { tenant_id: tenantId } },
    ),
  deleteCertificate: (tenantId: string, certificateId: string) =>
    api.delete<{ deleted: boolean; certificate_id: string }>(
      `/factory-platform/certificates/${certificateId}`,
      { params: { tenant_id: tenantId } },
    ),
  createExportMarket: (tenantId: string, body: FactoryExportMarketCreate) =>
    api.post<{ tenant: FactoryPlatformTenantRef; item: FactoryExportMarketItem }>(
      "/factory-platform/export-markets",
      body,
      { params: { tenant_id: tenantId } },
    ),
  updateExportMarket: (tenantId: string, marketId: string, body: FactoryExportMarketUpdate) =>
    api.patch<{ tenant: FactoryPlatformTenantRef; item: FactoryExportMarketItem }>(
      `/factory-platform/export-markets/${marketId}`,
      body,
      { params: { tenant_id: tenantId } },
    ),
  deleteExportMarket: (tenantId: string, marketId: string) =>
    api.delete<{ deleted: boolean; market_id: string }>(
      `/factory-platform/export-markets/${marketId}`,
      { params: { tenant_id: tenantId } },
    ),
  media: (tenantId: string) =>
    api.get<FactoryMediaResponse>("/factory-platform/media", {
      params: { tenant_id: tenantId },
    }),
  uploadMedia: (tenantId: string, formData: FormData) =>
    api.post<{ tenant: FactoryPlatformTenantRef; item: FactoryMediaItem }>(
      "/factory-platform/media",
      formData,
      {
        params: { tenant_id: tenantId },
        headers: { "Content-Type": "multipart/form-data" },
      },
    ),
  deleteMedia: (tenantId: string, mediaId: string) =>
    api.delete<{ deleted: boolean; media_id: string }>(
      `/factory-platform/media/${mediaId}`,
      { params: { tenant_id: tenantId } },
    ),
};

export interface FactoryCompanyProfileV2 {
  company_name: string;
  brand_name?: string | null;
  description?: string | null;
  country?: string | null;
  city?: string | null;
  address?: string | null;
  website?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  founded_year?: number | null;
  employee_count?: number | null;
  industry?: string | null;
  logo_url?: string | null;
  factory_video_url?: string | null;
  updated_at?: string | null;
}

export interface FactoryProfileUpdateRequest {
  company_name?: string;
  brand_name?: string;
  description?: string;
  country?: string;
  city?: string;
  address?: string;
  website?: string;
  contact_email?: string;
  contact_phone?: string;
  founded_year?: number;
  employee_count?: number;
  logo_url?: string;
  factory_video_url?: string;
}

export interface FactoryCompanyProfileResponse {
  tenant: FactoryPlatformTenantRef;
  profile: FactoryCompanyProfileV2;
  errors?: string[];
  safety_notice: string;
}

export interface FactoryCatalogItem {
  product_id: string;
  product_name: string;
  category?: string | null;
  description?: string | null;
  target_markets: string[];
  image_url?: string | null;
  moq?: number | null;
  price_min?: number | null;
  price_max?: number | null;
  currency?: string | null;
  export_available?: boolean;
  status: "active" | "draft" | "archived";
  updated_at?: string | null;
}

export interface FactoryCatalogProductCreate {
  product_name: string;
  category?: string;
  description?: string;
  target_markets?: string[];
  image_url?: string;
  moq?: number;
  price_min?: number;
  price_max?: number;
  currency?: string;
  export_available?: boolean;
  status?: "active" | "draft" | "archived";
}

export interface FactoryCatalogProductUpdate {
  product_name?: string;
  category?: string;
  description?: string;
  target_markets?: string[];
  image_url?: string;
  moq?: number;
  price_min?: number;
  price_max?: number;
  currency?: string;
  export_available?: boolean;
  status?: "active" | "draft" | "archived";
}

export interface FactoryCatalogResponse {
  tenant: FactoryPlatformTenantRef;
  items: FactoryCatalogItem[];
  total: number;
  active_count: number;
  draft_count: number;
  archived_count: number;
  errors?: string[];
}

export interface FactoryCertificateItem {
  certificate_id: string;
  certificate_name: string;
  certificate_type: string;
  issuing_authority?: string | null;
  certificate_number?: string | null;
  issue_date?: string | null;
  expiry_date?: string | null;
  document_url?: string | null;
  is_expired: boolean;
}

export interface FactoryCertificateCreate {
  certificate_name: string;
  certificate_type: string;
  issuing_authority?: string;
  certificate_number?: string;
  issue_date?: string;
  expiry_date?: string;
  document_url?: string;
}

export interface FactoryCertificateUpdate {
  certificate_name?: string;
  certificate_type?: string;
  issuing_authority?: string;
  certificate_number?: string;
  issue_date?: string;
  expiry_date?: string;
  document_url?: string;
}

export interface FactoryCertificatesResponse {
  tenant: FactoryPlatformTenantRef;
  items: FactoryCertificateItem[];
  total: number;
  valid_count: number;
  expired_count: number;
  errors?: string[];
}

export interface FactoryExportMarketItem {
  market_id: string;
  country: string;
  market_score: number;
  active_buyers: number;
  opportunities: number;
}

export interface FactoryExportMarketCreate {
  country: string;
  market_score?: number;
  active_buyers?: number;
  opportunities?: number;
}

export interface FactoryExportMarketUpdate {
  country?: string;
  market_score?: number;
  active_buyers?: number;
  opportunities?: number;
}

export interface FactoryExportMarketsResponse {
  tenant: FactoryPlatformTenantRef;
  items: FactoryExportMarketItem[];
  total: number;
  errors?: string[];
}

export interface FactoryProfileScoreComponents {
  profile: number;
  products: number;
  certificates: number;
  export_markets: number;
}

export interface FactoryReadinessBreakdownItem {
  key: string;
  label: string;
  score: number;
  max_score: number;
  complete: boolean;
  recommended_action?: string | null;
}

export interface FactoryProfileScoreResponse {
  tenant: FactoryPlatformTenantRef;
  profile_score: number;
  components: FactoryProfileScoreComponents;
  missing_items: string[];
  breakdown?: FactoryReadinessBreakdownItem[];
  recommended_actions?: string[];
  errors?: string[];
}

export interface FactoryProfileReadinessResponse {
  tenant: FactoryPlatformTenantRef;
  profile_score: number;
  components: FactoryProfileScoreComponents;
  breakdown: FactoryReadinessBreakdownItem[];
  missing_items: string[];
  recommended_actions: string[];
  errors?: string[];
}

export interface FactoryMediaItem {
  media_id: string;
  media_type: string;
  title?: string | null;
  description?: string | null;
  url?: string | null;
  original_filename?: string | null;
  reusable_modules: string[];
  created_at?: string | null;
}

export interface FactoryMediaResponse {
  tenant: FactoryPlatformTenantRef;
  items: FactoryMediaItem[];
  total: number;
  image_count: number;
  video_count: number;
  pdf_count: number;
  errors?: string[];
}

export interface FactoryPerformanceResponse {
  tenant: FactoryPlatformTenantRef;
  total_buyers: number;
  active_opportunities: number;
  marketplace_visibility: number;
  buyer_acquisition_score: number;
  profile_score: number;
  errors?: string[];
  safety_notice: string;
}

export interface FactoryVerificationStatusResponse {
  tenant: FactoryPlatformTenantRef;
  verification_status: "unverified" | "pending" | "verified";
  profile_score: number;
  requirements_met: string[];
  requirements_missing: string[];
  errors?: string[];
  safety_notice: string;
}

export interface FactoryPerformanceSummaryWidget {
  profile_score: number;
  catalog_score?: number;
  certificate_score?: number;
  export_market_score?: number;
  media_score?: number;
  total_buyers: number;
  active_opportunities: number;
  marketplace_visibility: number;
  buyer_acquisition_score: number;
  verification_status: "unverified" | "pending" | "verified";
  company_name?: string | null;
  missing_items?: string[];
  top_recommended_action?: string | null;
  errors?: string[];
  safety_notice: string;
}

export interface FactoryReadinessIndicators {
  profile_score: number;
  components: FactoryProfileScoreComponents;
  verification_status: "unverified" | "pending" | "verified";
  indicators: {
    label: string;
    score: number;
    max: number;
    status: "ready" | "needs_work";
  }[];
  missing_items: string[];
  safety_notice: string;
}

export interface FactorySnapshot {
  company_name: string;
  brand_name?: string | null;
  profile_score: number;
  components: FactoryProfileScoreComponents;
  verification_status: "unverified" | "pending" | "verified";
  total_buyers: number;
  active_opportunities: number;
  safety_notice: string;
}

// ─── Customer Portal v2 ────────────────────────────────────────────────────────

export interface CustomerPortalV2TenantRef {
  tenant_id: string;
  company_id: string;
  company_name: string;
  tenant_status: string;
}

export interface CustomerPortalV2RevenueSummary {
  total_revenue: number | string;
  deals_won: number;
  avg_deal_size: number | string;
  conversion_rate: number;
  currency: string;
}

export interface CustomerPortalV2Dashboard {
  tenant: CustomerPortalV2TenantRef;
  subscription_status?: string | null;
  current_plan?: string | null;
  active_buyers: number;
  active_opportunities: number;
  open_deals: number;
  proposals: number;
  revenue_summary: CustomerPortalV2RevenueSummary;
  profile_completeness: number;
  errors?: string[];
  safety_notice: string;
}

export interface CustomerPortalV2OpportunityItem {
  opportunity_id: string;
  title: string;
  source: "buyer_acquisition" | "marketplace" | "buyer_network";
  buyer_company?: string | null;
  opportunity_score: number;
  country?: string | null;
  industry?: string | null;
  recommended_action: string;
}

export interface CustomerPortalV2Opportunities {
  tenant: CustomerPortalV2TenantRef;
  buyer_acquisition: CustomerPortalV2OpportunityItem[];
  marketplace: CustomerPortalV2OpportunityItem[];
  buyer_network: CustomerPortalV2OpportunityItem[];
  total: number;
  errors?: string[];
  safety_notice: string;
}

export interface CustomerPortalV2DealItem {
  deal_id: string;
  deal_name: string;
  buyer?: string | null;
  stage: string;
  risk_level: string;
  close_probability: number;
  estimated_value: number | string;
  currency: string;
}

export interface CustomerPortalV2ProposalItem {
  proposal_id: string;
  proposal_title: string;
  buyer?: string | null;
  status: string;
  estimated_value: number | string;
  last_updated: string;
}

export interface CustomerPortalV2Reports {
  tenant: CustomerPortalV2TenantRef;
  revenue_forecast: {
    period?: string | null;
    best_case: number | string;
    expected_case: number | string;
    worst_case: number | string;
    currency: string;
  }[];
  forecast_confidence: string;
  revenue_attribution: CustomerPortalV2RevenueSummary;
  buyer_performance: {
    buyer_id?: string | null;
    name: string;
    buyer_score: number;
    classification?: string | null;
    annual_potential: number | string;
  }[];
  marketplace_performance: {
    open_opportunities: number;
    total_opportunities: number;
    visibility_score: number;
  };
  errors?: string[];
  safety_notice: string;
}

export interface CustomerPortalV2Billing {
  tenant: CustomerPortalV2TenantRef;
  current_plan?: string | null;
  subscription_status?: string | null;
  usage_summary: Record<string, unknown>;
  invoice_summary: {
    invoice_id: string;
    invoice_number?: string | null;
    status: string;
    amount: number | string;
    currency: string;
    invoice_date?: string | null;
  }[];
  monthly_price: number;
  next_renewal?: string | null;
  errors?: string[];
  safety_notice: string;
}

export interface CustomerPortalV2FactorySnapshot {
  tenant: CustomerPortalV2TenantRef;
  company_profile: Record<string, unknown>;
  products_count: number;
  certificates_count: number;
  export_markets: {
    country: string;
    market_score: number;
    active_buyers: number;
    opportunities: number;
  }[];
  verification_status: string;
  profile_score: number;
  errors?: string[];
  safety_notice: string;
}

export interface CustomerPortalV2SummaryWidget {
  active_buyers: number;
  open_deals: number;
  active_opportunities: number;
  profile_completeness: number;
  subscription_status?: string | null;
  company_name?: string | null;
  errors?: string[];
  safety_notice: string;
}

export interface CustomerPortalV2HealthOverview {
  active_buyers: number;
  open_deals: number;
  active_opportunities: number;
  profile_completeness: number;
  subscription_status?: string | null;
  company_name?: string | null;
  readiness: "healthy" | "moderate" | "needs_attention";
  errors?: string[];
  safety_notice: string;
}

export const customerPortalV2Api = {
  summaryWidget: () =>
    api.get<CustomerPortalV2SummaryWidget>("/customer-portal-v2/summary-widget"),
  dashboard: () => api.get<CustomerPortalV2Dashboard>("/customer-portal-v2/dashboard"),
  opportunities: (params?: { skip?: number; limit?: number }) =>
    api.get<CustomerPortalV2Opportunities>("/customer-portal-v2/opportunities", { params }),
  deals: (params?: { skip?: number; limit?: number }) =>
    api.get<{ tenant: CustomerPortalV2TenantRef; items: CustomerPortalV2DealItem[]; total: number; errors?: string[]; safety_notice: string }>(
      "/customer-portal-v2/deals",
      { params },
    ),
  proposals: (params?: { skip?: number; limit?: number }) =>
    api.get<{ tenant: CustomerPortalV2TenantRef; items: CustomerPortalV2ProposalItem[]; total: number; errors?: string[]; safety_notice: string }>(
      "/customer-portal-v2/proposals",
      { params },
    ),
  reports: () => api.get<CustomerPortalV2Reports>("/customer-portal-v2/reports"),
  billing: () => api.get<CustomerPortalV2Billing>("/customer-portal-v2/billing"),
  factorySnapshot: () =>
    api.get<CustomerPortalV2FactorySnapshot>("/customer-portal-v2/factory-snapshot"),
};

export const customerPortalApi = {
  listAccounts: (params?: { portal_status?: string; skip?: number; limit?: number }) =>
    api.get<{ items: CustomerPortalAccount[]; total: number }>("/customer-portal/accounts", {
      params,
    }),
  summaryWidget: () =>
    api.get<CustomerPortalSummaryWidget>("/customer-portal/summary-widget"),
  dashboard: (portalAccountId: string) =>
    api.get<CustomerPortalDashboard>("/customer-portal/dashboard", {
      params: { portal_account_id: portalAccountId },
    }),
  buyers: (portalAccountId: string, params?: { skip?: number; limit?: number }) =>
    api.get<{ account: CustomerPortalAccount; items: CustomerPortalBuyerItem[]; total: number; errors?: string[] }>(
      "/customer-portal/buyers",
      { params: { portal_account_id: portalAccountId, ...params } },
    ),
  deals: (portalAccountId: string, params?: { skip?: number; limit?: number }) =>
    api.get<{ account: CustomerPortalAccount; items: CustomerPortalDealItem[]; total: number; errors?: string[] }>(
      "/customer-portal/deals",
      { params: { portal_account_id: portalAccountId, ...params } },
    ),
  proposals: (portalAccountId: string, params?: { skip?: number; limit?: number }) =>
    api.get<{ account: CustomerPortalAccount; items: CustomerPortalProposalItem[]; total: number }>(
      "/customer-portal/proposals",
      { params: { portal_account_id: portalAccountId, ...params } },
    ),
  reports: (portalAccountId: string) =>
    api.get<CustomerPortalReports>("/customer-portal/reports", {
      params: { portal_account_id: portalAccountId },
    }),
  billing: (portalAccountId: string) =>
    api.get<{
      account: CustomerPortalAccount;
      billing_summary: SubscriptionBillingSummary;
      safety_notice: string;
      errors?: string[];
    }>("/customer-portal/billing", {
      params: { portal_account_id: portalAccountId },
    }),
  factorySnapshot: () =>
    api.get<FactorySnapshot>("/customer-portal/factory-snapshot"),
};

// ─── Tenant Authentication v1 ────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  tenant_id: string;
  email: string;
  role: TenantUserRole;
  status: TenantUserStatus;
  created_at?: string;
  updated_at?: string;
  last_login_at?: string | null;
  has_password?: boolean;
  permissions?: string[];
}

export interface AuthMeResponse {
  user: AuthUser;
  tenant: {
    id: string;
    company_name: string;
    status: string;
    plan?: string;
  };
  permissions: string[];
  roles_available: TenantUserRole[];
}

export const authApi = {
  login: (body: { email: string; password: string }) =>
    api.post<{
      access_token: string;
      refresh_token: string;
      token_type: string;
      user: AuthUser;
      tenant: { id: string; company_name: string; status: string };
    }>("/auth/login", body),
  logout: () => api.post<{ message: string }>("/auth/logout"),
  me: () => api.get<AuthMeResponse>("/auth/me"),
  refresh: (refresh_token: string) =>
    api.post<{ access_token: string; refresh_token: string; token_type: string }>(
      "/auth/refresh",
      { refresh_token },
    ),
  createDemoUser: () =>
    api.post<{
      message: string;
      email: string;
      password: string;
      tenant_id: string;
      company_name: string;
      user_id: string;
    }>("/auth/create-demo-user"),
};

export const tenantAuthApi = {
  listUsers: (params?: { skip?: number; limit?: number }) =>
    api.get<{
      tenant_id: string;
      items: AuthUser[];
      total: number;
      roles_available: TenantUserRole[];
      role_permissions: Record<string, string[]>;
    }>("/tenant-auth/users", { params }),
  createUser: (body: {
    email: string;
    role?: TenantUserRole;
    password?: string;
    status?: TenantUserStatus;
  }) => api.post<AuthUser>("/tenant-auth/users", body),
  updateUser: (
    id: string,
    body: Partial<{ email: string; role: TenantUserRole; password: string }>,
  ) => api.patch<AuthUser>(`/tenant-auth/users/${id}`, body),
  disableUser: (id: string) => api.post<AuthUser>(`/tenant-auth/users/${id}/disable`),
  enableUser: (id: string) => api.post<AuthUser>(`/tenant-auth/users/${id}/enable`),
};

export function getBackendBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
  return url.replace(/\/api\/v1\/?$/, "");
}

export const publicReviewApi = {
  get: (token: string) =>
    axios.get<PublicReview>(`${getBackendBaseUrl()}/public/review/${token}`),
  approve: (token: string) =>
    axios.post<{ ok: boolean; message: string }>(
      `${getBackendBaseUrl()}/public/review/${token}/approve`,
    ),
  requestChanges: (token: string, feedback: string) =>
    axios.post<{ ok: boolean; message: string }>(
      `${getBackendBaseUrl()}/public/review/${token}/request-changes`,
      { feedback },
    ),
  regenerate: (token: string) =>
    axios.post<{ ok: boolean; message: string }>(
      `${getBackendBaseUrl()}/public/review/${token}/regenerate`,
    ),
};

// ─── Admin Authentication ─────────────────────────────────────────────────────

export type AdminRole = "super_admin" | "platform_admin" | "support_admin" | "auditor";
export type AdminUserStatus = "invited" | "active" | "suspended" | "removed";

export interface AdminUser {
  id: string;
  email: string;
  role: AdminRole;
  status: AdminUserStatus;
  created_at?: string;
  updated_at?: string;
  last_login_at?: string;
  has_password?: boolean;
  permissions?: string[];
}

export interface AdminAuthMeResponse {
  user: AdminUser;
  permissions: string[];
  roles_available: AdminRole[];
  role_permissions: Record<string, string[]>;
}

export interface AdminAuditLog {
  id: string;
  admin_user_id?: string | null;
  admin_email?: string | null;
  event_type: string;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  details?: string | null;
  ip_address?: string | null;
  success: boolean;
  created_at: string;
}

export interface AdminSession {
  id: string;
  admin_user_id: string;
  admin_email: string;
  admin_role: AdminRole;
  login_time: string;
  last_activity: string;
  session_status: string;
  ip_address?: string | null;
  user_agent?: string | null;
}

export const adminAuthApi = {
  login: (body: { email: string; password: string }) =>
    adminApi.post<{
      access_token: string;
      refresh_token: string;
      token_type: string;
      user: AdminUser;
      session_id: string;
    }>("/admin-auth/login", body),
  logout: () => adminApi.post<{ message: string }>("/admin-auth/logout"),
  me: () => adminApi.get<AdminAuthMeResponse>("/admin-auth/me"),
  refresh: (refresh_token: string) =>
    adminApi.post<{ access_token: string; refresh_token: string; token_type: string; session_id: string }>(
      "/admin-auth/refresh",
      { refresh_token },
    ),
  bootstrap: () =>
    adminApi.post<{ message: string; email: string; user_id: string; created: boolean }>(
      "/admin-auth/bootstrap",
    ),
  listUsers: (params?: { skip?: number; limit?: number }) =>
    adminApi.get<{
      items: AdminUser[];
      total: number;
      roles_available: AdminRole[];
      role_permissions: Record<string, string[]>;
    }>("/admin-auth/users", { params }),
  createUser: (body: {
    email: string;
    role?: AdminRole;
    password?: string;
    status?: AdminUserStatus;
  }) => adminApi.post<AdminUser>("/admin-auth/users", body),
  updateUser: (
    id: string,
    body: Partial<{ email: string; role: AdminRole; password: string; status: AdminUserStatus }>,
  ) => adminApi.patch<AdminUser>(`/admin-auth/users/${id}`, body),
  listRoles: () =>
    adminApi.get<{ roles: AdminRole[]; role_permissions: Record<string, string[]> }>(
      "/admin-auth/roles",
    ),
  listPermissions: () =>
    adminApi.get<{ permissions: string[]; role_permissions: Record<string, string[]> }>(
      "/admin-auth/permissions",
    ),
  listAuditLogs: (params?: { skip?: number; limit?: number; event_type?: string }) =>
    adminApi.get<{ items: AdminAuditLog[]; total: number }>("/admin-auth/audit-logs", { params }),
  listSessions: (params?: { skip?: number; limit?: number; status?: string }) =>
    adminApi.get<{ items: AdminSession[]; total: number }>("/admin-auth/sessions", { params }),
  platformTenants: (params?: { skip?: number; limit?: number }) =>
    adminApi.get<{ items: Array<{ id: string; company_name: string; status: string; plan: string; created_at?: string }>; total: number }>(
      "/admin-auth/platform/tenants",
      { params },
    ),
  platformBilling: () =>
    adminApi.get<{
      total_tenants: number;
      active_subscriptions: number;
      trial_subscriptions: number;
      plans: SubscriptionPlan[];
    }>("/admin-auth/platform/billing"),
  platformSubscriptions: (params?: { skip?: number; limit?: number }) =>
    adminApi.get<{ items: SubscriptionRecord[]; total: number }>(
      "/admin-auth/platform/subscriptions",
      { params },
    ),
  platformAnalytics: () =>
    adminApi.get<{
      total_tenants: number;
      active_tenants: number;
      total_clients: number;
      total_leads: number;
      total_deals: number;
      executive_copilot_available: boolean;
    }>("/admin-auth/platform/analytics"),
  securityChecks: () =>
    adminApi.get<{
      checks: Array<{ name: string; status: string; message: string }>;
      ok_count: number;
      total: number;
    }>("/admin-auth/security-checks"),
};

// ─── Factory Tenant Onboarding ───────────────────────────────────────────────

export interface OnboardingStepItem {
  id: string;
  label: string;
  completed: boolean;
  completed_at?: string | null;
  route: string;
  estimated_minutes: number;
}

export interface OnboardingMilestoneMessage {
  step_id: string;
  message: string;
  shown_at: string;
}

export interface OnboardingDashboard {
  tenant_id: string;
  status: "not_started" | "in_progress" | "completed";
  progress_percent: number;
  completed_steps: number;
  total_steps: number;
  remaining_steps: number;
  estimated_minutes_remaining: number;
  steps: OnboardingStepItem[];
  next_step?: OnboardingStepItem | null;
  demo_data_generated: boolean;
  new_milestones: OnboardingMilestoneMessage[];
  started_at?: string | null;
  completed_at?: string | null;
}

export interface OnboardingCompanyProfile {
  company_name: string;
  industry?: string | null;
  country?: string | null;
  city?: string | null;
  website?: string | null;
  contact_person?: string | null;
  email?: string | null;
  phone?: string | null;
  preferred_languages?: string[];
}

export interface OnboardingChannelStatus {
  telegram: Record<string, unknown>;
  wechat: Record<string, unknown>;
  whatsapp: Record<string, unknown>;
}

export interface OnboardingAssistantResponse {
  reply: string;
  suggested_route?: string | null;
  source: string;
}

export interface OnboardingAdminTenantItem {
  tenant_id: string;
  company_name: string;
  status: string;
  progress_percent: number;
  completed_steps: number;
  total_steps: number;
  demo_data_generated: boolean;
  started_at?: string | null;
  completed_at?: string | null;
  time_to_first_content_hours?: number | null;
  time_to_first_lead_hours?: number | null;
  time_to_first_proposal_hours?: number | null;
  time_to_growth_center_hours?: number | null;
  drop_off_step?: string | null;
}

export interface OnboardingAdminAnalytics {
  total_tenants: number;
  started_count: number;
  completed_count: number;
  completion_rate_percent: number;
  demo_data_usage_count: number;
  avg_time_to_first_content_hours?: number | null;
  avg_time_to_first_lead_hours?: number | null;
  avg_time_to_first_proposal_hours?: number | null;
  avg_time_to_growth_center_hours?: number | null;
  drop_off_by_step: Record<string, number>;
  tenants: OnboardingAdminTenantItem[];
}

export const tenantOnboardingApi = {
  dashboard: () => api.get<OnboardingDashboard>("/onboarding/dashboard"),
  refresh: () => api.post<{ refreshed: boolean; progress: OnboardingDashboard }>("/onboarding/refresh"),
  saveCompany: (data: OnboardingCompanyProfile) =>
    api.post<{ saved: boolean; profile: OnboardingCompanyProfile; progress: OnboardingDashboard }>(
      "/onboarding/company",
      data,
    ),
  channelStatus: () => api.get<OnboardingChannelStatus>("/onboarding/channels/status"),
  generateDemoData: () =>
    api.post<{ generated: boolean; message: string; counts: Record<string, number>; progress: OnboardingDashboard }>(
      "/onboarding/demo-data",
    ),
  recordGrowthCenterVisit: () =>
    api.post<{ recorded: boolean; progress: OnboardingDashboard }>("/onboarding/growth-center/visit"),
  assistantChat: (message: string, context_step?: string) =>
    api.post<OnboardingAssistantResponse>("/onboarding/assistant/chat", {
      message,
      context_step,
    }),
  adminAnalytics: () => adminApi.get<OnboardingAdminAnalytics>("/onboarding/admin/analytics"),
  adminReset: (tenantId: string) =>
    adminApi.post<{ success: boolean; message: string; progress?: OnboardingDashboard }>(
      `/onboarding/admin/tenants/${tenantId}/reset`,
    ),
  adminComplete: (tenantId: string) =>
    adminApi.post<{ success: boolean; message: string; progress?: OnboardingDashboard }>(
      `/onboarding/admin/tenants/${tenantId}/complete`,
    ),
};

// ─── Pre-Launch Platform Ops ─────────────────────────────────────────────────

export type PilotFactoryStatus =
  | "invited"
  | "onboarding"
  | "active"
  | "feedback_phase"
  | "completed";

export interface PilotFactory {
  id: string;
  factory_name: string;
  country: string;
  industry: string;
  pilot_status: PilotFactoryStatus;
  start_date?: string | null;
  end_date?: string | null;
  success_score?: number | null;
  notes?: string | null;
  tenant_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformFeedback {
  id: string;
  tenant_id?: string | null;
  user_id?: string | null;
  feedback_type: string;
  category: string;
  title: string;
  description: string;
  status: string;
  created_at: string;
}

export interface PlatformAuditLog {
  id: string;
  actor_type: string;
  actor_id?: string | null;
  tenant_id?: string | null;
  event_type: string;
  resource_type?: string | null;
  resource_id?: string | null;
  details?: Record<string, unknown> | null;
  created_at: string;
}

export interface PlatformErrorReport {
  id: string;
  source: string;
  tenant_id?: string | null;
  user_id?: string | null;
  path?: string | null;
  message: string;
  stack_trace?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
}

export interface HealthComponent {
  key: string;
  label: string;
  status: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface LaunchReadinessComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  status: string;
  details?: string | null;
}

export const platformOpsApi = {
  listPilotFactories: (params?: { status?: string; skip?: number; limit?: number }) =>
    adminApi.get<{ items: PilotFactory[]; total: number }>("/platform-ops/pilot-program", { params }),
  createPilotFactory: (body: Partial<PilotFactory>) =>
    adminApi.post<PilotFactory>("/platform-ops/pilot-program", body),
  updatePilotFactory: (id: string, body: Partial<PilotFactory>) =>
    adminApi.patch<PilotFactory>(`/platform-ops/pilot-program/${id}`, body),
  deletePilotFactory: (id: string) =>
    adminApi.delete<{ message: string }>(`/platform-ops/pilot-program/${id}`),
  submitFeedback: (body: {
    feedback_type: string;
    category: string;
    title: string;
    description: string;
  }) => api.post<PlatformFeedback>("/platform-ops/feedback", body),
  listFeedback: (params?: {
    category?: string;
    feedback_type?: string;
    status?: string;
    skip?: number;
    limit?: number;
  }) => adminApi.get<{ items: PlatformFeedback[]; total: number }>("/platform-ops/feedback", { params }),
  listMyFeedback: (params?: { skip?: number; limit?: number }) =>
    api.get<{ items: PlatformFeedback[]; total: number }>("/platform-ops/feedback/my", { params }),
  systemHealth: () =>
    adminApi.get<{
      overall_status: string;
      components: HealthComponent[];
      refreshed_at: string;
    }>("/platform-ops/system-health"),
  listAuditLogs: (params?: {
    tenant_id?: string;
    event_type?: string;
    actor_type?: string;
    skip?: number;
    limit?: number;
  }) =>
    adminApi.get<{ items: PlatformAuditLog[]; total: number }>("/platform-ops/audit-logs", { params }),
  listMyAuditLogs: (params?: { skip?: number; limit?: number }) =>
    api.get<{ items: PlatformAuditLog[]; total: number }>("/platform-ops/audit-logs/my", { params }),
  reportError: (body: {
    source: string;
    path?: string;
    message: string;
    stack_trace?: string;
    metadata?: Record<string, unknown>;
  }) => api.post<PlatformErrorReport>("/platform-ops/errors", body),
  listErrors: (params?: { source?: string; tenant_id?: string; skip?: number; limit?: number }) =>
    adminApi.get<{
      items: PlatformErrorReport[];
      total: number;
      in_memory_errors: Array<Record<string, unknown>>;
      categories: Record<string, number>;
    }>("/platform-ops/errors", { params }),
  pilotSuccess: () =>
    adminApi.get<{
      overall_score: number;
      metrics: Array<{ key: string; label: string; value: string | number; status: string }>;
      pilot_factories_active: number;
      pilot_factories_total: number;
      feedback_open_count: number;
      refreshed_at: string;
    }>("/platform-ops/pilot-success"),
  launchReadiness: () =>
    adminApi.get<{
      readiness_score: number;
      pilot_readiness_score: number;
      components: LaunchReadinessComponent[];
      launch_blockers: string[];
      recommendations: string[];
      refreshed_at: string;
    }>("/platform-ops/launch-readiness"),
};
