"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { clientsApi, Client } from "@/lib/api";
import { X } from "lucide-react";
import toast from "react-hot-toast";

const CATEGORIES = [
  ["restaurant","Restaurant"],["retail","Retail"],["beauty","Beauty"],
  ["construction","Construction"],["logistics","Logistics"],["technology","Technology"],
  ["education","Education"],["healthcare","Healthcare"],["real_estate","Real Estate"],["other","Other"],
];
const STYLES = ["professional","casual","luxury","educational","promotional"];
const LANGUAGES = [["zh","Chinese"],["en","English"],["ru","Russian"],["ko","Korean"],["ja","Japanese"]];

interface Props {
  client: Client | null;
  onClose: () => void;
  onSaved: () => void;
}

export function ClientFormModal({ client, onClose, onSaved }: Props) {
  const [form, setForm] = useState({
    company_name: client?.company_name ?? "",
    source_language: client?.source_language ?? "zh",
    business_category: client?.business_category ?? "other",
    content_style: client?.content_style ?? "professional",
    notes: client?.notes ?? "",
    telegram_group_id: client?.telegram_group_id ?? "",
    telegram_group_title: client?.telegram_group_title ?? "",
    telegram_workflow_mode: client?.telegram_workflow_mode ?? "auto_create_from_media",
  });

  const mutation = useMutation({
    mutationFn: () =>
      client
        ? clientsApi.update(client.id, {
            ...form,
            telegram_group_id: form.telegram_group_id.trim() || null,
            telegram_group_title: form.telegram_group_title.trim() || null,
            telegram_workflow_mode: form.telegram_workflow_mode,
          })
        : clientsApi.create(form),
    onSuccess: () => {
      toast.success(client ? "Client updated" : "Client added");
      onSaved();
    },
    onError: () => toast.error("Failed to save"),
  });

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div
      data-app-modal
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
    >
      <div className="card w-full max-w-md p-6 shadow-xl">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-gray-900">
            {client ? "Edit client" : "Add new client"}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="label">Company name *</label>
            <input className="input" value={form.company_name} onChange={set("company_name")} placeholder="e.g. Golden Dragon Restaurant" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Source language</label>
              <select className="input" value={form.source_language} onChange={set("source_language")}>
                {LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Business category</label>
              <select className="input" value={form.business_category} onChange={set("business_category")}>
                {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="label">Content style</label>
            <select className="input" value={form.content_style} onChange={set("content_style")}>
              {STYLES.map((s) => <option key={s} value={s} className="capitalize">{s.charAt(0).toUpperCase()+s.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Notes (optional)</label>
            <textarea className="input resize-none" rows={2} value={form.notes} onChange={set("notes")} placeholder="Any context about this client…" />
          </div>
          <div className="border-t border-gray-100 pt-4 space-y-3">
            <p className="text-xs font-medium text-gray-700">Telegram group mapping</p>
            <p className="text-[11px] text-gray-500">
              Link a group chat so incoming media attaches to this client. Use the numeric chat ID from Telegram (often negative for groups).
            </p>
            <div>
              <label className="label">Telegram Group ID</label>
              <input
                className="input font-mono text-sm"
                value={form.telegram_group_id}
                onChange={set("telegram_group_id")}
                placeholder="e.g. -1001234567890"
              />
            </div>
            <div>
              <label className="label">Telegram Group Title</label>
              <input
                className="input"
                value={form.telegram_group_title}
                onChange={set("telegram_group_title")}
                placeholder="e.g. Client SMM Group"
              />
            </div>
            <div>
              <label className="label">Telegram workflow mode</label>
              <select
                className="input"
                value={form.telegram_workflow_mode}
                onChange={set("telegram_workflow_mode")}
              >
                <option value="auto_create_from_media">Auto — create content from each media</option>
                <option value="admin_controlled_buffer">Buffer — wait for admin instruction</option>
              </select>
              <p className="text-[11px] text-gray-500 mt-1">
                Buffer mode stores client photos/videos until admin selects materials via @bot.
              </p>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            onClick={() => mutation.mutate()}
            disabled={!form.company_name || mutation.isPending}
          >
            {mutation.isPending ? "Saving…" : client ? "Save changes" : "Add client"}
          </button>
        </div>
      </div>
    </div>
  );
}
