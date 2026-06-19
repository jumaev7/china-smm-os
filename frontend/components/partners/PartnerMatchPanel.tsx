"use client";

import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { Handshake, Loader2, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { partnersApi, PartnerMatchItem } from "@/lib/api";
import { cn } from "@/lib/utils";

type MatchMode = "lead" | "product";

export function PartnerMatchPanel({
  mode,
  entityId,
}: {
  mode: MatchMode;
  entityId: string;
}) {
  const matchMutation = useMutation({
    mutationFn: async () => {
      if (mode === "lead") {
        return partnersApi.matchLead(entityId).then((r) => r.data);
      }
      return partnersApi.matchProduct(entityId).then((r) => r.data);
    },
    onError: (err: Error) => toast.error(err.message || "Partner matching failed"),
  });

  const result = matchMutation.data;
  const matches = result?.matches ?? [];

  return (
    <div className="border-t border-gray-100 pt-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-800 flex items-center gap-1.5">
          <Handshake size={14} className="text-violet-600" />
          Partner network
        </p>
        <button
          type="button"
          className="text-[11px] px-2 py-1 rounded-lg border border-violet-200 text-violet-800 hover:bg-violet-50 flex items-center gap-1"
          disabled={matchMutation.isPending}
          onClick={() => matchMutation.mutate()}
        >
          {matchMutation.isPending ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Sparkles size={12} />
          )}
          Match partners
        </button>
      </div>

      {result && (
        <>
          {result.demo_mode && (
            <p className="text-[10px] text-amber-600">Keyword matching (AI unavailable)</p>
          )}
          {matches.length === 0 ? (
            <p className="text-[11px] text-gray-400">No matching partners found.</p>
          ) : (
            <ul className="space-y-2">
              {matches.map((m: PartnerMatchItem) => (
                <li
                  key={m.partner_id}
                  className="rounded-lg border border-gray-100 bg-violet-50/40 p-2.5 text-[11px]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      href={`/partners/${m.partner_id}`}
                      className="font-medium text-violet-900 hover:text-violet-950"
                    >
                      {m.name}
                      {m.company_name ? ` · ${m.company_name}` : ""}
                    </Link>
                    <span
                      className={cn(
                        "shrink-0 text-[10px] px-1.5 py-0.5 rounded-full font-medium tabular-nums",
                        m.score >= 0.7
                          ? "bg-emerald-100 text-emerald-800"
                          : m.score >= 0.4
                            ? "bg-amber-100 text-amber-800"
                            : "bg-gray-100 text-gray-600",
                      )}
                    >
                      {Math.round(m.score * 100)}%
                    </span>
                  </div>
                  {(m.partner_type || m.country) && (
                    <p className="text-gray-500 mt-0.5 capitalize">
                      {[m.partner_type?.replace("_", " "), m.country].filter(Boolean).join(" · ")}
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
