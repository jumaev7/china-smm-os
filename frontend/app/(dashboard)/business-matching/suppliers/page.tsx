"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Factory } from "lucide-react";
import { businessMatchingApi } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { DataTable, DataTableBody, DataTableHead, DataTableRow, DataTableTd, DataTableTh } from "@/components/ui/design-system/DataTable";
import { MatchScoreIndicator } from "@/components/business-matching/MatchScoreIndicator";

export default function BusinessMatchingSuppliersPage() {
  const { t } = useTranslation();
  const [minScore, setMinScore] = useState("0");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["business-matching", "suppliers", minScore],
    queryFn: () =>
      businessMatchingApi.suppliers({ min_score: parseInt(minScore, 10) || 0 }).then((r) => r.data),
  });

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/business-matching" className="text-gray-500 hover:text-brand-600">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Factory size={20} className="text-brand-600" />
            {t("businessMatching.suppliersTitle")}
          </h1>
          <p className="text-sm text-gray-500">{t("businessMatching.suppliersSubtitle")}</p>
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
        <Link href="/factory-platform" className="text-sm text-brand-600 hover:underline ml-auto">
          {t("businessMatching.openFactoryPlatform")}
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
            <EmptyState title={t("businessMatching.noSuppliers")} />
          ) : (
            <div className="card-premium overflow-hidden">
              <DataTable>
                <DataTableHead>
                  <DataTableRow>
                    <DataTableTh>{t("businessMatching.colCompany")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colIndustry")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colCountry")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colCategories")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colCertifications")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colContact")}</DataTableTh>
                    <DataTableTh>{t("businessMatching.colScore")}</DataTableTh>
                  </DataTableRow>
                </DataTableHead>
                <DataTableBody>
                  {data.items.map((s) => (
                    <DataTableRow key={s.tenant_id}>
                      <DataTableTd>
                        <p className="text-sm font-medium flex items-center gap-1">
                          <Factory size={14} className="text-gray-400" />
                          {s.company_name}
                        </p>
                        {s.match_reasoning && (
                          <p className="text-xs text-gray-500 mt-0.5 max-w-xs truncate">{s.match_reasoning}</p>
                        )}
                      </DataTableTd>
                      <DataTableTd className="text-sm">{s.industry || "—"}</DataTableTd>
                      <DataTableTd className="text-sm">{s.country || "—"}</DataTableTd>
                      <DataTableTd className="text-xs text-gray-600 max-w-[140px]">
                        {s.product_categories.slice(0, 3).join(", ") || "—"}
                      </DataTableTd>
                      <DataTableTd className="text-xs text-gray-600 max-w-[120px]">
                        {s.certifications.slice(0, 2).join(", ") || "—"}
                      </DataTableTd>
                      <DataTableTd className="text-xs">
                        {s.contact_email && <p>{s.contact_email}</p>}
                        {s.contact_phone && <p className="text-gray-500">{s.contact_phone}</p>}
                        {!s.contact_email && !s.contact_phone && "—"}
                      </DataTableTd>
                      <DataTableTd>
                        <MatchScoreIndicator score={s.match_score} confidence={s.confidence_score} size="sm" showConfidence />
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
