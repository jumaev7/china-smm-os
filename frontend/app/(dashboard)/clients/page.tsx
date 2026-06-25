"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { clientsApi, Client, normalizeList } from "@/lib/api";
import { CATEGORY_LABELS, LANGUAGE_LABELS } from "@/lib/utils";
import { Plus, Search, Globe, Tag, Trash2, Pencil, MessageCircle } from "lucide-react";
import toast from "react-hot-toast";
import { ClientFormModal } from "@/components/clients/ClientFormModal";
import Link from "next/link";

export default function ClientsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Client | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => clientsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["clients"] }); toast.success("Client deleted"); },
    onError: () => toast.error("Failed to delete"),
  });

  const clientList = normalizeList<Client>(data);
  const clients = clientList.filter((c) =>
    c.company_name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Clients</h1>
          <p className="text-sm text-gray-500 mt-0.5">{(!Array.isArray(data) ? data?.total : undefined) ?? clientList.length} companies</p>
        </div>
        <button className="btn-primary" onClick={() => { setEditing(null); setShowForm(true); }}>
          <Plus size={15} /> Add client
        </button>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          className="input pl-9"
          placeholder="Search by company name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="card p-8 text-center text-gray-400 text-sm">Loading…</div>
      ) : clients.length === 0 ? (
        <div className="card p-12 text-center">
          <p className="text-gray-400 text-sm">No clients yet. Add your first one.</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left px-4 py-3 font-medium text-gray-600">Company</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Category</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Language</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Style</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Telegram</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {clients.map((c) => (
                <tr key={c.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    <Link href={`/clients/${c.id}`} className="hover:text-brand-600 transition-colors">
                      {c.company_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    <span className="inline-flex items-center gap-1">
                      <Tag size={12} className="text-gray-400" />
                      {CATEGORY_LABELS[c.business_category] ?? c.business_category}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    <span className="inline-flex items-center gap-1">
                      <Globe size={12} className="text-gray-400" />
                      {LANGUAGE_LABELS[c.source_language] ?? c.source_language}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 capitalize">{c.content_style}</td>
                  <td className="px-4 py-3">
                    {c.telegram_group_id ? (
                      <span className="inline-flex items-center gap-1 text-xs text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full">
                        <MessageCircle size={11} />
                        {c.telegram_group_title || "Linked"}
                      </span>
                    ) : c.company_name.startsWith("Telegram Group:") ? (
                      <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">Placeholder</span>
                    ) : (
                      <span className="text-xs text-gray-400">Not linked</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                      c.status === "active" ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {c.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 justify-end">
                      <button
                        onClick={() => { setEditing(c); setShowForm(true); }}
                        className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => { if (confirm(`Delete ${c.company_name}?`)) deleteMutation.mutate(c.id); }}
                        className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <ClientFormModal
          client={editing}
          onClose={() => setShowForm(false)}
          onSaved={() => { setShowForm(false); qc.invalidateQueries({ queryKey: ["clients"] }); }}
        />
      )}
    </div>
  );
}
