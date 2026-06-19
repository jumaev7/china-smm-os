"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { ArrowLeft, Loader2, Megaphone, Plus, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  campaignsApi,
  contentApi,
  mediaLibraryApi,
  CampaignStatus,
  MediaAsset,
  normalizeList,
} from "@/lib/api";
import { STATUS_CONFIG, cn } from "@/lib/utils";
import { AskAiAboutItem } from "@/components/assistant/AskAiAboutItem";
import { useAiCommandContext } from "@/lib/useAiCommandContext";

function formatDate(val: string | null | undefined): string {
  if (!val) return "—";
  try {
    return format(parseISO(val), "MMM d, yyyy");
  } catch {
    return val;
  }
}

export default function CampaignDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const qc = useQueryClient();
  const aiCtx = useAiCommandContext();
  const [showAssign, setShowAssign] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const { data: campaign, isLoading } = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => campaignsApi.get(id).then((r) => r.data),
  });

  const { data: campaignAssets } = useQuery({
    queryKey: ["campaign-assets", id],
    queryFn: () => mediaLibraryApi.list({ campaign_id: id, limit: 50 }).then((r) => r.data),
    enabled: !!id,
  });

  const { data: clientContent } = useQuery({
    queryKey: ["content-for-campaign", campaign?.client_id],
    queryFn: () =>
      contentApi
        .list({ client_id: campaign!.client_id, limit: 200 })
        .then((r) => r.data),
    enabled: !!campaign?.client_id && showAssign,
  });

  const assignMutation = useMutation({
    mutationFn: (contentIds: string[]) => campaignsApi.assignContent(id, contentIds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", id] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      setShowAssign(false);
      setSelectedIds(new Set());
      toast.success("Content assigned");
    },
    onError: (err: Error) => toast.error(err.message || "Assign failed"),
  });

  const unassignMutation = useMutation({
    mutationFn: (contentId: string) => campaignsApi.unassignContent(id, [contentId]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", id] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Removed from campaign");
    },
    onError: (err: Error) => toast.error(err.message || "Remove failed"),
  });

  const statusMutation = useMutation({
    mutationFn: (status: CampaignStatus) => campaignsApi.update(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", id] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.success("Campaign updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  useEffect(() => {
    if (campaign?.name) {
      aiCtx.setEntityLabel(campaign.name);
    }
  }, [aiCtx, campaign?.name]);

  useEffect(() => {
    const assetIds = normalizeList(campaignAssets).slice(0, 8).map((a) => a.id);
    aiCtx.setSelectedItems(assetIds);
  }, [aiCtx, campaignAssets]);

  if (isLoading || !campaign) {
    return (
      <div className="p-6 flex items-center justify-center gap-2 text-sm text-gray-400">
        <Loader2 size={16} className="animate-spin" />
        Loading campaign…
      </div>
    );
  }

  const counts = campaign.status_counts;
  const assignable = normalizeList(clientContent).filter(
    (item) => item.campaign_id !== id,
  );

  const toggleSelect = (contentId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(contentId)) next.delete(contentId);
      else next.add(contentId);
      return next;
    });
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <Link href="/campaigns" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Campaigns
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
              <Megaphone size={20} className="text-orange-600" />
              {campaign.name}
            </h1>
            <p className="text-sm text-gray-500 mt-1">{campaign.client_name}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <AskAiAboutItem entityLabel={campaign.name} />
            <Link
              href={`/attribution-links?client=${campaign.client_id}&campaign=${id}`}
              className="text-xs px-3 py-1.5 rounded-lg border border-teal-200 text-teal-800 hover:bg-teal-50"
            >
              Create tracking link
            </Link>
            <Link
              href={`/repurpose?client=${campaign.client_id}&campaign=${id}`}
              className="text-xs px-3 py-1.5 rounded-lg border border-amber-200 text-amber-800 hover:bg-amber-50"
            >
              Repurpose Campaign Assets
            </Link>
            <Link
              href={`/content-studio?client=${campaign.client_id}&campaign=${id}`}
              className="text-xs px-3 py-1.5 rounded-lg border border-violet-200 text-violet-800 hover:bg-violet-50"
            >
              Open in Content Studio
            </Link>
            <Link
              href={`/pipeline?client=${campaign.client_id}&campaign=${id}`}
              className="text-xs px-3 py-1.5 rounded-lg border border-teal-200 text-teal-800 hover:bg-teal-50"
            >
              Open Pipeline
            </Link>
            <select
              className="input text-sm w-auto"
              value={campaign.status}
              onChange={(e) => statusMutation.mutate(e.target.value as CampaignStatus)}
              disabled={statusMutation.isPending}
            >
            {(["draft", "active", "completed", "archived"] as CampaignStatus[]).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
            </select>
          </div>
        </div>
      </div>

      <div className="card p-4 grid sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
        <div>
          <p className="text-[10px] uppercase text-gray-400">Objective</p>
          <p className="text-gray-900">{campaign.objective ?? "—"}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase text-gray-400">Dates</p>
          <p className="text-gray-900">
            {formatDate(campaign.start_date)} → {formatDate(campaign.end_date)}
          </p>
        </div>
        <div className="sm:col-span-2">
          <p className="text-[10px] uppercase text-gray-400">Description</p>
          <p className="text-gray-700 whitespace-pre-wrap">{campaign.description ?? "—"}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          { label: "Draft", value: counts.draft },
          { label: "Review", value: counts.review },
          { label: "Approved", value: counts.approved },
          { label: "Scheduled", value: counts.scheduled },
          { label: "Published", value: counts.published },
        ].map(({ label, value }) => (
          <div key={label} className="card p-3 text-center">
            <p className="text-lg font-semibold text-gray-900 tabular-nums">{value}</p>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</p>
          </div>
        ))}
      </div>

      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900">
            Content items ({campaign.content_items.length})
          </p>
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 text-brand-800 hover:bg-brand-50 flex items-center gap-1"
            onClick={() => setShowAssign(!showAssign)}
          >
            <Plus size={12} />
            Assign content
          </button>
        </div>

        {showAssign && (
          <div className="border border-gray-100 rounded-lg p-3 space-y-2 bg-gray-50/50">
            <p className="text-xs text-gray-600">Select existing content for {campaign.client_name}</p>
            {assignable.length === 0 ? (
              <p className="text-xs text-gray-400">No unassigned content for this client.</p>
            ) : (
              <ul className="max-h-48 overflow-y-auto space-y-1">
                {assignable.map((item) => (
                  <li key={item.id}>
                    <label className="flex items-center gap-2 text-xs cursor-pointer p-1.5 rounded hover:bg-white">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(item.id)}
                        onChange={() => toggleSelect(item.id)}
                      />
                      <span className={cn("px-1.5 py-0.5 rounded text-[10px] border", STATUS_CONFIG[item.status as keyof typeof STATUS_CONFIG]?.color ?? "bg-gray-100")}>
                        {STATUS_CONFIG[item.status as keyof typeof STATUS_CONFIG]?.label ?? item.status}
                      </span>
                      <span className="text-gray-800 truncate flex-1">
                        {item.caption_short_en || item.caption_short_ru || item.internal_notes || item.id.slice(0, 8)}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={selectedIds.size === 0 || assignMutation.isPending}
                onClick={() => assignMutation.mutate([...selectedIds])}
                className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white disabled:opacity-50"
              >
                Assign selected ({selectedIds.size})
              </button>
              <button type="button" className="text-xs text-gray-500" onClick={() => setShowAssign(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {campaign.content_items.length === 0 ? (
          <p className="text-xs text-gray-400">No content in this campaign yet.</p>
        ) : (
          <ul className="space-y-2">
            {campaign.content_items.map((item) => {
              const statusCfg = STATUS_CONFIG[item.status as keyof typeof STATUS_CONFIG];
              return (
                <li
                  key={item.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-gray-100 p-2.5"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    {item.media_url && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={item.media_url} alt="" className="w-10 h-10 rounded object-cover shrink-0" />
                    )}
                    <div className="min-w-0">
                      <Link href={`/content/${item.id}`} className="text-sm font-medium text-brand-700 hover:underline truncate block">
                        {item.caption_preview || "Content item"}
                      </Link>
                      <p className="text-[10px] text-gray-500">
                        {(item.platforms ?? []).join(", ") || "no platforms"}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full border", statusCfg?.color ?? "bg-gray-100")}>
                      {statusCfg?.label ?? item.status}
                    </span>
                    <button
                      type="button"
                      className="text-gray-400 hover:text-red-600"
                      title="Remove from campaign"
                      onClick={() => unassignMutation.mutate(item.id)}
                    >
                      <X size={14} />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900">
            Campaign assets ({normalizeList(campaignAssets).length})
          </p>
          <Link
            href={`/media-library?campaign=${id}`}
            className="text-xs text-brand-700 hover:text-brand-900"
          >
            View in library →
          </Link>
        </div>
        {normalizeList(campaignAssets).length === 0 ? (
          <p className="text-xs text-gray-400">
            No media assets linked to this campaign. Upload via Media Library with this campaign selected.
          </p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {normalizeList(campaignAssets).map((asset: MediaAsset) => (
              <Link
                key={asset.id}
                href={`/media-library/${asset.id}`}
                className="rounded-lg border border-gray-100 overflow-hidden hover:ring-1 hover:ring-brand-200"
              >
                <div className="aspect-square bg-gray-50">
                  {asset.thumbnail_url || asset.url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={asset.thumbnail_url || asset.url || ""}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-[10px] text-gray-400 uppercase">
                      {asset.file_type}
                    </div>
                  )}
                </div>
                <p className="text-[11px] p-2 truncate text-gray-800">{asset.title}</p>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
