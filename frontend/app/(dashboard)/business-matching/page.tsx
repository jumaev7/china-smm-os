"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Building2,
  Factory,
  Globe,
  Handshake,
  Lightbulb,
  Target,
  TrendingUp,
} from "lucide-react";
import {
  businessMatchingApi,
  type BusinessMatchingRecommendationPriority,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { DataTable, DataTableBody, DataTableHead, DataTableRow, DataTableTd, DataTableTh } from "@/components/ui/design-system/DataTable";
import { MatchScoreIndicator } from "@/components/business-matching/MatchScoreIndicator";
import { HorizontalBarChart } from "@/components/analytics/SimpleBarChart";

function fmtMoney(value: number | string | null | undefined) {
  if (value == null) return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

const PRIORITY_STYLES: Record<BusinessMatchingRecommendationPriority, string> = {
  urgent: "bg-red-100 text-red-900 border-red-200",
  high: "bg-orange-100 text-orange-900 border-orange-200",
  medium: "bg-sky-100 text-sky-900 border-sky-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

const STATUS_STYLES: Record<string, string> = {
  new: "bg-blue-100 text-blue-900",
  contacted: "bg-indigo-100 text-indigo-900",
  qualified: "bg-violet-100 text-violet-900",
  negotiation: "bg-amber-100 text-amber-900",
  won: "bg-emerald-100 text-emerald-900",
  lost: "bg-gray-100 text-gray-600",
};

function TrendChart({ points, label }: { points: Array<{ period: string; count: number }>; label: string }) {
  const max = Math.max(...points.map((p) => p.count), 1);
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <div className="flex items-end gap-2 h-24">
        {points.map((p) => (
          <div key={p.period} className="flex-1 flex flex-col items-center gap-1 min-w-0">
            <span className="text-[10px] font-semibold text-gray-700 tabular-nums">{p.count}</span>
            <div
              className="w-full rounded-t bg-brand-500/80 min-h-[4px]"
              style={{ height: `${Math.max(8, (p.count / max) * 100)}%` }}
            />
            <span className="text-[9px] text-gray-400 truncate w-full text-center">{p.period.slice(5)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function BusinessMatchingPage() {
  const { t } = useTranslation();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["business-matching", "dashboard"],
    queryFn: () => businessMatchingApi.dashboard().then((r) => r.data),
  });

  if (isLoading) return <LoadingState message={t("businessMatching.loading")} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("businessMatching.error")}
        onRetry={() => refetch()}
      />
    );
  }
  if (!data) return null;

  const { kpis, top_industries, top_countries, matching_opportunities, recommended_buyers, recommended_suppliers, new_opportunities, industry_trends, recommendations } = data;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Handshake size={22} className="text-brand-600" />
            {t("businessMatching.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("businessMatching.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/business-matching/opportunities" className="btn-secondary text-sm">
            {t("businessMatching.viewOpportunities")}
          </Link>
          <Link href="/business-matching/buyers" className="btn-secondary text-sm">
            {t("businessMatching.viewBuyers")}
          </Link>
          <Link href="/business-matching/suppliers" className="btn-secondary text-sm">
            {t("businessMatching.viewSuppliers")}
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
        <KpiCard label={t("businessMatching.totalOpportunities")} value={kpis.total_opportunities} icon={Target} />
        <KpiCard label={t("businessMatching.highValue")} value={kpis.high_value_opportunities} icon={TrendingUp} />
        <KpiCard label={t("businessMatching.activeMatches")} value={kpis.active_matches} icon={Handshake} />
        <KpiCard label={t("businessMatching.pipelineValue")} value={fmtMoney(kpis.estimated_pipeline_value)} icon={Building2} />
        <KpiCard label={t("businessMatching.avgMatchScore")} value={`${kpis.average_match_score}%`} icon={Globe} />
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card-premium p-4 lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-navy-900">{t("businessMatching.matchingOpportunities")}</h2>
            <Link href="/business-matching/opportunities" className="text-xs text-brand-600 hover:underline flex items-center gap-1">
              {t("common.viewAll")} <ArrowRight size={12} />
            </Link>
          </div>
          {matching_opportunities.length === 0 ? (
            <EmptyState title={t("businessMatching.noOpportunities")} />
          ) : (
            <DataTable>
              <DataTableHead>
                <DataTableRow>
                  <DataTableTh>{t("businessMatching.colTitle")}</DataTableTh>
                  <DataTableTh>{t("businessMatching.colScore")}</DataTableTh>
                  <DataTableTh>{t("businessMatching.colValue")}</DataTableTh>
                  <DataTableTh>{t("businessMatching.colStatus")}</DataTableTh>
                </DataTableRow>
              </DataTableHead>
              <DataTableBody>
                {matching_opportunities.slice(0, 6).map((o) => (
                  <DataTableRow key={o.id}>
                    <DataTableTd>
                      <div>
                        <p className="font-medium text-sm">{o.title}</p>
                        <p className="text-xs text-gray-500">{o.buyer_company || o.country || "—"}</p>
                      </div>
                    </DataTableTd>
                    <DataTableTd><MatchScoreIndicator score={o.score} size="sm" /></DataTableTd>
                    <DataTableTd className="tabular-nums text-sm">{fmtMoney(o.estimated_value)}</DataTableTd>
                    <DataTableTd>
                      <span className={cn("text-xs px-2 py-0.5 rounded-full capitalize", STATUS_STYLES[o.status] || "bg-gray-100")}>
                        {o.status}
                      </span>
                    </DataTableTd>
                  </DataTableRow>
                ))}
              </DataTableBody>
            </DataTable>
          )}
        </div>

        <div className="card-premium p-4 space-y-4">
          <h2 className="text-sm font-semibold text-navy-900 flex items-center gap-2">
            <Lightbulb size={16} className="text-amber-500" />
            {t("businessMatching.aiRecommendations")}
          </h2>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {recommendations.slice(0, 5).map((r) => (
              <div key={r.id} className="rounded-lg border border-gray-100 p-3 space-y-1">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-navy-900">{r.title}</p>
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded border shrink-0 capitalize", PRIORITY_STYLES[r.priority])}>
                    {r.priority}
                  </span>
                </div>
                <p className="text-xs text-gray-500">{r.reason}</p>
                <p className="text-xs text-brand-700">{r.recommended_action}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card-premium p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-navy-900">{t("businessMatching.recommendedBuyers")}</h2>
            <Link href="/business-matching/buyers" className="text-xs text-brand-600 hover:underline">{t("common.viewAll")}</Link>
          </div>
          <div className="space-y-3">
            {recommended_buyers.slice(0, 4).map((b) => (
              <div key={b.id} className="flex items-center justify-between gap-3 border-b border-gray-50 pb-2 last:border-0">
                <div className="min-w-0">
                  <Link href={`/buyers/${b.id}`} className="text-sm font-medium hover:text-brand-600 truncate block">{b.company_name}</Link>
                  <p className="text-xs text-gray-500">{b.country} · {b.industry || "—"}</p>
                </div>
                <MatchScoreIndicator score={b.match_score} size="sm" className="w-20 shrink-0" />
              </div>
            ))}
          </div>
        </div>

        <div className="card-premium p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-navy-900">{t("businessMatching.recommendedSuppliers")}</h2>
            <Link href="/business-matching/suppliers" className="text-xs text-brand-600 hover:underline">{t("common.viewAll")}</Link>
          </div>
          <div className="space-y-3">
            {recommended_suppliers.slice(0, 4).map((s) => (
              <div key={s.tenant_id} className="flex items-center justify-between gap-3 border-b border-gray-50 pb-2 last:border-0">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate flex items-center gap-1">
                    <Factory size={14} className="text-gray-400 shrink-0" />
                    {s.company_name}
                  </p>
                  <p className="text-xs text-gray-500">{s.country} · {s.industry || "—"}</p>
                </div>
                <MatchScoreIndicator score={s.match_score} size="sm" className="w-20 shrink-0" />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <div className="card-premium p-4">
          <h2 className="text-sm font-semibold text-navy-900 mb-3">{t("businessMatching.newOpportunities")}</h2>
          {new_opportunities.length === 0 ? (
            <p className="text-xs text-gray-500">{t("businessMatching.noNewOpportunities")}</p>
          ) : (
            <ul className="space-y-2">
              {new_opportunities.map((o) => (
                <li key={o.id} className="text-sm border-l-2 border-brand-400 pl-3">
                  <p className="font-medium">{o.title}</p>
                  <p className="text-xs text-gray-500">{fmtMoney(o.estimated_value)} · {o.score}% match</p>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card-premium p-4">
          <h2 className="text-sm font-semibold text-navy-900 mb-3">{t("businessMatching.topIndustries")}</h2>
          <HorizontalBarChart
            data={top_industries.slice(0, 6).map((i) => ({ label: i.label, value: i.count }))}
          />
        </div>

        <div className="card-premium p-4">
          <TrendChart points={industry_trends} label={t("businessMatching.industryTrends")} />
        </div>
      </div>

      <div className="card-premium p-4">
        <h2 className="text-sm font-semibold text-navy-900 mb-3">{t("businessMatching.topCountries")}</h2>
        <div className="flex flex-wrap gap-2">
          {top_countries.map((c) => (
            <span key={c.label} className="inline-flex items-center gap-1.5 rounded-full bg-gray-50 border border-gray-100 px-3 py-1 text-sm">
              <Globe size={12} className="text-gray-400" />
              {c.label}
              <span className="text-xs text-gray-400 tabular-nums">({c.count})</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
