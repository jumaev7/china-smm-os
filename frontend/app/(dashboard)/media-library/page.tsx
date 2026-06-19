"use client";

import { useRef, useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ImageIcon,
  LayoutGrid,
  List,
  Plus,
  Search,
  Upload,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  campaignsApi,
  clientsApi,
  Client,
  mediaLibraryApi,
  MediaAsset,
  MEDIA_LIBRARY_FILE_TYPES,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

function AssetPreview({ asset }: { asset: MediaAsset }) {
  const src = asset.thumbnail_url || asset.url;
  if (src && asset.file_type !== "document") {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img src={src} alt="" className="w-full h-full object-cover" />
    );
  }
  return (
    <div className="w-full h-full flex items-center justify-center bg-gray-100 text-gray-400 text-xs uppercase">
      {asset.file_type}
    </div>
  );
}

function AssetGridCard({ asset }: { asset: MediaAsset }) {
  return (
    <Link
      href={`/media-library/${asset.id}`}
      className="card overflow-hidden hover:ring-1 hover:ring-brand-200 transition-shadow"
    >
      <div className="aspect-square bg-gray-50">
        <AssetPreview asset={asset} />
      </div>
      <div className="p-3 space-y-1">
        <p className="text-sm font-medium text-gray-900 truncate">{asset.title}</p>
        <p className="text-[11px] text-gray-500 truncate">{asset.client_name}</p>
        <div className="flex items-center justify-between text-[10px] text-gray-400">
          <span className="capitalize">{asset.file_type}</span>
          <span>{asset.usage_count} uses</span>
        </div>
      </div>
    </Link>
  );
}

function AssetTableRow({ asset }: { asset: MediaAsset }) {
  return (
    <Link
      href={`/media-library/${asset.id}`}
      className="grid grid-cols-[48px_1fr_1fr_0.8fr_0.6fr_1fr_0.5fr] gap-3 items-center px-4 py-3 hover:bg-gray-50 border-b border-gray-100 text-sm"
    >
      <div className="w-12 h-12 rounded overflow-hidden bg-gray-100 shrink-0">
        <AssetPreview asset={asset} />
      </div>
      <p className="font-medium text-gray-900 truncate">{asset.title}</p>
      <p className="text-gray-600 truncate hidden md:block">{asset.client_name ?? "—"}</p>
      <p className="text-gray-600 truncate hidden lg:block">{asset.campaign_name ?? "—"}</p>
      <p className="text-gray-600 capitalize hidden sm:block">{asset.file_type}</p>
      <p className="text-gray-500 truncate hidden xl:block">
        {(asset.tags_json ?? []).slice(0, 3).join(", ") || "—"}
      </p>
      <p className="text-gray-900 tabular-nums text-right">{asset.usage_count}</p>
    </Link>
  );
}

