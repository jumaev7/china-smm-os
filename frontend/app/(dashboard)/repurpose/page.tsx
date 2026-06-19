"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Layers, Loader2, ExternalLink, Lightbulb } from "lucide-react";
import toast from "react-hot-toast";
import {
  campaignsApi,
  clientsApi,
  Client,
  contentApi,
  contentRepurposeApi,
  mediaLibraryApi,
  ContentRepurposeDraft,
  ContentRepurposeFormatSuggestion,
  REPURPOSE_FORMAT_LABELS,
  REPURPOSE_OUTPUT_FORMATS,
  RepurposeOutputFormat,
  RepurposeSourceType,
  normalizeList,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { EmptyState } from "@/components/ui/PageStates";

function DraftCard({ draft }: { draft: ContentRepurposeDraft }) {
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
          <p className="text-sm font-semibold text-gray-900">{draft.format_label}</p>
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
        Open draft
        <ExternalLink size={12} />
      </Link>
    </div>
  );
}

export default function RepurposePage() {
  const searchParams = useSearchParams();
  const [clientId, setClientId] = useState("");
  const [sourceType, setSourceType] = useState<RepurposeSourceType>("media_asset");
  const [sourceId, setSourceId] = useState("");
  const [selectedFormats, setSelectedFormats] = useState<Set<RepurposeOutputFormat>>(
    new Set(["instagram_post", "linkedin_post"]),
  );
  const [drafts, setDrafts] = useState<ContentRepurposeDraft[]>([]);
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    const c = searchParams.get("client");
    const st = searchParams.get("source_type") as RepurposeSourceType | null;
    const sid = searchParams.get("source");
    const camp = searchParams.get("campaign");
    if (c) setClientId(c);
    if (st && ["media_asset", "content_item", "campaign"].includes(st)) {
      setSourceType(st);
    }
    if (sid) setSourceId(sid);
    if (camp && !sid) {
      setSourceType("campaign");
      setSourceId(camp);
    }
  }, [searchParams]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: assetsData } = useQuery({
    queryKey: ["repurpose-assets", clientId],
    queryFn: () => mediaLibraryApi.list({ client_id: clientId, limit: 200 }).then((r) => r.data),
    enabled: !!clientId && sourceType === "media_asset",
  });

  const { data: contentData } = useQuery({
    queryKey: ["repurpose-content", clientId],
    queryFn: () => contentApi.list({ client_id: clientId, limit: 200 }).then((r) => r.data),
    enabled: !!clientId && sourceType === "content_item",
  });

  const { data: campaignsData } = useQuery({
    queryKey: ["repurpose-campaigns", clientId],
    queryFn: () => campaignsApi.list({ client_id: clientId, limit: 200 }).then((r) => r.data),
    enabled: !!clientId && sourceType === "campaign",
  });

  const sourceOptions = useMemo(() => {
    if (sourceType === "media_asset") {
      return normalizeList(assetsData).map((a) => ({
        id: a.id,
        label: a.title,
      }));
    }
    if (sourceType === "content_item") {
      return normalizeList(contentData).map((c) => ({
        id: c.id,
        label: (c.caption_short_en || c.caption_short_ru || c.internal_notes || "Content").slice(0, 60),
      }));
    }
    return normalizeList(campaignsData).map((c) => ({
      id: c.id,
      label: c.name,
    }));
  }, [sourceType, assetsData, contentData, campaignsData]);

  const { data: suggestions, refetch: refetchSuggestions, isFetching: loadingSuggestions } = useQuery({
    queryKey: ["repurpose-suggestions", clientId, sourceType, sourceId],
    queryFn: () =>
      contentRepurposeApi
        .suggestions({ client_id: clientId, source_type: sourceType, source_id: sourceId })
        .then((r) => r.data),
    enabled: false,
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      contentRepurposeApi
        .generate({
          client_id: clientId,
          source_type: sourceType,
          source_id: sourceId,
          output_formats: [...selectedFormats],
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      setDrafts(data.drafts);
      setDemoMode(data.demo_mode);
      toast.success(`Generated ${data.generated_count} draft${data.generated_count === 1 ? "" : "s"}`);
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  const toggleFormat = (fmt: RepurposeOutputFormat) => {
    setSelectedFormats((prev) => {
      const next = new Set(prev);
      if (next.has(fmt)) next.delete(fmt);
      else next.add(fmt);
      return next;
    });
  };

  const applySuggestion = (s: ContentRepurposeFormatSuggestion) => {
    const fmt = s.output_format as RepurposeOutputFormat;
    if (REPURPOSE_OUTPUT_FORMATS.includes(fmt)) {
      setSelectedFormats((prev) => new Set(prev).add(fmt));
    }
  };

  const canGenerate = !!clientId && !!sourceId && selectedFormats.size > 0;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Layers size={22} className="text-amber-600" />
          Repurpose
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Generate multiple platform formats from one media asset, content item, or campaign bundle — drafts only
        </p>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="card p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-900">Source</p>
            <div className="grid sm:grid-cols-2 gap-2">
              <select
                className="input text-sm"
                value={clientId}
                onChange={(e) => {
                  setClientId(e.target.value);
                  setSourceId("");
                  setDrafts([]);
                }}
              >
                <option value="">Client *</option>
                {clientOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.company_name}</option>
                ))}
              </select>
              <select
                className="input text-sm"
                value={sourceType}
                onChange={(e) => {
                  setSourceType(e.target.value as RepurposeSourceType);
                  setSourceId("");
                  setDrafts([]);
                }}
              >
                <option value="media_asset">Media Asset</option>
                <option value="content_item">Content Item</option>
                <option value="campaign">Campaign Asset Bundle</option>
              </select>
            </div>
            <select
              className="input text-sm w-full"
              value={sourceId}
              onChange={(e) => {
                setSourceId(e.target.value);
                setDrafts([]);
              }}
              disabled={!clientId}
            >
              <option value="">
                {!clientId
                  ? "Select client first"
                  : sourceType === "media_asset"
                  ? "Select media asset *"
                  : sourceType === "content_item"
                  ? "Select content item *"
                  : "Select campaign *"}
              </option>
              {sourceOptions.map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
          </div>

          <div className="card p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-900">Output formats</p>
            <div className="grid sm:grid-cols-2 gap-2">
              {REPURPOSE_OUTPUT_FORMATS.map((fmt) => (
                <label
                  key={fmt}
                  className={cn(
                    "flex items-start gap-2 p-2 rounded-lg border cursor-pointer text-sm",
                    selectedFormats.has(fmt) ? "border-amber-300 bg-amber-50" : "border-gray-200",
                  )}
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selectedFormats.has(fmt)}
                    onChange={() => toggleFormat(fmt)}
                  />
                  <span>
                    <span className="font-medium text-gray-900">{REPURPOSE_FORMAT_LABELS[fmt]}</span>
                  </span>
                </label>
              ))}
            </div>
            <button
              type="button"
              className="btn-primary w-full sm:w-auto flex items-center justify-center gap-2"
              disabled={!canGenerate || generateMutation.isPending}
              onClick={() => generateMutation.mutate()}
            >
              {generateMutation.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Layers size={16} />
              )}
              Generate drafts
            </button>
            {demoMode && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded px-2 py-1">
                Demo mode — heuristic drafts (no OpenAI key)
              </p>
            )}
          </div>

          {drafts.length > 0 && (
            <div className="space-y-3">
              <p className="text-sm font-semibold text-gray-900">Generated drafts</p>
              <div className="grid sm:grid-cols-2 gap-3">
                {drafts.map((d) => (
                  <DraftCard key={d.content_id} draft={d} />
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                <Lightbulb size={16} className="text-amber-500" />
                Best formats
              </p>
              <button
                type="button"
                className="text-xs text-brand-700 hover:text-brand-900"
                disabled={!clientId || !sourceId || loadingSuggestions}
                onClick={() => refetchSuggestions()}
              >
                Refresh
              </button>
            </div>
            {!clientId || !sourceId ? (
              <EmptyState title="Select a source" description="Choose client and source to see format suggestions." />
            ) : loadingSuggestions ? (
              <p className="text-xs text-gray-500 flex items-center gap-1">
                <Loader2 size={12} className="animate-spin" /> Loading…
              </p>
            ) : (suggestions?.suggestions ?? []).length === 0 ? (
              <p className="text-xs text-gray-500">No suggestions yet.</p>
            ) : (
              <ul className="space-y-2">
                {(suggestions?.suggestions ?? []).map((s) => (
                  <li key={s.output_format} className="text-xs border border-gray-100 rounded-lg p-2">
                    <button
                      type="button"
                      className="font-medium text-gray-900 hover:text-brand-700 text-left"
                      onClick={() => applySuggestion(s)}
                    >
                      {s.format_label}
                    </button>
                    <p className="text-gray-600 mt-0.5">{s.rationale}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="card p-4 text-xs text-gray-600 space-y-1">
            <p className="font-semibold text-gray-800">Safety</p>
            <p>All outputs are saved as draft ContentItems with source <code>repurpose_engine</code>.</p>
            <p>Nothing is published or approved automatically.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
