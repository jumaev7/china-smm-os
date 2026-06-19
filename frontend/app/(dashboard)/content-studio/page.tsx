"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles, Loader2, ExternalLink, Lightbulb } from "lucide-react";
import toast from "react-hot-toast";
import {
  campaignsApi,
  clientsApi,
  Client,
  contentStudioApi,
  mediaLibraryApi,
  ContentStudioDraft,
  ContentStudioGoal,
  CONTENT_STUDIO_GOALS,
  MediaAsset,
  normalizeList,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { EmptyState } from "@/components/ui/PageStates";

const PLATFORMS = ["instagram", "facebook", "tiktok", "telegram", "linkedin"] as const;

function AssetThumb({ asset, selected, onToggle }: { asset: MediaAsset; selected: boolean; onToggle: () => void }) {
  const src = asset.thumbnail_url || asset.url;
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "rounded-lg border overflow-hidden text-left transition-all",
        selected ? "ring-2 ring-brand-500 border-brand-300" : "border-gray-200 hover:border-gray-300",
      )}
    >
      <div className="aspect-square bg-gray-50">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[10px] text-gray-400 uppercase">
            {asset.file_type}
          </div>
        )}
      </div>
      <p className="text-[11px] p-1.5 truncate text-gray-800">{asset.title}</p>
    </button>
  );
}

