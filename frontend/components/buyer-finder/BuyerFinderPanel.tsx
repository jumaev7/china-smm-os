"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { buyerFinderApi, BuyerRecommendation, BuyerRecommendationType, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";

const TYPE_LABELS: Record<BuyerRecommendationType, string> = {
  partner: "Partner",
  crm_lead: "CRM Lead",
  contact: "Contact",
  industry_segment: "Industry Segment",
};

function ScoreBadge({ score }: { score: number }) {
  return (
    <span
      className={cn(
        "text-xs font-semibold px-2 py-0.5 rounded-full tabular-nums",
        score >= 70
          ? "bg-emerald-100 text-emerald-800"
          : score >= 45
            ? "bg-amber-100 text-amber-800"
            : "bg-gray-100 text-gray-600",
      )}
    >
      {Math.round(score)}
    </span>
  );
}

function actionLink(rec: Pick<BuyerRecommendation, "recommendation_type" | "reference_id">) {
  if (rec.recommendation_type === "partner" && rec.reference_id) {
    return { href: `/partners/${rec.reference_id}`, label: "Open Partner" };
  }
  if (rec.recommendation_type === "crm_lead" && rec.reference_id) {
    return { href: `/crm?lead=${rec.reference_id}`, label: "Open CRM Lead" };
  }
  if (rec.recommendation_type === "contact" && rec.reference_id) {
    return { href: `/communications/contacts/${rec.reference_id}`, label: "Open Contact" };
  }
  return null;
}

function ResultsTable({
  items,
  demoMode,
  productId,
}: {
  items: BuyerRecommendation[];
  demoMode?: boolean;
  productId?: string;
}) {
  if (items.length === 0) {
    return <p className="text-sm text-gray-400">No buyer recommendations yet. Run analysis to generate matches.</p>;
  }

  return (
    <div className="space-y-2">
      {demoMode && (
        <p className="text-[10px] text-amber-600">Rule-based scoring (AI reasons unavailable)</p>
      )}
      <div className="overflow-x-auto rounded-lg border border-gray-100">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left text-[10px] uppercase tracking-wide text-gray-500">
              <th className="px-3 py-2 font-medium">Type</th>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Country</th>
              <th className="px-3 py-2 font-medium">Score</th>
              <th className="px-3 py-2 font-medium">Reason</th>
              <th className="px-3 py-2 font-medium">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {items.map((rec) => {
              const action = actionLink(rec);
              return (
                <tr key={rec.id} className="hover:bg-gray-50/50">
                  <td className="px-3 py-2.5 text-xs text-gray-600 whitespace-nowrap">
                    {TYPE_LABELS[rec.recommendation_type]}
                  </td>
                  <td className="px-3 py-2.5 font-medium text-gray-900 max-w-[160px] truncate">{rec.name}</td>
                  <td className="px-3 py-2.5 text-gray-600 whitespace-nowrap">{rec.country ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    <ScoreBadge score={rec.score} />
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-600 max-w-xs">{rec.reason}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    <div className="flex flex-col gap-1">
                      {action ? (
                        <Link href={action.href} className="text-xs text-brand-700 hover:text-brand-900">
                          {action.label}
                        </Link>
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
                      {productId && (
                        <Link
                          href={`/outreach/new?product_id=${productId}&buyer_name=${encodeURIComponent(rec.name)}&country=${encodeURIComponent(rec.country ?? "")}${rec.recommendation_type === "crm_lead" && rec.reference_id ? `&lead_id=${rec.reference_id}` : ""}`}
                          className="text-xs text-indigo-700 hover:text-indigo-900"
                        >
                          Generate Outreach
                        </Link>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function BuyerFinderPanel({ productId }: { productId: string }) {
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["buyer-finder", productId],
    queryFn: () => buyerFinderApi.getForProduct(productId).then((r) => r.data),
  });

  const analyzeMutation = useMutation({
    mutationFn: () => buyerFinderApi.analyze(productId).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["buyer-finder", productId] });
      qc.invalidateQueries({ queryKey: ["export-dashboard"] });
      toast.success("Buyer analysis complete");
    },
    onError: (err: Error) => toast.error(err.message || "Buyer analysis failed"),
  });

  const items = normalizeList(analyzeMutation.data ?? data);

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Search size={14} className="text-indigo-600" />
          Buyer Finder
        </p>
        <button
          type="button"
          className="text-[11px] px-2 py-1 rounded-lg border border-indigo-200 text-indigo-800 hover:bg-indigo-50 flex items-center gap-1"
          disabled={analyzeMutation.isPending}
          onClick={() => analyzeMutation.mutate()}
        >
          {analyzeMutation.isPending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Sparkles size={12} />
          )}
          Find Buyers
        </button>
      </div>
      <p className="text-[11px] text-gray-500">Advisory only — no automatic outreach or messaging.</p>
      {isLoading && !analyzeMutation.data ? (
        <div className="flex justify-center py-4">
          <Loader2 size={18} className="animate-spin text-indigo-600" />
        </div>
      ) : (
        <ResultsTable
          items={items}
          demoMode={analyzeMutation.data?.demo_mode ?? data?.demo_mode}
          productId={productId}
        />
      )}
    </div>
  );
}

export { ResultsTable, ScoreBadge, TYPE_LABELS, actionLink };
