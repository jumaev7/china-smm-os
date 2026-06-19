"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { ArrowLeft, ImageIcon, Loader2 } from "lucide-react";
import { mediaLibraryApi, MediaAssetAiLabels } from "@/lib/api";

function LabelSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-[10px] uppercase text-gray-400 mb-1">{title}</p>
      <div className="flex flex-wrap gap-1">
        {items.map((t) => (
          <span key={t} className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-800 border border-indigo-100">
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function MediaAssetDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const { data: asset, isLoading } = useQuery({
    queryKey: ["media-asset", id],
    queryFn: () => mediaLibraryApi.get(id).then((r) => r.data),
  });

  if (isLoading || !asset) {
    return (
      <div className="p-6 flex items-center justify-center gap-2 text-sm text-gray-400">
        <Loader2 size={16} className="animate-spin" />
        Loading media…
      </div>
    );
  }

  const ai = (asset.ai_labels_json ?? {}) as MediaAssetAiLabels;
  const preview = asset.thumbnail_url || asset.url;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <Link href="/media-library" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Media library
        </Link>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <ImageIcon size={20} className="text-indigo-600" />
          {asset.title}
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          {asset.client_name}
          {asset.campaign_name ? ` · ${asset.campaign_name}` : ""}
        </p>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4">
          {preview && asset.file_type !== "document" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview} alt="" className="w-full rounded-lg max-h-80 object-contain bg-gray-50" />
          ) : (
            <div className="h-48 flex items-center justify-center bg-gray-100 rounded-lg text-gray-500 capitalize">
              {asset.file_type} — {asset.original_filename}
            </div>
          )}
          {asset.url && asset.file_type === "document" && (
            <a href={asset.url} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-700 mt-2 inline-block">
              Open document
            </a>
          )}
        </div>

        <div className="card p-4 space-y-3 text-sm">
          <div>
            <p className="text-[10px] uppercase text-gray-400">Usage</p>
            <p className="text-gray-900 font-medium">Used in {asset.usage_count} content items</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-[10px] uppercase text-gray-400">Type</p>
              <p className="text-gray-900 capitalize">{asset.file_type}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase text-gray-400">Filename</p>
              <p className="text-gray-900 truncate">{asset.original_filename}</p>
            </div>
          </div>
          {asset.description && (
            <div>
              <p className="text-[10px] uppercase text-gray-400">Description</p>
              <p className="text-gray-700">{asset.description}</p>
            </div>
          )}
          {(asset.tags_json ?? []).length > 0 && (
            <div>
              <p className="text-[10px] uppercase text-gray-400 mb-1">Tags</p>
              <div className="flex flex-wrap gap-1">
                {(asset.tags_json ?? []).map((t) => (
                  <span key={t} className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">{t}</span>
                ))}
              </div>
            </div>
          )}
          <p className="text-[10px] text-gray-400">
            Uploaded {format(parseISO(asset.created_at), "MMM d, yyyy HH:mm")}
            {asset.uploaded_by ? ` · ${asset.uploaded_by}` : ""}
          </p>
        </div>
      </div>

      <div className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900">
          AI tags
          {ai.source && <span className="text-xs font-normal text-gray-400 ml-2">({ai.source})</span>}
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <LabelSection title="Objects" items={ai.objects ?? []} />
          <LabelSection title="Products" items={ai.products ?? []} />
          <LabelSection title="Equipment" items={ai.equipment ?? []} />
          <LabelSection title="Industries" items={ai.industries ?? []} />
        </div>
        {!ai.objects?.length && !ai.products?.length && !ai.equipment?.length && !ai.industries?.length && (
          <p className="text-xs text-gray-400">No AI tags generated yet.</p>
        )}
      </div>

      <div className="card p-4">
        <p className="text-sm font-semibold text-gray-900 mb-3">Related content</p>
        {(asset.related_content ?? []).length === 0 ? (
          <p className="text-xs text-gray-400">Not used in any content items yet.</p>
        ) : (
          <ul className="space-y-2">
            {(asset.related_content ?? []).map((item) => (
              <li key={item.id} className="flex items-center justify-between gap-2 text-sm border-b border-gray-50 pb-2">
                <Link href={`/content/${item.id}`} className="text-brand-700 hover:underline truncate">
                  {item.caption_preview || "Content item"}
                </Link>
                <span className="text-[10px] text-gray-500 capitalize shrink-0">{item.status}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
