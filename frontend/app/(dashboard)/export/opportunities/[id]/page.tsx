"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { ArrowLeft, Globe, Loader2, Package } from "lucide-react";
import { exportApi, PARTNER_TYPE_LABELS, PartnerType } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ExportOpportunityDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const { data: opp, isLoading } = useQuery({
    queryKey: ["export-opportunity", id],
    queryFn: () => exportApi.getOpportunity(id).then((r) => r.data),
  });

  if (isLoading || !opp) {
    return (
      <div className="p-6 flex items-center justify-center gap-2 text-sm text-gray-400">
        <Loader2 size={16} className="animate-spin" />
        Loading opportunity…
      </div>
    );
  }

  const factors = opp.score_factors;

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <Link href="/export/opportunities" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Export opportunities
        </Link>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Globe size={20} className="text-sky-600" />
          {opp.country}
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          {opp.product_name}
          {opp.company_name ? ` · ${opp.company_name}` : ""}
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="card p-3 text-center sm:col-span-1">
          <p
            className={cn(
              "text-2xl font-bold tabular-nums",
              opp.score >= 70 ? "text-emerald-700" : opp.score >= 45 ? "text-amber-700" : "text-gray-700",
            )}
          >
            {Math.round(opp.score)}
          </p>
          <p className="text-[10px] text-gray-500 uppercase">Export score</p>
        </div>
        <div className="card p-3 text-center">
          <p className="text-lg font-semibold capitalize text-gray-900">{opp.demand_level ?? "—"}</p>
          <p className="text-[10px] text-gray-500 uppercase">Demand</p>
        </div>
        <div className="card p-3 text-center">
          <p className="text-lg font-semibold tabular-nums text-gray-900">{factors?.partner_count ?? "—"}</p>
          <p className="text-[10px] text-gray-500 uppercase">Partners</p>
        </div>
        <div className="card p-3 text-center">
          <p className="text-lg font-semibold tabular-nums text-gray-900">{factors?.lead_count ?? "—"}</p>
          <p className="text-[10px] text-gray-500 uppercase">Leads</p>
        </div>
      </div>

      {opp.market_summary && (
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-2">Market summary</p>
          <p className="text-sm text-gray-700">{opp.market_summary}</p>
        </div>
      )}

      <div className="grid sm:grid-cols-2 gap-4">
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-2">Recommended partner types</p>
          {(opp.recommended_partner_types_json ?? []).length === 0 ? (
            <p className="text-xs text-gray-400">—</p>
          ) : (
            <ul className="space-y-1">
              {(opp.recommended_partner_types_json ?? []).map((t) => (
                <li key={t} className="text-xs text-gray-700 capitalize">
                  {PARTNER_TYPE_LABELS[t as PartnerType] ?? t.replace("_", " ")}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-2">Recommended channels</p>
          {(opp.recommended_channels_json ?? []).length === 0 ? (
            <p className="text-xs text-gray-400">—</p>
          ) : (
            <ul className="space-y-1">
              {(opp.recommended_channels_json ?? []).map((c) => (
                <li key={c} className="text-xs text-gray-700">{c}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {factors?.breakdown && (
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-2">Score breakdown</p>
          <dl className="grid grid-cols-2 gap-2 text-xs">
            {Object.entries(factors.breakdown).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <dt className="text-gray-500 capitalize">{k}</dt>
                <dd className="font-medium tabular-nums">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {opp.insights.length > 0 && (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">Export insights</p>
          {opp.insights.map((ins) => (
            <div key={ins.id} className="border-b border-gray-50 pb-3 last:border-0">
              <p className="text-xs font-medium text-gray-800">
                {ins.title}
                <span className="text-gray-400 font-normal ml-2 capitalize">{ins.insight_type}</span>
              </p>
              <p className="text-xs text-gray-600 mt-0.5">{ins.description}</p>
            </div>
          ))}
        </div>
      )}

      <Link
        href={`/products/${opp.product_id}`}
        className="inline-flex items-center gap-1.5 text-sm text-brand-700 hover:text-brand-900"
      >
        <Package size={14} />
        View product
      </Link>

      <p className="text-[10px] text-gray-400">
        Analyzed {format(parseISO(opp.created_at), "MMM d, yyyy HH:mm")} · Advisory only
      </p>
    </div>
  );
}
