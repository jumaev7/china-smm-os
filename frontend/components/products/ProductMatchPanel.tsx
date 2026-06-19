"use client";

import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Package, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { productsApi, ProductMatchItem } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ProductMatchPanel({ leadId }: { leadId: string }) {
  const matchMutation = useMutation({
    mutationFn: () => productsApi.matchLead(leadId).then((r) => r.data),
    onError: (err: Error) => toast.error(err.message || "Product matching failed"),
  });

  const result = matchMutation.data;
  const matches = result?.matches ?? [];

  return (
    <div className="border-t border-gray-100 pt-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-800 flex items-center gap-1.5">
          <Package size={14} className="text-brand-600" />
          Product matching
        </p>
        <button
          type="button"
          className="text-[11px] px-2 py-1 rounded-lg border border-brand-200 text-brand-800 hover:bg-brand-50 flex items-center gap-1"
          disabled={matchMutation.isPending}
          onClick={() => matchMutation.mutate()}
        >
          {matchMutation.isPending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Sparkles size={12} />
          )}
          Match products
        </button>
      </div>

      {result && (
        <>
          {result.demo_mode && (
            <p className="text-[10px] text-amber-600">Keyword matching (AI unavailable)</p>
          )}
          {matches.length === 0 ? (
            <p className="text-[11px] text-gray-400">No matching products in catalog for this lead.</p>
          ) : (
            <ul className="space-y-2">
              {matches.map((m: ProductMatchItem) => (
                <li
                  key={m.product_id}
                  className="rounded-lg border border-gray-100 bg-gray-50/80 p-2.5 text-[11px]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      href={`/products/${m.product_id}`}
                      className="font-medium text-brand-800 hover:text-brand-950"
                    >
                      {m.name}
                    </Link>
                    <span
                      className={cn(
                        "shrink-0 text-[10px] px-1.5 py-0.5 rounded-full font-medium tabular-nums",
                        m.confidence >= 0.7
                          ? "bg-emerald-100 text-emerald-800"
                          : m.confidence >= 0.4
                            ? "bg-amber-100 text-amber-800"
                            : "bg-gray-100 text-gray-600",
                      )}
                    >
                      {Math.round(m.confidence * 100)}%
                    </span>
                  </div>
                  {m.category && <p className="text-gray-500 mt-0.5">{m.category}</p>}
                  {m.unit_price != null && (
                    <p className="text-gray-600 tabular-nums mt-0.5">
                      {m.unit_price} {m.currency}
                      {m.sku ? ` · ${m.sku}` : ""}
                    </p>
                  )}
                  <p className="text-gray-600 mt-1">{m.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
