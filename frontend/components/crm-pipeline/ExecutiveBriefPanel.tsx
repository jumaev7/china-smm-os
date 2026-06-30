"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Lightbulb,
  Sparkles,
  Target,
} from "lucide-react";
import { useState } from "react";
import type { CrmPipelineIntelligenceRecommendation, CrmPipelineMorningBrief } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-800 dark-tenant:bg-red-500/15 dark-tenant:text-red-300",
  high: "bg-orange-100 text-orange-800 dark-tenant:bg-orange-500/15 dark-tenant:text-orange-300",
  medium: "bg-amber-100 text-amber-800 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300",
  low: "bg-blue-100 text-blue-800 dark-tenant:bg-blue-500/15 dark-tenant:text-blue-300",
};

function RecommendationRow({
  rec,
  t,
}: {
  rec: CrmPipelineIntelligenceRecommendation;
  t: (k: string, p?: Record<string, string | number>) => string;
}) {
  const subject = rec.deal_title || rec.customer_name || rec.lead_name || rec.proposal_title || "—";
  return (
    <li className="flex gap-3 py-2.5 border-b border-gray-50 last:border-0 dark-tenant:border-white/[0.04]">
      <span
        className={cn(
          "shrink-0 self-start text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded",
          SEVERITY_STYLES[rec.severity] ?? SEVERITY_STYLES.medium,
        )}
      >
        {rec.severity}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-gray-900 dark-tenant:text-slate-100 truncate">
            {subject}
          </span>
          <span className="text-[10px] text-gray-400 dark-tenant:text-slate-500">
            {rec.category_label}
          </span>
          <span className="text-[10px] text-gray-400 dark-tenant:text-slate-500 tabular-nums">
            {rec.confidence}% {t("crmPipeline.executiveBrief.confidence")}
          </span>
        </div>
        <p className="text-xs text-gray-600 dark-tenant:text-slate-400 leading-relaxed">
          {rec.business_reason}
        </p>
        <p className="text-xs text-indigo-600 dark-tenant:text-indigo-400">
          → {rec.recommended_action}
        </p>
      </div>
    </li>
  );
}

function BriefSection({
  title,
  icon: Icon,
  items,
  t,
  defaultOpen = true,
}: {
  title: string;
  icon: React.ElementType;
  items: CrmPipelineIntelligenceRecommendation[];
  t: (k: string, p?: Record<string, string | number>) => string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (items.length === 0) return null;
  return (
    <div className="border-t border-gray-100 dark-tenant:border-white/[0.06] first:border-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-gray-50/80 dark-tenant:hover:bg-white/[0.02] transition-colors"
      >
        <span className="flex items-center gap-2 text-xs font-semibold text-gray-700 dark-tenant:text-slate-300">
          <Icon size={13} className="text-indigo-500" />
          {title}
          <span className="font-normal text-gray-400">({items.length})</span>
        </span>
        {open ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
      </button>
      {open && (
        <ul className="px-4 pb-2">
          {items.map((rec) => (
            <RecommendationRow key={`${rec.rule_id}-${rec.deal_id ?? rec.lead_id ?? rec.proposal_id ?? rec.owner_id}`} rec={rec} t={t} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function ExecutiveBriefPanel({
  brief,
  isLoading,
  className,
}: {
  brief: CrmPipelineMorningBrief | undefined;
  isLoading?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <div
        className={cn(
          "rounded-xl border border-gray-200 bg-white p-6 animate-pulse",
          "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card",
          className,
        )}
      >
        <div className="h-4 bg-gray-200 dark-tenant:bg-white/10 rounded w-48 mb-4" />
        <div className="space-y-2">
          <div className="h-3 bg-gray-100 dark-tenant:bg-white/5 rounded w-full" />
          <div className="h-3 bg-gray-100 dark-tenant:bg-white/5 rounded w-3/4" />
        </div>
      </div>
    );
  }

  if (!brief) return null;

  const health = brief.pipeline_health;
  const topRecs = brief.all_recommendations.slice(0, 8);

  return (
    <div
      className={cn(
        "rounded-xl border border-gray-200 bg-white overflow-hidden",
        "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card",
        className,
      )}
    >
      <div className="px-4 py-3 border-b border-gray-100 dark-tenant:border-white/[0.06] flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-indigo-500" />
          <div>
            <h2 className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100">
              {t("crmPipeline.executiveBrief.title")}
            </h2>
            <p className="text-[11px] text-gray-500 dark-tenant:text-slate-500">
              {t("crmPipeline.executiveBrief.subtitle")}
            </p>
          </div>
        </div>
        <span className="text-[10px] text-gray-400 dark-tenant:text-slate-500 shrink-0">
          {t("crmPipeline.executiveBrief.ruleEngine")}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-gray-100 dark-tenant:bg-white/[0.06]">
        {[
          { label: t("crmPipeline.executiveBrief.pipelineValue"), value: `$${Number(health.pipeline_value).toLocaleString()}` },
          { label: t("crmPipeline.executiveBrief.weightedRevenue"), value: `$${Number(health.weighted_expected_revenue).toLocaleString()}` },
          { label: t("crmPipeline.executiveBrief.openDeals"), value: String(health.open_deals_count) },
          { label: t("crmPipeline.executiveBrief.alerts"), value: String(brief.all_recommendations.length) },
        ].map((kpi) => (
          <div key={kpi.label} className="bg-white dark-tenant:bg-surface-dark-card px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-wide text-gray-500 dark-tenant:text-slate-500">{kpi.label}</div>
            <div className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100 tabular-nums">{kpi.value}</div>
          </div>
        ))}
      </div>

      {topRecs.length > 0 ? (
        <ul className="px-4 py-2 divide-y divide-gray-50 dark-tenant:divide-white/[0.04]">
          {topRecs.map((rec) => (
            <RecommendationRow key={`top-${rec.rule_id}-${rec.deal_id ?? rec.lead_id ?? rec.proposal_id ?? rec.owner_id}`} rec={rec} t={t} />
          ))}
        </ul>
      ) : (
        <p className="px-4 py-6 text-sm text-gray-500 dark-tenant:text-slate-400 text-center">
          {t("crmPipeline.executiveBrief.noAlerts")}
        </p>
      )}

      <BriefSection
        title={t("crmPipeline.executiveBrief.priorities")}
        icon={Target}
        items={brief.todays_priorities}
        t={t}
        defaultOpen={false}
      />
      <BriefSection
        title={t("crmPipeline.executiveBrief.risks")}
        icon={AlertTriangle}
        items={brief.top_risks}
        t={t}
        defaultOpen={false}
      />
      <BriefSection
        title={t("crmPipeline.executiveBrief.opportunities")}
        icon={Lightbulb}
        items={brief.top_opportunities}
        t={t}
        defaultOpen={false}
      />
    </div>
  );
}
