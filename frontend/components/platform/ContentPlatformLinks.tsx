"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import {
  buyersApi,
  platformRelationshipsApi,
  salesCrmApi,
  normalizeList,
} from "@/lib/api";
import { RelatedEntitiesPanel } from "@/components/platform/RelatedEntitiesPanel";

type Props = {
  contentId: string;
  linkedLeadId?: string | null;
  linkedBuyerId?: string | null;
  linkedDealId?: string | null;
};

export function ContentPlatformLinks({
  contentId,
  linkedLeadId,
  linkedBuyerId,
  linkedDealId,
}: Props) {
  const qc = useQueryClient();

  const { data: leadsData } = useQuery({
    queryKey: ["sales-crm", "leads", "content-link"],
    queryFn: () => salesCrmApi.listLeads({ limit: 100 }).then((r) => r.data),
  });
  const { data: buyersData } = useQuery({
    queryKey: ["buyers", "content-link"],
    queryFn: () => buyersApi.list({ limit: 100 }).then((r) => r.data),
  });
  const { data: dealsData } = useQuery({
    queryKey: ["sales-crm", "deals", "content-link"],
    queryFn: () => salesCrmApi.listDeals({ limit: 100 }).then((r) => r.data),
  });

  const linkMutation = useMutation({
    mutationFn: (links: {
      linked_sales_lead_id?: string | null;
      linked_buyer_id?: string | null;
      linked_sales_deal_id?: string | null;
    }) => platformRelationshipsApi.updateContentLinks(contentId, links),
    onSuccess: () => {
      toast.success("Platform links updated");
      qc.invalidateQueries({ queryKey: ["content", contentId] });
      qc.invalidateQueries({ queryKey: ["platform-related", "content", contentId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const leads = normalizeList(leadsData?.items);
  const buyers = normalizeList(buyersData?.items);
  const deals = normalizeList(dealsData?.items);

  return (
    <div className="card p-4 space-y-3">
      <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
        <Link2 size={16} className="text-indigo-600" />
        Platform links
      </h3>
      <p className="text-xs text-gray-500">
        Connect this content to leads, buyers, or deals for the unified sales workflow.
      </p>
      <label className="block text-xs space-y-1">
        <span className="text-gray-600">Lead</span>
        <select
          className="input w-full text-sm"
          value={linkedLeadId ?? ""}
          disabled={linkMutation.isPending}
          onChange={(e) =>
            linkMutation.mutate({
              linked_sales_lead_id: e.target.value || null,
            })
          }
        >
          <option value="">— None —</option>
          {leads.map((l) => (
            <option key={l.id} value={l.id}>
              {l.company || l.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs space-y-1">
        <span className="text-gray-600">Buyer</span>
        <select
          className="input w-full text-sm"
          value={linkedBuyerId ?? ""}
          disabled={linkMutation.isPending}
          onChange={(e) =>
            linkMutation.mutate({
              linked_buyer_id: e.target.value || null,
            })
          }
        >
          <option value="">— None —</option>
          {buyers.map((b) => (
            <option key={b.id} value={b.id}>
              {b.company_name}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs space-y-1">
        <span className="text-gray-600">Deal</span>
        <select
          className="input w-full text-sm"
          value={linkedDealId ?? ""}
          disabled={linkMutation.isPending}
          onChange={(e) =>
            linkMutation.mutate({
              linked_sales_deal_id: e.target.value || null,
            })
          }
        >
          <option value="">— None —</option>
          {deals.map((d) => (
            <option key={d.id} value={d.id}>
              {d.title}
            </option>
          ))}
        </select>
      </label>
      {linkMutation.isPending && (
        <p className="text-xs text-gray-500 flex items-center gap-1">
          <Loader2 size={12} className="animate-spin" /> Saving…
        </p>
      )}
      <div className="border-t border-gray-100 pt-3">
        <RelatedEntitiesPanel entityType="content" entityId={contentId} compact />
      </div>
    </div>
  );
}