export default function MediaLibraryPage() {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const fileRef = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<"grid" | "table">("grid");
  const [search, setSearch] = useState("");
  const [clientId, setClientId] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [fileType, setFileType] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [uploadClientId, setUploadClientId] = useState("");
  const [uploadCampaignId, setUploadCampaignId] = useState("");
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadType, setUploadType] = useState("");
  const [uploadTags, setUploadTags] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  useEffect(() => {
    const c = searchParams.get("campaign");
    if (c) setCampaignId(c);
  }, [searchParams]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: campaigns } = useQuery({
    queryKey: ["campaigns-filter", clientId],
    queryFn: () =>
      campaignsApi.list({ client_id: clientId || undefined, limit: 200 }).then((r) => r.data),
    enabled: !!clientId,
  });

  const { data: uploadCampaigns } = useQuery({
    queryKey: ["campaigns-upload", uploadClientId],
    queryFn: () =>
      campaignsApi.list({ client_id: uploadClientId, limit: 200 }).then((r) => r.data),
    enabled: !!uploadClientId,
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["media-library", search, clientId, campaignId, fileType],
    queryFn: () =>
      mediaLibraryApi
        .list({
          search: search || undefined,
          client_id: clientId || undefined,
          campaign_id: campaignId || undefined,
          file_type: fileType || undefined,
          limit: 200,
        })
        .then((r) => r.data),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("client_id", uploadClientId);
      fd.append("file", file);
      if (uploadTitle.trim()) fd.append("title", uploadTitle.trim());
      if (uploadCampaignId) fd.append("campaign_id", uploadCampaignId);
      if (uploadType) fd.append("file_type", uploadType);
      if (uploadTags.trim()) fd.append("tags", uploadTags.trim());
      return mediaLibraryApi.upload(fd).then((r) => r.data);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["media-library"] });
      setShowUpload(false);
      setUploadTitle("");
      setUploadTags("");
      setSelectedFile(null);
      if (fileRef.current) fileRef.current.value = "";
      toast.success("Media uploaded");
    },
    onError: (err: Error) => toast.error(err.message || "Upload failed"),
  });

  const items = normalizeList<MediaAsset>(data);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <ImageIcon size={22} className="text-indigo-600" />
            Media Library
          </h1>
          <p className="text-sm text-gray-500 mt-1">Centralized media repository per client</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            <button
              type="button"
              className={cn("p-2", view === "grid" ? "bg-brand-50 text-brand-800" : "text-gray-500")}
              onClick={() => setView("grid")}
            >
              <LayoutGrid size={16} />
            </button>
            <button
              type="button"
              className={cn("p-2", view === "table" ? "bg-brand-50 text-brand-800" : "text-gray-500")}
              onClick={() => setView("table")}
            >
              <List size={16} />
            </button>
          </div>
          <button type="button" className="btn-primary text-sm flex items-center gap-1.5" onClick={() => setShowUpload(!showUpload)}>
            <Plus size={14} />
            Upload
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="input pl-9 w-full"
            placeholder="Search media…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="input text-sm min-w-[140px]" value={clientId} onChange={(e) => { setClientId(e.target.value); setCampaignId(""); }}>
          <option value="">All clients</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
        <select className="input text-sm min-w-[140px]" value={campaignId} onChange={(e) => setCampaignId(e.target.value)} disabled={!clientId}>
          <option value="">All campaigns</option>
          {normalizeList(campaigns).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select className="input text-sm min-w-[120px]" value={fileType} onChange={(e) => setFileType(e.target.value)}>
          <option value="">All types</option>
          {MEDIA_LIBRARY_FILE_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {showUpload && (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Upload size={14} />
            Upload to library
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
            <select className="input text-sm" value={uploadClientId} onChange={(e) => { setUploadClientId(e.target.value); setUploadCampaignId(""); }}>
              <option value="">Client *</option>
              {clientOptions.map((c) => (
                <option key={c.id} value={c.id}>{c.company_name}</option>
              ))}
            </select>
            <select className="input text-sm" value={uploadCampaignId} onChange={(e) => setUploadCampaignId(e.target.value)} disabled={!uploadClientId}>
              <option value="">Campaign (optional)</option>
              {normalizeList(uploadCampaigns).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <input className="input text-sm" placeholder="Title (optional)" value={uploadTitle} onChange={(e) => setUploadTitle(e.target.value)} />
            <select className="input text-sm" value={uploadType} onChange={(e) => setUploadType(e.target.value)}>
              <option value="">Auto-detect type</option>
              {MEDIA_LIBRARY_FILE_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <input className="input text-sm" placeholder="Tags (comma-separated)" value={uploadTags} onChange={(e) => setUploadTags(e.target.value)} />
          <input ref={fileRef} type="file" className="text-sm" accept="image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx" onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)} />
          <button
            type="button"
            disabled={!uploadClientId || !selectedFile || uploadMutation.isPending}
            onClick={() => {
              if (selectedFile) uploadMutation.mutate(selectedFile);
            }}
            className="text-sm px-4 py-2 rounded-lg bg-brand-600 text-white disabled:opacity-50"
          >
            {uploadMutation.isPending ? "Uploading…" : "Upload file"}
          </button>
        </div>
      )}

      {isLoading && <LoadingState message="Loading media…" />}
      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load media"}
          onRetry={() => refetch()}
        />
      )}
      {!isLoading && !isError && items.length === 0 && (
        <EmptyState title="No media assets" description="Upload files to build your client media library." />
      )}

      {!isLoading && !isError && items.length > 0 && view === "grid" && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {items.map((a) => (
            <AssetGridCard key={a.id} asset={a} />
          ))}
        </div>
      )}

      {!isLoading && !isError && items.length > 0 && view === "table" && (
        <div className="card p-0 overflow-hidden">
          <div className="hidden md:grid grid-cols-[48px_1fr_1fr_0.8fr_0.6fr_1fr_0.5fr] gap-3 px-4 py-2 text-[10px] uppercase tracking-wide text-gray-400 font-medium border-b border-gray-100">
            <span />
            <span>Name</span>
            <span>Client</span>
            <span>Campaign</span>
            <span>Type</span>
            <span>Tags</span>
            <span className="text-right">Usage</span>
          </div>
          {items.map((a) => (
            <AssetTableRow key={a.id} asset={a} />
          ))}
        </div>
      )}
    </div>
  );
}
