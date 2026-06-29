"use client";

import { Filter } from "lucide-react";
import type { SalesDeal, SalesDealStage } from "@/lib/api";
import { SALES_DEAL_STAGES } from "@/lib/api";
import { CRM_PUBLISHING_STAGES, crmPipelineIsStale } from "@/lib/crm-pipeline";
import { useTranslation } from "@/lib/I18nProvider";
import { ActionBar } from "@/components/ui/design-system";

export type CrmPipelineFilters = {
  ownerId: string;
  stage: string;
  staleOnly: boolean;
  publishingOnly: boolean;
};

export const DEFAULT_CRM_PIPELINE_FILTERS: CrmPipelineFilters = {
  ownerId: "",
  stage: "",
  staleOnly: false,
  publishingOnly: false,
};

function stageLabel(stage: SalesDealStage, t: (k: string) => string) {
  const key = `salesCrm.stage.${stage}`;
  const translated = t(key);
  return translated === key ? stage.replace(/_/g, " ") : translated;
}

export function CrmPipelineFilterBar({
  filters,
  onChange,
  owners,
}: {
  filters: CrmPipelineFilters;
  onChange: (next: CrmPipelineFilters) => void;
  owners: Array<{ id: string; email: string }>;
}) {
  const { t } = useTranslation();

  const selectClass =
    "text-xs rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-200";

  return (
    <ActionBar>
      <Filter size={14} className="text-gray-400 dark-tenant:text-slate-500 shrink-0" />
      <label className="flex items-center gap-1.5 text-xs text-gray-600 dark-tenant:text-slate-400">
        <span className="shrink-0">{t("crmPipeline.filter.owner")}</span>
        <select
          value={filters.ownerId}
          onChange={(e) => onChange({ ...filters, ownerId: e.target.value })}
          className={selectClass}
        >
          <option value="">{t("common.all")}</option>
          {owners.map((o) => (
            <option key={o.id} value={o.id}>
              {o.email}
            </option>
          ))}
          <option value="__unassigned__">{t("crmPipeline.unassigned")}</option>
        </select>
      </label>

      <label className="flex items-center gap-1.5 text-xs text-gray-600 dark-tenant:text-slate-400">
        <span className="shrink-0">{t("crmPipeline.filter.stage")}</span>
        <select
          value={filters.stage}
          onChange={(e) => onChange({ ...filters, stage: e.target.value })}
          className={selectClass}
        >
          <option value="">{t("common.all")}</option>
          {SALES_DEAL_STAGES.map((s) => (
            <option key={s} value={s}>
              {stageLabel(s, t)}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1.5 text-xs text-gray-600 dark-tenant:text-slate-400 cursor-pointer">
        <input
          type="checkbox"
          checked={filters.staleOnly}
          onChange={(e) => onChange({ ...filters, staleOnly: e.target.checked })}
          className="rounded border-gray-300 dark-tenant:border-white/20"
        />
        {t("crmPipeline.filter.stale")}
      </label>

      <label className="flex items-center gap-1.5 text-xs text-gray-600 dark-tenant:text-slate-400 cursor-pointer">
        <input
          type="checkbox"
          checked={filters.publishingOnly}
          onChange={(e) => onChange({ ...filters, publishingOnly: e.target.checked })}
          className="rounded border-gray-300 dark-tenant:border-white/20"
        />
        {t("crmPipeline.filter.publishing")}
      </label>
    </ActionBar>
  );
}

export function applyCrmPipelineFilters(
  deals: SalesDeal[],
  filters: CrmPipelineFilters,
): SalesDeal[] {
  return deals.filter((deal) => {
    if (filters.ownerId === "__unassigned__") {
      if (deal.owner_id) return false;
    } else if (filters.ownerId && deal.owner_id !== filters.ownerId) {
      return false;
    }
    if (filters.stage && deal.stage !== filters.stage) return false;
    if (filters.staleOnly && !crmPipelineIsStale(deal)) return false;
    if (filters.publishingOnly && !CRM_PUBLISHING_STAGES.has(deal.stage)) return false;
    return true;
  });
}

export function extractOwnersFromDeals(deals: SalesDeal[]): Array<{ id: string; email: string }> {
  const map = new Map<string, string>();
  for (const deal of deals) {
    if (deal.owner_id && deal.owner_email) {
      map.set(deal.owner_id, deal.owner_email);
    }
  }
  return Array.from(map.entries())
    .map(([id, email]) => ({ id, email }))
    .sort((a, b) => a.email.localeCompare(b.email));
}
