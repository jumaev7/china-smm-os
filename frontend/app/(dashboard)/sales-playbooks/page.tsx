"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { ClipboardList, Plus, Sparkles } from "lucide-react";
import { salesPlaybooksApi, PlaybookStatus, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_STYLE: Record<PlaybookStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  active: "bg-emerald-100 text-emerald-800",
  archived: "bg-stone-100 text-stone-600",
};

export default function SalesPlaybooksPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-playbooks"],
    queryFn: () => salesPlaybooksApi.list({ limit: 100 }).then((r) => r.data),
  });

  const items = normalizeList(data);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <ClipboardList size={22} className="text-violet-600" />
            Sales Playbooks
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Reusable multi-step sales templates — apply creates drafts only
          </p>
        </div>
        <Link
          href="/sales-playbooks/new"
          className="btn-primary text-sm flex items-center gap-1.5"
        >
          <Sparkles size={15} />
          Generate playbook
        </Link>
      </div>

      {isLoading ? (
        <LoadingState message="Loading playbooks…" />
      ) : isError ? (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load playbooks"}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="No playbooks yet"
          description="Generate an AI playbook for your product category and buyer type."
          action={
            <Link href="/sales-playbooks/new" className="btn-primary text-sm flex items-center gap-1.5">
              <Plus size={14} />
              Generate playbook
            </Link>
          }
        />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Category</th>
                <th className="text-left px-4 py-2">Buyer type</th>
                <th className="text-left px-4 py-2">Country</th>
                <th className="text-left px-4 py-2">Channel</th>
                <th className="text-left px-4 py-2">Lang</th>
                <th className="text-left px-4 py-2">Status</th>
                <th className="text-left px-4 py-2">Steps</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className="border-t border-gray-100 hover:bg-gray-50/50">
                  <td className="px-4 py-2.5">
                    <Link href={`/sales-playbooks/${p.id}`} className="font-medium text-brand-700 hover:underline">
                      {p.name}
                    </Link>
                    <p className="text-[10px] text-gray-400">
                      {format(parseISO(p.updated_at), "MMM d, yyyy")}
                    </p>
                  </td>
                  <td className="px-4 py-2.5 text-gray-600">{p.product_category || "—"}</td>
                  <td className="px-4 py-2.5 text-gray-600">{p.buyer_type || "—"}</td>
                  <td className="px-4 py-2.5 text-gray-600">{p.country || "—"}</td>
                  <td className="px-4 py-2.5 text-gray-600 capitalize">{p.channel}</td>
                  <td className="px-4 py-2.5 text-gray-600 uppercase">{p.language}</td>
                  <td className="px-4 py-2.5">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full capitalize", STATUS_STYLE[p.status as PlaybookStatus])}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-600">{p.step_count ?? p.steps?.length ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
