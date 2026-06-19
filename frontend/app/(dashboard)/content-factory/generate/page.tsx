"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Upload,
  Sparkles,
  Plus,
  Image as ImageIcon,
  Film,
  FileText,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  clientsApi,
  Client,
  mediaApi,
  contentFactoryApi,
  ContentFactory,
  ContentFactoryItem,
  FactoryContentCategory,
  FactorySupportedLanguage,
  MediaFile,
  normalizeList,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { ContentFactoryHeader, ContentFactorySubNav } from "@/components/content-factory/ContentFactorySubNav";

const TYPE_LABEL: Record<string, string> = {
  reel: "Reel", post: "Post", story: "Story", carousel: "Carousel",
  article: "Article", telegram: "Telegram", linkedin: "LinkedIn",
};

const CATEGORIES: { value: FactoryContentCategory; label: string }[] = [
  { value: "product_announcement", label: "Product announcement" },
  { value: "factory_news", label: "Factory news" },
  { value: "production_process", label: "Production process" },
  { value: "customer_success", label: "Customer success" },
  { value: "promotion", label: "Promotion" },
  { value: "exhibition", label: "Exhibition" },
  { value: "educational", label: "Educational" },
  { value: "export_opportunity", label: "Export opportunity" },
  { value: "corporate_update", label: "Corporate update" },
  { value: "other", label: "Other" },
];

const LANGUAGES: FactorySupportedLanguage[] = ["ru", "uz", "en", "zh"];

