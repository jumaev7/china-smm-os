"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Plus } from "lucide-react";
import toast from "react-hot-toast";
import {
  clientsApi,
  Client,
  communicationsApi,
  CommunicationChannel,
  CHANNEL_LABELS,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ContactDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();
  const qc = useQueryClient();
  const isNew = id === "new";

  const [form, setForm] = useState({
    name: "",
    client_id: "",
    company: "",
    role: "",
    phone: "",
    telegram: "",
    whatsapp: "",
    wechat: "",
    email: "",
    country: "",
    language: "",
    notes: "",
  });
  const [showNewThread, setShowNewThread] = useState(false);
  const [threadForm, setThreadForm] = useState({
    title: "",
    channel: "manual" as CommunicationChannel,
  });

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
    enabled: isNew,
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: contact, isLoading } = useQuery({
    queryKey: ["communication-contact", id],
    queryFn: () => communicationsApi.getContact(id).then((r) => r.data),
    enabled: !isNew,
  });

  const createContactMutation = useMutation({
    mutationFn: () =>
      communicationsApi.createContact({
        name: form.name.trim(),
        client_id: form.client_id || null,
        company: form.company || null,
        role: form.role || null,
        phone: form.phone || null,
        telegram: form.telegram || null,
        whatsapp: form.whatsapp || null,
        wechat: form.wechat || null,
        email: form.email || null,
        country: form.country || null,
        language: form.language || null,
        notes: form.notes || null,
      }).then((r) => r.data),
    onSuccess: (data) => {
      toast.success("Contact created");
      router.push(`/communications/contacts/${data.id}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create contact"),
  });

  const createThreadMutation = useMutation({
    mutationFn: () =>
      communicationsApi.createThread({
        contact_id: id,
        channel: threadForm.channel,
        title: threadForm.title.trim(),
        client_id: contact?.client_id || null,
      }).then((r) => r.data),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["communication-contact", id] });
      setShowNewThread(false);
      toast.success("Thread created");
      router.push(`/communications/threads/${data.id}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create thread"),
  });

  if (isNew) {
    return (
      <div className="p-6 max-w-lg mx-auto space-y-6">
        <Link href="/communications" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1">
          <ArrowLeft size={12} />
          Communications
        </Link>
        <h1 className="text-xl font-semibold text-gray-900">New contact</h1>
        <div className="card p-4 space-y-3">
          <input className="input text-sm w-full" placeholder="Name *" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="input text-sm w-full" value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })}>
            <option value="">Client (optional)</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
          <input className="input text-sm w-full" placeholder="Company" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
          <input className="input text-sm w-full" placeholder="Phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          <input className="input text-sm w-full" placeholder="Telegram" value={form.telegram} onChange={(e) => setForm({ ...form, telegram: e.target.value })} />
          <input className="input text-sm w-full" placeholder="WhatsApp" value={form.whatsapp} onChange={(e) => setForm({ ...form, whatsapp: e.target.value })} />
          <input className="input text-sm w-full" placeholder="WeChat" value={form.wechat} onChange={(e) => setForm({ ...form, wechat: e.target.value })} />
          <input className="input text-sm w-full" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <textarea className="input text-sm w-full min-h-[60px]" placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button
            type="button"
            className="btn-primary w-full text-sm"
            disabled={!form.name.trim() || createContactMutation.isPending}
            onClick={() => createContactMutation.mutate()}
          >
            {createContactMutation.isPending ? <Loader2 size={14} className="animate-spin mx-auto" /> : "Create contact"}
          </button>
        </div>
      </div>
    );
  }

  if (isLoading || !contact) {
    return <div className="p-6 text-sm text-gray-500">Loading contact…</div>;
  }

  const threads = contact.threads ?? [];

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <Link href="/communications" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1">
        <ArrowLeft size={12} />
        Communications
      </Link>

      <div>
        <h1 className="text-xl font-semibold text-gray-900">{contact.name}</h1>
        {contact.company && <p className="text-sm text-gray-500">{contact.company}</p>}
      </div>

      <div className="card p-4 grid sm:grid-cols-2 gap-3 text-sm">
        {contact.client_name && (
          <div><p className="text-[10px] uppercase text-gray-400">Client</p><p>{contact.client_name}</p></div>
        )}
        {contact.lead_name && (
          <div><p className="text-[10px] uppercase text-gray-400">CRM Lead</p><p>{contact.lead_name}</p></div>
        )}
        {contact.partner_name && (
          <div><p className="text-[10px] uppercase text-gray-400">Partner</p><p>{contact.partner_name}</p></div>
        )}
        {contact.phone && <div><p className="text-[10px] uppercase text-gray-400">Phone</p><p>{contact.phone}</p></div>}
        {contact.telegram && <div><p className="text-[10px] uppercase text-gray-400">Telegram</p><p>{contact.telegram}</p></div>}
        {contact.whatsapp && <div><p className="text-[10px] uppercase text-gray-400">WhatsApp</p><p>{contact.whatsapp}</p></div>}
        {contact.wechat && <div><p className="text-[10px] uppercase text-gray-400">WeChat</p><p>{contact.wechat}</p></div>}
        {contact.email && <div><p className="text-[10px] uppercase text-gray-400">Email</p><p>{contact.email}</p></div>}
        {contact.country && <div><p className="text-[10px] uppercase text-gray-400">Country</p><p>{contact.country}</p></div>}
        {contact.language && <div><p className="text-[10px] uppercase text-gray-400">Language</p><p>{contact.language}</p></div>}
        {contact.notes && (
          <div className="sm:col-span-2"><p className="text-[10px] uppercase text-gray-400">Notes</p><p className="whitespace-pre-wrap">{contact.notes}</p></div>
        )}
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">Threads ({threads.length})</h2>
          <button
            type="button"
            className="text-xs px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 flex items-center gap-1"
            onClick={() => setShowNewThread((v) => !v)}
          >
            <Plus size={12} />
            New thread
          </button>
        </div>

        {showNewThread && (
          <div className="card p-3 space-y-2">
            <input
              className="input text-sm w-full"
              placeholder="Thread title *"
              value={threadForm.title}
              onChange={(e) => setThreadForm({ ...threadForm, title: e.target.value })}
            />
            <select
              className="input text-sm w-full"
              value={threadForm.channel}
              onChange={(e) => setThreadForm({ ...threadForm, channel: e.target.value as CommunicationChannel })}
            >
              {(["telegram", "whatsapp", "wechat", "email", "manual"] as CommunicationChannel[]).map((ch) => (
                <option key={ch} value={ch}>{CHANNEL_LABELS[ch]}</option>
              ))}
            </select>
            <button
              type="button"
              className="btn-primary text-sm w-full"
              disabled={!threadForm.title.trim() || createThreadMutation.isPending}
              onClick={() => createThreadMutation.mutate()}
            >
              Create thread
            </button>
          </div>
        )}

        {threads.length === 0 ? (
          <p className="text-sm text-gray-500">No threads yet.</p>
        ) : (
          <ul className="space-y-2">
            {threads.map((t) => (
              <li key={t.id}>
                <Link
                  href={`/communications/threads/${t.id}`}
                  className={cn("block card p-3 hover:ring-1 hover:ring-brand-200")}
                >
                  <p className="text-sm font-medium text-gray-900">{t.title}</p>
                  <p className="text-xs text-gray-500 capitalize">{CHANNEL_LABELS[t.channel]} · {t.status}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
