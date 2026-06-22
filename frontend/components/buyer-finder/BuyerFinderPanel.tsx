"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import {
  buyerFinderApi,
  BuyerRecommendation,
  BuyerRecommendationType,
  normalizeList,
} from "@/lib/api";
import { StatusBadge } from "@/components/ui/design-system";

const TYPE_LABELS: Record<BuyerRecommendationType, string> = {
  partner: "Partner",
  crm_lead: "CRM Lead",
  contact: "Contact",
  industry_segment: "Industry Segment",
};

function ScoreBadge({ score }: { score: number }) {
  const variant = score >= 70 ? "success" : score >= 45 ? "warning" : "neutral";
  return (
    <StatusBadge variant={variant} className="tabular-nums text-[10px]">
      {Math.round(score)}
    </StatusBadge>
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
    return (
      <p className="text-sm text-gray-400 dark-tenant:text-slate-500">
        No buyer recommendations yet. Run analysis to generate matches.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {demoMode && (
        <p className="text-[10px] text-amber-600 dark-tenant:text-amber-400">
          Rule-based scoring (AI reasons unavailable)
        </p>
      )}
      <div className="overflow-x-auto rounded-xl border border-gray-100 dark-tenant:border-white/[0.08]">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50/80 text-left text-[10px] uppercase tracking-wide text-gray-500 dark-tenant:bg-surface-dark-elevated/80 dark-tenant:text-slate-400">
              <th className="px-3 py-2.5 font-medium">Type</th>
              <th className="px-3 py-2.5 font-medium">Name</th>
              <th className="px-3 py-2.5 font-medium">Country</th>
              <th className="px-3 py-2.5 font-medium">Score</th>
              <th className="px-3 py-2.5 font-medium">Reason</th>
              <th className="px-3 py-2.5 font-medium">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50 dark-tenant:divide-white/[0.04]">
            {items.map((rec) => {
              const action = actionLink(rec);
              return (
                <tr
                  key={rec.id}
                  className="hover:bg-gray-50/60 dark-tenant:hover:bg-white/[0.02] transition-colors"
                >
                  <td className="px-3 py-2.5 text-xs text-gray-600 dark-tenant:text-slate-400 whitespace-nowrap">
                    {TYPE_LABELS[rec.recommendation_type]}
                  </td>
                  <td className="px-3 py-2.5 font-medium text-gray-900 dark-tenant:text-slate-100 max-w-[160px] truncate">
                    {rec.name}
                  </td>
                  <td className="px-3 py-2.5 text-gray-600 dark-tenant:text-slate-400 whitespace-nowrap">
                    {rec.country ?? "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    <ScoreBadge score={rec.score} />
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-600 dark-tenant:text-slate-400 max-w-xs">
                    {rec.reason}
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    <div className="flex flex-col gap-1">
                      {action ? (
                        <Link
                          href={action.href}
                          className="text-xs text-brand-700 hover:text-brand-900 dark-tenant:text-violet-400 dark-tenant:hover:text-violet-300 transition-colors"
                        >
                          {action.label}
                        </Link>
                      ) : (
                        <span className="text-xs text-gray-300 dark-tenant:text-slate-600">—</span>
                      )}
                      {productId && (
                        <Link
                          href={`/outreach/new?product_id=${productId}&buyer_name=${encodeURIComponent(rec.name)}&country=${encodeURIComponent(rec.country ?? "")}${rec.recommendation_type === "crm_lead" && rec.reference_id ? `&lead_id=${rec.reference_id}` : ""}`}
                          className="text-xs text-indigo-700 hover:text-indigo-900 dark-tenant:text-sky-400 dark-tenant:hover:text-sky-300 transition-colors"
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
    <div className="card-premium p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900 dark-tenant:text-slate-100 flex items-center gap-1.5">
          <Search size={14} className="text-sky-400" />
          Buyer Search
        </p>
        <button
          type="button"
          className="btn-secondary text-[11px] px-2 py-1 flex items-center gap-1"
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
      <p className="text-[11px] text-gray-500 dark-tenant:text-slate-500">
        Advisory only — no automatic outreach or messaging.
      </p>
      {isLoading && !analyzeMutation.data ? (
        <div className="flex justify-center py-4">
          <Loader2 size={18} className="animate-spin text-violet-500" />
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
