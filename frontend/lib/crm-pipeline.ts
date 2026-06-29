import type { SalesDeal, SalesDealStage } from "@/lib/api";

export const CRM_PIPELINE_STALE_DAYS = 14;

export const CRM_PIPELINE_STAGE_TRANSITIONS: Record<SalesDealStage, SalesDealStage[]> = {
  lead: ["qualified", "contacted", "meeting_scheduled", "proposal_sent", "negotiation", "closed_lost"],
  qualified: ["contacted", "meeting_scheduled", "proposal_sent", "negotiation", "closed_lost"],
  contacted: ["meeting_scheduled", "proposal_sent", "negotiation", "contract_pending", "closed_lost"],
  meeting_scheduled: ["proposal_sent", "negotiation", "contract_pending", "closed_lost"],
  proposal_sent: ["negotiation", "contract_pending", "client_active", "closed_won", "closed_lost"],
  negotiation: ["contract_pending", "client_active", "closed_won", "closed_lost"],
  contract_pending: ["client_active", "closed_won", "closed_lost"],
  client_active: ["publishing_active", "expansion_upsell", "closed_won", "closed_lost"],
  publishing_active: ["expansion_upsell", "closed_won", "closed_lost"],
  expansion_upsell: ["closed_won", "closed_lost", "publishing_active"],
  closed_won: [],
  closed_lost: ["lead", "qualified", "contacted"],
};

export const CRM_TERMINAL_STAGES = new Set<SalesDealStage>(["closed_won", "closed_lost"]);

export const CRM_PUBLISHING_STAGES = new Set<SalesDealStage>([
  "client_active",
  "publishing_active",
  "expansion_upsell",
]);

export const CRM_PIPELINE_STAGE_COLORS: Record<SalesDealStage, string> = {
  lead: "border-sky-500/20 bg-sky-500/[0.06]",
  qualified: "border-cyan-500/20 bg-cyan-500/[0.06]",
  contacted: "border-indigo-500/20 bg-indigo-500/[0.06]",
  meeting_scheduled: "border-violet-500/20 bg-violet-500/[0.06]",
  proposal_sent: "border-purple-500/20 bg-purple-500/[0.06]",
  negotiation: "border-fuchsia-500/20 bg-fuchsia-500/[0.06]",
  contract_pending: "border-amber-500/20 bg-amber-500/[0.06]",
  client_active: "border-emerald-500/20 bg-emerald-500/[0.06]",
  publishing_active: "border-teal-500/20 bg-teal-500/[0.06]",
  expansion_upsell: "border-lime-500/20 bg-lime-500/[0.06]",
  closed_won: "border-emerald-500/30 bg-emerald-500/[0.1]",
  closed_lost: "border-slate-500/20 bg-slate-500/[0.06]",
};

export function crmPipelineFmtMoney(value: number | null | undefined, currency = "USD") {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function crmPipelineIsStale(deal: SalesDeal, now = Date.now()): boolean {
  if (CRM_TERMINAL_STAGES.has(deal.stage)) return false;
  const updated = new Date(deal.updated_at || deal.created_at).getTime();
  const cutoff = now - CRM_PIPELINE_STALE_DAYS * 24 * 60 * 60 * 1000;
  return updated <= cutoff;
}

export function crmPipelineCanTransition(from: SalesDealStage, to: SalesDealStage): boolean {
  if (from === to) return true;
  return CRM_PIPELINE_STAGE_TRANSITIONS[from]?.includes(to) ?? false;
}

export type CrmPublishingStatus = "none" | "client" | "publishing" | "expansion";

export function crmPipelinePublishingStatus(stage: SalesDealStage): CrmPublishingStatus {
  if (stage === "publishing_active") return "publishing";
  if (stage === "client_active") return "client";
  if (stage === "expansion_upsell") return "expansion";
  return "none";
}

export function crmPipelineCompanyName(deal: SalesDeal): string {
  return deal.customer_name || deal.lead_name || deal.title;
}