function DraftCard({ draft }: { draft: ContentStudioDraft }) {
  return (
    <div className="card p-4 space-y-3">
      <div className="flex gap-3">
        {draft.media_url && (
          <div className="w-16 h-16 rounded overflow-hidden bg-gray-100 shrink-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={draft.media_url} alt="" className="w-full h-full object-cover" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-gray-900">{draft.title}</p>
          <p className="text-xs text-gray-600 mt-1 line-clamp-3">{draft.preview}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-1">
        {draft.platforms.map((p) => (
          <span key={p} className="text-[10px] px-1.5 py-0.5 rounded border bg-gray-50 text-gray-600 capitalize">
            {PLATFORM_CONFIG[p as keyof typeof PLATFORM_CONFIG]?.label ?? p}
          </span>
        ))}
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-50 text-yellow-800 border border-yellow-100 capitalize">
          {draft.status}
        </span>
      </div>
      <Link
        href={`/content/${draft.content_id}`}
        className="text-xs text-brand-700 hover:text-brand-900 inline-flex items-center gap-1"
      >
        Open content
        <ExternalLink size={12} />
      </Link>
    </div>
  );
}

export default function ContentStudioPage() {
  const searchParams = useSearchParams();
  const [clientId, setClientId] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [selectedAssets, setSelectedAssets] = useState<Set<string>>(new Set());
  const [platforms, setPlatforms] = useState<Set<string>>(new Set(["instagram", "telegram"]));
  const [contentCount, setContentCount] = useState(3);
  const [contentGoal, setContentGoal] = useState<ContentStudioGoal>("Brand awareness");
  const [drafts, setDrafts] = useState<ContentStudioDraft[]>([]);
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    const c = searchParams.get("client");
    const camp = searchParams.get("campaign");
    if (c) setClientId(c);
    if (camp) setCampaignId(camp);
  }, [searchParams]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: campaigns } = useQuery({
    queryKey: ["campaigns-studio", clientId],
    queryFn: () => campaignsApi.list({ client_id: clientId, limit: 200 }).then((r) => r.data),
    enabled: !!clientId,
  });

  const { data: assetsData } = useQuery({
    queryKey: ["media-library-studio", clientId, campaignId],
    queryFn: () =>
      mediaLibraryApi
        .list({
          client_id: clientId,
          campaign_id: campaignId || undefined,
          limit: 100,
        })
        .then((r) => r.data),
    enabled: !!clientId,
  });

  const { data: suggestions, refetch: refetchSuggestions, isFetching: loadingSuggestions } = useQuery({
    queryKey: ["content-studio-suggestions", clientId, campaignId, [...selectedAssets].sort().join(",")],
    queryFn: () =>
      contentStudioApi
        .suggestions({
          client_id: clientId,
          campaign_id: campaignId || undefined,
          media_asset_ids: [...selectedAssets],
        })
        .then((r) => r.data),
    enabled: false,
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      contentStudioApi
        .generate({
          client_id: clientId,
          campaign_id: campaignId || null,
          media_asset_ids: [...selectedAssets],
          platforms: [...platforms],
          content_count: contentCount,
          content_goal: contentGoal,
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      setDrafts(data.drafts);
      setDemoMode(data.demo_mode);
      toast.success(`Generated ${data.generated_count} drafts`);
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  const assets = normalizeList<MediaAsset>(assetsData);

  const toggleAsset = (id: string) => {
    setSelectedAssets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const togglePlatform = (p: string) => {
    setPlatforms((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Sparkles size={22} className="text-violet-600" />
          Content Studio
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Generate draft posts from campaign assets and client knowledge — never auto-published
        </p>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="card p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-900">Setup</p>
            <div className="grid sm:grid-cols-2 gap-2">
              <select className="input text-sm" value={clientId} onChange={(e) => { setClientId(e.target.value); setCampaignId(""); setSelectedAssets(new Set()); }}>
                <option value="">Client *</option>
                {clientOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.company_name}</option>
                ))}
              </select>
              <select className="input text-sm" value={campaignId} onChange={(e) => setCampaignId(e.target.value)} disabled={!clientId}>
                <option value="">Campaign (optional)</option>
                {normalizeList(campaigns).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <select className="input text-sm" value={contentGoal} onChange={(e) => setContentGoal(e.target.value as ContentStudioGoal)}>
                {CONTENT_STUDIO_GOALS.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
              <select className="input text-sm" value={contentCount} onChange={(e) => setContentCount(parseInt(e.target.value, 10))}>
                {[1, 2, 3, 4, 5, 6, 8, 10].map((n) => (
                  <option key={n} value={n}>{n} drafts</option>
                ))}
              </select>
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-1.5">Platforms</p>
              <div className="flex flex-wrap gap-2">
                {PLATFORMS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    onClick={() => togglePlatform(p)}
                    className={cn(
                      "text-xs px-2 py-1 rounded-full border capitalize",
                      platforms.has(p) ? "bg-brand-50 text-brand-800 border-brand-200" : "bg-white text-gray-500 border-gray-200",
                    )}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {clientId && (
            <div className="card p-4 space-y-3">
              <p className="text-sm font-semibold text-gray-900">Media assets ({selectedAssets.size} selected)</p>
              {assets.length === 0 ? (
                <p className="text-xs text-gray-400">No library assets for this client{campaignId ? " / campaign" : ""}.</p>
              ) : (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 max-h-64 overflow-y-auto">
                  {assets.map((a) => (
                    <AssetThumb
                      key={a.id}
                      asset={a}
                      selected={selectedAssets.has(a.id)}
                      onToggle={() => toggleAsset(a.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          <button
            type="button"
            className="btn-primary w-full sm:w-auto flex items-center justify-center gap-2"
            disabled={!clientId || platforms.size === 0 || generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
          >
            {generateMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            Generate drafts
          </button>

          {demoMode && (
            <p className="text-xs text-amber-600">Rule-based generation (AI unavailable)</p>
          )}

          {drafts.length > 0 && (
            <div className="space-y-3">
              <p className="text-sm font-semibold text-gray-900">Generated drafts ({drafts.length})</p>
              <div className="grid sm:grid-cols-2 gap-3">
                {drafts.map((d) => (
                  <DraftCard key={d.content_id} draft={d} />
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="card p-4 space-y-3 h-fit">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Lightbulb size={14} className="text-amber-500" />
              AI suggestions
            </p>
            <button
              type="button"
              className="text-[11px] text-brand-700"
              disabled={!clientId || loadingSuggestions}
              onClick={() => refetchSuggestions()}
            >
              Refresh
            </button>
          </div>
          {!clientId && <p className="text-xs text-gray-400">Select a client to see ideas.</p>}
          {clientId && (suggestions?.suggestions ?? []).length === 0 && !loadingSuggestions && (
            <EmptyState title="No suggestions" description="Try selecting campaign or media assets." />
          )}
          {loadingSuggestions && (
            <p className="text-xs text-gray-400 flex items-center gap-1">
              <Loader2 size={12} className="animate-spin" /> Loading…
            </p>
          )}
          <ul className="space-y-3">
            {(suggestions?.suggestions ?? []).map((s, i) => (
              <li key={i} className="text-xs border-b border-gray-50 pb-3 last:border-0">
                <p className="font-medium text-gray-900">{s.title}</p>
                <p className="text-gray-600 mt-0.5">{s.angle}</p>
                <p className="text-[10px] text-gray-400 mt-1 capitalize">{s.content_goal}</p>
                <p className="text-[10px] text-gray-500 mt-1">{s.rationale}</p>
                <button
                  type="button"
                  className="text-[10px] text-brand-700 mt-1"
                  onClick={() => setContentGoal(s.content_goal as ContentStudioGoal)}
                >
                  Use this goal →
                </button>
              </li>
            ))}
          </ul>
          {suggestions?.demo_mode && (
            <p className="text-[10px] text-amber-600">Fallback suggestions</p>
          )}
        </div>
      </div>
    </div>
  );
}
