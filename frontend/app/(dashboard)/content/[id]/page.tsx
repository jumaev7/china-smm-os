"use client";
import { useState, useCallback, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { contentApi, clientsApi, mediaApi, aiApi, publishingApi, mediaLibraryApi, Client, ContentItem, MediaFile, SelectedMediaItem, SubtitleBurnLang, VoiceoverLang, VoiceoverMode,
  CONTEXT_AI_CATEGORIES, CONTEXT_AI_CATEGORY_LABELS, Platform, normalizeList, ContentStatus,
} from "@/lib/api";
import { STATUS_CONFIG, PLATFORM_CONFIG, cn } from "@/lib/utils";
import {
  Sparkles, CheckCheck, ChevronLeft, Save, Calendar,
  Upload, Film, ImageIcon, X, AlertCircle, RefreshCw, Download, Clapperboard, Mic, Package, Brain,
  Link2, Copy, Send, MessageSquare,
} from "lucide-react";
import toast from "react-hot-toast";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useDropzone } from "react-dropzone";
import { ScheduleModal } from "@/components/content/ScheduleModal";
import { PublishingChecklist, useContentReadiness } from "@/components/content/PublishingChecklist";
import { ClientReviewStatusBadge, ClientReviewStatusPanel } from "@/components/content/ClientReviewStatus";
import { WorkflowPanel } from "@/components/content/WorkflowPanel";
import { ContentPlatformLinks } from "@/components/platform/ContentPlatformLinks";
import { TelegramIngestionPanel } from "@/components/content/TelegramIngestionPanel";
import { ContentDetailSkeleton } from "@/components/ui/Skeleton";
import { MediaPreview } from "@/components/ui/MediaPreview";
import { format, parseISO } from "date-fns";
import { clientTimezone, formatScheduledLocal, LOCAL_TIMEZONE_NOTE } from "@/lib/datetime";

const BURN_LANG_OPTIONS: { value: SubtitleBurnLang; label: string }[] = [
  { value: "ru", label: "RU — Russian" },
  { value: "cn", label: "CN — Simplified Chinese" },
  { value: "uz", label: "UZ — Uzbek" },
  { value: "en", label: "EN — English" },
];

const VOICE_LANG_OPTIONS: { value: VoiceoverLang; label: string }[] = [
  { value: "ru", label: "RU — Russian" },
  { value: "uz", label: "UZ — Uzbek" },
  { value: "en", label: "EN — English" },
];

const ACCEPTED_TYPES = {
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
  "image/webp": [".webp"],
  "video/mp4": [".mp4"],
  "video/quicktime": [".mov"],
  "video/webm": [".webm"],
};

