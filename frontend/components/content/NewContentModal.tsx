"use client";
import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { contentApi, mediaApi, Client, MediaFile, Platform, normalizeList } from "@/lib/api";
import { X, Upload, Film, ImageIcon, AlertCircle, CheckCircle2 } from "lucide-react";
import toast from "react-hot-toast";
import { useDropzone } from "react-dropzone";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { MediaPreview } from "@/components/ui/MediaPreview";

interface Props {
  clients: Client[];
  onClose: () => void;
  onSaved: () => void;
}

const ALL_PLATFORMS: Platform[] = ["instagram", "facebook", "tiktok", "telegram", "linkedin"];

const ACCEPTED_TYPES = {
  "image/jpeg": [".jpg", ".jpeg"],
  "image/png": [".png"],
  "image/webp": [".webp"],
  "video/mp4": [".mp4"],
  "video/quicktime": [".mov"],
  "video/webm": [".webm"],
};

const MAX_IMAGE_MB = 20;
const MAX_VIDEO_MB = 200;

function isVideo(mime: string) {
  return mime.startsWith("video/");
}

function formatMB(bytes: number) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function NewContentModal({ clients, onClose, onSaved }: Props) {
  const clientOptions = normalizeList<Client>(clients);
  const [clientId, setClientId] = useState(clientOptions[0]?.id ?? "");
  const [platforms, setPlatforms] = useState<Platform[]>(["instagram"]);
  const [notes, setNotes] = useState("");
  const [ocrSource, setOcrSource] = useState(false);  // true when notes came from OCR
  const [uploadedMedia, setUploadedMedia] = useState<MediaFile | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [fileError, setFileError] = useState<string | null>(null);

  const togglePlatform = (p: Platform) =>
    setPlatforms((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]);

  const validateFile = (file: File): string | null => {
    const mime = file.type;
    const isImg = mime.startsWith("image/");
    const isVid = mime.startsWith("video/");
    if (!isImg && !isVid) {
      return `Unsupported type "${mime}". Use JPG, PNG, WebP, MP4, MOV, or WebM.`;
    }
    const maxBytes = isVid ? MAX_VIDEO_MB * 1024 * 1024 : MAX_IMAGE_MB * 1024 * 1024;
    if (file.size > maxBytes) {
      return `File too large (${formatMB(file.size)}). Max for ${isVid ? "videos" : "images"}: ${isVid ? MAX_VIDEO_MB : MAX_IMAGE_MB} MB.`;
    }
    return null;
  };

  const onDrop = useCallback(async (accepted: File[], rejected: any[]) => {
    setFileError(null);

    if (rejected.length > 0) {
      const err = rejected[0]?.errors?.[0];
      if (err?.code === "file-too-large") {
        setFileError(`File too large. Max: images ${MAX_IMAGE_MB} MB, videos ${MAX_VIDEO_MB} MB.`);
      } else {
        setFileError("Unsupported file type. Use JPG, PNG, WebP, MP4, MOV, or WebM.");
      }
      return;
    }

    if (!clientId) { setFileError("Select a client first."); return; }
    if (accepted.length === 0) return;

    const file = accepted[0];
    const validationError = validateFile(file);
    if (validationError) { setFileError(validationError); return; }

    setUploading(true);
    setUploadProgress(0);

    try {
      const res = await mediaApi.upload(clientId, file, (pct) => {
        setUploadProgress(pct);
      });
      setUploadedMedia(res.data);
      setUploadProgress(100);
      // Pre-fill notes with OCR-extracted text if the image contained text
      if (res.data.ocr_text) {
        setNotes(res.data.ocr_text);
        setOcrSource(true);
      }
      toast.success("Media uploaded ✓");
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        (err?.response?.status === 413 ? `File too large. Max: images ${MAX_IMAGE_MB} MB, videos ${MAX_VIDEO_MB} MB.` : "Upload failed. Please try again.");
      setFileError(msg);
      toast.error(msg);
    } finally {
      setUploading(false);
    }
  }, [clientId]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxFiles: 1,
    maxSize: MAX_VIDEO_MB * 1024 * 1024,
    disabled: !clientId || uploading,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      contentApi.create({
        client_id: clientId,
        media_file_id: uploadedMedia?.id,
        platforms,
        internal_notes: notes || undefined,
      }),
    onSuccess: () => { toast.success("Content item created"); onSaved(); },
    onError: () => toast.error("Failed to create content item"),
  });

  const removeMedia = () => {
    setUploadedMedia(null);
    setFileError(null);
    setUploadProgress(0);
    setOcrSource(false);
  };

  return (
    <div
      data-app-modal
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm p-4"
    >
      <div className="card w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <h2 className="text-base font-semibold text-gray-900">New content item</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="overflow-y-auto p-6 space-y-5">
          {/* Client */}
          <div>
            <label className="label">Client *</label>
            <select
              className="input"
              value={clientId}
              onChange={(e) => { setClientId(e.target.value); removeMedia(); }}
            >
              {clientOptions.length === 0 && <option value="">No clients yet</option>}
              {clientOptions.map((c) => (
                <option key={c.id} value={c.id}>{c.company_name}</option>
              ))}
            </select>
          </div>

          {/* Platforms */}
          <div>
            <label className="label">Platforms</label>
            <div className="grid grid-cols-3 gap-2 mt-1">
              {ALL_PLATFORMS.map((p) => {
                const cfg = PLATFORM_CONFIG[p];
                const on = platforms.includes(p);
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => togglePlatform(p)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-all",
                      on
                        ? "border-brand-500 bg-brand-50 text-brand-700"
                        : "border-gray-200 text-gray-500 hover:border-gray-300"
                    )}
                  >
                    <span className={cn("text-[10px] font-bold px-1 py-0.5 rounded", cfg.color)}>
                      {cfg.icon}
                    </span>
                    {cfg.label}
                    {on && <span className="ml-auto text-brand-500 text-[10px]">✓</span>}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Media upload */}
          <div>
            <label className="label">Media</label>
            <p className="text-[10px] text-gray-400 mb-2">
              Images: JPG, PNG, WebP (max {MAX_IMAGE_MB} MB) · Videos: MP4, MOV, WebM (max {MAX_VIDEO_MB} MB)
            </p>

            {uploadedMedia ? (
              /* Preview after upload */
              <div className="rounded-xl border border-gray-200 overflow-hidden bg-gray-50">
                <div className="max-h-48 overflow-hidden">
                  <MediaPreview
                    url={uploadedMedia.url}
                    fileType={uploadedMedia.file_type}
                    controls={uploadedMedia.file_type === "video"}
                    muted={uploadedMedia.file_type !== "video"}
                    alt={uploadedMedia.original_filename}
                    className="max-h-48"
                  />
                </div>
                <div className="flex items-center gap-2 px-3 py-2">
                  {uploadedMedia.file_type === "video"
                    ? <Film size={14} className="text-blue-500 shrink-0" />
                    : <ImageIcon size={14} className="text-green-500 shrink-0" />
                  }
                  <span className="text-xs text-gray-600 flex-1 truncate">{uploadedMedia.original_filename}</span>
                  <span className="text-[10px] text-gray-400">{formatMB(uploadedMedia.file_size)}</span>
                  <CheckCircle2 size={14} className="text-green-500 shrink-0" />
                  <button
                    onClick={removeMedia}
                    className="text-gray-400 hover:text-red-500 transition-colors ml-1"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            ) : (
              /* Drop zone */
              <div
                {...getRootProps()}
                className={cn(
                  "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
                  isDragActive
                    ? "border-brand-400 bg-brand-50 scale-[1.01]"
                    : "border-gray-200 hover:border-gray-300 hover:bg-gray-50",
                  (!clientId || uploading) && "opacity-50 cursor-not-allowed pointer-events-none"
                )}
              >
                <input {...getInputProps()} />
                {uploading ? (
                  <div className="space-y-3">
                    <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto" />
                    <p className="text-xs text-gray-500">Uploading…</p>
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-brand-500 rounded-full transition-all duration-300"
                        style={{ width: `${uploadProgress}%` }}
                      />
                    </div>
                  </div>
                ) : (
                  <>
                    <Upload size={24} className="mx-auto text-gray-300 mb-3" />
                    <p className="text-sm text-gray-500 font-medium">
                      {isDragActive ? "Drop to upload" : "Drop file here or click to browse"}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      {!clientId ? "Select a client first" : "Images & videos accepted"}
                    </p>
                  </>
                )}
              </div>
            )}

            {/* Error message */}
            {fileError && (
              <div className="flex items-start gap-2 mt-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg">
                <AlertCircle size={14} className="text-red-500 shrink-0 mt-0.5" />
                <p className="text-xs text-red-600">{fileError}</p>
              </div>
            )}
          </div>

          {/* Internal notes — pre-filled from OCR if image contained text */}
          <div>
            <label className="label">
              Internal notes (optional)
              {ocrSource && (
                <span className="ml-2 text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium">
                  🔍 OCR extracted
                </span>
              )}
            </label>
            <textarea
              className="input resize-none"
              rows={2}
              value={notes}
              onChange={(e) => { setNotes(e.target.value); setOcrSource(false); }}
              placeholder="Context for this content piece…"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100 shrink-0">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            onClick={() => createMutation.mutate()}
            disabled={!clientId || platforms.length === 0 || uploading || createMutation.isPending}
          >
            {createMutation.isPending ? "Creating…" : "Create as Draft"}
          </button>
        </div>
      </div>
    </div>
  );
}
