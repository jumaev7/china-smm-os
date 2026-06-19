"use client";

import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { Globe, Loader2, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { exportApi } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ExportAnalysisPanel({ productId }: { productId: string }) {
  const analyzeMutation = useMutation({
    mutationFn: () => exportApi.analyzeProduct(productId).then((r) => r.data),
    onError: (err: Error) => toast.error(err.message || "Export analysis failed"),
    onSuccess: () => toast.success("Export analysis complete"),
  });

  const result = analyzeMutation.data;

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Globe size={14} className="text-sky-600" />
          Export potential
        </p>
        <button
          type="button"
          className="text-[11px] px-2 py-1 rounded-lg border border-sky-200 text-sky-800 hover:bg-sky-50 flex items-center gap-1"
          disabled={analyzeMutation.isPending}
          onClick={() => analyzeMutation.mutate()}
        >
          {analyzeMutation.isPending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Sparkles size={12} />
          )}
          Analyze export potential
        </button>
      </div>

      {result && (
        <>
          {result.demo_mode && (
            <p className="text-[10px] text-amber-600">Rule-based analysis (AI unavailable)</p>
          )}
          <div className="flex items-center gap-3">
            <span
              className={cn(
                "text-2xl font-bold tabular-nums",
                result.overall_score >= 70
                  ? "text-emerald-700"
                  : result.overall_score >= 45
                    ? "text-amber-700"
                    : "text-gray-700",
              )}
            >
              {Math.round(result.overall_score)}
            </span>
            <span className="text-xs text-gray-500">overall export score</span>
          </div>
          {result.market_summary && (
            <p className="text-xs text-gray-700">{result.market_summary}</p>
          )}
          <div className="grid sm:grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-1">Top countries</p>
              {result.top_countries.length === 0 ? (
                <p className="text-gray-400">—</p>
              ) : (
                <ul className="space-y-0.5">
                  {result.top_countries.map((c) => (
                    <li key={c} className="text-gray-800">{c}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-1">Top partner types</p>
              {result.top_partner_types.length === 0 ? (
                <p className="text-gray-400">—</p>
              ) : (
                <ul className="space-y-0.5">
                  {result.top_partner_types.map((t) => (
                    <li key={t} className="text-gray-800 capitalize">{t.replace("_", " ")}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          {result.opportunities.length > 0 && (
            <Link
              href="/export/opportunities"
              className="text-[11px] text-sky-700 hover:text-sky-900"
            >
              View {result.opportunities.length} opportunities →
            </Link>
          )}
        </>
      )}

      <p className="text-[10px] text-gray-400">Advisory only — no automatic outreach</p>
    </div>
  );
}
