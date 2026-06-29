"use client";

import { format, parseISO } from "date-fns";
import { AlertCircle, Facebook, GripVertical } from "lucide-react";
import type { SalesDeal } from "@/lib/api";
import {
  crmPipelineCompanyName,
  crmPipelineFmtMoney,
  crmPipelineIsStale,
  crmPipelinePublishingStatus,
} from "@/lib/crm-pipeline";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

export function DealCard({
  deal,
  metaConnected,
  onClick,
  onDragStart,
  dragging,
}: {
  deal: SalesDeal;
  metaConnected: boolean;
  onClick: () => void;
  onDragStart: (e: React.DragEvent) => void;
  dragging?: boolean;
}) {
  const { t } = useTranslation();
  const stale = crmPipelineIsStale(deal);
  const publishing = crmPipelinePublishingStatus(deal.stage);

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onClick={onClick}
      className={cn(
        "group rounded-xl border border-gray-200 bg-white p-3 shadow-sm cursor-grab active:cursor-grabbing",
        "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card dark-tenant:shadow-dark-card",
        "transition-all hover:border-violet-500/30 hover:shadow-md dark-tenant:hover:shadow-glow",
        dragging && "opacity-50 ring-2 ring-violet-500/40",
      )}
    >
      <div className="flex items-start gap-2">
        <GripVertical
          size={14}
          className="shrink-0 mt-0.5 text-gray-300 dark-tenant:text-slate-600 group-hover:text-gray-400"
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100 line-clamp-2 leading-snug">
              {crmPipelineCompanyName(deal)}
            </p>
            {stale && (
              <span
                className="shrink-0 inline-flex items-center gap-0.5 text-[10px] font-medium text-amber-600 dark-tenant:text-amber-400"
                title={t("crmPipeline.staleHint")}
              >
                <AlertCircle size={11} />
                {t("crmPipeline.stale")}
              </span>
            )}
          </div>

          <p className="text-[11px] text-gray-500 dark-tenant:text-slate-500 truncate">
            {deal.owner_email || t("crmPipeline.unassigned")}
          </p>

          <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100 tabular-nums">
            {crmPipelineFmtMoney(deal.value, deal.currency)}
          </p>

          <div className="flex items-center justify-between text-[10px] text-gray-500 dark-tenant:text-slate-500">
            <span>{deal.probability}%</span>
            {deal.expected_close_date && (
              <span className="truncate ml-2">
                {format(parseISO(deal.expected_close_date), "MMM d, yyyy")}
              </span>
            )}
          </div>

          <div className="flex flex-wrap gap-1 pt-1">
            {publishing !== "none" && (
              <span
                className={cn(
                  "text-[9px] px-1.5 py-0.5 rounded-md font-medium capitalize",
                  publishing === "publishing" &&
                    "bg-teal-500/15 text-teal-700 dark-tenant:text-teal-400",
                  publishing === "client" &&
                    "bg-emerald-500/15 text-emerald-700 dark-tenant:text-emerald-400",
                  publishing === "expansion" &&
                    "bg-lime-500/15 text-lime-700 dark-tenant:text-lime-400",
                )}
              >
                {t(`crmPipeline.publishing.${publishing}`)}
              </span>
            )}
            {metaConnected && (
              <span className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-md bg-blue-500/15 text-blue-700 dark-tenant:text-blue-400 font-medium">
                <Facebook size={9} />
                {t("crmPipeline.metaConnected")}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
