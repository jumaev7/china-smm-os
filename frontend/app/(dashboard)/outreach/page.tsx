"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Plus, Send } from "lucide-react";
import { outreachApi, OutreachStatus, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_STYLE: Record<OutreachStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  approved: "bg-emerald-100 text-emerald-800",
  sent: "bg-sky-100 text-sky-800",
  archived: "bg-stone-100 text-stone-600",
};

export default function OutreachListPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["outreach"],
    queryFn: () => outreachApi.list({ limit: 100 }).then((r) => r.data),
  });

  const items = normalizeList(data);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Send size={22} className="text-indigo-600" />
            Outreach
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            AI-generated buyer messages — drafts only, manual send
          </p>
        </div>
        <Link href="/outreach/new" className="btn-primary text-sm flex items-center gap-1.5">
          <Plus size={15} />
          Generate outreach
        </Link>
      </div>

      {isLoading ? (
        <LoadingState message="Loading outreach messages…" />
      ) : isError ? (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load outreach"}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="No outreach drafts yet"
          description="Generate a professional message for email, WhatsApp, WeChat, or LinkedIn."
        />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-gray-100 bg-gray-50/50">
                <th className="px-4 py-2 font-medium">Buyer</th>
                <th className="px-4 py-2 font-medium">Company</th>
                <th className="px-4 py-2 font-medium">Country</th>
                <th className="px-4 py-2 font-medium">Channel</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id} className="border-b border-gray-50 hover:bg-gray-50/50">
                  <td className="px-4 py-3">
                    <Link href={`/outreach/${m.id}`} className="font-medium text-brand-800 hover:underline">
                      {m.buyer_name || m.lead_name || "—"}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{m.buyer_company || "—"}</td>
                  <td className="px-4 py-3 text-gray-600">{m.country || "—"}</td>
                  <td className="px-4 py-3 capitalize text-xs">{m.channel}</td>
                  <td className="px-4 py-3 text-xs text-gray-600">{m.outreach_type.replace(/_/g, " ")}</td>
                  <td className="px-4 py-3">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full capitalize", STATUS_STYLE[m.status as OutreachStatus])}>
                      {m.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                    {format(parseISO(m.created_at), "MMM d, yyyy")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
