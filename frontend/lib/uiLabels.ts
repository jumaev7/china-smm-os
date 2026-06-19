import type { BuyerEnginePipelineStatus, RevenueEngineDealStage } from "@/lib/api";

export type TranslateFn = (key: string, params?: Record<string, string | number>) => string;

const BUYER_STAGE_KEYS: Record<BuyerEnginePipelineStatus, string> = {
  new: "buyer.stageNew",
  contacted: "buyer.stageContacted",
  replied: "buyer.stageReplied",
  negotiating: "buyer.stageNegotiating",
  quotation_sent: "buyer.stageQuotationSent",
  sample_sent: "buyer.stageSampleSent",
  won: "buyer.stageWon",
  lost: "buyer.stageLost",
};

const REVENUE_STAGE_KEYS: Record<RevenueEngineDealStage, string> = {
  lead: "revenue.stageLead",
  qualified: "revenue.stageQualified",
  negotiation: "revenue.stageNegotiation",
  quotation: "revenue.stageQuotation",
  sample: "revenue.stageSample",
  contract: "revenue.stageContract",
  won: "revenue.stageWon",
  lost: "revenue.stageLost",
};

export function translateSystemStatus(t: TranslateFn, value: string | null | undefined): string {
  if (!value) return "—";
  const key = `systemStatus.${value.toLowerCase().replace(/[^a-z0-9_]/g, "_")}`;
  const translated = t(key);
  return translated !== key ? translated : value;
}

export function translateHealthStatus(t: TranslateFn, value: string | null | undefined): string {
  if (!value) return "—";
  const key = `systemStatus.health_${value.toLowerCase()}`;
  const translated = t(key);
  return translated !== key ? translated : value;
}

export function buyerPipelineLabel(t: TranslateFn, stage: BuyerEnginePipelineStatus): string {
  return t(BUYER_STAGE_KEYS[stage]);
}

export function buyerPipelineLabels(t: TranslateFn): Record<BuyerEnginePipelineStatus, string> {
  return Object.fromEntries(
    (Object.keys(BUYER_STAGE_KEYS) as BuyerEnginePipelineStatus[]).map((stage) => [
      stage,
      buyerPipelineLabel(t, stage),
    ]),
  ) as Record<BuyerEnginePipelineStatus, string>;
}

export function revenueStageLabel(t: TranslateFn, stage: RevenueEngineDealStage): string {
  return t(REVENUE_STAGE_KEYS[stage]);
}

export function revenueStageLabels(t: TranslateFn): Record<RevenueEngineDealStage, string> {
  return Object.fromEntries(
    (Object.keys(REVENUE_STAGE_KEYS) as RevenueEngineDealStage[]).map((stage) => [
      stage,
      revenueStageLabel(t, stage),
    ]),
  ) as Record<RevenueEngineDealStage, string>;
}
