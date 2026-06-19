"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { aiApi, ContentItem, Client } from "@/lib/api";
import { X, Sparkles, AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import toast from "react-hot-toast";
import { cn } from "@/lib/utils";

interface Props {
  contentItem: ContentItem;
  client: Client;
  onClose: () => void;
  onGenerated: (updated: ContentItem) => void;
}

const LANG_OPTIONS = [
  { value: "zh", label: "🇨🇳 Chinese" },
  { value: "ru", label: "🇷🇺 Russian" },
  { value: "uz", label: "🇺🇿 Uzbek" },
  { value: "en", label: "🇬🇧 English" },
  { value: "ko", label: "🇰🇷 Korean" },
  { value: "ja", label: "🇯🇵 Japanese" },
];

export function GenerateModal({ contentItem, client, onClose, onGenerated }: Props) {
  // Pre-fill source text from internal_notes for any item that has it.
  // Priority: caption/description first (before [OCR]: or [Transcript]: markers).
  // Works for: Telegram captions, OCR text, video transcripts, manual notes.
  const _getSourceText = () => {
    const notes = contentItem.internal_notes ?? "";
    if (!notes) return "";
    const markers = ["[OCR]:", "[Transcript]:"]
      .map(m => notes.indexOf("\n" + m))
      .filter(i => i !== -1);
    const cut = markers.length ? Math.min(...markers) : -1;
    return cut !== -1 ? notes.slice(0, cut).trim() : notes.trim();
  };
  const [sourceText, setSourceText] = useState(_getSourceText);
  const [contextHint, setContextHint] = useState("");
  const [sourceLang, setSourceLang] = useState<string>(client.source_language ?? "zh");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  const [isDemo, setIsDemo] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      aiApi.generateForContent(contentItem.id, {
        source_language: sourceLang,
        source_text: sourceText.trim() || undefined,
        context_hint: contextHint.trim() || undefined,
      }),
    onSuccess: (res) => {
      const demo = res.headers?.["x-demo-mode"] === "true";
      setIsDemo(demo);
      toast.success(demo ? "Demo captions generated (no API key)" : "Captions generated ✨");
      onGenerated(res.data);
    },
    onError: (err: any) => {
      const detail: string =
        err?.response?.data?.detail ||
        err?.message ||
        "Unknown error";

      if (err?.response?.status === 503) {
        setErrorDetail(
          "OpenAI API key is not configured. Add OPENAI_API_KEY to backend/.env and restart the backend."
        );
      } else if (err?.response?.status === 502) {
        setErrorDetail(`AI generation failed: ${detail}`);
      } else {
        setErrorDetail(detail);
      }
      toast.error("Generation failed");
    },
  });

  return (
    <div
      data-app-modal
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm p-4"
    >
      <div className="card w-full max-w-md shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-brand-600" />
            <h2 className="text-sm font-semibold text-gray-900">Generate AI Content</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          {/* Client context */}
          <div className="bg-gray-50 rounded-lg p-3 text-xs space-y-1">
            <p className="font-medium text-gray-700">{client.company_name}</p>
            <p className="text-gray-400">
              {client.business_category} · {client.content_style} style
            </p>
          </div>

          {/* Source text */}
          <div>
            <label className="label text-xs">
              Source text / product info / post idea
              <span className="text-gray-400 font-normal ml-1">(optional)</span>
              {(contentItem.source === "telegram" || contentItem.source === "telegram_group") && contentItem.internal_notes && !contentItem.internal_notes.includes("[Transcript]:") && (
                <span className="ml-2 text-[10px] bg-sky-100 text-sky-700 px-1.5 py-0.5 rounded font-medium">
                  {contentItem.source === "telegram_group" ? "👥 from Telegram Group" : "📩 from Telegram"}
                </span>
              )}
              {contentItem.internal_notes?.includes("[Transcript]:") && (
                <span className="ml-2 text-[10px] bg-violet-100 text-violet-700 px-1.5 py-0.5 rounded font-medium">
                  🎤 Transcript detected
                </span>
              )}
              {contentItem.source !== "telegram" && contentItem.source !== "telegram_group" && contentItem.internal_notes && !contentItem.internal_notes.includes("[Transcript]:") && (
                <span className="ml-2 text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">
                  🔍 OCR detected
                </span>
              )}
            </label>
            <textarea
              className="input text-sm resize-none"
              rows={4}
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              placeholder={
                sourceLang === "zh"
                  ? "粘贴中文描述或产品信息…"
                  : "Paste product description or post idea…"
              }
              disabled={mutation.isPending}
            />
            <p className="text-[10px] text-gray-400 mt-0.5">
              Supports Chinese, Russian, English — AI will adapt for the Uzbek market
            </p>
          </div>

          {/* Source language */}
          <div>
            <label className="label text-xs">Source text language</label>
            <div className="grid grid-cols-3 gap-1.5">
              {LANG_OPTIONS.map((l) => (
                <button
                  key={l.value}
                  type="button"
                  onClick={() => setSourceLang(l.value)}
                  disabled={mutation.isPending}
                  className={cn(
                    "text-xs py-1.5 px-2 rounded-lg border font-medium transition-all",
                    sourceLang === l.value
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-gray-200 text-gray-500 hover:border-gray-300"
                  )}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          {/* Advanced / context hint */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {showAdvanced ? "Hide" : "Show"} advanced options
            </button>
            {showAdvanced && (
              <div className="mt-2">
                <label className="label text-xs">Context hint</label>
                <input
                  className="input text-xs"
                  value={contextHint}
                  onChange={(e) => setContextHint(e.target.value)}
                  placeholder="e.g. Ramadan promotion, new product launch, grand opening…"
                  disabled={mutation.isPending}
                />
              </div>
            )}
          </div>

          {/* Error display */}
          {errorDetail && (
            <div className="flex items-start gap-2 px-3 py-2.5 bg-red-50 border border-red-200 rounded-lg">
              <AlertCircle size={14} className="text-red-500 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-red-600">{errorDetail}</p>
              </div>
              <button onClick={() => setErrorDetail(null)} className="text-red-400 shrink-0">
                <X size={12} />
              </button>
            </div>
          )}

          {/* What gets generated */}
          {!mutation.isPending && !mutation.isSuccess && (
            <div className="text-[10px] text-gray-400 space-y-0.5">
              <p className="font-medium text-gray-500">Will generate:</p>
              <p>· Short + long captions in Russian, Uzbek, English</p>
              <p>· 10–15 relevant hashtags</p>
              <p>· Status will move to Ready (not auto-approved)</p>
            </div>
          )}

          {/* Generating state */}
          {mutation.isPending && (
            <div className="flex items-center gap-3 py-3">
              <div className="w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full animate-spin shrink-0" />
              <div className="text-xs text-gray-500 space-y-0.5">
                <p className="font-medium text-gray-700">Generating content…</p>
                <p>Translating and localizing for Uzbekistan market</p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-gray-100 shrink-0">
          <button className="btn-secondary text-xs" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </button>
          <button
            className="btn-primary text-xs"
            onClick={() => {
              setErrorDetail(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending}
          >
            <Sparkles size={13} />
            {mutation.isPending ? "Generating…" : "Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
