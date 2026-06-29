"use client";

import type { SalesDeal, SalesDealStage } from "@/lib/api";
import { CRM_PIPELINE_STAGE_COLORS } from "@/lib/crm-pipeline";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { DealCard } from "./DealCard";

function stageLabel(stage: SalesDealStage, t: (k: string) => string) {
  const key = `salesCrm.stage.${stage}`;
  const translated = t(key);
  return translated === key ? stage.replace(/_/g, " ") : translated;
}

export function PipelineColumn({
  stage,
  deals,
  metaByCustomer,
  dragOver,
  draggingDealId,
  onDealClick,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  stage: SalesDealStage;
  deals: SalesDeal[];
  metaByCustomer: Map<string, boolean>;
  dragOver: boolean;
  draggingDealId: string | null;
  onDealClick: (deal: SalesDeal) => void;
  onDragStart: (deal: SalesDeal, e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}) {
  const { t } = useTranslation();

  return (
    <div
      className={cn(
        "min-w-[240px] w-[240px] shrink-0 rounded-xl border p-3 flex flex-col max-h-[calc(100vh-320px)]",
        CRM_PIPELINE_STAGE_COLORS[stage],
        dragOver && "ring-2 ring-violet-500/50 border-violet-500/40",
      )}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <div className="flex items-center justify-between mb-3 shrink-0">
        <h3 className="text-xs font-semibold text-gray-800 dark-tenant:text-slate-200 leading-tight">
          {stageLabel(stage, t)}
        </h3>
        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-white/70 text-gray-600 dark-tenant:bg-white/[0.08] dark-tenant:text-slate-400 tabular-nums">
          {deals.length}
        </span>
      </div>
      <div className="space-y-2 overflow-y-auto flex-1 min-h-[120px] pr-0.5">
        {deals.map((deal) => (
          <DealCard
            key={deal.id}
            deal={deal}
            metaConnected={deal.customer_id ? metaByCustomer.get(deal.customer_id) === true : false}
            onClick={() => onDealClick(deal)}
            onDragStart={(e) => onDragStart(deal, e)}
            dragging={draggingDealId === deal.id}
          />
        ))}
      </div>
    </div>
  );
}