export default function ContentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [showSchedule, setShowSchedule] = useState(false);
  const [sourceText, setSourceText] = useState("");
  const [contextHint, setContextHint] = useState("");
  const [sourceLang, setSourceLang] = useState<string | null>(null); // null = use client default
  const [edits, setEdits] = useState<Partial<ContentItem>>({});
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [justGenerated, setJustGenerated] = useState(false);
  const [burnLang, setBurnLang] = useState<SubtitleBurnLang>("ru");
  const [voiceLang, setVoiceLang] = useState<VoiceoverLang>("ru");
  const [voiceoverMode, setVoiceoverMode] = useState<VoiceoverMode | null>(null);
  const [finalExportMode, setFinalExportMode] = useState<VoiceoverMode>("fitted");
  const [previewIndex, setPreviewIndex] = useState(0);
  const [reviewLinkUrl, setReviewLinkUrl] = useState<string | null>(null);
  const [testPlatform, setTestPlatform] = useState<Platform | "">("");
  const [testAccountId, setTestAccountId] = useState("");

  const { data: item, isLoading } = useQuery({
    queryKey: ["content", id],
    queryFn: () => contentApi.get(id).then((r) => r.data),
  });

  const { data: parentAsset } = useQuery({
    queryKey: ["media-asset", item?.parent_media_asset_id],
    queryFn: () => mediaLibraryApi.get(item!.parent_media_asset_id!).then((r) => r.data),
    enabled: !!item?.parent_media_asset_id,
  });

  // Pre-fill the AI source text from internal_notes when the item loads.
  // Works for both Telegram items (caption) and manual uploads (OCR text).
  // Priority: Telegram caption > OCR text > transcript.
  // Strips [OCR]: and [Transcript]: prefixes — only the human/detected content is used.
  // Only runs once per item load — won't overwrite user edits.
  useEffect(() => {
    if (!item?.internal_notes || sourceText !== "") return;
    const notes = item.internal_notes;
    const machineMarkers = ["\n[OCR]:", "\n[Transcript]:", "\n[Context AI]:", "\n[Context AI override]:", "\n[Admin instruction]:", "\n[Telegram instruction]:", "\n[Internal comment]:"];
    let cutIdx = notes.length;
    for (const marker of machineMarkers) {
      const idx = notes.indexOf(marker);
      if (idx !== -1 && idx < cutIdx) cutIdx = idx;
    }
    const sourceInput = notes.slice(0, cutIdx).trim();
    if (sourceInput) setSourceText(sourceInput);
  }, [item?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setPreviewIndex(0);
  }, [item?.id]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: readiness } = useContentReadiness(id, "approve");
  const isPostAdmin = !!item?.approved_at;
  const { data: publishSafety } = useQuery({
    queryKey: ["publish-safety", id, "manual_publish"],
    queryFn: () =>
      contentApi.publishSafety(id, { mode: "manual_publish" }).then((r) => r.data),
    enabled: isPostAdmin,
  });

  const { data: publishingAccounts } = useQuery({
    queryKey: ["publishing-accounts"],
    queryFn: () => publishingApi.listAccounts().then((r) => r.data),
  });

  const { data: publishHistory } = useQuery({
    queryKey: ["publish-history", id],
    queryFn: () => contentApi.getPublishHistory(id).then((r) => r.data),
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      aiApi.generateForContent(id, {
        source_language: sourceLang ?? client?.source_language ?? "zh",
        source_text: sourceText.trim() || undefined,
        context_hint: contextHint.trim() || undefined,
      }),
    onSuccess: (res) => {
      qc.setQueryData(["content", id], res.data);
      qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      setEdits({});
      setGenerateError(null);
      setJustGenerated(true);
      setTimeout(() => setJustGenerated(false), 3000);
      const isDemo = res.headers?.["x-demo-mode"] === "true";
      toast.success(isDemo ? "Demo captions generated (DEMO_MODE=true)" : "Captions generated ✨");
    },
    onError: (err: any) => {
      const status = err?.response?.status;
      const detail: string = err?.response?.data?.detail || err?.message || "Unknown error";
      if (status === 503) {
        setGenerateError(
          "OpenAI API key is not configured. Add OPENAI_API_KEY to backend/.env and restart the backend."
        );
      } else if (status === 502) {
        setGenerateError(`AI service error: ${detail}`);
      } else {
        setGenerateError(detail);
      }
      toast.error("Generation failed");
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => contentApi.update(id, edits),
    onSuccess: (res) => {
      qc.setQueryData(["content", id], res.data);
      qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      setEdits({});
      toast.success("Saved");
    },
    onError: () => toast.error("Save failed"),
  });

  const statusMutation = useMutation({
    mutationFn: (status: ContentStatus) => contentApi.update(id, { status }),
    onSuccess: (res) => {
      qc.setQueryData(["content", id], res.data);
      qc.invalidateQueries({ queryKey: ["content"] });
      toast.success("Status updated");
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Status update failed");
    },
  });

  const voiceoverMutation = useMutation({
    mutationFn: (mode: VoiceoverMode) => contentApi.generateVoiceover(id, voiceLang, mode),
    onMutate: (mode) => setVoiceoverMode(mode),
    onSuccess: (res, mode) => {
      qc.setQueryData(["content", id], res.data);
      qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      toast.success(
        mode === "fitted" ? "Fitted voiceover ready" : "Extended voiceover ready"
      );
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || "Failed to generate voiceover";
      toast.error(typeof detail === "string" ? detail : "Failed to generate voiceover");
    },
    onSettled: () => setVoiceoverMode(null),
  });

  const burnSubtitlesMutation = useMutation({
    mutationFn: () => contentApi.burnSubtitles(id, burnLang),
    onSuccess: (res) => {
      qc.setQueryData(["content", id], res.data);
      qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      toast.success("Subtitled video ready");
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || "Failed to generate subtitled video";
      toast.error(typeof detail === "string" ? detail : "Failed to generate subtitled video");
    },
  });

  const finalVideoMutation = useMutation({
    mutationFn: () =>
      contentApi.generateFinalVideo(id, burnLang, voiceLang, finalExportMode),
    onSuccess: (res) => {
      qc.setQueryData(["content", id], res.data);
      qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      toast.success("Final video ready");
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail || "Failed to generate final video";
      toast.error(typeof detail === "string" ? detail : "Failed to generate final video");
    },
  });

  const approveMutation = useMutation({
    mutationFn: () => contentApi.approve(id),
    onSuccess: (res) => {
      qc.setQueryData(["content", id], res.data);
      qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      qc.invalidateQueries({ queryKey: ["publish-safety", id] });
      toast.success("Approved ✓");
    },
    onError: () => toast.error("Approval failed"),
  });

  const publishMutation = useMutation({
    mutationFn: () => contentApi.publish(id, { mode: "manual_publish" }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["content", id] });
      qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      qc.invalidateQueries({ queryKey: ["publish-safety", id] });
      qc.invalidateQueries({ queryKey: ["publish-history", id] });
      if (res.data.all_success) {
        toast.success(`Published to ${res.data.results.length} platform(s) ✓`);
      } else {
        toast.error("Publishing failed on one or more platforms");
      }
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail && typeof detail === "object" && "message" in detail
            ? String((detail as { message?: string }).message)
            : "Publish failed";
      toast.error(message);
      qc.invalidateQueries({ queryKey: ["publish-safety", id] });
      qc.invalidateQueries({ queryKey: ["publish-history", id] });
    },
  });

  const { data: testPublishSafety } = useQuery({
    queryKey: ["publish-safety", id, "test_publish", testPlatform, testAccountId],
    queryFn: () =>
      contentApi
        .publishSafety(id, {
          mode: "test_publish",
          platform: testPlatform as Platform,
          account_id: testAccountId,
        })
        .then((r) => r.data),
    enabled: !!testPlatform && !!testAccountId,
  });

  const testPublishMutation = useMutation({
    mutationFn: () =>
      contentApi.publish(id, {
        platforms: [testPlatform as Platform],
        account_id: testAccountId,
        mode: "test_publish",
        test: true,
      }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["publish-history", id] });
      if (res.data.all_success) {
        toast.success(`Test publish succeeded on ${testPlatform} ✓`);
      } else {
        toast.error("Test publish failed");
      }
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Test publish failed");
    },
  });

  const reviewLinkMutation = useMutation({
    mutationFn: () => contentApi.createReviewLink(id),
    onSuccess: (res) => {
      setReviewLinkUrl(res.data.url);
      qc.invalidateQueries({ queryKey: ["content", id] });
      toast.success("Client review link created");
    },
    onError: () => toast.error("Failed to create review link"),
  });

  const mediaRequestMutation = useMutation({
    mutationFn: () => {
      const planType = item?.content_plan_context?.content_type;
      const formatMap: Record<string, "photo" | "video" | "carousel" | "story"> = {
        image: "photo",
        video: "video",
        carousel: "carousel",
        story: "story",
      };
      const format = planType ? formatMap[planType] ?? "any" : "any";
      return contentApi.requestMedia(id, { format });
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["content", id] });
      qc.invalidateQueries({ queryKey: ["operator-inbox"] });
      toast.success(res.data.message);
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Media request failed");
    },
  });

  const copyReviewLink = async () => {
    const url = reviewLinkUrl
      || (item?.review_token ? `${window.location.origin}/review/${item.review_token}` : null);
    if (!url) return;
    await navigator.clipboard.writeText(url);
    toast.success("Link copied");
  };

  const onDrop = useCallback(async (accepted: File[], rejected: any[]) => {
    setUploadError(null);
    if (!item) return;
    if (rejected.length > 0) {
      setUploadError("Unsupported file or size exceeded. Use JPG/PNG/WebP (≤20 MB) or MP4/MOV/WebM (≤200 MB).");
      return;
    }
    if (accepted.length === 0) return;

    setUploading(true);
    setUploadProgress(0);
    try {
      const res = await mediaApi.upload(item.client_id, accepted[0], (pct) => {
        setUploadProgress(pct);
      });
      const newMedia: MediaFile = res.data;
      // Attach new media to this content item
      await contentApi.update(id, { media_file_id: newMedia.id } as any);
      await qc.invalidateQueries({ queryKey: ["content", id] });
      await qc.invalidateQueries({ queryKey: ["content-readiness", id] });
      toast.success("Media replaced ✓");
    } catch (err: any) {
      const msg = err?.response?.data?.detail || "Upload failed";
      setUploadError(msg);
      toast.error(msg);
    } finally {
      setUploading(false);
    }
  }, [item, id, qc]);

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxFiles: 1,
    maxSize: 200 * 1024 * 1024,
    disabled: uploading,
    noClick: true,
  });

  if (isLoading || !item) return <ContentDetailSkeleton />;

  const client = clientOptions.find((c) => c.id === item.client_id);
  const status = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.draft;
  const merged = { ...item, ...edits };
  const hasChanges = Object.keys(edits).length > 0;

  const clientChangesPending = readiness?.items.some(
    (i) => i.id === "client_changes" && !i.ready,
  );
  const approveBlockedReason = clientChangesPending
    ? "Client requested changes — update content first"
    : !readiness?.ready_for_approve
      ? "Complete the publishing checklist first"
      : undefined;

  const publishSafetyErrors = publishSafety?.errors.filter((e) => e.critical) ?? [];
  const publishBlockedBySafety = isPostAdmin && publishSafety != null && !publishSafety.passed;
  const testPublishSafetyErrors = testPublishSafety?.errors.filter((e) => e.critical) ?? [];
  const testPublishBlockedBySafety =
    testPublishSafety != null && !testPublishSafety.passed;
  const galleryMedia: SelectedMediaItem[] =
    item.selected_media && item.selected_media.length > 0
      ? item.selected_media
      : item.media_url
        ? [{
            ordinal: 1,
            media_file_id: item.media_file_id ?? "",
            media_type: item.media_file_type ?? "image",
            url: item.media_url,
            text: "",
          }]
        : [];

  const safePreviewIndex =
    galleryMedia.length > 0 ? Math.min(previewIndex, galleryMedia.length - 1) : 0;
  const currentPreview = galleryMedia[safePreviewIndex] ?? galleryMedia[0];
  const previewUrl = currentPreview?.url ?? item.media_url;
  const showGallery = galleryMedia.length > 1;

  const activeAccounts = normalizeList(publishingAccounts).filter(
    (a) => a.status === "mock" || a.status === "connected",
  );
  const platformsWithAccounts = [...new Set(activeAccounts.map((a) => a.platform))] as Platform[];
  const testPublishPlatforms = [
    ...new Set<Platform>([...(item.platforms ?? []), ...platformsWithAccounts]),
  ].sort((a, b) => (PLATFORM_CONFIG[a]?.label ?? a).localeCompare(PLATFORM_CONFIG[b]?.label ?? b));
  const accountsForPlatform = activeAccounts.filter((a) => a.platform === testPlatform);

  const isVideo =
    currentPreview?.media_type === "video" ||
    item.media_file_type === "video" ||
    !!previewUrl?.match(/\.(mp4|webm|mov)$/i);

  const subtitleUrlForBurn =
    burnLang === "cn" ? item.subtitle_url_cn
    : burnLang === "ru" ? item.subtitle_url_ru
    : burnLang === "uz" ? item.subtitle_url_uz
    : item.subtitle_url_en;

  const subtitledVideoUrlForBurn =
    burnLang === "cn" ? item.subtitled_video_url_cn
    : burnLang === "ru" ? item.subtitled_video_url_ru
    : burnLang === "uz" ? item.subtitled_video_url_uz
    : item.subtitled_video_url_en;

  const subtitleUrlForVoice =
    voiceLang === "ru" ? item.subtitle_url_ru
    : voiceLang === "uz" ? item.subtitle_url_uz
    : item.subtitle_url_en;

  const dubbedVideoUrlForVoice =
    voiceLang === "ru" ? item.dubbed_video_url_ru
    : voiceLang === "uz" ? item.dubbed_video_url_uz
    : item.dubbed_video_url_en;

  const dubbedExtendedVideoUrlForVoice =
    voiceLang === "ru" ? item.dubbed_video_extended_url_ru
    : voiceLang === "uz" ? item.dubbed_video_extended_url_uz
    : item.dubbed_video_extended_url_en;

  const subtitleUrlForFinal =
    burnLang === "cn" ? item.subtitle_url_cn
    : burnLang === "ru" ? item.subtitle_url_ru
    : burnLang === "uz" ? item.subtitle_url_uz
    : item.subtitle_url_en;

  const finalExportKey =
    burnLang === "cn"
      ? "cn:original:n/a"
      : `${burnLang}:${voiceLang}:${finalExportMode}`;

  const finalVideoUrlForExport =
    item.generated_final_video_url
    ?? item.final_export_urls?.[finalExportKey]
    ?? null;

  const finalExportSummary =
    burnLang === "cn"
      ? {
          subtitle: burnLang.toUpperCase(),
          voice: "Original",
          mode: "N/A",
        }
      : {
          subtitle: burnLang.toUpperCase(),
          voice: voiceLang.toUpperCase(),
          mode: finalExportMode === "fitted" ? "Fitted" : "Extended",
        };

  const field = (key: keyof ContentItem) => ({
    value: (merged[key] as string) ?? "",
    onChange: (e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) =>
      setEdits((prev) => ({ ...prev, [key]: e.target.value })),
  });

  let telegramInstructionHistory: {
    at: string;
    instruction: string;
    summary: string;
    from: string;
    status?: string;
  }[] = [];
  if (item.telegram_instructions) {
    try {
      telegramInstructionHistory = JSON.parse(item.telegram_instructions);
    } catch {
      telegramInstructionHistory = [];
    }
  }

  const effectiveContextCategory =
    merged.context_ai_override || item.context_ai_detected || null;
  const contextConfidence = item.context_ai_confidence ?? null;

  const instructionStatusLabel = (entry: { status?: string; summary?: string }) => {
    if (entry.status) return entry.status;
    if (entry.summary?.toLowerCase().includes("internal note")) return "internal note";
    return "applied";
  };

  const instructionStatusStyle = (status: string) => {
    if (status === "internal note") return "bg-blue-100 text-blue-700";
    if (status === "ignored") return "bg-gray-100 text-gray-600";
    return "bg-green-100 text-green-700";
  };

  let bufferRefs: {
    ordinal: number;
    message_id: number;
    message_type: string;
    media_file_id?: string | null;
    text?: string;
  }[] = [];
  if (item.telegram_buffer_refs) {
    try {
      bufferRefs = JSON.parse(item.telegram_buffer_refs);
    } catch {
      bufferRefs = [];
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* Back + header */}
      <div className="flex items-start justify-between mb-6 gap-4">
        <div>
          <Link
            href="/content"
            className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-2 transition-colors"
          >
            <ChevronLeft size={14} /> Back to content
          </Link>
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-xl font-semibold text-gray-900">{client?.company_name ?? "Content"}</h1>
            {item.source === "telegram_group" && (
              <span className="text-[10px] bg-violet-100 text-violet-700 px-2 py-0.5 rounded font-medium">
                👥 Telegram Group
              </span>
            )}
            {item.source === "tg_group_buffer" && (
              <span className="text-[10px] bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded font-medium">
                📦 Telegram group buffer
              </span>
            )}
            {item.source === "tg_inbox_auto_draft" && (
              <span className="text-[10px] bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded font-medium">
                ✨ AI Auto Draft
              </span>
            )}
            {item.source === "content_plan" && (
              <span className="text-[10px] bg-violet-100 text-violet-800 px-2 py-0.5 rounded font-medium">
                {item.content_plan_context?.ai_generated ? "✨ Content Plan AI" : "📋 Content Plan"}
              </span>
            )}
            {item.source === "repurpose_engine" && (
              <span className="text-[10px] bg-amber-100 text-amber-800 px-2 py-0.5 rounded font-medium">
                ♻️ Repurpose Engine
              </span>
            )}
            {item.source === "telegram" && (
              <span className="text-[10px] bg-sky-100 text-sky-700 px-2 py-0.5 rounded font-medium">
                📩 Telegram
              </span>
            )}
            <span className={cn("status-badge", status.color)}>
              <span className={cn("w-1.5 h-1.5 rounded-full", status.dot)} />
              {status.label}
            </span>
            {item.telegram_excluded && (
              <span className="text-[10px] bg-red-100 text-red-700 px-2 py-0.5 rounded font-medium">
                Excluded
              </span>
            )}
          </div>
            {item.source === "telegram_group" && item.telegram_group_title && (
            <p className="text-xs text-violet-700 mt-1">{item.telegram_group_title}</p>
          )}
          {item.source === "tg_group_buffer" && (
            <div className="mt-2 text-xs text-indigo-800 bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-2">
              <p className="font-medium">Source: Telegram group buffer</p>
              {item.telegram_group_title && (
                <p className="text-indigo-700 mt-0.5">{item.telegram_group_title}</p>
              )}
              {bufferRefs.length > 0 && (
                <ul className="mt-2 space-y-1 text-[11px] text-indigo-900">
                  {bufferRefs.map((ref) => (
                    <li key={`${ref.message_id}-${ref.ordinal}`}>
                      #{ref.ordinal} · {ref.message_type} · msg {ref.message_id}
                      {ref.text ? ` · “${ref.text.slice(0, 60)}${ref.text.length > 60 ? "…" : ""}”` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {item.source === "tg_inbox_auto_draft" && (
            <div className="mt-2 text-xs text-emerald-900 bg-emerald-50 border border-emerald-100 rounded-lg px-3 py-2">
              <p className="font-medium">Source: Created by AI Auto Draft</p>
              <p className="text-emerald-800/90 mt-0.5">
                Draft only — admin must review and approve before anything is published.
              </p>
              {item.telegram_group_title && (
                <p className="text-emerald-700 mt-0.5">{item.telegram_group_title}</p>
              )}
              {bufferRefs.length > 0 && (
                <ul className="mt-2 space-y-1 text-[11px] text-emerald-900">
                  {bufferRefs.map((ref) => (
                    <li key={`${ref.message_id}-${ref.ordinal}`}>
                      #{ref.ordinal} · {ref.message_type} · msg {ref.message_id}
                      {ref.text ? ` · “${ref.text.slice(0, 60)}${ref.text.length > 60 ? "…" : ""}”` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {item.source === "content_plan" && item.content_plan_context && (
            <div className="mt-2 text-xs text-violet-900 bg-violet-50 border border-violet-100 rounded-lg px-3 py-2">
              <p className="font-medium">
                {item.content_plan_context.ai_generated
                  ? "Generated from Content Plan with AI"
                  : "Created from Content Plan"}
              </p>
              <p className="text-violet-800/90 mt-0.5">{item.content_plan_context.plan_title}</p>
              <dl className="mt-2 space-y-1 text-[11px] text-violet-900">
                <div>
                  <dt className="font-medium inline">Theme: </dt>
                  <dd className="inline">{item.content_plan_context.theme}</dd>
                </div>
                <div>
                  <dt className="font-medium inline">Goal: </dt>
                  <dd className="inline">{item.content_plan_context.goal}</dd>
                </div>
                <div>
                  <dt className="font-medium inline">Planned date: </dt>
                  <dd className="inline">
                    {formatScheduledLocal(`${item.content_plan_context.planned_date}T12:00:00.000Z`)}
                  </dd>
                </div>
                <div>
                  <dt className="font-medium inline">Format: </dt>
                  <dd className="inline capitalize">{item.content_plan_context.content_type}</dd>
                </div>
              </dl>
              <p className="text-violet-800/90 mt-2">
                {item.content_plan_context.ai_generated
                  ? "AI captions are a starting point — add media, review text, and approve before publishing."
                  : "Draft only — add media, generate captions, and approve before publishing."}
              </p>
            </div>
          )}
          {(item.parent_content_id || item.parent_media_asset_id || item.source === "repurpose_engine") && (
            <div className="mt-2 text-xs text-amber-900 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
              <p className="font-medium">Generated From</p>
              <ul className="mt-1.5 space-y-1">
                {item.parent_media_asset_id && (
                  <li>
                    <span className="text-amber-800">Media Asset: </span>
                    <Link
                      href={`/media-library/${item.parent_media_asset_id}`}
                      className="text-brand-700 hover:text-brand-900 font-medium"
                    >
                      {parentAsset?.title ?? item.parent_media_asset_id.slice(0, 8) + "…"}
                    </Link>
                  </li>
                )}
                {item.parent_content_id && (
                  <li>
                    <span className="text-amber-800">Content Item: </span>
                    <Link
                      href={`/content/${item.parent_content_id}`}
                      className="text-brand-700 hover:text-brand-900 font-medium"
                    >
                      Open source content
                    </Link>
                  </li>
                )}
              </ul>
              {item.source === "repurpose_engine" && (
                <p className="text-amber-800/90 mt-2">
                  Draft only — review captions and approve before publishing.
                </p>
              )}
            </div>
          )}
          <div className="flex gap-1.5 mt-1.5 flex-wrap">
            {item.platforms.map((p) => (
              <span key={p} className={cn("text-[10px] px-2 py-0.5 rounded font-medium", PLATFORM_CONFIG[p]?.color)}>
                {PLATFORM_CONFIG[p]?.label}
              </span>
            ))}
          </div>
          {item.scheduled_for && (
            <p className="text-xs text-purple-600 font-medium mt-1.5">
              📅 Scheduled: {formatScheduledLocal(item.scheduled_for)}
            </p>
          )}
          {item.published_at && (
            <p className="text-xs text-emerald-600 font-medium mt-1">
              ✅ Published: {format(parseISO(item.published_at), "EEE MMM d, yyyy 'at' HH:mm")}
            </p>
          )}
          {item.client_approved_at && (
            <p className="text-xs text-teal-700 font-medium mt-1">
              ✅ Client approved: {format(parseISO(item.client_approved_at), "EEE MMM d, yyyy 'at' HH:mm")}
            </p>
          )}
          {item.client_review_status && (
            <div className="mt-1.5">
              <ClientReviewStatusBadge item={item} />
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {hasChanges && (
            <button
              className="btn-secondary text-xs"
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
            >
              <Save size={13} /> {saveMutation.isPending ? "Saving…" : "Save edits"}
            </button>
          )}
          <button
            className="btn-secondary text-xs"
            onClick={() => setShowSchedule(true)}
            disabled={!readiness?.ready_for_approve}
            title={approveBlockedReason}
          >
            <Calendar size={13} /> Schedule
          </button>
          {!["approved", "scheduled", "published", "publishing"].includes(item.status) && (
            <button
              className="btn-primary text-xs"
              onClick={() => approveMutation.mutate()}
              disabled={approveMutation.isPending || !readiness?.ready_for_approve}
              title={approveBlockedReason}
            >
              <CheckCheck size={13} /> Approve
            </button>
          )}
          {["approved", "scheduled", "failed", "partial_failed"].includes(item.status) && (
            <button
              className="btn-primary text-xs"
              onClick={() => publishMutation.mutate()}
              disabled={
                publishMutation.isPending
                || !item.approved_at
                || publishBlockedBySafety
              }
              title={
                publishBlockedBySafety
                  ? publishSafety?.message || "Publish blocked by safety guard"
                  : !item.approved_at
                    ? "Approve content before publishing"
                    : "Publish to selected platforms"
              }
            >
              <Send size={13} />
              {publishMutation.isPending ? "Publishing…" : "Publish now"}
            </button>
          )}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
        {/* Left col: media + AI + client info */}
        <div className="space-y-4">

          <div className="card p-3">
            <WorkflowPanel
              contentId={id}
              voiceLang={voiceLang}
              subtitleLang={burnLang}
              voiceMode={finalExportMode}
              sourceLanguage={sourceLang ?? client?.source_language}
              sourceText={sourceText}
              contextHint={contextHint}
              disabled={!item.media_file_id}
            />
          </div>

          <ContentPlatformLinks
            contentId={id}
            linkedLeadId={item.linked_sales_lead_id}
            linkedBuyerId={item.linked_buyer_id}
            linkedDealId={item.linked_sales_deal_id}
          />

          {!["approved", "scheduled", "published"].includes(item.status) && (
            <PublishingChecklist
              contentId={id}
              intent="approve"
              onFixWithAi={() => generateMutation.mutate()}
              fixingWithAi={generateMutation.isPending}
            />
          )}

          {isPostAdmin && (
            <PublishingChecklist
              contentId={id}
              intent="schedule"
            />
          )}

          <ClientReviewStatusPanel
            item={item}
            contentId={id}
            onPreviewSent={() => qc.invalidateQueries({ queryKey: ["content", id] })}
          />

          <div className="card p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-2">Client review link</h3>
            <p className="text-xs text-gray-500 mb-3">
              After admin approve or schedule (while client review is pending), a Telegram preview
              with ✅ / ✏️ / ❌ buttons is sent to the client intake group. Use the button above to
              resend if needed.
            </p>
            <button
              type="button"
              className="btn-secondary text-xs w-full"
              onClick={() => reviewLinkMutation.mutate()}
              disabled={reviewLinkMutation.isPending}
            >
              <Link2 size={13} />
              {reviewLinkMutation.isPending ? "Creating…" : "Create client review link"}
            </button>
            {(reviewLinkUrl || item.review_token) && (
              <div className="mt-3 flex gap-2">
                <input
                  readOnly
                  className="input text-[11px] flex-1 font-mono"
                  value={
                    reviewLinkUrl
                    || `${typeof window !== "undefined" ? window.location.origin : ""}/review/${item.review_token}`
                  }
                />
                <button type="button" className="btn-secondary text-xs shrink-0" onClick={copyReviewLink}>
                  <Copy size={13} /> Copy
                </button>
              </div>
            )}
          </div>

          {(item.scheduled_for
            || item.status === "scheduled"
            || item.status === "publishing"
            || item.status === "partial_failed"
            || normalizeList(publishHistory).length > 0) && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Scheduled publishing</h3>
              {publishBlockedBySafety && publishSafetyErrors.length > 0 && (
                <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <p className="text-xs font-medium text-amber-900 mb-1">Publish blocked</p>
                  <ul className="space-y-1">
                    {publishSafetyErrors.map((e) => (
                      <li key={e.id} className="text-[11px] text-amber-800">
                        • {e.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="space-y-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-gray-500">Status</span>
                  <span className={cn("status-badge text-[10px]", status.color)}>
                    <span className={cn("w-1.5 h-1.5 rounded-full", status.dot)} />
                    {status.label}
                  </span>
                </div>
                {item.status === "scheduled" && item.scheduled_for && (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-gray-500">Next publish</span>
                    <span className="font-medium text-purple-700">
                      {formatScheduledLocal(item.scheduled_for)}
                    </span>
                  </div>
                )}
                <p className="text-[10px] text-gray-400">{LOCAL_TIMEZONE_NOTE}</p>
                {item.status === "publishing" && (
                  <p className="text-cyan-700">Auto-publish in progress…</p>
                )}
                {item.published_at && (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-gray-500">Last published</span>
                    <span className="font-medium text-emerald-700">
                      {format(parseISO(item.published_at), "EEE MMM d, yyyy 'at' HH:mm")}
                    </span>
                  </div>
                )}
              </div>

              <div className="mt-4 border-t border-gray-100 pt-3">
                <p className="text-[10px] text-gray-400 uppercase font-medium tracking-wide mb-2">
                  Publish history
                </p>
                {normalizeList(publishHistory).length > 0 ? (
                  <ul className="space-y-2 max-h-48 overflow-y-auto">
                    {normalizeList(publishHistory).map((attempt) => (
                      <li key={attempt.id} className="text-[11px] border border-gray-100 rounded-lg p-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-gray-800">
                            {PLATFORM_CONFIG[attempt.platform]?.label ?? attempt.platform}
                          </span>
                          <span
                            className={cn(
                              "text-[10px] px-1.5 py-0.5 rounded-full font-medium",
                              attempt.status === "success"
                                ? "bg-emerald-100 text-emerald-700"
                                : "bg-red-100 text-red-700",
                            )}
                          >
                            {attempt.status}
                          </span>
                        </div>
                        {attempt.account_name && (
                          <p className="text-gray-500 mt-0.5">{attempt.account_name}</p>
                        )}
                        {attempt.status === "success" && attempt.platform_post_id && (
                          <p className="text-gray-500 mt-0.5 font-mono text-[10px]">
                            Post ID: {attempt.platform_post_id}
                          </p>
                        )}
                        {attempt.error && (
                          <p className="text-red-600 mt-0.5">{attempt.error}</p>
                        )}
                        <div className="flex items-center justify-between gap-2 mt-1">
                          <p className="text-gray-400">
                            {format(parseISO(attempt.created_at), "MMM d, HH:mm")}
                          </p>
                          {attempt.status === "success" && attempt.post_url && (
                            <a
                              href={attempt.post_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[10px] font-medium text-sky-600 hover:text-sky-800 underline shrink-0"
                            >
                              Open post
                            </a>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11px] text-gray-400">No publish attempts yet.</p>
                )}
              </div>
            </div>
          )}

          <div className="card p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Test publish</h3>
              <p className="text-xs text-gray-500 mb-3">
                Dry-run to a selected account. Does not require client approval or a due schedule, and does not change content status.
              </p>
              {testPublishBlockedBySafety && testPublishSafetyErrors.length > 0 && (
                <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <p className="text-xs font-medium text-amber-900 mb-1">Test publish blocked</p>
                  <ul className="space-y-1">
                    {testPublishSafetyErrors.map((e) => (
                      <li key={e.id} className="text-[11px] text-amber-800">
                        • {e.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="space-y-2">
                <div>
                  <label className="text-[10px] text-gray-400 uppercase font-medium tracking-wide">Platform</label>
                  <select
                    className="input text-xs mt-1"
                    value={testPlatform}
                    onChange={(e) => {
                      setTestPlatform(e.target.value as Platform | "");
                      setTestAccountId("");
                    }}
                  >
                    <option value="">Select platform…</option>
                    {testPublishPlatforms.map((p) => (
                      <option key={p} value={p}>
                        {PLATFORM_CONFIG[p]?.label ?? p}
                        {!item.platforms.includes(p) ? " (account available)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] text-gray-400 uppercase font-medium tracking-wide">Account</label>
                  <select
                    className="input text-xs mt-1"
                    value={testAccountId}
                    onChange={(e) => setTestAccountId(e.target.value)}
                    disabled={!testPlatform}
                  >
                    <option value="">Select account…</option>
                    {accountsForPlatform.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.account_name} ({a.status === "connected" ? "Live" : a.status})
                        {a.platform === "telegram" && a.status === "connected"
                          ? ` · ${a.account_id}`
                          : ""}
                      </option>
                    ))}
                  </select>
                  {testPlatform && accountsForPlatform.length === 0 && (
                    <p className="text-[10px] text-amber-700 mt-1">
                      No publishing account for this platform.{" "}
                      <Link href="/publishing" className="underline">Add one in Publishing</Link>.
                    </p>
                  )}
                  {testPlatform === "telegram" && accountsForPlatform.some((a) => a.status === "connected") && (
                    <p className="text-[10px] text-sky-700 mt-1">
                      Live Telegram publish uses TELEGRAM_BOT_TOKEN — bot must be channel admin.
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  className="btn-secondary text-xs w-full"
                  disabled={
                    testPublishMutation.isPending
                    || !testPlatform
                    || !testAccountId
                    || testPublishBlockedBySafety
                  }
                  onClick={() => testPublishMutation.mutate()}
                >
                  <Send size={13} />
                  {testPublishMutation.isPending ? "Testing…" : "Test publish"}
                </button>
              </div>
            </div>

          {(item.approved_at || ["approved", "scheduled", "published", "failed", "partial_failed"].includes(item.status)) && publishBlockedBySafety && publishSafetyErrors.length > 0 && (
            <div className="card p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Live publish checks</h3>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs font-medium text-amber-900 mb-1">Safety checks failed</p>
                <ul className="space-y-1">
                  {publishSafetyErrors.map((e) => (
                    <li key={e.id} className="text-[11px] text-amber-800">
                      • {e.message}
                    </li>
                  ))}
                </ul>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                Use Publish now in the header when all checks pass.
              </p>
            </div>
          )}

          {/* ── Media Preview / Upload ── */}
          <div className="card overflow-hidden">
            {previewUrl ? (
              <>
                <input {...getInputProps()} />
                {showGallery && (
                  <div className="px-3 py-2 border-b border-gray-100 bg-gray-50 flex items-center justify-between gap-2">
                    <span className="text-[10px] font-medium text-gray-600">
                      Media {safePreviewIndex + 1} / {galleryMedia.length}
                    </span>
                  </div>
                )}
                {isVideo ? (
                  /* Video: no hover overlay — native controls stay clickable */
                  <div
                    {...getRootProps({
                      className: cn(
                        "relative",
                        isDragActive && "ring-2 ring-brand-500 ring-inset"
                      ),
                    })}
                  >
                    <MediaPreview
                      url={previewUrl}
                      fileType="video"
                      controls
                      muted={false}
                      alt="Media"
                      className="max-h-64 bg-black"
                      mediaClassName="max-h-64 w-full"
                    />
                    {isDragActive && (
                      <div className="absolute inset-0 bg-brand-600/40 flex items-center justify-center pointer-events-none">
                        <span className="text-white text-xs font-medium">Drop to replace</span>
                      </div>
                    )}
                  </div>
                ) : (
                  /* Image: hover overlay to replace */
                  <div
                    {...getRootProps({ className: "relative group" })}
                  >
                    <MediaPreview
                      url={previewUrl}
                      fileType="image"
                      alt="Media"
                      className="max-h-64 bg-black"
                      mediaClassName="max-h-64"
                    />
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => !uploading && open()}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          if (!uploading) open();
                        }
                      }}
                      className={cn(
                        "absolute inset-0 flex flex-col items-center justify-center gap-2 transition-all cursor-pointer",
                        isDragActive
                          ? "bg-brand-600/80 opacity-100"
                          : "bg-black/0 group-hover:bg-black/40 opacity-0 group-hover:opacity-100"
                      )}
                    >
                      <RefreshCw size={20} className="text-white" />
                      <span className="text-white text-xs font-medium">
                        {isDragActive ? "Drop to replace" : uploading ? "Uploading…" : "Replace media"}
                      </span>
                    </div>
                    {uploading && (
                      <div className="absolute inset-0 bg-black/60 flex flex-col items-center justify-center gap-2 pointer-events-none">
                        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        {uploadProgress > 0 && uploadProgress < 100 && (
                          <div className="w-24 h-1.5 bg-white/20 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-white rounded-full transition-all"
                              style={{ width: `${uploadProgress}%` }}
                            />
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
                {showGallery && (
                  <div className="px-3 py-2 border-t border-gray-100 bg-white flex gap-2 overflow-x-auto">
                    {galleryMedia.map((media, index) => {
                      const thumbIsVideo = media.media_type === "video";
                      return (
                        <button
                          key={`${media.media_file_id}-${media.ordinal}`}
                          type="button"
                          onClick={() => setPreviewIndex(index)}
                          className={cn(
                            "relative shrink-0 w-14 h-14 rounded-md overflow-hidden border-2 transition-colors",
                            index === safePreviewIndex
                              ? "border-brand-600 ring-1 ring-brand-200"
                              : "border-gray-200 hover:border-gray-300",
                          )}
                          title={`Media ${index + 1}`}
                        >
                          <MediaPreview
                            url={media.url}
                            fileType={thumbIsVideo ? "video" : "image"}
                            alt={`Media ${index + 1}`}
                            className="w-full h-full bg-gray-100"
                            mediaClassName="w-full h-full object-cover"
                          />
                          <span className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-[9px] text-center py-0.5">
                            {index + 1}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
                {/* File info bar */}
                <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-gray-50 border-t border-gray-100">
                  {isVideo
                    ? <Film size={13} className="text-blue-500 shrink-0" />
                    : <ImageIcon size={13} className="text-green-500 shrink-0" />
                  }
                  <span className="text-[10px] text-gray-500 truncate flex-1 min-w-[4rem]">
                    {isVideo ? "Video" : "Image"}
                    {showGallery && ` · ${safePreviewIndex + 1}/${galleryMedia.length}`}
                    {!isVideo && !showGallery && " · hover to replace"}
                    {!isVideo && showGallery && " · select thumbnail or hover to replace"}
                    {isVideo && uploading && " · uploading…"}
                  </span>
                  {isVideo && item.subtitle_url && (
                    <a
                      href={item.subtitle_url}
                      download
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-gray-600 hover:text-brand-800 px-2 py-1 rounded border border-gray-200 hover:bg-white transition-colors"
                    >
                      <Download size={11} />
                      Original
                    </a>
                  )}
                  {isVideo && item.subtitle_url_cn && (
                    <a
                      href={item.subtitle_url_cn}
                      download
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-brand-700 hover:text-brand-900 px-2 py-1 rounded border border-brand-200 hover:bg-brand-50 transition-colors"
                    >
                      <Download size={11} />
                      Download CN subtitles
                    </a>
                  )}
                  {isVideo && item.subtitle_url_ru && (
                    <a
                      href={item.subtitle_url_ru}
                      download
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-brand-700 hover:text-brand-900 px-2 py-1 rounded border border-brand-200 hover:bg-brand-50 transition-colors"
                    >
                      <Download size={11} />
                      Download RU subtitles
                    </a>
                  )}
                  {isVideo && item.subtitle_url_uz && (
                    <a
                      href={item.subtitle_url_uz}
                      download
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-brand-700 hover:text-brand-900 px-2 py-1 rounded border border-brand-200 hover:bg-brand-50 transition-colors"
                    >
                      <Download size={11} />
                      Download UZ subtitles
                    </a>
                  )}
                  {isVideo && item.subtitle_url_en && (
                    <a
                      href={item.subtitle_url_en}
                      download
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-brand-700 hover:text-brand-900 px-2 py-1 rounded border border-brand-200 hover:bg-brand-50 transition-colors"
                    >
                      <Download size={11} />
                      Download EN subtitles
                    </a>
                  )}
                  {isVideo && (
                    <button
                      type="button"
                      onClick={() => open()}
                      disabled={uploading}
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-gray-600 hover:text-brand-700 disabled:opacity-50 px-2 py-1 rounded border border-gray-200 hover:border-brand-300 hover:bg-white transition-colors"
                    >
                      <RefreshCw size={11} className={uploading ? "animate-spin" : ""} />
                      Replace
                    </button>
                  )}
                  {isVideo && uploading && uploadProgress > 0 && uploadProgress < 100 && (
                    <div className="w-12 h-1 bg-gray-200 rounded-full overflow-hidden shrink-0">
                      <div
                        className="h-full bg-brand-500 rounded-full transition-all"
                        style={{ width: `${uploadProgress}%` }}
                      />
                    </div>
                  )}
                </div>
                {isVideo && (
                  <div className="flex flex-wrap items-center gap-2 px-3 py-2.5 bg-white border-t border-gray-100">
                    <Clapperboard size={13} className="text-purple-500 shrink-0" />
                    <label className="text-[10px] text-gray-500 shrink-0">Subtitle language</label>
                    <select
                      className="input text-[10px] py-1 w-auto min-w-[10rem]"
                      value={burnLang}
                      onChange={(e) => setBurnLang(e.target.value as SubtitleBurnLang)}
                      disabled={burnSubtitlesMutation.isPending}
                    >
                      {BURN_LANG_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => burnSubtitlesMutation.mutate()}
                      disabled={
                        !subtitleUrlForBurn
                        || burnSubtitlesMutation.isPending
                      }
                      title={
                        !subtitleUrlForBurn
                          ? "Generate translated subtitles first"
                          : undefined
                      }
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-white bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:hover:bg-purple-600 px-2.5 py-1 rounded transition-colors"
                    >
                      <RefreshCw
                        size={11}
                        className={burnSubtitlesMutation.isPending ? "animate-spin" : ""}
                      />
                      {burnSubtitlesMutation.isPending
                        ? "Generating…"
                        : "Generate subtitled video"}
                    </button>
                    {subtitledVideoUrlForBurn && (
                      <a
                        href={subtitledVideoUrlForBurn}
                        download
                        className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-purple-700 hover:text-purple-900 px-2 py-1 rounded border border-purple-200 hover:bg-purple-50 transition-colors"
                      >
                        <Download size={11} />
                        Download subtitled video
                      </a>
                    )}
                  </div>
                )}
                {isVideo && (
                  <div className="flex flex-wrap items-center gap-2 px-3 py-2.5 bg-white border-t border-gray-100">
                    <Mic size={13} className="text-amber-600 shrink-0" />
                    <label className="text-[10px] text-gray-500 shrink-0">Voiceover</label>
                    <select
                      className="input text-[10px] py-1 w-auto min-w-[9rem]"
                      value={voiceLang}
                      onChange={(e) => setVoiceLang(e.target.value as VoiceoverLang)}
                      disabled={voiceoverMutation.isPending}
                    >
                      {VOICE_LANG_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => voiceoverMutation.mutate("fitted")}
                      disabled={!subtitleUrlForVoice || voiceoverMutation.isPending}
                      title={
                        !subtitleUrlForVoice
                          ? "Generate translated subtitles for this language first"
                          : "Short script — fits original video duration"
                      }
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-white bg-amber-600 hover:bg-amber-700 disabled:opacity-50 disabled:hover:bg-amber-600 px-2.5 py-1 rounded transition-colors"
                    >
                      <RefreshCw
                        size={11}
                        className={
                          voiceoverMutation.isPending && voiceoverMode === "fitted"
                            ? "animate-spin"
                            : ""
                        }
                      />
                      {voiceoverMutation.isPending && voiceoverMode === "fitted"
                        ? "Generating…"
                        : "Generate fitted voiceover"}
                    </button>
                    <button
                      type="button"
                      onClick={() => voiceoverMutation.mutate("extended")}
                      disabled={!subtitleUrlForVoice || voiceoverMutation.isPending}
                      title={
                        !subtitleUrlForVoice
                          ? "Generate translated subtitles for this language first"
                          : "More detail — may extend video duration"
                      }
                      className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-amber-800 bg-amber-100 hover:bg-amber-200 disabled:opacity-50 disabled:hover:bg-amber-100 px-2.5 py-1 rounded border border-amber-300 transition-colors"
                    >
                      <RefreshCw
                        size={11}
                        className={
                          voiceoverMutation.isPending && voiceoverMode === "extended"
                            ? "animate-spin"
                            : ""
                        }
                      />
                      {voiceoverMutation.isPending && voiceoverMode === "extended"
                        ? "Generating…"
                        : "Generate extended voiceover"}
                    </button>
                    {dubbedVideoUrlForVoice && (
                      <a
                        href={dubbedVideoUrlForVoice}
                        download
                        className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-amber-800 hover:text-amber-950 px-2 py-1 rounded border border-amber-200 hover:bg-amber-50 transition-colors"
                      >
                        <Download size={11} />
                        Download fitted dub
                      </a>
                    )}
                    {dubbedExtendedVideoUrlForVoice && (
                      <a
                        href={dubbedExtendedVideoUrlForVoice}
                        download
                        className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-amber-900 hover:text-amber-950 px-2 py-1 rounded border border-amber-300 hover:bg-amber-50 transition-colors"
                      >
                        <Download size={11} />
                        Download extended dub
                      </a>
                    )}
                  </div>
                )}
                {isVideo && (
                  <div className="flex flex-col gap-2 px-3 py-2.5 bg-white border-t border-gray-100">
                    <div className="flex flex-wrap items-center gap-2">
                      <Package size={13} className="text-emerald-600 shrink-0" />
                      <label className="text-[10px] text-gray-500 shrink-0">Final export</label>
                      {burnLang !== "cn" && (
                        <select
                          className="input text-[10px] py-1 w-auto min-w-[8rem]"
                          value={finalExportMode}
                          onChange={(e) =>
                            setFinalExportMode(e.target.value as VoiceoverMode)
                          }
                          disabled={finalVideoMutation.isPending}
                        >
                          <option value="fitted">Mode: Fitted</option>
                          <option value="extended">Mode: Extended</option>
                        </select>
                      )}
                      <button
                        type="button"
                        onClick={() => finalVideoMutation.mutate()}
                        disabled={!subtitleUrlForFinal || finalVideoMutation.isPending}
                        title={
                          !subtitleUrlForFinal
                            ? "Generate translated subtitles for this language first"
                            : undefined
                        }
                        className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-white bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:hover:bg-emerald-600 px-2.5 py-1 rounded transition-colors"
                      >
                        <RefreshCw
                          size={11}
                          className={finalVideoMutation.isPending ? "animate-spin" : ""}
                        />
                        {finalVideoMutation.isPending ? "Generating…" : "Generate final video"}
                      </button>
                      {finalVideoUrlForExport && (
                        <a
                          href={finalVideoUrlForExport}
                          download
                          className="shrink-0 inline-flex items-center gap-1 text-[10px] font-medium text-emerald-800 hover:text-emerald-950 px-2 py-1 rounded border border-emerald-200 hover:bg-emerald-50 transition-colors"
                        >
                          <Download size={11} />
                          Download final video
                        </a>
                      )}
                    </div>
                    <div className="text-[10px] text-gray-600 pl-5">
                      Subtitle: {finalExportSummary.subtitle}
                      {" · "}
                      Voice: {finalExportSummary.voice}
                      {" · "}
                      Mode: {finalExportSummary.mode}
                    </div>
                  </div>
                )}
              </>
            ) : (
              /* No media — upload zone */
              <div
                {...getRootProps()}
                className={cn(
                  "p-8 text-center cursor-pointer transition-all border-2 border-dashed border-gray-200 rounded-xl",
                  isDragActive ? "border-brand-400 bg-brand-50" : "hover:border-gray-300 hover:bg-gray-50"
                )}
              >
                <input {...getInputProps()} />
                {uploading ? (
                  <div className="flex flex-col items-center gap-2">
                    <div className="w-7 h-7 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
                    <p className="text-xs text-gray-500">Uploading…</p>
                  </div>
                ) : (
                  <>
                    <Upload size={22} className="mx-auto text-gray-300 mb-2" />
                    <p className="text-xs text-gray-500 font-medium">
                      {isDragActive ? "Drop here" : "Upload media"}
                    </p>
                    <p className="text-[10px] text-gray-400 mt-1">
                      JPG · PNG · WebP · MP4 · MOV · WebM
                    </p>
                  </>
                )}
              </div>
            )}

            {uploadError && (
              <div className="flex items-start gap-2 m-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg">
                <AlertCircle size={13} className="text-red-500 shrink-0 mt-0.5" />
                <p className="text-[11px] text-red-600">{uploadError}</p>
                <button onClick={() => setUploadError(null)} className="ml-auto text-red-400"><X size={12} /></button>
              </div>
            )}

            {(!previewUrl || item.media_request_sent_at) && (
              <div className="border-t border-gray-100 p-4 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-gray-900 flex items-center gap-1.5">
                      <MessageSquare size={14} className="text-sky-600" />
                      Media Request Assistant
                    </p>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      Ask the client to send materials via their Telegram intake group.
                    </p>
                  </div>
                  {!previewUrl && !item.media_request_sent_at && (
                    <button
                      type="button"
                      className="btn-secondary text-xs shrink-0"
                      disabled={mediaRequestMutation.isPending}
                      onClick={() => mediaRequestMutation.mutate()}
                    >
                      {mediaRequestMutation.isPending ? "Sending…" : "Request media from client"}
                    </button>
                  )}
                </div>

                {item.media_request_sent_at && (
                  <div className="rounded-lg border border-sky-100 bg-sky-50 px-3 py-2.5 text-xs text-sky-900 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium capitalize">
                        Status: {item.media_request_status ?? "requested"}
                      </span>
                      {item.media_request_format && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white border border-sky-200 capitalize">
                          {item.media_request_format}
                        </span>
                      )}
                      <span className="text-[10px] text-sky-700">
                        Sent {format(parseISO(item.media_request_sent_at), "MMM d, yyyy HH:mm")}
                      </span>
                    </div>
                    {item.media_request_message && (
                      <p className="text-[11px] text-sky-800 whitespace-pre-wrap border-t border-sky-100 pt-2">
                        {item.media_request_message}
                      </p>
                    )}
                    {!previewUrl && item.media_request_status === "requested" && (
                      <button
                        type="button"
                        className="text-[11px] text-sky-700 hover:text-sky-900 underline"
                        disabled={mediaRequestMutation.isPending}
                        onClick={() => mediaRequestMutation.mutate()}
                      >
                        {mediaRequestMutation.isPending ? "Sending…" : "Send reminder"}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {item.source === "telegram_group" && telegramInstructionHistory.length > 0 && (
            <div className="card p-4 space-y-3">
              <p className="text-sm font-medium text-gray-900">Telegram instructions</p>
              <p className="text-[11px] text-gray-500">
                Operator messages from the group — not used as publish captions unless applied to source text.
              </p>
              <ol className="space-y-3 max-h-64 overflow-y-auto">
                {telegramInstructionHistory.slice().reverse().map((entry, i) => {
                  const status = instructionStatusLabel(entry);
                  return (
                    <li key={i} className="relative pl-4 border-l-2 border-violet-200">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span className="text-[10px] text-gray-500">
                          {entry.at ? format(parseISO(entry.at), "MMM d, yyyy HH:mm") : "—"}
                        </span>
                        <span className="text-[10px] text-gray-600">{entry.from || "Admin"}</span>
                        <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium capitalize", instructionStatusStyle(status))}>
                          {status}
                        </span>
                      </div>
                      <p className="text-xs text-gray-800">&ldquo;{entry.instruction}&rdquo;</p>
                      {entry.summary && entry.summary !== entry.instruction && (
                        <p className="text-[11px] text-gray-500 mt-1">{entry.summary}</p>
                      )}
                    </li>
                  );
                })}
              </ol>
            </div>
          )}

          <div className="card p-4 space-y-3">
            <div className="flex items-center gap-1.5 text-sm font-medium text-gray-900">
              <Brain size={14} className="text-indigo-600" />
              Context AI
            </div>
            <div className="text-xs space-y-1.5 text-gray-600">
              <p>
                <span className="font-medium text-gray-700">Detected category:</span>{" "}
                {item.context_ai_detected
                  ? CONTEXT_AI_CATEGORY_LABELS[item.context_ai_detected] ?? item.context_ai_detected
                  : "—"}
              </p>
              <p>
                <span className="font-medium text-gray-700">Confidence:</span>{" "}
                {contextConfidence != null ? contextConfidence.toFixed(2) : "—"}
              </p>
              {merged.context_ai_override && (
                <p className="text-indigo-700 font-medium">
                  [Context AI override]: {merged.context_ai_override}
                </p>
              )}
            </div>
            <div>
              <label className="label text-xs">Override category</label>
              <select
                className="input text-xs"
                value={merged.context_ai_override ?? ""}
                onChange={(e) =>
                  setEdits((prev) => ({
                    ...prev,
                    context_ai_override: e.target.value || null,
                  }))
                }
              >
                <option value="">— Use detected category —</option>
                {CONTEXT_AI_CATEGORIES.map((cat) => (
                  <option key={cat} value={cat}>
                    {CONTEXT_AI_CATEGORY_LABELS[cat] ?? cat}
                  </option>
                ))}
              </select>
              <p className="text-[10px] text-gray-400 mt-1">
                Caption generation uses override when set
                {effectiveContextCategory ? ` (${effectiveContextCategory})` : ""}.
              </p>
            </div>
          </div>

          {/* AI Generation */}
          <div className="card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-sm font-medium text-gray-900">
                <Sparkles size={14} className="text-brand-600" />
                AI Generation
              </div>
              {item.caption_short_ru && (
                <span className="text-[10px] text-green-600 font-medium bg-green-50 px-1.5 py-0.5 rounded">
                  ✓ Captions ready
                </span>
              )}
            </div>

            {/* Source text */}
            <div>
              <label className="label text-xs">
                Source text / product info
                <span className="text-gray-400 font-normal ml-1">(optional)</span>
                {(item.source === "telegram" || item.source === "telegram_group") && item.internal_notes && !item.internal_notes.includes("[OCR]:") && !item.internal_notes.includes("[Transcript]:") && (
                  <span className="ml-2 text-[10px] bg-sky-100 text-sky-700 px-1.5 py-0.5 rounded font-medium">
                    {item.source === "telegram_group" ? "👥 Group message" : "📩 Telegram caption"}
                  </span>
                )}
                {(item.source === "telegram" || item.source === "telegram_group") && item.internal_notes?.includes("[OCR]:") && !item.internal_notes.includes("[Transcript]:") && (
                  <span className="ml-2 text-[10px] bg-sky-100 text-sky-700 px-1.5 py-0.5 rounded font-medium">
                    {item.source === "telegram_group" ? "👥 Group + 🔍 OCR" : "📩 Telegram + 🔍 OCR"}
                  </span>
                )}
                {item.internal_notes?.includes("[Transcript]:") && !item.internal_notes.includes("[OCR]:") && (
                  <span className="ml-2 text-[10px] bg-violet-100 text-violet-700 px-1.5 py-0.5 rounded font-medium">
                    🎤 Transcript detected
                  </span>
                )}
                {item.internal_notes?.includes("[Transcript]:") && item.internal_notes.includes("[OCR]:") && (
                  <span className="ml-2 text-[10px] bg-violet-100 text-violet-700 px-1.5 py-0.5 rounded font-medium">
                    🎤 Transcript + 🔍 OCR
                  </span>
                )}
                {item.source !== "telegram" && item.source !== "telegram_group" && item.internal_notes && !item.internal_notes.includes("[Transcript]:") && (
                  <span className="ml-2 text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">
                    🔍 OCR detected
                  </span>
                )}
              </label>
              <textarea
                className="input text-xs resize-none"
                rows={3}
                value={sourceText}
                onChange={(e) => setSourceText(e.target.value)}
                placeholder={
                  (sourceLang ?? client?.source_language) === "zh"
                    ? "粘贴中文描述或产品信息…"
                    : "Paste client's text, product info, or post idea…"
                }
                disabled={generateMutation.isPending}
              />
            </div>

            {/* Source language selector */}
            <div>
              <label className="label text-xs">
                Source language
                {client?.source_language && !sourceLang && (
                  <span className="text-gray-400 font-normal ml-1">
                    (default: {client.source_language})
                  </span>
                )}
              </label>
              <div className="grid grid-cols-3 gap-1">
                {[
                  { v: "zh", l: "🇨🇳 ZH" },
                  { v: "ru", l: "🇷🇺 RU" },
                  { v: "uz", l: "🇺🇿 UZ" },
                  { v: "en", l: "🇬🇧 EN" },
                  { v: "ko", l: "🇰🇷 KO" },
                  { v: "ja", l: "🇯🇵 JA" },
                ].map(({ v, l }) => {
                  const active = (sourceLang ?? client?.source_language) === v;
                  return (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setSourceLang(v)}
                      disabled={generateMutation.isPending}
                      className={cn(
                        "text-xs py-1 rounded-lg border font-medium transition-all",
                        active
                          ? "border-brand-500 bg-brand-50 text-brand-700"
                          : "border-gray-200 text-gray-500 hover:border-gray-300"
                      )}
                    >
                      {l}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Context hint */}
            <div>
              <label className="label text-xs">Context hint</label>
              <input
                className="input text-xs"
                value={contextHint}
                onChange={(e) => setContextHint(e.target.value)}
                placeholder="e.g. Ramadan promotion, grand opening, new product…"
                disabled={generateMutation.isPending}
              />
            </div>

            {/* Error display */}
            {generateError && (
              <div className="flex items-start gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg">
                <AlertCircle size={13} className="text-red-500 shrink-0 mt-0.5" />
                <p className="text-[11px] text-red-600 flex-1">{generateError}</p>
                <button onClick={() => setGenerateError(null)} className="text-red-400 shrink-0">
                  <X size={12} />
                </button>
              </div>
            )}

            {/* Generate button */}
            <button
              className={cn(
                "btn-primary w-full justify-center text-xs",
                justGenerated && "bg-green-600 hover:bg-green-700"
              )}
              onClick={() => {
                setGenerateError(null);
                generateMutation.mutate();
              }}
              disabled={generateMutation.isPending}
            >
              <Sparkles size={13} />
              {generateMutation.isPending
                ? "Generating…"
                : justGenerated
                ? "Generated ✓"
                : item.caption_short_ru
                ? "Regenerate"
                : "Generate content"
              }
            </button>

            {generateMutation.isPending && (
              <p className="text-[10px] text-gray-400 text-center">
                Translating &amp; localizing for Uzbekistan market…
              </p>
            )}
          </div>

          {/* Client info */}
          {client && (
            <div className="card p-4 text-xs space-y-1.5 text-gray-500">
              <p><span className="font-medium text-gray-700">Client:</span> {client.company_name}</p>
              <p><span className="font-medium text-gray-700">Category:</span> {client.business_category}</p>
              <p><span className="font-medium text-gray-700">Style:</span> {client.content_style}</p>
              <p><span className="font-medium text-gray-700">Source lang:</span> {client.source_language}</p>
              <p><span className="font-medium text-gray-700">Created:</span> {format(parseISO(item.created_at), "MMM d, yyyy")}</p>
            </div>
          )}
        </div>

        {/* Right col: captions */}
        <div className="space-y-4">
          <TelegramIngestionPanel
            item={item}
            statusSaving={statusMutation.isPending}
            onStatusChange={(status) => statusMutation.mutate(status)}
          />
          <CaptionSection lang="🇷🇺 Russian" short={field("caption_short_ru")} long={field("caption_long_ru")} hasContent={!!merged.caption_short_ru} />
          <CaptionSection lang="🇺🇿 Uzbek"  short={field("caption_short_uz")} long={field("caption_long_uz")} hasContent={!!merged.caption_short_uz} />
          <CaptionSection lang="🇬🇧 English" short={field("caption_short_en")} long={field("caption_long_en")} hasContent={!!merged.caption_short_en} />

          <div className="card p-4">
            <label className="label text-xs">Hashtags</label>
            <input
              className="input text-xs font-mono"
              {...field("hashtags")}
              placeholder="#hashtag1 #hashtag2 …"
            />
          </div>

          <div className="card p-4">
            <label className="label text-xs">
              Internal notes
              {item.internal_notes?.includes("[OCR]:") && !item.internal_notes.includes("[Transcript]:") && (
                <span className="ml-2 text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">
                  🔍 OCR text included
                </span>
              )}
              {item.internal_notes?.includes("[Transcript]:") && (
                <span className="ml-2 text-[10px] bg-violet-100 text-violet-700 px-1.5 py-0.5 rounded font-medium">
                  🎤 Transcript included
                </span>
              )}
            </label>
            <textarea
              className="input text-xs resize-none"
              rows={2}
              {...field("internal_notes")}
              placeholder="Notes for the operator…"
            />
          </div>
        </div>
      </div>

      {showSchedule && (
        <ScheduleModal
          contentItemId={id}
          currentPlatforms={item.platforms}
          existingScheduledForUtc={item.scheduled_for}
          onClose={() => setShowSchedule(false)}
          onSaved={() => {
            setShowSchedule(false);
            qc.invalidateQueries({ queryKey: ["content", id] });
            qc.invalidateQueries({ queryKey: ["content-readiness", id] });
            qc.invalidateQueries({ queryKey: ["scheduled-publish-debug"] });
          }}
        />
      )}
    </div>
  );
}

function CaptionSection({
  lang, short, long, hasContent,
}: {
  lang: string;
  short: { value: string; onChange: any };
  long: { value: string; onChange: any };
  hasContent?: boolean;
}) {
  return (
    <div className={cn(
      "card p-4 space-y-3 transition-all",
      hasContent && "ring-1 ring-green-200"
    )}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-700">{lang}</p>
        {hasContent && (
          <span className="text-[10px] text-green-600 font-medium">✓ Generated</span>
        )}
      </div>
      <div>
        <label className="label text-xs">Short caption</label>
        <textarea
          className="input text-sm resize-none"
          rows={2}
          {...short}
          placeholder="Short caption (≤150 chars)…"
        />
        {short.value && (
          <p className={cn("text-[10px] mt-0.5", short.value.length > 150 ? "text-red-500" : "text-gray-400")}>
            {short.value.length}/150 chars
          </p>
        )}
      </div>
      <div>
        <label className="label text-xs">Long caption</label>
        <textarea
          className="input text-sm resize-none"
          rows={4}
          {...long}
          placeholder="Full post body…"
        />
        {long.value && (
          <p className="text-[10px] mt-0.5 text-gray-400">{long.value.length} chars</p>
        )}
      </div>
    </div>
  );
}
