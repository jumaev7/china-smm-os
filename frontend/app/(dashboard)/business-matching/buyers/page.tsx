"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Building2, Users } from "lucide-react";
import { businessMatchingApi } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { DataTable, DataTableBody, DataTableHead, DataTableRow, DataTableTd, DataTableTh } from "@/components/ui/design-system/DataTable";
import { MatchScoreIndicator } from "@/components/business-matching/MatchScoreIndicator";

const STATUS_STYLES: Record<string, string> = {
  prospect: "bg-gray-100 text-gray-700",
  contacted: "bg-blue-100 text-blue-900",
  interested: "bg-indigo-100 text-indigo-900",
  negotiating: "bg-amber-100 text-amber-900",
  active_buyer: "bg-emerald-100 text-emerald-900",
  inactive: "bg-gray-100 text-gray-500",
};

export default function BusinessMatchingBuyersPage() {
  const { t } = useTranslation();
  const [minScore, setMinScore] = useState("0");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["business-matching", "buyers", minScore],
    queryFn: () =>
      businessMatchingApi.buyers({ min_score: parseInt(minScore, 10) || 0 }).then((r) => r.data),
  });

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/business-matching" className="text-gray-500 hover:text-brand-600">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Users size={20} className="text-brand-600" />
            {t("businessMatching.buyersTitle")}
          </h1>
          <p className="text-sm text-gray-500">{t("businessMatching.buyersSubtitle")}</p>
        </div>
      </div>

      <div className="card-premium p-4 flex flex-wrap items-center gap-3">
        <label className="text-sm text-gray-600">{t("businessMatching.filterMinScore")}</label>
        <input
          className="input-field text-sm w-24"
          type="number"
          min={0}
          max={100}
          value={minScore}
          onChange={(e) => setMinScore(e.target.value)}
        />
        <Link href="/buyers" className="text-sm text-brand-600 hover:underline ml-auto">
          {t("businessMatching.openBuyerNetwork")}
        </Link>
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
            <EmptyState title={t("businessMatching.noBuyers")} />
          ) : (
            <div className="card-premium overflow-hidden">
              <DataTable>
                <DataTableHead>
                  <DataTableRow>
                    <DataTableTh>{t("businessMatching.colCompany")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colCountry")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colIndustry")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colScore")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colStatus")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.recommendedActions")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.similarBuyers")}</DataTableTh>
                  </DataTableRow>
                </DataTableHead>
                <DataTableBody>
                  {data.items.map((b) => (
                    <DataTableRow key={b.id}>
                      <DataTableTd>
                        <Link href={`/buyers/${b.id}`} className="text-sm font-medium hover:text-brand-600 flex items-center gap-1">
                          <Building2 size={14} className="text-gray-400" />
                          {b.company_name}
                        </Link>
                      </DataTableTd>
                      <DataTableTd className="text-sm">{b.country || "—"}</DataTableTd>
                      <DataTableTd className="text-sm">{b.industry || "—"}</DataTableTd>
                      <DataTableTd>
                        <MatchScoreIndicator score={b.match_score} confidence={b.confidence_score} size="sm" showConfidence />
                      </DataTableTd>
                      <DataTableTd>
                        <span className={cn("text-xs px-2 py-0.5 rounded-full", STATUS_STYLES[b.status] || "bg-gray-100")}>
                          {b.status.replace("_", " ")}
                        </span>
                      </DataTableTd>
                      <DataTableTd>
                        <ul className="text-xs text-gray-600 space-y-0.5 max-w-xs">
                          {b.recommended_actions.slice(0, 2).map((a) => (
                            <li key={a}>• {a}</li>
                          ))}
                        </ul>
                      </DataTableTd>
                      <DataTableTd className="text-xs text-gray-500">
                        {b.similar_buyers.length > 0 ? b.similar_buyers.join(", ") : "—"}
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
