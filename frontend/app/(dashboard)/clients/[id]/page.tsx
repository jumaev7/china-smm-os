"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { clientsApi, contentApi, normalizeList, type ContentStatus } from "@/lib/api";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { ChevronLeft, Plus, Globe, Tag, Pencil, CheckCheck, Trash2 } from "lucide-react";
import { useState } from "react";
import { ClientFormModal } from "@/components/clients/ClientFormModal";
import { ClientBrandProfileForm } from "@/components/clients/ClientBrandProfileForm";
import { ClientTelegramSettingsForm } from "@/components/clients/ClientTelegramSettingsForm";
import { ClientBillingSection } from "@/components/clients/ClientBillingSection";
import { ClientKnowledgeBaseSection } from "@/components/clients/ClientKnowledgeBaseSection";
import { STATUS_CONFIG, PLATFORM_CONFIG, CATEGORY_LABELS, LANGUAGE_LABELS, cn } from "@/lib/utils";
import toast from "react-hot-toast";

export default function ClientDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);

  const { data: client, isLoading } = useQuery({
    queryKey: ["client", id],
    queryFn: () => clientsApi.get(id).then((r) => r.data),
  });

  const { data: contentData } = useQuery({
    queryKey: ["content", "client", id],
    queryFn: () => contentApi.list({ client_id: id, limit: 50 }).then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: () => clientsApi.delete(id),
    onSuccess: () => { router.push("/clients"); toast.success("Client deleted"); },
    onError: () => toast.error("Failed to delete"),
  });

  const approveMutation = useMutation({
    mutationFn: (contentId: string) => contentApi.approve(contentId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["content", "client", id] }); toast.success("Approved"); },
  });

  if (isLoading || !client) return <div className="p-8 text-gray-400 text-sm">Loading…</div>;

  const items = normalizeList(contentData);
  const counts = {
    draft: items.filter((i) => i.status === "draft").length,
    ready: items.filter((i) => i.status === "ready").length,
    approved: items.filter((i) => i.status === "approved").length,
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Back */}
      <Link href="/clients" className="inline-flex items-center gap-1 text-sm text-gray-400 hover:text-gray-700 mb-4 transition-colors">
        <ChevronLeft size={14} /> Back to clients
      </Link>

      {/* Header card */}
      <div className="card p-5 mb-5">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">{client.company_name}</h1>
            <div className="flex flex-wrap gap-3 mt-2 text-sm text-gray-500">
              <span className="flex items-center gap-1">
                <Globe size={13} /> {LANGUAGE_LABELS[client.source_language] ?? client.source_language}
              </span>
              <span className="flex items-center gap-1">
                <Tag size={13} /> {CATEGORY_LABELS[client.business_category] ?? client.business_category}
              </span>
              <span className="capitalize">{client.content_style} style</span>
              <span className={cn(
                "rounded-full px-2 py-0.5 text-xs font-medium",
                client.status === "active" ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"
              )}>
                {client.status}
              </span>
            </div>
            {client.notes && (
              <p className="mt-2 text-sm text-gray-500 max-w-xl">{client.notes}</p>
            )}
          </div>
          <div className="flex gap-2">
            <button className="btn-secondary text-xs" onClick={() => setShowEdit(true)}>
              <Pencil size={13} /> Edit
            </button>
            <button
              className="btn-danger text-xs"
              onClick={() => { if (confirm(`Delete ${client.company_name} and all their content?`)) deleteMutation.mutate(); }}
            >
              <Trash2 size={13} /> Delete
            </button>
          </div>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-gray-100">
          {(["draft", "ready", "approved"] as const).map((s) => {
            const cfg = STATUS_CONFIG[s];
            return (
              <div key={s} className="text-center">
                <div className="text-2xl font-semibold text-gray-900">{counts[s]}</div>
                <div className={cn("text-xs mt-0.5 inline-flex items-center gap-1", cfg.color.split(" ")[1])}>
                  <span className={cn("w-1.5 h-1.5 rounded-full", cfg.dot)} />{cfg.label}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <ClientTelegramSettingsForm
        client={client}
        onSaved={() => qc.invalidateQueries({ queryKey: ["client", id] })}
      />

      <ClientBillingSection clientId={id} />

      <ClientBrandProfileForm
        client={client}
        onSaved={() => qc.invalidateQueries({ queryKey: ["client", id] })}
      />

      <ClientKnowledgeBaseSection clientId={id} />

      {/* Content list */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">Content items ({items.length})</h2>
        <Link href="/content" className="btn-primary text-xs">
          <Plus size={13} /> New content
        </Link>
      </div>

      {items.length === 0 ? (
        <div className="card p-8 text-center text-gray-400 text-sm">
          No content yet for this client.
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Status</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Platforms</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Caption (RU)</th>
                <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Created</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((item) => {
                const status = STATUS_CONFIG[item.status as ContentStatus];
                return (
                  <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className={cn("status-badge", status.color)}>
                        <span className={cn("w-1.5 h-1.5 rounded-full", status.dot)} />
                        {status.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1 flex-wrap">
                        {item.platforms.map((p: string) => (
                          <span key={p} className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", PLATFORM_CONFIG[p]?.color)}>
                            {PLATFORM_CONFIG[p]?.label}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600 max-w-xs">
                      <p className="truncate text-xs">{item.caption_short_ru || <span className="text-gray-300 italic">No caption</span>}</p>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {new Date(item.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1 justify-end">
                        <Link href={`/content/${item.id}`} className="btn-secondary text-xs py-1">View</Link>
                        {item.status !== "approved" && (
                          <button className="btn-primary text-xs py-1" onClick={() => approveMutation.mutate(item.id)}>
                            <CheckCheck size={12} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {showEdit && (
        <ClientFormModal
          client={client}
          onClose={() => setShowEdit(false)}
          onSaved={() => {
            setShowEdit(false);
            qc.invalidateQueries({ queryKey: ["client", id] });
            qc.invalidateQueries({ queryKey: ["clients"] });
          }}
        />
      )}
    </div>
  );
}