function VariationCard({
  item,
  sourceMediaUrl,
  busy,
  createdContentId,
  onCreateDraft,
}: {
  item: ContentFactoryItem;
  sourceMediaUrl?: string | null;
  busy: boolean;
  createdContentId?: string;
  onCreateDraft: () => void;
}) {
  const contentId = item.generated_content_id ?? createdContentId;
  const scores = item.quality_scores;

  return (
    <div className="card p-4 flex flex-col gap-3">
      {sourceMediaUrl && (
        <div className="rounded-lg overflow-hidden bg-gray-100 aspect-video max-h-36 flex items-center justify-center">
          {sourceMediaUrl.match(/\.(mp4|mov|webm)/i) ? (
            <video src={sourceMediaUrl} className="w-full h-full object-cover" muted />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={sourceMediaUrl} alt="" className="w-full h-full object-cover" />
          )}
        </div>
      )}

      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 leading-snug">{item.title}</p>
          {item.headline && <p className="text-xs text-teal-700 mt-0.5">{item.headline}</p>}
          <p className="text-xs text-gray-500 mt-0.5">{item.theme}</p>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span className="text-[10px] px-2 py-0.5 rounded-full border font-medium bg-indigo-50 text-indigo-800 border-indigo-200">
            {TYPE_LABEL[item.content_type] ?? item.content_type}
          </span>
          {scores?.overall_score != null && (
            <span className="text-[10px] font-bold text-teal-700">Score {scores.overall_score}</span>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1">
        {item.platforms.map((p) => (
          <span
            key={p}
            className={cn(
              "text-[10px] px-1.5 py-0.5 rounded border font-medium",
              PLATFORM_CONFIG[p]?.color ?? "bg-gray-100 text-gray-600 border-gray-200",
            )}
          >
            {PLATFORM_CONFIG[p]?.label ?? p}
          </span>
        ))}
      </div>

      {item.preview_caption && (
        <div className="rounded-lg border border-gray-100 bg-gray-50 p-2.5 text-xs text-gray-700 line-clamp-4">
          {item.preview_caption}
        </div>
      )}

      {item.cta_suggestion && (
        <p className="text-[10px] text-gray-600"><span className="font-medium">CTA:</span> {item.cta_suggestion}</p>
      )}

      {scores?.recommendations && scores.recommendations.length > 0 && (
        <ul className="text-[10px] text-amber-700 list-disc pl-3">
          {scores.recommendations.slice(0, 2).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      <div className="pt-1 border-t border-gray-100 flex gap-2">
        {contentId ? (
          <Link href={`/content/${contentId}`} className="btn-secondary text-xs py-1 flex-1 text-center">
            Open draft
          </Link>
        ) : (
          <button
            type="button"
            className="btn-primary text-xs py-1 flex-1 flex items-center justify-center gap-1"
            disabled={busy}
            onClick={onCreateDraft}
          >
            {busy ? <><Sparkles size={12} className="animate-pulse" /> Creating…</> : <><Plus size={12} /> Create draft</>}
          </button>
        )}
        <Link href="/content-factory/review" className="btn-secondary text-xs py-1 px-2">Review</Link>
      </div>
    </div>
  );
}

export default function ContentFactoryGeneratePage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [clientId, setClientId] = useState("");
  const [selectedMediaId, setSelectedMediaId] = useState<string | null>(null);
  const [variations, setVariations] = useState(4);
  const [inputText, setInputText] = useState("");
  const [inputMode, setInputMode] = useState<"media" | "text">("media");
  const [category, setCategory] = useState<FactoryContentCategory>("product_announcement");
  const [languages, setLanguages] = useState<FactorySupportedLanguage[]>(["ru", "en", "zh"]);
  const [factory, setFactory] = useState<ContentFactory | null>(null);
  const [createdMap, setCreatedMap] = useState<Record<string, string>>({});
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: mediaList, refetch: refetchMedia } = useQuery({
    queryKey: ["media", clientId],
    queryFn: () => mediaApi.listForClient(clientId).then((r) => r.data),
    enabled: !!clientId,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      mediaApi.upload(clientId, file, (pct) => setUploadProgress(pct)),
    onSuccess: (res) => {
      setSelectedMediaId(res.data.id);
      setUploadProgress(null);
      refetchMedia();
      toast.success("Media uploaded");
    },
    onError: (err: Error) => {
      setUploadProgress(null);
      toast.error(err.message || "Upload failed");
    },
  });

  const generateMutation = useMutation({
    mutationFn: async () => {
      if (inputMode === "text") {
        return contentFactoryApi.generateText({
          client_id: clientId,
          input_text: inputText,
          source_media_id: selectedMediaId ?? undefined,
          number_of_variations: variations,
          content_category: category,
          target_languages: languages,
        }).then((r) => r.data);
      }
      return contentFactoryApi.generate({
        client_id: clientId,
        source_media_id: selectedMediaId!,
        number_of_variations: variations,
        content_category: category,
        target_languages: languages,
        input_text: inputText || undefined,
      }).then((r) => r.data);
    },
    onSuccess: (data) => {
      setFactory(data);
      setCreatedMap({});
      queryClient.invalidateQueries({ queryKey: ["content-factory-dashboard"] });
      toast.success(`Generated ${data.items.length} variations`);
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  const draftMutation = useMutation({
    mutationFn: (itemId: string) =>
      contentFactoryApi.createDraftFromItem(itemId).then((r) => r.data),
    onSuccess: (result) => {
      setCreatedMap((prev) => ({ ...prev, [result.factory_item_id]: result.content_id }));
      queryClient.invalidateQueries({ queryKey: ["content"] });
      toast.success(result.message);
      if (result.ai_error) toast.error(`Captions: ${result.ai_error}`);
    },
    onError: (err: Error) => toast.error(err.message || "Draft creation failed"),
  });

  const toggleLanguage = (lang: FactorySupportedLanguage) => {
    setLanguages((prev) =>
      prev.includes(lang) ? prev.filter((l) => l !== lang) : [...prev, lang],
    );
  };

  const canGenerate =
    clientId &&
    languages.length > 0 &&
    (inputMode === "text" ? inputText.trim().length >= 10 : !!selectedMediaId);

  const factoryItems = normalizeList<ContentFactoryItem>(factory);
  const busyItemId = draftMutation.isPending ? draftMutation.variables : null;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <ContentFactoryHeader
        title="Generate content"
        description="Upload raw materials or paste product descriptions — get multilingual, platform-ready posts"
      />
      <ContentFactorySubNav />

      <div className="card p-4 mb-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">Factory / client</label>
            <select
              className="input w-full text-sm"
              value={clientId}
              onChange={(e) => {
                setClientId(e.target.value);
                setSelectedMediaId(null);
                setFactory(null);
              }}
            >
              <option value="">Select client…</option>
              {clientOptions.map((c) => (
                <option key={c.id} value={c.id}>{c.company_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">Content category</label>
            <select className="input w-full text-sm" value={category} onChange={(e) => setCategory(e.target.value as FactoryContentCategory)}>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600 block mb-1">Target languages</label>
          <div className="flex flex-wrap gap-2">
            {LANGUAGES.map((lang) => (
              <button
                key={lang}
                type="button"
                onClick={() => toggleLanguage(lang)}
                className={cn(
                  "text-xs px-3 py-1 rounded-full border",
                  languages.includes(lang)
                    ? "bg-teal-50 border-teal-300 text-teal-800 font-medium"
                    : "border-gray-200 text-gray-500",
                )}
              >
                {lang.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="flex gap-2 border-b border-gray-100 pb-2">
          <button
            type="button"
            className={cn("text-xs px-3 py-1.5 rounded-lg", inputMode === "media" ? "bg-gray-900 text-white" : "text-gray-600")}
            onClick={() => setInputMode("media")}
          >
            Images / video
          </button>
          <button
            type="button"
            className={cn("text-xs px-3 py-1.5 rounded-lg", inputMode === "text" ? "bg-gray-900 text-white" : "text-gray-600")}
            onClick={() => setInputMode("text")}
          >
            Text / documents
          </button>
        </div>

        {inputMode === "text" ? (
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1 flex items-center gap-1">
              <FileText size={12} /> Product description, news, or event info
            </label>
            <textarea
              className="input w-full text-sm min-h-[120px]"
              placeholder="Paste product specs, factory news, exhibition details…"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
            />
          </div>
        ) : (
          clientId && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-medium text-gray-600">Source media</label>
                <button
                  type="button"
                  className="text-xs text-brand-700 flex items-center gap-1"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadMutation.isPending}
                >
                  <Upload size={12} />
                  {uploadProgress != null ? `Uploading ${uploadProgress}%` : "Upload new"}
                </button>
                <input ref={fileInputRef} type="file" accept="image/*,video/*" className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) uploadMutation.mutate(file);
                    e.target.value = "";
                  }}
                />
              </div>
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
                {(mediaList ?? []).map((m: MediaFile) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => { setSelectedMediaId(m.id); setFactory(null); }}
                    className={cn(
                      "rounded-lg border overflow-hidden aspect-square bg-gray-100",
                      selectedMediaId === m.id ? "ring-2 ring-brand-500" : "border-gray-200",
                    )}
                  >
                    {m.file_type === "video" ? (
                      <div className="w-full h-full flex items-center justify-center text-gray-400"><Film size={24} /></div>
                    ) : m.url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={m.url} alt="" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-gray-400"><ImageIcon size={24} /></div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )
        )}

        <div className="optional text-xs text-gray-500">
          Optional context (merged with media)
          <textarea
            className="input w-full text-sm mt-1 min-h-[60px]"
            placeholder="Additional notes for AI…"
            value={inputMode === "media" ? inputText : ""}
            onChange={(e) => inputMode === "media" && setInputText(e.target.value)}
            disabled={inputMode === "text"}
          />
        </div>

        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">Variations</label>
            <input
              type="number"
              min={1}
              max={12}
              className="input w-24 text-sm"
              value={variations}
              onChange={(e) => setVariations(Math.min(12, Math.max(1, Number(e.target.value) || 1)))}
            />
          </div>
          <button
            type="button"
            className="btn-primary text-sm flex items-center gap-1.5"
            disabled={!canGenerate || generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
          >
            {generateMutation.isPending ? (
              <><Sparkles size={14} className="animate-pulse" /> Generating…</>
            ) : (
              <><Sparkles size={14} /> Generate content</>
            )}
          </button>
        </div>
      </div>

      {factory && factoryItems.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-800 mb-3">
            {factoryItems.length} variations · {factory.company_name} · {factory.content_category?.replace("_", " ")}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {factoryItems.map((item) => (
              <VariationCard
                key={item.id}
                item={item}
                sourceMediaUrl={factory.source_media_url}
                busy={busyItemId === item.id}
                createdContentId={createdMap[item.id]}
                onCreateDraft={() => draftMutation.mutate(item.id)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
