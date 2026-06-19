"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Filter, Handshake } from "lucide-react";
import {
  businessMatchingApi,
  type BusinessMatchingOpportunityStatus,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { DataTable, DataTableBody, DataTableHead, DataTableRow, DataTableTd, DataTableTh } from "@/components/ui/design-system/DataTable";
import { MatchScoreIndicator } from "@/components/business-matching/MatchScoreIndicator";

const STATUSES: BusinessMatchingOpportunityStatus[] = [
  "new", "contacted", "qualified", "negotiation", "won", "lost",
];

function fmtMoney(value: number | string | null | undefined) {
  if (value == null) return "—";
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

const STATUS_STYLES: Record<string, string> = {
  new: "bg-blue-100 text-blue-900",
  contacted: "bg-indigo-100 text-indigo-900",
  qualified: "bg-violet-100 text-violet-900",
  negotiation: "bg-amber-100 text-amber-900",
  won: "bg-emerald-100 text-emerald-900",
  lost: "bg-gray-100 text-gray-600",
};

export default function BusinessMatchingOpportunitiesPage() {
  const { t } = useTranslation();
  const [country, setCountry] = useState("");
  const [industry, setIndustry] = useState("");
  const [productCategory, setProductCategory] = useState("");
  const [minScore, setMinScore] = useState("");
  const [status, setStatus] = useState<BusinessMatchingOpportunityStatus | "">("");

  const params = useMemo(() => ({
    country: country || undefined,
    industry: industry || undefined,
    product_category: productCategory || undefined,
    min_score: minScore ? parseInt(minScore, 10) : undefined,
    status: status || undefined,
  }), [country, industry, productCategory, minScore, status]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["business-matching", "opportunities", params],
    queryFn: () => businessMatchingApi.opportunities(params).then((r) => r.data),
  });

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/business-matching" className="text-gray-500 hover:text-brand-600">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Handshake size={20} className="text-brand-600" />
            {t("businessMatching.opportunitiesTitle")}
          </h1>
          <p className="text-sm text-gray-500">{t("businessMatching.opportunitiesSubtitle")}</p>
        </div>
      </div>

      <div className="card-premium p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter size={16} className="text-gray-400" />
          <span className="text-sm font-medium">{t("businessMatching.filters")}</span>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <input
            className="input-field text-sm"
            placeholder={t("businessMatching.filterCountry")}
            value={country}
            onChange={(e) => setCountry(e.target.value)}
          />
          <input
            className="input-field text-sm"
            placeholder={t("businessMatching.filterIndustry")}
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
          />
          <input
            className="input-field text-sm"
            placeholder={t("businessMatching.filterCategory")}
            value={productCategory}
            onChange={(e) => setProductCategory(e.target.value)}
          />
          <input
            className="input-field text-sm"
            type="number"
            min={0}
            max={100}
            placeholder={t("businessMatching.filterMinScore")}
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
          />
          <select
            className="input-field text-sm"
            value={status}
            onChange={(e) => setStatus(e.target.value as BusinessMatchingOpportunityStatus | "")}
          >
            <option value="">{t("businessMatching.filterStatus")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading && <LoadingState message={t("businessMatching.loading")} />}
      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : t("businessMatching.error")}
          onRetry={() => refetch()}
        />
      )}
      {data && (
        <>
          <p className="text-sm text-gray-500">{data.total} {t("businessMatching.results")}</p>
          {data.items.length === 0 ? (
            <EmptyState title={t("businessMatching.noOpportunities")} />
          ) : (
            <div className="card-premium overflow-hidden">
              <DataTable>
                <DataTableHead>
                  <DataTableRow>
                    <DataTableTh>{t("businessMatching.colTitle")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colBuyer")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colCountry")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colIndustry")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colScore")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colValue")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colStatus")}</DataTableTh>
                  </DataTableRow>
                </DataTableHead>
                <DataTableBody>
                  {data.items.map((o) => (
                    <DataTableRow key={o.id}>
                      <DataTableTd>
                        <div>
                          <p className="font-medium text-sm">{o.title}</p>
                          <p className="text-xs text-gray-400 capitalize">{o.opportunity_type}</p>
                        </div>
                      </DataTableTd>
                      <DataTableTd className="text-sm">{o.buyer_company || "—"}</DataTableTd>
                      <DataTableTd className="text-sm">{o.country || "—"}</DataTableTd>
                      <DataTableTd className="text-sm">{o.industry || "—"}</DataTableTd>
                      <DataTableTd>
                        <MatchScoreIndicator score={o.score} confidence={o.confidence_score} size="sm" showConfidence />
                      </DataTableTd>
                      <DataTableTd className="tabular-nums text-sm">{fmtMoney(o.estimated_value)}</DataTableTd>
                      <DataTableTd>
                        <span className={cn("text-xs px-2 py-0.5 rounded-full capitalize", STATUS_STYLES[o.status])}>
                          {o.status}
                        </span>
                      </DataTableTd>
                    </DataTableRow>
                  ))}
                </DataTableBody>
              </DataTable>
            </div>
          )}
        </>
      )}
    </div>
  );
}
