"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Globe, ArrowLeft, ChevronRight, Search } from "lucide-react";
import { exportApi, ExportOpportunity, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

function OpportunityRow({ opp }: { opp: ExportOpportunity }) {
  return (
    <Link
      href={`/export/opportunities/${opp.id}`}
      className="card p-4 flex items-center justify-between gap-3 hover:ring-1 hover:ring-sky-200 transition-shadow"
    >
      <div className="min-w-0">
        <p className="text-sm font-semibold text-gray-900">
          {opp.product_name ?? "Product"} → {opp.country}
        </p>
        <p className="text-xs text-gray-500 mt-0.5">
          {opp.company_name ?? "—"}
          {opp.product_category ? ` · ${opp.product_category}` : ""}
        </p>
        {opp.market_summary && (
          <p className="text-[11px] text-gray-600 mt-1 line-clamp-2">{opp.market_summary}</p>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        {opp.demand_level && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-sky-50 text-sky-800 capitalize border border-sky-100">
            {opp.demand_level.replace("_", " ")}
          </span>
        )}
        <span
          className={cn(
            "text-sm font-semibold tabular-nums px-2 py-0.5 rounded-full",
            opp.score >= 70
              ? "bg-emerald-100 text-emerald-800"
              : opp.score >= 45
                ? "bg-amber-100 text-amber-800"
                : "bg-gray-100 text-gray-600",
          )}
        >
          {Math.round(opp.score)}
        </span>
        <ChevronRight size={16} className="text-gray-400" />
      </div>
    </Link>
  );
}

export default function ExportOpportunitiesPage() {
  const [country, setCountry] = useState("");
  const [search, setSearch] = useState("");

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["export-opportunities", country],
    queryFn: () =>
      exportApi
        .listOpportunities({ country: country || undefined, limit: 200 })
        .then((r) => r.data),
  });

  const allItems = normalizeList<ExportOpportunity>(data);
  const items = allItems.filter((o) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      o.country.toLowerCase().includes(q) ||
      (o.product_name ?? "").toLowerCase().includes(q) ||
      (o.company_name ?? "").toLowerCase().includes(q)
    );
  });

  const countries = [...new Set(allItems.map((o) => o.country))].sort();

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <Link href="/export" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Export dashboard
        </Link>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Globe size={20} className="text-sky-600" />
          Export opportunities
        </h1>
        <p className="text-sm text-gray-500 mt-1">Ranked by export potential score (0–100)</p>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="input pl-9 w-full"
            placeholder="Search product, country, client…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="input text-sm min-w-[140px]" value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">All countries</option>
          {countries.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      {isLoading && <LoadingState message="Loading opportunities…" />}
      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load opportunities"}
          onRetry={() => refetch()}
        />
      )}
      {!isLoading && !isError && items.length === 0 && (
        <EmptyState
          title="No export opportunities"
          description="Use Analyze Export Potential on a product to generate market recommendations."
        />
      )}
      <div className="space-y-2">
        {items.map((o) => (
          <OpportunityRow key={o.id} opp={o} />
        ))}
      </div>
    </div>
  );
}
